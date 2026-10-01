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
