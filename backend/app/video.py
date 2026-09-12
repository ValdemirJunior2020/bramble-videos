from __future__ import annotations

import asyncio
from pathlib import Path

from .config import settings
from .models import Project
from .comfy import dimensions

async def _run(cmd: list[str], allow_fail: bool = False):
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0 and not allow_fail:
        raise RuntimeError(err.decode(errors="ignore")[-4000:])
    return proc.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")

async def detect_encoder() -> str:
    if settings.ffmpeg_encoder and settings.ffmpeg_encoder != "auto":
        return settings.ffmpeg_encoder
    code, out, err = await _run(["ffmpeg", "-hide_banner", "-encoders"], allow_fail=True)
    return "h264_amf" if code == 0 and "h264_amf" in out + err else "libx264"

def _encoder_args(encoder: str) -> list[str]:
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]

def _escape_sub(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "\\'").replace(":", "\\:")

async def make_scene_clip(image: Path, seconds: float, project: Project, output: Path, index: int, encoder: str) -> None:
    width, height = dimensions(project)
    frames = max(1, round(seconds * 30))
    zoom = "min(zoom+0.00022,1.035)" if index % 2 == 0 else "if(eq(on,1),1.035,max(1.0,zoom-0.00022))"
    vf = f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,crop={width*2}:{height*2},zoompan=z='{zoom}':d={frames}:s={width}x{height}:fps=30"
    if project.transition == "Gentle Fade" and seconds > 1.0:
        vf += f",fade=t=in:st=0:d=0.22,fade=t=out:st={max(0.1, seconds-0.28):.3f}:d=0.28"
    base = ["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-t", f"{seconds:.3f}", "-vf", vf, "-an", "-pix_fmt", "yuv420p"]
    code, _, _ = await _run([*base, *_encoder_args(encoder), str(output)], allow_fail=True)
    if code != 0 and encoder != "libx264":
        await _run([*base, *_encoder_args("libx264"), str(output)])

async def concat_clips(clips: list[Path], output: Path, encoder: str) -> None:
    listfile = output.with_suffix(".txt")
    listfile.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in clips), encoding="utf-8")
    base = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile), "-an"]
    code, _, _ = await _run([*base, *_encoder_args(encoder), str(output)], allow_fail=True)
    if code != 0 and encoder != "libx264":
        await _run([*base, *_encoder_args("libx264"), str(output)])

async def render_final(visuals: Path, narration: Path, subtitles: Path, output: Path, project: Project, encoder: str) -> str:
    cmd = ["ffmpeg", "-y", "-i", str(visuals), "-i", str(narration)]
    audio_map = ["-map", "1:a:0"]
    filters = [f"[0:v]subtitles='{_escape_sub(subtitles)}':force_style='FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=3,Shadow=0,Alignment=2,MarginV=65'[v]"]
    if project.background_music_path and Path(project.background_music_path).exists():
        cmd += ["-stream_loop", "-1", "-i", project.background_music_path]
        filters += [f"[2:a]volume={project.music_volume}[m]", "[1:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]"]
        audio_map = ["-map", "[a]"]
    cmd += ["-filter_complex", ";".join(filters), "-map", "[v]", *audio_map, "-shortest", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-pix_fmt", "yuv420p"]
    code, _, _ = await _run([*cmd, *_encoder_args(encoder), str(output)], allow_fail=True)
    if code == 0:
        return encoder
    if encoder != "libx264":
        await _run([*cmd, *_encoder_args("libx264"), str(output)])
        return "libx264"
    raise RuntimeError("Final FFmpeg render failed")
