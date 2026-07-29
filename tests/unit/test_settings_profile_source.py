"""``profile_source`` — which tier a profile is assembled from (M3, #24).

The setting exists so the assertion-backed path can ship dark: present,
exercised by its own tests, and reachable by anyone who wants to compare, while
every existing profile keeps being built exactly as before.

So the guarantee worth pinning is the default. It stays "analyzers" until the
equivalence gate is green, because the gate compares the two paths, and a
default that flipped first would make it compare the new path against itself.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas.config.settings import Settings


def test_default_is_analyzers() -> None:
    """Flipping this is M4's job (#35), and only once #26 is green."""
    assert Settings(_env_file=None).profile_source == "analyzers"


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
