from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .assets import add_reference, delete_asset, load_assets
from .audio import list_sapi_voices
from .comfy import generate_scene_image
from .config import settings
from .models import Project, ProjectCreate, RenderRequest, SceneUpdate
from .pipeline import load_project, project_dir, save_project, start_render
from .planner import plan_scenes, build_prompt
from .video import detect_encoder

app = FastAPI(title="Bramble Videos", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health():
    ollama = False
    ollama_vram = 0
    comfyui = False
    comfy_device = ""
    comfy_vram_total = 0
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{settings.ollama_url.rstrip('/')}/api/ps")
            ollama = response.status_code == 200
            if ollama:
                ollama_vram = sum(int(model.get("size_vram") or 0) for model in response.json().get("models", []))
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{settings.comfyui_url.rstrip('/')}/system_stats")
            comfyui = response.status_code == 200
            if comfyui:
                devices = response.json().get("devices", [])
                if devices:
                    device = devices[0]
                    comfy_device = str(device.get("name") or device.get("type") or "GPU")
                    comfy_vram_total = int(device.get("vram_total") or 0)
    except Exception:
        pass
    return {"status": "ok", "ollama": ollama, "ollama_gpu_vram_bytes": ollama_vram, "comfyui": comfyui, "comfy_device": comfy_device, "comfy_vram_total_bytes": comfy_vram_total, "ffmpeg_encoder": await detect_encoder(), "storage": str(settings.storage_path.resolve())}

@app.get("/api/voices")
async def voices():
    return [voice.model_dump() for voice in await list_sapi_voices()]

@app.get("/api/assets")
def assets():
    return [asset.model_dump() for asset in load_assets()]

@app.post("/api/assets")
async def upload_asset(name: str = Form(...), asset_type: str = Form(...), aliases: str = Form(""), description: str = Form(""), traits: str = Form(""), file: UploadFile = File(...)):
    if asset_type not in {"character", "location", "prop", "group"}:
        raise HTTPException(400, "Invalid asset type")
    try:
        return (await add_reference(name, asset_type, file, aliases, description, traits)).model_dump()
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.delete("/api/assets/{asset_id}")
def remove_asset(asset_id: str):
    if not delete_asset(asset_id):
        raise HTTPException(404, "Asset not found")
    return {"ok": True}

@app.post("/api/uploads")
async def upload_file(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload.bin").suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(400, "Unsupported upload type")
    target = settings.uploads_path / f"{uuid4().hex}{suffix}"
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"path": str(target)}

@app.post("/api/projects")
async def create_project(request: ProjectCreate):
    scenes = await plan_scenes(request)
    project = Project(id=uuid4().hex, title=request.title, script=request.script, language=request.language, aspect=request.aspect, custom_width=request.custom_width, custom_height=request.custom_height, voice=request.voice, narration_style=request.narration_style, consistency_lock=request.consistency_lock, generate_images=request.generate_images, reference_denoise=request.reference_denoise, transition=request.transition, background_music_path=request.background_music_path, music_volume=request.music_volume, scenes=scenes)
    save_project(project)
    return project.model_dump()

@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    try:
        return load_project(project_id).model_dump()
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")

@app.patch("/api/projects/{project_id}/scenes/{scene_number}")
def update_scene(project_id: str, scene_number: int, update: SceneUpdate):
    try:
        project = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    scene = next((item for item in project.scenes if item.scene_number == scene_number), None)
    if not scene:
        raise HTTPException(404, "Scene not found")
    data = update.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(scene, key, value)
    if any(key in data for key in {"characters", "location", "emotion", "action"}) and "image_prompt" not in data:
        scene.image_prompt = build_prompt(scene)
    save_project(project)
    return scene.model_dump()

@app.post("/api/projects/{project_id}/scenes/{scene_number}/regenerate")
async def regenerate_scene(project_id: str, scene_number: int):
    project = load_project(project_id)
    scene = next((item for item in project.scenes if item.scene_number == scene_number), None)
    if not scene:
        raise HTTPException(404, "Scene not found")
    out = project_dir(project_id) / "images" / f"scene-{scene.scene_number:03d}.png"
    await generate_scene_image(project, scene, out)
    scene.image_path = str(out)
    save_project(project)
    return scene.model_dump()

@app.get("/api/projects/{project_id}/scenes/{scene_number}/image")
def scene_image(project_id: str, scene_number: int):
    project = load_project(project_id)
    scene = next((item for item in project.scenes if item.scene_number == scene_number), None)
    if not scene or not scene.image_path:
        raise HTTPException(404, "Scene image not ready")
    path = Path(scene.image_path)
    if not path.exists():
        raise HTTPException(404, "Scene image not ready")
    return FileResponse(path)

@app.post("/api/projects/{project_id}/render")
def render(project_id: str, request: RenderRequest):
    try:
        load_project(project_id)
        start_render(project_id, request.regenerate_all_images)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}

@app.get("/api/projects/{project_id}/subtitles")
def subtitles(project_id: str):
    project = load_project(project_id)
    if not project.subtitle_path or not Path(project.subtitle_path).exists():
        raise HTTPException(404, "Subtitles not ready")
    return FileResponse(project.subtitle_path, media_type="application/x-subrip", filename=f"{project.title}.srt")

@app.get("/api/projects/{project_id}/video")
def video(project_id: str):
    project = load_project(project_id)
    if not project.output_path or not Path(project.output_path).exists():
        raise HTTPException(404, "Video not ready")
    return FileResponse(project.output_path, media_type="video/mp4", filename=f"{project.title}.mp4")
