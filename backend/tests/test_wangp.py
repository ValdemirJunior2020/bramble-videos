from app.generation.presets import apply_preset, split_duration, target_resolution
from app.models import ProjectCreate, Scene


def test_wangp_is_default_generator():
    request = ProjectCreate(title="x", script="A short test scene.")
    assert request.generation_engine == "wangp"
    assert request.generation_preset == "balanced"


def test_rx9060_safe_native_sizes():
    assert target_resolution("16:9") == (832, 480)
    assert target_resolution("9:16") == (480, 832)
    assert max(target_resolution("1:1")) <= 640


def test_long_scene_splits_without_losing_duration():
    shots = split_duration(13.0, max_shot_seconds=6.0)
    assert shots == [6.0, 6.0, 1.0]
    assert sum(shots) == 13.0


def test_preset_changes_real_inference_steps():
    defaults = {"num_inference_steps": 8}
    assert apply_preset(defaults, "fast")["num_inference_steps"] < 8
    assert apply_preset(defaults, "high")["num_inference_steps"] > 8
    assert apply_preset(defaults, "balanced")["override_profile"] == 4
    assert apply_preset(defaults, "balanced")["override_attention"] == "sdpa"


def test_scene_generation_state_is_persistable():
    scene = Scene(scene_number=1, narration="hello")
    scene.generation_state = "complete"
    scene.seed = 1234
    scene.clip_path = "clip.mp4"
    restored = Scene.model_validate_json(scene.model_dump_json())
    assert restored.generation_state == "complete"
    assert restored.seed == 1234
    assert restored.clip_path == "clip.mp4"


def test_wangp_scene_request_to_real_output_path(tmp_path):
    import asyncio
    from pathlib import Path
    from app.generation.wangp import WanGPService
    from app.models import Project

    service = WanGPService()
    captured = {}

    async def fake_request(method, path, **kwargs):
        if method == "POST" and path == "/generate":
            captured.update(kwargs["json"])
            return {"job_id": "job-1"}
        if method == "GET" and path == "/jobs/job-1":
            output = Path(captured["output_path"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"fake-mp4-for-adapter-test")
            return {
                "state": "complete",
                "phase": "Scene complete",
                "progress": 100,
                "seed": 12345,
                "output_path": str(output),
            }
        raise AssertionError((method, path))

    service._request = fake_request
    project = Project(id="p1", title="Test", script="Hello", language="en", aspect="16:9")
    scene = Scene(
        scene_number=1,
        narration="Hello",
        image_prompt="A cinematic meadow, slow dolly forward",
        duration_seconds=3.0,
    )
    outputs = asyncio.run(service.generate_scene(project, scene, tmp_path))
    assert outputs == [tmp_path / "clip.mp4"]
    assert captured["duration_seconds"] == 3.0
    assert captured["resolution"] == "832x480"
    assert captured["preset"] == "balanced"
    assert scene.seed == 12345
    assert scene.generation_state == "complete"
    assert (tmp_path / "settings-01.json").exists()
