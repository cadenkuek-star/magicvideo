# R7 handover (Claude → Antigravity)

Branch `claude/vibrant-brahmagupta-yr5pu4`, on top of `0e048df` (R6 approved). Written from the owner's feedback
after three trips; implemented and tested here (Linux), not yet run on the owner's PC.

## Before you pull: your local edits

On the owner's PC you changed `default_policy.yaml`, `moments.py` ("partner span rules", "+0.15 bonus",
"clip-edge extension"), `assemble.py` (CoverPool and dropped cutaways) and the Pakistan `policy.yaml`, and none
of that was pushed. Do this first, verbatim:

```powershell
cd C:\Travel\magicvideo
git status --short
git stash push -u -m "local-before-r7"      # keeps your edits safe; nothing is lost
git pull
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

Then compare: `git stash show -p stash@{0} > C:\Travel\work\local_before_r7.diff` and read it. Everything the
owner asked for is now in the code with policy keys (below), so **do not re-apply your `moments.py` or
`default_policy.yaml` edits**. Re-apply only what is not covered, on a new branch, with a test, per CLAUDE.md.
Trip `policy.yaml` files are not in git; the Pakistan one keeps whatever values it has.

## What changed (brief §15 has the contract)

| Owner feedback | Now |
|---|---|
| 58 retake groups / 82 duplicates had to be found by a separate script and dropped by hand | `plan/retakes.py`: the planner groups takes of the same line (transcript similarity, or picture for wordless takes), keeps the best take, leaves the others out with reason `retake: best take is …`. `keep` rescues any. Storyboard badges `★ best of rtNNN` / `retake rtNNN`; header shows the counts. Policy block `retakes:`. |
| "keep 2 s of couple / bf / gf instead of trimming" | `coverage.partner_shot_min_s: 2.0`, `coverage.partner_visible_bonus: 0.15`; defaults now `silent_solo_shot_max_s` 4.0 for both, `pre_roll_s` 1.5, `post_roll_s` 2.0, `action.pre_s` 2.0 (your accepted Pakistan values). |
| flipped landscape clips got through | new analysis step `orient` (uses the face backend): `analysis/<clip>/orient.json`, automatic extra rotation, badge `rotated:<deg>`; an owner `clips.<id>.rotate` override always wins. |
| portrait clips dropped by hand | `reframe.portrait_in_landscape: auto | static_bg | crop | drop`. `drop` leaves portrait B-roll out automatically; conversations are kept and badged `portrait`. |

Tests: 133 pass here (`pytest -q`), including the end-to-end render.

## Steps on the PC

1. The pull/pytest block above. Report the pytest tail.
2. Existing trips need the new analysis step once (faces backend must be installed):
   ```powershell
   magicvideo analyze C:\Travel\work\Pakistan_2024 --steps orient
   ```
   Report how many clips got `rotate` ≠ 0 (`Select-String '"rotate": [1-9]' C:\Travel\work\Pakistan_2024\analysis\*\orient.json`).
3. If the owner wants portrait B-roll out of the Pakistan film (they dropped it by hand last time), set
   `reframe.portrait_in_landscape: drop` in `C:\Travel\work\Pakistan_2024\policy.yaml` (one-line reason: owner
   request, Pakistan review), then:
   ```powershell
   magicvideo plan C:\Travel\work\Pakistan_2024 --thumbs
   ```
   Report the header line of the storyboard (retake groups, takes left out, flagged counts) and the plan
   warnings. The owner's `overrides.yaml` from v003 still applies; moments they dropped stay dropped.
4. Owner reviews in `magicvideo review`; render and QC as before.

## What to watch for (report, don't fix)

- Retake grouping too eager (two different lines grouped) or too shy (obvious retakes not grouped): report the
  group id, the two moment ids and their transcript text. The knobs are `retakes.text_similarity_min` and
  `retakes.window_s`; the owner decides.
- `orient` rotating an upright clip: report the clip and its `orient.json` scores. Knobs: `orientation.min_ratio`,
  `orientation.min_faces`.

## Round 8 (after the owner's v004 review)

Pull again (`git pull`, `pip install -e ".[dev]"`, `pytest -q`: expect 137 passed, 1 skipped), then
`magicvideo plan C:\Travel\work\Pakistan_2024 --thumbs` and report the new header line. Brief §16 has the rules:
at most 2 B-roll shots per clip per event, similar shots cut to 3 s, `drop` now leaves portrait conversations out
too (keep rescues), the `rt002`-type false retake no longer groups, thumbnails show rotated clips upright.
Delete `C:\Travel\work\Pakistan_2024\plan\thumbs\` first so old flipped thumbnails are not reused.
