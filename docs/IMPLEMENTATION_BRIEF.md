# magicvideo: Implementation Brief (v3, build 1)

This brief is the contract for the code in this repository. The design rationale is in [PROPOSAL.md](PROPOSAL.md). Where this brief and the code disagree, the code is wrong. Fix the code, or change this brief in the same commit.

---

## 1. Goal

Turn one trip's raw footage into:

- **One final film per trip**
- **One file per day** (chapters, optional)
- **An editable timeline** (OTIO for DaVinci Resolve, plus a CSV EDL)
- **A QC report whose verdict a script computes**

Raw footage is never modified.

Cameras:

- Insta360 X6 (360°)
- DJI Osmo Nano
- DJI Osmo Pocket 4P (gimbal)
- Phones

Camera behaviour is detected from file metadata and measurements, never assumed from the name alone.

## 2. Non-negotiable rules

1. **Code decides; models describe.** Models only write analysis files. The deterministic planner turns analysis + `policy.yaml` + `overrides.yaml` into a timeline. The same inputs give a byte-identical `timeline.json`.
2. **One policy file.** Every threshold comes from `policy.yaml`, with defaults in `magicvideo/default_policy.yaml`. No magic numbers in planner, render or QC code, except mathematical constants and format facts.
3. **The two partners' speech is protected.** A conversation (§6.3) is never cut inside a word, and partner words are only removed when the user drops a moment in `overrides.yaml`.
4. **Footage is corrected before it is rejected.** Nothing is rejected for orientation alone.
5. **Sources are read-only.** Write only under the trip work directory and the shared people directory. Every output is versioned (`v001`, `v002`, …) and never overwritten.
6. **QC verdicts are computed.** `qc.json` is written only by `magicvideo qc`. Agents and humans never edit it. A check that couldn't run is `SKIPPED`, and the verdict is then `INCOMPLETE`, never `PASS`.
7. **Cloud privacy.** The cloud receives only low-res still frames (long side ≤ `cloud.max_frame_px`) for scene tagging. It never receives audio, transcripts, face crops, embeddings, GPS or original media. The tagger uses the Anthropic SDK (`client.beta.messages.create`) with JSON-schema structured output, `fallbacks: "default"` for refusals, and `cloud.effort` (default `low`). The model defaults to `claude-opus-5-5` and is set with `cloud.model`.
8. **Cross-platform.** Windows is the primary target. Use `pathlib`, pass subprocess argument lists (never `shell=True`), and give ffmpeg filter-file arguments as relative names with `cwd` set, so Windows drive-letter colons never appear inside filtergraphs.

## 3. Build 1 scope

| In build 1 | Later builds |
|---|---|
| ingest, inventory, camera/360 detection, capture time, duplicates | audio cross-correlation clock alignment between devices |
| analysis: quality and jitter, ASR, voice windows and embeddings, faces, cloud tags, 360 analysis views | Gyroflow integration; insightface-based orientation refinement for sideways clips without metadata (build 1 uses metadata, plus a face check when the face backend is installed) |
| enrollment: deletion-only face and voice review, finalize | interactive review web app (build 1 writes a static storyboard plus `overrides.yaml`) |
| planner: moments, events, chapters, budgets, guards, covered pauses, orientation choice, 360 camera paths | highlights profile |
| render: frame-exact pieces, reframing, 360 reframing, stabilization fallback, PCM audio, linear loudness, chapters, master, OTIO, CSV | FCPXML (written only when the optional adapter is installed) |
| QC: technical and editorial checks, computed verdict | |

Optional backends (ASR, voice, faces, tags, geo) are imported lazily. If one is missing, its analysis step is recorded as skipped and the planner degrades as described in §6.

## 4. Layout

