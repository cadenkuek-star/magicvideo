# magicvideo — Round 4 brief: true peak after encoding, per-language speech QC, edge warnings, UTF-8 console

Status: owner approved the scope on 2026-11-06 ("go round 4"). Author: spec designer (Claude).
Base: `claude/vibrant-brahmagupta-yr5pu4` @ `486c485` (Round 3 merged). Branch: `r4/peaks-language`.
CLAUDE.md applies. Contract changes are appended to `docs/IMPLEMENTATION_BRIEF.md` (W5).

## 1. Evidence (Test_Trip_R2 v003, 2026-11-06, measured on the owner's PC)
- `loudness.true_peak` FAIL at +2.91 dBTP, although `render/v003/master_audio.wav` peaks at −2.0 dBTP (the
  render log says output TP −1.97).
  - The overshoot is created by the AAC encode: 2 decoded samples at film 59.3813 s reach 1.149 (+1.2 dBFS).
    The PCM there is 0.45; the source has a steep transient (Nyuto clip ≈ 15.3 s).
  - The rest of the film stays ≤ −1.7.
  - Encoding a 10 s window around that spot alone gives −1.2 dBTP. So the overshoot depends on encoder frame
    alignment and can only be judged on the actual final encode.
  - A raised-cosine dip of 3–5 dB over 30–60 ms at the spot brought the windowed encode to −1.8/−1.9 dBTP.
- `speech.partner_words_rendered` 0.71 (400/563).
  - The QC transcribes the whole master once, and Whisper keeps the language it detects at the start.
  - GF's English line at film 0:00–0:02 never appears in the heard tokens.
  - The biggest missing runs are in the Nyuto section (0:44–1:13), where the couple mixes Japanese into Chinese.
  - Each clip's own transcript already stores `language` (en/zh/ja).
- Edge warnings also fire for camera originals (026 DJI, "starts at the very beginning"). A camera original
  cannot be "trimmed too tight": recording simply started or stopped there.
- The owner's agent had to set `PYTHONUTF8=1`. magicvideo prints Japanese/Chinese warnings and curly quotes
  without making its console stream UTF-8.

## 2. Scope
In: W1–W5. Out: any change to the limiter or loudness targets, re-rendering video, new QC checks.

## 3. Work items (in order)

### W1 — Verify true peak after the AAC encode and repair locally
Policy (`audio:`):
```yaml
  post_encode_check: true         # measure true peak on the encoded master; repair overshoots locally
  post_encode_max_passes: 3
  post_encode_margin_db: 0.3      # aim this far below true_peak_dbtp
  post_encode_dip_win_ms: 40      # width of each local gain dip
  post_encode_global_max_db: 0.8  # if no overshoot spot can be found, lower everything by at most this
```
In `render/audio.py`, add pure numpy helpers:
1. `overshoot_times(x: np.ndarray, sr: int, threshold: float, merge_s: float = 0.05) -> list[float]`:
   - the times of samples (any channel) whose absolute value exceeds `threshold`;
   - spots closer than `merge_s` merged into one, keeping the time of the largest sample;
   - sorted.
2. `apply_dips(x: np.ndarray, sr: int, times: list[float], dip_db: float, win_ms: float) -> None`:
   - multiplies `x` in place by a raised-cosine envelope per time: unity at the window edges, `10**(-dip_db/20)`
     at the centre, window length `win_ms`;
   - overlapping windows take the minimum gain;
   - windows are clipped to the array bounds.
3. `scan_true_peaks(path: Path, sr: int, threshold: float, chunk_s: float = 30.0) -> list[float]`:
   - decodes `path` with ffmpeg at `4 * sr` (`-ar`, f32le, stereo) in `chunk_s` chunks (`-ss`/`-t`);
   - calls `overshoot_times` per chunk with `sr = 4 * sr`;
   - returns absolute times (merged across chunk edges with the same `merge_s`).

In `render/renderer.py`:

