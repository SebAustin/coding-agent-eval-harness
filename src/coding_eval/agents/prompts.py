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

AGENTIC_SYSTEM_PROMPT = (
    "You are a software engineer fixing an issue in a repository checked out at a "
    "fixed commit. You have read-only tools to explore the code: 'read_file', "
    "'grep', and 'list_dir'. Use them to find every file the fix must touch — many "
    "fixes span more than one module (e.g. a helper and its caller). "
    "Call the real tools provided; NEVER invent pseudo tool calls such as "
    "<file_search> or <read_files> in your text — they do nothing.\n\n"
    "When you have gathered enough context, stop calling tools and reply with ONLY "
    "a unified diff that fixes the issue in production/source code — never modify "
    "files under tests/ or test_*.py. read_file shows line numbers as 'N| code'; "
    "use those numbers in @@ hunk headers and copy context lines character-for-"
    "character so the diff applies cleanly with `git apply`. "
    "The final message must be the diff alone, starting with '---', with no prose "
    "and no markdown fence.\n\n"
    "Example of correct diff output:\n"
    f"{FEW_SHOT_EXAMPLE}\n"
    "Every removed line starts with '-', every added line with '+', context lines "
    "with a single space."
)

AGENTIC_NO_OUTPUT_REPROMPT = (
    "You neither called a tool nor produced a unified diff. Either call read_file / "
    "grep / list_dir to gather more context, or output ONLY the final unified diff "
    "starting with '--- a/path/to/file.py'. No prose, no markdown fence."
)

__all__ = [
    "AGENTIC_NO_OUTPUT_REPROMPT",
    "AGENTIC_SYSTEM_PROMPT",
    "FEW_SHOT_EXAMPLE",
    "FORMAT_REPROMPT",
    "FORMAT_REPROMPT_STRICT",
    "SYSTEM_PROMPT",
]
