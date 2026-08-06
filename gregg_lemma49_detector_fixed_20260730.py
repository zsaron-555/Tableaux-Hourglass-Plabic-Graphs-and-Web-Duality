#!/usr/bin/env python3
"""Portable replacement for the zero-pattern detector in July23-GreggColab.

The notebook's matcher greedily selects the first locally compatible internal
vertex.  That is not a subgraph-isomorphism search: a later constraint can
invalidate the choice even when another candidate gives a valid match.  This
script delegates complete subgraph matching to the current production matcher,
which backtracks over internal vertices, permits arbitrary additional edges
outside the displayed configuration, and reads the rule catalogues from
``sl4_lemma49_zero_patterns/manifest.json`` and
``sl4_lemma48_zero_patterns/manifest.json``.

Accepted input formats:

* pair table with ``w_word`` and ``x_word`` columns (CSV or TSV);
* Gregg's grouped table with ``w_word`` and a Python-list ``survivor_words``
  column.
"""

from __future__ import annotations

import argparse
import ast
import csv
import importlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
DEFAULT_REPO = (
    HERE.parent / "GitHub" / "Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality"
)
DEFAULT_GRAPH_DIR = HERE / "4x4_All_graph_data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Filter SL4 web pairs by the executable fork, Lemma 4.9, and "
            "corrected GL4 Lemma 4.8 rules."
        )
    )
    parser.add_argument("input", type=Path, help="Pairwise TSV/CSV or grouped survivor CSV")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--graphs", type=Path, default=DEFAULT_GRAPH_DIR)
    parser.add_argument("--survivors-out", type=Path, default=Path("final_survivors_fixed.tsv"))
    parser.add_argument("--killed-out", type=Path, default=Path("lemma49_killed_fixed.tsv"))
    parser.add_argument("--summary-out", type=Path, default=Path("final_summary_fixed.txt"))
    parser.add_argument(
        "--post-boundary-survivors-out",
        type=Path,
        help="Optional TSV containing every pair surviving the common (1,16) fork check.",
    )
    parser.add_argument(
        "--skip-boundary-fork",
        action="store_true",
        help="Do not apply Gregg's additional common (1,16) fork check.",
    )
    parser.add_argument(
        "--skip-lemma49",
        action="store_true",
        help="Do not apply the manifest-driven Lemma 4.9 paired-pattern check.",
    )
    parser.add_argument(
        "--skip-lemma48",
        action="store_true",
        help="Do not apply the corrected GL4 Lemma 4.8 paired-pattern check.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print a progress line after this many input pairs (0 disables it).",
    )
    return parser.parse_args()


def delimiter_for(path: Path) -> str:
    return "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","


def word_to_tableau(word: str) -> list[list[int]]:
    rows: list[list[int]] = [[] for _ in range(4)]
    for number, letter in enumerate(word, start=1):
        rows[int(letter) - 1].append(number)
    return rows


def tableau_to_word(tableau: list[list[int]]) -> str:
    letters = [""] * sum(len(row) for row in tableau)
    for row_index, row in enumerate(tableau, start=1):
        for entry in row:
            letters[entry - 1] = str(row_index)
    return "".join(letters)


def promote_word(word: str) -> str:
    tableau = word_to_tableau(word)
    row = col = None
    for r, entries in enumerate(tableau):
        if 1 in entries:
            row, col = r, entries.index(1)
            break
    if row is None or col is None:
        raise ValueError(f"Could not find 1 in tableau for word {word}")

    tableau[row][col] = None  # type: ignore[index]
    while True:
        candidates = []
        if col + 1 < len(tableau[row]) and tableau[row][col + 1] is not None:
            candidates.append((tableau[row][col + 1], row, col + 1))
        if (
            row + 1 < len(tableau)
            and col < len(tableau[row + 1])
            and tableau[row + 1][col] is not None
        ):
            candidates.append((tableau[row + 1][col], row + 1, col))
        if not candidates:
            break
        _, next_row, next_col = min(candidates)
        tableau[row][col] = tableau[next_row][next_col]
        tableau[next_row][next_col] = None  # type: ignore[index]
        row, col = next_row, next_col

    tableau[row][col] = len(word) + 1  # type: ignore[index]
    promoted = [[int(entry) - 1 for entry in entries] for entries in tableau]
    return tableau_to_word(promoted)


