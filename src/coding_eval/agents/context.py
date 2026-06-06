from __future__ import annotations

import re
from pathlib import Path

MAX_CHARS_PER_FILE = 12_000
MAX_TOTAL_CHARS = 48_000
MAX_RETRY_FILE_CHARS = 12_000

_IMPORT_FROM_RE = re.compile(r"^\s*from ([\w.]+) import\b")
_IMPORT_RE = re.compile(r"^\s*import ([\w.]+)\b")
_BACKTICK_PATH_RE = re.compile(r"`([^`\n]+\.py)`")
_ISSUE_PATH_RE = re.compile(r"(?:^|[\s`'\"(])([\w][\w./-]*\.py)\b")
_GITHUB_BLOB_RE = re.compile(
    r"github\.com/[^/\s]+/[^/\s]+/blob/[0-9a-f]+/(.+?\.py)",
    re.IGNORECASE,
)
_FROM_PKG_IMPORT_RE = re.compile(r"from ([\w]+) import ([\w.]+)")
_DOTTED_MODULE_RE = re.compile(r"\b([\w]+)\.([\w]+)\b")
_PATCH_OLD_FILE_RE = re.compile(r"^--- (?:a/)?(.+)$")
_APPLY_FAIL_RE = re.compile(r"error: patch failed: ([^:\n]+):(\d+)")
_CONTEXT_WINDOW = 60

# Relevance-aware windowing for files too large to send whole. Sending only the
# head of a large file means the model never sees the function it must patch and
# hallucinates the context, producing patches that cannot apply.
_RELEVANCE_WINDOW = 45
_MAX_KEYWORD_LINE_HITS = 12  # keywords matching more lines than this aren't discriminative
_KEYWORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_BACKTICK_TERM_RE = re.compile(r"`([^`\n]+)`")
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "when", "this", "that", "from", "into", "not",
        "but", "you", "your", "are", "was", "were", "will", "would", "should",
        "could", "has", "have", "had", "does", "did", "done", "using", "use",
        "used", "value", "values", "return", "returns", "expected", "actual",
        "example", "issue", "bug", "error", "output", "input", "code", "file",
        "files", "line", "lines", "test", "tests", "case", "cases", "function",
        "method", "class", "object", "instance", "default", "none", "true",
        "false", "python", "repository", "repo", "steps", "see", "linked",
        "https", "http", "com", "github", "www", "new", "old", "fix", "fixes",
        "add", "added", "change", "changed", "also", "only", "all", "any", "one",
        "first", "like", "instead", "where", "which", "what", "here", "there",
    }
)


def _format_numbered(source: str, *, start_line: int = 1) -> str:
    lines = source.splitlines()
    width = len(str(start_line + len(lines) - 1)) if lines else 1
    return "\n".join(f"{idx:>{width}}| {line}" for idx, line in enumerate(lines, start=start_line))


def _read_numbered_bounded(path: Path, *, limit: int, start_line: int = 1) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return _format_numbered(text, start_line=start_line)
    truncated = text[:limit]
    if truncated and not truncated.endswith("\n"):
        truncated = truncated.rsplit("\n", 1)[0] + "\n"
    body = _format_numbered(truncated, start_line=start_line)
    return body + f"\n... [truncated {len(text) - len(truncated)} chars]"


def _is_noise_identifier(ident: str) -> bool:
    # ALL-CAPS tokens in issue prose are almost always env vars / constants from
    # diagnostic dumps (CLICOLOR, JPY_PARENT_PID), not the symbol being fixed.
    return ident.isupper() or ident.lower() in _STOPWORDS


def extract_keywords(
    issue_title: str, issue_body: str, test_sources: list[str]
) -> dict[str, float]:
    """Identifiers likely to name the buggy code, weighted by issue-centrality.

    Backticked and title terms (``maxlen``, ``deque``) are far stronger signals
    than a word that happens to appear once in the issue body, so they carry more
    weight when ranking which regions of a large file to show.
    """
    # Dedup per source so a term repeated in an env/diagnostic dump can't inflate
    # its weight; then sum source weights so a term that is BOTH in the title and
    # backticked (the central symbol) decisively outranks incidental matches.
    backtick: set[str] = set()
    for term in _BACKTICK_TERM_RE.findall(f"{issue_title}\n{issue_body}"):
        backtick.update(_KEYWORD_RE.findall(term))
    title = set(_KEYWORD_RE.findall(issue_title))
    body = set(_KEYWORD_RE.findall(issue_body))
    test_syms: set[str] = set()
    for source in test_sources:
        test_syms.update(
            ident for ident in _KEYWORD_RE.findall(source) if "_" in ident or ident[:1].isupper()
        )

    weights: dict[str, float] = {}
    for ident in backtick | title | body | test_syms:
        if _is_noise_identifier(ident):
            continue
        weight = (
            4.0 * (ident in backtick)
            + 3.0 * (ident in title)
            + 2.0 * (ident in test_syms)
            + 0.5 * (ident in body)
        )
        if weight > 0:
            weights[ident] = weight
    return weights


