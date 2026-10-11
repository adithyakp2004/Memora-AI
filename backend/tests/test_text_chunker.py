from app.services.text_chunker import chunk_text


def test_short_text_produces_a_single_deterministic_chunk():
    text = "Short paragraph.\n\nSecond paragraph."

    assert chunk_text(text) == ["Short paragraph.\n\nSecond paragraph."]
    assert chunk_text(text) == chunk_text(text)


def test_empty_and_whitespace_only_documents_produce_no_chunks():
    assert chunk_text("") == []
    assert chunk_text(" \n \t\n ") == []


def test_long_text_is_split_without_splitting_words_and_has_overlap():
    words = [f"word{index}" for index in range(180)]
    text = " ".join(words)

    chunks = chunk_text(text, chunk_size_chars=180, overlap_chars=40)

    assert len(chunks) > 1
    assert all(len(chunk) <= 220 for chunk in chunks)
    assert all(word in " ".join(chunks) for word in words)
    for previous, following in zip(chunks, chunks[1:]):
        previous_words = previous.split()
        following_words = following.split()
        assert set(previous_words[-3:]).intersection(following_words[:3])


def test_paragraph_boundaries_are_preserved_when_chunks_fit():
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."

    assert chunk_text(text, chunk_size_chars=80, overlap_chars=10) == [
        text
    ]


def test_small_final_chunk_is_merged_when_it_fits_target():
    text = f"{'A' * 140}\n\n{'B' * 25}"

    chunks = chunk_text(text, chunk_size_chars=180, overlap_chars=20)

    assert len(chunks) == 1
    assert "A" * 140 in chunks[0]
    assert "B" * 25 in chunks[0]
