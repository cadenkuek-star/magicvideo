# magicvideo — Round 2 brief: recognise the couple, clickable review, Antigravity tagging

Status: **DRAFT, awaiting owner approval of assumptions A1–A6 (§9).** Do not start until the relay says go.
Author: spec designer (Claude), 2026-11-06. Base: `claude/vibrant-brahmagupta-yr5pu4` @ `1e0dded`.
Contract rule (CLAUDE.md): where this brief changes a contract in `docs/IMPLEMENTATION_BRIEF.md`, update that file in
the same work (item W10).

---

## 1. Objective

The first Windows run (Test_Trip, 2026-11-05) produced a film that treats the couple as strangers. Fix that first,
then remove the two things that make the tool hard to use: hand-editing YAML to review, and needing an Anthropic API
key for scene tags. After this round:

1. Speech by either partner is couple speech, unless a stranger is on screen.
2. The owner reviews the storyboard by clicking. Clicks save straight to `overrides.yaml`.
3. Scene tags are produced by the Antigravity agent looking at frame grids on disk (no API key). The Anthropic API
   stays as an option.
4. Enrollment copes with a partner split across two voice folders (behind-camera voice) and with a partner who
   speaks little.
5. Small fixes: test pinned to no-ASR, tags without a key don't crash, file-name dates with prefixes, stale plan warning.

## 2. Evidence (measured on the owner's PC, 2026-11-06)

Voice refs `C:\Travel\people\refs.npz`: one centroid per partner from 5 and 4 clips, **all cut from 04_Kanazawa
02:31–03:02**. Policy `identity.voice.min_similarity` 0.55, margin 0.05; face 0.40, margin 0.06.

| Clip | Voice windows matched to a partner | Best voice score | Face dets matched | Clear stranger face dets* |
| --- | --- | --- | --- | --- |
| 04_Kanazawa | 13 / 68 | 0.87 | 296 / 454 | 17 |
| 034_DJI (BF talking, couple) | 0 / 61 | 0.54 | 214 / 653 | 2 |
| 026_DJI (GF) | 0 / 1 (0.8 s window) | −0.06 | 123 / 180 | 0 |
| 01_Arrival_La_Paz | 0 / 8 | 0.51 | 46 / 143 | 0 |
| 01_Tokyo_Arrival | 0 / 9 | 0.44 | 40 / 42 | 1 |
| 06_Nyuto_Onsen | 0 / 11 | 0.40 | 38 / 39 | 0 |
| 03_Scenic (guide talks) | 0 / 8 | 0.22 | 0 / 71 | 36 |

\* q ≥ 0.5 and similarity < 0.20 to both partner face refs.

Simulation of the rule in W4 on these clips: Scenic keeps 8/8 windows as third party (stranger on screen). The couple
clips become couple speech except 2 windows in 034, 2 in Tokyo, 11 in Kanazawa (stranger on screen in those windows).

Code paths that cause the bug:
- `magicvideo/analysis/voices.py::label_windows` → every window below threshold becomes `OTHER`.
- `magicvideo/plan/data.py::is_couple_speaker` → `OTHER` is never couple.
- `magicvideo/plan/moments.py::third_party` → builds third-party moments from `OTHER` turns with no look at faces.
- `magicvideo/plan/data.py::load_clip` → face labels are computed after turns and never feed speaker labels.
- `magicvideo/enroll.py::_surviving` → folders below the minimum are silently ignored, then "need exactly 2" fails.
- `magicvideo/ingest.py` `_DJI_RE`/`_INSTA_RE`/`_PIXEL_RE` are anchored with `^` → `026_DJI_2026…` falls back to
  `creation_time` (UTC), so day grouping is off by the UTC offset.
- `magicvideo/analysis/tags.py::Tagger.__init__` → no key: the SDK fails later with `TypeError: Could not resolve
  authentication method`, not `BackendMissing`.
- `tests/test_e2e.py::test_plan_render_qc` → QC calls real `asr.transcribe` when faster-whisper is installed; the sine
  tone gives 0/8 words.
- Plan v002 (15:55 UTC) is older than `refs.npz` (16:13 UTC); nothing warns.

## 3. Scope

