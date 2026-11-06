# Review log — magicvideo Round 6

## Review R01 — 2026-11-06

**Verdict: REVISE (narrow).** Head reviewed: `2b1339b` on `r6/enroll-page` (base `9059ca7`).

### What I ran
- Fresh clone, `PYTHONPATH` pinned. Full suite: **125 passed** (my run). `git status` after the run was clean.
  The brief is byte-identical. `tests/test_review.py` is untouched and passes.
- Read `localserver.py`, `enroll_page.py`, the `enroll.py` diff, `review.py` and `cli.py`.
  - Loopback bind, Host check, 415/400 handling, confined media, atomic state (`write_json`).
  - Neither the page nor finalize-by-assignment deletes or moves anything; the only `rmtree` calls are the
    existing ones in `prepare()`.
- **Browser render pass** (headless Chromium; synthetic candidates with real JPGs and WAVs; 3 face and 3 voice
  groups). The full flow:
  1. typed the names GF/BF, which relabelled the buttons;
  2. assigned person_001 → A, person_002 → B, person_003 → Not us, voice_001 → A, voice_002 + voice_003 → B;
  3. left out one photo and one clip;
  4. the live summary read "GF: … 4 photos … 3 clips ✓ | BF: … 5 photos … 2 voice groups, 3 clips ✓";
  5. pressed Finish → "faces: approved … voice_face_link: set by owner on the enrollment page … next: magicvideo
     plan".

  Results:
  - `refs` `face_a_all` has 4 rows (exclusion honoured) and `voice_b_all` 3 rows (voice_002 + voice_003 minus
    the excluded clip);
  - every review file still exists; `enrollment.yaml` `names` = GF/BF;
  - no page or console errors;
  - desktop and 390 px phone layouts are fine.
- 11 mutations: **9 killed, 2 survived.**

| # | Mutation | Result |
| --- | --- | --- |
| 1 | excluded files still used | killed |
| 2 | assignment ignored | killed |
| 3 | swap heuristic runs after an assignment | **SURVIVED** (synthetic footage can never trigger it) |
| 5a | media serves other suffixes | killed |
| 5b | media leaves the review folder | **SURVIVED** (the traversal test targets a file that doesn't exist) |
| 6 | Host check removed from the base | killed |
| 8 | bind 0.0.0.0 | killed |
| 9 | unknown folder accepted | killed |
| 10 | names not written | killed |
| 11 | minimum ignored in assignment mode | killed |
| 12 | 415 check removed from the base | killed |

### Finding F1
`finalize` skips `_voice_face_swap` only when **both** kinds were finalized by assignment. When one kind succeeds
on the page and the other fails (for example faces pass, voices are short), or only one kind has candidates,
the heuristic still runs. It can then swap the owner's explicit A/B voice choice against older references.
An owner's explicit assignment must never be swapped.

### Rulings
- **R01-1** (production + test). In `finalize`, skip `_voice_face_swap` whenever **any** kind was finalized from
  `assignment` (`assigned_done` non-empty). Set `voice_face_link`:
  - both kinds → `"set by owner on the enrollment page"` (unchanged);
  - one kind → `"set by owner for <kind>s on the enrollment page; <other kind>s kept from before (not
    cross-checked)"`, where `<kind>` is `face` or `voice`.

  Test `tests/test_enroll_page.py::test_owner_assignment_never_swapped`: monkeypatch `enroll._voice_face_swap`
  with a spy that returns True.
  - (a) Finalize with both kinds assigned → the spy is not called.
  - (b) First finalize faces and voices once by assignment. Then finalize again with only `voice` in the
    assignment → the spy is not called, the one-kind link text is as above, and `voice_a` is still the voice A
    embedding.
- **R01-2** (test only). `tests/test_enroll_page.py::test_media_cannot_leave_review_folder`:
  - create a real `secret.jpg` in `people_dir`;
  - request `/media/face/..%2F..%2F..%2Fsecret.jpg` (percent-encoded so the client does not normalise it; the
    server unquotes) and the same with `/media/voice/` → 404 both.

### Rulings on parked items
- **P1, P3, P4, P5, P6, P7:** ACCEPT.
- **P2** (thumbnails restricted to image suffixes): ACCEPT. It is a tightening, and only images are written there.

### Expected count and evidence for R02
**127 collected, 127 passed**, a prediction.

Evidence required:
- `test(R01-1)` then `fix(R01-1)`; `test(R01-2)`;
- the full suite run once;
- `git log --oneline 2b1339b..HEAD` and `git status --short`.

Append `## Coder response R01` to `docs/R6_HANDOVER.md`.

## Review R02 — 2026-11-06

**Verdict: APPROVE.** Head reviewed: `f88484a` (`f88484a2aa1459f234ff0b5a1fcacf5512adebf6`).

### What I ran
- Fresh clone. Full suite: **127 passed** (my run). `git status` after the run was clean. R01 of this log is
  unchanged.
- The production diff since R01 is `finalize`'s swap block only: the heuristic is skipped whenever
  `assigned_done` is non-empty, with the one-kind and both-kinds link texts as ruled.
- Mutations on the new code:
  - swap runs after an assignment → killed (test_finalize_by_assignment_deletes_nothing);
  - swap skipped only when both kinds are assigned (the pre-fix behaviour) → killed
    (test_owner_assignment_never_swapped);
  - media leaves the review folder → killed (test_media_cannot_leave_review_folder).
- Browser render pass repeated on the new head: same flow and same results, the review files kept, no errors.
- Integrity:
  - no NUL bytes or BOMs;
  - `IMPLEMENTATION_BRIEF.md` has 10 lines added and 0 deleted;
  - `tests/test_review.py` and the R5 docs are untouched.

### Authorisation
The branch `r6/enroll-page` at `f88484a` is approved to fast-forward `claude/vibrant-brahmagupta-yr5pu4`
(currently `9059ca7`) on the owner's PC, and to be pushed to origin.

After the merge, copy `agent/SKILL.md` to `C:\Travel\.agents\skills\magicvideo\SKILL.md` and
`C:\Travel\skills\magicvideo\SKILL.md`. Its Partners section now uses the page.

Markers:
- **contains:** `def make_loopback_server` in `magicvideo/localserver.py`; `def render_page` in
  `magicvideo/enroll_page.py`; `assignment: dict | None = None` in `magicvideo/enroll.py`; `page_port: 8766`
  in `magicvideo/default_policy.yaml`; `--page` in `agent/SKILL.md`.
- **absent:** `unlink`, `rmtree` and `os.remove` in `magicvideo/enroll_page.py` and
  `magicvideo/localserver.py`.
