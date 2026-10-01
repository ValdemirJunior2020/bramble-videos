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
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
WANGP_ROOT = Path(os.environ.get("WANGP_ROOT", REPO_ROOT / "runtime" / "WanGP")).expanduser().resolve()
OUTPUT_ROOT = Path(os.environ.get("WANGP_OUTPUT_DIR", REPO_ROOT / "storage" / "wangp")).expanduser().resolve()
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
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
    references: list[str] = []
    consistency_lock: bool = False
    output_path: str


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(WANGP_ROOT), "rev-parse", "HEAD"], text=True, timeout=3).strip()
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
        from shared.api import init
        profile = os.environ.get("WANGP_MEMORY_PROFILE", "4")
        attention = os.environ.get("WANGP_ATTENTION", "sdpa")
        _session = init(root=WANGP_ROOT, output_dir=OUTPUT_ROOT, cli_args=["--attention", attention, "--profile", profile], console_output=True)
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


def _pick_model(session, requested: str) -> str:
    if requested:
        return requested
    env_model = os.environ.get("WANGP_DEFAULT_MODEL", "").strip()
    if env_model:
        return env_model
    models = session.list_model_metadata(main_output="video", include_availability=True)
    ready = [m for m in models if _availability_ready(m)]
    if not ready:
        raise RuntimeError("No locally available WanGP video model was found. Install a video model in WanGP first.")
    # Prefer a fast general-purpose LTX distilled model when present, then use the
    # first available video model reported by WanGP.
    preferred = [m for m in ready if "ltx" in str(m.get("family", "")).lower() and "distill" in (str(m.get("name", "")) + str(m.get("model_type", ""))).lower()]
    return str((preferred or ready)[0].get("model_type") or "")


def _build_settings(session, req: GenerateRequest) -> tuple[dict, dict]:
    model_type = _pick_model(session, req.model_type)
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
            _set_job(job_id, state="generating", status="Preparing", phase="Preparing", progress=1, model_type=settings["model_type"], settings=settings, schema=schema, seed=settings.get("seed"))

            class Callbacks:
                def on_progress(self, update):
                    _set_job(job_id, phase=_phase_label(update), status=str(getattr(update, "status", "") or "Generating"), progress=int(getattr(update, "progress", 0) or 0), current_step=getattr(update, "current_step", None), total_steps=getattr(update, "total_steps", None))
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
                _set_job(job_id, state=state, error=message, progress=0)
                return
            generated = [Path(p) for p in result.generated_files if Path(p).exists()]
            if not generated:
                raise RuntimeError("WanGP completed without a generated media file.")
            source = generated[-1]
            target = Path(req.output_path).resolve(); target.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target:
                shutil.copy2(source, target)
            _set_job(job_id, state="complete", status="Scene complete", phase="Scene complete", progress=100, output_path=str(target), generated_files=[str(p) for p in generated])
    except Exception as exc:
        _set_job(job_id, state="failed", error=str(exc), traceback=traceback.format_exc())
    finally:
        _model_status = "Loaded" if _active_model else "Idle"
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].pop("native_job", None)


@app.get("/health")
def health():
    installed = (WANGP_ROOT / "shared" / "api.py").exists()
    info = {"installed": installed, "ready": False, "root": str(WANGP_ROOT), "commit": _git_commit(), "attention": os.environ.get("WANGP_ATTENTION", "sdpa"), "memory_profile": os.environ.get("WANGP_MEMORY_PROFILE", "4"), "active_model": _active_model, "model_status": _model_status, "session": "Connected" if _session is not None else "Offline"}
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
