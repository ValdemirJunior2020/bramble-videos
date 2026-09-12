from __future__ import annotations

import asyncio
import math
import random
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image, ImageOps

from .assets import find_asset
from .config import settings
from .models import Project, Scene


def dimensions(project: Project) -> tuple[int, int]:
    if project.aspect == "16:9":
        return (1920, 1080)
    if project.aspect == "9:16":
        return (1080, 1920)
    if project.aspect == "1:1":
        return (1536, 1536)
    if project.aspect == "4:5":
        return (1440, 1800)
    return (project.custom_width or 1920, project.custom_height or 1080)


async def health() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{settings.comfyui_url.rstrip('/')}/system_stats")
            return response.status_code == 200
    except Exception:
        return False


async def _object_info(node: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{settings.comfyui_url.rstrip('/')}/object_info/{node}")
        if response.status_code >= 400:
            return {}
        data = response.json()
    return data.get(node, data)


def _first_required_option(info: dict, key: str) -> str:
    try:
        values = info["input"]["required"][key][0]
        return values[0] if values else ""
    except Exception:
        return ""


async def checkpoint_name() -> str:
    if settings.comfyui_checkpoint.strip():
        return settings.comfyui_checkpoint.strip()
    value = _first_required_option(
        await _object_info("CheckpointLoaderSimple"),
        "ckpt_name",
    )
    if not value:
        raise RuntimeError(
            "No ComfyUI checkpoint found. Put a checkpoint in ComfyUI/models/checkpoints or set COMFYUI_CHECKPOINT."
        )
    return value


async def _ipadapter_options() -> tuple[str, str] | None:
    loader = await _object_info("IPAdapterModelLoader")
    vision = await _object_info("CLIPVisionLoader")
    advanced = await _object_info("IPAdapterAdvanced")
    if not loader or not vision or not advanced:
        return None
    adapter = _first_required_option(loader, "ipadapter_file")
    clip = _first_required_option(vision, "clip_name")
    return (adapter, clip) if adapter and clip else None


def _reference_paths(scene: Scene) -> list[Path]:
    paths: list[Path] = []
    for name in scene.characters:
        asset = find_asset(name)
        if not asset:
            continue
        valid = [Path(value) for value in asset.image_paths if Path(value).exists()]
        # Two references per character is enough for identity while avoiding a huge collage.
        paths.extend(valid[:2])
    return paths[:6]


def _reference_sheet(scene: Scene, out: Path) -> Path | None:
    """Build a neutral square identity board for IP-Adapter only.

    This is intentionally NOT the same shape as the movie frame so the model is less likely
    to reproduce the upload layout as the final composition.
    """
    refs = _reference_paths(scene)
    if not refs:
        return None

    size = 1024
    canvas = Image.new("RGB", (size, size), "#808080")
    cols = min(3, max(1, math.ceil(math.sqrt(len(refs)))))
    rows = max(1, math.ceil(len(refs) / cols))
    cell_w = size // cols
    cell_h = size // rows

    for i, path in enumerate(refs):
        image = Image.open(path).convert("RGB")
        # Keep the entire uploaded face/body reference visible, but do not stretch it into the movie frame.
        fitted = ImageOps.contain(
            image,
            (max(96, cell_w - 40), max(96, cell_h - 40)),
            method=Image.Resampling.LANCZOS,
        )
        col = i % cols
        row = i // cols
        x = col * cell_w + (cell_w - fitted.width) // 2
        y = row * cell_h + (cell_h - fitted.height) // 2
        canvas.paste(fitted, (x, y))

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, format="PNG", optimize=True)
    return out


async def _upload_reference(path: Path) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        with path.open("rb") as handle:
            response = await client.post(
                f"{settings.comfyui_url.rstrip('/')}/upload/image",
                data={"overwrite": "true"},
                files={"image": (path.name, handle, "image/png")},
            )
        response.raise_for_status()
        data = response.json()
    return data.get("name") or path.name


def _base_nodes(checkpoint: str, prompt: str, negative: str) -> dict:
    return {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["4", 1]},
        },
    }


def _text_workflow(
    checkpoint: str,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
) -> dict:
    wf = _base_nodes(checkpoint, prompt, negative)
    wf.update(
        {
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": 34,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "bramble_scene", "images": ["8", 0]},
            },
        }
    )
    return wf


