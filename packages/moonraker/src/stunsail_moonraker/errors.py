"""Moonraker client errors."""


class MoonrakerError(Exception):
    """Base class for Moonraker client failures."""


class MoonrakerConnectionError(MoonrakerError):
    """Moonraker could not be reached or the connection was lost."""


class MoonrakerResponseError(MoonrakerError):
    """Moonraker answered with an error or an unexpected payload."""