In: W1–W10 below. Out (parked for R3): rendering `.insv` without Studio export, "export only selected X6 clips",
multi-reference faces, stranger voice references, a web page for enrollment, music.

## 4. Work items (in this order)

### W1 — Pin the end-to-end test to "no ASR"
- `tests/test_e2e.py::test_plan_render_qc`: add the `monkeypatch` fixture. Before `run_qc(...)`, replace
  `magicvideo.analysis.asr.transcribe` with a function that raises `asr.BackendMissing("disabled in test")`.
  QC imports `asr` inside the function (`from ..analysis import asr`), so patching the module attribute works.
- Add to the same test, after `run_plan`: `assert "refs_sha256" in plan` (W6).
- Done means: the test passes with faster-whisper installed and with it absent; the existing
  `verdict == "INCOMPLETE"` assertion is unchanged.

### W2 — Tags without a key raise BackendMissing
- `Tagger.__init__` (tags.py): after computing `key`, if `not key and not os.environ.get("ANTHROPIC_API_KEY") and
  not os.environ.get("ANTHROPIC_AUTH_TOKEN")`, raise `BackendMissing("no Anthropic key: set cloud.provider: agent
  (default) or set ANTHROPIC_API_KEY")`.
- Test `tests/test_tags.py::test_anthropic_without_key_is_backend_missing`: insert a dummy module as
  `sys.modules["anthropic"]`, clear both env vars with `monkeypatch.delenv(..., raising=False)`, use a policy with
  `cloud.provider: anthropic`, assert `BackendMissing`.

### W3 — File-name capture times with a prefix
- `ingest.py`: in all three regexes replace the leading `^` with `(?:^|(?<=[^A-Za-z0-9]))` and change `.match(` to
  `.search(` in `filename_time`. Group numbers stay the same.
- Test `tests/test_ingest.py::test_filename_time_with_prefix`, parametrized (4 cases):
  `026_DJI_20260420125548_0027_D.MP4` → 2026-04-20 12:55:48 · `DJI_20260420125548_0027_D.MP4` → same ·
  `026_VID_20260919_110940_00_004.insv` → 2026-09-19 11:09:40 · `XDJI_20260420125548_0027_D.MP4` → `None`.

