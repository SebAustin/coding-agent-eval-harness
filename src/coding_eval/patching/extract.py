from __future__ import annotations

import re

_DIFF_START_RE = re.compile(
    r"^--- (?:a/|/dev/null|(?:\S+/)*\S+\.\S+)",
    re.MULTILINE,
)
_OLD_FILE_RE = re.compile(r"^--- (?:a/)?(.+)$")
_NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _normalize_header_line(line: str) -> str:
    old_match = _OLD_FILE_RE.match(line)
    if old_match is not None:
        path = old_match.group(1).strip()
        if path == "/dev/null":
            return "--- /dev/null"
        if path.startswith("a/"):
            return f"--- a/{path.removeprefix('a/')}"
        return f"--- a/{path.lstrip('/')}"
    new_match = _NEW_FILE_RE.match(line)
    if new_match is not None:
        path = new_match.group(1).strip()
        if path == "/dev/null":
            return "+++ /dev/null"
        if path.startswith("b/"):
            return f"+++ b/{path.removeprefix('b/')}"
        return f"+++ b/{path.lstrip('/')}"
    return line


def _is_diff_line(line: str) -> bool:
    if not line:
        return True
    if line.startswith(("--- ", "+++ ", "@@ ", "diff --git ", "index ")):
        return True
    if line.startswith(("new file mode ", "deleted file mode ", "similarity index ")):
        return True
    if line.startswith(("rename from ", "rename to ")):
        return True
    return line.startswith(("+", "-", " "))


def _hunk_line_counts(line: str) -> tuple[int, int]:
    if line.startswith(" "):
        return 1, 1
    if line.startswith("-"):
        return 1, 0
    if line.startswith("+"):
        return 0, 1
    return 0, 0


def _trim_incomplete_hunks(lines: list[str]) -> list[str]:
    """Drop trailing hunks whose body line counts do not match the @@ header."""
    hunk_start = next((idx for idx, line in enumerate(lines) if line.startswith("@@")), len(lines))
    kept = lines[:hunk_start]
    idx = hunk_start
    while idx < len(lines):
        line = lines[idx]
        if not line.startswith("@@"):
            idx += 1
            continue
        match = _HUNK_RE.match(line)
        if match is None:
            break
        old_expected = int(match.group(2) or "1")
        new_expected = int(match.group(4) or "1")
        hunk_lines = [line]
        idx += 1
        old_seen = 0
        new_seen = 0
        while idx < len(lines) and not lines[idx].startswith("@@"):
            body = lines[idx]
            if body.startswith(("--- ", "+++ ", "diff --git ")):
                break
            old_delta, new_delta = _hunk_line_counts(body)
            old_seen += old_delta
            new_seen += new_delta
            hunk_lines.append(body)
            idx += 1
        if old_seen != old_expected or new_seen != new_expected:
            break
        kept.extend(hunk_lines)
    return kept


def extract_unified_patch(text: str) -> str:
    """Return the first valid unified diff, stopping before prose or duplicate file hunks."""
    stripped = _strip_markdown_fences(text)
    match = _DIFF_START_RE.search(stripped)
    if match is None:
        return ""

    lines = stripped[match.start() :].splitlines()
    collected: list[str] = []
    seen_old_files: set[str] = set()

    for line in lines:
        if not _is_diff_line(line):
            break
        if line.startswith("--- ") or line.startswith("+++ "):
            line = _normalize_header_line(line)
        old_match = _OLD_FILE_RE.match(line)
        if old_match is not None:
            old_path = old_match.group(1).strip()
            if old_path in seen_old_files:
                break
            seen_old_files.add(old_path)
        collected.append(line)

    collected = _trim_incomplete_hunks(collected)
    patch = "\n".join(collected).strip()
    if not patch:
        return ""
    if "@@" not in patch or "+++" not in patch:
        return ""
    if not patch.endswith("\n"):
        patch += "\n"
    return patch


def looks_like_diff_attempt(text: str) -> bool:
    if _DIFF_START_RE.search(text):
        return True
    if re.search(r"^\+\+\+ ", text, re.MULTILINE):
        return True
    return "@@" in text and re.search(r"^--- ", text, re.MULTILINE) is not None


__all__ = ["extract_unified_patch", "looks_like_diff_attempt"]
