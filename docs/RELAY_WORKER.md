# Relay: resume magicvideo on the owner's PC (new AI worker replacing Antigravity)

You are the new **operator** on the owner's Windows PC: a **Claude Code** session opened in `C:\Travel\magicvideo`.
The previous operator (Antigravity) ran out of tokens mid-trip. Code changes are made by a separate Claude Code
session (the author); you run the tool, look at frame grids when asked (section 6), and report. Read this file
fully, then do section 3 in order.

**There is no Anthropic API key on this PC, and none is needed.** Scene tagging uses `cloud.provider: agent` (the
default): magicvideo writes small frame-grid images to disk and *you* look at them with your Read tool and write
the answers. Never switch a trip to `cloud.provider: anthropic`.

**Model:** run this session on Claude Sonnet 5.5 (`/model sonnet`). It follows the stop points reliably and reads
images well. Tagging many grids can be handed to cheaper Haiku subagents (section 6.3).

**`CLAUDE.md` in this repo is written for the code author.** As operator you do not change code; where `CLAUDE.md`
and this relay differ, this relay wins.

## 1. What this is

`magicvideo` turns a trip's raw footage into one film per trip (plus per-day files, a DaVinci Resolve timeline and
a QC report). The CLI makes every editing decision from analysis files + `policy.yaml` + `overrides.yaml`.

