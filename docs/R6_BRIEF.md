# magicvideo — Round 6 brief: clickable enrollment page (nothing deleted)

Status: owner asked for it on 2026-11-06 ("build that clickable page for enrollment"). Author: spec designer
(Claude). Base: `claude/vibrant-brahmagupta-yr5pu4` @ `9059ca7` (Round 5 merged). Branch: `r6/enroll-page`.
CLAUDE.md applies. Contract changes are appended to `docs/IMPLEMENTATION_BRIEF.md` (W5).

## 1. Why
- Enrollment today is deletion-only: the owner deletes wrong folders and files in Explorer, then types
  `--finalize`, `--merge`, `--allow-sparse`.
- The owner finds hand-editing troublesome (R1 feedback), and is wary of anything deleting files in C:\Travel
  (2026-11-06).
- The voice references are weak because they came from a single clip; re-enrolling on a multi-camera trip is
  the fix, so enrollment must be easy.
- The page replaces deleting with clicking. Candidate files are never deleted or moved.

## 2. Scope
In: W1–W5. The deletion-based `--finalize` path stays working, unchanged.
Out: re-clustering from the page, editing clusters, moving files between folders.

## 3. Work items

### W1 — Shared local-server base (refactor, no behaviour change)
- New `magicvideo/localserver.py` with the request plumbing from `review.py`:
  - a `BaseHandler(BaseHTTPRequestHandler)` with `log_message` silenced;
  - `_send`, `_json`, `_error`;
  - `_host_ok` (127.0.0.1:<port> / localhost:<port>);
  - `_read_json_body() -> dict` (415 unless `Content-Type: application/json`; 400 for bad JSON, a non-dict body,
    or a body above 1 MiB);
  - `serve_file(base: Path, rel: str, allowed_suffixes: set[str])` (resolve, `is_relative_to(base)`, is_file,
    suffix allowed, else 404; MIME from `mimetypes`);
  - `make_loopback_server(handler_cls, port) -> ThreadingHTTPServer` bound to `127.0.0.1`.
- `review.py` uses it. Its routes, responses and existing tests stay unchanged. All `tests/test_review.py` must
  pass untouched.

### W2 — Enrollment by assignment in `enroll.finalize`
- Signature:
  `finalize(project, merges=(), allow_sparse=False, assignment: dict | None = None, excluded: set[str] | None = None)`.
  - `assignment` = `{"face": {"a": [folders], "b": [folders]}, "voice": {"a": [...], "b": [...]}}`. A kind may be
    missing.
  - `excluded` = a set of `"<kind>/<folder>/<file>"` keys.
- For a kind present in `assignment`:
  - Slot `a` takes all files of its folders, and slot `b` likewise, read from the review dir in sorted order,
    minus `excluded`.
  - Folders not assigned are ignored. Nothing is deleted.
  - `merges` are ignored for that kind.
  - The minimum and sparse rules, the multi-reference `*_all`, the approved copies, the diversity warning and
    the report lines are the same as today.
  - The slots are exactly as assigned: no name sorting.
  - A slot with zero files gives the report line `"<kind>s: partner_<slot> has no <unit> assigned"`, and that
    kind is not written.
- When both `face` and `voice` were finalized from `assignment`, skip `_voice_face_swap`, and set
  `voice_face_link` = `"set by owner on the enrollment page"`. The owner put each face and voice under the same
  partner.
- With `assignment=None`, behaviour is identical to today.
- Optional `names: {"a": str, "b": str}` (each ≤ 40 chars): when given, they are written to `enrollment.yaml` as
  `names`. Display only.

### W3 — The page: `magicvideo enroll <work> --page`
New module `magicvideo/enroll_page.py`, standard library plus the W1 base.

- **State file:** `people/review_<trip>.json` = `{"assign": {"face": {folder: "a"|"b"|"none"}, "voice": {...}},
  "excluded": [keys], "names": {"a": "", "b": ""}}`. Written atomically (temp + `os.replace`) after every change,
  so the owner can close and come back. Default for every folder: `"none"`.
- **Candidates:** the folders and files present in `faces/review/<trip>/person_*` (`.jpg`) and
  `voices/review/<trip>/voice_*` (`.wav`), sorted, that also appear in that kind's `manifest.json`.
- **Routes** (all with the Host check):
  - `GET /` → the page;
  - `GET /media/face/<folder>/<file>` and `/media/voice/<folder>/<file>` → `serve_file` with `.jpg`/`.wav` only;
  - `GET /api/state` → `{"state", "candidates": {"face": {folder: [files]}, "voice": {...}}, "summary"}`.
    `summary` per slot: number of face groups and kept photos, voice groups and kept clips, plus the minimums
    from policy;
  - `POST /api/assign` `{"kind": "face"|"voice", "folder", "slot": "a"|"b"|"none"}`;
  - `POST /api/exclude` `{"kind", "folder", "file", "excluded": bool}`;
  - `POST /api/names` `{"a", "b"}` (strings, ≤ 40 chars each, stripped);
  - `POST /api/finalize` `{"allow_sparse": bool}` → calls `finalize(project, allow_sparse=…, assignment=…,
    excluded=…, names=…)` built from the state. Returns `{"ok": true, "report": {...}, "next": "magicvideo plan
    \"<work>\""}`.
  - Unknown kind, folder, file or slot → 400. Every POST except finalize returns the new state and summary.
