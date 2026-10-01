from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from ..assets import find_asset
from ..config import settings
from ..models import Project, Scene
from .presets import split_duration, target_resolution


class WanGPError(RuntimeError):
    pass


class WanGPService:
    def __init__(self) -> None:
        self.base_url = settings.wangp_bridge_url.rstrip("/")

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 30.0)) as client:
                response = await client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.RequestError as exc:
            raise WanGPError("WanGP bridge is offline. Run START.bat or verify WANGP_ROOT.") from exc
        if response.status_code >= 400:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            raise WanGPError(str(detail))
        return response.json()

    async def health(self) -> dict:
        try:
            return await self._request("GET", "/health", timeout=4.0)
        except Exception as exc:
            return {"installed": False, "ready": False, "error": str(exc)}

    async def list_models(self) -> list[dict]:
        data = await self._request("GET", "/models", timeout=30.0)
        return data.get("models", [])

    async def model_schema(self, model_type: str) -> dict:
        return await self._request("GET", f"/models/{model_type}/schema")

    async def default_settings(self, model_type: str) -> dict:
        return await self._request("GET", f"/models/{model_type}/defaults")

    async def cancel(self, job_id: str) -> None:
        await self._request("POST", f"/jobs/{job_id}/cancel")

    def _references(self, scene: Scene) -> list[str]:
        refs: list[str] = []
        for name in scene.characters:
            asset = find_asset(name)
            if not asset or not asset.identity_lock:
                continue
            ordered = []
            if asset.primary_image_path:
                ordered.append(asset.primary_image_path)
            ordered.extend(asset.image_paths)
            for value in ordered:
                path = Path(value)
                if path.exists() and str(path.resolve()) not in refs:
                    refs.append(str(path.resolve()))
        return refs[:5]

    async def generate_scene(self, project: Project, scene: Scene, out_dir: Path, *, seed: int | None = None, new_seed: bool = False, on_update=None) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        durations = split_duration(scene.duration_seconds)
        outputs: list[Path] = []
        refs = self._references(scene)
        base_seed = -1 if new_seed else (seed if seed is not None else scene.seed)
        for shot_index, duration in enumerate(durations, 1):
            target = out_dir / (f"clip-{shot_index:02d}.mp4" if len(durations) > 1 else "clip.mp4")
            width, height = target_resolution(project.aspect, project.custom_width, project.custom_height)
            prompt = scene.image_prompt.strip()
            if len(durations) > 1:
                prompt += f"\nContinuity shot {shot_index} of {len(durations)}. Preserve the same characters, clothing, location, lighting and visual style. Advance the action naturally without a reset."
            payload = {
                "model_type": project.generation_model or settings.wangp_default_model,
                "prompt": prompt,
                "negative_prompt": scene.negative_prompt,
                "duration_seconds": duration,
                "resolution": f"{width}x{height}",
                "seed": base_seed if base_seed is not None else -1,
                "preset": project.generation_preset,
                "references": refs,
                "consistency_lock": project.consistency_lock and bool(scene.characters),
                "output_path": str(target.resolve()),
            }
            (out_dir / f"prompt-{shot_index:02d}.json").write_text(json.dumps({"prompt": prompt, "negative_prompt": scene.negative_prompt, "references": refs}, indent=2), encoding="utf-8")
            (out_dir / f"settings-{shot_index:02d}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            data = await self._request("POST", "/generate", json=payload, timeout=30.0)
            job_id = data["job_id"]
            scene.generation_job_id = job_id
            scene.generation_state = "generating"
            while True:
                status = await self._request("GET", f"/jobs/{job_id}", timeout=15.0)
                scene.generation_phase = status.get("phase") or status.get("status") or "Generating"
                scene.generation_progress = int(status.get("progress") or 0)
                scene.generation_current_step = status.get("current_step")
                scene.generation_total_steps = status.get("total_steps")
                scene.preview_path = status.get("preview_path") or scene.preview_path
                if status.get("seed") is not None:
                    scene.seed = int(status["seed"])
                if on_update is not None:
                    on_update()
                if status["state"] in {"complete", "failed", "cancelled"}:
                    if status["state"] != "complete":
                        scene.generation_state = status["state"]
                        raise WanGPError(status.get("error") or f"WanGP generation {status['state']}")
                    break
                await asyncio.sleep(1.0)
            produced = Path(status.get("output_path") or target)
            if not produced.exists():
                raise WanGPError("WanGP reported success but the generated video file was not found.")
            payload["seed"] = scene.seed
            (out_dir / f"settings-{shot_index:02d}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            if base_seed is None or base_seed < 0:
                base_seed = scene.seed
            outputs.append(produced)
        scene.generation_state = "complete"
        scene.generation_progress = 100
        return outputs


wangp_service = WanGPService()