| Thing | Where |
|---|---|
| Code (git) | `C:\Travel\magicvideo`, branch `claude/vibrant-brahmagupta-yr5pu4` (PR #1, not merged) |
| Python | `C:\Travel\magicvideo\.venv` (Python 3.11.9). Command: `C:\Travel\magicvideo\.venv\Scripts\magicvideo.exe` |
| Current trip | raw `D:\Photo\Travel\Pakistan 2024` → work `C:\Travel\work\Pakistan_2024` |
| Shared partner references | `C:\Travel\people` (`refs.npz` exists; enrollment is done; do not redo it) |
| Operator runbook | `agent\SKILL.md` (read it; it is your standing instructions) |
| Contract / rules for code | `docs\IMPLEMENTATION_BRIEF.md` (§15 round 7, §16 round 8 are the newest), `CLAUDE.md` |

## 2. Where the work stopped

- Pakistan_2024 was analysed (245 clips, `orient` step done), tagged (agent tags imported) and planned up to
  **plan v004**. The owner reviewed v004 and asked for changes; Claude implemented them as **round 8** (commit
  `ff0ac3d`): at most 2 B-roll shots per clip per event, similar shots cut to 3 s, `reframe.portrait_in_landscape:
  drop` now also drops portrait conversations, a false-retake fix, storyboard thumbnails shown rotated.
- **Not yet done on the PC:** pull round 7/8, re-plan (v005), owner review, render, QC.
- `C:\Travel\work\Pakistan_2024\policy.yaml` already has `reframe.portrait_in_landscape: drop` (owner request).
  `overrides.yaml` holds the owner's keep/drop decisions; it must survive.
- Antigravity may have left **uncommitted local edits** in `C:\Travel\magicvideo` (it edited `moments.py`,
  `assemble.py`, `default_policy.yaml` earlier) and possibly a stash named `local-before-r7`. Those edits are
  superseded by rounds 7–8. Never re-apply them.

## 3. Resume steps (PowerShell; report each CHECK verbatim)

**3.1 Code state**
```powershell
cd C:\Travel\magicvideo
git status --short
git stash list
git log --oneline -3
```
- If `git status` lists modified files: `git stash push -u -m "local-before-r8"` (keeps them, loses nothing).
- Then:
```powershell
git checkout claude/vibrant-brahmagupta-yr5pu4
git pull
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
pip install -e ".[dev]"
pytest -q
```
**CHECK:** `git log --oneline -1` shows the Windows file-lock fix (see the commit list) or newer; pytest ends with
`0 failed` (139 tests; one may be skipped when the `anthropic` package is not installed). If tests fail: STOP, report the full tail. Do not edit code to make them pass.

**3.2 Tool health**
```powershell
magicvideo doctor
```
**CHECK:** report the output (GPU, filters, installed backends).

**3.3 Re-plan Pakistan with round 8**
```powershell
Remove-Item -Recurse -Force C:\Travel\work\Pakistan_2024\plan\thumbs   # old thumbnails were cached flipped
magicvideo plan C:\Travel\work\Pakistan_2024 --thumbs
```
(`plan\thumbs` is a cache the next command rebuilds; nothing else may be deleted.)
**CHECK:** report the printed plan line and warnings, and the header line of
`C:\Travel\work\Pakistan_2024\plan\storyboard_v005.html` (moments, minutes, shares, retakes, portrait, rotated).
Expected compared with v004 (40.0 min, `portrait: 23`): fewer minutes, no selected portrait moments, no
6-shot runs from one clip.

**3.4 Owner review** — STOP and hand over to the owner:
```powershell
magicvideo review C:\Travel\work\Pakistan_2024
```
It opens http://127.0.0.1:8765/. Tell the owner: keep/drop any card, then **Re-plan now**; tell you when done.

**3.5 Render and QC** (only after the owner says go)
```powershell
magicvideo render C:\Travel\work\Pakistan_2024
magicvideo qc C:\Travel\work\Pakistan_2024
```
**CHECK:** report master/chapter/OTIO paths, the QC verdict and every non-PASS row of `qc\qc_vNNN.md`
(id, value, limit, detail). INCOMPLETE or FAIL is never "done".

## 4. Rules (same as Antigravity had)

1. Never write `plan\*.json`, `timeline_*.json`, `qc\*`, `analysis\*`, `output\*` by hand.
2. Raw footage is read-only. Never move, rename or delete source files.
3. Edit changes go through the review page or `overrides.yaml`; threshold changes through the trip's
   `policy.yaml`, with a one-line reason, then re-plan. Never change `magicvideo\default_policy.yaml` or code.
4. Something looks wrong in the edit (bad retake group, wrongly rotated clip, too long/short shots): report the
   moment ids and what you saw, plus the policy knob if you know it. Claude changes the code.
5. A command fails twice the same way: stop, report the command and its last 20 lines.
6. Never decide who the partners are; never print or store the API key.

## 6. Scene tags (new trips; Pakistan is already tagged)

`magicvideo analyze` ends with `tags: N grids waiting` when there are grids to look at.

**6.1 What a grid is.** `C:\Travel\work\<Trip>\tagging\<clip_id>\grid_NNN.jpg` is a 3×3 image of numbered
frames (cell 1 top-left, row by row). `tagging\TASKS.md` lists every unanswered grid, the allowed tags and the
answer format. Read TASKS.md first.

**6.2 Per grid:** open the jpg with the Read tool, then write `grid_NNN.answer.json` in the same folder:
```json
{"cells": [{"cell": 1, "tags": ["food", "table"], "people": "partners", "interest": 0.7, "desc": "noodles on the table"}]}
```
One entry per numbered cell; `tags` only from the allowed list; `people` one of none / partners / others / crowd /
mixed (`partners` = the travelling couple, `others` = guides, staff, performers, strangers in focus); `interest`
0.0–1.0; `desc` at most 12 words, what is visible only, no names or guessed places. Write the file with the Write
tool; never edit anything under `analysis\`.

**6.3 Many grids (Pakistan had 376): use Haiku subagents.** Split the TASKS.md list into batches of about 20 grids
and give each batch to a subagent with `model: haiku`, run in the background, at most 4 at a time. Give each one
this prompt (fill in the paths):
> Open each of these frame-grid images with the Read tool and write the matching `grid_NNN.answer.json` next to it,
> exactly as described in `C:\Travel\work\<Trip>\tagging\TASKS.md` (read it first). Write only answer files; change
> nothing else. Grids: <list of paths>. Reply with the number of files written.

**6.4 Import and check:**
```powershell
magicvideo tags import C:\Travel\work\<Trip>
```
It lists invalid or missing answers; open those grids yourself (Sonnet), rewrite the answers, import again until it
reports 0 invalid, 0 missing. Then spot-check 5 random grids yourself against their answers and report any that are
wrong.

## 5. Report template (send to the owner, who passes it to Claude)

```
Code: git log -1 / git status / stash list
pytest tail
magicvideo doctor
plan v005: printed line, warnings, storyboard header
(after review) render paths, QC verdict, every non-PASS row
Anything odd: moment ids + what you saw
```
