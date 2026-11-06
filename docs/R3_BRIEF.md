# magicvideo — Round 3 brief: honest speech QC, hallucinations, clip-edge warnings, Insta360 from previews

Status: owner approved the scope on 2026-11-06 ("go ahead with round 3"). Author: spec designer (Claude).
Base: `claude/vibrant-brahmagupta-yr5pu4` @ `2c0f6d6` (Round 2 merged). Branch: `r3/speech-qc-x6`.
CLAUDE.md applies (policy keys for every threshold, deterministic planner, lazy optional imports, Windows paths).
Where this brief changes a contract, append to `docs/IMPLEMENTATION_BRIEF.md` (W6).

## 1. Evidence (owner's acceptance run, Test_Trip_R2, 2026-11-06)
- QC `speech.partner_words_rendered` = 0.619 (286/462) FAIL. The owner listened to the whole Kanazawa section
  (film 1:52.7–5:02.6) and every stretch is clearly audible. So the check undercounts:
  - It compares Whisper *word* tokens. Chinese word splitting changes between passes ("很多 年" vs "很多年").
  - Whisper mixes scripts inside one clip: Kanazawa source 144–171 s came out Simplified (几, 说, 来), the rest
    Traditional (們, 這, 來).
  - The QC throws away what it heard, so a failure cannot be traced.
- Film 0:43: GF is cut mid-sentence because the source file `01_Arrival_La_Paz…mp4` ends at 23.1 s. The last
  transcribed word ends at 21.7 s. Nothing warned.
- `01_Arrival_and_City_Vistas_v002.mp4` 1.8–4.9 s became a protected "couple conversation" whose only text is
  ご視聴ありがとうございました ("thank you for watching"), a classic Whisper hallucination.
  - Its mean word probability is **0.75**, while real couple speech often scores 0.04–0.45 (p10 = 0.37 over 122
    segments). So a word-probability rule would delete real dialogue: **do not use word probability**.
  - Stored segments today have only `t0`, `t1`, `text`.
- Insta360: unstitched `.insv` recordings are dropped from the plan unless the owner exports every one from Studio
  first (`plan/planner.py::plannable_clips`). The owner wants to export only what the film uses.
- R2 parked: `ingest.insta360_key` and `detect_camera` still use anchored `.match`, so `026_VID_…insv` would not
  group. `qc/runner.py` imports `PARTNERS` unused.

## 2. Scope
In: W1–W6. Out: an enrollment web page, automatic voice re-enrollment, music, the Media SDK stitcher.

## 3. Work items (in order)

### W1 — Rendered-speech QC that is fair to Chinese and Japanese
Policy (`qc:`): `fold_chinese_script: true  # compare Simplified and Traditional as the same (needs zhconv)` and
`speech_missing_run_min: 3  # report runs of at least this many unheard planned tokens`.
Dependency: add `zh = ["zhconv>=1.4"]` to `[project.optional-dependencies]` and add `zh` to `all`. Import it
lazily inside the function.

In `qc/runner.py`:
1. `speech_tokens(words: list[str], fold: bool) -> list[str]`:
   - Normalise each word with the existing `_norm`. Drop empties.
   - A word that contains any CJK Unified Ideograph (U+3400–U+4DBF, U+4E00–U+9FFF), Hiragana (U+3040–U+309F) or
     Katakana (U+30A0–U+30FF) is split into single characters. Any Latin letters or digits inside it are kept as
     one token per run.
   - Other words stay whole.
   - When `fold` is true and zhconv imports, each CJK character is converted with
     `zhconv.convert(ch, "zh-hans")`.
2. `rendered_speech_check(planned: list[tuple[str, float]], heard: list[str], fold: bool, min_run: int) ->
   dict`.
   - `planned` is (word, master_time_s) in film order. Tokenise both sides with `speech_tokens`; each planned
     token keeps the master time of its word.
   - Match with `difflib.SequenceMatcher(autojunk=False)`.
   - Return `{"ratio", "matched", "total", "folded": bool, "missing_runs": [{"t0", "t1", "text"}]}`. A missing run
     is a maximal run of ≥ `min_run` consecutive unmatched planned tokens; `t0`/`t1` are the master times of its
     first and last token, rounded to 0.1 s.