### W4 — Couple prior: unmatched speech is the couple's unless a stranger is on screen (core)
Policy (`default_policy.yaml`, under `identity:`):
```yaml
  couple_prior: true            # couple trip: speech is the couple's unless a stranger is on screen
  stranger_face:
    max_similarity: 0.20        # face scores below this against BOTH partner refs = a stranger
    min_q: 0.5                  # only clear faces count
    pad_s: 1.0                  # look this far before/after a speech window
```
Code:
1. `analysis/voices.py`: add `COUPLE = "COUPLE"` next to the other labels and export it. Add
   `window_best_scores(emb, refs) -> np.ndarray`: per window `max(score_a, score_b)` using the same scoring as
   `label_windows` (including W5's multi-reference rule); zeros when refs are missing or lengths differ.
2. `analysis/faces.py`: add `stranger_times(dets, emb, refs, policy) -> list[float]`: the `t` of every detection with
   `q >= identity.stranger_face.min_q` and `max(emb@face_a, emb@face_b) < identity.stranger_face.max_similarity`.
   Returns `[]` when face refs are missing, shapes differ, or there are no detections. Sorted ascending.
3. `plan/data.py`: add pure function `apply_couple_prior(windows, labels, stranger_ts, policy) -> list[str]`:
   if `identity.couple_prior` is false, return `labels` unchanged. Otherwise, each `OTHER` window becomes `COUPLE`
   unless some `t` in `stranger_ts` satisfies `w.t0 - pad_s <= t <= w.t1 + pad_s`. Other labels are untouched.
4. `plan/data.py::load_clip`: load faces (dets, labels, fps) **before** building turns. Then
   `labels = apply_couple_prior(windows, labels, stranger_times(...), policy)` and build turns from the result.
   Store `cd.window_evidence`: one dict per window `{"t0","t1","raw","label","voice_best"}` with `voice_best`
   rounded to 3 decimals and `"stranger": bool`.
5. `is_couple_speaker`: return True for `COUPLE` as well.
6. `plan/model.py::Moment`: add `identity: dict = field(default_factory=dict)`, serialised in the plan. In
   `moments.conversations` and `moments.third_party`, fill it from overlapping `cd.window_evidence`:
   `{"voice_best": max voice_best (3 dp), "stranger_on_screen": any stranger, "assumed_couple": count of windows
   with raw OTHER and label COUPLE}`. Keep key order fixed and values rounded so the plan stays byte-identical.
7. `plan/storyboard.py`: on each card with a non-empty `identity`, add one line, e.g.
   `voice match 0.54 (needs 0.55) · stranger on screen: no · treated as you two (3 windows)`.
   The "needs" figure comes from `identity.voice.min_similarity`.

Tests (`tests/test_moments.py`):
- `test_couple_prior_relabels_unmatched_voice` — OTHER window, no strangers → COUPLE.
- `test_stranger_on_screen_keeps_third_party` — stranger t inside the padded window → OTHER; a second stranger at
  exactly `t1 + pad_s + 0.01` does not affect a different window (boundary).
- `test_couple_prior_off_keeps_old_labels` — `couple_prior: false` → labels unchanged.
- `test_couple_turns_make_a_conversation` — `conversations()` on a ClipData whose turns are `COUPLE` returns a
  `conversation` moment with `cls == "couple"` and `partner_words > 0`.
- `test_stranger_times_thresholds` — synthetic 4-dim embeddings: one det below 0.20 with q 0.6 (stranger), one below
  0.20 with q 0.3 (ignored), one at 0.25 (not a stranger).

### W5 — Enrollment: merge folders, sparse partners, clear errors, multi-reference voices
CLI: `magicvideo enroll <work> --finalize [--merge SRC:DST]... [--allow-sparse]`.
1. `--merge voice_003:voice_001` (repeatable): the files in `SRC` count toward and are approved under `DST`'s
   partner. The prefix (`person_` / `voice_`) decides the kind. Errors (no files written, exit 1, message names the
   problem): SRC or DST folder missing; kinds differ; SRC also used as a DST (no chains); same SRC twice.
2. Count **every** surviving non-empty folder after merges (change `_surviving` so it no longer drops folders below
   the minimum). If the count is not 2, the report line is, for example:
   `voices: need exactly 2 partners, found 3 after merges: voice_001 (5 clips), voice_002 (3), voice_003 (2 — below
   minimum 3). Delete folders that are not you two, or fold one into another: --merge voice_003:voice_002`.
3. If a partner is below `enrollment.min_kept_per_partner.<kind>`: without `--allow-sparse` the report names the
   folder, its count, the minimum and the flag; with `--allow-sparse` the minimum is 1 and the report adds
   `sparse: partner_b has 2 voice clips (minimum 3); recognition will rely on the couple prior`.
4. Slots stay as today: surviving DST folders sorted by name → `a`, `b`; swap heuristic unchanged.
5. Multi-reference: besides the centroid, store `refs[f"{kind}_{slot}_all"]` = stacked L2-normalised embeddings
   (N×D). In `voices.label_windows` (and `window_best_scores`), when `voice_a_all`/`voice_b_all` exist, the score
   for a partner is `max(emb @ centroid, max over rows of emb @ all.T)`. Faces keep centroid scoring.
6. Diversity warning: if all approved files of a slot come from one `clip_id` (from the manifest), add
   `warning: partner_b's voice reference comes from 1 clip; add clips from other cameras for better recognition`.
7. Finalize ends by printing `next: magicvideo plan "<work>"`. Update `REVIEW_TEXT` to mention `--merge` and
   `--allow-sparse` in plain words.

Tests (new `tests/test_enroll.py`, synthetic, no models; build the project with `Project.init(tmp/"work",
[tmp/"raw"], "T", tmp/"people")`, write `inventory.json` as `{"version": 1, "clips": []}` if the loader needs it,
and write review folders + `manifest.json` by hand):
- `test_merge_folds_folder_into_partner`
- `test_below_minimum_message_names_folder_and_flag`
- `test_allow_sparse_accepts_two_clips`
- `test_single_clip_reference_warns`
- `test_multi_reference_uses_best_match` — a window close to one stored row but far from the centroid is labelled
  as that partner.

### W6 — Warn when the plan is older than the partner references
- `enroll.py`: add `refs_fingerprint(people_dir) -> str | None` (sha256 hex of `refs.npz` bytes; None if missing).
- `run_plan` writes `plan["refs_sha256"]`. Add `stale_refs(project, plan) -> bool`.
- `magicvideo render` and `magicvideo review` log a warning when stale; the storyboard page shows a red banner
  "Your partner references changed after this plan was made. Run magicvideo plan again." (in live mode, from the
  `/api/overrides` response field `stale_refs`).
- Test `tests/test_review.py::test_stale_refs_detected`.

### W7 — Clickable review: `magicvideo review` writes overrides.yaml
New module `magicvideo/review.py`, standard library only (`http.server.ThreadingHTTPServer`).
- `make_server(project, version=None, port=None) -> ThreadingHTTPServer` bound to **127.0.0.1 only**
  (`port=None` → policy `review.port`, default 8765; tests pass 0). `serve(...)` runs it, prints the URL, opens the
  browser unless `--no-open`; Ctrl+C stops.
- Routes:
  - `GET /` → `plan/storyboard_<version>.html` (latest when no version).
  - `GET /thumbs/<name>` → file inside `plan/thumbs/`; anything resolving outside it → 404.
  - `GET /api/overrides` → `{"overrides": {...}, "version": "v00N", "stale_refs": bool}`.
  - `POST /api/moment` body `{"id": str, "value": "keep"|"drop"|"couple"|"clear"}` → id must exist in that plan's
    `moments`; unknown id or value → 400. Writes `overrides.yaml` and returns `{"ok": true, "overrides": {...}}`.
  - `POST /api/replan` → runs `run_plan(project, thumbs=True)` and returns `{"version": "v00N"}`.
  - Every request whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` → 403. Every POST without
    `Content-Type: application/json` → 415.
- Writing `overrides.yaml`: read with `encoding="utf-8-sig"` (the owner's file has a BOM); keep `events` and
  `clips` as they are; `clear` deletes the key; write `yaml.safe_dump(data, sort_keys=True, allow_unicode=True)` to a
  temp file next to it, then `os.replace`. Before the first write of a session, copy the old file to
  `overrides.yaml.bak`. No BOM on output.
- New override value `couple` ("this is us"): in `plan/budget.py::apply_overrides` set `m.cls = "couple"` for that
  moment; `_override(m) == "couple"` is treated exactly like `"keep"` wherever `"keep"` is checked
  (`select_event` forced list and the third-party branch).
- `plan/storyboard.py`:
  - Remove the `<textarea id=ov>`. Embed `window.OVERRIDES = <current overrides as JSON>` and
    `window.PLAN_VERSION`.
  - Buttons per card: keep · drop · **this is us** (only when `cls == "third_party"`) · clear. The current choice is
    highlighted.
  - On load, `fetch('/api/overrides')`. Success = live mode: each click POSTs, a fixed bottom bar shows
    `Saved · N changes` and a **Re-plan now** button (POST `/api/replan`, then load `/`).
  - Failure (opened as a file) = offline mode: clicks collect locally; the bar shows **Download overrides.yaml**,
    which builds YAML from `window.OVERRIDES` merged with the clicks and downloads it via a Blob, with the text
    `Save it over <work>\overrides.yaml, or run: magicvideo review "<work>"`.
- CLI: `magicvideo review <work> [--plan vNNN] [--port N] [--no-open]`. Policy: `review: {port: 8765}`.

Tests (`tests/test_review.py`; write a minimal `plan_v001.json` with two moment ids and a `storyboard_v001.html`
by hand; run the server on port 0 in a thread; use `urllib.request`):
- `test_post_keep_writes_overrides` (start from an `overrides.yaml` that has a UTF-8 BOM and an `events:` entry;
  both survive, output has no BOM)
- `test_clear_removes_entry`
- `test_unknown_moment_rejected`
- `test_bad_value_rejected`
- `test_foreign_host_rejected`
- `test_server_binds_loopback`
- `test_thumb_path_traversal_blocked`
- `test_storyboard_has_offline_download` (page contains `window.OVERRIDES` and the download button id)

Plus `tests/test_budget.py::test_couple_override_counts_as_couple` (a third-party moment with override `couple` is
selected and counted in the couple share, not the third-party share).

### W8 — Scene tags by the Antigravity agent (no API key)
Policy: `cloud.provider: agent` becomes the **default** (`anthropic` stays supported). Comment:
`# agent = the coding agent (Antigravity/Gemini) views frame grids on disk; anthropic = API key`.
1. `analysis/tags.py`: move the cell-cleaning code at the end of `Tagger.tag_grid` into
   `clean_cells(cells: list, n: int) -> list[dict | None]` and call it from both paths.
2. `export_for_agent(project, clip, path, policy) -> int` (grids written): uses `sample_frames` and `make_grid`
   exactly as the API path does (`cloud.frames_per_request` per grid, `cloud.max_frame_px`). Writes into
   `<work>/tagging/<clip_id>/`: `grid_NNN.jpg`, `grid_NNN.cells.json` (`[{"cell": 1, "t": 12.0, "view": null}, …]`).
   Skips grids whose frames are already in `analysis/<clip>/tags.json`.
3. After exporting all clips, write `<work>/tagging/TASKS.md`: the `SYSTEM_PROMPT`, the allowed `TAGS` and `PEOPLE`
   lists, `response_schema(9)` as JSON, the answer file rule (`grid_NNN.answer.json` next to each grid), and a
   checklist of every grid path not yet answered.
4. `analysis/runner.py`: when the provider is `agent`, the tags step calls `export_for_agent` and records status
   `skipped: awaiting agent tags` (this is SKIPPED, not failed); the run summary prints
   `tags: N grids waiting — ask the agent to answer <work>\tagging\TASKS.md, then run magicvideo tags import`.
5. `import_agent_tags(project) -> dict`: for each `grid_NNN.answer.json`, parse `{"cells": [...]}`, run
   `clean_cells`, map cells to `t`/`view` via `cells.json`, merge into `analysis/<clip>/tags.json` (backend
   `"agent"`, sorted like the API path, `frames_sent` incremented). Invalid JSON or cells outside 1..n → listed in the
   result, that grid skipped, nothing else changed. A clip whose grids are all imported gets status `tags: done`.
   Re-importing the same answer adds nothing (idempotent on `(t, view)`).
6. CLI: `magicvideo tags export <work>` and `magicvideo tags import <work>`; import prints imported / invalid /
   still missing counts.
7. Privacy: only these low-res grids are seen by the agent's model; the rule in the module docstring is updated to say so.

Tests (`tests/test_tags.py`, synthetic footage from the existing helpers):
- `test_agent_export_writes_grids_and_tasks`
- `test_agent_import_merges_answers`
- `test_agent_import_rejects_bad_answers` (unknown tag dropped, cell 12 of 9 rejected, bad JSON listed)
- `test_agent_import_is_idempotent`
- `test_analyze_with_agent_provider_skips_not_fails`

### W9 — Antigravity skill and workspace entry
- Copy `docs/R2_SKILL_magicvideo.md` (provided, do not edit its meaning) to `agent/SKILL.md`, and to
  `C:\Travel\.agents\skills\magicvideo\SKILL.md` and `C:\Travel\skills\magicvideo\SKILL.md`. All three must be
  byte-identical (self-check prints their hashes).
- `C:\Travel\PROJECT.md` is provided by the spec designer; do not change it.

### W10 — Update the contract
Append `## 10. Round 2 changes` to `docs/IMPLEMENTATION_BRIEF.md`: the couple prior and its policy keys, `COUPLE`
label, `Moment.identity`, enroll flags and `*_all` refs, `refs_sha256`, the review server routes, the `couple`
override, the agent tagging files and commands. No deletions in that file (append only).

## 5. Must get right
1. The server binds 127.0.0.1 only and checks Host. Never `0.0.0.0`.
2. The plan stays byte-identical across runs (rounded floats, fixed key order, no set iteration into output).
3. `overrides.yaml` is never half-written (temp + `os.replace`) and the BOM file is read.
4. With `couple_prior: false`, labels are exactly as before (regression guard).
5. Every new threshold is a policy key read with `policy("…")`; none hard-coded.
6. Raw footage is never written. Tagging grids live under `<work>\tagging\` only.
7. Windows: `pathlib`, argument lists for subprocesses, no shell strings.

## 6. Mutation intent (the reviewer will reintroduce these; a test must fail for each)
1. Drop the stranger check in `apply_couple_prior` (every OTHER → COUPLE).
2. Use `<` instead of `<=` at the padded edge.
3. `stranger_times` ignores `min_q`.
4. `is_couple_speaker` forgets `COUPLE`.
5. `_surviving` filters by the minimum again.
6. `--merge` approves SRC under its own slot.
7. Multi-reference scoring uses the centroid only.
8. Server binds `0.0.0.0` / Host check removed / unknown ids accepted / `clear` writes `None` instead of deleting.
9. `overrides.yaml` read without `utf-8-sig`.
10. The `couple` override counts in the third-party share.
11. `import_agent_tags` accepts cell numbers outside 1..n, or double-counts on re-import.
12. The anchor `^` restored in `_DJI_RE`.

## 7. Expected count (prediction)
Baseline on the owner's PC: 37 collected (36 passed, 1 failed). New: W2 1 · W3 4 · W4 5 · W5 5 · W6 1 · W7 9 ·
W8 5 = 30. **Prediction: 67 collected, 67 passed** with all backends installed. If your count differs, show the
`pytest --collect-only -q` diff in the handover; do not add or merge tests to reach the number.

## 8. Owner acceptance run (after merge; the owner or the helper runs it, not the coder)
Test footage is ready in `C:\Travel\raw\Test_Trip_R2` (026 trimmed to 0:00–0:18, 034 to 0:00–1:02, the rest as the
owner cut them; the X6 files are left out).
```
magicvideo init    C:\Travel\work\Test_Trip_R2 --source C:\Travel\raw\Test_Trip_R2 --people C:\Travel\people
magicvideo analyze C:\Travel\work\Test_Trip_R2
(agent answers C:\Travel\work\Test_Trip_R2\tagging\TASKS.md)
magicvideo tags import C:\Travel\work\Test_Trip_R2
magicvideo plan    C:\Travel\work\Test_Trip_R2 --thumbs
magicvideo review  C:\Travel\work\Test_Trip_R2
```
Pass when: 026 0–1.8 s and 034 0–8 s show as `conversation · couple`; the 03_Scenic guide stays `third_party`;
`edit.third_party_share` ≤ 5 %; clicking keep/drop changes `overrides.yaml` with no copy-paste; 026 and 041 get
2026-04-20/21 capture times from their file names.

## 9. Assumptions for the owner to approve (dated 2026-11-06)
- **A1 Couple prior on by default.** A stranger who talks while off screen (a waiter behind the camera) will be
  treated as couple speech. You can mark those "drop" in review. Set `identity.couple_prior: false` to undo.
- **A2 Antigravity does the tagging by default**; the Anthropic API remains an option (`cloud.provider: anthropic`).
  The agent's model (Gemini) sees only the low-res 3×3 frame grids, nothing else.
- **A3 Insta360: no change this round.** You don't need to export every X6 clip; with no X6 clips this round, it is
  parked. R3 idea: plan from the `.lrv` previews, then list only the selected X6 clips for you to export.
- **A4 Review server is local only** (127.0.0.1), no password.
- **A5 Saving from the review page rewrites `overrides.yaml` without your comments**; the old file is kept as
  `overrides.yaml.bak` once per session.
- **A6 Voice merging is a command-line flag** (`--merge voice_003:voice_001`), not a page, this round.

## 10. What I did NOT verify
- The 0.20 stranger threshold is tuned on 9 clips from one trip; it may need tuning on a market or restaurant clip.
- Gemini's tagging quality on the grids is untested.
- That Antigravity reads `C:\Travel\.agents\skills\` automatically — the owner's existing setup uses it; if not, tell
  the agent to read `C:\Travel\PROJECT.md`.
- Windows firewall behaviour for a loopback server (normally no prompt).
- The rendered-speech QC score after the fix (0.67 last run); it may still need work on cuts or music ducking.
