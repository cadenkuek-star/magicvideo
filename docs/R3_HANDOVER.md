# R3 handover (Coder A)

Branch `r3/speech-qc-x6` from `2c0f6d6`. Nothing pushed or merged.

## 1. Work items

| Item | Test commit | Feature/fix commit | Files | What changed |
| --- | --- | --- | --- | --- |
| Step 0 | - | `159d448` | `docs/R3_BRIEF.md` | Brief committed unchanged. |
| W1 | `1d36fd2` | `ad463b4` | `qc/runner.py`, `default_policy.yaml`, `pyproject.toml`, `tests/test_qc_speech.py` | `speech_tokens`, `rendered_speech_check`, master times for planned words, `<master>_speech.json`, `qc.fold_chinese_script`/`speech_missing_run_min`, `zh` extra, unused `PARTNERS` import removed. |
| W2 | `3775b8e` | `e90e87d` | `analysis/asr.py`, `plan/data.py`, `plan/planner.py`, `default_policy.yaml`, `tests/test_asr_filter.py` | `asr_filter` policy, segment scores stored, `drop_hallucinations` (windows and emb remapped), `ClipData.dropped_speech`, plan warnings. |
| W3 | `3f8a97d` | `a56e142` | `plan/planner.py`, `default_policy.yaml`, `tests/test_moments.py` | `edge_speech_warnings` and `moments.edge_speech`; joins plan warnings. |
| W4 | `29d4426` | `796dd95` | `plan/planner.py`, `render/renderer.py`, `default_policy.yaml`, `tests/test_x6_flow.py` | `filter_plannable`, `x6_export_list`, `x6_exports_<tag>.md` and warning, renderer refuses before any output, `insta360.plan_unstitched`. |
| W5 | `fff8a83` | `fb7d4e8` | `ingest.py`, `tests/test_ingest.py` | `.search` in `insta360_key` and `detect_camera`. |
| W6 | - | `644d57f` | `docs/IMPLEMENTATION_BRIEF.md`, `agent/SKILL.md` | Section 11 appended; SKILL block inserted before "Render and check" (additions only). |

## 2. Full suite (run once, at the end)

```
89 passed in 19.36s
89 tests collected in 0.89s
```
Matches the prediction (89 / 89, zhconv installed).

## 3. Self-checks (verbatim; taken before this file was committed)

```
$ git log --oneline 2c0f6d6..HEAD
644d57f docs(W6): contract section 11 and agent skill additions (append only)
fb7d4e8 fix(W5): search, not match, for prefixed Insta360/DJI names
fff8a83 test(W5): prefixed Insta360/DJI names
796dd95 feat(W4): plan unstitched Insta360 from preview, export list file, renderer refusal
29d4426 test(W4): Insta360 plan-from-preview flow
a56e142 feat(W3): warn when speech runs into the edge of a source file
3f8a97d test(W3): edge speech warnings
e90e87d feat(W2): ignore Whisper hallucinations (phrase list and score rule), plan warnings
3775b8e test(W2): Whisper hallucination filter
ad463b4 feat(W1): fair rendered-speech QC (character tokens, script folding, unheard runs, speech report)
1d36fd2 test(W1): rendered-speech QC tokens, folding, missing runs
159d448 R3: brief

$ git status --short

$ git diff --numstat 2c0f6d6..HEAD -- docs/IMPLEMENTATION_BRIEF.md agent/SKILL.md
10	0	agent/SKILL.md
14	0	docs/IMPLEMENTATION_BRIEF.md

$ git grep -n "\.match(name)" -- magicvideo/ingest.py

$ git grep -n "PARTNERS" -- magicvideo/qc/runner.py
```
(The `PARTNERS` and `.match(name)` greps are empty.) The numstat for the two files shows 0 deletions each.

## 4. Parked

1. W4 test `test_clip_id_stable_when_export_added` uses unprefixed file names (`VID_...`), so it does not depend on W5; with prefixed names it would only pass after W5. The change was made in the W4 feature commit, not in the test commit.
2. W1: `folded` in the result is true only when folding was requested and zhconv imports. `rendered_speech_check` returns ratio 0.0 for an empty planned list (the caller never reaches it then).
3. W2: `dropped.text` is the segment text stripped of surrounding whitespace.
4. W3: the brief gives no text for the "starts" warning beyond "same shape"; I used "speech starts at the very beginning of the file (first word starts at Xs); the sentence may be cut. If you trimmed this clip, export it a few seconds earlier." Words of the moment are taken with `words_in(m.t0, m.t1)`.
5. W4: the renderer test patches `magicvideo.render.renderer.x6_export_list` (the name imported into the renderer); patching only `plan.planner.x6_export_list` would not affect the renderer. Whether Studio's default export name is `VID_..._004.mp4` is assumed in the test only.
6. W4: `run_plan` computes the export list from the finished timeline and appends the warning to `plan["warnings"]` before writing the plan (the storyboard shows it).

## 5. What I did NOT verify

- That folding plus character matching lifts the owner's score above 0.9 (no heard transcript here).
- The X6 flow on real `.insv`/`.lrv`; Whisper's `no_speech_prob`/`avg_logprob` on real footage (the segment fields are read with `getattr`, untested against faster-whisper).
- The `Renderer` refusal path was tested with a patched export list and an empty timeline, not a real render.
- The mutation list in brief section 5 was not run (reviewer's job).

## Coder response R01

Review `docs/R3_REVIEW.md` committed unchanged first (`d822d61`). Same branch; nothing pushed or merged.

| Ruling | Test commit | Fix commit | What changed |
| --- | --- | --- | --- |
| R01-1 | `ca7f34c` | none (test only) | `test_edge_speech_uses_last_word_not_moment_edge`; it passed against the current code, no production change. |
| R01-2 | `b2b9836` | `48a5d58` | `qc/runner.py::collect_planned_words` extracted from `editorial` unchanged; `test_planned_words_follow_film_order`. The test commit alone fails at import, as expected. |

Full suite (run once, at the end): `91 passed in 20.75s`; `pytest --collect-only -q`: `91 tests collected` (matches the prediction).

```
$ git status --short
(clean, taken before this section was committed)
$ git log --oneline 66e7267..HEAD   (before the handover commit)
48a5d58 fix(R01-2): extract collect_planned_words from editorial (no behaviour change)
b2b9836 test(R01-2): planned words follow film order
ca7f34c test(R01-1): edge speech uses the last word, not the moment edge
d822d61 docs: R3 review R01
```

Parked: none. Note: in `tests/test_qc_speech.py` I added a `from helpers import policy` import at the top for the new test.
