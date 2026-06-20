# Rubric design

Five-axis scoring for coding-agent patches. Weights are defined in
`src/coding_eval/rubric/scorer.py::WEIGHTS`; methodology rationale is in
[methodology.md](methodology.md).

## Composite score

```
composite = Σ (axis_score × weight)
```

| Axis | Weight |
| --- | ---: |
| `test_pass_rate` | 0.35 |
| `diff_minimality` | 0.15 |
| `complexity_delta` | 0.15 |
| `style_score` | 0.15 |
| `semantic_score` | 0.20 |

All axis scores are floats in **[0.0, 1.0]**. Empty patches score **0.0** on every axis.

### Test-only patch penalty

If a patch only modifies test files (`rubric/_patch_files.patch_only_modifies_tests`),
`test_pass_rate` is forced to **0.0** regardless of pytest output. The semantic judge
also receives `test_only_patch=True` and is instructed to score **0.0**.

---

## test_pass_rate (weight 0.35)

**Module:** `src/coding_eval/rubric/test_pass.py`

**Formula:**

```
test_pass_rate = passed / total
```

where `passed` and `total` are parsed from pytest `-q` summary lines in sandbox stdout
(`sandbox/patch.py::parse_test_results`).

**Baseline reference:** SWE-bench ([Jimenez et al., ICLR 2024](https://arxiv.org/abs/2310.06770))
defines task resolution as passing the target test suite. We generalise to the **fraction
of all pytest outcomes that pass** after applying the agent patch, which captures partial
progress on multi-test files.

**Edge cases:**

| Condition | Score |
| --- | ---: |
| Sandbox timed out | 0.0 |
| Patch failed `git apply --check` (sandbox skipped) | 0.0 |
| Pytest summary missing (`total = 0`) | 0.0 |
| Non-zero pytest exit with some passes | `passed / total` (partial credit) |

---

## diff_minimality (weight 0.15)

**Module:** `src/coding_eval/rubric/diff_minimality.py`

**Formula:**

```
changed_lines = count of '+' and '-' hunk lines (excluding ---/+++ headers)
diff_minimality = 1.0 - min(changed_lines / 200, 1.0)
```

**Why cap at 200 lines?**

1. **Signal saturation.** Beyond ~200 changed lines, additional edits rarely indicate
   *worse* agent behaviour for bug-fix tasks — the patch is already a large refactor.
2. **Task scope.** Our filter caps substantive files at 3; a correct fix for these tasks
   should require tens of lines, not hundreds. 200 lines is ~2× a generous upper bound.
3. **Stability.** Without a cap, a 2 000-line patch would drive the axis to `-9.0` before
   clamping; the cap keeps the axis interpretable as "how close to surgical."

| Changed lines | Score |
| ---: | ---: |
| 0 | 1.00 |
| 50 | 0.75 |
| 100 | 0.50 |
| 200+ | 0.00 |

Constant: `MAX_REASONABLE_LINES = 200`.

---

## complexity_delta (weight 0.15)

**Module:** `src/coding_eval/rubric/complexity.py`

Uses [radon](https://radon.readthedocs.io/) cyclomatic complexity on Python files touched
by the patch.

**Formula:**

```
before = mean CC of touched files at base commit
after  = mean CC after applying patch in a temp copy
delta  = after - before

complexity_delta = 1.0                    if delta <= 0
                 = max(0, 1.0 - delta/10) if delta > 0
```

**Interpretation:** reducing or preserving complexity scores 1.0; each +10 average CC
costs 1.0 point on this axis.

**Edge cases:** non-Python patches → 1.0; patch fails to apply in temp workspace → 0.0.

---

## style_score (weight 0.15)

**Module:** `src/coding_eval/rubric/style.py`

**Formula:**

```
violations = ruff check violations in added lines only (select=ALL, project ignores)
style_score = max(0.0, 1.0 - violations / 20)
```

Only **added** lines from the unified diff are linted (not the whole repo), isolating
style regressions introduced by the agent.

| New violations | Score |
| ---: | ---: |
| 0 | 1.00 |
| 10 | 0.50 |
| 20+ | 0.00 |

---

## semantic_score (weight 0.20)

**Module:** `src/coding_eval/rubric/semantic.py`

Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`, temperature **0**) rates whether the
patch correctly addresses the issue given:

- Issue title and body
- Unified diff
- Pytest output tail
- Current `test_pass_rate` (for calibration)

**Output:** JSON `{"score": float, "reasoning": str}` with score ∈ [0.0, 1.0].

**Parse pipeline:**

1. Strict JSON parse
2. Regex fallback on `"score": <float>`
3. Single reprompt with `JUDGE_REPROMPT`
4. Failure → 0.0, logged as `semantic.parse_failed`

Results cached in SQLite (`CACHE_VERSION = v6`) keyed by issue + patch prefix + test context.

---

## Worked example

| Axis | Raw | × Weight | Contribution |
| --- | ---: | ---: | ---: |
| test_pass_rate | 0.80 | 0.35 | 0.280 |
| diff_minimality | 0.90 | 0.15 | 0.135 |
| complexity_delta | 1.00 | 0.15 | 0.150 |
| style_score | 0.95 | 0.15 | 0.143 |
| semantic_score | 0.70 | 0.20 | 0.140 |
| **Composite** | | | **0.848** |

---

## Related docs

- [Methodology](methodology.md) — task selection, weights rationale, judge limitations
- [Contamination analysis](contamination_analysis.md) — overlap with SWE-bench train
- [Adding agents](adding_agents.md) — adapter registration
