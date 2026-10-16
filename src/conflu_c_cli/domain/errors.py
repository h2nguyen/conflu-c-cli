"""Errors of the Confluence CLI. Every error carries the exit code that the CLI reports for it."""
from __future__ import annotations

from typing import Any


class ConfluCliError(Exception):
    exit_code = 1
    code = "ERROR"

    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details = details or {}


class UsageError(ConfluCliError):
    exit_code = 2
    code = "USAGE"


class ConfigError(ConfluCliError):
    code = "CONFIG"


class ValidationError(ConfluCliError):
    code = "INVALID"


class ConflictError(ConfluCliError):
    exit_code = 3
    code = "CONFLICT"


class NotFoundError(ConfluCliError):
    exit_code = 4
    code = "NOT_FOUND"


class AuthError(ConfluCliError):
    exit_code = 5
    code = "AUTH"


class RejectedError(ConfluCliError):
    exit_code = 6
    code = "REJECTED"


class UnavailableError(ConfluCliError):
    exit_code = 7
    code = "UNAVAILABLE"


# (exit code, error codes, meaning) - the single source for the docs and `conflu commands --json`.
EXIT_CODES: tuple[tuple[int, str, str], ...] = (
    (0, "OK", "The command succeeded (also for a dry run)."),
    (1, "ERROR, CONFIG, INVALID", "The command failed: bad input, missing configuration or another error."),
    (2, "USAGE", "The command line is wrong: unknown command or option, missing argument."),
    (3, "CONFLICT", "The page changed in Confluence after the version or time you named (--if-version, --if-unchanged-since), or while the update was on its way (HTTP 409)."),
    (4, "NOT_FOUND", "Confluence has no such page, space or resource (HTTP 404)."),
    (5, "AUTH", "Confluence refused the credentials or the permission (HTTP 401 or 403)."),
    (6, "REJECTED", "Confluence understood the request and refused it (for example HTTP 400); its message is shown."),
    (7, "UNAVAILABLE", "Confluence cannot be reached or answered with a server error (network, timeout, HTTP 5xx)."),
)
