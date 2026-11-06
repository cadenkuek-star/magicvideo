# R6 handover (Coder A)

Branch `r6/enroll-page` from `9059ca7`. Nothing pushed or merged.

## 1. Work items

| Item | Test commit | Feature commit | Files | What changed |
| --- | --- | --- | --- | --- |
| Step 0 | - | `8ca86ec` | `docs/R6_BRIEF.md` | Brief unchanged. |
| W1 | (existing `tests/test_review.py`, untouched, 10 passed before and after) | `15bec21` | `localserver.py` (new), `review.py` | `BaseHandler`, `_read_json_body`, `serve_file`, `make_loopback_server`; review uses them. |
| W2 | `4ec7c27` | `815e81b` | `enroll.py`, `tests/test_enroll.py` | `finalize(..., assignment, excluded, names)`; `_assigned_slots`; swap heuristic skipped and `voice_face_link` set when both kinds are assigned; names in `enrollment.yaml`. |
| W3 | `fefbede` | `331244d` | `enroll_page.py` (new), `cli.py`, `enroll.py` (`REVIEW_TEXT`), `default_policy.yaml`, `tests/test_enroll_page.py` | Page, routes, state file `people/review_<trip>.json`, `--page/--port/--no-open`, `enrollment.page_port`, `next:` line after prepare. |
| W4 | - | `2a498af` | `agent/SKILL.md` | "Partners" section replaced with the brief's text. |
| W5 | - | `f59d504` | `docs/IMPLEMENTATION_BRIEF.md` | Section 14 appended. |

## 2. Full suite (run once, at the end)

```
125 passed in 34.26s
125 tests collected in 1.16s
```
Matches the prediction (125 / 125).

## 3. Self-checks (verbatim; before this file was committed)

```
$ git log --oneline 9059ca7..HEAD
f59d504 docs(W5): contract section 14 (append only)
2a498af feat(W4): agent skill uses the enrollment page
331244d feat(W3): clickable enrollment page (magicvideo enroll --page), state file, page_port, REVIEW_TEXT
fefbede test(W3): enrollment page routes, state, media, finalize by assignment
815e81b feat(W2): finalize by assignment (slots as assigned, exclusions, no swap heuristic, names)
4ec7c27 test(W2): finalize without assignment is unchanged
15bec21 feat(W1): shared local-server base (localserver.py); review.py uses it, behaviour unchanged
8ca86ec R6: brief

$ git status --short

$ git diff --numstat 9059ca7..HEAD -- docs/IMPLEMENTATION_BRIEF.md agent/SKILL.md tests/test_review.py
6	8	agent/SKILL.md
10	0	docs/IMPLEMENTATION_BRIEF.md

$ git grep -n "0.0.0.0\|unlink\|rmtree\|os.remove" -- magicvideo/enroll_page.py magicvideo/localserver.py

$ git grep -n "unlink\|rmtree\|os.remove" -- magicvideo/enroll.py
magicvideo/enroll.py:141:        shutil.rmtree(paths["face_review"], ignore_errors=True)
magicvideo/enroll.py:185:        shutil.rmtree(paths["voice_review"], ignore_errors=True)
```
`tests/test_review.py` does not appear in the numstat. `agent/SKILL.md` shows 6 added / 8 deleted lines: the brief asks to replace the whole Partners section. The `rmtree` hits in `enroll.py` are the existing `prepare()` rebuild of the review folders (as today); neither `finalize` nor the page deletes anything.

## 4. Parked

1. `_read_json_body` returns `None` after sending the error response (the brief says `-> dict`); callers `return` on None.
2. `serve_file` in review now also restricts thumbnails to image suffixes (`.jpg .jpeg .png .gif .webp`); before, any file under `plan/thumbs/` was served. Existing tests pass.
3. W2 zero-file report: the report key is `faces`/`voices` and the value `partner_<slot> has no <unit> assigned` (printed as `voices: partner_a has no clips assigned`). Under-minimum slots in assignment mode say `partner_x has N <unit>, below the minimum M: add more groups, or accept it with --allow-sparse`.
4. W2 test commit holds only `test_finalize_without_assignment_unchanged` (as the brief says); it passes already, since it guards existing behaviour. The assignment tests are the page tests in W3.
5. W3: `/api/finalize` sends `names` only when at least one is non-empty. When a kind has no candidates it is left out of the assignment (falls back to the deletion path for that kind).
6. W3: the state keeps `assign` only for candidates and drops excluded keys that no longer exist. Excluded files are removed from slot counts in the summary.
7. W3: the page is server-rendered (cards) so `GET /` lists every group and its `<img>`/`<audio>` tags; the script wires clicks and refreshes highlight and summary from `/api/state`.
8. `serve` for the review server is untouched apart from using the base.

## 5. What I did NOT verify

- The page in a browser (none allowed): only `node --check` on the script and HTTP-level tests.
- Behaviour on a real `prepare()` output with hundreds of photos or on the owner's footage.
- The mutation list in brief section 6 was not run (reviewer's job).

## Coder response R01

Review `docs/R6_REVIEW.md` committed unchanged first (`055c5a5`). Same branch; nothing pushed or merged.

| Ruling | Test commit | Fix commit | What changed |
| --- | --- | --- | --- |
| R01-1 | `2f22255` | `ea00fa0` | `finalize` skips `_voice_face_swap` whenever any kind was finalized from `assignment`; link text is the both-kinds text, or `set by owner for <kind>s on the enrollment page; <other kind>s kept from before (not cross-checked)`. `test_owner_assignment_never_swapped` failed against the old code (part b), passes now. |
| R01-2 | `264fa90` | none (test only) | `test_media_cannot_leave_review_folder`; it passed against the current code, no production change. |

Full suite (run once, at the end): `127 passed in 35.70s`; `pytest --collect-only -q`: `127 tests collected` (matches the prediction).

```
$ git status --short
(clean, taken before this section was committed)
$ git log --oneline 2b1339b..HEAD   (before the handover commit)
ea00fa0 fix(R01-1): never run the swap heuristic after an owner assignment of either kind
264fa90 test(R01-2): media cannot leave the review folder
2f22255 test(R01-1): an owner's assignment is never swapped
055c5a5 docs: R6 review R01
```

Parked: none. Note: the R01-2 test commit came before the R01-1 fix commit (both tests precede the fix); part (b) of the R01-1 test calls `enroll.finalize` directly because the page's finalize always sends every kind that has candidates.
