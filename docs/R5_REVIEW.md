# Review log — magicvideo Round 5

## Review R01 — 2026-11-06

**Verdict: REVISE (one defect, found on real footage).** Head reviewed: `c906d68` on `r5/signal-speech-qc` (base
`a4c3843`).

### What I ran
- Fresh clone, `PYTHONPATH` pinned. Full suite: **111 passed** (my run). `git status` after the run was clean.
  The brief is byte-identical.
- Read the production diff (`qc/runner.py`, `analysis/runner.py`, the policy).
- **Real-footage run.** The branch's `magicvideo` package was copied to the owner's PC and run in the Linux
  shell there. It computed `collect_planned_word_spans` and `signal_word_presence` on the owner's actual
  Test_Trip_R2 v004 master and source clips, with paths remapped. Harness: `C:\Travel\scratch\r5_realcheck.py`.
  - **As built: 150/458 present, ratio 0.3275**, in 18.8 s. The correct film would FAIL. Absent words show
    corr 0.2–0.6 with levels within ±2.5 dB, so the audio is there but the correlation misses it.
  - **The same run with the lag search corrected (below): 458/458 present, ratio 1.0.** Corr ≈ 0.99, levels
    −2.5 to +1.9 dB. GF's English line at film 0:00 ("This is what it looks like") is present at corr 0.999+.

### Finding F1 (defect)
`signal_word_presence` passes a master slice padded by `lag` on **both** sides, but `word_present` searches
k ∈ [−L, L] as if the arrays were aligned and unpadded.
- In a padded slice the true alignment is k = +L, so the search covers only "master on time or early".
- Its negative half compares partial overlaps.
- Any word that sits even slightly late in the master is reported absent; on real AAC/limited audio most words
  failed.
- The synthetic tests passed because they build unpadded arrays.

The brief was ambiguous about the padding contract. This is my spec gap as much as the code's.

### Rulings
- **R01-1.** Define `word_present` on the padded contract:
  - `m` is the master slice padded by `L = round(max_lag_s*sr)` samples on both sides of the word.
  - The search compares `s` with `m[k:k+len(s)]` for every k in `0..2L` with `k + len(s) <= len(m)` (full
    windows only), zero-mean both, normalised correlation, best over k.
  - The level uses the centre window `m[L:L+len(s)]` against `s`, minus `gain_db`.
  - If `len(m) < len(s)` or either side is silent, then corr is 0 and the word is absent.
  - `signal_word_presence` already pads by `lag` on the master side; keep that. Vectorising is optional; the
    result must be identical.

  Tests in `tests/test_signal_speech.py`:
  - Adapt the existing `word_present` unit tests to the padded contract (build `m` padded by L on both sides).
    Their intent stays the same: gain + small lag present, silent absent, 300 ms absent, level floor absent.
  - Add `test_word_present_finds_late_and_early_words`: the same source word placed 20 ms late and 20 ms early
    inside a padded master (lag 0.05) → both present with corr > 0.95.
  - Add `test_signal_presence_master_slightly_late`: the real-file test variant where the master audio starts
    20 ms later than the mapping says → ratio 1.0.

### Rulings on parked items
- **P1, P2, P4, P6:** ACCEPT.
- **P3** (per-segment timeline `gain_db` not subtracted): ACCEPT. It is 0.0 on every v004 segment, and the
  level floor covers it.
- **P5:** superseded by R01-1.
- **P7** (speed): ACCEPT. 18.8 s for 458 words on the owner's PC.

### Expected count and evidence for R02
**113 collected, 113 passed** (111 + 2 new; the adapted tests keep their names), a prediction.

Evidence required:
- a `test(R01-1)` commit, then a `fix(R01-1)` commit;
- the full suite run once;
- `git log --oneline c906d68..HEAD` and `git status --short`.

Append `## Coder response R01` to `docs/R5_HANDOVER.md`. The reviewer will re-run the real-footage harness.

## Review R02 — 2026-11-06

**Verdict: REVISE (narrow, tests only).** Head reviewed: `b109fc0`.

### What I ran
- Fresh clone. Full suite: **113 passed** (my run). `git status` after the run was clean. R01 of this log is
  unchanged.
- **Real footage, fixed code** (owner's PC, harness `C:\Travel\scratch\r5_realcheck2.py`):
  - v004: **458/458 present, ratio 1.0**; corr p5 0.996, median 1.0; 10.8 s.
  - Negative controls on the same real film:
    - master mapping shifted +0.3 s → 4/458 present;
    - mapping shifted −0.3 s → 6/458;
    - expected gain raised by 20 dB → 0/458.

  The check passes a correct film and fails shifted or attenuated speech.
- 8 mutations: **5 killed, 3 survived.**

| # | Mutation | Result |
| --- | --- | --- |
| 1 | lag 0 only | killed (test_word_present_with_gain_and_small_lag) |
| 2 | level floor ignored | killed (test_word_absent_below_level_floor) |
| 3 | `dialogue_gains_db` not used | **SURVIVED** |
| 4 | silent window counted present | killed (test_word_absent_when_master_silent) |
| 5 | wrong master offset | killed (test_e2e::test_plan_render_qc) |
| 6 | verdict decided by Whisper | killed (test_e2e::test_plan_render_qc) |
| 7 | analysis runner does not pass the policy language | **SURVIVED** (only the helper is tested) |
| 8 | level from the whole padded slice instead of the centre window | **SURVIVED** |

### Rulings (tests only; no production change)
- **R02-1** `tests/test_signal_speech.py::test_signal_presence_uses_dialogue_gain`: the real-file setup with the
  master audio at −20 dB.
  - `render_log = {"loudness": {"dialogue_gains_db": {"s1": -20.0}}}` → ratio 1.0.
  - The same with `render_log = {}` → ratio 0.0.
- **R02-2** `tests/test_qc_speech.py::test_analysis_runner_passes_policy_language`:
  - make one tiny synthetic clip with ffmpeg (tone, about 2 s) and a project via `Project.init`;
  - set `compute.asr_language: yue` in the trip's `policy.yaml`;
  - monkeypatch `magicvideo.analysis.asr.load_model` to return `object()`, and `asr.transcribe` to record kwargs
    and return `{"backend": "x", "language": "yue", "words": [], "segments": []}`;
  - run `run_analysis(project, ["asr"])` → recorded `language == "yue"`;
  - if `run_analysis` needs other steps first, include only the steps required and say so in the handover.
- **R02-3** `tests/test_signal_speech.py::test_word_present_level_uses_centre_window`:
  - `s` = a noise burst;
  - `m` = padding filled with loud independent noise (same RMS as `s`), and the centre = `s × 0.05`;
  - with lag 0.05, min_corr 0.6, min_level −12 and gain 0 → absent (level ≈ −26 dB).

### Expected count and evidence for R03
**116 collected, 116 passed**, a prediction.

Evidence required:
- three `test(R02-n)` commits;
- the full suite run once;
- `git log --oneline b109fc0..HEAD` and `git status --short`.

Append `## Coder response R02` to `docs/R5_HANDOVER.md`.
