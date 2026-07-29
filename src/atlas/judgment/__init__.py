"""Tier 0 user judgments.

A ``Judgment`` is what a human concluded, recorded as a fact about the human
rather than about the company. Tier 0 is canonical and is never regenerated:
a rebuild rewrites assertions and profiles, and must leave this layer
untouched.

Deliberately separate from ``research/memory.py``'s ``Thesis``, which stores
what the *model* synthesized. That module's own docstring argues a derived
artifact and a judgment cannot share a store; a human judgment is the same
argument one tier further down.
"""
