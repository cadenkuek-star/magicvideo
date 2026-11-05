# magicvideo

Turns a trip's raw footage (Insta360 X6, DJI Osmo Nano, DJI Osmo Pocket 4P, phones) into **one film per trip**. Alongside it you get:

- **One file per day**
- **An editable timeline** for DaVinci Resolve
- **A QC report** whose verdict is computed by a script

Your raw files are never modified.

- Design and reasoning: [docs/PROPOSAL.md](docs/PROPOSAL.md)
- Contract the code follows: [docs/IMPLEMENTATION_BRIEF.md](docs/IMPLEMENTATION_BRIEF.md)
- What still needs checking on real footage: [docs/VERIFICATION.md](docs/VERIFICATION.md)
- Setting it up on Windows with Antigravity: [docs/RELAY_ANTIGRAVITY.md](docs/RELAY_ANTIGRAVITY.md)

## What it does differently from v2

- **Your conversations stay whole.** Speech is attributed to *you two*, by voice, so a guide or waiter talking no longer counts as "dialogue". A conversation is kept from its first line to its last laugh. A pause is shortened only when a cutaway from the same scene can hide the cut.
- **Strangers, roads and B-roll get time budgets.** Each event gets a time budget, filled with its best and most varied shots. Film-wide limits apply too: transit at most 10% of the film, other people at most 5%.
- **Footage is fixed instead of rejected.** Clips are auto-rotated and stabilized (vidstab, or deshake as a fallback). Vertical clips are reframed with a face-centred crop or a *still* blurred background. 360° clips get a virtual camera that follows whoever is talking.
- **Every threshold lives in one file.** That file is `policy.yaml`. The same footage with the same policy always gives the same timeline.
- **QC can't be talked into a PASS.** If a check can't run, the verdict is INCOMPLETE, never PASS.

## Install (Windows)

1. Use Python 3.10–3.13 (whatever you already have in that range is fine; 3.13 recommended) and a *full* ffmpeg build (for example from gyan.dev) on PATH. You need the full build for vidstab and v360. Python 3.14+ works as soon as every dependency ships Windows wheels for it; [docs/RELAY_ANTIGRAVITY.md](docs/RELAY_ANTIGRAVITY.md) step 2 has the check.
2. From this folder, install the package:
   ```
   pip install -e ".[all]"
   ```
   With an NVIDIA GPU, also run `pip install -e ".[faces-gpu]"` and install the CUDA build of PyTorch, using the command from pytorch.org. Without a GPU everything runs on the CPU, just slower.
3. Scene tagging uses the Anthropic API on low-resolution stills only. Set your key:
   ```
   setx ANTHROPIC_API_KEY "sk-ant-..."
   ```
   It defaults to `claude-opus-5-5`. To cut tagging cost, set `cloud.model` in `policy.yaml` to a cheaper model such as `claude-haiku-5-5`.
4. Check what's available:
   ```
   magicvideo doctor
   ```

## Use

```
magicvideo init    C:\Travel\work\Seoul --source C:\Travel\raw\Seoul --people C:\Travel\people
magicvideo analyze C:\Travel\work\Seoul
magicvideo enroll  C:\Travel\work\Seoul            # first trip only: delete the folders that aren't you two
magicvideo enroll  C:\Travel\work\Seoul --finalize
magicvideo plan    C:\Travel\work\Seoul --thumbs   # then open plan\storyboard_v001.html
magicvideo render  C:\Travel\work\Seoul
magicvideo qc      C:\Travel\work\Seoul
```

**Review.** Open the storyboard, click *keep* or *drop* on any moment, and paste the generated lines into `overrides.yaml`. Then run `plan` again. Planning takes seconds, and your overrides carry over to every later plan.

**Output** goes in `C:\Travel\work\Seoul\output\`:

- `Seoul_v001.mp4`, the film
- `chapters\01_Day_1_…_v001.mp4`, one file per day
- `Seoul_v001.otio`, the timeline to import into Resolve and add music
- `Seoul_v001_edl.csv`

Nothing is ever overwritten: each new plan or render gets the next `vNNN`.

## Insta360 X6

Until the Insta360 Media SDK is set up, stitch in **Insta360 Studio**:

1. Select all of the trip's clips.
2. Export as **360° equirectangular**, with FlowState stabilization and horizon lock on.
3. Put the exports next to the `.insv` files.

magicvideo matches them to their recordings by name and timestamp. It uses the `.lrv` previews for analysis and the exports for the final render. `.insv` files that have no export are skipped, with a warning.

## What leaves your machine

Only stills for scene tagging, at most 512 px on the long side, nine per request. Video, audio, transcripts, face crops, embeddings and GPS never leave your machine.

## Development

```
pip install -e ".[dev]"
pytest
```

The tests run on synthetic footage generated with ffmpeg. They cover the planner, timing, render (including 360° reframing and the static background) and QC. The model backends (Whisper, speechbrain, insightface, the cloud tagger) need a one-time check on real clips, listed in [docs/VERIFICATION.md](docs/VERIFICATION.md).
