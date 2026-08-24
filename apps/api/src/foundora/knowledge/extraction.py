from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import PurePath

EXTRACTION_VERSION = "foundora-text-extractor.v1"
SUPPORTED_MEDIA_TYPES: dict[str, frozenset[str]] = {
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/markdown", "text/plain"}),
    ".json": frozenset({"application/json", "text/json"}),
    ".csv": frozenset({"text/csv", "text/plain"}),
}


class ExtractionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExtractedDocument:
    filename: str
    media_type: str
    text: str
    content_sha256: str
    byte_size: int


@dataclass(frozen=True)
class TextChunk:
    ordinal: int
    start_character: int
    end_character: int
    content: str
    content_sha256: str
    estimated_tokens: int


def extract_text(
    data: bytes,
    *,
    filename: str,
    media_type: str,
    max_bytes: int,
    max_characters: int,
) -> ExtractedDocument:
    normalized_name = filename.strip()
    if (
        not normalized_name
        or len(normalized_name) > 255
        or PurePath(normalized_name).name != normalized_name
        or normalized_name in {".", ".."}
    ):
        raise ExtractionError("invalid_filename", "The filename is invalid")
    if not data:
        raise ExtractionError("empty_file", "The uploaded file is empty")
    if len(data) > max_bytes:
        raise ExtractionError("file_too_large", "The uploaded file exceeds the configured limit")

    extension = PurePath(normalized_name).suffix.lower()
    normalized_media_type = media_type.split(";", 1)[0].strip().lower()
    allowed = SUPPORTED_MEDIA_TYPES.get(extension)
    if allowed is None or normalized_media_type not in allowed:
        raise ExtractionError(
            "unsupported_file_type",
            "Only UTF-8 .txt, .md, .json, and .csv files are supported",
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ExtractionError(
            "invalid_encoding", "The file must contain valid UTF-8 text"
        ) from error
    if "\x00" in text:
        raise ExtractionError("malformed_text", "The file contains unsupported null bytes")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if extension == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise ExtractionError("malformed_json", "The JSON document is malformed") from error
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    text = text.strip()
    if not text:
        raise ExtractionError("empty_text", "The file contains no retrievable text")
    if len(text) > max_characters:
        raise ExtractionError(
            "extracted_text_too_large",
            "The extracted text exceeds the configured character limit",
        )
    return ExtractedDocument(
        filename=normalized_name,
        media_type=normalized_media_type,
        text=text,
        content_sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    )


def chunk_text(text: str, *, max_characters: int = 1200, overlap: int = 160) -> list[TextChunk]:
    if max_characters < 200 or overlap < 0 or overlap >= max_characters:
        raise ValueError("invalid chunking bounds")
    chunks: list[TextChunk] = []
    start = 0
    while start < len(text):
        hard_end = min(start + max_characters, len(text))
        end = hard_end
        if hard_end < len(text):
            paragraph = text.rfind("\n\n", start + max_characters // 2, hard_end)
            whitespace = text.rfind(" ", start + max_characters // 2, hard_end)
            boundary = max(paragraph + 2 if paragraph >= 0 else -1, whitespace + 1)
            if boundary > start:
                end = boundary
        raw = text[start:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        content_start = start + leading
        content_end = start + trailing
        content = text[content_start:content_end]
        if content:
            chunks.append(
                TextChunk(
                    ordinal=len(chunks),
                    start_character=content_start,
                    end_character=content_end,
                    content=content,
                    content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    estimated_tokens=max(1, math.ceil(len(content.encode("utf-8")) / 4)),
                )
            )
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    if not chunks:
        raise ExtractionError("empty_text", "The file contains no retrievable text")
    return chunks