- **Page** (one self-contained HTML string, no external resources, light/dark via `prefers-color-scheme`):
  1. A header in plain words: "Who are the two of you? Tap A or B on each group that is one of you, and Not us
     on the others. Tap a photo or clip to leave it out if it's someone else. Then press Finish."
  2. Two name boxes, "Partner A name" and "Partner B name". Once filled, they label the buttons.
  3. Faces: one card per `person_NNN`, showing its photos as thumbnails (`<img loading=lazy>`). A tapped photo
     greys out with an ✕ (excluded). Three buttons: [A] [B] [Not us]; the current choice is highlighted.
  4. Voices: one card per `voice_NNN`, showing each clip as `<audio controls preload=none>` with the words from
     its file name and a "leave out" toggle, plus the same three buttons.
  5. A fixed bottom bar showing the live summary, e.g. "A: 1 face group, 10 photos · 2 voice groups, 7 clips ✓
     | B: … 2 clips (needs 3)", a checkbox "Accept fewer clips than usual", and a **Finish** button. After
     Finish, the report lines appear, with the next command to run.
- **CLI:** `magicvideo enroll <work> --page [--port N] [--no-open]`.
  - Policy `enrollment.page_port: 8766`.
  - If no candidate folders exist, `ProjectError("no candidates yet: run magicvideo enroll \"<work>\" first")`.
  - Prints the URL; Ctrl+C stops.
  - `magicvideo enroll <work>` (prepare) now ends with `next: magicvideo enroll "<work>" --page`.
- **`REVIEW_TEXT`:** lead with the page command. Keep the delete-folders route as "Alternative" below it.

### W4 — Agent skill
In `agent/SKILL.md`, replace the whole "### Partners (first trip, or when the owner asks)" section, from its
heading up to (not including) "### Plan and review", with exactly the text between the `~~~~` lines (it contains its own ``` code block):

~~~~
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
~~~~

### W5 — Contract
Append `## 14. Round 6 changes` to `docs/IMPLEMENTATION_BRIEF.md`: the localserver base, `finalize` by
assignment, the page routes and state file, `enrollment.page_port`. Append only.

## 4. Tests (new `tests/test_enroll_page.py`; synthetic review folders and manifests as in `tests/test_enroll.py`; server on port 0 in a thread; `urllib.request`)
1. `test_page_lists_candidates`: `GET /` contains each `person_NNN` and `voice_NNN`, `<img` and `<audio` tags.
2. `test_assign_and_exclude_saved_to_state`: POST assign and exclude; the state file holds both, and survives a new
   server instance.
3. `test_unknown_folder_file_or_slot_rejected` (three 400s).
4. `test_media_confined`: a traversal path → 404; a `.json` under media → 404; a valid jpg → 200.
5. `test_foreign_host_rejected` (403).
6. `test_finalize_by_assignment_deletes_nothing`:
   - setup: voice_001 → a, voice_002 + voice_003 → b, one excluded file, faces person_001 → a, person_002 → b;
   - after finalize: every review file still exists;
   - `refs` `voice_b_all` has the rows of voice_002 + voice_003 minus the excluded file;
   - `voice_face_link == "set by owner on the enrollment page"`.
7. `test_finalize_reports_shortfall_then_sparse`: B has 2 voice clips (minimum 3). Without `allow_sparse` the
   report names the shortfall; with it, approved with a sparse note.
8. `test_names_written_to_enrollment`: names A/B → `enrollment.yaml` `names`.

Also in `tests/test_enroll.py`:
- `test_finalize_without_assignment_unchanged` asserts the deletion path still behaves as before. Re-use an
  existing scenario: two folders → approved, swap heuristic consulted.

## 5. Must get right
1. **Nothing in the people folder is ever deleted or moved by the page or by finalize-by-assignment.**
2. Loopback only, with the Host check, through the shared base. `review.py` behaviour is unchanged (its tests
   pass untouched).
3. The state survives restarts and is never half-written.
4. Face slot A and voice slot A are the same person, by the owner's assignment; no swap heuristic overrides it.
5. Media serving is confined to the review folders and the two allowed suffixes.

## 6. Mutation intent
1. Excluded files still used in the refs.
2. The assignment ignored (falls back to sorted names).
3. The swap heuristic still runs after an assignment.
4. finalize deletes or moves review files.
5. The media route serves other suffixes or leaves the folder.
6. The Host check missing in the shared base.
7. The state written non-atomically.

## 7. Expected count (prediction)
Baseline 116. New: 8 page tests + 1 enroll test = 9. **125 collected, 125 passed.**

## 8. Owner acceptance
On Test_Trip_R2 (more cameras than the first enrollment):
1. `magicvideo enroll C:\Travel\work\Test_Trip_R2`
2. `magicvideo enroll C:\Travel\work\Test_Trip_R2 --page`: tap the groups, Finish.
3. `magicvideo plan C:\Travel\work\Test_Trip_R2 --thumbs`
4. Expect the storyboard cards' "voice match" figures to rise above the old ~0.4–0.5 on clips other than
   Kanazawa.

## 9. Assumptions (dated 2026-11-06)
- **A1:** Partners are labelled A/B with optional names. Names are for display only.
- **A2:** Candidates are reviewed as `prepare()` made them. To get different groups, the owner re-runs
  `magicvideo enroll`, which rebuilds the review folders as today.

## 10. Not verified
- The page on the owner's browser. The reviewer runs a headless-browser render pass on synthetic candidates
  before approving.
