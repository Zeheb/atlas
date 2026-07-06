"""Machine-readable evaluation reports and milestone comparison.

A Report captures per-case results across the four dimensions plus provenance
(milestone, model, git commit), and computes per-dimension aggregates. compare()
diffs two reports so we can answer, after each milestone: did the dimensions
improve, did coverage grow, and did anything regress?
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

Status = Literal["active", "pending"]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    status: Status
    refused: bool | None = None
    correctness_pass: bool | None = None
    correctness_reasons: tuple[str, ...] = ()
    grounding_pass: bool | None = None
    grounding_reasons: tuple[str, ...] = ()
    reasoning_quality: int | None = None
    usefulness: int | None = None
    # §12.6 amendment 3: judged completeness against the available evidence,
    # plus the free deterministic proxy (distinct evidence documents cited).
    evidence_use: int | None = None
    distinct_docs_cited: int | None = None
    judge_notes: str = ""
    error: str | None = None


@dataclass(frozen=True)
class Report:
    milestone: str
    created_at: str
    model: str
    capabilities: tuple[str, ...]
    results: tuple[CaseResult, ...]
    git_commit: str | None = None
    # Judge model recorded separately from the reasoning model: the instrument
    # is pinned independently of the system under test (§12.6 amendment 1).
    judge_model: str | None = None
    # Free-tier operation: LLM-call cache hit/miss counts for this run, when
    # caching was enabled. Optional and additive — absent in older reports,
    # which from_dict() reads as None, so report compatibility is preserved.
    cache_hits: int | None = None
    cache_misses: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone": self.milestone,
            "created_at": self.created_at,
            "model": self.model,
            "judge_model": self.judge_model,
            "git_commit": self.git_commit,
            "capabilities": list(self.capabilities),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "aggregates": aggregate(self.results),
            "results": [asdict(r) for r in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Report":
        results = tuple(
            CaseResult(
                case_id=r["case_id"], category=r["category"], status=r["status"],
                refused=r.get("refused"),
                correctness_pass=r.get("correctness_pass"),
                correctness_reasons=tuple(r.get("correctness_reasons", ())),
                grounding_pass=r.get("grounding_pass"),
                grounding_reasons=tuple(r.get("grounding_reasons", ())),
                reasoning_quality=r.get("reasoning_quality"),
                usefulness=r.get("usefulness"),
                evidence_use=r.get("evidence_use"),
                distinct_docs_cited=r.get("distinct_docs_cited"),
                judge_notes=r.get("judge_notes", ""),
                error=r.get("error"),
            )
            for r in d["results"]
        )
        return cls(
            milestone=d["milestone"], created_at=d["created_at"], model=d["model"],
            capabilities=tuple(d.get("capabilities", ())), results=results,
            git_commit=d.get("git_commit"), judge_model=d.get("judge_model"),
            cache_hits=d.get("cache_hits"), cache_misses=d.get("cache_misses"),
        )

    @classmethod
    def from_json(cls, text: str) -> "Report":
        return cls.from_dict(json.loads(text))


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def aggregate(results: tuple[CaseResult, ...]) -> dict[str, Any]:
    """Per-dimension aggregates. Pending cases count only toward coverage."""
    active = [r for r in results if r.status == "active"]
    correctness = [r.correctness_pass for r in active if r.correctness_pass is not None]
    grounding = [r.grounding_pass for r in active if r.grounding_pass is not None]
    quality = [r.reasoning_quality for r in active if r.reasoning_quality is not None]
    useful = [r.usefulness for r in active if r.usefulness is not None]
    ev_use = [r.evidence_use for r in active if r.evidence_use is not None]
    docs = [r.distinct_docs_cited for r in active if r.distinct_docs_cited is not None]
    return {
        "total_cases": len(results),
        "active_cases": len(active),
        "coverage": round(len(active) / len(results), 3) if results else 0.0,
        "correctness_pass_rate": _mean([1.0 if p else 0.0 for p in correctness]),
        "grounding_pass_rate": _mean([1.0 if p else 0.0 for p in grounding]),
        "mean_reasoning_quality": _mean([float(q) for q in quality]),
        "mean_usefulness": _mean([float(u) for u in useful]),
        "mean_evidence_use": _mean([float(e) for e in ev_use]),
        "mean_distinct_docs_cited": _mean([float(d) for d in docs]),
        "errors": sum(1 for r in active if r.error),
    }


def compare(baseline: Report, candidate: Report) -> dict[str, Any]:
    """Diff two reports: per-dimension deltas, regressions, newly-active cases."""
    base_agg, cand_agg = aggregate(baseline.results), aggregate(candidate.results)
    dims = [
        "coverage", "correctness_pass_rate", "grounding_pass_rate",
        "mean_reasoning_quality", "mean_usefulness", "mean_evidence_use",
    ]
    deltas: dict[str, Any] = {}
    for d in dims:
        b, c = base_agg.get(d), cand_agg.get(d)
        deltas[d] = {
            "baseline": b, "candidate": c,
            "delta": round(c - b, 3) if isinstance(b, (int, float)) and isinstance(c, (int, float)) else None,
        }

    base_by_id = {r.case_id: r for r in baseline.results}
    regressions: list[str] = []
    newly_active: list[str] = []
    for r in candidate.results:
        b = base_by_id.get(r.case_id)
        if b is None:
            continue
        if b.status == "pending" and r.status == "active":
            newly_active.append(r.case_id)
        if b.status == "active" and r.status == "active":
            if b.correctness_pass and not r.correctness_pass:
                regressions.append(f"{r.case_id}: correctness")
            if b.grounding_pass and not r.grounding_pass:
                regressions.append(f"{r.case_id}: grounding")

    return {
        "baseline": baseline.milestone,
        "candidate": candidate.milestone,
        "dimensions": deltas,
        "regressions": regressions,
        "newly_active": newly_active,
    }
