---
name: magicvideo
description: Process a couple travel trip folder into a finished film with the magicvideo CLI. Use when the owner asks to analyse, tag, plan, review, render or check a trip in C:\Travel\raw\<Trip>. magicvideo makes every editing decision; you run it, look at the frame grids it asks you to tag, and report results.
---

# magicvideo + agent runbook

You are the hands and eyes of the pipeline. magicvideo decides the edit. You:
1. run its commands,
2. look at the frame grids it exports and write the scene tags for them (this replaces a paid API),
3. tell the owner exactly what to review and what QC said.

## Paths (Windows)
- Tool: `C:\Travel\magicvideo` · Python: `C:\Travel\magicvideo\.venv\Scripts\python.exe`
- Command: `C:\Travel\magicvideo\.venv\Scripts\magicvideo.exe` (below written as `magicvideo`)
- Raw footage: `C:\Travel\raw\<Trip>` (read-only) · Work folder: `C:\Travel\work\<Trip>`
- Shared partner references: `C:\Travel\people` (one for all trips)

## Rules
1. Run `magicvideo` commands. Never write or edit `plan\*.json`, `plan\timeline_*.json`, `qc\*`, `analysis\*`, or
   anything in `output\`.
2. Raw footage is read-only. Never move, rename, trim or delete source files.
3. To change the edit, the owner uses `magicvideo review`. If they ask you instead, change `overrides.yaml` or
   `policy.yaml`, give a one-line reason for each policy change, then run `magicvideo plan` again.
4. Report the QC verdict exactly as printed. For every check that is not PASS give id, value, limit, detail. Never
   call INCOMPLETE or FAIL a success.
5. Never decide who the partners are. Enrollment folders are the owner's call; you may suggest, they confirm.
6. If a command fails twice the same way, stop and report the command and its last 20 lines. No retry loops.
7. One trip at a time. Don't start the next step while a command is still running.

## Steps for a new trip
```
magicvideo doctor
magicvideo init    C:\Travel\work\<Trip> --source C:\Travel\raw\<Trip> --people C:\Travel\people
magicvideo analyze C:\Travel\work\<Trip>
```
`analyze` is slow on CPU (Whisper). Let it finish.

### Scene tags (you do this)
If analyze prints `tags: N grids waiting`, open `C:\Travel\work\<Trip>\tagging\TASKS.md` and follow it:
- Each `grid_NNN.jpg` is a 3×3 grid of numbered frames. Look at the image.
- Write `grid_NNN.answer.json` next to it: `{"cells": [{"cell": 1, "tags": [...], "people": "...", "interest": 0.0-1.0, "desc": "..."}, ...]}`
  with one entry per numbered cell, tags only from the allowed list in TASKS.md, `people` one of
  none / partners / others / crowd / mixed.
- `partners` = the travelling couple (the people the camera follows or who hold it). `others` = guides, staff,
  performers, strangers in focus. Describe what is visible; never guess names or exact places.
- Work through every grid in TASKS.md, then run:
```
magicvideo tags import C:\Travel\work\<Trip>
```
  Fix any grid it lists as invalid and import again.

### Partners (first trip, or when the owner asks)
If `C:\Travel\people\refs.npz` is missing, or the owner says recognition is wrong:
```
magicvideo enroll C:\Travel\work\<Trip>
magicvideo enroll C:\Travel\work\<Trip> --page
```
The page opens in the browser. Tell the owner: tap A or B on each face group and voice group that is one of them,
Not us on the rest, tap any photo or clip that is someone else to leave it out, then press Finish. Nothing is
deleted. You may compare `person_NNN` photos with `C:\Travel\Couple_References` and suggest which groups are the
couple, but the owner decides. When they say they are done, stop the page (Ctrl+C), pass on the report and any
warning, then run `magicvideo plan` again.

### Plan and review
```
magicvideo plan   C:\Travel\work\<Trip> --thumbs
magicvideo review C:\Travel\work\<Trip>
```
`review` opens the storyboard in the browser. Tell the owner: click keep / drop / "this is us" on cards, then
**Re-plan now**. Wait until they say they are done, then stop the review server (Ctrl+C).
Pass on every plan warning.

### Insta360 clips
If the plan warns that Insta360 clips need exporting, open `C:\Travel\work\<Trip>\plan\x6_exports_vNNN.md` and
tell the owner which files to export from Insta360 Studio. After they confirm, run `magicvideo analyze` and
`magicvideo plan` again. Don't render before that; render will refuse.

### Plan warnings to pass on
- "speech runs to the end/start of the file": the source clip was trimmed too tight; ask the owner to export it
  longer.
- "ignored likely Whisper hallucination": nothing to do; mention it.

### Render and check
```
magicvideo render C:\Travel\work\<Trip>
magicvideo qc     C:\Travel\work\<Trip>
```
Report: output files in `C:\Travel\work\<Trip>\output\`, the `.otio` timeline (import in DaVinci Resolve to add
music), and the QC table per rule 4.

## What to report back
Trip name · clips found · tags grids answered · enrollment status · plan warnings · QC verdict and every non-PASS
check · anything you skipped and why.
