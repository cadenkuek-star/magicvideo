# R2 handover (Coder A)

Branch `r2/identity-review` from `1e0dded`. Linux cloud workspace (`/home/claude/cadenkuek-star/magicvideo`), so the
Windows paths and `certutil` in the relay were replaced as instructed. Nothing was pushed or merged.

## 1. Work items

| Item | Test commit | Fix / feature commit | Files touched | What changed |
| --- | --- | --- | --- | --- |
| Step 0 | - | `96718e5` | `docs/R2_BRIEF.md`, `docs/R2_RELAY.md`, `docs/R2_SKILL_magicvideo.md` | Three docs committed unchanged. |
| W1 | `65d8e55` | (test-only change) | `tests/test_e2e.py` | `test_plan_render_qc` takes `monkeypatch`; `asr.transcribe` raises `BackendMissing` before `run_qc`. The `refs_sha256` assertion is in the W6 test commit (see Parked 1). |
| W2 | `26d4161` | `6d60fc7` | `magicvideo/analysis/tags.py`, `tests/test_tags.py` | `Tagger.__init__` raises `BackendMissing` when no key and no env var exist. |
| W3 | `f99b7d9` | `2059d79` | `magicvideo/ingest.py`, `tests/test_ingest.py` | Three regexes use `(?:^\|(?<=[^A-Za-z0-9]))`; `filename_time` uses `.search`. |
| W4 | `752c01a` | `83d397e` | `default_policy.yaml`, `analysis/voices.py`, `analysis/faces.py`, `plan/data.py`, `plan/model.py`, `plan/moments.py`, `plan/storyboard.py`, `tests/test_moments.py` | `COUPLE` label, `window_best_scores`, `stranger_times`, `apply_couple_prior`, faces loaded before turns, `window_evidence`, `Moment.identity`, storyboard evidence line. |
| W5 | `cdea6c4` | `42dd45a` | `enroll.py`, `analysis/voices.py`, `cli.py`, `tests/test_enroll.py` | `--merge`, `--allow-sparse`, all folders counted, messages, `*_all` refs, multi-reference voice scoring, diversity warning, `next:` line, `REVIEW_TEXT`. |
| W6 | `4f7b35c` | `ce40222` | `enroll.py`, `plan/planner.py`, `cli.py`, `tests/test_review.py`, `tests/test_e2e.py` | `refs_fingerprint`, `plan["refs_sha256"]`, `stale_refs`, `warn_if_stale` (used by `render`). |
| W7 | `6b3d7f0` | `1e72df6` | `review.py` (new), `plan/storyboard.py`, `plan/budget.py`, `plan/planner.py`, `cli.py`, `default_policy.yaml`, `tests/test_review.py`, `tests/test_budget.py` | Loopback review server and routes, clickable storyboard (live and offline modes, stale banner), `couple` override, `review.port` policy, `magicvideo review`. |
| W8 | `f6a5d7b` | `b5b441c` | `analysis/tags.py`, `analysis/runner.py`, `cli.py`, `default_policy.yaml`, `tests/test_agent_tags.py` (new) | `clean_cells`, `export_for_agent`, `write_tasks`, `export_all`, `pending_grids`, `import_agent_tags`, `tags export/import`, provider `agent` default, docstring privacy rule. |
| W9 | - | `969292e` | `agent/SKILL.md` | Byte-identical copy of `docs/R2_SKILL_magicvideo.md` (the two `C:\Travel` copies are the reviewer's job). |
| W10 | - | `51478b7` | `docs/IMPLEMENTATION_BRIEF.md` | `## 10. Round 2 changes` appended (29 added, 0 deleted lines). |

Per ruling R2-0 the five W8 tests are in `tests/test_agent_tags.py`; the W2 test stays in `tests/test_tags.py`.
Test-first order holds for W2 to W8. In W5 the feature commit also adjusts the test data (voice_001 gets 4 clips so
the merge suggestion has no size tie); in W7 it also fixes one assertion in my own foreign-host test (it searched for
the word "keep", which is in the overrides template comment).

## 2. Full suite (run once, at the end)

```
...................................................................      [100%]
67 passed in 18.25s

$ .venv/bin/python -m pytest --collect-only -q | tail -1
67 tests collected in 0.89s
```

Prediction was 67 collected, 67 passed: it matches. Baseline here was 37 collected, 37 passed, no difference to
explain. `faster-whisper` is not installed in this workspace, so W1's "passes with faster-whisper installed" is not
shown here (see section 5).

## 3. Self-check (Linux versions; verbatim)

The suite was not run a second time for the self-check; its result is section 2. `git status` and `git log` were
captured before this file was committed, so the handover commit is not in the log below.

```
$ git log --oneline 1e0dded..HEAD
51478b7 feat(W10): IMPLEMENTATION_BRIEF section 10, Round 2 changes (append only)
969292e feat(W9): agent/SKILL.md from docs/R2_SKILL_magicvideo.md (byte-identical)
b5b441c feat(W8): scene tags by the coding agent (export grids, import answers); provider agent is the default
f6a5d7b test(W8): agent tagging export/import (new file; needs no anthropic SDK)
1e72df6 feat(W7): review server, clickable storyboard, 'couple' override, review.port policy
6b3d7f0 test(W7): review server, storyboard offline download, couple override
ce40222 feat(W6): plan records refs_sha256; render warns when references changed
4f7b35c test(W6): stale partner references; e2e asserts refs_sha256 in the plan
42dd45a feat(W5): enroll --merge/--allow-sparse, clear errors, multi-reference voices
cdea6c4 test(W5): enrollment merge, sparse partners, messages, multi-reference voices
83d397e feat(W4): couple prior - unmatched speech is the couple's unless a stranger is on screen
752c01a test(W4): couple prior, stranger times, COUPLE turns
2059d79 fix(W3): match camera file-name times after a prefix
f99b7d9 test(W3): file-name capture times with a prefix
6d60fc7 fix(W2): Tagger raises BackendMissing when no Anthropic key is available
26d4161 test(W2): anthropic provider without a key must raise BackendMissing
65d8e55 test(W1): pin end-to-end QC test to no ASR
96718e5 R2: brief, relay, agent skill

$ git status --short

$ git diff --stat 1e0dded..HEAD
 agent/SKILL.md                 |  90 +++++++++---
 docs/IMPLEMENTATION_BRIEF.md   |  29 ++++
 docs/R2_BRIEF.md               | 320 +++++++++++++++++++++++++++++++++++++++++
 docs/R2_RELAY.md               |  77 ++++++++++
 docs/R2_SKILL_magicvideo.md    |  86 +++++++++++
 magicvideo/analysis/faces.py   |  14 ++
 magicvideo/analysis/runner.py  |  13 ++
 magicvideo/analysis/tags.py    | 220 +++++++++++++++++++++++++---
 magicvideo/analysis/voices.py  |  32 ++++-
 magicvideo/cli.py              |  55 ++++++-
 magicvideo/default_policy.yaml |  10 +-
 magicvideo/enroll.py           | 150 ++++++++++++++++---
 magicvideo/ingest.py           |  12 +-
 magicvideo/plan/budget.py      |  16 ++-
 magicvideo/plan/data.py        |  43 +++++-
 magicvideo/plan/model.py       |   3 +-
 magicvideo/plan/moments.py     |  17 ++-
 magicvideo/plan/planner.py     |  21 ++-
 magicvideo/plan/storyboard.py  |  93 ++++++++++--
 magicvideo/review.py           | 205 ++++++++++++++++++++++++++
 tests/test_agent_tags.py       | 122 ++++++++++++++++
 tests/test_budget.py           |  22 +++
 tests/test_e2e.py              |   9 +-
 tests/test_enroll.py           | 121 ++++++++++++++++
 tests/test_ingest.py           |  11 ++
 tests/test_moments.py          |  56 ++++++++
 tests/test_review.py           | 175 ++++++++++++++++++++++
 tests/test_tags.py             |  13 ++
 28 files changed, 1935 insertions(+), 100 deletions(-)

$ git diff 1e0dded..HEAD --numstat -- docs/IMPLEMENTATION_BRIEF.md
29	0	docs/IMPLEMENTATION_BRIEF.md

$ git grep -n "0.0.0.0" -- magicvideo

$ git grep -n "_RE = re.compile" -- magicvideo/ingest.py
magicvideo/ingest.py:21:_DJI_RE = re.compile(r"(?:^|(?<=[^A-Za-z0-9]))DJI_(\d{14})_(\d{4})", re.I)
magicvideo/ingest.py:22:_INSTA_RE = re.compile(r"(?:^|(?<=[^A-Za-z0-9]))(VID|LRV|PRO_VID|PRO_LRV|IMG)_(\d{8})_(\d{6})_(\d{2})_(\d{3})", re.I)
magicvideo/ingest.py:23:_PIXEL_RE = re.compile(r"(?:^|(?<=[^A-Za-z0-9]))(?:PXL|VID|IMG)_(\d{8})_(\d{6})", re.I)

$ sha256sum agent/SKILL.md docs/R2_SKILL_magicvideo.md
47d8a813d32bf587c709566d96ff5b053fd5c501866546089f4fc3a26e1d4621  agent/SKILL.md
47d8a813d32bf587c709566d96ff5b053fd5c501866546089f4fc3a26e1d4621  docs/R2_SKILL_magicvideo.md
```

The relay's two `certutil` lines for `C:\Travel\.agents\skills\magicvideo\SKILL.md` and
`C:\Travel\skills\magicvideo\SKILL.md` were not run: nothing is written outside the repo (adjustment 2).

## 4. Parked

1. **W1 vs W6 order.** The brief puts `assert "refs_sha256" in plan` in W1's test, but it cannot pass before W6.
   I put it in the W6 test commit (`4f7b35c`). Need: confirm that is acceptable.
2. **W4 storyboard line.** The example always ends with `treated as you two (N windows)`. I print that part only when
   `assumed_couple > 0`. Need: say if it should always show.
3. **W7 `couple` override, three consequences of "treat exactly like keep".**
   (a) `apply_overrides` sets `cls = "couple"` before selection, so the third-party list and the coverage candidate
   list in `select_event` no longer matched such a moment; I widened both filters to admit a moment whose override is
   `couple` (a `third_party` kind goes through the third-party branch, a `coverage` kind through the forced-keep
   coverage branch, never both).
   (b) In the third-party branch the moment is still trimmed to `third_party.excerpt_max_s` before the override check,
   so a long "this is us" moment is cut to 8 s.
   (c) It still adds to the per-event third-party budget counter (`third_party_used`, shown as "other people" on the
   storyboard) although it counts in the couple share. Need: rulings on (b) and (c).
4. **W5 report wording.** The brief gives the "need exactly 2" example only for 3 folders. For fewer than 2 I print
   the count and folder list without the "delete or fold" advice. The `--merge` suggestion is "smallest folder into the
   next-smallest" (this reproduces the example; ties break by folder name). The report's `sparse` and `warning` entries
   are lists, printed one `sparse:` or `warning:` line each. Face counts use "images", voices "clips".
5. **W5 voice swap.** The swap heuristic (and `swap_voices` in `load_refs`) now swaps `voice_*_count` and
   `voice_*_all` together with the centroids; without that the multi-reference rows would end up under the wrong
   partner. Approved files merged from SRC are copied as `<trip>_<SRC>_<file>` to avoid name clashes.
6. **W7 "N changes".** I count successful clicks in this page session, not entries in `overrides.yaml`.
7. **W7 download button id.** The brief does not name it; I used `download-overrides`.
8. **W3 scope.** Only `filename_time` uses `.search`, as written. `insta360_key` and `detect_camera` still use
   `.match`, so a prefixed `.insv` name gets a capture time but is not grouped or detected as Insta360 by name.
9. **QC.** `qc/runner.py` (max-gap-without-partner check, around line 213) tests `speaker in PARTNERS`, so `COUPLE`
   labelled speech is not counted as partner presence there. Not in the brief; not changed.
10. **Overrides template.** The comment in `project.py::OVERRIDES_TEMPLATE` does not list `couple`. Not in the brief; not changed.

## 5. What I did NOT verify

- The storyboard JavaScript in a browser (no browser allowed). Only `node --check` for syntax, plus a stubbed run of
  the YAML builder, whose output parsed with PyYAML.
- The page against a real running `magicvideo review` (the tests drive the server through `urllib` on port 0).
- Any real footage, real models, Windows paths or the Windows firewall; the couple prior and the 0.20 threshold on
  real clips; Gemini's grid answers.
- W1 with faster-whisper installed (it is not installed here); only the no-ASR case ran.
- "Analyze with provider anthropic and no key records SKIPPED, no crash" (work table, W2) has no test of its own: the
  runner already turns `BackendMissing` into a skipped status and the new test covers the raise.
- The mutation list in brief section 6 was not run (that is the reviewer's job).

## Coder response R01

Review `docs/R2_REVIEW.md` committed unchanged first (`bcac647`). Same branch; nothing pushed or merged.

| Ruling | Test commit | Fix commit | What changed |
| --- | --- | --- | --- |
| R01-1 | `b3ed7e9` | `b24453f` | `select_event`: a `third_party` moment overridden to `couple` skips `_trim_excerpt`, is selected whole with reason `kept in review (this is us)`, and is not added to `used` / `third_party_used`. |
| R01-2 | `2d3f3ce` | `2759f69` | `qc/runner.py::_partner_heard` (uses `is_couple_speaker`, False for no clip) replaces the `in PARTNERS` check in the max-gap loop. |
| R01-3 | `a3b0a6c` | `28a2e13`, `4d7c0a6` | `voice_best` is `None` in `window_evidence` without voice refs; `_identity` omits the key then; the storyboard line prints the voice part only when present. |
| R01-4 | none | `03e4892` | `OVERRIDES_TEMPLATE` comment lists `couple` ("couple = this is us: count as couple time"). |

Slip, corrected: the R01-3 fix commit `28a2e13` accidentally deleted `_js_json` from `plan/storyboard.py` (two storyboard tests failed); `4d7c0a6` restores it byte-for-byte. The suite was run only after that.

Full suite (run once, at the end): `71 passed in 19.26s`; `pytest --collect-only -q`: `71 tests collected` (matches the prediction).

Self-checks:
```
$ git grep -n "0.0.0.0" -- magicvideo
(empty)
$ git status --short
(clean, taken before this section was committed)
$ git log --oneline 6b5c3a0..HEAD   (before the handover commit)
4d7c0a6 fix(R01-3): restore _js_json that the previous commit removed by mistake
03e4892 fix(R01-4): overrides template lists the couple value
28a2e13 fix(R01-3): no voice score shown when there are no voice references
2759f69 fix(R01-2): QC max-gap check counts COUPLE speech as partner heard
b24453f fix(R01-1): couple-override moment is selected whole, not trimmed or budgeted
a3b0a6c test(R01-3): no voice score without voice references
2d3f3ce test(R01-2): COUPLE speech counts as partner heard in the QC gap check
b3ed7e9 test(R01-1): couple override is not trimmed or budgeted
bcac647 docs: R2 review R01
```

Parked: none. Left as is: the `PARTNERS` import in `qc/runner.py` is now unused there.