```
<work>/                         one directory per trip (e.g. C:\Travel\work\Japan)
  project.yaml                  name, source_dirs, people_dir
  policy.yaml                   copied from defaults at init; edit freely
  devices.yaml                  optional per-device clock offsets / timezones
  overrides.yaml                review decisions (created empty at init)
  inventory.json
  analysis/<clip_id>/
    audio16k.wav  transcript.json  voices.json  voice_emb.npy
    faces.json  face_emb.npy  quality.json  visual_desc.npy  tags.json
    status.json                 per-step: done | skipped:<reason> | failed:<error>
  plan/plan_vNNN.json  timeline_vNNN.json  storyboard_vNNN.html
  render/vNNN/                  intermediates (deletable after QC PASS)
  output/<Name>_vNNN.mp4  output/chapters/NN_<chapter>_vNNN.mp4
  output/<Name>_vNNN.otio  output/<Name>_vNNN_edl.csv
  qc/qc_vNNN.json  qc/qc_vNNN.md
<people>/                       shared by all trips (e.g. C:\Travel\people)
  faces/review/<trip>/person_NNN/*.jpg   faces/approved/partner_a|partner_b/*.jpg
  voices/review/<trip>/voice_NNN/*.wav   voices/approved/partner_a|partner_b/*.wav
  refs.npz                      face_a, face_b, voice_a, voice_b centroids (+ counts)
  enrollment.yaml               status and voice↔face mapping; editable (swap_voices)
```

## 5. CLI

```
magicvideo doctor                                   check ffmpeg, filters, backends, GPU
magicvideo init    <work> --source <dir> [--source <dir2>] [--name Japan] [--people <dir>]
magicvideo analyze <work> [--steps quality,asr,voices,faces,tags] [--force]
magicvideo enroll  <work> [--finalize]
magicvideo plan    <work>
magicvideo render  <work> [--plan vNNN]
magicvideo qc      <work> [--version vNNN]
magicvideo run     <work>        analyze → plan → render → qc
```

Exit code 0 means success. A QC FAIL exits 2, and INCOMPLETE exits 3.

## 6. Data contracts and algorithms

All times are seconds (float) in source-clip time unless named `*_frame`. JSON is UTF-8 with sorted keys, and floats are rounded to 3 decimals.

### 6.1 Inventory (`inventory.json`)

`clip_id` = `c_` + first 10 hex digits of sha1(`<source folder name>/<relative path>`, POSIX separators). Stable across runs, and unique across several source folders.

Per clip:

- **File:** `path`, `rel_path`, `size`, `duration`.
- **Video:** `fps` (float), `fps_rational`, `width`, `height` (coded), `rotation` (degrees), `display_w`, `display_h`, `orientation` (`landscape | portrait | square`), `projection` (`flat | equirect | dual_fisheye`).
- **Audio:** `has_audio`, `audio_channels`, `audio_rate`.
- **Camera:** `camera` = `{make, model, kind}`, where `kind` is `gimbal | action | 360 | phone | unknown`.
- **Color:** `color` = `{transfer, primaries, matrix, log_profile}`.
- **Capture time:** `capture_start` (local naive ISO time) and `capture_source` (`filename | qt_creationdate | creation_time | mtime`).
- **Links:** `analysis_path`, `render_path`, `role` (`source | lrv | second_lens | stitched_export`), `group` (the 360 recording key), `duplicate_of`.

**Capture time**, in order of precedence:

1. The filename timestamp (`DJI_YYYYMMDDhhmmss_…`, `VID_YYYYMMDD_hhmmss_…`, `PXL_YYYYMMDD_hhmmss…`), which is camera-local time.
2. `com.apple.quicktime.creationdate`, which carries a timezone and is converted to `trip.timezone` when set.
3. `creation_time`, which is UTC and converted with `trip.timezone`.
4. The file's mtime.

A `devices.yaml` offset is then added per `camera.make/model`.

**360 grouping:** Insta360 files that share a `(date, time, index)` key form one recording.

- `render_path` is the stitched equirect export if one exists; otherwise the `.insv` (dual fisheye).
- `analysis_path` is the `.lrv` if it exists; otherwise `render_path`.
- Only the primary member gets `role: source`, and the others are not planned separately.

**Projection detection:**

- Spherical side data marked equirectangular → `equirect`.
- `.insv`, or 2:1 frames whose four corners in each half are dark (dual fisheye heuristic) → `dual_fisheye`.
- 2:1 frames with Insta360 naming or make → `equirect`.
- Anything else → `flat`.

**Duplicates:** files with the same size and SHA-256. The later path gets `duplicate_of`.

### 6.2 Analysis files

