import json

import pytest

from atlas import Atlas
from atlas.acquisition.scaffold import RepositoryAlreadyExistsError, build_repository


class TestRepositoryCreation:
    def test_creates_repository_directory(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        assert (atlas.settings.repository_base_path / "TCS").is_dir()

    def test_creates_all_subdirectories(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        root = atlas.settings.repository_base_path / "TCS"
        for name in [
            "annual_reports",
            "financial_results",
            "earnings_transcripts",
            "investor_presentations",
            "logs",
        ]:
            assert (root / name).is_dir(), f"Missing: {name}"

    def test_ticker_normalised_to_uppercase(self, atlas: Atlas) -> None:
        path = build_repository(atlas, "tcs")
        assert path.name == "TCS"
        assert (atlas.settings.repository_base_path / "TCS").is_dir()

    def test_returns_path_to_repository_root(self, atlas: Atlas) -> None:
        path = build_repository(atlas, "TCS")
        assert path == atlas.settings.repository_base_path / "TCS"


class TestCompanyJson:
    def test_company_json_exists(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        assert (atlas.settings.repository_base_path / "TCS" / "company.json").exists()

    def test_company_json_contains_ticker(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        data = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "company.json").read_text()
        )
        assert data["ticker"] == "TCS"

    def test_company_json_contains_id_with_prefix(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        data = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "company.json").read_text()
        )
        assert data["id"].startswith("cmp_")
        assert len(data["id"]) == len("cmp_") + 32  # cmp_ + uuid4 hex

    def test_company_json_contains_created_at(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        data = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "company.json").read_text()
        )
        assert "created_at" in data
        assert data["created_at"]  # non-empty

    def test_company_json_contains_atlas_version(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        data = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "company.json").read_text()
        )
        assert "atlas_version" in data
        assert data["atlas_version"] == "0.1.0"


class TestCatalogJson:
    def test_catalog_json_exists(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        assert (atlas.settings.repository_base_path / "TCS" / "catalog.json").exists()

    def test_catalog_schema_version_is_one(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        data = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "catalog.json").read_text()
        )
        assert data["schema_version"] == "1"

    def test_catalog_schema_version_is_string(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        data = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "catalog.json").read_text()
        )
        assert isinstance(data["schema_version"], str)


class TestIdempotency:
    def test_second_run_raises_already_exists(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        with pytest.raises(RepositoryAlreadyExistsError):
            build_repository(atlas, "TCS")

    def test_already_exists_error_carries_path(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        with pytest.raises(RepositoryAlreadyExistsError) as exc_info:
            build_repository(atlas, "TCS")
        assert exc_info.value.path == atlas.settings.repository_base_path / "TCS"

    def test_second_run_does_not_overwrite_company_id(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        original_id = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "company.json").read_text()
        )["id"]
        with pytest.raises(RepositoryAlreadyExistsError):
            build_repository(atlas, "TCS")
        current_id = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "company.json").read_text()
        )["id"]
        assert original_id == current_id

    def test_second_run_does_not_overwrite_created_at(self, atlas: Atlas) -> None:
        build_repository(atlas, "TCS")
        original_ts = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "company.json").read_text()
        )["created_at"]
        with pytest.raises(RepositoryAlreadyExistsError):
            build_repository(atlas, "TCS")
        current_ts = json.loads(
            (atlas.settings.repository_base_path / "TCS" / "company.json").read_text()
        )["created_at"]
        assert original_ts == current_ts
