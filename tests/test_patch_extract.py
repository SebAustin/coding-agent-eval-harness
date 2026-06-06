from __future__ import annotations

from coding_eval.patching.extract import extract_unified_patch

_VALID = (
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1,3 +1,3 @@\n"
    " line1\n"
    "-old\n"
    "+new\n"
    " line3\n"
)


def test_extract_simple_patch() -> None:
    assert extract_unified_patch(_VALID) == _VALID


def test_extract_strips_markdown_fence() -> None:
    wrapped = f"```diff\n{_VALID}```"
    assert extract_unified_patch(wrapped) == _VALID


def test_extract_stops_at_prose() -> None:
    text = _VALID + "\nWait, let me reconsider.\n"
    assert extract_unified_patch(text) == _VALID


def test_extract_rejects_duplicate_file_hunk() -> None:
    duplicate = _VALID + "\n" + _VALID
    assert extract_unified_patch(duplicate) == _VALID


def test_extract_skips_bare_triple_dash_before_real_header() -> None:
    text = "---\n" + _VALID
    assert extract_unified_patch(text) == _VALID


def test_extract_empty_when_no_diff() -> None:
    assert extract_unified_patch("Here is my fix: change foo to bar") == ""


def test_extract_requires_hunk_header() -> None:
    assert extract_unified_patch("--- a/x.py\n+++ b/x.py\n") == ""


def test_extract_drops_incomplete_trailing_hunk() -> None:
    partial = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-old\n"
        "+new\n"
        " line3\n"
        "@@ -10,2 +10,5 @@\n"
        " ctx\n"
        "+only one added line\n"
    )
    assert extract_unified_patch(partial) == _VALID


def test_looks_like_diff_attempt() -> None:
    from coding_eval.patching.extract import looks_like_diff_attempt

    assert looks_like_diff_attempt("Explanation\n--- a/x.py\n+++ b/x.py\n") is True
    assert looks_like_diff_attempt("no diff here") is False


def test_extract_prose_before_diff() -> None:
    prose = (
        "Looking at the issue, the fix is in pretty.py.\n\n"
        f"{_VALID}"
    )
    assert extract_unified_patch(prose) == _VALID


def test_extract_normalizes_bare_path_headers() -> None:
    bare = (
        "--- rich/pretty.py\n"
        "+++ rich/pretty.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-old\n"
        "+new\n"
        " line3\n"
    )
    expected = (
        "--- a/rich/pretty.py\n"
        "+++ b/rich/pretty.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-old\n"
        "+new\n"
        " line3\n"
    )
    assert extract_unified_patch(bare) == expected


def test_looks_like_diff_attempt_bare_plus_header() -> None:
    from coding_eval.patching.extract import looks_like_diff_attempt

    assert looks_like_diff_attempt("Fix:\n+++ rich/pretty.py\n") is True
    assert looks_like_diff_attempt("--- rich/foo.py\n(no hunks yet)\n") is True
