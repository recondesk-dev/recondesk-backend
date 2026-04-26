"""Re-export shared :class:`~slowapi.Limiter` (defined in ``app.main``)."""

from __future__ import annotations

from typing import Any

__all__ = ("limiter",)


def __getattr__(name: str) -> Any:
    if name == "limiter":
        from app import main

        return main.limiter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