3. In `editorial`, record each planned word's master time: the segment of the same `clip_id` whose source span
   covers the word's midpoint, then `start_frame / fps + (mid - src_in)`.
   - Order planned words by master time (today they are ordered by `abs_t0`).
   - Call `rendered_speech_check`.
   - The check's detail becomes `"{matched}/{total} planned partner characters/words heard; {n} unheard runs (see
     <file>)"`, plus `"; script folding off (pip install zhconv)"` when folding was requested but unavailable.
4. Write `qc/<master stem>_speech.json`: `{"planned": [...tokens], "heard": [...tokens], "result": <the dict>}`.
   Only `magicvideo qc` writes it (CLAUDE.md).
5. Remove the unused `PARTNERS` import.

Tests (new `tests/test_qc_speech.py`):
- `test_cjk_words_split_into_characters`: `["很多年", "Akita是"]` → `["很","多","年","akita","是"]`.
- `test_latin_words_stay_whole`: `["Hello", "world's"]` → `["hello","world's"]`.
- `test_scripts_fold_together`: `pytest.importorskip("zhconv")`; planned `說來` vs heard `说来` → ratio 1.0.
- `test_regrouped_words_still_match`: planned `["很多年"]` vs heard `["很多","年"]` → ratio 1.0.
- `test_missing_runs_reported_with_master_times`: 6 planned tokens at times 10.0–15.0, heard missing tokens 2–4
  → one run with t0 11.0, t1 13.0. With `min_run` 4 → no runs.

### W2 — Ignore Whisper hallucinations
Policy (new top-level `asr_filter:`):
```yaml
asr_filter:
  enabled: true
  # whole-segment texts Whisper invents on silence/music; compared after removing spaces and punctuation, lowercase
  phrases: ["ご視聴ありがとうございました", "ご視聴ありがとうございます", "thankyouforwatching",
            "thanksforwatching", "pleasesubscribe", "subtitlesbytheamaraorgcommunity", "字幕由amaraorg社区提供",
            "请不吝点赞订阅转发打赏支持明镜与点点栏目", "謝謝觀看", "谢谢观看", "感謝收看", "感谢收看"]
  no_speech_prob_min: 0.6      # with avg_logprob_max: both must hold (only when the segment stores them)
  avg_logprob_max: -1.0
```
1. `analysis/asr.py::transcribe`: store per segment also `no_speech_prob`, `avg_logprob` and `compression_ratio`
   (floats, rounded to 4 dp). Existing transcripts lack them; the code must work without them.
2. `plan/data.py`: `drop_hallucinations(words, segments, windows, emb, policy) -> tuple[words, windows, emb,
   dropped]`.
   - Assign a word to the first segment with `seg.t0 - 0.01 <= w.t0 < seg.t1 + 0.01`.
   - A segment is a hallucination when, with the filter enabled:
     - its text, normalised (lowercase; remove whitespace and every char whose `unicodedata.category` starts with
       P or S), is in the normalised `phrases`; or
     - it stores both scores and `no_speech_prob >= no_speech_prob_min` and `avg_logprob <= avg_logprob_max`.
   - Remove those words. Remap each window's `w0`/`w1` to the new indices; drop windows left with no words, and
     their `emb` rows.
   - `dropped = [{"t0", "t1", "text"}]` per removed segment.
   - With the filter disabled, return the inputs unchanged.
3. `load_clip`: apply it right after loading the transcript and voices, before labels and turns. Store
   `cd.dropped_speech`.
4. `planner.make_plan`: add one warning per dropped segment of a plannable clip:
   `"<rel_path> <t0>–<t1>s: ignored likely Whisper hallucination “<text>”"` (1 dp).

Tests (new `tests/test_asr_filter.py`):
- `test_known_phrase_segment_dropped` (with punctuation and spaces in the text)
- `test_score_rule_needs_both_scores` (high no_speech + low logprob → dropped; only one of them → kept; missing
  keys → kept)