def build_promotion_orbits(all_words_path: Path) -> dict[int, list[str]]:
    with all_words_path.open(newline="", encoding="utf-8-sig") as handle:
        words = {
            str(row["word"]).strip()
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("word")
        }
    seen: set[str] = set()
    representatives: list[tuple[str, list[str]]] = []
    for word in sorted(words):
        if word in seen:
            continue
        orbit: list[str] = []
        current = word
        while current not in orbit:
            if current not in words:
                raise ValueError(f"Promotion produced unknown word {current}")
            orbit.append(current)
            seen.add(current)
            current = promote_word(current)
        representatives.append((min(orbit), orbit))
    representatives.sort(key=lambda item: item[0])
    return {
        index: orbit
        for index, (_, orbit) in enumerate(representatives, start=1)
    }


def read_pairs(path: Path, all_words_path: Path) -> list[tuple[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter_for(path))
        fields = set(reader.fieldnames or [])
        if {"w_word", "x_word"} <= fields:
            return [
                (str(row["w_word"]).strip(), str(row["x_word"]).strip())
                for row in reader
                if row.get("w_word") and row.get("x_word")
            ]
        if {"w_word", "survivor_words"} <= fields:
            pairs: list[tuple[str, str]] = []
            orbits: dict[int, list[str]] | None = None
            for row in reader:
                w_word = str(row["w_word"]).strip()
                raw_words = str(row.get("survivor_words") or "").strip()
                if raw_words:
                    survivor_words = ast.literal_eval(raw_words)
                else:
                    if orbits is None:
                        orbits = build_promotion_orbits(all_words_path)
                    survivor_words = []
                    for orbit_index, position in ast.literal_eval(row["survivor_pairs"]):
                        orbit = orbits[int(orbit_index)]
                        survivor_words.append(orbit[int(position) % len(orbit)])
                for x_word in survivor_words:
                    pairs.append((w_word, str(x_word).strip()))
            return pairs
    raise ValueError(
        "Input must contain w_word/x_word or w_word/survivor_words columns"
    )


def graph_index(graph_dir: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in graph_dir.glob("*.json"):
        if "_" not in path.stem:
            continue
        result[path.stem.split("_", 1)[1]] = path
    return result


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_rules(repo: Path) -> Any:
    repo = repo.resolve()
    os.environ["PROBLEM3_APP_DIR"] = str(repo)
    sys.path.insert(0, str(repo))
    for module_name in (
        "web_relation_rules_optimized_20260726",
        "web_relation_rules_0714",
    ):
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
    raise ModuleNotFoundError(
        f"No production relation module found under {repo}; expected "
        "web_relation_rules_optimized_20260726.py or web_relation_rules_0714.py"
    )


def has_fork_at_1_16(graph: dict[str, Any]) -> bool:
    nodes = {int(node["id"]): node for node in graph.get("nodes", [])}
    boundary_by_label = {
        int(node["boundary_label"]): int(node["id"])
        for node in graph.get("nodes", [])
        if node.get("boundary_label") is not None
    }
    if 1 not in boundary_by_label or 16 not in boundary_by_label:
        return False

    ordinary_neighbors: dict[int, set[int]] = {}
    for edge in graph.get("edges", []):
        if edge.get("kind", "ordinary") != "ordinary":
            continue
        u, v = int(edge["src"]), int(edge["dst"])
        ordinary_neighbors.setdefault(u, set()).add(v)
        ordinary_neighbors.setdefault(v, set()).add(u)

    def internal_white_neighbors(boundary_label: int) -> set[int]:
        boundary = boundary_by_label[boundary_label]
        return {
            neighbor
            for neighbor in ordinary_neighbors.get(boundary, set())
            if nodes.get(neighbor, {}).get("color") == "white"
            and nodes.get(neighbor, {}).get("boundary_label") is None
        }

    return bool(internal_white_neighbors(1) & internal_white_neighbors(16))


def write_rows(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    rules = load_rules(args.repo)
    pairs = read_pairs(args.input, args.graphs / "all_4x4_words.tsv")
    index = graph_index(args.graphs)
    if not index:
        raise FileNotFoundError(f"No graph JSON files found under {args.graphs}")

    needed = {word for pair in pairs for word in pair}
    missing = sorted(needed - set(index))
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} graph words are missing; first entries: {missing[:10]}"
        )

    graph_cache = {word: load_json(index[word]) for word in needed}
    survivors: list[dict[str, Any]] = []
    post_boundary_survivors: list[dict[str, Any]] = []
    killed: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    started = time.monotonic()

    def report_progress(row_number: int) -> None:
        if not args.progress_every or row_number % args.progress_every:
            return
        elapsed = time.monotonic() - started
        rate = row_number / elapsed if elapsed else 0.0
        remaining = len(pairs) - row_number
        eta = remaining / rate if rate else 0.0
        print(
            f"progress {row_number:,}/{len(pairs):,}; "
            f"killed={len(killed):,}; survivors={len(survivors):,}; "
            f"rate={rate:.2f} pairs/s; eta={eta / 60:.1f} min",
            flush=True,
        )

    for row_number, (w_word, x_word) in enumerate(pairs, start=1):
        w_graph = graph_cache[w_word]
        x_graph = graph_cache[x_word]

        if (
            not args.skip_boundary_fork
            and has_fork_at_1_16(w_graph)
            and has_fork_at_1_16(x_graph)
        ):
            reason = "common_boundary_fork_1_16"
            counts[reason] += 1
            killed.append(
                {
                    "row_number": row_number,
                    "w_word": w_word,
                    "x_word": x_word,
                    "elimination": reason,
                    "boundary_labels": "1,16",
                    "reflected": "",
                    "pair_swapped": "",
                }
            )
            report_progress(row_number)
            continue

        post_boundary_survivors.append(
            {
                "row_number": row_number,
                "w_word": w_word,
                "x_word": x_word,
            }
        )

        matches = []
        if not args.skip_lemma49:
            matches = rules.detect_sl4_lemma49_zero_pair(
                w_graph,
                x_graph,
                max_matches=1,
            )
        if matches:
            match = matches[0]
            rule_id = str(match["rule_id"])
            counts[rule_id] += 1
            killed.append(
                {
                    "row_number": row_number,
                    "w_word": w_word,
                    "x_word": x_word,
                    "lemma": "4.9",
                    "elimination": rule_id,
                    "boundary_labels": ",".join(
                        str(label) for label in match.get("boundary_labels", [])
                    ),
                    "reflected": str(bool(match.get("reflected", False))).lower(),
                    "pair_swapped": str(bool(match.get("pair_swapped", False))).lower(),
                }
            )
            report_progress(row_number)
            continue

        lemma48_matches = []
        if not args.skip_lemma48:
            lemma48_matches = rules.detect_sl4_lemma48_zero_pair(
                w_graph,
                x_graph,
                max_matches=1,
            )
        if lemma48_matches:
            match = lemma48_matches[0]
            rule_id = str(match["rule_id"])
            counts[rule_id] += 1
            killed.append(
                {
                    "row_number": row_number,
                    "w_word": w_word,
                    "x_word": x_word,
                    "lemma": "4.8",
                    "elimination": rule_id,
                    "boundary_labels": ",".join(
                        str(label) for label in match.get("boundary_labels", [])
                    ),
                    "reflected": str(bool(match.get("reflected", False))).lower(),
                    "pair_swapped": str(bool(match.get("pair_swapped", False))).lower(),
                }
            )
            report_progress(row_number)
            continue

        survivors.append(
            {
                "row_number": row_number,
                "w_word": w_word,
                "x_word": x_word,
            }
        )
        report_progress(row_number)

    write_rows(
        args.survivors_out,
        survivors,
        ["row_number", "w_word", "x_word"],
    )
    if args.post_boundary_survivors_out:
        write_rows(
            args.post_boundary_survivors_out,
            post_boundary_survivors,
            ["row_number", "w_word", "x_word"],
        )
    write_rows(
        args.killed_out,
        killed,
        [
            "row_number",
            "w_word",
            "x_word",
            "lemma",
            "elimination",
            "boundary_labels",
            "reflected",
            "pair_swapped",
        ],
    )

    lines = [
        "Corrected fork, Lemma 4.9, and Lemma 4.8 detector summary",
        "=========================================================",
        f"Input pairs: {len(pairs):,}",
        f"Survived common boundary fork (1,16): {len(post_boundary_survivors):,}",
        f"Eliminated after boundary-fork stage: {len(killed):,}",
        f"Surviving: {len(survivors):,}",
        "",
        "Elimination breakdown:",
    ]
    lines.extend(f"  {name}: {count:,}" for name, count in counts.most_common())
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.summary_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
