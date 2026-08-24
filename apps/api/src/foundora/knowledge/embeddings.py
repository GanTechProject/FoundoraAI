from __future__ import annotations

import hashlib
import itertools
import math
import re
import unicodedata
from typing import Protocol

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


class EmbeddingAdapter(Protocol):
    model: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


class LocalFeatureHashEmbedding:
    """Deterministic local lexical embedding with no provider or network dependency."""

    model = "foundora.local-feature-hash.v1"
    dimensions = 256

    def embed(self, text: str) -> list[float]:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        tokens = TOKEN_PATTERN.findall(normalized)
        if not tokens and normalized.strip():
            tokens = [normalized.strip()]
        features = [
            *tokens,
            *(f"{left}\u241f{right}" for left, right in itertools.pairwise(tokens)),
        ]
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [round(value / norm, 10) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
