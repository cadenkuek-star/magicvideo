"""`magicvideo render`: timeline -> chapters + master MP4, OTIO, CSV (brief §6.8)."""
from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

import numpy as np

from .. import ffmpeg
from ..project import Project, ProjectError
from ..util import log, read_json, safe_name, version_of, vtag, write_json
from . import audio as A
from ..plan.planner import x6_export_list
from .export import write_edl_csv, write_otio
from .filters import (path_for_piece, per_frame_commands, reframe_filters, rotate_filters, stabilize_backend,
                      stabilize_filters, v360_filter)


def pieces_of(timeline: dict) -> list[dict]:
    """Cut the timeline at every segment/overlay boundary; video from overlay if present."""
    segs, ovs = timeline["segments"], timeline["overlays"]
    cuts = {0, timeline["total_frames"]}
    for s in segs:
        cuts.update((s["start_frame"], s["start_frame"] + s["frames"]))
    for o in ovs:
        cuts.update((o["start_frame"], o["start_frame"] + o["frames"]))
    bounds = sorted(cuts)
    out = []
    si = 0
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        while segs[si]["start_frame"] + segs[si]["frames"] <= a:
            si += 1
        seg = segs[si]
        ov = next((o for o in ovs if o["start_frame"] <= a < o["start_frame"] + o["frames"]), None)
        src = ov or seg
        off = a - src["start_frame"]
        out.append({"index": len(out) + 1, "start_frame": a, "frames": b - a, "chapter": seg["chapter"],
                    "clip_id": src["clip_id"], "offset": off, "src": src, "is_overlay": ov is not None})
    return out


