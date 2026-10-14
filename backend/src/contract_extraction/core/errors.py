"""Application errors. The API (Phase 5) maps them to HTTP status codes."""


class AppError(Exception):
    """Base class for expected, user-facing errors."""


class NotFound(AppError):
    """A requested row does not exist."""


class Conflict(AppError):
    """The request conflicts with current state (e.g. a document already has an active run)."""


class InvalidConfig(AppError):
    """Configuration in the database cannot be used (missing default, disabled model, ...)."""


class InvalidInput(AppError):
    """Input rejected before it reaches the database (bad file, unknown option, ...)."""


class PayloadTooLarge(InvalidInput):
    """An upload exceeds the configured size limit."""
