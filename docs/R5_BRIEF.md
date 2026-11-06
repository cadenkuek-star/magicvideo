# magicvideo — Round 5 brief: audio-signal speech check, Cantonese ASR option

Status: owner chose option A on 2026-11-06 ("A is fine, let's do it"), and said the couple speaks Cantonese.
Author: spec designer (Claude). Base: `claude/vibrant-brahmagupta-yr5pu4` @ `a4c3843` (Round 4 merged).
Branch: `r5/signal-speech-qc`. CLAUDE.md applies. Contract changes are appended to
`docs/IMPLEMENTATION_BRIEF.md` (W3).

## 1. Evidence (Test_Trip_R2 v004)
- `speech.partner_words_rendered` 0.7123 with per-language spans. The remaining misses are ASR-versus-ASR noise:
  - Repeats are collapsed differently by each pass: 一级棒 一级棒 / 好吃 ×4 at 1:08–1:12, and 她比较年轻 ×2 at
    3:49–3:53.
  - 3–5 character fragments are spread across Kanazawa, which the owner listened to and confirmed fully audible.
  - The couple speaks **Cantonese**. Whisper labels it `zh` and writes standard Chinese, inconsistently between
    passes.
- The QC exists to catch render faults: missing, muted, shifted or masked speech. magicvideo adds no music, so
  the master's dialogue is the source audio with known gains, an 8 ms edge fade, limiting and AAC. A direct
  waveform comparison per planned word is exact, language-free and deterministic.

## 2. Scope
In: W1–W3. Out: re-running analysis on the owner's trips (the owner decides when, see A2); any change to
planning.

## 3. Work items

### W1 — `speech.partner_words_rendered` by audio signal; Whisper becomes information only
Policy (`qc:`):
```yaml
  signal_check: true              # decide speech.partner_words_rendered by comparing master audio with the source
  signal_sr: 16000
  signal_min_corr: 0.6            # normalised correlation (best lag) for a word to count as present
  signal_max_lag_s: 0.05
  signal_min_level_db: -12.0      # master word level relative to the source word level, after known gains
  rendered_signal_match_min: 0.98 # pass line for the signal method
  asr_crosscheck: true            # still run the Whisper comparison when available, as information
```
In `qc/runner.py`:
1. `collect_planned_word_spans(convs, cds, seg_spans, timeline, fps, policy) -> list[dict]`. It walks the same
   words as `collect_planned_words` (leave that function and its test unchanged) and returns, in film order:
   `{"w", "clip_id", "src_t0", "src_t1", "m_t0", "m_t1", "seg_id"}`.
   - `m_t0`/`m_t1` are the master times of the word edges, mapped through the segment that covers the word's
     midpoint (`start_frame/fps + (t - src_in)`).
   - `seg_id` is that segment's `id`.
2. `word_present(m: np.ndarray, s: np.ndarray, sr: int, max_lag_s: float, min_corr: float, min_level_db: float,
   gain_db: float) -> tuple[bool, float, float]`. Both arrays are mono float. It returns
   `(present, best_corr, level_db)`:
   - `level_db = 20*log10(rms(m)/rms(s)) - gain_db` (rms floor 1e-9);
   - `best_corr` is the maximum normalised correlation of `m` against `s` over integer lags within
     ±`max_lag_s*sr` (zero-mean both; when either is silent, the corr is 0);
   - `present = best_corr >= min_corr and level_db >= min_level_db`.
3. `signal_word_presence(master: Path, words: list[dict], inventory: dict, render_log: dict, policy) -> dict`.
   - Group the words by `seg_id`. For each group, decode with ffmpeg as mono f32 at `signal_sr`:
     - the master span `[min m_t0 - lag, max m_t1 + lag]`;
     - the source span `[min src_t0 - lag, max src_t1 + lag]` from the clip's `render_path`.
   - Slice each word out of both, padded by `lag` on the master side.
   - `gain_db` = that segment's `loudness.dialogue_gains_db[seg_id]` (0 if absent) + `loudness.gain_db`
     + `loudness.post_encode.global_db` negated. Missing keys count as 0. The limiter is ignored; the level floor
     absorbs it.
   - Return `{"present", "total", "ratio", "absent_runs": [...], "words": [{"m_t0", "w", "present", "corr",
     "level_db"}]}`. `absent_runs` are built exactly like `missing_runs` (≥ `speech_missing_run_min`
     consecutive absent words; times = first/last `m_t0`, 0.1 s). Corr and level are rounded to 3 dp.
   - It never loads the whole master: decode per group.
4. In `editorial`, the check `speech.partner_words_rendered`:
   - When `signal_check` is true and there are planned words: status = PASS if `ratio >= rendered_signal_match_min`
     else FAIL; value = ratio (4 dp); detail = `"{present}/{total} planned partner words present in the master
     audio (signal match); {n} absent runs (see <file>)"`. When the ASR cross-check ran, append
     `"; Whisper cross-check {r:.2f} (information)"`.
   - When `asr_crosscheck` is true and ASR is available, run the existing per-language Whisper comparison as
     today, but only for the report and the detail suffix; it no longer decides the status. A `BackendMissing`
     or any error in it is recorded in the report as `"asr": {"error": "..."}`; it does not SKIP the check.
   - When `signal_check` is false, behave exactly as Round 4 (Whisper decides).
