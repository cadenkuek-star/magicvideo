# R4 handover (Coder A)

Branch `r4/peaks-language` from `486c485`. Nothing pushed or merged.

## 1. Work items

| Item | Test commit | Feature commit | Files | What changed |
| --- | --- | --- | --- | --- |
| Step 0 | - | `f45cf4d` | `docs/R4_BRIEF.md` | Brief committed unchanged. |
| W1 | `7438c87` | `d36e4ef` | `render/audio.py`, `render/renderer.py`, `default_policy.yaml`, `tests/test_true_peak.py` | `overshoot_times`, `apply_dips`, `scan_true_peaks`; `_encode_master`, `_encode_verified` (+ `_dip_wav`, memmap), `loudness.post_encode` log, five `audio.post_encode_*` keys. |
| W2 | `105e495` | `8a02d42` | `analysis/asr.py`, `qc/runner.py`, `default_policy.yaml`, `tests/test_qc_speech.py` | `transcribe(..., language)`, `language_spans`, per-span transcription of the master, `spans` in the speech report, `qc.speech_span_merge_gap_s`. |
| W3 | `4311369` | `370a193` | `plan/planner.py`, `default_policy.yaml`, `tests/test_moments.py` | Edge warnings skip `capture_source == "filename"` unless `camera_originals`. |
| W4 | `ec0ed5f` | `67a0359` | `cli.py`, `tests/test_cli.py` | `_utf8_console`, called first in `main`. |
| W5 | - | `c93a5d0` | `docs/IMPLEMENTATION_BRIEF.md` | Section 12 appended; `agent/SKILL.md` unchanged. |

## 2. Full suite (run once, at the end)

```
102 passed in 22.23s
102 tests collected in 1.00s
```
Matches the prediction (102 / 102).

## 3. Self-checks (verbatim; before this file was committed)

```
$ git log --oneline 486c485..HEAD
c93a5d0 docs(W5): contract section 12 (append only)
67a0359 feat(W4): UTF-8 console at the start of main
ec0ed5f test(W4): UTF-8 console
370a193 feat(W3): edge warnings only for trimmed or exported files
4311369 test(W3): edge warnings skip camera originals
8a02d42 feat(W2): speech QC transcribes each span in its own language
105e495 test(W2): per-language spans and language passed to Whisper
d36e4ef feat(W1): verify true peak after the AAC encode and repair overshoots locally
7438c87 test(W1): post-encode true-peak repair helpers and loop
f45cf4d R4: brief

$ git status --short

$ git diff --numstat 486c485..HEAD -- docs/IMPLEMENTATION_BRIEF.md agent/SKILL.md
12	0	docs/IMPLEMENTATION_BRIEF.md

$ git grep -n "_utf8_console" -- magicvideo/cli.py
magicvideo/cli.py:138:def _utf8_console(streams=None) -> None:
magicvideo/cli.py:150:    _utf8_console()
```
`agent/SKILL.md` does not appear in the numstat (unchanged); the brief has 0 deletions.

## 4. Parked

1. W1: `passes` counts encodes (first encode = 1), so the repair test's "TP +2.9 then -1.9" gives `passes == 2`. `note` is `"repaired"` whenever more than one pass ran and TP ended within the limit.
2. W1: `_encode_verified` is a Renderer method (tests build a Renderer with `object.__new__` and patch `Renderer._encode_master`, `A.measure`, `A.scan_true_peaks`, `A.apply_dips`). `scan_true_peaks` also takes an optional `merge_s` argument (default 0.05).
3. W1: `dips` accumulates the rounded times of all passes (sorted, de-duplicated); `global_db` is the sum of global reductions.
4. W2: `collect_planned_words` keeps its return signature (R3 test). To get "the segments planned words were drawn from" the QC selects timeline segments whose master time range contains a planned word's master time.
5. W2: each span is cut at `[t0-0.3, t1+0.3]` with the start clamped at 0; the end is not clamped (ffmpeg stops at the end of the file).
6. W2: a clip whose transcript has no `language` gets `lang None` (auto); None spans merge with other None spans.
7. W4: `test_utf8_console_handles_japanese` also checks that a stream without `reconfigure` does not raise.
8. The `test_apply_dips_shape` overlap assertion checks the minimum rule at the centre and 50 samples away (a product of two windows would be lower there).

## 5. What I did NOT verify

- A real AAC encode: `_encode_master` is patched in the tests and `A.measure` is stubbed; `scan_true_peaks` was not run on a real encode (only the numpy helpers and the loop logic are tested).
- That 3 passes suffice on long films; the speed and memory of the chunked scan on a feature-length master.
- Per-span Whisper accuracy; `ffmpeg.run` slicing on real masters.
- The mutation list in brief section 5 was not run (reviewer's job).
