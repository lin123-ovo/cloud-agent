"""Local single-operator identity; never trust an identity supplied in a prompt."""

import os
import re


def operator_id() -> str:
    """Use server configuration for the local operator, not browser user_id."""
    identity = os.getenv("CLOUDAGENT_OPERATOR_ID", "user_1001")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity):
        raise ValueError("Invalid CLOUDAGENT_OPERATOR_ID")
    return identity