- `test_real_speech_kept_even_with_low_word_probability` (word p 0.04 → kept)
- `test_windows_and_embeddings_remapped` (a 3-window clip where the middle segment is dropped: indices shift and
  the emb rows match)
- `test_filter_disabled_changes_nothing`

### W3 — Warn when speech runs into the edge of a source file
Policy (`moments:`): `edge_speech: {start_s: 0.3, end_s: 1.5}  # warn if couple speech starts/ends this close to
a clip edge`.
- `plan/planner.py::edge_speech_warnings(selected: list[Moment], cds: dict, policy) -> list[str]`, for each
  selected `conversation` moment:
  - If its last word's `t1 >= clip duration - end_s`, warn:
    `"<rel_path>: speech runs to the end of the file (last word ends at 21.7s of 23.1s); the sentence may be cut.
    If you trimmed this clip, export it a few seconds longer."`
  - If its first word's `t0 <= start_s`, warn with the same shape: "starts at the very beginning of the file …
    export it a few seconds earlier".
  - Sorted by rel_path, then time.
- Called in `make_plan` after selection; the warnings join `plan["warnings"]` (the storyboard already shows
  them).

Tests (`tests/test_moments.py`):
- `test_edge_speech_warns_at_clip_end` (the 21.7/23.1 case)
- `test_edge_speech_quiet_when_there_is_room` (last word 18.0 of 23.1 and first word 1.0 → no warning)

### W4 — Insta360: plan from the preview, export only what the film uses
Policy (`insta360:`): `plan_unstitched: true  # plan unstitched .insv from its .lrv preview; export only the
selected clips before render`.
1. Extract from `plannable_clips` a pure `filter_plannable(clips, excluded: set[str], policy, warnings) -> list`.
   When an unstitched clip (`render_projection == "dual_fisheye"`) meets `allow_unstitched_render: false`:
   - `plan_unstitched: true` → keep it, with the warning
     `"<rel_path>: planned from its preview; if the film uses it you will be asked to export it from Insta360
     Studio before render"`;
   - otherwise → today's skip and warning.
2. `x6_export_list(timeline: dict, inventory: list[dict], policy) -> list[dict]`:
   - For every clip used by a timeline segment or overlay whose `render_projection` is `dual_fisheye`, while
     `allow_unstitched_render` is false, return `{"rel_path", "uses": [[src_t0, src_t1], …]}` (sorted, 1 dp).
   - Empty list otherwise.
3. `run_plan` writes `plan/x6_exports_<tag>.md` **only when the list is non-empty**, in plain words:
   - which files to export;
   - the time ranges the film uses (for reference; export the whole clip);
   - Studio steps: Export → 360° → Equirectangular, FlowState and horizon lock on;
   - save the export next to the `.insv` with Studio's default name;
   - then run `magicvideo analyze` and `magicvideo plan` again.

   It also adds one plan warning: `"N Insta360 clip(s) need exporting before render: see plan/x6_exports_<tag>.md"`.
4. `Renderer.run`: before writing anything, call `x6_export_list`. If it is non-empty, raise `ProjectError`
   listing the files and the `.md` path. No partial outputs.
5. Clip ids are hashes of the primary file's path (the `.insv`), so they and the moment ids, and therefore the
   owner's overrides, stay the same once the export appears. Assert this in a test.

Tests (new `tests/test_x6_flow.py`; synthetic inventory dicts, no footage):
- `test_unstitched_kept_when_plan_unstitched` (and skipped with the old warning when false)
- `test_export_list_names_used_unstitched_only` (a stitched clip and an unused unstitched clip are not listed;
  uses ranges come from segments and overlays)
- `test_renderer_refuses_before_writing` (monkeypatch `x6_export_list` to return one entry; `Renderer.run`
  raises `ProjectError` and the render folder gets no new files)
- `test_clip_id_stable_when_export_added` (`group_insta360` on [insv, lrv] then on [insv, lrv, export]: the primary
  `.insv` keeps the same `clip_id`)

