# Review log — magicvideo Round 3

## Review R01 — 2026-11-06

**Verdict: REVISE (narrow, tests only).** Head reviewed: `66e7267` on `r3/speech-qc-x6` (base `2c0f6d6`).

### What I ran
- Fresh clone with `PYTHONPATH` pinned. Full suite: **89 passed** (my run; matches the prediction).
- Again with zhconv blocked (`sys.modules["zhconv"] = None`): **88 passed, 1 skipped**
  (`test_scripts_fold_together`). The optional dependency is truly optional.
- `git status` after the run was clean. The brief is byte-identical to what was issued.
- Read every production diff: `qc/runner.py`, `plan/data.py`, `analysis/asr.py`, `plan/planner.py`,
  `render/renderer.py`, `ingest.py`, the policy and `pyproject.toml`. They match the brief.
  - The renderer refusal runs before `pdir.mkdir`.
  - The hallucination filter has no word-probability rule.
- 15 mutations: **13 killed, 2 survived** (below).
- Integrity:
  - No NUL bytes or BOMs; all `.py` files compile.
  - `IMPLEMENTATION_BRIEF.md` has 14 lines added and 0 deleted; `agent/SKILL.md` has 10 added and 0 deleted.
  - R2 docs untouched; no binaries.
  - Every commit carries the Sonnet 5.5 co-author trailer.

### Mutation table
| # | Mutation | Result |
| --- | --- | --- |
| 1 | CJK words not split | killed (test_cjk_words_split_into_characters) |
| 2 | folding ignored | killed (test_scripts_fold_together) |
| 3 | missing runs `>` instead of `>=` | killed (test_missing_runs_reported_with_master_times) |
| 4 | phrase match without punctuation removal | killed (test_known_phrase_segment_dropped) |
| 5 | score rule fires on one score | killed (test_score_rule_needs_both_scores) |
| 6 | windows not remapped | killed (test_windows_and_embeddings_remapped) |
| 7 | edge warning uses the moment edge instead of the last word | **SURVIVED** |
| 8 | an unused unstitched clip is listed | killed (test_export_list_names_used_unstitched_only) |
| 9 | renderer check removed | killed (test_renderer_refuses_before_writing) |
| 10 | `.match` in `insta360_key` | killed (test_prefixed_names_group_and_detect) |
| 11 | `plan_unstitched` ignored | killed (test_unstitched_kept_when_plan_unstitched) |
| 12 | `asr_filter.enabled` ignored | killed (test_filter_disabled_changes_nothing) |
| 13 | refusal moved after `pdir.mkdir` | killed (test_renderer_refuses_before_writing) |
| 14 | planned words not sorted by film time | **SURVIVED** |
| 15 | `detect_camera` `.match` for DJI | killed (test_prefixed_names_group_and_detect) |

### Rulings on parked items
P1–P5: ACCEPT, all five.

### Rulings
- **R01-1** (mutation 7, brief §5.7). Add the test
  `tests/test_moments.py::test_edge_speech_uses_last_word_not_moment_edge`:
  - clip duration 23.1;
  - a selected conversation moment with `t1 = 23.0` (post-roll reaches the end) whose last word ends at 20.0
    and first word starts at 1.0;
  - expected: `edge_speech_warnings` returns `[]`.

  No production change.
- **R01-2** (mutation 14, brief W1.3). In `qc/runner.py`, extract the planned-word loop from `editorial`
  unchanged into `collect_planned_words(convs, cds, seg_spans, timeline, fps, policy) -> tuple[int, int,
  list[tuple[str, float]]]`, returning `(total, kept, planned)` with `planned` sorted by master time. `editorial`
  calls it; no behaviour change.

  Test `tests/test_qc_speech.py::test_planned_words_follow_film_order`:
  - two conversations, A (`abs_t0` 100) and B (`abs_t0` 200), on two clips;
  - the timeline places B's segment at `start_frame` 0 and A's after it;
  - the planned words come out B's then A's.

  Build each ClipData directly, with words and one turn labelled `PARTNER_A`.

### Expected count and evidence for R02
**91 collected, 91 passed** (89 + 2), a prediction.

Evidence required:
- `test(R01-n)` commits;
- R01-2's refactor in its own commit after its test;
- the full suite run once;
- `git log --oneline 66e7267..HEAD` and `git status --short`.

Append `## Coder response R01` to `docs/R3_HANDOVER.md`.

## Review R02 — 2026-11-06

**Verdict: APPROVE.** Head reviewed: `2d1c332` (`2d1c3329e7a790ee195304e6b35e90740f949122`).

### What I ran
- Fresh clone. Full suite: **91 passed** (my run; matches the prediction). `git status` after the run was clean.
  `R3_REVIEW.md` R01 is unchanged.
- The two R01 survivors were re-run on the new head and are now killed:
  - mutation 7 by `test_edge_speech_uses_last_word_not_moment_edge`;
  - mutation 14 by `test_planned_words_follow_film_order`.
- The `qc/runner.py` diff since R01 is a verbatim move of the planned-word loop into `collect_planned_words`,
  plus the call; no logic changed.

### Authorisation
The branch `r3/speech-qc-x6` at `2d1c332` is approved to fast-forward `claude/vibrant-brahmagupta-yr5pu4`
(currently `2c0f6d6`) on the owner's PC, and to be pushed to origin.

Markers:
- **contains:** `def rendered_speech_check` in `magicvideo/qc/runner.py`; `def drop_hallucinations` in
  `magicvideo/plan/data.py`; `def x6_export_list` in `magicvideo/plan/planner.py`; `plan_unstitched: true` in
  `magicvideo/default_policy.yaml`.
- **absent:** `_INSTA_RE.match(` and `_DJI_RE.match(` in `magicvideo/ingest.py`.

After the merge, the SKILL.md copies at `C:\Travel\.agents\skills\magicvideo\` and
`C:\Travel\skills\magicvideo\` must match `agent/SKILL.md`, which gained the Insta360 and plan-warning
sections.
