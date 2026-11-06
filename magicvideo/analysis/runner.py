"""`magicvideo analyze`: inventory + per-clip analysis steps with resumable status."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import ffmpeg, ingest
from ..project import Project
from ..util import log, read_json, write_json
from . import asr, faces, quality, tags, voices
from .asr import BackendMissing

ALL_STEPS = ["quality", "asr", "voices", "faces", "tags"]
AWAITING_AGENT = "skipped: awaiting agent tags"


def _asr_language(policy) -> str | None:
    return policy("compute.asr_language") or None


def _done(status: str | None) -> bool:
    return bool(status) and (status == "done" or status.startswith("skipped:"))


def run_inventory(project: Project) -> list[dict]:
    p = project.policy
    clips = ingest.build_inventory(project.source_dirs, p("trip.timezone"), project.devices())
    project.save_inventory(clips)
    n_src = len(ingest.plannable(clips))
    log.info("inventory: %d files, %d plannable clips", len(clips), n_src)
    for c in clips:
        if c.get("projection") == "dual_fisheye" and c.get("role") == "source" and c.get("render_projection") == "dual_fisheye":
            log.warning("%s: 360 recording without a stitched export; export it from Insta360 Studio "
                        "(equirectangular, FlowState + horizon lock) for best results", c["rel_path"])
        if c.get("color", {}).get("log_profile"):
            log.warning("%s: %s footage detected; set color.luts in policy.yaml to convert it",
                        c["rel_path"], c["color"]["log_profile"])
    return clips


def run_analysis(project: Project, steps: list[str] | None = None, force: bool = False) -> dict:
    policy = project.policy
    steps = steps or list(policy("analysis.steps"))
    clips = ingest.plannable(run_inventory(project))
    summary: dict[str, dict[str, int]] = {s: {"done": 0, "skipped": 0, "failed": 0} for s in steps}
    backends: dict[str, object] = {}
    unavailable: dict[str, str] = {}

    def backend(step: str):
        if step in unavailable:
            raise BackendMissing(unavailable[step])
        if step not in backends:
            try:
                if step == "faces":
                    backends[step] = faces.load_backend(policy)
                elif step == "tags":
                    backends[step] = tags.Tagger(policy)
                elif step == "asr":
                    backends[step] = asr.load_model(policy)
            except BackendMissing as e:
                unavailable[step] = str(e)
                raise
        return backends.get(step)

    for i, clip in enumerate(clips, 1):
        cid = clip["clip_id"]
        adir = project.analysis_dir(cid)
        status = project.step_status(cid)
        apath = Path(clip["analysis_path"])
        log.info("[%d/%d] %s", i, len(clips), clip["rel_path"])
        for step in steps:
            if not force and _done(status.get(step)):
                continue
            if step in unavailable and step != "voices":
                project.set_step_status(cid, step, f"skipped:{unavailable[step]}")
                summary[step]["skipped"] += 1
                continue
            try:
                if step == "quality":
                    data, desc = quality.analyze(apath, clip, policy)
                    write_json(adir / "quality.json", data)
                    np.save(adir / "visual_desc.npy", desc)
                elif step == "asr":
                    if not clip.get("has_audio"):
                        write_json(adir / "transcript.json", {"backend": "none", "words": [], "segments": []})
                        project.set_step_status(cid, step, "skipped:no audio")
                        summary[step]["skipped"] += 1
                        continue
                    backend("asr")
                    wav = ffmpeg.extract_audio(Path(clip["render_path"]), adir / "audio16k.wav")
                    write_json(adir / "transcript.json", asr.transcribe(wav, policy, language=_asr_language(policy)))
                elif step == "voices":
                    tr = read_json(adir / "transcript.json")
                    if tr is None:
                        raise BackendMissing("needs transcript (asr step)")
                    wins = voices.build_windows(tr["words"], float(policy("voice.window_gap_s")),
                                                float(policy("voice.window_max_s")))
                    wav = adir / "audio16k.wav"
                    emb = voices.embed_windows(wav, wins, policy) if wins else np.zeros((0, 192), np.float32)
                    np.save(adir / "voice_emb.npy", emb)
                    write_json(adir / "voices.json", {"backend": "speechbrain:ecapa-voxceleb", "windows": wins})
                elif step == "faces":
                    backend("faces")
                    data, emb = faces.analyze(apath, clip, policy)
                    write_json(adir / "faces.json", data)
                    np.save(adir / "face_emb.npy", emb)
                elif step == "tags" and policy("cloud.provider") == "agent":
                    if not policy("cloud.scene_tagging"):
                        raise BackendMissing("cloud.scene_tagging is false")
                    if tags.export_for_agent(project, clip, apath, policy) == 0:
                        project.set_step_status(cid, step, "done")  # nothing left to tag
                        summary[step]["done"] += 1
                    else:
                        project.set_step_status(cid, step, AWAITING_AGENT)
                        summary[step]["skipped"] += 1
                    continue
                elif step == "tags":
                    tagger = backend("tags")
                    prev = read_json(adir / "tags.json") if not force else None
                    write_json(adir / "tags.json", tags.analyze(apath, clip, policy, tagger, prev))
                project.set_step_status(cid, step, "done")
                summary[step]["done"] += 1
            except BackendMissing as e:
                project.set_step_status(cid, step, f"skipped:{e}")
                summary[step]["skipped"] += 1
                if step in ("asr", "voices", "faces", "tags") and "needs transcript" not in str(e):
                    unavailable.setdefault(step, str(e))  # e.g. bad API key: do not retry on every clip
            except Exception as e:  # keep going; the failure is recorded per clip
                log.exception("%s failed for %s", step, clip["rel_path"])
                project.set_step_status(cid, step, f"failed:{e}")
                summary[step]["failed"] += 1
    if "tags" in steps and policy("cloud.provider") == "agent" and policy("cloud.scene_tagging"):
        tags.write_tasks(project)
    for step, reason in unavailable.items():
        log.warning("step %s skipped for all clips: %s", step, reason)
    write_json(project.root / "analysis" / "summary.json", {"steps": summary, "unavailable": unavailable})
    return summary
