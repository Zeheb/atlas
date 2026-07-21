"""Benchmark subsystem (M1.8.5 / ADR-0005).

Atlas's evaluation BENCHMARK — the case suite itself — as a first-class
concern alongside Retrieval (``atlas.reasoning``) and Evaluation
(``atlas.eval``), not a sub-concern of either. M1.8 (ADR-0004) built the
machinery to measure retrieval; this package measures whether the *benchmark*
used to drive that machinery is itself adequate — which planner intents and
rules it exercises, which retrieval scenarios it covers, how skewed its
distribution is, and whether its claims about the corpus are actually true.

Depends on ``atlas.reasoning`` (planner, plan, text) and ``atlas.knowledge``
(KnowledgeBase) to do its analysis; nothing in ``atlas.eval`` depends on this
package except by import at the CLI boundary, so evaluation keeps working
if benchmark tooling is absent or fails.

Adds no retrieval heuristics and changes no reasoning/retrieval behavior —
this package only reads and describes the benchmark, it never influences
what `atlas ask`/`atlas eval run` actually do.
"""
from __future__ import annotations
