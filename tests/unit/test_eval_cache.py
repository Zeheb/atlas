"""LLM-response cache for free-tier evaluation (harness redesign).

Verifies the cache sits purely at the LLMClient boundary: identical
(model, system, user) triples never re-invoke the wrapped client, differing
inputs never collide, and the cache persists across separate EvalCache
instances pointed at the same file (simulating separate `atlas eval run`
invocations). No network, no reasoning code involved.
"""
from __future__ import annotations

import json

from atlas.eval.cache import CACHE_VERSION, CachingLLMClient, EvalCache
from atlas.reasoning.llm import FakeLLMClient


def test_second_identical_call_is_a_cache_hit_and_skips_inner_client(tmp_path) -> None:
    cache = EvalCache(tmp_path / "cache.json")
    inner = FakeLLMClient(response="answer text")
    client = CachingLLMClient(inner, cache, model="claude-sonnet-5")

    first = client.complete(system="SYS", user="USER: q1")
    second = client.complete(system="SYS", user="USER: q1")

    assert first == second == "answer text"
    assert len(inner.calls) == 1  # only the first call reached the inner client
    assert cache.hits == 1
    assert cache.misses == 1


def test_different_user_prompt_is_not_a_cache_hit(tmp_path) -> None:
    cache = EvalCache(tmp_path / "cache.json")
    inner = FakeLLMClient(response="answer text")
    client = CachingLLMClient(inner, cache, model="claude-sonnet-5")

    client.complete(system="SYS", user="USER: q1")
    client.complete(system="SYS", user="USER: q2")

    assert len(inner.calls) == 2
    assert cache.misses == 2
    assert cache.hits == 0


def test_different_model_is_not_a_cache_hit_even_with_same_prompts(tmp_path) -> None:
    # A different model could legitimately answer differently, so the model
    # must be part of the functional key, not just a label.
    cache = EvalCache(tmp_path / "cache.json")
    inner = FakeLLMClient(response="answer text")
    client_a = CachingLLMClient(inner, cache, model="model-a")
    client_b = CachingLLMClient(inner, cache, model="model-b")

    client_a.complete(system="SYS", user="USER: q1")
    client_b.complete(system="SYS", user="USER: q1")

    assert len(inner.calls) == 2
    assert cache.misses == 2


def test_different_system_prompt_is_not_a_cache_hit(tmp_path) -> None:
    cache = EvalCache(tmp_path / "cache.json")
    inner = FakeLLMClient(response="answer text")
    client = CachingLLMClient(inner, cache, model="claude-sonnet-5")

    client.complete(system="SYS-A", user="USER: q1")
    client.complete(system="SYS-B", user="USER: q1")

    assert len(inner.calls) == 2


def test_cache_persists_across_separate_instances_sharing_a_path(tmp_path) -> None:
    path = tmp_path / "cache.json"

    cache1 = EvalCache(path)
    inner1 = FakeLLMClient(response="cached answer")
    CachingLLMClient(inner1, cache1, model="m").complete(system="SYS", user="USER: q1")
    cache1.save()

    # A fresh EvalCache instance, as a new `atlas eval run` process would
    # construct, reading the same path.
    cache2 = EvalCache(path)
    inner2 = FakeLLMClient(response="should not be used")
    result = CachingLLMClient(inner2, cache2, model="m").complete(system="SYS", user="USER: q1")

    assert result == "cached answer"
    assert len(inner2.calls) == 0
    assert cache2.hits == 1


def test_cache_entry_records_readable_question_label(tmp_path) -> None:
    cache = EvalCache(tmp_path / "cache.json")
    inner = FakeLLMClient(response="ans")
    client = CachingLLMClient(inner, cache, model="m")
    client.complete(system="SYS", user="Some context.\nQUESTION: How stable are margins?")
    cache.save()

    raw = (tmp_path / "cache.json").read_text(encoding="utf-8")
    assert "How stable are margins?" in raw


def test_save_creates_parent_directories(tmp_path) -> None:
    nested = tmp_path / "nested" / "dir" / "cache.json"
    cache = EvalCache(nested)
    CachingLLMClient(FakeLLMClient(response="x"), cache, model="m").complete(
        system="SYS", user="USER"
    )
    cache.save()
    assert nested.exists()


def test_missing_cache_file_starts_empty(tmp_path) -> None:
    cache = EvalCache(tmp_path / "does-not-exist.json")
    assert cache.get("anything") is None
    assert cache.misses == 1


def test_different_fingerprint_is_not_a_cache_hit(tmp_path) -> None:
    # A generation-parameter drift (temperature/max_tokens) isn't visible in
    # (system, user) text alone, so it must be part of the key or it could
    # silently replay a response generated under different settings.
    cache = EvalCache(tmp_path / "cache.json")
    inner = FakeLLMClient(response="answer text")
    client_a = CachingLLMClient(inner, cache, model="m", fingerprint="t=0.0:m=4096")
    client_b = CachingLLMClient(inner, cache, model="m", fingerprint="t=0.7:m=4096")

    client_a.complete(system="SYS", user="USER: q1")
    client_b.complete(system="SYS", user="USER: q1")

    assert len(inner.calls) == 2


def test_same_fingerprint_still_hits(tmp_path) -> None:
    cache = EvalCache(tmp_path / "cache.json")
    inner = FakeLLMClient(response="answer text")
    client = CachingLLMClient(inner, cache, model="m", fingerprint="t=0.0:m=4096")

    client.complete(system="SYS", user="USER: q1")
    client.complete(system="SYS", user="USER: q1")

    assert len(inner.calls) == 1


def test_write_through_persists_immediately_without_explicit_save(tmp_path) -> None:
    # A mid-run interrupt shouldn't lose entries recorded before it: put()
    # must persist immediately, not only when save() is called at the end.
    path = tmp_path / "cache.json"
    cache = EvalCache(path)
    CachingLLMClient(FakeLLMClient(response="x"), cache, model="m").complete(
        system="SYS", user="USER"
    )
    # No explicit cache.save() call here.
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["entries"]  # already written


def test_mismatched_cache_version_is_treated_as_cold(tmp_path) -> None:
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({
        "cache_version": CACHE_VERSION + 1,
        "entries": {"some::key": {"response": "stale-schema-response"}},
    }), encoding="utf-8")

    cache = EvalCache(path)
    assert cache.get("some::key") is None  # not trusted, not returned
    assert cache.misses == 1


def test_missing_cache_version_field_is_treated_as_cold(tmp_path) -> None:
    # A foreign or pre-versioning file shouldn't be interpreted as compatible.
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"entries": {"some::key": {"response": "x"}}}), encoding="utf-8")

    cache = EvalCache(path)
    assert cache.get("some::key") is None
    assert cache.misses == 1
