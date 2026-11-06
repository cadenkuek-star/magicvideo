# Review log — magicvideo Round 4

## Review R01 — 2026-11-06

**Verdict: REVISE (narrow, tests only).** Head reviewed: `97aa274` on `r4/peaks-language` (base `486c485`).

### What I ran
- Fresh clone, `PYTHONPATH` pinned. Full suite: **102 passed** (my run). `git status` after the run was clean. The
  brief is byte-identical.
- **Real-audio test of W1** on the owner's actual `render/v003/master_audio.wav` (staged from the owner's PC),
  muxed with a black video of the same length, through the real `Renderer._encode_verified`:
  - Result: `{"passes": 2, "tp_first": 2.91, "tp_final": -1.54, "dips": [59.381], "global_db": 0.0, "note":
    "repaired"}` in 36.5 s.
  - Final measure: I −16.01 LUFS, TP −1.54 dBTP.
  - The first encode reproduces the owner's +2.91 exactly. One local dip at the measured spot fixes it, and
    loudness is untouched.
- Read every production diff (`render/audio.py`, `render/renderer.py`, `qc/runner.py`, `analysis/asr.py`,
  `plan/planner.py`, `cli.py`).
  - The dips go through a memory map.
  - The scan is chunked at 4× the sample rate.
  - The chapters read the same wav path that is repaired in place.
- 12 mutations: **10 killed, 2 survived.** Brief mutation 6 (chapters use the unrepaired wav) is not
  applicable: the repair rewrites the wav in place and the chapters read that path.

### Mutation table
| # | Mutation | Result |
| --- | --- | --- |
| 1 | constant dip instead of a raised cosine | killed (test_apply_dips_shape) |
| 2 | overlapping dips multiply | killed (test_apply_dips_shape) |
| 3 | merge keeps the first spot | killed (test_overshoot_times_merges_nearby_spots) |
| 4 | no re-measure after a pass | killed (test_encode_verified_repairs_then_stops) |
| 5 | global fallback ignores its cap | killed (test_encode_verified_gives_up) |
| 7 | spans merge across a language change | killed (test_language_spans_split_on_language_change) |
| 8 | language not passed to Whisper | killed (test_transcribe_passes_language) |
| 9 / 9b | camera flag ignored / camera skip removed | killed (test_edge_speech_skips_camera_originals) |
| 10 | `_utf8_console` not called in `main` | **SURVIVED** |
| 11 | "gave up" note never set | killed (test_encode_verified_gives_up) |
| 12 | `post_encode_check: false` ignored | **SURVIVED** |

### Rulings on parked items
P1–P8: ACCEPT, all eight.

### Rulings
- **R01-1.** Add `tests/test_cli.py::test_main_sets_utf8_console`:
  - monkeypatch `magicvideo.cli._utf8_console` with a spy;
  - call `cli.main(["--version"])` inside `pytest.raises(SystemExit)`;
  - assert the spy was called once.

  No production change.
- **R01-2.** Add `tests/test_true_peak.py::test_encode_verified_check_off`:
  - with `audio.post_encode_check: false`, `_encode_verified` encodes once;
  - `A.measure` and `A.scan_true_peaks` are never called (spies);
  - the log has `passes == 1`, `note == "ok"` and `tp_first is None`.

  No production change.

### Expected count and evidence for R02
**104 collected, 104 passed**, a prediction.

Evidence required:
- `test(R01-n)` commits;
- the full suite run once;
- `git log --oneline 97aa274..HEAD` and `git status --short`.

Append `## Coder response R01` to `docs/R4_HANDOVER.md`.
