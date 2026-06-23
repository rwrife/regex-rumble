"""Built-in challenge packs shipped with regex-rumble."""

from __future__ import annotations

from pathlib import Path

PACK_DIR = Path(__file__).parent


def builtin_pack_path(pack_id: str) -> Path:
    """Return the on-disk path to a built-in pack (no validation)."""
    return PACK_DIR / f"{pack_id}.json"
