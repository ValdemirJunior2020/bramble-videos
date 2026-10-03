from __future__ import annotations

import os
import shutil
import secrets
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
WANGP_ROOT = Path(os.environ.get("WANGP_ROOT", REPO_ROOT / "runtime" / "WanGP")).expanduser().resolve()
OUTPUT_ROOT = Path(os.environ.get("WANGP_OUTPUT_DIR", REPO_ROOT / "storage" / "wangp")).expanduser().resolve()
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
DIAGNOSTIC_ROOT = REPO_ROOT / "storage" / "diagnostics"
DIAGNOSTIC_ROOT.mkdir(parents=True, exist_ok=True)
if str(WANGP_ROOT) not in sys.path:
    sys.path.insert(0, str(WANGP_ROOT))

app = FastAPI(title="Bramble WanGP Bridge", version="1.0")
_session = None
_session_lock = threading.Lock()
_gpu_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_active_model = ""
_model_status = "Idle"


class GenerateRequest(BaseModel):
    model_type: str = ""
    prompt: str
    negative_prompt: str = ""
    duration_seconds: float = 4.0
    resolution: str = "832x480"
    seed: int = -1
    preset: str = "balanced"
    references: list[str] = Field(default_factory=list)
    consistency_lock: bool = False
    output_path: str
    image_start: str = ""
    image_end: str = ""
    video_source: str = ""
    video_guide: str = ""
    overrides: dict = Field(default_factory=dict)


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(WANGP_ROOT), "rev-parse", "HEAD"], text=True, timeout=3).strip()
    except Exception:
        return ""


def _is_gfx1200() -> bool:
    try:
        import torch
        if not torch.cuda.is_available():
            return False
        name = str(torch.cuda.get_device_name(0) or "").lower()
        props = torch.cuda.get_device_properties(0)
        arch = str(getattr(props, "gcnArchName", "") or getattr(props, "gcn_arch_name", "") or "").lower()
        return "9060" in name or "gfx1200" in arch
    except Exception:
        return False


def _model_text(record: dict) -> str:
    return " ".join(
        str(record.get(k, "") or "").lower()
        for k in ("family", "name", "model_type", "description")
    )


