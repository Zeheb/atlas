"""Atlas evaluation harness.

Measures the reasoning subsystem against the V2.1 Product Specification (§8).
Completely orthogonal to reasoning: it consumes reasoning's public API to run
the system under test and scores the output along four independent dimensions —
correctness, grounding, reasoning quality, investor usefulness. It never imports
reasoning internals and adds no analytic capability.

The suite is the full §8.6 acceptance-test set encoded as data; each case
declares the capabilities it needs, so a milestone that lacks them marks the
case *pending* rather than failing it. As milestones land, more of the spec
activates — giving both per-dimension scores and a coverage metric to answer,
after each milestone: "did Atlas become a better investment analyst?"
"""
