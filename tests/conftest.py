import shutil
from pathlib import Path
from typing import Callable

import pytest

from atlas import Atlas
from atlas.config.settings import Settings


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Settings with a temporary directory as the repository base path."""
    return Settings(repository_base_path=tmp_path)


@pytest.fixture
def atlas(test_settings: Settings) -> Atlas:
    """Fully constructed Atlas using test settings."""
    return Atlas(settings=test_settings)


@pytest.fixture(scope="session")
def isolated_repo_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[..., Path]:
    """Factory fixture: build a private copy of a real company repository.

    Integration tests need real acquired documents (PDFs, catalog.json) to
    exercise KnowledgeBase/CompanyStore against, but must never write to the
    canonical repositories/ tree — knowledge.db deletion/reparse in a test
    fixture must not mutate shared, checked-in data. This factory copies
    catalog.json + company.json plus only the specific documents a test
    needs into a session-scoped tmp directory, leaving the real repository
    untouched (read-only access via Repository()).

    Usage inside a test file's own fixture::

        @pytest.fixture(scope="module")
        def tcs_root(isolated_repo_factory):
            return isolated_repo_factory(_TCS_REPO, evidence_ids=[_ANN_ID, _Q2_ID])
    """

    def _make(
        real_root: Path,
        evidence_ids: list[str] | None = None,
        extra_paths: list[str] | None = None,
    ) -> Path:
        from atlas.acquisition.repository import Repository

        dest = tmp_path_factory.mktemp("repo") / real_root.name
        dest.mkdir(parents=True)
        for meta in ("catalog.json", "company.json"):
            src = real_root / meta
            if src.exists():
                shutil.copy2(src, dest / meta)

        paths = list(extra_paths or [])
        if evidence_ids:
            repo = Repository(real_root)
            for eid in evidence_ids:
                entry = repo.get(eid)
                if entry is not None and entry.local_path:
                    paths.append(entry.local_path)

        for rel in paths:
            src = real_root / rel
            if not src.exists():
                continue
            dst = dest / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return dest

    return _make
