# Relay: resume magicvideo on the owner's PC (new AI worker replacing Antigravity)

You are the new **operator** on the owner's Windows PC. The previous operator (Antigravity) ran out of tokens
mid-trip. Code changes are made by Claude Code in a separate session; you run the tool, look at images when asked,
and report. Read this file fully, then do section 3 in order.

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
**CHECK:** `git log --oneline -1` shows `ff0ac3d` (or newer); pytest ends `137 passed, 1 skipped` (or more passed,
0 failed). If tests fail: STOP, report the full tail. Do not edit code to make them pass.

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

## 5. Report template (send to the owner, who passes it to Claude)

```
Code: git log -1 / git status / stash list
pytest tail
magicvideo doctor
plan v005: printed line, warnings, storyboard header
(after review) render paths, QC verdict, every non-PASS row
Anything odd: moment ids + what you saw
```
