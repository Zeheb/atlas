from pathlib import Path

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
