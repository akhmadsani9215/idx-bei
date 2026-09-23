"""Allowlisted public static files under DATA_DIR.

Never mount the entire DATA_DIR — private session stores and ownership CSVs
must not be world-readable via HTTP.
"""

from __future__ import annotations

import os
import re
from typing import Final

from idx.core.utils import DATA_DIR

# Only explicitly public artifacts. Private stores use .ritelinsight_* prefix.
PUBLIC_DATA_FILES: Final[frozenset[str]] = frozenset(
    {
        "network_alpha_data.json",
        "network_alpha_data.js",
    }
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def resolve_public_data_path(filename: str) -> str | None:
    """Return absolute path if filename is allowlisted and inside DATA_DIR.

    Rejects path traversal, absolute paths, and non-allowlisted names.
    """
    if not filename or not isinstance(filename, str):
        return None
    name = filename.strip().replace("\\", "/")
    if not name or "/" in name or name in (".", ".."):
        return None
    if not _SAFE_NAME.match(name):
        return None
    if name not in PUBLIC_DATA_FILES:
        return None
    root = os.path.realpath(DATA_DIR)
    candidate = os.path.realpath(os.path.join(root, name))
    try:
        common = os.path.commonpath([root, candidate])
    except ValueError:
        return None
    if common != root:
        return None
    if not os.path.isfile(candidate):
        return None
    return candidate
