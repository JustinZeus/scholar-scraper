from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ThemeDefinition:
    slug: str
    label: str


THEMES: Final[tuple[ThemeDefinition, ...]] = (
    ThemeDefinition(slug="terracotta", label="Terracotta"),
    ThemeDefinition(slug="fjord", label="Fjord"),
    ThemeDefinition(slug="spruce", label="Spruce"),
)
_THEME_SLUGS: Final[frozenset[str]] = frozenset(theme.slug for theme in THEMES)
DEFAULT_THEME: Final[str] = THEMES[0].slug


def resolve_theme(candidate: str | None) -> str:
    if candidate and candidate in _THEME_SLUGS:
        return candidate
    return DEFAULT_THEME

