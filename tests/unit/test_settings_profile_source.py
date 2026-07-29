"""``profile_source`` — which tier a profile is assembled from (M3, #24).

The setting shipped dark in M3 with the default on "analyzers", so the
assertion path could be exercised without carrying any real work. M4 flipped
it, once the equivalence gate was green in both variants.

The guarantee worth pinning is now the reverse of what it was: profiles come
from the store by default, and the one word that reverts that is here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas.config.settings import Settings


def test_default_is_assertions() -> None:
    """Flipped in M4 (#35), once the equivalence gate was green in both
    variants and the order-dependence it exposed (#33) was fixed.

    Rollback is this one word, and the analyzer path stays importable and
    tested until M10 -- flipping back must not mean recovering deleted code.
    """
    assert Settings(_env_file=None).profile_source == "assertions"


@pytest.mark.parametrize("value", ["analyzers", "assertions"])
def test_both_values_parse(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ATLAS_PROFILE_SOURCE", value)

    assert Settings(_env_file=None).profile_source == value


def test_an_unknown_source_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo must fail at construction, not silently select a default.

    Falling back would mean a run the operator believed was reading the store
    was in fact re-running analyzers, and the profiles would agree, which is
    the worst possible way to learn nothing.
    """
    monkeypatch.setenv("ATLAS_PROFILE_SOURCE", "assertion")  # missing the s

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_the_setting_does_not_disturb_the_rest_of_the_config() -> None:
    """Adding a field must not change any other default."""
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.repository_base_path.name == "repositories"
