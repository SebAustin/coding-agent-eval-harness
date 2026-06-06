from __future__ import annotations

import re

_DIFF_START_RE = re.compile(
    r"^--- (?:a/|/dev/null|(?:\S+/)*\S+\.\S+)",
    re.MULTILINE,
)
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)
_PLUS_HEADER_RE = re.compile(r"^\+\+\+ (?:b/)?", re.MULTILINE)
_FENCE_BLOCK_RE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_OLD_FILE_RE = re.compile(r"^--- (?:a/)?(.+)$")
_NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")

# Models routinely miscount hunk lengths by a line. A body that falls short of
# the declared count by more than this is treated as truncated, not miscounted.
HUNK_COUNT_TOLERANCE = 1


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


def _find_diff_start(text: str) -> int | None:
    match = _DIFF_START_RE.search(text)
    if match is not None:
        return match.start()
    git_match = _DIFF_GIT_RE.search(text)
    if git_match is not None:
        return git_match.start()
    plus_match = _PLUS_HEADER_RE.search(text)
    if plus_match is not None:
        return plus_match.start()
    return None


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


def _recount_hunks(lines: list[str]) -> list[str]:
    """Rewrite @@ header counts to match each hunk body.

    Models frequently miscount hunk lengths by a line (e.g. counting the @@
    section heading, or a boundary blank). The old behaviour discarded any such
    hunk, which turned an otherwise-applicable fix into an empty patch. Instead
    we trust the body and recompute the declared counts so the patch is
    well-formed. A hunk whose body diverges from the header by more than
    ``HUNK_COUNT_TOLERANCE`` is treated as truncated (e.g. the response hit the
    token limit mid-hunk) and dropped along with everything that follows it.
    """
    hunk_start = next((idx for idx, line in enumerate(lines) if line.startswith("@@")), len(lines))
    kept = lines[:hunk_start]
    idx = hunk_start
    while idx < len(lines):
        line = lines[idx]
        if not line.startswith("@@"):
            idx += 1
            continue
        match = _HUNK_HEADER_RE.match(line)
        if match is None:
            break
        old_start = match.group(1)
        new_start = match.group(3)
        section = match.group(5)
        old_expected = int(match.group(2) or "1")
        new_expected = int(match.group(4) or "1")
        body: list[str] = []
        idx += 1
        old_seen = 0
        new_seen = 0
        while idx < len(lines) and not lines[idx].startswith("@@"):
            entry = lines[idx]
            if entry.startswith(("--- ", "+++ ", "diff --git ")):
                break
            old_delta, new_delta = _hunk_line_counts(entry)
            old_seen += old_delta
            new_seen += new_delta
            body.append(entry)
            idx += 1
        if old_seen == 0 and new_seen == 0:
            break
        # Distinguish a miscount (recount it) from a truncation (drop it) by
        # DIRECTION, not magnitude. Truncation means generation was cut off, so the
        # body is SHORTER than the header declared on the added/context side; that
        # can only happen at the very end of the response. A body that meets or
        # exceeds its declared new-count is a complete hunk the model merely
        # miscounted (often by more than one on large hunks) — trust the body.
        stopped_at_end = idx >= len(lines)
        if stopped_at_end and new_seen < new_expected - HUNK_COUNT_TOLERANCE:
            break
        if old_seen == old_expected and new_seen == new_expected:
            kept.append(line)  # counts already correct — keep header verbatim
        else:
            kept.append(f"@@ -{old_start},{old_seen} +{new_start},{new_seen} @@{section}")
        kept.extend(body)
    return kept


def _normalize_hunk_line(line: str, *, in_hunk: bool) -> str:
    if not in_hunk or not line.strip():
        return line
    if line.startswith(("+", "-", " ", "\\", "@@")):
        return line
    return f" {line}"


def _is_unprefixed_hunk_body(line: str) -> bool:
    """Lines inside a hunk that omit the unified-diff prefix but are indented code."""
    return bool(line.strip()) and line[0] in " \t"


def _collect_diff_lines(lines: list[str]) -> list[str]:
    collected: list[str] = []
    seen_old_files: set[str] = set()
    pending_plus: str | None = None
    in_hunk = False

    for line in lines:
        if line.startswith("@@"):
            in_hunk = True
        elif line.startswith("--- ") and collected:
            in_hunk = False
        if not _is_diff_line(line):
            if in_hunk and _is_unprefixed_hunk_body(line):
                line = _normalize_hunk_line(line, in_hunk=True)
            else:
                break
        elif in_hunk:
            line = _normalize_hunk_line(line, in_hunk=True)
        if not _is_diff_line(line):
            break
        if line.startswith(("--- ", "+++ ")):
            line = _normalize_header_line(line)
        if line.startswith("+++ ") and not any(item.startswith("--- ") for item in collected):
            pending_plus = line
            continue
        if pending_plus is not None:
            new_match = _NEW_FILE_RE.match(pending_plus)
            if new_match is not None:
                path = new_match.group(1).strip().removeprefix("b/")
                collected.append(f"--- a/{path.lstrip('/')}")
            collected.append(pending_plus)
            pending_plus = None
        old_match = _OLD_FILE_RE.match(line)
        if old_match is not None:
            old_path = old_match.group(1).strip()
            if old_path in seen_old_files:
                break
            seen_old_files.add(old_path)
        collected.append(line)

    if pending_plus is not None:
        new_match = _NEW_FILE_RE.match(pending_plus)
        if new_match is not None:
            path = new_match.group(1).strip().removeprefix("b/")
            collected.append(f"--- a/{path.lstrip('/')}")
        collected.append(pending_plus)

    return collected


def _extract_from_text(text: str) -> str:
    start = _find_diff_start(text)
    if start is None:
        return ""

    lines = text[start:].splitlines()
    collected = _collect_diff_lines(lines)
    collected = _recount_hunks(collected)
    patch = "\n".join(collected).strip()
    if not patch:
        return ""
    if "@@" not in patch or "+++" not in patch:
        return ""
    if not patch.endswith("\n"):
        patch += "\n"
    return patch


def extract_unified_patch(text: str) -> str:
    """Return the first valid unified diff, stopping before prose or duplicate file hunks."""
    stripped = _strip_markdown_fences(text)
    patch = _extract_from_text(stripped)
    if patch:
        return patch

    for block in _FENCE_BLOCK_RE.findall(text):
        patch = _extract_from_text(block.strip())
        if patch:
            return patch

    return ""


def looks_like_diff_attempt(text: str) -> bool:
    if _DIFF_START_RE.search(text):
        return True
    if _DIFF_GIT_RE.search(text):
        return True
    if re.search(r"^\+\+\+ ", text, re.MULTILINE):
        return True
    return "@@" in text and re.search(r"^--- ", text, re.MULTILINE) is not None


__all__ = ["extract_unified_patch", "looks_like_diff_attempt"]
