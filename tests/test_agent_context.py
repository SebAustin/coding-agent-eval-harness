from __future__ import annotations

from pathlib import Path

from coding_eval.agents.context import (
    extract_keywords,
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


def test_extract_keywords_prioritizes_backtick_and_title_terms() -> None:
    weights = extract_keywords(
        "rich.pretty does not show maxlen for `deque`",
        "Some prose mentioning helper once. CLICOLOR=1 in the dump.",
        [],
    )
    # backtick + title term outranks an incidental body word; env vars are dropped.
    assert weights["deque"] > weights.get("helper", 0.0)
    assert "CLICOLOR" not in weights


def test_gather_surfaces_relevant_region_of_large_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "rich"
    tests = repo / "tests"
    pkg.mkdir(parents=True)
    tests.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    # A file far larger than the per-file budget; the relevant symbol sits well
    # past the head, where naive head-truncation would never reach it.
    head = "".join(f"filler_{i} = {i}\n" for i in range(2000))
    relevant = "def handle_deque(obj):\n    return obj.maxlen  # the fix lives here\n"
    tail = "".join(f"more_{i} = {i}\n" for i in range(2000))
    (pkg / "pretty.py").write_text(head + relevant + tail, encoding="utf-8")
    (tests / "test_pretty.py").write_text("from rich.pretty import pretty_repr\n", encoding="utf-8")

    ctx = gather_repo_context(
        str(repo),
        ["tests/test_pretty.py"],
        issue_title="pretty does not show `maxlen` for `deque`",
        issue_body="When rendering a deque, maxlen is missing.",
    )
    assert "def handle_deque" in ctx
    assert "the fix lives here" in ctx
    assert "filler_0 = 0" not in ctx  # head was not blindly included
