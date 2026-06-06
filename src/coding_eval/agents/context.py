from __future__ import annotations

import re
from pathlib import Path

MAX_CHARS_PER_FILE = 12_000
MAX_TOTAL_CHARS = 48_000
MAX_RETRY_FILE_CHARS = 8_000

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
_CONTEXT_WINDOW = 40


def _format_numbered(source: str, *, start_line: int = 1) -> str:
    lines = source.splitlines()
    width = len(str(start_line + len(lines) - 1)) if lines else 1
    return "\n".join(
        f"{idx:>{width}}| {line}" for idx, line in enumerate(lines, start=start_line)
    )


def _read_numbered_bounded(path: Path, *, limit: int, start_line: int = 1) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return _format_numbered(text, start_line=start_line)
    truncated = text[:limit]
    if truncated and not truncated.endswith("\n"):
        truncated = truncated.rsplit("\n", 1)[0] + "\n"
    body = _format_numbered(truncated, start_line=start_line)
    return body + f"\n... [truncated {len(text) - len(truncated)} chars]"


def _parse_apply_failures(apply_error: str) -> list[tuple[str, int]]:
    return [
        (path.strip(), int(line_no))
        for path, line_no in _APPLY_FAIL_RE.findall(apply_error)
    ]


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
    failure_by_file = {rel: line_no for rel, line_no in failures}

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

    for test_path in list(ordered):
        if not test_path.name.startswith("test_"):
            continue
        source = test_path.read_text(encoding="utf-8", errors="replace")
        for imported in _paths_from_imports(root, source):
            add(imported)

    for mentioned in _paths_from_issue(root, issue_text):
        add(mentioned)

    sections: list[str] = []
    total = 0
    for path in ordered:
        if total >= MAX_TOTAL_CHARS:
            break
        remaining = MAX_TOTAL_CHARS - total
        per_file = min(MAX_CHARS_PER_FILE, remaining)
        rel = path.relative_to(root).as_posix()
        body = _read_numbered_bounded(path, limit=per_file)
        block = f"### {rel}\n```python\n{body}\n```"
        sections.append(block)
        total += len(block)

    if not sections:
        return ""
    return "Relevant repository files at base commit (line numbers shown as N| code):\n\n" + "\n\n".join(
        sections,
    )


__all__ = [
    "MAX_CHARS_PER_FILE",
    "MAX_RETRY_FILE_CHARS",
    "MAX_TOTAL_CHARS",
    "format_apply_failure_context",
    "format_patch_target_files",
    "gather_repo_context",
    "paths_from_patch",
]