class Renderer:
    def __init__(self, project: Project, plan_tag: str | None = None):
        self.p = project
        self.policy = project.policy
        tl_files = sorted(project.plan_dir.glob("timeline_v*.json"))
        if not tl_files:
            raise ProjectError("no timeline: run `magicvideo plan` first")
        if plan_tag:
            path = project.plan_dir / f"timeline_{plan_tag}.json"
        else:
            path = max(tl_files, key=lambda p: version_of(p) or 0)
        self.tag = vtag(version_of(path) or 1)
        self.timeline = read_json(path)
        self.clips = {c["clip_id"]: c for c in project.inventory()}
        self.fps = Fraction(*self.timeline["fps"])
        self.W, self.H = self.timeline["width"], self.timeline["height"]
        self.work = project.render_dir(self.tag)
        self.pdir = self.work / "pieces"
        self.out_dir = project.output_dir
        self.name = safe_name(self.timeline["name"])
        self.log: dict = {"version": self.tag, "pieces": [], "stabilizer": stabilize_backend()}

    # ------------------------------------------------------------------ video pieces
    def _piece_cmd(self, pc: dict) -> tuple[list[list[str]], str]:
        src = pc["src"]
        clip = self.clips[pc["clip_id"]]
        spec = src["reframe"]
        path = Path(clip["render_path"])
        src_in = float(src["src_in"]) + pc["offset"] / float(self.fps)
        n = pc["frames"]
        name = f"p{pc['index']:05d}"
        fps_s = f"{self.fps.numerator}/{self.fps.denominator}"
        pre = ["setpts=PTS-STARTPTS"] + rotate_filters(int(spec.get("rotate", 0))) + [f"fps={fps_s}"]
        lut = (self.policy("color.luts") or {}).get((clip.get("color") or {}).get("log_profile") or "")
        if lut and Path(lut).exists():
            local = f"{name}.cube"
            shutil.copyfile(lut, self.pdir / local)
            pre.append(f"lut3d=file={local}")
        cmds: list[list[str]] = []
        stab: list[str] = []
        if src.get("stabilize") and spec.get("mode") != "v360":
            zoom = float(self.policy("quality.stabilize_max_zoom"))
            if stabilize_backend() == "vidstab":
                detect = pre + stabilize_filters(f"{name}.trf", zoom, detect=True)
                cmds.append(["-y", "-v", "error", "-ss", f"{src_in:.6f}", "-i", str(path), "-an",
                             "-vf", ",".join(detect), "-frames:v", str(n), "-f", "null", "-"])
            stab = stabilize_filters(f"{name}.trf", zoom, detect=False)
        inputs = ["-ss", f"{src_in:.6f}", "-i", str(path)]
        tail = ["tpad=stop_mode=clone:stop_duration=5", "format=yuv420p", "setsar=1"]
        if spec.get("mode") == "v360":
            ppath = path_for_piece(spec.get("path", []), pc["offset"], n)
            lines = per_frame_commands(ppath, n, float(self.fps), self.W, self.H)
            cmd_name = None
            if lines:
                cmd_name = f"{name}.cmd"
                (self.pdir / cmd_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
            chain = pre + v360_filter(spec, self.W, self.H, cmd_name, float(self.policy("insta360.fisheye_fov_deg")),
                                      ppath[0]) + tail
            graph = ["-vf", ",".join(chain)]
        elif spec.get("mode") == "static_bg":
            bg = f"{name}_bg.png"
            bg_vf = ",".join(rotate_filters(int(spec.get("rotate", 0))) + [
                f"scale={self.W}:{self.H}:force_original_aspect_ratio=increase", f"crop={self.W}:{self.H}",
                f"gblur=sigma={float(self.policy('reframe.bg_blur_sigma')):g}",
                f"eq=brightness={float(self.policy('reframe.bg_brightness')):g}:saturation=0.85"])
            ffmpeg.frame_png(path, float(spec.get("bg_t", src_in)), self.pdir / bg, vf=bg_vf)
            inputs += ["-loop", "1", "-i", bg]
            fg = ",".join(pre + stab + reframe_filters(spec, self.W, self.H))
            graph = ["-filter_complex",
                     f"[0:v]{fg}[fg];[1:v]fps={fps_s},format=yuv420p[bg];"
                     f"[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:shortest=1,{','.join(tail)}[v]", "-map", "[v]"]
        else:
            graph = ["-vf", ",".join(pre + stab + reframe_filters(spec, self.W, self.H) + tail)]
        out = f"{name}.mp4"
        cmds.append(["-y", "-v", "error", *inputs, "-an", *graph, "-frames:v", str(n), "-r", fps_s,
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", str(self.policy("render.intermediate_crf")),
                     "-pix_fmt", "yuv420p", "-g", str(max(1, int(float(self.fps) * 2))), out])
        return cmds, out

    def _render_piece(self, pc: dict) -> str:
        cmds, out = self._piece_cmd(pc)
        target = self.pdir / out
        if target.exists() and self._frames(target) == pc["frames"]:
            return out  # resumable
        for c in cmds:
            ffmpeg.run(c, cwd=self.pdir)
        got = self._frames(target)
        if got != pc["frames"]:
            raise ffmpeg.FFmpegError(f"piece {out}: {got} frames, expected {pc['frames']}")
        return out

    @staticmethod
    def _frames(path: Path) -> int:
        info = ffmpeg.probe(path)
        v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
        if not v:
            return -1
        nb = v.get("nb_frames")
        if nb and str(nb).isdigit():
            return int(nb)
        return ffmpeg.count_frames(path)

    # ------------------------------------------------------------------ audio
    def _render_audio(self) -> tuple[Path, dict]:
        sr = int(self.policy("audio.sample_rate"))
        fade = float(self.policy("render.audio_fade_ms"))
        raw = self.work / "master_audio.f32"
        segs = self.timeline["segments"]
        # pass 1: dialogue levels of conversation segments
        levels: dict[str, float] = {}
        cache: dict[str, np.ndarray] = {}
        for s in segs:
            clip = self.clips[s["clip_id"]]
            a, b = A.sample_bounds(s["start_frame"], s["frames"], self.fps, sr)
            x = A.extract_segment(Path(clip["render_path"]), float(s["src_in"]), b - a, sr,
                                  bool(clip.get("has_audio")), fade)
            if s["kind"] == "conversation":
                lv = A.speech_level_db(x, sr)
                if lv is not None:
                    levels[s["id"]] = lv
            if len(cache) < 64:
                cache[s["id"]] = x
        gains = A.dialogue_gains(levels, float(self.policy("audio.dialogue_match_max_db")))
        total = 0
        with open(raw, "wb") as f:
            for s in segs:
                clip = self.clips[s["clip_id"]]
                a, b = A.sample_bounds(s["start_frame"], s["frames"], self.fps, sr)
                x = cache.pop(s["id"], None)
                if x is None:
                    x = A.extract_segment(Path(clip["render_path"]), float(s["src_in"]), b - a, sr,
                                          bool(clip.get("has_audio")), fade)
                g = gains.get(s["id"], 0.0) + float(s.get("gain_db", 0.0))
                if g:
                    x = x * np.float32(10 ** (g / 20))
                f.write(np.ascontiguousarray(x, dtype=np.float32).tobytes())
                total += len(x)
        expected = A.sample_bounds(0, self.timeline["total_frames"], self.fps, sr)[1]
        if total != expected:
            raise RuntimeError(f"audio sample count {total} != expected {expected}")
        wav = self.work / "master_audio.wav"
        loud = A.master_loudness(raw, wav, self.policy)
        loud["dialogue_gains_db"] = {k: round(v, 2) for k, v in gains.items()}
        raw.unlink(missing_ok=True)
        return wav, loud

    # ------------------------------------------------------------------ main
    def run(self) -> dict:
        master_path = self.out_dir / f"{self.name}_{self.tag}.mp4"
        if master_path.exists():
            raise ProjectError(f"{master_path.name} already exists; outputs are never overwritten "
                               "(run `magicvideo plan` to create a new version)")
        exports = x6_export_list(self.timeline, list(self.clips.values()), self.policy)
        if exports:
            names = ", ".join(e["rel_path"] for e in exports)
            raise ProjectError(f"{len(exports)} Insta360 clip(s) must be exported from Insta360 Studio before "
                               f"render: {names}. See {self.p.plan_dir / f'x6_exports_{self.tag}.md'}")
        self.pdir.mkdir(parents=True, exist_ok=True)
        pieces = pieces_of(self.timeline)
        workers = int(self.policy("render.workers")) if str(self.policy("render.workers")) != "auto" \
            else max(1, min(4, (os.cpu_count() or 2) // 2))
        log.info("render %s: %d pieces, %d frames @ %s fps, %dx%d, %d workers", self.tag, len(pieces),
                 self.timeline["total_frames"], self.fps, self.W, self.H, workers)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            outs = list(ex.map(self._render_piece, pieces))
        for pc, out in zip(pieces, outs):
            self.log["pieces"].append({"piece": out, "clip_id": pc["clip_id"], "frames": pc["frames"],
                                       "mode": pc["src"]["reframe"].get("mode"), "overlay": pc["is_overlay"],
                                       "stabilized": bool(pc["src"].get("stabilize"))})
        vcfg = self.policy("output.video")
        fps_s = f"{self.fps.numerator}/{self.fps.denominator}"
        chapter_videos = []
        for ch in self.timeline["chapters"]:
            lst = self.work / f"chapter_{ch['index']:02d}.txt"
            lst.write_text("".join(f"file 'pieces/{o}'\n" for pc, o in zip(pieces, outs)
                                   if pc["chapter"] == ch["index"]), encoding="utf-8")
            vout = self.work / f"chapter_{ch['index']:02d}_video.mp4"
            ffmpeg.run(["-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name, "-an",
                        "-c:v", vcfg["codec"], "-preset", vcfg["preset"], "-crf", str(vcfg["crf"]),
                        "-profile:v", vcfg["profile"], "-pix_fmt", "yuv420p", "-r", fps_s,
                        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                        "-frames:v", str(ch["end_frame"] - ch["start_frame"]), "-movflags", "+faststart",
                        vout.name], cwd=self.work)
            chapter_videos.append((ch, vout))
        lst = self.work / "master_video.txt"
        lst.write_text("".join(f"file '{v.name}'\n" for _, v in chapter_videos), encoding="utf-8")
        mvid = self.work / "master_video.mp4"
        ffmpeg.run(["-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", mvid.name],
                   cwd=self.work)
        wav, loud = self._render_audio()
        self.log["loudness"] = loud
        sr = int(self.policy("audio.sample_rate"))
        abr = str(self.policy("audio.aac_bitrate"))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg.run(["-y", "-v", "error", "-i", str(mvid), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", abr, "-ar", str(sr), "-ac", "2",
                    "-metadata", f"title={self.timeline['name']}", "-movflags", "+faststart", str(master_path)])
        outputs = {"master": str(master_path), "chapters": []}
        if self.policy("output.chapters"):
            cdir = self.out_dir / "chapters"
            cdir.mkdir(parents=True, exist_ok=True)
            for ch, vout in chapter_videos:
                a, b = A.sample_bounds(ch["start_frame"], ch["end_frame"] - ch["start_frame"], self.fps, sr)
                cpath = cdir / f"{ch['index']:02d}_{safe_name(ch['name'], 50)}_{self.tag}.mp4"
                ffmpeg.run(["-y", "-v", "error", "-i", str(vout), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
                            "-filter:a", f"atrim=start_sample={a}:end_sample={b},asetpts=PTS-STARTPTS",
                            "-c:v", "copy", "-c:a", "aac", "-b:a", abr, "-ar", str(sr), "-ac", "2",
                            "-metadata", f"title={ch['name']}", "-movflags", "+faststart", str(cpath)])
                outputs["chapters"].append(str(cpath))
        outputs["otio"] = str(write_otio(self.timeline, self.clips, self.out_dir / f"{self.name}_{self.tag}.otio"))
        outputs["edl_csv"] = str(write_edl_csv(self.timeline, self.clips, self.out_dir / f"{self.name}_{self.tag}_edl.csv"))
        self.log["outputs"] = outputs
        write_json(self.work / f"render_{self.tag}.json", self.log)
        if not self.policy("render.keep_intermediates"):
            shutil.rmtree(self.pdir, ignore_errors=True)
        log.info("rendered %s (loudness I=%.1f LUFS, TP=%.1f dBTP)", master_path.name,
                 loud["output"]["I"], loud["output"]["TP"])
        return outputs