| File | Content |
|---|---|
| `transcript.json` | `{backend, language, words:[{t0,t1,w,p}], segments:[{t0,t1,text}]}` |
| `voices.json` + `voice_emb.npy` | `{backend, windows:[{t0,t1,w0,w1}]}`; one L2-normalized row per window. A window is a run of consecutive words, split on a gap greater than `voice.window_gap_s` or a length greater than `voice.window_max_s`. |
| `faces.json` + `face_emb.npy` | `{backend, sample_fps, dets:[{t,box:[x,y,w,h] (normalized), score, q, track, yaw?, pitch?}]}`; one L2-normalized row per detection. 360 clips add `yaw`/`pitch` in degrees. |
| `quality.json` | `{fps, t[], sharp[], luma[], white[], black[], motion[], jitter[]}` |
| `visual_desc.npy` | One L2-normalized appearance descriptor per second (times in `quality.json` → `desc_t`), used for near-duplicates and novelty |
| `tags.json` | `{backend, frames:[{t, view?, tags[], people, interest, desc}]}` with a fixed tag vocabulary (`magicvideo/analysis/tags.py`) |

**Jitter** is computed at `quality.sample_fps` on a ≤ 320 px upright proxy:

1. Estimate global motion between consecutive frames as dx, dy and rotation (feature tracking with a partial-affine fit).
2. Integrate the motion into a camera path.
3. Smooth the path with a moving average of `quality.jitter_smooth_s`.
4. Jitter = |path − smoothed| / frame diagonal, so deliberate pans aren't counted.
5. The planner masks and scores on a ~0.5 s rolling median of jitter, so single-sample spikes don't fragment steady shots.

### 6.3 Moments (`magicvideo/plan/moments.py`)

**Speaker labels.** Each voice window is compared with `refs.voice_a/b`:

- `PARTNER_A` or `PARTNER_B` when its similarity is at least `identity.voice.min_similarity` and it beats the other partner by `identity.voice.margin`.
- `OTHER` otherwise.
- `UNKNOWN` when no voice refs exist.

Words take their window's label. Windows shorter than `voice.min_window_s` take the label of the longer neighbouring window when it is within `voice.window_gap_s`. Consecutive words with the same label form a **turn**.

**Conversation.** A maximal chain of turns where:

- gaps are ≤ `moments.conversation.join_gap_s`;
- at least one turn is a partner turn, or `UNKNOWN` when `identity.unknown_speech_is_couple` is true;
- `OTHER` turns inside the chain stay in it, when `keep_other_speakers_inside` is true.

Leading and trailing `OTHER` turns are left out.

Bounds run from `first.t0 − pre_roll_s` to `last.t1 + post_roll_s`, clamped to the clip. If an edge would fall inside a word, it moves outside that word, plus a 0.05 s guard.

**Pauses.** These are gaps between consecutive words inside a conversation:

| Pause length | Treatment |
|---|---|
| ≤ `keep_pause_up_to_s` | Kept as is. |
| Up to `split_pause_over_s` | **Shortenable**: assembly (§6.6) may shorten it to `shorten_pause_to_s`, but only with a cover shot. |
| > `split_pause_over_s` | Splits the conversation. |

**Third-party moment.** A chain of `OTHER` turns outside any conversation, joined the same way.

**Action moment.** A tag frame carrying an action tag (`taste, toast, cheers, reveal, game, dance, purchase`) while a partner is visible within ±`moments.action.partner_window_s`. It covers `t − pre_s` to `t + post_s`. Overlapping actions merge, and actions inside conversations are dropped.

**Coverage candidates.** These are windows of `shot_max_s`, stepped by `coverage.step_s`, inside spans that aren't occupied by the moments above (with a margin of `coverage.margin_s`).

- **Rejected** when any sample is black, white, has jitter at or above `quality.jitter.high`, or is blurred below `quality.blur_min`. The window is then shrunk to its longest clean sub-span, which must be at least `shot_min_s`.
- **Score** = mean of the normalized sharpness, exposure and stability terms × (0.5 + 0.5 × tag interest).
- **Silent solo shots:** when exactly one partner is visible and nobody speaks, the duration is capped at `identity.silent_solo_shot_max_s[partner]`; 0 drops the window.

**Moment IDs** are `<clip_id>:<kind>:<round(t0*10):06d>`, stable across re-plans.

### 6.4 Events and chapters

- **Events.** Clips are sorted by `capture_start`. A new event starts when the gap from the previous clip's end is more than `events.gap_min` minutes, or when the local date changes.
- **Event type** is the majority type among the event's tag frames (tag→type map in `tags.py`): `meal | transit | landmark | street | hotel | performance | general`. Events without tags are `general`.
- **Event label:** meals become Breakfast, Lunch, Dinner or Snack by local hour. Other types use a fixed word, plus a place name when the GPS backend is available.
- **Chapters:** one per local date, named `Day N · <up to 3 event labels>`.