def _relevant_numbered(text: str, *, keywords: dict[str, float], limit: int) -> str | None:
    """Numbered windows around the most discriminative keyword matches.

    Each line is scored by the keywords on it, combining issue-centrality (a
    backticked/title term outweighs an incidental body word) with file rarity (a
    keyword hitting two lines is more telling than one hitting ten). Windows are
    added best-first until the char budget is exhausted — so a large file shows
    the regions that matter instead of its head or an over-budget sprawl. Returns
    None when nothing is discriminative.
    """
    if not keywords:
        return None
    lines = text.splitlines()
    line_score: dict[int, float] = {}
    for keyword, importance in keywords.items():
        hits = [idx for idx, line in enumerate(lines) if keyword in line]
        if 0 < len(hits) <= _MAX_KEYWORD_LINE_HITS:
            weight = importance / len(hits)  # central + rare => stronger anchor
            for idx in hits:
                line_score[idx] = line_score.get(idx, 0.0) + weight
    if not line_score:
        return None

    selected: list[list[int]] = []
    used = 0
    for anchor in sorted(line_score, key=lambda i: (-line_score[i], i)):
        if any(lo <= anchor < hi for lo, hi in selected):
            continue
        lo = max(0, anchor - _RELEVANCE_WINDOW)
        hi = min(len(lines), anchor + _RELEVANCE_WINDOW + 1)
        cost = len("\n".join(lines[lo:hi]))
        if used + cost > limit and selected:
            break
        selected.append([lo, hi])
        used += cost

    selected.sort()
    spans: list[list[int]] = []
    for lo, hi in selected:
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])

    chunks: list[str] = []
    prev_hi = 0
    for lo, hi in spans:
        body = _format_numbered("\n".join(lines[lo:hi]), start_line=lo + 1)
        marker = "" if not chunks else f"... [{lo - prev_hi} lines omitted]\n"
        chunks.append(marker + body)
        prev_hi = hi

    suffix = "" if prev_hi >= len(lines) else "\n... [showing sections relevant to the issue]"
    return "\n".join(chunks) + suffix


