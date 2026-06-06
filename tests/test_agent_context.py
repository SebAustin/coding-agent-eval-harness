from __future__ import annotations

from pathlib import Path

from coding_eval.agents.context import (
    format_apply_failure_context,
    format_patch_target_files,
    gather_repo_context,
)


def test_gather_includes_test_file_and_imports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    tests = repo / "tests"
    pkg.mkdir(parents=True)
    tests.mkdir()
    (pkg / "highlighter.py").write_text("def highlight() -> None:\n    pass\n", encoding="utf-8")
    (tests / "test_highlighter.py").write_text(
        "from rich.highlighter import highlight\n\ndef test_x() -> None:\n    highlight()\n",
        encoding="utf-8",
    )

    context = gather_repo_context(str(repo), ["tests/test_highlighter.py"])

    assert "tests/test_highlighter.py" in context
    assert "rich/highlighter.py" in context
    assert "def highlight()" in context


def test_gather_includes_issue_mentioned_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    pkg.mkdir(parents=True)
    (pkg / "pretty.py").write_text("x = 1\n", encoding="utf-8")

    context = gather_repo_context(
        str(repo),
        [],
        issue_body="Bug in `rich/pretty.py` when printing complex numbers.",
    )

    assert "rich/pretty.py" in context


def test_gather_truncates_large_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "big.py").write_text("x = 1\n" * 10_000, encoding="utf-8")

    context = gather_repo_context(str(repo), ["big.py"])

    assert "[truncated" in context


def test_gather_github_blob_url(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    pkg.mkdir(parents=True)
    (pkg / "style.py").write_text("class Style:\n    pass\n", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    issue = (
        "See https://github.com/Textualize/rich/blob/"
        "6d30ad0f30028210124c149811cbbe2b183711f9/rich/style.py#L664"
    )
    context = gather_repo_context(str(repo), [], issue_body=issue)

    assert "rich/style.py" in context
    assert "class Style" in context


def test_gather_module_keywords_from_title_and_body(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "traceback.py").write_text("def install():\n    pass\n", encoding="utf-8")
    (pkg / "pretty.py").write_text("def install():\n    pass\n", encoding="utf-8")

    context = gather_repo_context(
        str(repo),
        [],
        issue_title="[BUG] rich.traceback: no lexer for filename X found",
        issue_body="from rich import pretty\npretty.install()",
    )

    assert "rich/traceback.py" in context
    assert "rich/pretty.py" in context


def test_format_patch_target_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    pkg.mkdir(parents=True)
    (pkg / "style.py").write_text("alpha = 1\nbeta = 2\n", encoding="utf-8")
    patch = "--- a/rich/style.py\n+++ b/rich/style.py\n@@ -1 +1 @@\n-alpha\n+beta\n"
    formatted = format_patch_target_files(str(repo), patch)
    assert "rich/style.py" in formatted
    assert "1| alpha = 1" in formatted


def test_format_patch_target_files_apply_error_window(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    pkg.mkdir(parents=True)
    lines = [f"line_{idx} = {idx}\n" for idx in range(1, 120)]
    (pkg / "style.py").write_text("".join(lines), encoding="utf-8")
    patch = "--- a/rich/style.py\n+++ b/rich/style.py\n@@ -80 +80 @@\n-line_80\n+line_80 = 99\n"
    apply_error = (
        "error: patch failed: rich/style.py:80\nerror: rich/style.py: patch does not apply"
    )
    formatted = format_patch_target_files(str(repo), patch, apply_error=apply_error)
    assert "apply failed near line 80" in formatted
    assert "80| line_80" in formatted
    assert "line_1 =" not in formatted


def test_format_apply_failure_context(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    pkg.mkdir(parents=True)
    (pkg / "pretty.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    apply_error = "error: patch failed: rich/pretty.py:2\n"
    formatted = format_apply_failure_context(str(repo), apply_error)
    assert "git apply failed at line 2" in formatted
    assert "2| b = 2" in formatted
