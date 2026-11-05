---
name: magicvideo
description: Runbook for producing a couple travel film with the magicvideo CLI. Use when asked to analyse, plan, render or check a trip's footage. The CLI makes every editing decision; the agent runs it and reports results.
---

# magicvideo runbook

## Rules

1. Run `magicvideo` commands. Never write or edit `plan/*.json`, `plan/timeline_*.json`, `qc/*`, or anything in `output/`.
2. To change the edit, change `overrides.yaml` (per moment, event or clip) or `policy.yaml` (thresholds), then run `magicvideo plan` again. Give a one-line reason for every policy change.
3. Report the QC verdict exactly as printed. For every check that isn't PASS, give its id, value, limit and detail. Never describe INCOMPLETE or FAIL as success.
4. Raw footage is read-only. Don't move, rename or delete source files.

## Steps

```
magicvideo doctor
magicvideo init    <work> --source <raw trip folder> --people <shared people folder>
magicvideo analyze <work>
magicvideo enroll  <work>            # first trip only; the owner deletes non-partner folders
magicvideo enroll  <work> --finalize
magicvideo plan    <work> --thumbs
magicvideo render  <work>
magicvideo qc      <work>
```

After `plan`, point the owner to `plan/storyboard_vNNN.html` and the plan warnings. After `render`, point them to `output/` and the `.otio` timeline (import it in DaVinci Resolve to add music).
