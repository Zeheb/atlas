"""Helpers shared between the unit and integration variants of a test.

Per D1: a test whose only home is ``tests/integration/`` never runs in CI,
because CI deselects that marker. Invariants that need a real CI gate are
therefore written once here and exercised twice -- against synthetic inputs
in ``tests/unit/`` on every push, and against the golden corpus in
``tests/integration/`` before merge.
"""