### 6.5 Budgets and selection (`magicvideo/plan/budget.py`)

Per event:

1. **Protected:** all conversations and actions, minus those the user dropped in overrides.
2. **Third-party:** moments are scored by partner reaction (partner speech or laughter within `third_party.reaction_window_s` after the moment) plus tag interest. Each one is trimmed to its best window of at most `third_party.excerpt_max_s`, and they are added in score order until `budgets_s.third_party_per_event` is reached.
3. **Coverage:** the budget is `budgets_s[type][1]` (or `general`), multiplied by the runtime scale factor. Candidates are picked greedily by MMR: `λ·score − (1−λ)·max_cosine(desc, chosen)`, where λ = `coverage.mmr_lambda`. A candidate must have a cosine below `coverage.max_similarity` to everything already chosen. Picking stops when the budget is reached. A shot is added only if the total stays within `budget × (1 + coverage.budget_overshoot_max)`.

**Film guards**, iterated until stable or 10 rounds:

- Transit coverage at most `film_limits.transit_share_max` of the runtime.
- Third-party at most `film_limits.third_party_share_max`.
- Each round drops the lowest-scored item of the offending class, keeping at least one item per event.

**`target_runtime_min`, when set:** the planner first scales coverage budgets, from a factor of 1.0 down to 0.2. If the film is still too long, it drops the lowest-scored conversations and lists every one in `plan.warnings`.

**Overrides** (`overrides.yaml`):

```yaml
moments:   {<moment_id>: drop | keep | {extend_start_s: 1.0, extend_end_s: 2.0}}
events:    {<event_id>: {coverage_budget_s: 60}}
clips:     {<clip_id>: {exclude: true, rotate: 90}}
```

`keep` forces a coverage candidate or third-party moment to be selected, regardless of budget.

### 6.6 Assembly → `timeline_vNNN.json`

**Master format:**

- **Orientation:** `output.orientation: auto` gives portrait (1080×1920) when portrait clips make up at least `output.portrait_threshold` of the duration of the selected flat protected moments. Otherwise it is landscape (1920×1080). 360 clips are excluded from this vote.
- **Frame rate:** with `output.fps: dominant_family`, the planner picks 25 or 30 (or 30000/1001 when most of the selected footage is 29.97/59.94), weighted by selected duration.

**Order:** items sorted by absolute time, `capture_start + t0`. Items from the same clip that overlap, or sit within `assembly.merge_gap_s` of each other, are merged, so no micro jump cuts are created.

**Covered pauses:** a shortenable pause is shortened only if a cover shot of at least `assembly.cover_len_s` exists in the same event. Cover shots come from unused coverage candidates first. If none exist, a selected coverage shot is *moved* to become the cutaway, and no longer stands alone.

- Segment 1 ends at `p0 + shorten/2` and segment 2 starts at `p1 − shorten/2`.
- An overlay (video only) with the cover shot spans `join ± cover_len_s/2` on the timeline.
- Picture defects inside conversations (runs of at least `assembly.defect_min_s` that are black, white or high-jitter) are covered the same way when a cover shot exists. Otherwise the picture is kept as is.

**Quantization:** every segment and overlay gets an integer frame count and start frame, using `frames = round(duration × fps)` and cumulative start frames.

**Reframe per segment and overlay:**

| Mode | When |
|---|---|
| `fill` | Same orientation as the master. Scale to cover, then crop centred on the mean face centre (or the frame centre). |
| `crop` | Opposite orientation, and the source short side is at least `reframe.min_crop_short_side`. A face-centred crop. |
| `static_bg` | Opposite orientation and the source is too small. Fit the clip on a blurred, darkened **still** frame from the same clip. |
| `v360` | Equirect or dual fisheye. `path` holds `[frame, yaw, pitch, hfov]` keyframes, built by `plan/camera360.py`. |

`stabilize: true` is set when a segment's p90 jitter is at least `quality.jitter.medium` and the camera kind is not `gimbal` or `360`.

**Timeline schema:**

