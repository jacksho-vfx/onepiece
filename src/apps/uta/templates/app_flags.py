from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html import escape


@dataclass(frozen=True)
class AppFlag:
    name: str
    slug: str
    emblem: str
    background: str
    accent: str
    highlight: str


_EMBLEMS = [
    "☠️",
    "⚓",
    "🗡️",
    "🧭",
    "🏴‍☠️",
    "🌊",
    "🦜",
    "🪝",
    "🪙",
    "🧨",
]
_PALETTES: list[tuple[str, str, str]] = [
    ("#0f172a", "#38bdf8", "#e2e8f0"),
    ("#1f2937", "#f97316", "#fde68a"),
    ("#111827", "#a855f7", "#fbcfe8"),
    ("#0b1120", "#34d399", "#bbf7d0"),
    ("#171717", "#fb7185", "#fecdd3"),
    ("#111827", "#facc15", "#fef3c7"),
    ("#0f172a", "#60a5fa", "#dbeafe"),
    ("#1f2937", "#22d3ee", "#cffafe"),
]


def _slugify(name: str) -> str:
    return "-".join(name.lower().split())


def resolve_app_flag(name: str) -> AppFlag:
    cleaned = name.strip() or "app"
    digest = int(sha256(cleaned.encode("utf-8")).hexdigest(), 16)
    emblem = _EMBLEMS[digest % len(_EMBLEMS)]
    palette = _PALETTES[(digest // len(_EMBLEMS)) % len(_PALETTES)]
    return AppFlag(
        name=cleaned,
        slug=_slugify(cleaned),
        emblem=emblem,
        background=palette[0],
        accent=palette[1],
        highlight=palette[2],
    )


def render_app_flag(name: str, *, size: str = "md", extra_class: str = "") -> str:
    flag = resolve_app_flag(name)
    class_bits = " ".join(
        bit for bit in ["app-flag", f"app-flag--{size}", extra_class] if bit
    )
    style = (
        f"--flag-bg: {flag.background}; "
        f"--flag-accent: {flag.accent}; "
        f"--flag-highlight: {flag.highlight};"
    )
    return (
        f'<span class="{escape(class_bits)}" style="{escape(style, quote=True)}"'
        f' data-app-flag="{escape(flag.slug, quote=True)}" aria-hidden="true">'
        f'<span class="app-flag-emblem">{escape(flag.emblem)}</span>'
        "</span>"
    )


__all__ = ["AppFlag", "render_app_flag", "resolve_app_flag"]
