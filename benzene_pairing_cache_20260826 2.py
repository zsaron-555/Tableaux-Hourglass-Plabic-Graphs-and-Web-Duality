"""Read-only lookup for the presentation-dependent benzene pairing corpus."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


CACHE_SCHEMA = "problem3.benzene_pairing_website_cache.v1"


class PairingCacheError(RuntimeError):
    pass


@dataclass(frozen=True)
class PairingLookup:
    w_presentation_id: str
    x_presentation_id: str
    value: int
    value_source: str
    w: Mapping[str, Any]
    x: Mapping[str, Any]
    dataset: Mapping[str, Any]
    cache: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "computed_from_authoritative_tsv_cache",
            "w_presentation_id": self.w_presentation_id,
            "x_presentation_id": self.x_presentation_id,
            "value": self.value,
            "value_source": self.value_source,
            "w": dict(self.w),
            "x": dict(self.x),
            "dataset": dict(self.dataset),
            "cache": dict(self.cache),
        }


class BenzenePairingCache:
    """Complete Cartesian lookup with sparse storage of nonzero values.

    Every W presentation in the cache was paired with every X presentation.
    Therefore an omitted W/X entry is exactly zero, not an unknown value.
    """

    def __init__(self, payload: Mapping[str, Any], *, path: Path):
        if payload.get("schema") != CACHE_SCHEMA:
            raise PairingCacheError(
                f"Unsupported benzene pairing cache schema {payload.get('schema')!r}."
            )
        if payload.get("missing_value_policy") != "zero_within_complete_cartesian_coverage":
            raise PairingCacheError("The pairing cache does not certify omitted values as zero.")
        self.path = path.resolve()
        self.payload = dict(payload)
        self.w_presentations = {
            str(key): dict(value)
            for key, value in payload.get("w_presentations", {}).items()
        }
        self.x_presentations = {
            str(key): dict(value)
            for key, value in payload.get("x_presentations", {}).items()
        }
        self.nonzero_values = {
            str(w_id): {str(x_id): int(value) for x_id, value in values.items()}
            for w_id, values in payload.get("nonzero_values", {}).items()
        }
        self.datasets = {
            str(key): dict(value) for key, value in payload.get("datasets", {}).items()
        }
        if not self.w_presentations or not self.x_presentations:
            raise PairingCacheError("The pairing cache contains no presentation universe.")
        self._w_by_word: dict[str, list[str]] = {}
        self._x_by_word: dict[str, list[str]] = {}
        for presentation_id, record in self.w_presentations.items():
            self._w_by_word.setdefault(str(record["word"]), []).append(presentation_id)
        for presentation_id, record in self.x_presentations.items():
            self._x_by_word.setdefault(str(record["word"]), []).append(presentation_id)
        for values in (self._w_by_word, self._x_by_word):
            for ids in values.values():
                ids.sort(key=self._presentation_sort_key)

    @staticmethod
    def _presentation_sort_key(presentation_id: str) -> tuple[Any, ...]:
        if presentation_id.startswith("catalogue_X_"):
            return (-1, presentation_id)
        state_order = {
            "top": 0,
            "middle": 1,
            "bottom": 2,
            "sm_top": 3,
            "upper_square": 3,
            "sm_bottom": 4,
            "lower_square": 4,
            "upper_horizontal": 5,
            "lower_horizontal": 6,
            "common_vertical": 7,
        }
        tail = presentation_id.rsplit("__", 1)[-1]
        return (state_order.get(tail, 99), presentation_id)

    @classmethod
    def load(cls, path: str | Path) -> "BenzenePairingCache":
        resolved = Path(path).expanduser().resolve()
        with gzip.open(resolved, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, Mapping):
            raise PairingCacheError("The pairing cache root must be a JSON object.")
        return cls(payload, path=resolved)

    def options(self, value: str, side: str) -> list[dict[str, Any]]:
        side = side.upper()
        identifier = str(value).strip()
        if side == "W":
            records = self.w_presentations
            by_word = self._w_by_word
        elif side == "X":
            records = self.x_presentations
            by_word = self._x_by_word
        else:
            raise ValueError("side must be W or X")
        if identifier in records:
            word = str(records[identifier]["word"])
            ids = by_word.get(word, [])
        else:
            ids = by_word.get(identifier, [])
        return [
            {"value": presentation_id, **records[presentation_id]}
            for presentation_id in ids
        ]

    def resolve(self, value: str, side: str) -> tuple[str | None, list[str]]:
        options = self.options(value, side)
        identifier = str(value).strip()
        if side.upper() == "W" and identifier in self.w_presentations:
            return identifier, []
        if side.upper() == "X" and identifier in self.x_presentations:
            return identifier, []
        ids = [str(item["value"]) for item in options]
        if len(ids) == 1:
            return ids[0], []
        return None, ids

    def lookup(self, w_presentation_id: str, x_presentation_id: str) -> PairingLookup | None:
        w_id = str(w_presentation_id).strip()
        x_id = str(x_presentation_id).strip()
        w = self.w_presentations.get(w_id)
        x = self.x_presentations.get(x_id)
        if w is None or x is None:
            return None
        dataset_id = str(w["dataset_id"])
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            raise PairingCacheError(f"Unknown dataset {dataset_id!r} for {w_id}.")
        sparse = self.nonzero_values.get(w_id, {})
        value = int(sparse.get(x_id, 0))
        source = "stored_nonzero" if x_id in sparse else "certified_zero_complete_coverage"
        return PairingLookup(
            w_presentation_id=w_id,
            x_presentation_id=x_id,
            value=value,
            value_source=source,
            w=w,
            x=x,
            dataset=dataset,
            cache={
                "schema": self.payload["schema"],
                "cache_id": self.payload.get("cache_id"),
                "file": self.path.name,
                "terminal_convention_id": self.payload.get("terminal_convention_id"),
                "source_verification_sha256": self.payload.get(
                    "source_verification_sha256"
                ),
            },
        )

    def summary(self) -> dict[str, Any]:
        return {
            "schema": self.payload["schema"],
            "cache_id": self.payload.get("cache_id"),
            "w_presentation_count": len(self.w_presentations),
            "x_presentation_count": len(self.x_presentations),
            "nonzero_pairing_count": sum(
                len(values) for values in self.nonzero_values.values()
            ),
            "missing_value_policy": self.payload["missing_value_policy"],
            "terminal_convention_id": self.payload.get("terminal_convention_id"),
        }
