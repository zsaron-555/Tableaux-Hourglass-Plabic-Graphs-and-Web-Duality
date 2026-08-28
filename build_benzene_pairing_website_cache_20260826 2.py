#!/usr/bin/env python3
"""Build a compact website cache from the latest presentation TSVs.

The source TSVs contain the complete Cartesian W-state/X-presentation
universe.  Only nonzero scalar values are stored; an omitted value is zero
only after the builder has reconciled every expected TSV row and presentation.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from benzene_pairing_cache_20260826 import CACHE_SCHEMA, BenzenePairingCache


ROOT = Path(__file__).resolve().parent
FINAL = (
    ROOT
    / "output/analysis/benzene_X_presentation_expansion_20260826/final_results"
)
DEFAULT_SINGLE = FINAL / "benzene_only_presentation_dependent_WX_results_0826.tsv"
DEFAULT_CHAIN = FINAL / "chain_benzene_presentation_dependent_WX_results_0826.tsv"
DEFAULT_VERIFICATION = FINAL / "BENZENE_WX_PRESENTATION_VERIFICATION.json"
DEFAULT_OUTPUT = ROOT / "benzene_pairing_cache_0826.json.gz"
TERMINAL_CONVENTION_ID = "fll_prop2_20_source_orientation_unsigned_count_v1"


class CacheBuildError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _semantic_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _atomic_gzip_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                encoded = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                compressed.write(encoded)
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _record_metadata(
    target: dict[str, dict[str, Any]], identifier: str, metadata: Mapping[str, Any]
) -> None:
    normalized = dict(metadata)
    previous = target.setdefault(identifier, normalized)
    if previous != normalized:
        raise CacheBuildError(f"Inconsistent metadata for {identifier}: {previous} != {normalized}")


def _consume_tsv(
    path: Path,
    *,
    dataset_id: str,
    expected_rows: int,
    w_word_column: str,
    w_family_column: str,
    state_columns: Sequence[tuple[str, str, str]],
    w_presentations: dict[str, dict[str, Any]],
    x_presentations: dict[str, dict[str, Any]],
    nonzero_values: dict[str, dict[str, int]],
) -> dict[str, Any]:
    row_count = 0
    x_ids: set[str] = set()
    w_ids: set[str] = set()
    w_occurrences: dict[str, int] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        required = {
            w_word_column,
            w_family_column,
            "X_presentation_id",
            "X_yamanouchi_word",
            "X_benzene_type",
            "X_representation",
            *(column for column, _state, _value in state_columns),
            *(value for _column, _state, value in state_columns),
        }
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise CacheBuildError(f"{path} is missing columns {sorted(missing)}")
        for row in reader:
            row_count += 1
            x_id = str(row["X_presentation_id"])
            x_ids.add(x_id)
            _record_metadata(
                x_presentations,
                x_id,
                {
                    "word": str(row["X_yamanouchi_word"]),
                    "benzene_type": str(row["X_benzene_type"]),
                    "representation": str(row["X_representation"]),
                    "display_label": (
                        f"{row['X_representation']} {row['X_benzene_type']} X — {x_id}"
                    ),
                },
            )
            for id_column, state_name, value_column in state_columns:
                w_id = str(row[id_column])
                w_ids.add(w_id)
                w_occurrences[w_id] = w_occurrences.get(w_id, 0) + 1
                _record_metadata(
                    w_presentations,
                    w_id,
                    {
                        "word": str(row[w_word_column]),
                        "family_id": str(row[w_family_column]),
                        "dataset_id": dataset_id,
                        "state_name": state_name,
                        "representation": state_name,
                        "display_label": f"{state_name} — {w_id}",
                    },
                )
                value = int(row[value_column])
                if value:
                    bucket = nonzero_values.setdefault(w_id, {})
                    previous = bucket.setdefault(x_id, value)
                    if previous != value:
                        raise CacheBuildError(
                            f"Conflicting value for {w_id} / {x_id}: {previous} != {value}"
                        )
            if row_count % 1_000_000 == 0:
                print(f"{path.name}: {row_count:,}/{expected_rows:,} rows", flush=True)
    if row_count != expected_rows:
        raise CacheBuildError(
            f"{path}: expected {expected_rows:,} rows, read {row_count:,}"
        )
    incomplete = {
        w_id: count
        for w_id, count in w_occurrences.items()
        if count != len(x_ids)
    }
    if incomplete:
        sample = list(sorted(incomplete.items()))[:5]
        raise CacheBuildError(
            "A W presentation does not cover the complete X universe: "
            f"expected {len(x_ids)}, sample {sample}"
        )
    return {
        "row_count": row_count,
        "w_presentation_count": len(w_ids),
        "x_presentation_count": len(x_ids),
        "tsv_sha256": _sha256(path),
        "tsv_size": path.stat().st_size,
    }


def build(single: Path, chain: Path, verification_path: Path, output: Path) -> dict[str, Any]:
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    w_presentations: dict[str, dict[str, Any]] = {}
    x_presentations: dict[str, dict[str, Any]] = {}
    nonzero_values: dict[str, dict[str, int]] = {}

    single_source = _consume_tsv(
        single,
        dataset_id="isolated_benzene_0826",
        expected_rows=int(verification["single_benzene"]["row_count"]),
        w_word_column="W_yamanouchi_word",
        w_family_column="benzene_W_family_id",
        state_columns=(
            ("W_T_presentation_id", "T", "pairing_<T(W),X>"),
            ("W_Sm(T)_presentation_id", "Sm(T)", "pairing_<Sm(T)(W),X>"),
            ("W_B_presentation_id", "B", "pairing_<B(W),X>"),
            ("W_Sm(B)_presentation_id", "Sm(B)", "pairing_<Sm(B)(W),X>"),
        ),
        w_presentations=w_presentations,
        x_presentations=x_presentations,
        nonzero_values=nonzero_values,
    )
    chain_source = _consume_tsv(
        chain,
        dataset_id="chain_benzene_0826",
        expected_rows=int(verification["chain_benzene"]["row_count"]),
        w_word_column="W_yamanouchi_word",
        w_family_column="chain_W_family_id",
        state_columns=(
            ("W_C_T_presentation_id", "C_T", "pairing_<C_T(W),X>"),
            (
                "W_Sm_top(C_T)_presentation_id",
                "Sm_top(C_T)",
                "pairing_<Sm_top(C_T(W)),X>",
            ),
            ("W_R_MB_presentation_id", "R_MB", "pairing_<R_MB(W),X>"),
            ("W_C_M_presentation_id", "C_M", "pairing_<C_M(W),X>"),
            ("W_R_TM_presentation_id", "R_TM", "pairing_<R_TM(W),X>"),
            ("W_E_raw_presentation_id", "E_raw", "pairing_<E_raw(W),X>"),
            ("W_C_B_presentation_id", "C_B", "pairing_<C_B(W),X>"),
            (
                "W_Sm_bottom(C_B)_presentation_id",
                "Sm_bottom(C_B)",
                "pairing_<Sm_bottom(C_B(W)),X>",
            ),
        ),
        w_presentations=w_presentations,
        x_presentations=x_presentations,
        nonzero_values=nonzero_values,
    )
    if single_source["x_presentation_count"] != chain_source["x_presentation_count"]:
        raise CacheBuildError("The two TSVs do not use the same X-presentation universe.")
    if len(x_presentations) != int(verification["expanded_x_presentation_count"]):
        raise CacheBuildError("The cache X universe disagrees with the verification report.")

    datasets = {
        "isolated_benzene_0826": {
            "label": "Isolated-benzene presentation corpus",
            "source_tsv": single.name,
            "source_tsv_sha256": single_source["tsv_sha256"],
            "row_count": single_source["row_count"],
            "w_presentation_count": single_source["w_presentation_count"],
            "x_presentation_count": single_source["x_presentation_count"],
            "conjecture_status": "raw_fll_discrepancies_present",
            "conjecture_failure_count": int(
                verification["single_benzene"]["failure_count"]
            ),
            "pairing_values_are_authoritative": True,
            "convention_note": (
                "Raw FLL scalar values from the latest TSV. The isolated recurrence "
                "requires an explicit paper-tagged/intrinsic basis choice; the website "
                "does not silently apply a smoothing sign transport."
            ),
        },
        "chain_benzene_0826": {
            "label": "Chain-benzene presentation corpus",
            "source_tsv": chain.name,
            "source_tsv_sha256": chain_source["tsv_sha256"],
            "row_count": chain_source["row_count"],
            "w_presentation_count": chain_source["w_presentation_count"],
            "x_presentation_count": chain_source["x_presentation_count"],
            "conjecture_status": "verified",
            "conjecture_failure_count": int(
                verification["chain_benzene"]["failure_count"]
            ),
            "pairing_values_are_authoritative": True,
            "convention_note": "Raw FLL scalar values from the latest verified TSV.",
        },
    }
    semantic = {
        "datasets": datasets,
        "w_presentations": w_presentations,
        "x_presentations": x_presentations,
        "nonzero_values": nonzero_values,
        "terminal_convention_id": TERMINAL_CONVENTION_ID,
    }
    payload = {
        "schema": CACHE_SCHEMA,
        "cache_id": f"benzene_pairings_0826_{_semantic_sha256(semantic)[:16]}",
        "terminal_convention_id": TERMINAL_CONVENTION_ID,
        "missing_value_policy": "zero_within_complete_cartesian_coverage",
        "source_verification": verification_path.name,
        "source_verification_sha256": _sha256(verification_path),
        "datasets": datasets,
        "w_presentations": w_presentations,
        "x_presentations": x_presentations,
        "nonzero_values": nonzero_values,
        "statistics": {
            "w_presentation_count": len(w_presentations),
            "x_presentation_count": len(x_presentations),
            "nonzero_pairing_count": sum(
                len(values) for values in nonzero_values.values()
            ),
            "complete_pairing_count": len(w_presentations) * len(x_presentations),
        },
    }
    _atomic_gzip_json(output, payload)
    loaded = BenzenePairingCache.load(output)
    if loaded.summary()["w_presentation_count"] != len(w_presentations):
        raise CacheBuildError("Round-trip W-presentation count mismatch.")
    return {
        "output": str(output.resolve()),
        "output_sha256": _sha256(output),
        "output_size": output.stat().st_size,
        **loaded.summary(),
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", type=Path, default=DEFAULT_SINGLE)
    parser.add_argument("--chain", type=Path, default=DEFAULT_CHAIN)
    parser.add_argument("--verification", type=Path, default=DEFAULT_VERIFICATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = build(
        args.single.resolve(),
        args.chain.resolve(),
        args.verification.resolve(),
        args.output.resolve(),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