```json
{"version": 1, "name": "...", "fps": [30, 1], "width": 1920, "height": 1080, "sample_rate": 48000,
 "chapters": [{"index": 1, "name": "...", "start_frame": 0, "end_frame": 900}],
 "segments": [{"id": "s00001", "clip_id": "...", "src_in": 12.4, "frames": 150, "start_frame": 0,
               "kind": "conversation", "moment_id": "...", "event_id": "...", "chapter": 1,
               "reframe": {"mode": "fill", "cx": 0.5, "cy": 0.5}, "stabilize": false, "gain_db": 0.0}],
 "overlays": [{"id": "o00001", "clip_id": "...", "src_in": 3.0, "frames": 60, "start_frame": 120,
               "reframe": {}, "stabilize": false, "reason": "cover_pause"}]}
```

Segments tile the timeline exactly: each `start_frame` is the previous `start_frame + frames`. Overlays always fall inside segment time. Segments also carry `moment_ids` (every moment merged into them) and `join` (`start` or `hidden_pause`). The timeline also carries `orientation` and `total_frames`. Pieces are rendered in parallel (`render.workers`) and are resumable.

### 6.7 360 camera paths (`plan/camera360.py`)

Inputs: the partner face directions from `faces.json` (`yaw`) and the speaker turns.

| Moment | Camera target |
|---|---|
| Conversation, both partners within `insta360.both_partners_max_spread_deg` | The circular mean of their yaws, with `hfov = clamp(spread + 40, min_hfov, 120)`. |
| Conversation, partners further apart | The speaking partner, with a cut when the speaker changes. Each hold lasts at least `insta360.min_shot_hold_s`. |
| Action | The visible partner. |
| Coverage | The highest-interest tagged view. |

Between cuts, yaw is rate-limited to `insta360.max_yaw_speed_dps`, with easing. Pitch is clamped to ±`insta360.pitch_limit_deg`. `hfov` is at least `insta360.min_hfov_deg` for the source width: 90° below 7680 px, 80° otherwise.

### 6.8 Render (`magicvideo/render/`)

1. **Pieces:** cut the timeline at every segment and overlay boundary. Each piece takes its video from the overlay if one is present, otherwise from the segment, and runs a fixed number of frames. Video-only intermediates are encoded with `libx264 -crf <render.intermediate_crf> -preset veryfast`, yuv420p, at constant fps:
   - `-ss <src_in>` before `-i`, then `setpts=PTS-STARTPTS`.
   - Then the orientation fix (overrides and analysis), stabilization, reframe and `fps`.
   - `tpad` clones the last frame if the source runs short, and the frame count is forced with `-frames:v`.
2. **Audio:** each segment's sample range is `[round(start_frame·sr/fps), round(end_frame·sr/fps))`. That range is extracted from its source as s16 stereo 48 kHz, padded or trimmed to the exact sample count, and given `render.audio_fade_ms` fades at both ends. Clips without audio give silence. Concatenating the ranges gives `master.wav`, sample-exact.
3. **Dialogue level matching:** each conversation segment's speech loudness is measured, and its gain is moved toward the median of all conversation segments, by at most ±`audio.dialogue_match_max_db`.
4. **Loudness:** measure the master with loudnorm in measurement mode. If the measured TP plus the gain needed would exceed `audio.true_peak_dbtp`, apply an oversampled limiter (192 kHz `alimiter`) first and measure again. Then apply the gain with `volume` — always linear by construction — and verify that I is within ±`audio.integrated_tolerance` and that TP is at or below the limit.
5. **Encode:**
   - Each chapter's video is the concat of its pieces, encoded with `libx264 -crf <output.video.crf> -preset <preset> -profile:v high`, yuv420p.
   - Master video: the chapter videos concatenated by stream copy.
   - Master: master video + AAC encoded once from `master.wav`, with `+faststart`.
   - Each chapter file: chapter video + its own sample slice of the processed `master.wav`.
6. **Exports:**
   - `<Name>_vNNN.otio`, with `opentimelineio`: V1 segments, V2 overlays, A1 audio, media references to the original sources, and chapter markers.
   - `<Name>_vNNN_edl.csv`.
   - `render_vNNN.json`, which records the loudness measurements, the limiter decision and the commands that were run.
7. **Stabilization backend:** use `vidstabdetect`/`vidstabtransform` when ffmpeg has them. Otherwise use `deshake`, followed by a zoom crop of `quality.stabilize_max_zoom`. The choice is recorded per piece.

### 6.9 QC (`magicvideo/qc/`)

Each check is `{id, status: PASS|FAIL|SKIPPED, value, limit, detail}`. The verdict is FAIL if any check fails, INCOMPLETE if any check was skipped, and PASS otherwise.

