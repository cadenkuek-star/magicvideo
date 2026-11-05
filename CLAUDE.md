# magicvideo: notes for coding agents

- Contract: `docs/IMPLEMENTATION_BRIEF.md`. If code and brief disagree, fix one of them in the same commit.
- Every threshold belongs in `magicvideo/default_policy.yaml` and is read via `policy("dotted.key")`. Don't hard-code numbers in planner, render or QC code.
- The planner must stay deterministic: same inputs, byte-identical `timeline.json`. Sort explicitly; never iterate over sets into output.
- Optional backends (faster-whisper, speechbrain, insightface, anthropic, reverse_geocoder) are imported lazily and raise `BackendMissing`.
- Only `magicvideo qc` writes QC files. A check that can't run is SKIPPED, and the verdict is then INCOMPLETE.
- Windows is the primary target: `pathlib`, subprocess argument lists, and relative filter-file names with `cwd` set.
- Run `pytest` (it uses synthetic ffmpeg footage) before committing.