def _ipadapter_workflow(
    checkpoint: str,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    reference_name: str,
    adapter_file: str,
    clip_name: str,
) -> dict:
    wf = _base_nodes(checkpoint, prompt, negative)
    wf.update(
        {
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "10": {
                "class_type": "LoadImage",
                "inputs": {"image": reference_name},
            },
            "11": {
                "class_type": "IPAdapterModelLoader",
                "inputs": {"ipadapter_file": adapter_file},
            },
            "12": {
                "class_type": "CLIPVisionLoader",
                "inputs": {"clip_name": clip_name},
            },
            "13": {
                "class_type": "IPAdapterAdvanced",
                "inputs": {
                    # Lower weight preserves identity without copying the uploaded sheet composition.
                    "weight": 0.62,
                    "weight_type": "linear",
                    "combine_embeds": "concat",
                    "start_at": 0.0,
                    "end_at": 0.82,
                    "embeds_scaling": "V only",
                    "model": ["4", 0],
                    "ipadapter": ["11", 0],
                    "image": ["10", 0],
                    "clip_vision": ["12", 0],
                },
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": 34,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["13", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "bramble_scene", "images": ["8", 0]},
            },
        }
    )
    return wf


async def _queue(workflow: dict, client_id: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.comfyui_url.rstrip('/')}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        response.raise_for_status()
        return response.json()["prompt_id"]


async def generate_scene_image(
    project: Project,
    scene: Scene,
    out_path: Path,
    force_text_only: bool = False,
) -> Path:
    if not await health():
        raise RuntimeError("ComfyUI is not running on port 8188")

    width, height = dimensions(project)
    checkpoint = await checkpoint_name()
    seed = random.randint(1, 2_147_483_647)
    client_id = str(uuid4())

    # Make the story beat stronger than the identity reference.
    prompt = (
        scene.image_prompt
        + ", create a completely new cinematic scene matching the spoken action; "
        + "do not reproduce the uploaded reference image layout, pose, background, framing, or character sheet"
    )
    negative = (
        scene.negative_prompt
        + ", copied reference image, copied pose, copied framing, character sheet, turnaround sheet, model sheet, "
        + "reference board, contact sheet, collage, split screen, multiple character views, white studio background"
    )

    prompt_id = ""
    reference_name: str | None = None

    if scene.characters and not force_text_only:
        sheet = _reference_sheet(
            scene,
            out_path.with_name(f"scene-{scene.scene_number:03d}-identity.png"),
        )
        if sheet:
            reference_name = await _upload_reference(sheet)

    # Use references only through IP-Adapter. NEVER feed a character sheet into VAE img2img,
    # because that causes the final movie frame to reproduce the uploaded sheet itself.
    if reference_name:
        options = await _ipadapter_options()
        if options:
            try:
                prompt_id = await _queue(
                    _ipadapter_workflow(
                        checkpoint,
                        prompt,
                        negative,
                        width,
                        height,
                        seed,
                        reference_name,
                        options[0],
                        options[1],
                    ),
                    client_id,
                )
            except Exception:
                prompt_id = ""

    # Safe fallback: fresh text-to-image using the character traits embedded in the prompt.
    # This may preserve identity less strongly than IP-Adapter, but it will still create the correct story scene
    # instead of copying the uploaded front/back/face reference sheet.
    if not prompt_id:
        prompt_id = await _queue(
            _text_workflow(
                checkpoint,
                prompt,
                negative,
                width,
                height,
                seed,
            ),
            client_id,
        )

    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(600):
            await asyncio.sleep(1)
            response = await client.get(
                f"{settings.comfyui_url.rstrip('/')}/history/{prompt_id}"
            )
            response.raise_for_status()
            history = response.json()
            if prompt_id not in history:
                continue

            for node in history[prompt_id].get("outputs", {}).values():
                for image in node.get("images", []):
                    params = {
                        "filename": image["filename"],
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    }
                    result = await client.get(
                        f"{settings.comfyui_url.rstrip('/')}/view",
                        params=params,
                    )
                    result.raise_for_status()
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(result.content)
                    return out_path

            raise RuntimeError("ComfyUI finished without returning an image")

    raise TimeoutError("ComfyUI image generation timed out")