**Technical checks:**

| Check | Pass condition |
|---|---|
| `decode.clean` | `ffmpeg -v error … -f null -` prints nothing |
| `video.resolution` | equals the timeline |
| `video.fps` | equals the timeline |
| `video.pix_fmt` | yuv420p |
| `video.profile` | High |
| `audio.format` | aac, 48 kHz, 2 channels |
| `av.drift_ms` | ≤ `qc.av_drift_ms_max` |
| `duration.matches_timeline` | ≤ 1 frame difference |
| `loudness.integrated` | I within tolerance |
| `loudness.true_peak` | TP at or below the limit |
| `loudness.linear` | from `render_vNNN.json` |
| `container.faststart` | `moov` before `mdat` |
| `chapters.sum` | chapter durations sum to the master duration |

**Editorial checks:**

| Check | How it's measured / pass condition |
|---|---|
| `speech.partner_words_planned` | Partner words of kept conversations present in timeline audio, ≥ `qc.couple_word_retention_min` |
| `speech.partner_words_rendered` | Independent re-transcription of the master with the ASR backend, aligned (difflib) against the planned partner words, ≥ `qc.rendered_word_match_min` (lower than the planned limit, because ASR is noisy). SKIPPED without an ASR backend. |
| `edit.unhidden_conversation_jump_cuts` | ≤ `qc.unhidden_conversation_jump_cuts_max` |
| `edit.transit_share` | ≤ `film_limits.transit_share_max` |
| `edit.third_party_share` | ≤ `film_limits.third_party_share_max` |
| `edit.max_gap_without_partner_s` | ≤ `film_limits.max_gap_without_partner_s`. Partner presence comes from labelled speech and identified faces mapped through the timeline; SKIPPED when there are no refs. |
| `edit.event_over_budget` | ≤ `qc.event_over_budget_max` |
| `edit.orientation` | Every segment's reframe mode is valid for its source and the master |

## 7. Testing

- **Unit tests** (`tests/`) cover:
  - filename and capture-time parsing, camera and projection detection;
  - turn building and conversation joining;
  - pause classification;
  - budgets, MMR and guards;
  - frame and sample quantization (no drift over 1,000 segments at 30000/1001);
  - camera-path rate limiting;
  - the QC verdict logic;
  - determinism (planning twice gives identical JSON).
- **End-to-end** (`tests/test_e2e.py`): synthetic clips generated with ffmpeg (landscape with tone, portrait, shaky, 2:1 equirect), plus synthetic analysis files that stand in for the model backends, go through `plan → render → qc`. The test asserts frame counts, A/V drift and the reframe modes used.
- **Model backends** (faster-whisper, speechbrain, insightface, the cloud tagger) are *not* exercised in CI. They need a one-time manual check on real sample clips, which is recorded in `docs/VERIFICATION.md`.

## 8. Known unknowns (need real sample files)

| Item | Needed | Fallback until then |
|---|---|---|
| X6 `.insv` layout (streams, lens FOV, LRV format) | 10–20 s `.insv` + `.lrv` | Use Studio equirect exports; `.insv` dual-fisheye is analysis-only unless `insta360.allow_unstitched_render` |
| Osmo Nano / Pocket 4P metadata (model tag, gyro, timezone) | one short clip each | Detect DJI by filename and tags; decide stabilization from measured jitter |
| D-Log M / HLG usage | the camera's color settings | Detect and warn; no LUT is applied unless `color.luts` maps the profile to a file |

## 9. Agent rules (for Antigravity / Claude runbooks)

Run `magicvideo` commands and report the QC verdict and its failing checks word for word. Propose `policy.yaml` changes with a reason. Never write or edit `timeline*.json`, `plan*.json`, `qc*.json` or anything under `output/` by hand.

## 10. Round 2 changes

Source: `docs/R2_BRIEF.md`. Where this section differs from §1–§9, this section wins.

