from __future__ import annotations

import re
from typing import Any

# Match DPAPI ciphertexts
_DPAPI_PATTERN = re.compile(r"dpapi:[a-zA-Z0-9+/=]+", re.IGNORECASE)
# Match API keys like sk-..., Bearer tokens, etc.
_SK_PATTERN = re.compile(r"sk-[a-zA-Z0-9_\-]{8,}")
_BEARER_PATTERN = re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE)
# Match whole Windows and Unix user directory paths: C:\Users\alice\... or /home/alice/... or /Users/alice/...
_WIN_USER_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/]{1,2}(?:Users|users)[\\/]{1,2}[^\s\"'\`\<\>\,]+", re.IGNORECASE)
_UNIX_USER_PATH_PATTERN = re.compile(r"/(?:home|Users)/[^\s\"'\`\<\>\,]+", re.IGNORECASE)

SENSITIVE_KEYS = {
    "token",
    "api_key",
    "secret",
    "password",
    "authorization",
    "raw_text",
    "user_text",
    "transcript",
    "audio_pcm",
    "audio_hex",
}


def redact_string(val: str) -> str:
    """Redact secrets and personal directory paths from a string."""
    if not val:
        return val
    s = _DPAPI_PATTERN.sub("[REDACTED_DPAPI]", val)
    s = _SK_PATTERN.sub("sk-[REDACTED]", s)
    s = _BEARER_PATTERN.sub("Bearer [REDACTED]", s)
    s = _WIN_USER_PATH_PATTERN.sub("<REDACTED_PATH>", s)
    s = _UNIX_USER_PATH_PATTERN.sub("<REDACTED_PATH>", s)
    return s


def redact_dict(data: Any) -> Any:
    """Recursively redact sensitive keys and values from dictionaries or lists."""
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(sens in k_lower for sens in SENSITIVE_KEYS):
                result[k] = "[REDACTED]"
            elif isinstance(v, (dict, list)):
                result[k] = redact_dict(v)
            elif isinstance(v, str):
                result[k] = redact_string(v)
            else:
                result[k] = v
        return result
    elif isinstance(data, list):
        return [redact_dict(item) for item in data]
    elif isinstance(data, str):
        return redact_string(data)
    else:
        return data
