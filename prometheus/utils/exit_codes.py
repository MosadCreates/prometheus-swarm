from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    ERROR = 1
    ERROR_CONFIG = 2
    ERROR_NOT_FOUND = 3
    ERROR_VALIDATION = 4
    ERROR_PERMISSION = 5
    ERROR_NETWORK = 6
    ERROR_PROVIDER = 7
    ERROR_INTERRUPTED = 130