def _read_numbered_context(path: Path, *, limit: int, keywords: dict[str, float]) -> str:
    """Whole file if it fits, else keyword-relevant windows, else the head."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return _format_numbered(text)
    relevant = _relevant_numbered(text, keywords=keywords, limit=limit)
    if relevant is not None:
        return relevant
    truncated = text[:limit]
    if truncated and not truncated.endswith("\n"):
        truncated = truncated.rsplit("\n", 1)[0] + "\n"
    body = _format_numbered(truncated)
    return body + f"\n... [truncated {len(text) - len(truncated)} chars]"


def _parse_apply_failures(apply_error: str) -> list[tuple[str, int]]:
    return [(path.strip(), int(line_no)) for path, line_no in _APPLY_FAIL_RE.findall(apply_error)]


def _read_line_window(path: Path, center_line: int, *, window: int = _CONTEXT_WINDOW) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return ""
    start = max(0, center_line - window - 1)
    end = min(len(lines), center_line + window)
    return _format_numbered("\n".join(lines[start:end]), start_line=start + 1)


def _read_bounded(path: Path, *, limit: int) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _module_to_path(repo_root: Path, module: str) -> Path | None:
    candidate = repo_root / f"{module.replace('.', '/')}.py"
    if candidate.is_file():
        return candidate
    package_init = repo_root / module.replace(".", "/") / "__init__.py"
    if package_init.is_file():
        return package_init
    return None


def _valid_repo_file(repo_root: Path, rel: str) -> Path | None:
    rel = rel.lstrip("./")
    if rel.startswith("/"):
        return None
    path = repo_root / rel
    if path.is_file():
        return path
    return None


def _top_level_packages(repo_root: Path) -> set[str]:
    packages: set[str] = set()
    for child in repo_root.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            packages.add(child.name)
    return packages


def _paths_from_imports(repo_root: Path, source: str) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for line in source.splitlines():
        match = _IMPORT_FROM_RE.match(line)
        module = match.group(1) if match else None
        if module is None:
            match = _IMPORT_RE.match(line)
            module = match.group(1) if match else None
        if module is None:
            continue
        path = _module_to_path(repo_root, module)
        if path is None or path in seen:
            continue
        seen.add(path)
        found.append(path)
    return found


def _paths_from_github_urls(issue_text: str) -> list[str]:
    return [match.group(1) for match in _GITHUB_BLOB_RE.finditer(issue_text)]


def _paths_from_module_keywords(repo_root: Path, issue_text: str) -> list[Path]:
    packages = _top_level_packages(repo_root)
    found: list[Path] = []
    seen: set[Path] = set()

    def add_rel(rel: str) -> None:
        path = _valid_repo_file(repo_root, rel)
        if path is None or path in seen:
            return
        seen.add(path)
        found.append(path)

    for pkg, name in _FROM_PKG_IMPORT_RE.findall(issue_text):
        if pkg in packages:
            add_rel(f"{pkg}/{name.replace('.', '/')}.py")

    for pkg, name in _DOTTED_MODULE_RE.findall(issue_text):
        if pkg not in packages:
            continue
        if name.endswith(".py"):
            add_rel(f"{pkg}/{name}")
        else:
            add_rel(f"{pkg}/{name.replace('.', '/')}.py")

    return found


def _paths_from_issue(repo_root: Path, issue_body: str) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None or path in seen:
            return
        seen.add(path)
        found.append(path)

    for rel in _paths_from_github_urls(issue_body):
        add(_valid_repo_file(repo_root, rel))

    for match in _BACKTICK_PATH_RE.finditer(issue_body):
        add(_valid_repo_file(repo_root, match.group(1)))

    for match in _ISSUE_PATH_RE.finditer(issue_body):
        add(_valid_repo_file(repo_root, match.group(1)))

    for path in _paths_from_module_keywords(repo_root, issue_body):
        add(path)

    return found


def paths_from_patch(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        match = _PATCH_OLD_FILE_RE.match(line)
        if match is None:
            continue
        rel = match.group(1).strip()
        if rel != "/dev/null" and rel not in paths:
            paths.append(rel)
    return paths


def format_patch_target_files(
    repo_path: str,
    patch: str,
    *,
    apply_error: str = "",
) -> str:
    root = Path(repo_path)
    sections: list[str] = []
    failures = _parse_apply_failures(apply_error)
    failure_by_file = dict(failures)

    for rel in paths_from_patch(patch):
        path = root / rel
        if not path.is_file():
            continue
        if rel in failure_by_file:
            body = _read_line_window(path, failure_by_file[rel])
            header = (
                f"### {rel} (apply failed near line {failure_by_file[rel]}; "
                "copy context lines exactly)\n"
            )
        else:
            body = _read_numbered_bounded(path, limit=MAX_RETRY_FILE_CHARS)
            header = f"### {rel}\n"
        sections.append(f"{header}```python\n{body}\n```")
    return "\n\n".join(sections)


def format_apply_failure_context(repo_path: str, apply_error: str) -> str:
    """Line-numbered slices around git apply failure locations."""
    root = Path(repo_path)
    sections: list[str] = []
    seen: set[str] = set()
    for rel, line_no in _parse_apply_failures(apply_error):
        if rel in seen:
            continue
        seen.add(rel)
        path = root / rel
        if not path.is_file():
            continue
        body = _read_line_window(path, line_no)
        sections.append(
            f"### {rel} (git apply failed at line {line_no})\n```python\n{body}\n```",
        )
    return "\n\n".join(sections)


def gather_repo_context(
    repo_path: str,
    test_files: list[str],
    *,
    issue_body: str = "",
    issue_title: str = "",
) -> str:
    """Collect test files, import targets, and issue-mentioned sources for the agent prompt."""
    root = Path(repo_path)
    issue_text = f"{issue_title}\n{issue_body}"
    ordered: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        if not path.is_file() or path in seen:
            return
        seen.add(path)
        ordered.append(path)

    for rel in test_files:
        add(root / rel)

    test_sources: list[str] = []
    for test_path in ordered:
        if not test_path.name.startswith("test_"):
            continue
        source = test_path.read_text(encoding="utf-8", errors="replace")
        test_sources.append(source)
        for imported in _paths_from_imports(root, source):
            add(imported)

    for mentioned in _paths_from_issue(root, issue_text):
        add(mentioned)

    # One more hop: a fix often spans a primary target and a sibling it imports
    # (e.g. completion.py and its _completion_shared helper). Follow imports from
    # the source files gathered so far so multi-file fixes have that context up
    # front. Neighbours are added last, so they only consume leftover budget.
    for source_path in [path for path in list(ordered) if not path.name.startswith("test_")]:
        source = source_path.read_text(encoding="utf-8", errors="replace")
        for neighbor in _paths_from_imports(root, source):
            add(neighbor)

    keywords = extract_keywords(issue_title, issue_body, test_sources)

    sections: list[str] = []
    total = 0
    for path in ordered:
        if total >= MAX_TOTAL_CHARS:
            break
        remaining = MAX_TOTAL_CHARS - total
        per_file = min(MAX_CHARS_PER_FILE, remaining)
        rel = path.relative_to(root).as_posix()
        body = _read_numbered_context(path, limit=per_file, keywords=keywords)
        block = f"### {rel}\n```python\n{body}\n```"
        sections.append(block)
        total += len(block)

    if not sections:
        return ""
    return (
        "Relevant repository files at base commit (line numbers shown as N| code):\n\n"
        + "\n\n".join(
            sections,
        )
    )


__all__ = [
    "MAX_CHARS_PER_FILE",
    "MAX_RETRY_FILE_CHARS",
    "MAX_TOTAL_CHARS",
    "extract_keywords",
    "format_apply_failure_context",
    "format_patch_target_files",
    "gather_repo_context",
    "paths_from_patch",
]
