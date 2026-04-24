"""Shared error types for the little64 CLI.

Library modules should *raise* instead of calling :func:`sys.exit`. The CLI
entry point (:mod:`little64.cli`) catches :class:`CLIError` and its
subclasses and renders them consistently: a single ``error: <message>`` line
followed by any ``hints`` the exception carried.

Existing narrow error types (``MissingToolError`` in ``tools.py``,
``CommandError`` in ``proc.py``, ``KernelConfigError`` in
``commands/kernel/validate.py``) are deliberately left as their own classes
to avoid churn, but callers can still catch :class:`CLIError` to handle
them all at once.
"""

from __future__ import annotations


class CLIError(RuntimeError):
    """A user-actionable CLI failure.

    Subclasses may set ``hints`` to a tuple of short strings; the CLI will
    print each as ``hint: <text>`` after the main error line.
    """

    hints: tuple[str, ...] = ()

    def __init__(self, message: str, *, hints: tuple[str, ...] | None = None) -> None:
        super().__init__(message)
        if hints is not None:
            self.hints = hints


class LitexBootError(CLIError):
    """Failure while preparing or validating a LiteX boot path."""
