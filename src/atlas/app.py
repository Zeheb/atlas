from typing import Self

from atlas.config.settings import Settings


class Atlas:
    """The Atlas application object.

    Holds shared infrastructure: configuration now; logging, HTTP client,
    and cache in future tasks. Never holds domain state such as the current
    company, repository, or research session.

    Production code should construct via the factory::

        atlas = Atlas.from_environment()

    Tests should construct directly, injecting controlled settings::

        atlas = Atlas(settings=Settings(repository_base_path=tmp_path))
    """

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    @property
    def settings(self) -> Settings:
        return self._settings

    @classmethod
    def from_environment(cls) -> Self:
        """Create a fully initialised Atlas from environment variables and .env."""
        return cls(settings=Settings())
