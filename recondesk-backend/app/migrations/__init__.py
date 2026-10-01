"""AWS Aurora database migrations module for ReconDesk."""

from __future__ import annotations

__all__ = [
    "AuroraMigrationRunner",
    "ChecksumMismatchError",
    "MalformedMigrationError",
    "MigrationConcurrencyError",
    "MigrationError",
    "MigrationExecutionError",
    "MigrationFile",
    "MigrationRecord",
    "MissingMigrationFileError",
    "OutOrderMigrationError",
]


def __getattr__(name: str):
    if name in __all__:
        import app.migrations.runner as runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
