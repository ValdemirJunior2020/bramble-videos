from app.audio import split_voice_chunks


def test_explicit_character_dialogue():
    chunks = split_voice_chunks("Pip: Grace, look what I found! Grace: Slow down, Pip.", ["Pip", "Grace"])
    assert chunks == [("Pip", "Grace, look what I found!"), ("Grace", "Slow down, Pip.")]


def test_quoted_dialogue_uses_named_speaker():
    chunks = split_voice_chunks('Pip said, "Look at the gate!"', ["Pip", "Grace"])
    assert any(speaker == "Pip" and "Look at the gate!" in text for speaker, text in chunks)


def test_plain_narration_stays_narrator():
    chunks = split_voice_chunks("The morning sun warmed the Meadowood path.", ["Pip"])
    assert chunks == [("Narrator", "The morning sun warmed the Meadowood path.")]
