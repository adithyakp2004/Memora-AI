import re


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    words = paragraph.split()
    pieces = []
    current: list[str] = []
    current_length = 0

    for word in words:
        added_length = len(word) + bool(current)
        if current and current_length + added_length > max_chars:
            pieces.append(" ".join(current))
            current = []
            current_length = 0
        if len(word) > max_chars:
            raise ValueError("A single word exceeds the configured chunk size.")
        current.append(word)
        current_length += len(word) + bool(len(current) > 1)

    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_text(
    text: str,
    *,
    chunk_size_chars: int = 2_000,
    overlap_chars: int = 400,
) -> list[str]:
    if chunk_size_chars <= 0:
        raise ValueError("Chunk size must be positive.")
    if overlap_chars < 0 or overlap_chars >= chunk_size_chars:
        raise ValueError("Chunk overlap must be non-negative and smaller than chunk size.")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", normalized)
    ]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        return []

    core_chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > chunk_size_chars:
            if current:
                core_chunks.append(current)
                current = ""
            pieces = _split_long_paragraph(paragraph, chunk_size_chars)
            core_chunks.extend(pieces[:-1])
            current = pieces[-1]
            continue

        combined = f"{current}\n\n{paragraph}" if current else paragraph
        if current and len(combined) > chunk_size_chars:
            core_chunks.append(current)
            current = paragraph
        else:
            current = combined

    if current:
        core_chunks.append(current)

    if len(core_chunks) > 1 and len(core_chunks[-1]) < min(200, chunk_size_chars // 4):
        combined = f"{core_chunks[-2]}\n\n{core_chunks[-1]}"
        if len(combined) <= chunk_size_chars:
            core_chunks[-2:] = [combined]

    chunks = [core_chunks[0]]
    for core in core_chunks[1:]:
        previous_words = chunks[-1].split()
        overlap: list[str] = []
        overlap_length = 0
        for word in reversed(previous_words):
            added_length = len(word) + bool(overlap)
            if overlap and overlap_length + added_length > overlap_chars:
                break
            if not overlap and len(word) > overlap_chars:
                break
            overlap.append(word)
            overlap_length += len(word) + bool(len(overlap) > 1)
        overlap.reverse()
        prefix = " ".join(overlap)
        chunks.append(f"{prefix} {core}" if prefix else core)

    return chunks
