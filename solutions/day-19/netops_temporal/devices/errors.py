"""Our own exception types, so activities don't depend on each library's error classes.

Every device helper translates its library's errors into these. Day 3 decides which of
them are worth retrying.
"""


class DeviceUnreachableError(Exception):
    """Couldn't connect, or the connection timed out. Often temporary: worth retrying."""


class DeviceAuthError(Exception):
    """The device rejected our credentials. Retrying won't fix that."""


class UnknownDeviceError(ValueError):
    """The device name isn't in DEVICE_HOSTS. Retrying won't fix that either."""
