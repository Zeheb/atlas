from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas import Atlas
from atlas.config.settings import Settings


class TestSettings:
    def test_defaults(self) -> None:
        settings = Settings()
        assert settings.environment == "development"
        assert settings.log_level == "DEBUG"
        assert settings.http_timeout_seconds == 30
        assert settings.http_max_retries == 3
        assert settings.http_rate_limit_rps == 2.0

    def test_repository_base_path_is_path_object(self) -> None:
        settings = Settings()
        assert isinstance(settings.repository_base_path, Path)

    def test_environment_override_via_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_ENVIRONMENT", "production")
        monkeypatch.setenv("ATLAS_LOG_LEVEL", "INFO")
        settings = Settings()
        assert settings.environment == "production"
        assert settings.log_level == "INFO"

    def test_invalid_environment_raises(self) -> None:
        with pytest.raises(ValidationError):
            Settings(environment="staging")  # type: ignore[arg-type]

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(ValidationError):
            Settings(log_level="VERBOSE")  # type: ignore[arg-type]

    def test_http_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Settings(http_timeout_seconds=0)

    def test_http_rate_limit_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Settings(http_rate_limit_rps=0.0)


class TestAtlas:
    def test_from_environment_returns_atlas_instance(self) -> None:
        result = Atlas.from_environment()
        assert isinstance(result, Atlas)

    def test_from_environment_settings_are_accessible(self) -> None:
        atlas = Atlas.from_environment()
        assert isinstance(atlas.settings, Settings)

    def test_accepts_custom_settings(self, tmp_path: Path) -> None:
        settings = Settings(repository_base_path=tmp_path)
        atlas = Atlas(settings=settings)
        assert atlas.settings.repository_base_path == tmp_path

    def test_settings_fixture_uses_tmp_path(self, atlas: Atlas, tmp_path: Path) -> None:
        assert atlas.settings.repository_base_path == tmp_path

    def test_two_instances_are_independent(self, tmp_path: Path) -> None:
        path_a = tmp_path / "a"
        path_b = tmp_path / "b"
        atlas_a = Atlas(settings=Settings(repository_base_path=path_a))
        atlas_b = Atlas(settings=Settings(repository_base_path=path_b))
        assert (
            atlas_a.settings.repository_base_path
            != atlas_b.settings.repository_base_path
        )
