from app.planner import segment_script

def test_segment_preserves_words():
    source = "Grace walked to the gate. Pip followed her quickly. They stopped and looked at the vines. Bramble smiled from the path."
    scenes = segment_script(source, target_words=8, max_words=12)
    assert " ".join(scenes) == source
    assert len(scenes) >= 2
