from app.audio import split_phrases

def test_phrase_chunks_are_readable():
    text = "Grace looked at Bramble, smiled gently, and said that everything would be okay."
    chunks = split_phrases(text, max_words=6)
    assert chunks
    assert all(len(x.split()) <= 6 for x in chunks)
