from __future__ import annotations

import asyncio
from pathlib import Path

from .assets import find_asset
from .audio import build_narration_and_subtitles
from .comfy import generate_scene_image
from .config import settings
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
            if not asset or not any(Path(x).exists() for x in asset.image_paths):
                missing.add(name)
    return sorted(missing)

async def render_project(project_id: str, regenerate_all_images: bool = False) -> None:
    project = load_project(project_id)
    folder = project_dir(project_id)
    project.state = "rendering"; project.progress = 1; project.stage = "Checking character references"; project.error = None; save_project(project)
    try:
        if project.consistency_lock:
            missing = _missing_references(project)
            if missing:
                raise RuntimeError("Consistency Lock is ON. Upload approved reference images for: " + ", ".join(missing))
        project.stage = "Creating phrase-timed narration"; project.progress = 8; save_project(project)
        narration, subtitles, _ = await build_narration_and_subtitles(project.scenes, project.language, project.voice, project.narration_style, folder)
        project.narration_path = str(narration); project.subtitle_path = str(subtitles); save_project(project)
        images_dir = folder / "images"; images_dir.mkdir(exist_ok=True)
        for i, scene in enumerate(project.scenes, 1):
            project.stage = f"Generating scene {i} of {len(project.scenes)}"; project.progress = 15 + round(48 * i / max(1, len(project.scenes))); save_project(project)
            out = images_dir / f"scene-{scene.scene_number:03d}.png"
            if project.generate_images and (regenerate_all_images or not out.exists()):
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
            scene.image_path = str(out); save_project(project)
        encoder = await detect_encoder(); project.video_encoder = encoder; project.stage = f"Building scene clips ({encoder})"; project.progress = 68; save_project(project)
        clips_dir = folder / "clips"; clips_dir.mkdir(exist_ok=True); clips: list[Path] = []
        for i, scene in enumerate(project.scenes):
            clip = clips_dir / f"scene-{scene.scene_number:03d}.mp4"
            await make_scene_clip(Path(scene.image_path), scene.duration_seconds, project, clip, i, encoder)
            clips.append(clip); project.progress = 68 + round(12 * (i + 1) / max(1, len(project.scenes))); save_project(project)
        visuals = folder / "visuals.mp4"; await concat_clips(clips, visuals, encoder)
        project.stage = "Burning phrase subtitles and final audio"; project.progress = 88; save_project(project)
        final = folder / "final.mp4"; project.video_encoder = await render_final(visuals, narration, subtitles, final, project, encoder)
        project.output_path = str(final); project.state = "complete"; project.stage = "Complete"; project.progress = 100; save_project(project)
    except Exception as exc:
        project.state = "failed"; project.stage = "Failed"; project.error = str(exc); save_project(project)

TASKS: dict[str, asyncio.Task] = {}
def start_render(project_id: str, regenerate_all_images: bool = False) -> None:
    existing = TASKS.get(project_id)
    if existing and not existing.done():
        raise RuntimeError("This project is already rendering")
    TASKS[project_id] = asyncio.create_task(render_project(project_id, regenerate_all_images))