4. `_encode_master(wav, mvid, out) -> None`: the existing master mux command, unchanged, writing to `out`.
5. Replace the direct master encode with `_encode_verified(wav, mvid, master_path) -> dict`:
   - Encode to `self.work / "master_try.mp4"`, then measure TP with `A.measure(...)["TP"]`.
   - While `TP > true_peak_dbtp` and passes < max:
     - set `excess = TP - true_peak_dbtp + margin`;
     - set `times = A.scan_true_peaks(try, sr, 10**(true_peak_dbtp/20))`;
     - if `times`: convert the wav to raw f32 next to it, open it with `np.memmap` (mode `r+`, shape
       (n, 2)), call `apply_dips(..., excess, win_ms)`, flush, and convert back to the wav (ffmpeg, pcm_f32le);
     - else if `excess <= global_max`: apply `volume=-{excess:.3f}dB` to the wav;
     - else stop.
     - Re-encode and re-measure.
   - Finally move `master_try.mp4` to `master_path` (`os.replace`). The chapters are then encoded from the
     **repaired** wav (same command as today).
   - Return the log
     `{"passes": int, "tp_first": float, "tp_final": float, "dips": [times rounded 3 dp], "global_db": float,
     "note": str}`. The note is `"ok"`, `"repaired"` or `"gave up: TP still above limit"`.
   - Store it as `self.log["loudness"]["post_encode"]`.
   - With `post_encode_check: false`, encode once as today.
6. The "outputs are never overwritten" check stays where it is; only `master_try.mp4` in the work dir is
   rewritten.

Tests (new `tests/test_true_peak.py`, numpy only unless stated):
- `test_overshoot_times_merges_nearby_spots` (two samples 10 ms apart → one time at the larger; a third 200 ms
  later → second time)
- `test_apply_dips_shape` (centre gain = −dip dB within 1e-3; unity at ±win/2; samples outside untouched;
  overlapping dips take the minimum)
- `test_encode_verified_repairs_then_stops`: monkeypatch `A.measure` to return TP +2.9, then −1.9;
  `scan_true_peaks` to return `[1.0]`; patch `_encode_master` to touch the output. Expect
  `passes == 2`, `note == "repaired"`, `dips == [1.0]`, and `apply_dips` was called once (spy). Use a tiny real
  wav made with numpy + ffmpeg.
- `test_encode_verified_global_fallback` (no times found, excess 0.5 → `global_db == 0.5`)
- `test_encode_verified_gives_up` (TP stays +3.0 for max passes, or excess > global_max with no times →
  `note` starts with "gave up")

### W2 — Speech QC transcribes each part in its own language
1. `analysis/asr.py::transcribe(audio_path, policy, language: str | None = None)`: pass
   `language=language` to `model.transcribe`. Default behaviour is unchanged.
2. `qc/runner.py::language_spans(segments: list[dict], clip_lang: dict[str, str | None], fps: float,
   merge_gap_s: float) -> list[dict]`:
   - takes the timeline segments that `collect_planned_words` drew planned words from (pass them in);
   - returns `[{"t0", "t1", "lang"}]` in master seconds, in film order;
   - consecutive segments with the same `lang` and a gap ≤ `merge_gap_s` are merged.
3. In `editorial`, instead of one transcription of the whole master:
   - for each span, cut `[t0 - 0.3, t1 + 0.3]` from the master to a 16 kHz wav (ffmpeg `-ss`/`-t`, clamped to
     the master);
   - transcribe it with `language=span["lang"]` (None → auto);
   - concatenate the heard words in film order;
   - delete each temp wav.

   Then `rendered_speech_check` as today. `clip_lang` comes from each clip's analysis `transcript.json`
   `language`.
4. Policy (`qc:`): `speech_span_merge_gap_s: 2.0`. The speech report gains `"spans": [...]`.

Tests (`tests/test_qc_speech.py`):
- `test_language_spans_merge_same_language` (two adjacent zh segments 1 s apart → one span)
- `test_language_spans_split_on_language_change` (en, zh, zh → two spans)
- `test_transcribe_passes_language`: monkeypatch `asr.load_model` to return a stub whose `transcribe` records
  kwargs and yields no segments; `transcribe(path, policy, language="en")` → recorded `language == "en"`.