**Couple prior.** Speech the voice references do not match is the couple's, unless a stranger's face is on screen.
- Policy keys: `identity.couple_prior` (default `true`; `false` restores the old labels exactly), `identity.stranger_face.max_similarity` (0.20), `identity.stranger_face.min_q` (0.5), `identity.stranger_face.pad_s` (1.0).
- Label `COUPLE` (`analysis/voices.py`) is a speaker label next to `PARTNER_A`, `PARTNER_B`, `OTHER` and `UNKNOWN`; `is_couple_speaker` is true for it.
- `analysis/voices.py::window_best_scores`, `analysis/faces.py::stranger_times` and `plan/data.py::apply_couple_prior` implement it. An `OTHER` window becomes `COUPLE` unless a stranger time `t` satisfies `w.t0 - pad_s <= t <= w.t1 + pad_s`. `load_clip` loads faces before building turns.
- `Moment.identity` (dict, serialised in the plan) holds `voice_best`, `stranger_on_screen` and `assumed_couple` for conversation and third-party moments; the storyboard card shows it as one line.

**Enrollment.** `magicvideo enroll <work> --finalize [--merge SRC:DST]... [--allow-sparse]`.
- `--merge` counts the files of folder SRC under partner folder DST. Errors (exit 1, nothing written): a folder is missing, the kinds differ (`person_` vs `voice_`), SRC is also a DST, the same SRC twice.
- Every non-empty folder is counted after merges; if the count is not 2 the report lists the folders with their counts. A partner below `enrollment.min_kept_per_partner.<kind>` is refused unless `--allow-sparse` (minimum 1), which adds a `sparse:` line. A reference built from a single clip adds a `warning:` line.
- `refs.npz` additionally stores `<kind>_<slot>_all` (stacked, L2-normalised embeddings). Voice scoring uses `max(centroid score, best single-row score)`; faces keep centroid scoring. Voice swapping swaps the centroid, the count and the `_all` rows together.

**Stale references.** `plan_vNNN.json` carries `refs_sha256` (sha256 of `refs.npz`, or null). `plan/planner.py::stale_refs` compares it with the current file; `magicvideo render`, `magicvideo review` and the storyboard banner report a mismatch.

