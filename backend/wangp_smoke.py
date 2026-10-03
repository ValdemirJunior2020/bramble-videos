from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WANGP_ROOT", Path(__file__).resolve().parents[1] / "runtime" / "WanGP")).resolve()
OUT = Path(__file__).resolve().parents[1] / "storage" / "wangp-smoke"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

# Match the exact conservative AMD path used by the persistent Bramble bridge.
# This must be set before WanGP imports torch-backed attention code.
os.environ["TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL"] = "0"
os.environ["WANGP_AMD_SAFE_SDPA"] = "1"

import torch  # noqa: E402

torch.backends.cuda.enable_flash_sdp(False)
torch.backends.cuda.enable_mem_efficient_sdp(False)
torch.backends.cuda.enable_math_sdp(True)

if torch.cuda.is_available() and "9060" in torch.cuda.get_device_name(0):
    if not torch.__version__.startswith("2.12.0+rocm7.14.0"):
        raise SystemExit(
            f"RX 9060 XT compatibility check failed: found {torch.__version__}; "
            "expected PyTorch 2.12.0+rocm7.14.0. Run INSTALL.bat."
        )

from shared.api import init  # noqa: E402

session = init(root=ROOT, output_dir=OUT, cli_args=["--attention", "sdpa", "--profile", "4"], console_output=True)
models = session.list_model_metadata(main_output="video", include_availability=True)
if not models:
    raise SystemExit("No WanGP video models are registered.")

def available(m):
    a = m.get("availability") or {}
    if isinstance(a, bool):
        return a
    return bool(a.get("available", a.get("ready", a.get("installed", True))))

ready = [m for m in models if available(m)]
if not ready:
    raise SystemExit("No WanGP video model is locally available. Open Bramble after install and install a supported model.")

def model_text(m):
    return " ".join(str(m.get(k, "") or "").lower() for k in ("family", "name", "model_type", "description"))

gfx1200 = torch.cuda.is_available() and (
    "9060" in torch.cuda.get_device_name(0)
    or "gfx1200" in str(getattr(torch.cuda.get_device_properties(0), "gcnArchName", "") or "")
)
pool = [m for m in ready if "ltx" not in model_text(m)] if gfx1200 else ready
pool = pool or ready

def rank(m):
    text = model_text(m)
    score = 0
    if gfx1200:
        if "1.3b" in text:
            score -= 80
        if "wan" in text:
            score -= 40
        if "ltx" in text:
            score += 500
    else:
        if "ltx" in text and "distill" in text:
            score -= 30
    return (score, str(m.get("name") or m.get("model_type") or ""))

model_type = str(sorted(pool, key=rank)[0]["model_type"])
settings = session.get_default_settings(model_type)
settings.update({
    "model_type": model_type,
    "prompt": "A cinematic sunrise over a peaceful meadow, slow camera push forward.",
    "duration_seconds": 2,
    "video_length": "2s",
    "seed": 20261001,
    "override_profile": 4,
    "override_attention": "sdpa",
})
steps = int(settings.get("num_inference_steps") or 0)
if steps:
    settings["num_inference_steps"] = max(4, min(steps, 6))

print("Model:", model_type)
job = session.submit_task(settings)
for event in job.events.iter(timeout=0.25):
    if event.kind == "progress":
        p = event.data
        print(f"{p.phase}: {p.progress}% {p.status}")
result = job.result()
if not result.success or not result.generated_files:
    for error in result.errors:
        print("ERROR:", error.message)
    raise SystemExit(1)
path = Path(result.generated_files[-1])
if not path.exists() or path.suffix.lower() != ".mp4":
    raise SystemExit(f"Expected an MP4, got: {path}")
print("SMOKE TEST PASSED:", path)
