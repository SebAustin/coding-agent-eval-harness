from __future__ import annotations

from pathlib import Path

from coding_eval.agents.repo_tools import MAX_GREP_RESULTS, RepoTools


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    pkg = repo / "typer"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "completion.py").write_text(
        "from typer._completion_shared import resolve_help\n\nLINE = resolve_help('x')\n",
        encoding="utf-8",
    )
    (pkg / "_completion_shared.py").write_text(
        "def resolve_help(text):\n    return text\n",
        encoding="utf-8",
    )
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("secret\n", encoding="utf-8")
    return repo


def test_read_file_numbered(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    out = tools.read_file("typer/_completion_shared.py")
    assert "1| def resolve_help(text):" in out
    assert "2|     return text" in out


def test_read_file_missing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    assert tools.read_file("typer/nope.py").startswith("error: not a file")


def test_read_file_rejects_escape(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    out = tools.dispatch("read_file", {"path": "../../etc/passwd"})
    assert out.startswith("error: path escapes repository")


def test_read_file_truncates(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "big.py").write_text("x = 1\n" * 5000, encoding="utf-8")
    tools = RepoTools(str(repo))
    out = tools.read_file("big.py")
    assert "[truncated" in out


def test_read_file_line_range(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "many.py").write_text("".join(f"line{n}\n" for n in range(1, 21)), encoding="utf-8")
    tools = RepoTools(str(repo))
    out = tools.dispatch("read_file", {"path": "many.py", "start_line": 5, "end_line": 7})
    assert "5| line5" in out
    assert "7| line7" in out
    assert "line4" not in out
    assert "line8" not in out


def test_read_file_ignores_non_integer_range(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    out = tools.dispatch("read_file", {"path": "typer/_completion_shared.py", "start_line": "x"})
    assert "1| def resolve_help(text):" in out


def test_grep_finds_matches(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    out = tools.grep("resolve_help")
    assert "typer/completion.py:" in out
    assert "typer/_completion_shared.py:" in out


def test_grep_no_matches(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    assert tools.grep("nonexistent_symbol_xyz") == "no matches"


def test_grep_skips_git_dir(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    out = tools.grep("secret")
    assert out == "no matches"


def test_grep_in_single_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    out = tools.grep("resolve_help", "typer/_completion_shared.py")
    assert "typer/completion.py" not in out
    assert "typer/_completion_shared.py:" in out


def test_grep_caps_results(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "many.py").write_text("hit\n" * 200, encoding="utf-8")
    tools = RepoTools(str(repo))
    out = tools.grep("hit")
    assert "more matches truncated" in out
    assert out.count("many.py:") == MAX_GREP_RESULTS


def test_grep_invalid_regex_returns_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    assert tools.dispatch("grep", {"pattern": "("}).startswith("error:")


def test_list_dir_root_and_subdir(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    assert "typer/" in tools.list_dir()
    assert ".git" not in tools.list_dir()
    sub = tools.list_dir("typer")
    assert "completion.py" in sub
    assert "_completion_shared.py" in sub


def test_list_dir_not_a_directory(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    assert tools.list_dir("typer/completion.py").startswith("error: not a directory")


def test_dispatch_unknown_tool(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    assert tools.dispatch("frobnicate", {}).startswith("error: unknown tool")


def test_dispatch_missing_required_arg(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tools = RepoTools(str(repo))
    assert tools.dispatch("read_file", {}).startswith("error:")
