from __future__ import annotations

import enum


class Hook(enum.Enum):
    PRE_COMMAND = "pre_command"
    POST_COMMAND = "post_command"
    PRE_SPLASH = "pre_splash"
    POST_SPLASH = "post_splash"
    PRE_SERVICE_CALL = "pre_service_call"
    POST_SERVICE_CALL = "post_service_call"
