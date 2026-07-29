"""Tier 1 assertion storage.

Assertions are the persisted form of what an analyzer extracted from one
evidence document. Tier 0 (evidence, user judgments) is canonical; this
layer is a rebuildable cache derived from it, and Tier 2 (facts, profiles,
metrics) is a projection of this layer.
"""
