from __future__ import annotations

from pathlib import Path

from git import Repo

from coding_eval.patching.validate import patch_py_files_compile


def test_patch_py_files_compile_accepts_valid_patch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("value = 1\n", encoding="utf-8")
    git_repo = Repo.init(repo)
    git_repo.index.add(["pkg/__init__.py", "pkg/mod.py"])
    git_repo.index.commit("init")

    patch = "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    ok, error = patch_py_files_compile(str(repo), patch)
    assert ok is True
    assert error == ""


def test_patch_py_files_compile_rejects_syntax_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("while True:\n    pass\n", encoding="utf-8")
    git_repo = Repo.init(repo)
    git_repo.index.add(["pkg/__init__.py", "pkg/mod.py"])
    git_repo.index.commit("init")

    patch = (
        "--- a/pkg/mod.py\n"
        "+++ b/pkg/mod.py\n"
        "@@ -1,2 +1,3 @@\n"
        " while True:\n"
        "+    raise (\n"
        "     pass\n"
    )
    ok, error = patch_py_files_compile(str(repo), patch)
    assert ok is False
    assert "SyntaxError" in error
