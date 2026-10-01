from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WANGP_ROOT", Path(__file__).resolve().parents[1] / "runtime" / "WanGP")).resolve()
OUT = Path(__file__).resolve().parents[1] / "storage" / "wangp-smoke"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

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

preferred = [m for m in ready if "ltx" in str(m.get("family", "")).lower() and "distill" in (str(m.get("name", "")) + str(m.get("model_type", ""))).lower()]
model_type = str((preferred or ready)[0]["model_type"])
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
