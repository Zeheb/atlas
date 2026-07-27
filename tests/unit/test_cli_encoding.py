"""CLI output encoding: never crash on non-ASCII (₹, €, ✓, CJK, ...).

Windows consoles default to cp1252, which can't encode the characters that show
up in real answers (rupee amounts, ticks, Greek). The CLI forces UTF-8 on its
streams so ``click.echo`` can't die with a UnicodeEncodeError regardless of the
active provider.
"""

from __future__ import annotations

import sys

from atlas.cli import _force_utf8_output


class _RecordingStream:
    """Stand-in for a text stream that records reconfigure() calls."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def reconfigure(self, *, encoding: str, errors: str) -> None:
        self.calls.append({"encoding": encoding, "errors": errors})


class _LegacyStream:
    """A stream without reconfigure() (e.g. a redirected/test double)."""


def test_force_utf8_reconfigures_stdout_and_stderr(monkeypatch) -> None:
    out, err = _RecordingStream(), _RecordingStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    _force_utf8_output()

    assert out.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_force_utf8_is_a_noop_on_streams_without_reconfigure(monkeypatch) -> None:
    # Must not raise when a stream predates reconfigure() or is a test double.
    monkeypatch.setattr(sys, "stdout", _LegacyStream())
    monkeypatch.setattr(sys, "stderr", _LegacyStream())
    _force_utf8_output()  # no exception == pass