def _gpu_snapshot() -> dict:
    data = {}
    try:
        import torch
        data["torch"] = torch.__version__
        data["hip"] = getattr(torch.version, "hip", None)
        data["gpu_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            data["gpu_name"] = torch.cuda.get_device_name(0)
            data["architecture"] = str(getattr(props, "gcnArchName", "") or getattr(props, "gcn_arch_name", "") or "")
            data["vram_total_gb"] = round(props.total_memory / 1024**3, 3)
            data["vram_allocated_gb"] = round(torch.cuda.memory_allocated(0) / 1024**3, 3)
            data["vram_reserved_gb"] = round(torch.cuda.memory_reserved(0) / 1024**3, 3)
    except Exception as exc:
        data["gpu_snapshot_error"] = str(exc)
    return data


def _write_diagnostic(job_id: str, payload: dict) -> str:
    import json
    path = DIAGNOSTIC_ROOT / f"{job_id}.json"
    try:
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return str(path)
    except Exception:
        return ""


def _init_session():
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is not None:
            return _session
        if not (WANGP_ROOT / "shared" / "api.py").exists():
            raise RuntimeError(f"WanGP is not installed at {WANGP_ROOT}")
        # On Windows ROCm / RDNA4 gfx1200, WanGP currently has an upstream
        # regression where experimental AOTriton / flash SDPA can fail with
        # hipErrorLaunchFailure or hipErrorInvalidValue. Force the conservative
        # PyTorch math SDPA backend when Bramble safe mode is enabled.
        if os.environ.get("WANGP_AMD_SAFE_SDPA", "0") == "1":
            os.environ["TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL"] = "0"
            import torch
            try:
                torch.backends.cuda.enable_flash_sdp(False)
            except Exception:
                pass
            try:
                torch.backends.cuda.enable_mem_efficient_sdp(False)
            except Exception:
                pass
            try:
                torch.backends.cuda.enable_math_sdp(True)
            except Exception:
                pass
        from shared.api import init
        profile = os.environ.get("WANGP_MEMORY_PROFILE", "4")
        attention = os.environ.get("WANGP_ATTENTION", "sdpa")
        cli_args = ["--attention", attention, "--profile", profile]
        # WanGP's emergency AMD fallback uses FP16 with SDPA/profile 4.
        # Keep this scoped to gfx1200 so other GPUs retain upstream defaults.
        if _is_gfx1200():
            cli_args.append("--fp16")
        _session = init(root=WANGP_ROOT, output_dir=OUTPUT_ROOT, cli_args=cli_args, console_output=True)
        return _session


def _availability_ready(record: dict) -> bool:
    availability = record.get("availability") or {}
    if isinstance(availability, bool):
        return availability
    for key in ("available", "ready", "installed", "complete"):
        if key in availability:
            return bool(availability[key])
    # If upstream omits availability details, keep the model visible; generation will
    # return the real download/missing-file error instead of hiding it.
    return True


def _model_image_roles(session, model_type: str, record: dict | None = None) -> dict:
    record = record or {}
    media = (record.get("media_inputs") or {}).get("image") or {}
    if media:
        return media
    try:
        schema = session.get_model_schema(model_type) or {}
        metadata = schema.get("metadata", schema)
        return ((metadata.get("media_inputs") or {}).get("image") or {})
    except Exception:
        return {}


def _supports_reference_images(session, model_type: str, record: dict | None = None) -> bool:
    media = _model_image_roles(session, model_type, record)
    return bool(
        media.get("reference")
        or media.get("single_reference")
        or media.get("multiple_references")
        or media.get("start")
    )


def _pick_model(session, requested: str, require_reference: bool = False) -> str:
    models = session.list_model_metadata(main_output="video", include_availability=True)
    if not models:
        raise RuntimeError("WanGP did not report any video models.")

    def compatible(record: dict) -> bool:
        model_type = str(record.get("model_type") or "")
        return bool(model_type) and (not require_reference or _supports_reference_images(session, model_type, record))

    compatible_models = [m for m in models if compatible(m)]

    # LTX-2 currently has a known WanGP/ROCm gfx1200 failure path on RX 9060 XT.
    # On this GPU, keep LTX out of automatic/selected generation and prefer
    # the smaller Wan 1.3B family recommended by WanGP's fallback guidance.
    if _is_gfx1200():
        non_ltx = [m for m in compatible_models if "ltx" not in _model_text(m)]
        if non_ltx:
            compatible_models = non_ltx

    if not compatible_models:
        if require_reference:
            raise RuntimeError(
                "Consistency Lock needs a WanGP video model that supports reference/start images, "
                "but WanGP did not report any compatible video model."
            )
        raise RuntimeError("WanGP did not report a compatible video model.")

    # Respect an explicitly selected model only when it can satisfy the scene.
    if requested:
        selected = next((m for m in compatible_models if str(m.get("model_type") or "") == requested), None)
        if selected is not None:
            return requested

    env_model = os.environ.get("WANGP_DEFAULT_MODEL", "").strip()
    if env_model:
        selected = next((m for m in compatible_models if str(m.get("model_type") or "") == env_model), None)
        if selected is not None:
            return env_model

    # Prefer models whose files are already present, but DO NOT require local
    # availability. WanGP downloads architecture-appropriate model files on demand.
    ready = [m for m in compatible_models if _availability_ready(m)]
    pool = ready or compatible_models

    # Prefer lighter/faster families first on a 16 GB local GPU, while still
    # honoring reference-image capability when Consistency Lock is enabled.
    gfx1200 = _is_gfx1200()

    def rank(record: dict) -> tuple:
        text = _model_text(record)
        preferred = 0
        if gfx1200:
            if "1.3b" in text:
                preferred -= 80
            if "wan" in text:
                preferred -= 40
            if "distill" in text or "fast" in text:
                preferred -= 15
            if "ltx" in text:
                preferred += 500
        else:
            if "ltx" in text:
                preferred -= 30
            if "distill" in text or "fast" in text:
                preferred -= 20
            if "1.3b" in text:
                preferred -= 10
        availability_penalty = 0 if _availability_ready(record) else 100
        return (availability_penalty + preferred, str(record.get("name") or record.get("model_type") or ""))

    return str(sorted(pool, key=rank)[0].get("model_type") or "")


def _build_settings(session, req: GenerateRequest) -> tuple[dict, dict]:
    refs_present = any(Path(p).exists() for p in req.references)
    model_type = _pick_model(session, req.model_type, require_reference=bool(req.consistency_lock and refs_present))
    schema = session.get_model_schema(model_type) or {}
    metadata = schema.get("metadata", schema)
    defaults = dict(session.get_default_settings(model_type) or {})
    defaults["model_type"] = model_type
    defaults["prompt"] = req.prompt
    defaults["negative_prompt"] = req.negative_prompt
    defaults["resolution"] = req.resolution
    defaults["duration_seconds"] = float(req.duration_seconds)
    defaults["video_length"] = f"{float(req.duration_seconds):.2f}s"
    resolved_seed = int(req.seed) if int(req.seed) >= 0 else secrets.randbelow(2_147_483_647)
    defaults["seed"] = resolved_seed
    defaults["override_profile"] = int(os.environ.get("WANGP_MEMORY_PROFILE", "4"))
    defaults["override_attention"] = os.environ.get("WANGP_ATTENTION", "sdpa")

    # Keep the RDNA4 fallback conservative even if the UI sends a heavier preset.
    if _is_gfx1200():
        defaults["override_profile"] = 4

    if req.preset == "max":
        try:
            import torch
            total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3 if torch.cuda.is_available() else 0
        except Exception:
            total_gb = 0
        if total_gb < 15.0:
            raise RuntimeError("Maximum Local Quality requires at least 15 GB of detected VRAM. Choose High Quality or Balanced Cinematic.")

    steps = int(defaults.get("num_inference_steps") or 0)
    scale = {"fast": 0.65, "balanced": 1.0, "high": 1.25, "max": 1.45}.get(req.preset, 1.0)
    if steps:
        defaults["num_inference_steps"] = max(4, min(steps + 12, round(steps * scale)))

    safe_override_keys = {
        "num_inference_steps", "force_fps", "guidance_scale", "guidance2_scale",
        "guidance3_scale", "embedded_guidance_scale", "flow_shift", "motion_amplitude",
        "temporal_upsampling", "spatial_upsampling", "prompt_enhancer", "sample_solver",
    }
    for key, value in req.overrides.items():
        if key in safe_override_keys and value not in (None, ""):
            defaults[key] = value

    if _is_gfx1200():
        # Avoid optional post-process / upsampling passes that can push a 16 GB
        # RDNA4 card over the edge after the main diffusion allocation.
        defaults["temporal_upsampling"] = False
        defaults["spatial_upsampling"] = False
        if defaults.get("num_inference_steps"):
            defaults["num_inference_steps"] = min(int(defaults["num_inference_steps"]), 20)

    def media_path(value: str) -> str:
        if not value:
            return ""
        path = Path(value).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f"Media input was not found: {path.name}")
        return str(path)

    image_meta = (metadata.get("media_inputs") or {}).get("image") or {}
    video_meta = (metadata.get("media_inputs") or {}).get("video") or {}
    start = media_path(req.image_start)
    end = media_path(req.image_end)
    source_video = media_path(req.video_source)
    control_video = media_path(req.video_guide)

    if start:
        if not image_meta.get("start"):
            raise RuntimeError(f"Selected model '{model_type}' does not support start-frame image-to-video.")
        defaults["image_start"] = start
    if end:
        if not image_meta.get("end"):
            raise RuntimeError(f"Selected model '{model_type}' does not support end-frame guidance.")
        defaults["image_end"] = end
    if source_video:
        if not video_meta.get("continue"):
            raise RuntimeError(f"Selected model '{model_type}' does not support video continuation/source-video input.")
        defaults["video_source"] = source_video
    if control_video:
        if not video_meta.get("control"):
            raise RuntimeError(f"Selected model '{model_type}' does not support control-video guidance.")
        setting_values = metadata.get("setting_values") or {}
        prompt_values = setting_values.get("video_prompt_type") or {}
        choice_groups = (
            prompt_values.get("guide_preprocessing"),
            prompt_values.get("guide_custom_choices"),
            prompt_values.get("custom_video_selection"),
        )
        chosen = ""
        for group in choice_groups:
            if not isinstance(group, dict):
                continue
            for choice in group.get("choices") or []:
                value = str(choice.get("value", "") if isinstance(choice, dict) else "")
                if "V" in value:
                    chosen = value
                    break
            if chosen:
                break
        if not chosen:
            raise RuntimeError(f"Selected model '{model_type}' reports control-video capability but no compatible control mode was exposed.")
        defaults["video_guide"] = control_video
        defaults["video_prompt_type"] = chosen

    refs = [str(Path(p).resolve()) for p in req.references if Path(p).exists()]
    media = (metadata.get("media_inputs") or {}).get("image") or {}
    if refs:
        if media.get("reference") or media.get("single_reference") or media.get("multiple_references"):
            if media.get("single_reference") and not media.get("multiple_references"):
                refs = refs[:1]
            defaults["image_refs"] = refs
        elif media.get("start"):
            defaults["image_start"] = refs[0]
        elif req.consistency_lock:
            raise RuntimeError(f"Selected model '{model_type}' does not support a reference-image role required by Consistency Lock.")
    elif req.consistency_lock:
        raise RuntimeError("Missing approved character reference for this scene.")
    return defaults, schema




