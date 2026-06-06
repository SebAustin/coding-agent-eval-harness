from __future__ import annotations

from coding_eval.patching.extract import extract_unified_patch

_VALID = (
    "--- a/foo.py\n" "+++ b/foo.py\n" "@@ -1,3 +1,3 @@\n" " line1\n" "-old\n" "+new\n" " line3\n"
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


def test_extract_recounts_miscounted_hunk_header() -> None:
    # Model declares 7,7 but the body is a complete 6,6 hunk (off-by-one count
    # error). The hunk must be kept with corrected counts, not discarded.
    miscounted = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,7 +1,7 @@\n"
        " line1\n"
        " line2\n"
        " line3\n"
        "-old\n"
        "+new\n"
        " line5\n"
        " line6\n"
    )
    patch = extract_unified_patch(miscounted)
    assert "@@ -1,6 +1,6 @@\n" in patch
    assert "+new\n" in patch
    assert " line6\n" in patch


def test_extract_recounts_preserves_section_heading() -> None:
    miscounted = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -10,5 +10,5 @@ class Foo:\n"
        " a\n"
        "-b\n"
        "+c\n"
        " d\n"
        " e\n"
    )
    patch = extract_unified_patch(miscounted)
    assert "@@ -10,4 +10,4 @@ class Foo:\n" in patch


def test_extract_keeps_dropping_truncated_trailing_hunk() -> None:
    # A trailing hunk whose body falls short of the header by more than the
    # tolerance is a real truncation (token cutoff) and must still be dropped.
    truncated = (
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
    assert extract_unified_patch(truncated) == _VALID


def test_looks_like_diff_attempt() -> None:
    from coding_eval.patching.extract import looks_like_diff_attempt

    assert looks_like_diff_attempt("Explanation\n--- a/x.py\n+++ b/x.py\n") is True
    assert looks_like_diff_attempt("no diff here") is False


def test_extract_prose_before_diff() -> None:
    prose = "Looking at the issue, the fix is in pretty.py.\n\n" f"{_VALID}"
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


def test_extract_from_nested_markdown_fence() -> None:
    text = "Explanation first.\n\n```diff\n" + _VALID + "```\n\nMore prose."
    assert extract_unified_patch(text) == _VALID


def test_extract_when_plus_header_comes_first() -> None:
    plus_first = (
        "+++ b/rich/pretty.py\n" "@@ -1,3 +1,3 @@\n" " line1\n" "-old\n" "+new\n" " line3\n"
    )
    patch = extract_unified_patch(plus_first)
    assert patch.startswith("--- a/rich/pretty.py\n")
    assert "+++ b/rich/pretty.py\n" in patch


def test_extract_normalizes_unprefixed_hunk_context() -> None:
    unprefixed = (
        "--- a/rich/style.py\n"
        "+++ b/rich/style.py\n"
        "@@ -677,5 +677,6 @@ class Style:\n"
        "        style._link = None\n"
        '        style._link_id = ""\n'
        "        style._meta = None\n"
        "+        style._hash = None\n"
        "        style._null = not (style._color or style._bgcolor or style._set_attributes)\n"
        "        return style\n"
    )
    patch = extract_unified_patch(unprefixed)
    assert "+        style._hash = None" in patch
    assert " return style" in patch


def test_looks_like_diff_attempt_bare_plus_header() -> None:
    from coding_eval.patching.extract import looks_like_diff_attempt

    assert looks_like_diff_attempt("Fix:\n+++ rich/pretty.py\n") is True
    assert looks_like_diff_attempt("--- rich/foo.py\n(no hunks yet)\n") is True
