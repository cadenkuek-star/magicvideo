# Relay for Coder A — magicvideo Round 2

Paste this whole file to the coder. It is self-contained.

## Your role
You are the implementer. Do **not** load any skill. Build exactly what `docs/R2_BRIEF.md` says; make no design
decisions. If the brief is unclear or wrong, stop that item, write it under "Parked" in the handover, and carry on
with the next item.

## Repo
- Folder: `C:\Travel\magicvideo` · Python: `C:\Travel\magicvideo\.venv\Scripts\python.exe` (3.11.9)
- Base: branch `claude/vibrant-brahmagupta-yr5pu4` at commit **`1e0dded`**. Confirm with `git rev-parse HEAD`.
- Create the work branch: `git switch -c r2/identity-review`
- Tests: `.venv\Scripts\python.exe -m pytest` (synthetic ffmpeg footage; ~1 min)
- Baseline: 37 collected, 36 passed, 1 failed (`test_e2e.py::test_plan_render_qc`, fixed by W1).

## Step 0
The spec designer has placed these untracked files: `docs/R2_BRIEF.md`, `docs/R2_RELAY.md`,
`docs/R2_SKILL_magicvideo.md`. Commit them unchanged as the first commit:
`git add docs/R2_BRIEF.md docs/R2_RELAY.md docs/R2_SKILL_magicvideo.md` → `git commit -m "R2: brief, relay, agent skill"`.

## Work table (in order; brief section in brackets)
| # | Item | Done means |
| --- | --- | --- |
| 1 | W1 pin e2e test to no ASR [§4 W1] | test passes with faster-whisper installed; `refs_sha256` assertion added |
| 2 | W2 tags without key → BackendMissing [W2] | new test passes; analyze with provider anthropic and no key records SKIPPED, no crash |
| 3 | W3 file-name times with prefix [W3] | 4 parametrized cases pass |
| 4 | W4 couple prior [W4] | 5 tests pass; policy keys in `default_policy.yaml`; storyboard line shows evidence |
| 5 | W5 enrollment merge / sparse / errors / multi-ref [W5] | 5 tests pass; `enroll --help` shows `--merge` and `--allow-sparse` |
| 6 | W6 stale refs [W6] | test passes; plan JSON has `refs_sha256` |
| 7 | W7 review server + `couple` override + storyboard [W7] | 9 tests pass; `magicvideo review --help` works |
| 8 | W8 agent tagging export/import [W8] | 5 tests pass; `cloud.provider: agent` is the default |
| 9 | W9 skill copies [W9] | three SKILL.md files byte-identical (hash in handover) |
| 10 | W10 contract update [W10] | `IMPLEMENTATION_BRIEF.md` has `## 10. Round 2 changes`, 0 deleted lines |

## Test rules
- Test first: commit each item's tests **before** its fix (`test(Wn): …`, then `fix(Wn): …` / `feat(Wn): …`), so the
  reviewer can check the test fails without the fix.
- While working, run only the test file you are changing. Run the **full suite once**, at the end.
- Do not fold, delete, skip or rename existing tests to reach a count. Expected count: 67 collected, 67 passed
  (a prediction; if yours differs, explain with `pytest --collect-only -q`).
- Tests use synthetic data only. No real footage, no files from `C:\Travel\raw`, `C:\Travel\work`, `C:\Travel\people`.

## Working rules
- No retry loops: if a command fails twice the same way, stop and write it up.
- Stop anything that prints nothing for 5 minutes.
- No browser, no screenshots, no live API calls. Do not run `magicvideo review` against a real trip (tests start
  the server on port 0 themselves).
- Do not install, upgrade or remove packages; do not change the venv or PATH. If something is missing, park it.
- Do not edit `docs/R2_BRIEF.md`, `docs/R2_RELAY.md`, `docs/R2_SKILL_magicvideo.md` or `C:\Travel\PROJECT.md`.
- The only files you write outside the repo are the two SKILL.md copies in W9.
- Follow `CLAUDE.md` (policy keys for every threshold, deterministic planner, lazy optional imports, Windows paths).
- Do not merge and do not push.

## Self-check (paste every output into the handover)
```
git log --oneline 1e0dded..HEAD
git status --short
git diff --stat 1e0dded..HEAD
git diff 1e0dded..HEAD --numstat -- docs/IMPLEMENTATION_BRIEF.md
git grep -n "0.0.0.0" -- magicvideo
git grep -n "_RE = re.compile" -- magicvideo/ingest.py
.venv\Scripts\python.exe -m pytest -q
certutil -hashfile agent\SKILL.md SHA256
certutil -hashfile C:\Travel\.agents\skills\magicvideo\SKILL.md SHA256
certutil -hashfile C:\Travel\skills\magicvideo\SKILL.md SHA256
```
Expected: `0.0.0.0` grep empty; no regex starts with `r"^`; `IMPLEMENTATION_BRIEF.md` numstat shows 0 deletions; `git status` clean; three
equal hashes.

## Handover
Write `docs/R2_HANDOVER.md` and commit it last:
1. Per work item: commits (test commit, fix commit), files touched, one line on what changed.
2. Full-suite result (the one run), with the count.
3. Self-check outputs, verbatim.
4. Parked items: what, why, what you need.
5. What I did NOT verify.