5. The speech report `qc/<stem>_speech.json` gains `"signal": <the signal dict>`. The keys `planned`, `heard`,
   `result` and `spans` stay when the ASR part ran.
6. `tests/test_e2e.py::test_plan_render_qc` (synthetic tone audio, ASR patched out):
   - replace the assertion `verdict == "INCOMPLETE" and "speech.partner_words_rendered" in skipped` with
     `status of speech.partner_words_rendered == "PASS"`, and
     `verdict == ("INCOMPLETE" if skipped else "PASS")`;
   - keep the `pytest.raises` part that follows unchanged.

Tests (new `tests/test_signal_speech.py`):
- `test_word_present_with_gain_and_small_lag` (source = noise burst; master = source × 0.5 shifted 10 ms;
  gain_db −6.02 → present, corr > 0.9)
- `test_word_absent_when_master_silent`
- `test_word_absent_when_shifted_far` (300 ms shift with max_lag 0.05 → absent)
- `test_word_absent_below_level_floor` (master = source × 10^(−20/20), gain_db 0 → absent)
- `test_signal_presence_on_real_files`: with ffmpeg, make a 3 s source wav (noise bursts at 0.5–0.8 s and
  1.5–1.9 s) and a "master" mp4 (black video + AAC) where the source audio starts at master 1.0 s. Two words
  mapped accordingly, one segment `s1` → ratio 1.0.
- `test_signal_presence_detects_muted_master`: the same, but the master audio is silent → ratio 0.0, with one
  absent run when `speech_missing_run_min` is 2.

### W2 — Optional ASR language for analysis (Cantonese)
- Policy (`compute:`): `asr_language: null  # e.g. yue for Cantonese; null = auto-detect. Re-run analyze --force
  --steps asr to apply`.
- `analysis/runner.py`: pass `language=policy("compute.asr_language")` to `asr.transcribe`.
- In QC W2/R4 spans, a clip whose transcript language is `yue` is transcribed with `yue`. This works through
  `clip_lang` already; just make sure it is not filtered.
- Test `tests/test_qc_speech.py::test_analysis_passes_policy_language`: monkeypatch `asr.transcribe` to record
  kwargs; call the runner's ASR step for one synthetic clip with `compute.asr_language: yue` → recorded
  `language == "yue"`. If the ASR step cannot be called in isolation, test a small extracted helper
  `_asr_language(policy) -> str | None` instead, and make the runner use it.

### W3 — Contract
Append `## 13. Round 5 changes` to `docs/IMPLEMENTATION_BRIEF.md`: the signal method, its policy keys and report
field; Whisper as information only; `compute.asr_language`. Append only. `agent/SKILL.md`: no change.

## 4. Must get right
1. A muted, shifted or missing word must FAIL the check. A correct render must pass at ≥ 0.98 regardless of
   language.
2. The whole master is never loaded at once.
3. Whisper errors never change the verdict when `signal_check` is true.
4. With `signal_check: false`, behaviour is identical to Round 4.
5. `collect_planned_words` and its R3 test stay unchanged.

## 5. Mutation intent
1. Correlation computed without a lag search (lag 0 only).
2. The level floor ignored.
3. Gain from `dialogue_gains_db` not subtracted.
4. A silent window gives corr NaN treated as present.
5. Words decoded from the wrong master offset (`m_t0` not used).
6. The verdict still decided by the Whisper ratio.
7. The ASR language from policy not passed.

## 6. Expected count (prediction)
Baseline 104. New: W1 6, W2 1 = 7. The e2e test is modified, not added. **111 collected, 111 passed.**

## 7. Owner acceptance
Run `magicvideo qc` on Test_Trip_R2. This works on the existing v004 master; no re-render is needed, because QC
writes a new qc file.
- Expect `speech.partner_words_rendered` PASS ≥ 0.98, with the Whisper cross-check ~0.71 shown as information.
- If any absent run is listed, it is a real audio fault at that film time; the English line at 0:00 will be
  answered by this.
- Optionally, for better speech protection on Cantonese trips, set `compute.asr_language: yue` in the trip's
  `policy.yaml` and re-run `magicvideo analyze <work> --force --steps asr` (slow on CPU), then plan again.

## 8. Assumptions (dated 2026-11-06)
- **A1:** Without music in magicvideo's render, waveform correlation is a valid proof of presence. If music is
  ever mixed in by magicvideo, revisit.
- **A2:** `yue` is offered as an option, not the default; re-running ASR is the owner's call (slow on CPU).

## 9. Not verified
- The correlation threshold on the owner's real master. The reviewer will run the new check on v004 before
  approving.
- Whisper `yue` output quality on the owner's footage.
