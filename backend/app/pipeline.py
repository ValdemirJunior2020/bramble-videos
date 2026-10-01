from __future__ import annotations

import asyncio

import httpx
from pathlib import Path

from .assets import find_asset
from .audio import build_narration_and_subtitles
from .comfy import generate_scene_image
from .config import settings
from .generation.wangp import WanGPError, wangp_service
from .models import Project
from .video import concat_clips, detect_encoder, make_scene_clip, render_final


def project_dir(project_id: str) -> Path:
    path = settings.projects_path / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_file(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def save_project(project: Project) -> None:
    project_file(project.id).write_text(project.model_dump_json(indent=2), encoding="utf-8")


def load_project(project_id: str) -> Project:
    path = project_file(project_id)
    if not path.exists():
        raise FileNotFoundError(project_id)
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def _missing_references(project: Project) -> list[str]:
    missing: set[str] = set()
    for scene in project.scenes:
        for name in scene.characters:
            asset = find_asset(name)
            if asset and not asset.identity_lock:
                continue
            if not asset or not asset.approved:
                missing.add(name)
                continue
            candidates = [asset.primary_image_path, *asset.image_paths]
            if not any(value and Path(value).exists() for value in candidates):
                missing.add(name)
    return sorted(missing)


async def _generate_wangp_scene(project: Project, scene, scene_index: int, total: int, regenerate: bool) -> Path:
    scene_dir = project_dir(project.id) / "scenes" / f"scene-{scene.scene_number:03d}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    final_clip = scene_dir / "clip.mp4"
    if final_clip.exists() and not regenerate and scene.generation_state == "complete":
        scene.clip_path = str(final_clip)
        return final_clip

    scene.generation_state = "pending"
    scene.generation_progress = 0
    scene.generation_phase = "Queued"
    save_project(project)

    def persist():
        project.stage = f"Scene {scene_index}/{total} · {scene.generation_phase or 'Generating'}"
        project.progress = min(82, 15 + round(62 * ((scene_index - 1) + scene.generation_progress / 100) / max(1, total)))
        save_project(project)

    try:
        outputs = await wangp_service.generate_scene(project, scene, scene_dir, on_update=persist)
    except Exception:
        scene.generation_state = "failed"
        scene.generation_phase = "Failed"
        save_project(project)
        raise
    if len(outputs) == 1:
        produced = outputs[0]
        if produced.resolve() != final_clip.resolve():
            final_clip.write_bytes(produced.read_bytes())
    else:
        encoder = await detect_encoder()
        await concat_clips(outputs, final_clip, encoder)
    scene.clip_path = str(final_clip)
    scene.generation_state = "complete"
    scene.generation_progress = 100
    scene.generation_phase = "Scene complete"
    save_project(project)
    return final_clip


async def _generate_comfy_scene(project: Project, scene, index: int, total: int, regenerate: bool) -> Path:
    folder = project_dir(project.id)
    images_dir = folder / "images"
    images_dir.mkdir(exist_ok=True)
    out = images_dir / f"scene-{scene.scene_number:03d}.png"
    if project.generate_images and (regenerate or not out.exists()):
        await generate_scene_image(project, scene, out)
    if not out.exists():
        fallback = None
        for name in [*scene.characters, scene.location]:
            asset = find_asset(name)
            if asset:
                fallback = next((Path(x) for x in asset.image_paths if Path(x).exists()), None)
                if fallback:
                    break
        if not fallback:
            raise RuntimeError(f"Scene {scene.scene_number} has no generated image or uploaded reference")
        out.write_bytes(fallback.read_bytes())
    scene.image_path = str(out)
    encoder = await detect_encoder()
    clips_dir = folder / "clips"
    clips_dir.mkdir(exist_ok=True)
    clip = clips_dir / f"scene-{scene.scene_number:03d}.mp4"
    await make_scene_clip(out, scene.duration_seconds, project, clip, index - 1, encoder)
    scene.clip_path = str(clip)
    save_project(project)
    return clip


async def _release_ollama_for_wangp() -> None:
    """Best-effort unload of the planning model so WanGP gets the 16 GB GPU budget."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{settings.ollama_url.rstrip('/')}/api/generate",
                json={"model": settings.ollama_model, "prompt": "", "keep_alive": 0, "stream": False},
            )
    except Exception:
        # Ollama is optional during rendering; failure to unload must not destroy a project.
        pass


async def _release_chatterbox_for_wangp() -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{settings.chatterbox_url.rstrip('/')}/unload")
    except Exception:
        pass


async def render_project(project_id: str, regenerate_all_images: bool = False) -> None:
    project = load_project(project_id)
    folder = project_dir(project_id)
    project.state = "rendering"
    project.progress = 1
    project.stage = "Checking character references"
    project.error = None
    save_project(project)
    try:
        if project.consistency_lock:
            missing = _missing_references(project)
            if missing:
                raise RuntimeError("Consistency Lock is ON. Missing approved reference for: " + ", ".join(missing))

        project.stage = "Creating phrase-timed narration"
        project.progress = 8
        save_project(project)
        previous_speed = settings.narration_speed
        settings.narration_speed = project.narrator_speed
        try:
            narration, subtitles, _ = await build_narration_and_subtitles(
                project.scenes,
                project.language,
                project.voice,
                project.narration_style,
                folder,
                project.reference_voice_path,
            )
        finally:
            settings.narration_speed = previous_speed
        project.narration_path = str(narration)
        project.subtitle_path = str(subtitles)
        save_project(project)

        if project.generation_engine == "wangp":
            project.stage = "Releasing planner VRAM for WanGP"
            save_project(project)
            await _release_ollama_for_wangp()
            await _release_chatterbox_for_wangp()

        clips: list[Path] = []
        total = len(project.scenes)
        for i, scene in enumerate(project.scenes, 1):
            project.stage = f"Scene {i}/{total} · Preparing"
            project.progress = 15 + round(62 * (i - 1) / max(1, total))
            save_project(project)
            if project.generation_engine == "wangp":
                clip = await _generate_wangp_scene(project, scene, i, total, regenerate_all_images)
            else:
                clip = await _generate_comfy_scene(project, scene, i, total, regenerate_all_images)
            clips.append(clip)

        encoder = await detect_encoder()
        project.video_encoder = encoder
        project.stage = f"Assembling cinematic clips ({encoder})"
        project.progress = 84
        save_project(project)
        visuals = folder / "visuals.mp4"
        await concat_clips(clips, visuals, encoder)

        project.stage = "Rendering narration, phrase subtitles, music and watermark"
        project.progress = 91
        save_project(project)
        final_dir = folder / "final"
        final_dir.mkdir(exist_ok=True)
        final = final_dir / f"{project.id}-final.mp4"
        project.video_encoder = await render_final(visuals, narration, subtitles, final, project, encoder)
        project.output_path = str(final)
        project.state = "complete"
        project.stage = "Complete"
        project.progress = 100
        save_project(project)
    except asyncio.CancelledError:
        project.state = "cancelled"
        project.stage = "Cancelled"
        project.error = "Generation was cancelled."
        save_project(project)
        raise
    except Exception as exc:
        project.state = "failed"
        project.stage = "Failed"
        project.error = str(exc)
        save_project(project)


TASKS: dict[str, asyncio.Task] = {}


def start_render(project_id: str, regenerate_all_images: bool = False) -> None:
    existing = TASKS.get(project_id)
    if existing and not existing.done():
        raise RuntimeError("This project is already rendering")
    TASKS[project_id] = asyncio.create_task(render_project(project_id, regenerate_all_images))


async def cancel_render(project_id: str) -> None:
    project = load_project(project_id)
    for scene in project.scenes:
        if scene.generation_job_id and scene.generation_state == "generating":
            try:
                await wangp_service.cancel(scene.generation_job_id)
            except Exception:
                pass
    task = TASKS.get(project_id)
    if task and not task.done():
        task.cancel()
