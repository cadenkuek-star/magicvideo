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
