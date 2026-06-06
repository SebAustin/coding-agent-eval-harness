from __future__ import annotations

FEW_SHOT_EXAMPLE = """\
--- a/rich/traceback.py
+++ b/rich/traceback.py
@@ -229,6 +229,8 @@ class Traceback:
         ".pxd": "cython",
         ".pyx": "cython",
         ".pxi": "pyrex",
+        ".j2": "jinja2",
+        ".jinja2": "jinja2",
     }

     def __init__("""

SYSTEM_PROMPT = (
    "You are a software engineer. You are given an issue and relevant source files "
    "from the repository at a fixed commit. Source files show line numbers as "
    "'N| code' — use those line numbers when writing @@ hunk headers. "
    "Produce a minimal unified diff patch that fixes the issue in production/source "
    "code — never modify files under tests/ or test_*.py. The diff MUST apply "
    "cleanly with `git apply` against those files — copy context lines character-for-character "
    "from the numbered source. "
    "Output ONLY the diff, starting with '---'. No explanation, no markdown fence.\n\n"
    "Example of correct output (minimal change, valid unified diff):\n"
    f"{FEW_SHOT_EXAMPLE}\n"
    "Every removed line must start with '-'. Every added line with '+'. "
    "Context lines start with a single space."
)

FORMAT_REPROMPT = (
    "Your previous response included explanation or a malformed diff. "
    "Output ONLY a valid unified diff starting with '--- a/' or '--- path/to/file.py'. "
    "No prose, no markdown fence. Use exact context lines (including spaces) from the "
    "numbered source files. @@ headers must match the line numbers shown. "
    "Do not modify test files."
)

FORMAT_REPROMPT_STRICT = (
    "STRICT: Your last two responses were not valid unified diffs. "
    "Reply with NOTHING except the diff text. "
    "First line MUST be '--- a/path/to/file.py'. "
    "No markdown fences, no commentary, no blank lines before the diff. "
    "Copy context lines exactly from the numbered source. "
    "Fix source code only — not tests."
)

__all__ = ["FEW_SHOT_EXAMPLE", "FORMAT_REPROMPT", "FORMAT_REPROMPT_STRICT", "SYSTEM_PROMPT"]
