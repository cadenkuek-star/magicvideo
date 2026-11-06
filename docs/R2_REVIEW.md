# Review log — magicvideo Round 2

## Review R01 — 2026-11-06

**Verdict: REVISE (narrow).** Head reviewed: `6b5c3a0` on `r2/identity-review` (base `1e0dded`).

### What I ran
- A fresh clone of the branch outside the coder's checkout, with `PYTHONPATH` pinned to the clone (confirmed that
  `magicvideo.__file__` resolves inside it). Full suite: **67 passed** (my run; matches the claim).
  `git status` after the run was clean.
- 19 mutations (brief §6 plus extras), one at a time, with the full suite minus e2e. **18 killed, 1 survived.**
- Render pass: the e2e synthetic trip, `run_plan(thumbs=True)`, and `make_server(port=0)`, driven in headless
  Chromium.
  - Live mode: a keep click wrote `overrides.yaml`, and the bar shows "Saved · 1 change / Re-plan now". No page
    errors.
  - `file://` mode: the Download overrides.yaml button and the save hint are shown. The only console error is the
    expected failed fetch.
- Integrity sweep:
  - No NUL bytes or BOMs.
  - Every `.py` and `.json` file parses.
  - The R2 docs are byte-identical to what was issued, and `agent/SKILL.md` is identical to
    `docs/R2_SKILL_magicvideo.md`.
  - `IMPLEMENTATION_BRIEF.md` has 29 lines added and 0 deleted.
  - No binaries or footage.
  - Every commit carries the Sonnet 5.5 co-author trailer.
- Read in full: `review.py`. Its security is sound:
  - it binds to 127.0.0.1;
  - it checks the Host header;
  - it rejects a non-JSON Content-Type with 415;
  - it caps the request body;
  - it validates ids against the plan;
  - writes go to a temp file and then `os.replace`;
  - thumbnails are confined by `resolve` + `is_relative_to`;
  - writes are serialised under a lock.

### Mutation table
| # | Mutation | Result | Killed by |
| --- | --- | --- | --- |
| 1 | no stranger check | killed | test_stranger_on_screen_keeps_third_party |
| 2 | `<` at padded edge | killed | test_stranger_on_screen_keeps_third_party |
| 3 | stranger ignores min_q | killed | test_stranger_times_thresholds |
| 4 | is_couple forgets COUPLE | killed | test_couple_turns_make_a_conversation |
| 5 | minimum check removed | killed | test_below_minimum_message_names_folder_and_flag |
| 6 | merge keeps SRC separate | killed | test_merge_folds_folder_into_partner |
| 7 | centroid-only voice scoring | killed | test_multi_reference_uses_best_match |
| 8a–d | 0.0.0.0 / Host check / unknown ids / clear→None | killed | test_review.py (4 tests) |
| 9 | read overrides without utf-8-sig | **survived — equivalent** (PyYAML strips a BOM itself; verified) | — |
| 10 | couple override not applied | killed | test_couple_override_counts_as_couple |
| 11a–b | cells out of range / double count | killed | test_agent_tags.py |
| 12 | `^` anchor restored | killed | test_filename_time_with_prefix |
| 13 | couple_prior flag ignored | killed | test_couple_prior_off_keeps_old_labels |
| 14 | non-atomic write | killed | test_post_keep_writes_overrides |
| 15 | no-key check removed | killed | test_anthropic_without_key_is_backend_missing |

### Rulings on parked items
- **P1** (refs_sha256 assertion moved to the W6 commit) — ACCEPT.
- **P2** (the "treated as you two" line only when N > 0) — ACCEPT.
- **P3** (a `couple` override is still trimmed to the 8 s excerpt and counted in the third-party budget) — REVISE, see R01-1.
- **P4** (W5 wording and edge cases) — ACCEPT.
- **P5** (`*_count`/`*_all` swapped with the centroids; merged files named `<trip>_<SRC>_<file>`) — ACCEPT. Good catch.
- **P6** (the change counter and the `download-overrides` id) — ACCEPT.
- **P7** (`insta360_key`/`detect_camera` still anchored) — ACCEPT for this round. Noted for R3: a prefixed X6 file
  name (`026_VID_…`) would not pair `.insv`/`.lrv`. The owner's X6 files are not prefixed today.
- **P8** (QC max-gap ignores COUPLE) — REVISE, see R01-2. This would falsely fail `edit.max_gap_without_partner_s`
  on the owner's next run.
- **P9** (OVERRIDES_TEMPLATE does not mention `couple`) — REVISE, see R01-4.

### Rulings
- **R01-1.** In `plan/budget.py::select_event`, a `kind == "third_party"` moment whose override is `couple`:
  - is selected whole, with no `_trim_excerpt` call;
  - is **not** added to `used` / `ev.third_party_used`;
  - has the reason `"kept in review (this is us)"`.

  All other third-party handling stays as it is.

  Test `tests/test_budget.py::test_couple_override_not_trimmed_or_budgeted`: a 20 s third-party moment with the
  `couple` override keeps `t0`/`t1` unchanged, and `ev.third_party_used == 0`.
- **R01-2.** In `qc/runner.py`, extract `_partner_heard(cd, t: float, step: float, policy) -> bool`. It returns
  True when any word in `cd.words_in(t - step, t + step)` has `is_couple_speaker(cd.word_speaker(i), policy)`, and
  False when `cd` is None. Use it in place of the `in PARTNERS` check at the max-gap computation (around line 213).

  Test, new file `tests/test_qc_gap.py::test_couple_speech_counts_as_partner_heard`: a ClipData with one word
  inside a `COUPLE` turn returns True; the same with `OTHER` returns False.
- **R01-3.** Show no voice score when there are no voice references:
  - In `load_clip`, when refs lack `voice_a`/`voice_b`, `window_evidence[*]["voice_best"]` is `None`.
  - `moments._identity` leaves out the `voice_best` key when every overlapping value is `None`.
  - The storyboard prints the `voice match … (needs …)` part only when `voice_best` is present.

  Tests:
  - `tests/test_moments.py::test_identity_omits_voice_without_refs`
  - `tests/test_review.py::test_storyboard_hides_voice_match_without_refs` (a hand-written plan whose moment
    identity has no `voice_best` produces a page without "voice match")
- **R01-4.** In `project.py`, add `couple` to the `OVERRIDES_TEMPLATE` comment that lists moment values, in plain
  words ("couple = this is us: count as couple time"). No test.

### Expected count and evidence for R02
**71 collected, 71 passed** (67 + 4), a prediction.

Evidence required:
- test-first commits for R01-1 to R01-3;
- the full suite run once;
- the R01 self-checks again: the `0.0.0.0` grep, a clean `git status`, and `git log --oneline 6b5c3a0..HEAD`.

Append `## Coder response R01` to `docs/R2_HANDOVER.md`; do not rewrite the earlier sections.