### W3 — Edge warnings only for trimmed or exported files
- Policy: extend `moments.edge_speech` with `camera_originals: false  # camera-named originals can't be trimmed
  too tight`.
- In `edge_speech_warnings`, skip a clip whose `clip["capture_source"] == "filename"` (its capture time came
  from a camera file name such as `DJI_…`/`VID_…`) unless `camera_originals` is true.

Tests (`tests/test_moments.py`):
- `test_edge_speech_skips_camera_originals` (`capture_source "filename"` → no warning for a 21.7/23.1 case)
- `test_edge_speech_still_warns_for_exports` (`capture_source "mtime"` → warns)

### W4 — UTF-8 console
- `cli.py`: add `_utf8_console(streams=None)`. For `sys.stdout` and `sys.stderr` (or the given streams), call
  `stream.reconfigure(encoding="utf-8", errors="replace")` when the stream has `reconfigure`; never raise.
- Call it first thing in `main`, before `setup_logging`.
- Test `tests/test_cli.py::test_utf8_console_handles_japanese`: a `io.TextIOWrapper(io.BytesIO(),
  encoding="cp1252")` passed to `_utf8_console([w])`. Writing "ご視聴“x”" then must not raise, and the bytes decode
  as UTF-8.

### W5 — Contract and skill
- Append `## 12. Round 4 changes` to `docs/IMPLEMENTATION_BRIEF.md`: the post-encode true-peak repair and its
  policy keys and log; per-language QC spans; the camera-original edge rule; UTF-8 console. Append only.
- `agent/SKILL.md`: no change.

## 4. Must get right
1. The repair touches only short windows around measured overshoots. It never re-limits the whole film. The
   global fallback is capped at `post_encode_global_max_db`.
2. The final master and the chapters use the same repaired wav.
3. Memory: a feature-length wav must never be loaded whole (memmap for dips, chunked scan).
4. If the repair cannot get under the limit, QC still FAILs honestly. The log says "gave up".
5. `transcribe` without `language` behaves exactly as before.

## 5. Mutation intent
1. Dips applied as a constant gain instead of a raised cosine.
2. Overlapping dips multiply instead of taking the minimum.
3. Overshoot merge keeps the first spot, not the largest.
4. The repair loop does not re-measure after a pass.
5. The global fallback ignores `post_encode_global_max_db`.
6. Chapters use the unrepaired wav.
7. `language_spans` merges across a language change.
8. `language` not passed to `model.transcribe`.
9. The camera-original skip ignores the policy flag.
10. `_utf8_console` missing from `main`.

## 6. Expected count (prediction)
Baseline 91. New: W1 5, W2 3, W3 2, W4 1 = 11. **102 collected, 102 passed.**

## 7. Owner acceptance (after merge)
Run `magicvideo plan`, `magicvideo render` and `magicvideo qc` on Test_Trip_R2 (v004). Expect:
- `loudness.true_peak` ≤ −1.5 dBTP, with `post_encode.note` = "repaired" or "ok" in the render log;
- integrated loudness still −16 ± 1;
- `speech.partner_words_rendered` higher than 0.71, with the English line at 0:00 heard;
- no edge warnings for 026 or other camera originals;
- no more need for `PYTHONUTF8`.

## 8. Assumptions (dated 2026-11-06)
- **A1:** A 3–5 dB dip over ~40 ms at an isolated click is inaudible in practice and acceptable.
- **A2:** Short spans transcribed separately are acceptable for QC (it is a check, not the edit).
- **A3:** Camera-named files are originals; the owner trims only exported/compilation files.

## 9. Not verified
- That 3 passes always suffice on long films (frame alignment shifts after each repair).
- Whisper accuracy on short per-language spans of the owner's footage.
- Behaviour when a camera original was trimmed by someone (the reviewer trimmed 026/034 for the test set; their
  edge warnings will now be suppressed).
