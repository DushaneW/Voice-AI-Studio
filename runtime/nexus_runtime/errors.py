"""Stable domain errors.

`DomainError` carries a content-free, stable machine code (the exception message).
It subclasses `ValueError` so existing internal `except ValueError` blocks keep
working, but the API maps only `DomainError` to client errors. A plain
`ValueError` escaping from application code is a bug and becomes HTTP 500.
"""


class DomainError(ValueError):
    """Expected, user-correctable failure with a stable code (HTTP 409)."""

    @property
    def code(self) -> str:
        return str(self)


class NotFound(DomainError):
    """Requested entity does not exist or is unavailable (HTTP 404)."""
