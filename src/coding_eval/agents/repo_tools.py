from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

# Read-only filesystem tools the agentic adapter exposes to the model over the
# repository cloned at base_commit. Everything is sandboxed to the repo root:
# a path that resolves outside the tree is rejected rather than read.

MAX_READ_CHARS = 16_000
MAX_GREP_RESULTS = 80
MAX_GREP_FILE_BYTES = 1_000_000
MAX_GREP_LINE_CHARS = 200
MAX_LIST_ENTRIES = 400

_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".eggs",
    },
)
_TEXT_SUFFIXES = frozenset(
    {
        ".py", ".pyi", ".txt", ".md", ".rst", ".cfg", ".ini", ".toml",
        ".json", ".yaml", ".yml", ".in", ".sh",
    },
)


class RepoToolError(Exception):
    """Raised when a tool call references a path outside the repository."""


class RepoTools:
    """Read-only file access scoped to a single repository checkout."""

    def __init__(self, repo_path: str) -> None:
        self.root = Path(repo_path).resolve()

    def _resolve(self, rel: str | None) -> Path:
        cleaned = (rel or "").strip().lstrip("/")
        candidate = (self.root / cleaned).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            msg = f"path escapes repository: {rel!r}"
            raise RepoToolError(msg)
        return candidate

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            return f"error: not a file: {path}"
        text = target.read_text(encoding="utf-8", errors="replace")
        truncated = text[:MAX_READ_CHARS]
        numbered = "\n".join(
            f"{idx}| {line}" for idx, line in enumerate(truncated.splitlines(), start=1)
        )
        if len(text) > MAX_READ_CHARS:
            numbered += f"\n... [truncated {len(text) - MAX_READ_CHARS} chars]"
        return numbered or "(empty file)"

    def grep(self, pattern: str, path: str | None = None) -> str:
        regex = re.compile(pattern)
        base = self._resolve(path)
        files: Iterator[Path] = iter((base,)) if base.is_file() else self._walk(base)
        results: list[str] = []
        for file in files:
            rel = file.relative_to(self.root).as_posix()
            try:
                if file.stat().st_size > MAX_GREP_FILE_BYTES:
                    continue
                content = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    results.append(f"{rel}:{lineno}: {line.strip()[:MAX_GREP_LINE_CHARS]}")
                    if len(results) >= MAX_GREP_RESULTS:
                        results.append("... [more matches truncated]")
                        return "\n".join(results)
        return "\n".join(results) if results else "no matches"

    def list_dir(self, path: str | None = None) -> str:
        target = self._resolve(path)
        if not target.is_dir():
            return f"error: not a directory: {path}"
        entries: list[str] = []
        for child in sorted(target.iterdir(), key=lambda p: p.name):
            if child.name in _SKIP_DIRS:
                continue
            entries.append(child.name + ("/" if child.is_dir() else ""))
            if len(entries) >= MAX_LIST_ENTRIES:
                entries.append("... [more entries truncated]")
                break
        return "\n".join(entries) if entries else "(empty)"

    def _walk(self, base: Path) -> Iterator[Path]:
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(self.root).parts
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            if path.suffix not in _TEXT_SUFFIXES:
                continue
            yield path

    def dispatch(self, name: str, tool_input: dict[str, Any]) -> str:
        """Route a tool-use block to its handler, returning a string result.

        Errors are returned as ``error: ...`` text rather than raised so the model
        sees the failure and can adjust, instead of aborting the solve loop.
        """
        try:
            if name == "read_file":
                return self.read_file(str(tool_input["path"]))
            if name == "grep":
                return self.grep(str(tool_input["pattern"]), tool_input.get("path"))
            if name == "list_dir":
                return self.list_dir(tool_input.get("path"))
        except (RepoToolError, KeyError, TypeError, OSError, re.error) as exc:
            return f"error: {exc}"
        return f"error: unknown tool {name!r}"


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file from the repository. Returns the contents with "
            "'N| ' line-number prefixes; use those numbers when writing @@ hunk headers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative path, e.g. 'typer/completion.py'.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "grep",
        "description": (
            "Search the repository with a Python regular expression. Returns matching "
            "'path:line: text'. Use this to locate the code that needs changing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regular expression."},
                "path": {
                    "type": "string",
                    "description": "Optional file or subdirectory to limit the search.",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files and subdirectories of a repository directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative directory; defaults to the repo root.",
                },
            },
            "required": [],
        },
    },
]


__all__ = [
    "MAX_GREP_RESULTS",
    "MAX_READ_CHARS",
    "TOOL_SPECS",
    "RepoToolError",
    "RepoTools",
]
