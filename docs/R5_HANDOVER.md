# R5 handover (Coder A)

Branch `r5/signal-speech-qc` from `a4c3843`. Nothing pushed or merged.

## 1. Work items

| Item | Test commit | Feature commit | Files | What changed |
| --- | --- | --- | --- | --- |
| Step 0 | - | `6b495c3` | `docs/R5_BRIEF.md` | Brief unchanged. |
| W1 | `6bf76e2` | `986b870` | `qc/runner.py`, `default_policy.yaml`, `tests/test_signal_speech.py`, `tests/test_e2e.py` | `collect_planned_word_spans`, `word_present`, `signal_word_presence`; `editorial` decides by signal, Whisper cross-check is information; `signal` in the speech report; six `qc.*` keys; e2e expects PASS. |
| W2 | `c61c93b` | `ce05b7a` | `analysis/runner.py`, `default_policy.yaml`, `tests/test_qc_speech.py` | `_asr_language` helper used by the ASR step; `compute.asr_language`. |
| W3 | - | `4aa3eb5` | `docs/IMPLEMENTATION_BRIEF.md` | Section 13 appended. |

## 2. Full suite (run once, at the end)

```
111 passed in 27.95s
111 tests collected in 1.26s
```
Matches the prediction (111 / 111).

## 3. Self-checks (verbatim; before this file was committed)

```
$ git log --oneline a4c3843..HEAD
4aa3eb5 docs(W3): contract section 13 (append only)
ce05b7a feat(W2): compute.asr_language for analysis (e.g. yue for Cantonese)
c61c93b test(W2): analysis passes the policy ASR language
986b870 feat(W1): speech.partner_words_rendered decided by audio signal; Whisper is information only
6bf76e2 test(W1): signal-based speech presence; e2e expects PASS
6b495c3 R5: brief

$ git status --short

$ git diff --numstat a4c3843..HEAD -- docs/IMPLEMENTATION_BRIEF.md agent/SKILL.md
10	0	docs/IMPLEMENTATION_BRIEF.md

$ git diff a4c3843..HEAD -- tests/test_qc_speech.py | grep "^-" | grep -v "^---"
```
`agent/SKILL.md` is unchanged (absent from numstat); the last grep is empty.

## 4. Parked

1. The W1 test commit contained a sample-count rounding slip in my own helper (`_files`); it was fixed in the W1 feature commit, so the test commit does not collect cleanly on its own (it fails at import anyway).
2. W2 test uses the brief's fallback (`_asr_language(policy)` helper) rather than driving the ASR step.
3. The renderer also adds a per-segment `gain_db` from the timeline; the brief's gain formula omits it and `signal_word_presence` has no segment access, so it is not subtracted (the level floor absorbs it).
4. `editorial` gained an optional `render_log` argument (passed from `run_qc`) to supply the loudness gains.
5. `word_present` compares over the overlap of the two arrays for each lag; the level is computed on the master slice as given (padded by the lag on both sides).
6. When `signal_check` is true and the ASR part is skipped (`asr_crosscheck: false`, or no ASR backend), the report holds only `signal` (plus `asr.error` when ASR failed); `planned/heard/spans/result` appear only when ASR ran.
7. `word_present` uses a Python loop over lags (about 1600 per word); speed on a feature-length film is untested.

## 5. What I did NOT verify

- The correlation threshold and the 0.98 line on a real master (the reviewer runs v004).
- Speed of the per-word lag search on hundreds of words.
- Whisper `yue` quality; the ASR cross-check path through a real model.
- The mutation list in brief section 5 was not run (reviewer's job).

## Coder response R01

Review `docs/R5_REVIEW.md` committed unchanged first (`8dce71b`). Same branch; nothing pushed or merged.

| Ruling | Test commit | Fix commit | What changed |
| --- | --- | --- | --- |
| R01-1 | `ca46f28` | `af22785` | `word_present` now follows the padded contract: `m` padded by L on both sides, windows `m[k:k+len(s)]` for k in 0..2L (full windows only), level from the centre window `m[L:L+len(s)]`, corr 0 when `m` is shorter than `s` or either side is silent. `signal_word_presence` unchanged (still pads by `lag`). |

Tests: the four existing `word_present` unit tests keep their names and intent, rebuilt with padded masters; added `test_word_present_finds_late_and_early_words` and `test_signal_presence_master_slightly_late`. Against the old code three tests failed (the small-lag, late/early and slightly-late ones); after the fix all pass.

Full suite (run once, at the end): `113 passed in 27.95s`; `pytest --collect-only -q`: `113 tests collected` (matches the prediction).

```
$ git status --short
(clean, taken before this section was committed)
$ git log --oneline c906d68..HEAD   (before the handover commit)
af22785 fix(R01-1): word_present searches the padded master window correctly
ca46f28 test(R01-1): word_present on the padded-master contract; late/early word tests
8dce71b docs: R5 review R01
```

Parked: none. Not verified: the real-footage run (the reviewer re-runs the harness); the lag loop is not vectorised (optional per the ruling).