def _phase_label(update) -> str:
    phase = str(getattr(update, "phase", "") or "").strip().lower()
    raw = str(getattr(update, "raw_phase", "") or "").strip()
    labels = {
        "loading_model": "Loading model",
        "encoding_text": "Encoding prompt",
        "inference": raw or "Generating",
        "decoding": "Decoding video",
        "downloading_output": "Post-processing",
        "cancelled": "Cancelled",
    }
    return labels.get(phase, raw or str(getattr(update, "phase", "") or "Generating"))

def _set_job(job_id: str, **values):
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(values)


def _run_generation(job_id: str, req: GenerateRequest):
    global _active_model, _model_status
    active_job = None
    try:
        with _gpu_lock:
            with _jobs_lock:
                if (_jobs.get(job_id) or {}).get("state") == "cancelled":
                    return
            session = _init_session()
            settings, schema = _build_settings(session, req)
            _active_model = settings["model_type"]
            _model_status = "Generating"
            diagnostic = {
                "job_id": job_id,
                "started_at": time.time(),
                "wangp_commit": _git_commit(),
                "model_type": settings.get("model_type"),
                "preset": req.preset,
                "resolution": settings.get("resolution"),
                "duration_seconds": settings.get("duration_seconds"),
                "video_length": settings.get("video_length"),
                "num_inference_steps": settings.get("num_inference_steps"),
                "override_profile": settings.get("override_profile"),
                "override_attention": settings.get("override_attention"),
                "seed": settings.get("seed"),
                "env": {
                    "AMD_SERIALIZE_KERNEL": os.environ.get("AMD_SERIALIZE_KERNEL"),
                    "HIP_LAUNCH_BLOCKING": os.environ.get("HIP_LAUNCH_BLOCKING"),
                    "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL": os.environ.get("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL"),
                    "WANGP_AMD_SAFE_SDPA": os.environ.get("WANGP_AMD_SAFE_SDPA"),
                },
                "gpu_before": _gpu_snapshot(),
                "last_phase": "Preparing",
                "last_status": "Preparing WanGP model",
                "last_progress": 0,
            }
            diagnostic_path = _write_diagnostic(job_id, diagnostic)
            _set_job(job_id, diagnostic_log=diagnostic_path)
            try:
                availability = session.get_model_availability(settings["model_type"]) or {}
            except Exception:
                availability = {}
            is_local = _availability_ready({"availability": availability})
            initial_phase = "Preparing" if is_local else "Downloading model"
            initial_status = "Preparing WanGP model" if is_local else "First run: WanGP is downloading the required video model files"
            _set_job(job_id, state="generating", status=initial_status, phase=initial_phase, progress=1, model_type=settings["model_type"], settings=settings, schema=schema, seed=settings.get("seed"))

            class Callbacks:
                def on_progress(self, update):
                    phase = _phase_label(update)
                    status = str(getattr(update, "status", "") or "Generating")
                    progress = int(getattr(update, "progress", 0) or 0)
                    current_step = getattr(update, "current_step", None)
                    total_steps = getattr(update, "total_steps", None)
                    _set_job(job_id, phase=phase, status=status, progress=progress, current_step=current_step, total_steps=total_steps)
                    diagnostic["last_phase"] = phase
                    diagnostic["last_status"] = status
                    diagnostic["last_progress"] = progress
                    diagnostic["current_step"] = current_step
                    diagnostic["total_steps"] = total_steps
                    diagnostic["gpu_last_progress"] = _gpu_snapshot()
                    _write_diagnostic(job_id, diagnostic)
                def on_status(self, text):
                    _set_job(job_id, status=str(text or ""))
                def on_preview(self, preview):
                    preview_dir = OUTPUT_ROOT / "previews"; preview_dir.mkdir(parents=True, exist_ok=True)
                    if getattr(preview, "video", None):
                        path = preview_dir / f"{job_id}.mp4"; path.write_bytes(preview.video); _set_job(job_id, preview_path=str(path))
                    elif getattr(preview, "image", None) is not None:
                        path = preview_dir / f"{job_id}.png"; preview.image.save(path); _set_job(job_id, preview_path=str(path))
                def on_stream(self, message):
                    text = str(getattr(message, "text", "") or "").strip()
                    if not text:
                        return
                    lowered = text.lower()
                    if "download" in lowered:
                        _set_job(job_id, phase="Downloading model", status=text)
                    elif any(word in lowered for word in ("loading", "checkpoint", "model")):
                        _set_job(job_id, status=text)
                def on_info(self, text):
                    value = str(text or "").strip()
                    if value:
                        _set_job(job_id, status=value)
                def on_error(self, error):
                    _set_job(job_id, error=str(getattr(error, "message", error)))

            active_job = session.submit_task(settings, callbacks=Callbacks())
            _set_job(job_id, native_job=active_job)
            result = active_job.result()
            if not result.success:
                message = "; ".join(str(getattr(e, "message", e)) for e in result.errors) or "WanGP generation failed."
                state = "cancelled" if getattr(result, "cancelled", False) or getattr(active_job, "cancel_requested", False) else "failed"
                diagnostic["finished_at"] = time.time()
                diagnostic["state"] = state
                diagnostic["error"] = message
                diagnostic["gpu_after_failure"] = _gpu_snapshot()
                diagnostic_path = _write_diagnostic(job_id, diagnostic)
                _set_job(job_id, state=state, error=message, progress=0, diagnostic_log=diagnostic_path)
                return
            generated = [Path(p) for p in result.generated_files if Path(p).exists()]
            if not generated:
                raise RuntimeError("WanGP completed without a generated media file.")
            source = generated[-1]
            target = Path(req.output_path).resolve(); target.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target:
                shutil.copy2(source, target)
            diagnostic["finished_at"] = time.time()
            diagnostic["state"] = "complete"
            diagnostic["output_path"] = str(target)
            diagnostic["gpu_after"] = _gpu_snapshot()
            diagnostic_path = _write_diagnostic(job_id, diagnostic)
            _set_job(job_id, state="complete", status="Scene complete", phase="Scene complete", progress=100, output_path=str(target), generated_files=[str(p) for p in generated], diagnostic_log=diagnostic_path)
    except Exception as exc:
        tb = traceback.format_exc()
        failure = {
            "job_id": job_id,
            "finished_at": time.time(),
            "state": "failed",
            "error": str(exc),
            "traceback": tb,
            "active_model": _active_model,
            "gpu_after_failure": _gpu_snapshot(),
            "env": {
                "AMD_SERIALIZE_KERNEL": os.environ.get("AMD_SERIALIZE_KERNEL"),
                "HIP_LAUNCH_BLOCKING": os.environ.get("HIP_LAUNCH_BLOCKING"),
                "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL": os.environ.get("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL"),
                "WANGP_AMD_SAFE_SDPA": os.environ.get("WANGP_AMD_SAFE_SDPA"),
            },
        }
        with _jobs_lock:
            previous = dict(_jobs.get(job_id) or {})
        failure["last_phase"] = previous.get("phase")
        failure["last_status"] = previous.get("status")
        failure["last_progress"] = previous.get("progress")
        failure["current_step"] = previous.get("current_step")
        failure["total_steps"] = previous.get("total_steps")
        diagnostic_path = _write_diagnostic(job_id, failure)
        _set_job(job_id, state="failed", error=str(exc), traceback=tb, diagnostic_log=diagnostic_path)
    finally:
        _model_status = "Loaded" if _active_model else "Idle"
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].pop("native_job", None)


