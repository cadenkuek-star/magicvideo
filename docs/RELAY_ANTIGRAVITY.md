# Relay: install and run magicvideo on Windows

**For:** Antigravity (installer and operator on the owner's Windows PC)
**From:** Claude Code (author of build 1)
**Repo:** https://github.com/cadenkuek-star/magicvideo (public)
**Code:** pull request #1, branch `claude/vibrant-brahmagupta-yr5pu4` (use `main` once #1 is merged)
**Contract:** `docs/IMPLEMENTATION_BRIEF.md`. Design: `docs/PROPOSAL.md`. Operator runbook: `agent/SKILL.md`. Coding rules: `CLAUDE.md`.

## State at handover

| Item | State |
|---|---|
| Pipeline code (ingest, analysis, enrollment, planner, render, QC, CLI) | Written; 35 tests pass on **Linux** |
| Windows | **Never run on Windows.** Step 4 (`pytest`) is the first Windows check. |
| Model backends (faster-whisper, speechbrain, insightface, Anthropic API) | Code written, **never run with real models** |
| Real camera files (Insta360 X6, DJI Osmo Nano, DJI Osmo Pocket 4P) | **Never seen.** Step 8 is the first real run. |
| Old v2 skills (`travel-footage-analyzer`, `travel-video-master-editor`, `couple-travel-documentary-editor`) | To be retired (step 7) |

---

## 0. Rules for Antigravity

1. **Work in order.** Every step ends with a **CHECK**. If a CHECK fails, stop and report the full output. Don't continue on a guess.
2. **At every STOP, ask the owner and wait.** These are things only the owner can do or decide.
3. **Report output verbatim.** Never describe a failure, `FAIL` or `INCOMPLETE` as success.
4. **Don't change pipeline behaviour.** Never edit planner, render or QC code, `magicvideo/default_policy.yaml`, or a trip's `policy.yaml` thresholds to make something pass.
   - You *may* fix the environment (installs, PATH, drivers).
   - You may fix a clearly Windows-only bug (path, encoding, quoting) only if all of these hold: a failing `pytest` reproduces it, the fix goes on a new branch, `pytest` passes afterwards, and you follow `CLAUDE.md`.
5. **Never modify raw footage.** Don't move, rename or delete source videos or old v2 outputs.
6. **Never write the Anthropic API key** into any file, log, commit or chat message. The owner sets it.
7. **Only the owner decides who the two partners are** during enrollment.
8. **Keep the v2 skills off these trips.** Never run them on a trip that magicvideo is processing.

## 1. Target layout

```
C:\Travel\magicvideo\          code (this repo)
C:\Travel\raw\<Trip>\          raw footage per trip (read-only)
C:\Travel\work\<Trip>\         magicvideo work folder per trip (created by `init`)
C:\Travel\people\              shared face/voice enrollment (reused for every trip)
```

Existing v2 folders (`C:\Travel\output\...`, `C:\Travel\Couple_References\...`) stay exactly as they are.

## 2. System tools (check first; install only what is missing)

Use PowerShell (a normal user window is fine; `winget` asks for elevation when it needs it).

### 2a. Git and ffmpeg

```powershell
git --version
ffmpeg -hide_banner -filters | Select-String -Pattern " v360 | vidstabdetect | loudnorm | alimiter | sendcmd "
```

- If `git` is missing: `winget install --id Git.Git -e`
- If `ffmpeg` is missing, or any of the five filters is not listed: `winget install --id Gyan.FFmpeg -e`. That is the **full** build, which magicvideo needs for vidstab and v360; the "essentials" build won't do. If an older ffmpeg comes first on PATH (`where.exe ffmpeg`), fix the PATH order.

### 2b. Python: use what is installed when it works

magicvideo itself runs on Python 3.10 or newer. What decides the version is whether **every dependency has a ready-made Windows wheel** for it; otherwise pip tries to compile C++/Rust code and fails.

Status checked on PyPI on 2026-11-05:

| Python | Usable? | Why |
|---|---|---|
| 3.15 | No | no Windows wheels yet for pyyaml, opentimelineio, onnxruntime, torchaudio, pydantic-core |
| 3.14 | No | no Windows wheels yet for opentimelineio (the Resolve timeline export) and pydantic-core (used by the Anthropic SDK) |
| **3.13** | **Yes, recommended** | newest version with every wheel; security fixes until Oct 2029 |
| 3.12 | Yes | |
| 3.10, 3.11 | Yes | slightly older numpy/scipy; 3.11 security fixes end Oct 2027 |

Don't take the table on trust; it changes as packages release. Run this check **on the Windows PC itself**: pip only evaluates Windows-specific requirements correctly when it runs on Windows. It asks pip to resolve every dependency using wheels only, installs nothing, and prints the newest installed version that passes:

```powershell
py -0p
$deps = "numpy pyyaml opencv-python opentimelineio torch torchaudio faster-whisper speechbrain insightface onnxruntime anthropic".Split(" ")
$PY = $null
foreach ($v in "3.15","3.14","3.13","3.12","3.11","3.10") {
  py -$v -c "pass" 2>$null; if ($LASTEXITCODE -ne 0) { continue }
  py -$v -m pip install --dry-run --quiet --only-binary=:all: @deps 2>$null
  if ($LASTEXITCODE -eq 0) { $PY = $v; "USE Python $v"; break } else { "skip Python $v (a dependency has no Windows wheel yet)" }
}
```

Then:

- If any version passed, **use `$PY`**, the newest installed version that passed. Don't install another Python. An installed 3.10 or 3.11 is fine; moving to 3.13 later is optional (3.11 stops getting security fixes in Oct 2027).
- Only if **nothing** passed: run `winget install --id Python.Python.3.13 -e`, open a new terminal and run the check again. It should print `USE Python 3.13`.
- **Never uninstall other Python versions.** They live side by side under the `py` launcher.

**CHECK:** the check printed `USE Python <version>`, and `$PY` holds it. Report the full output, including `py -0p`. Every later step uses `py -$PY`; if you open a new terminal, set `$PY` again (for example `$PY = "3.13"`).

## 3. Get the code

```powershell
git clone https://github.com/cadenkuek-star/magicvideo C:\Travel\magicvideo
cd C:\Travel\magicvideo
git ls-remote --heads origin claude/vibrant-brahmagupta-yr5pu4
```

- If that branch is listed and pull request #1 is not merged yet: `git checkout claude/vibrant-brahmagupta-yr5pu4`
- If #1 is merged: stay on `main`.

The repo is public, so cloning needs no login. Pushing (only for step 0.4 fixes) needs the owner's GitHub authentication.

**CHECK:** `Test-Path pyproject.toml, docs\IMPLEMENTATION_BRIEF.md, agent\SKILL.md` prints `True` three times.

## 4. Python environment and the first Windows test

```powershell
cd C:\Travel\magicvideo
py -$PY -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
setx PYTHONUTF8 1
$env:PYTHONUTF8 = "1"
pip install -e ".[dev]"
```

- If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first.
- `PYTHONUTF8=1` avoids encoding errors with non-English file names and transcripts.

**CHECK**

```powershell
magicvideo --version
pytest
```

Expected: `0.1.0`, then `35 passed`. This is the first time the code runs on Windows. If anything fails, **STOP** and report the full `pytest` output. Fix only per rule 0.4.

## 5. Model backends (GPU if available, otherwise CPU)

```powershell
nvidia-smi
```

**With an NVIDIA GPU** (`nvidia-smi` lists one):

1. Install the CUDA build of PyTorch *first*, using the command pytorch.org shows for: Windows, Pip, Python, the newest CUDA version the driver supports. It installs `torch` and `torchaudio`.
2. Install the extras:
   ```powershell
   pip install -e ".[asr,voice,tags,geo,faces-gpu]"
   ```
3. faster-whisper and insightface also pull in the CPU build of `onnxruntime`, which can shadow the GPU build. Keep only the GPU build:
   ```powershell
   pip uninstall -y onnxruntime
   pip install --force-reinstall --no-deps onnxruntime-gpu
   python -c "import onnxruntime as o; print(o.get_available_providers())"
   ```
   The list must include `CUDAExecutionProvider`.
4. faster-whisper on GPU also needs the CUDA 12 cuBLAS and cuDNN 9 libraries. If step 8 fails with a missing `cublas64_12.dll` or `cudnn*.dll`, follow the GPU section of the faster-whisper README for Windows. If that can't be resolved, set `compute.device: cpu` in the trip's `policy.yaml` and tell the owner. This is an allowed environment change.

**Without a GPU:**

```powershell
pip install torch torchaudio
pip install -e ".[asr,voice,tags,geo,faces]"
```

**torch and torchaudio must be a matching pair.** Check:

```powershell
python -c "import torch, torchaudio; print(torch.__version__, torchaudio.__version__)"
```

If that import fails: the newest torchaudio release (2.11.1) has no Windows wheels, so pip may have mixed versions. Pin both to the newest pair that has Windows wheels, then check again. With CUDA, use the PyTorch index URL from pytorch.org with the same two pins.

```powershell
pip install "torch==2.11.*" "torchaudio==2.11.*"
```

insightface 2.1 is pure Python, so no C++ compiler is needed. **If `insightface` still fails to install or import,** use the OpenCV face backend instead. It reuses the v2 model files. Find them:
   ```powershell
   Get-ChildItem C:\Travel -Recurse -Include face_detection_yunet_2023mar.onnx,face_recognition_sface_2021dec.onnx -ErrorAction SilentlyContinue | Select-Object FullName
   ```
   Note both paths for step 8, then tell the owner the fallback is in use.

**CHECK:** `magicvideo doctor`. Expected:

- the ffmpeg line, then `yes` for `v360`, `sendcmd`, `loudnorm`, `alimiter`, `vidstabdetect`, `deshake`, `lut3d`
- `gpu (cuda): yes` on a GPU machine
- `installed` for faster_whisper, speechbrain, insightface (unless the YuNet fallback is used), anthropic, reverse_geocoder, opentimelineio

Report the full output.

## 6. Anthropic API key (owner)

**STOP.** Ask the owner to type this themselves in their own PowerShell window, then open a new terminal:

```powershell
setx ANTHROPIC_API_KEY "<their key>"
```

**CHECK** (prints only `set` or `missing`, never the key):

```powershell
if ($env:ANTHROPIC_API_KEY) { "set" } else { "missing" }
```

Scene tagging defaults to the `claude-opus-5-5` model. To lower cost, the owner may ask for `cloud.model: claude-haiku-5-5` in a trip's `policy.yaml`. Change it only if the owner asks.

## 7. Install the new skill and retire the v2 skills (owner OK required)

**STOP.** Ask the owner to confirm before moving anything.

1. Copy the new operator skill to where Antigravity loads skills. The v2 skills lived in all three of these places; use the same ones:
   - `C:\Travel\.agents\skills\magicvideo\SKILL.md`
   - `C:\Travel\skills\magicvideo\SKILL.md`
   - `%USERPROFILE%\.gemini\config\plugins\user-skills-plugin\skills\magicvideo\SKILL.md`

   Source: `C:\Travel\magicvideo\agent\SKILL.md`.
2. **Move, don't delete,** the three v2 skill folders (`travel-footage-analyzer`, `travel-video-master-editor`, `couple-travel-documentary-editor`) out of every skill location into `C:\Travel\skills_retired_v2\<original location name>\`. This keeps them recoverable.

**CHECK:** Antigravity lists `magicvideo` as an available skill, and no longer lists the three v2 skills.

## 8. First test trip (the verification run)

**STOP.** The owner copies (not moves) 5–10 short clips into `C:\Travel\raw\Test_Trip\`:

- one clip from each camera
- for the X6: the `.insv`, its `.lrv`, **and** the Insta360 Studio export (see below)
- at least one conversation between the two of them
- one clip where a guide or waiter talks
- one vertical selfie
- one shaky walk

**X6 export (owner, in Insta360 Studio):**

1. Select the clips.
2. Export → 360° → equirectangular, with **FlowState** and **horizon lock** on.
3. Save the exports into the same folder as the `.insv` files.

Then run:

```powershell
cd C:\Travel\magicvideo
.\.venv\Scripts\Activate.ps1
magicvideo init C:\Travel\work\Test_Trip --source C:\Travel\raw\Test_Trip --people C:\Travel\people
```

**Only if the YuNet fallback is used (step 5):** in `C:\Travel\work\Test_Trip\policy.yaml`, set:

- `identity.face.backend: yunet`
- `identity.face.yunet_detector:` the detector path from step 5
- `identity.face.sface_recognizer:` the recognizer path from step 5

Use forward slashes in the paths.

```powershell
magicvideo analyze C:\Travel\work\Test_Trip
```

**CHECK**

- Open `C:\Travel\work\Test_Trip\analysis\summary.json`. Every step should be `done` for every clip. The only allowed exceptions are `asr` and `voices` for clips without audio. Report the file and any `failed:`/`skipped:` reasons from `analysis\<clip>\status.json`.
- In `inventory.json`, report each clip's `rel_path`, `camera.kind`, `projection`, `role` and `capture_start`.

```powershell
magicvideo enroll C:\Travel\work\Test_Trip
```

**STOP.** The owner follows `C:\Travel\people\REVIEW_Test_Trip.md`: they delete every face and voice folder that isn't one of them. Antigravity must not choose. When the owner says they're done:

```powershell
magicvideo enroll C:\Travel\work\Test_Trip --finalize
```

**CHECK:** the output shows `faces: approved from [...]` and `voices: approved from [...]`. If it says `need exactly 2 ...`, send the owner back to the review.

```powershell
magicvideo plan C:\Travel\work\Test_Trip --thumbs
```

**STOP.** The owner opens `C:\Travel\work\Test_Trip\plan\storyboard_v001.html` and reviews it. If they paste keep/drop lines into `C:\Travel\work\Test_Trip\overrides.yaml`, run `magicvideo plan` again and it writes `v002`, `v003` and so on. Report the plan warnings printed by the command.

```powershell
magicvideo render C:\Travel\work\Test_Trip
magicvideo qc C:\Travel\work\Test_Trip
```

**CHECK**

- `render` prints the paths of the master MP4, the chapter files and the `.otio` timeline.
- `qc` prints `QC verdict: PASS | FAIL | INCOMPLETE`, with exit codes 0, 2 and 3 respectively.
- Report the verdict and **every** row of `qc\qc_vNNN.md` that is not `PASS`, with its value, limit and detail.

**Finally:** go through `docs\VERIFICATION.md` with the owner (14 checks: watching the film, importing the `.otio` into DaVinci Resolve, and so on). Fill in the Result column.

## 9. Real trips (after the test trip is accepted)

For each trip:

```powershell
magicvideo init C:\Travel\work\<Trip> --source C:\Travel\raw\<Trip> --people C:\Travel\people
magicvideo analyze C:\Travel\work\<Trip>
magicvideo plan C:\Travel\work\<Trip> --thumbs
```

Then the owner reviews the storyboard, and you run:

```powershell
magicvideo render C:\Travel\work\<Trip>
magicvideo qc C:\Travel\work\<Trip>
```

- **Enrollment** (`magicvideo enroll`) is needed only once, because `C:\Travel\people` is shared. New embedding models would need a re-enrollment; the v2 `Couple_References` can't be reused.
- **Old v2 trips:** create new work folders. Never point magicvideo at v2 `output\work\...` folders.

## 10. Report back (template)

```
## Environment
- Windows version / GPU (nvidia-smi first lines) / ffmpeg version
- Python: `py -0p` output, step 2b check output, version used (`$PY`)
- Branch + commit: <git rev-parse --short HEAD>

## Step 4: pytest on Windows
<last 30 lines of output>

## Step 5: magicvideo doctor
<full output>  (fallbacks used: none | YuNet | CPU ASR)

## Step 8: test trip
- inventory table: rel_path | camera.kind | projection | role | capture_start
- analysis summary.json + any failed/skipped reasons
- enroll --finalize output
- plan warnings
- render outputs
- QC verdict + every non-PASS row (value, limit, detail)

## VERIFICATION.md table (filled)

## Problems and what was changed (environment changes; any code fix with branch name and pytest result)

## Samples for Claude
- 10–20 s each: X6 .insv + .lrv + Studio export, Osmo Nano clip, Pocket 4P clip
- inventory.json and analysis\<clip>\quality.json for those clips
```

Send the report and samples back to the owner, who will pass them to Claude for calibration: jitter thresholds, X6 fisheye FOV, any camera detection fixes.

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then retry |
| `magicvideo` not recognized | The venv isn't active. Activate it, or call `C:\Travel\magicvideo\.venv\Scripts\magicvideo.exe` |
| doctor shows `vidstabdetect: no` or `v360: no` | Wrong ffmpeg build or PATH order. Install `Gyan.FFmpeg` (full); check `where.exe ffmpeg` |
| pip tries to compile something ("Microsoft Visual C++ 14.0 or greater is required", CMake or Rust errors) | The Python version is too new for one dependency's Windows wheels. Re-run the step 2b check and use the version it picks |
| `import torch, torchaudio` fails | Pin a matching pair (step 5) |
| GPU machine, but `onnxruntime` has no `CUDAExecutionProvider` | Uninstall `onnxruntime`, reinstall `onnxruntime-gpu` (step 5) |
| insightface fails to install or import | YuNet fallback (step 5) |
| speechbrain: "symbolic link privilege not held" | The code already copies files on Windows. If it still appears, turn on Windows Developer Mode and report it |
| ASR on GPU: missing `cublas64_12.dll` / `cudnn` | Step 5 GPU note, or `compute.device: cpu` |
| `UnicodeEncodeError` | `$env:PYTHONUTF8 = "1"` (and `setx PYTHONUTF8 1`) |
| `tags` step `skipped: cloud tagging unavailable ... authentication` | API key missing or invalid (step 6) |
| plan warning `unstitched 360 recording skipped` | The Studio export for that `.insv` is missing (step 8) |
| render: `... already exists; outputs are never overwritten` | Expected. Run `magicvideo plan` to make a new version, then render |
| `QC verdict: INCOMPLETE` | A check was SKIPPED (for example ASR not installed, or no enrollment). Report which one; it isn't a pass |
| `QC verdict: FAIL` | Report the failing rows. Don't change thresholds or edit QC files (rule 0.4) |

## 12. Still open after handover

| Item | Owner / next step |
|---|---|
| Merge pull request #1 | Owner: after step 4 passes on Windows, or after the test trip |
| `docs/VERIFICATION.md` | Antigravity + owner, step 8 |
| Calibration from real samples (jitter thresholds, X6 fisheye FOV, camera tags) | Claude, from the report in section 10 |
| Interactive review app, highlights profile, Insta360 Media SDK, Gyroflow | Later builds (brief §3) |
