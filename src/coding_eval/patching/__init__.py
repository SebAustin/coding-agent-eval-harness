from __future__ import annotations

from .extract import extract_unified_patch
from .git_apply import apply_unified_diff

__all__ = ["apply_unified_diff", "extract_unified_patch"]