**Review server.** `magicvideo review <work> [--plan vNNN] [--port N] [--no-open]` (`magicvideo/review.py`, standard library only; policy `review.port`, default 8765). It binds 127.0.0.1 only and answers 403 to any request whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>`; every POST needs `Content-Type: application/json` (else 415).
- `GET /` storyboard · `GET /thumbs/<name>` (only inside `plan/thumbs/`) · `GET /api/overrides` → `{"overrides", "version", "stale_refs"}` · `POST /api/moment` `{"id", "value": keep|drop|couple|clear}` (unknown id or value → 400) · `POST /api/replan` → `{"version"}`.
- `overrides.yaml` is read as `utf-8-sig`, rewritten with `yaml.safe_dump(sort_keys=True)` via a temp file and `os.replace`, comments are lost, the old file is copied to `overrides.yaml.bak` once per server session, `clear` deletes the key.
- New override value `couple` ("this is us"): `plan/budget.py::apply_overrides` sets `cls = "couple"`; the moment is then treated like `keep` and counts in the couple share.

**Scene tags by the agent (no API key).** `cloud.provider` defaults to `agent`; `anthropic` stays supported (and raises `BackendMissing` when no key is available).
- `analyze` (tags step) calls `analysis/tags.py::export_for_agent`, which writes `<work>/tagging/<clip_id>/grid_NNN.jpg` and `grid_NNN.cells.json`, and records the step status `skipped: awaiting agent tags`. `<work>/tagging/TASKS.md` holds the prompt, the allowed lists, the response schema, the answer-file rule and a checklist.
- The agent writes `grid_NNN.answer.json` (`{"cells": [...]}`) next to each grid. `magicvideo tags export <work>` and `magicvideo tags import <work>` run the two halves; import validates cells 1..n, merges into `analysis/<clip>/tags.json` (backend `agent`, idempotent on `(t, view)`), and sets `tags: done` for a clip whose grids are all imported.
- Privacy: only these low-res grids are seen by the agent's model.

**Other.** Capture times are read from file names with a prefix (`026_DJI_2026…`, `(?:^|(?<=[^A-Za-z0-9]))` instead of `^`). The end-to-end test pins QC to "no ASR".

## 11. Round 3 changes

Source: `docs/R3_BRIEF.md`. Where this section differs from earlier sections, this section wins.

**Rendered-speech QC.** `speech.partner_words_rendered` compares tokens, not Whisper words. `qc/runner.py::speech_tokens` normalises each word, splits words containing CJK ideographs, hiragana or katakana into single characters (Latin/digit runs inside stay one token) and, when `qc.fold_chinese_script` is true and `zhconv` imports, folds Simplified/Traditional with `zhconv.convert(ch, "zh-hans")`. `rendered_speech_check` matches planned tokens (each with the master time of its word, in film order) against the heard tokens with `difflib.SequenceMatcher(autojunk=False)` and returns `ratio`, `matched`, `total`, `folded` and `missing_runs` (runs of at least `qc.speech_missing_run_min` unheard planned tokens, with master `t0`/`t1`). `magicvideo qc` writes `qc/<master stem>_speech.json` (`planned`, `heard`, `result`). Without zhconv folding is off and the check detail says so. New optional extra: `zh = ["zhconv>=1.4"]` (also in `all`).

**Whisper hallucinations.** `asr_filter` policy (`enabled`, `phrases`, `no_speech_prob_min`, `avg_logprob_max`). `analysis/asr.py` now stores `no_speech_prob`, `avg_logprob` and `compression_ratio` per segment (older transcripts lack them). `plan/data.py::drop_hallucinations` removes the words of a segment whose normalised text is in the phrase list, or whose stored `no_speech_prob >= no_speech_prob_min` and `avg_logprob <= avg_logprob_max` (both must be stored and hold); it remaps voice windows and embedding rows. Word probability is never used. `load_clip` stores `ClipData.dropped_speech`; the plan warns once per dropped segment.

**Edge speech.** `moments.edge_speech: {start_s, end_s}`. `plan/planner.py::edge_speech_warnings` warns when a selected conversation's last word ends within `end_s` of the clip end, or its first word starts within `start_s` of the clip start.

**Insta360 from the preview.** `insta360.plan_unstitched` (default true): `plan/planner.py::filter_plannable` keeps unstitched `.insv` clips (planned from the `.lrv`) with a warning instead of skipping them. `x6_export_list(timeline, inventory, policy)` lists the unstitched clips the timeline uses, with `uses` ranges; `run_plan` writes `plan/x6_exports_<tag>.md` (only when non-empty) and adds a plan warning. `Renderer.run` raises `ProjectError` naming the files and the `.md` before creating any output. Clip ids hash the primary `.insv` path, so ids, moment ids and overrides survive when the Studio export appears.

**Names.** `ingest.insta360_key` and `detect_camera` use `.search` on `_INSTA_RE` / `_DJI_RE`, so prefixed names (`026_VID_…`, `034_DJI_…`) group and detect.

## 12. Round 4 changes

Source: `docs/R4_BRIEF.md`. Where this section differs from earlier sections, this section wins.

**True peak after encoding.** The AAC encode can create peaks the PCM master does not have, so the final encode is verified. Policy `audio.post_encode_check` (true), `post_encode_max_passes` (3), `post_encode_margin_db` (0.3), `post_encode_dip_win_ms` (40), `post_encode_global_max_db` (0.8). `Renderer._encode_verified` encodes to `master_try.mp4` in the work folder, measures true peak, and while it is above `audio.true_peak_dbtp` (and passes remain) scans the encoded file with `render/audio.py::scan_true_peaks` (4x oversampled, chunked decode) and applies raised-cosine gain dips of `excess = TP - limit + margin` dB (`apply_dips`, minimum gain where windows overlap) to the master wav through a memory map, then re-encodes and re-measures. With no overshoot spot found it lowers the wav by `excess` dB if that is at most `post_encode_global_max_db`, otherwise it stops. The chapters are encoded from the repaired wav. The result is stored as `loudness.post_encode` in the render log: `passes`, `tp_first`, `tp_final`, `dips` (3 dp), `global_db`, `note` (`ok`, `repaired`, `gave up: TP still above limit`); QC still fails honestly when it gave up. `post_encode_check: false` encodes once as before.

**Per-language speech QC.** `analysis/asr.py::transcribe(path, policy, language=None)` passes `language` to Whisper. The QC takes the timeline segments that carry planned partner words, `qc/runner.py::language_spans` groups them into spans of one clip language (the `language` stored in each clip's `transcript.json`; neighbours closer than `qc.speech_span_merge_gap_s`, 2.0 s, merge), cuts each span from the master (plus 0.3 s each side), transcribes it in its own language and concatenates the heard words in film order. The speech report gains `spans`.

**Edge warnings.** `moments.edge_speech.camera_originals` (false): clips whose `capture_source` is `filename` (camera-named originals) get no edge warning unless it is true.

**Console.** `cli._utf8_console` reconfigures stdout/stderr to UTF-8 (`errors="replace"`), called first in `main`.
