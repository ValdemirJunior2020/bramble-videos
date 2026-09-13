from app.planner import segment_script, segment_script_with_sections


def test_segment_preserves_words():
    source = "Grace walked to the gate. Pip followed her quickly. They stopped and looked at the vines. Bramble smiled from the path."
    scenes = segment_script(source, target_words=8, max_words=12)
    assert " ".join(scenes) == source
    assert len(scenes) >= 2


def test_detects_english_reflection_sections_without_speaking_headings():
    source = (
        "Grace and Pip walked home together.\n"
        "Heart Lesson\n"
        "Big jobs become easier when we slow down.\n"
        "For Parents: Why This Story Matters\n"
        "Children learn patience through small repeated choices."
    )
    items = segment_script_with_sections(source)
    assert [x["section_type"] for x in items] == ["story", "heart_lesson", "parents"]
    assert all("Heart Lesson" not in x["text"] for x in items)
    assert all("For Parents" not in x["text"] for x in items)


def test_detects_portuguese_reflection_sections():
    source = (
        "Grace e Pip voltaram para casa.\n"
        "**Lição para o Coração**\n"
        "Um trabalho grande fica mais leve quando vamos devagar.\n"
        "**Para os Pais: Por Que Esta História é Importante**\n"
        "As crianças aprendem com pequenas escolhas repetidas."
    )
    items = segment_script_with_sections(source)
    assert [x["section_type"] for x in items] == ["story", "heart_lesson", "parents"]
    assert items[1]["section_label"] == "Lição para o Coração"
    assert items[2]["section_label"].startswith("Para os Pais")