@app.get("/health")
def health():
    installed = (WANGP_ROOT / "shared" / "api.py").exists()
    info = {"installed": installed, "ready": False, "root": str(WANGP_ROOT), "commit": _git_commit(), "attention": os.environ.get("WANGP_ATTENTION", "sdpa"), "attention_backend": "math-sdpa-safe" if os.environ.get("WANGP_AMD_SAFE_SDPA", "0") == "1" else "default", "memory_profile": os.environ.get("WANGP_MEMORY_PROFILE", "4"), "active_model": _active_model, "model_status": _model_status, "session": "Connected" if _session is not None else "Offline"}
    try:
        import torch
        info["pytorch"] = torch.__version__
        info["gpu_accelerated"] = bool(torch.cuda.is_available())
        info["gpu_name"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""
        info["rocm"] = getattr(torch.version, "hip", None) or ""
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            info["vram_gb"] = round(props.total_memory / 1024**3, 1)
            info["architecture"] = str(getattr(props, "gcnArchName", "") or getattr(props, "gcn_arch_name", "") or ("gfx1200" if "9060" in info["gpu_name"] else ""))
        if installed:
            _init_session(); info["ready"] = True; info["session"] = "Connected"
    except Exception as exc:
        info["error"] = str(exc)
    return info


@app.get("/models")
def models():
    try:
        session = _init_session()
        return {"models": session.list_model_metadata(main_output="video", include_availability=True)}
    except Exception as exc:
        raise HTTPException(503, str(exc))


@app.get("/models/{model_type}/schema")
def model_schema(model_type: str):
    try:
        return _init_session().get_model_schema(model_type) or {}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.get("/models/{model_type}/defaults")
def defaults(model_type: str):
    try:
        return _init_session().get_default_settings(model_type) or {}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/generate")
def generate(req: GenerateRequest):
    job_id = uuid4().hex
    _set_job(job_id, state="pending", status="Queued", phase="Queued", progress=0, created_at=time.time(), output_path=req.output_path)
    threading.Thread(target=_run_generation, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    with _jobs_lock:
        job = dict(_jobs.get(job_id) or {})
    if not job:
        raise HTTPException(404, "WanGP job not found")
    job.pop("native_job", None)
    job.pop("settings", None)
    job.pop("schema", None)
    # Keep the UI concise, but leave the diagnostic JSON path visible so the exact
    # crash report can be inspected after a HIP kernel failure.
    job.pop("traceback", None)
    return job


@app.post("/jobs/{job_id}/cancel")
def cancel(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        native = job.get("native_job") if job else None
    if not job:
        raise HTTPException(404, "WanGP job not found")
    if native is not None and not native.done:
        native.cancel()
    _set_job(job_id, state="cancelled", status="Cancellation requested", phase="Cancelled")
    return {"ok": True}