### W5 — Prefixed Insta360 / DJI names (R2 P7)
- `ingest.insta360_key` and `detect_camera`: `.match(` → `.search(` on `_INSTA_RE` and `_DJI_RE`. The regexes
  already carry the R2 prefix guard.
- Test `tests/test_ingest.py::test_prefixed_names_group_and_detect`, parametrized (2 cases):
  - `026_VID_20260919_110940_00_004.insv` → `insta360_key` returns `("20260919_110940_004", "vid")`;
  - `034_DJI_20260420183356_0035_D.MP4` → `detect_camera(name, ".mp4", {})["make"] == "DJI"`.

### W6 — Contract and skill
- Append `## 11. Round 3 changes` to `docs/IMPLEMENTATION_BRIEF.md`: speech tokens and folding, the speech
  report file, `asr_filter`, `edge_speech`, `plan_unstitched` and the export list, renderer refusal, the `zh`
  extra. Append only.
- Append to `agent/SKILL.md`, after the "Plan and review" section, exactly this block:

```
### Insta360 clips
If the plan warns that Insta360 clips need exporting, open `C:\Travel\work\<Trip>\plan\x6_exports_vNNN.md` and
tell the owner which files to export from Insta360 Studio. After they confirm, run `magicvideo analyze` and
`magicvideo plan` again. Don't render before that; render will refuse.

### Plan warnings to pass on
- "speech runs to the end/start of the file": the source clip was trimmed too tight; ask the owner to export it
  longer.
- "ignored likely Whisper hallucination": nothing to do; mention it.
```

## 4. Must get right
1. No rule may drop real speech because of low word probability (the evidence forbids it).
2. The planner stays byte-identical across runs (fixed rounding, sorted lists).
3. The QC check still FAILs when speech is truly missing. Folding and character splitting only remove
   tokenisation noise.
4. The renderer refuses before creating any output when an unstitched clip is used.
5. Optional dependency: without zhconv everything works; folding is off and the QC detail says so.

## 5. Mutation intent (the reviewer will reintroduce these)
1. CJK words not split.
2. Folding ignored when zhconv is present.
3. Missing runs computed with `>` instead of `>=` `min_run`.
4. Phrase match without punctuation removal.
5. Score rule fires on one score alone.
6. Window indices not remapped after a drop.
7. The edge warning uses the moment edge instead of the last word.
8. An unused unstitched clip is listed for export.
9. The renderer check is removed or moved after output creation.
10. `.match` restored in `insta360_key`.

## 6. Expected count (prediction)
Baseline 71. New: W1 5, W2 5, W3 2, W4 4, W5 2 = 18. **89 collected, 89 passed** with zhconv installed.

## 7. Owner acceptance (after merge)
On the owner's PC: `pip install zhconv` in the venv. Then run `magicvideo plan` and `magicvideo qc` on
Test_Trip_R2. A re-render is needed, because outputs are never overwritten (`render` makes v003).

Expect:
- `speech.partner_words_rendered` well above 0.62. If it still fails, the speech report lists the unheard runs
  with film times, to check by ear.
- An edge warning for the La Paz clip.
- A hallucination warning for the v002 clip, and no conversation moment there.

## 8. Assumptions (dated 2026-11-06)
- **A1:** Comparing at character level is accepted as the measure for Chinese and Japanese. 0.9 stays the pass
  line.
- **A2:** zhconv (pure Python, small) is an optional dependency, installed on the owner's PC.
- **A3:** The phrase list is the main hallucination rule. The score rule only applies to new transcripts.
  Existing transcripts are not re-run.
- **A4:** Insta360 exports are done by the owner in Studio. magicvideo only lists what to export and refuses to
  render until it is there.

## 9. Not verified
- That folding plus character matching lifts the owner's score above 0.9 (the heard transcript was not kept).
- The X6 flow on real `.insv`/`.lrv` without an export: there is no such owner sample in Test_Trip_R2.
- Whisper's `no_speech_prob`/`avg_logprob` values on the owner's footage.
