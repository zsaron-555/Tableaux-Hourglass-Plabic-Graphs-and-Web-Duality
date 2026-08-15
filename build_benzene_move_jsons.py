#!/usr/bin/env python3
"""Build every noncatalogue benzene-move presentation and its promotions.

The original 24,024 graph JSON files are never modified.  Generated files are
written below ``4x4_All_graph_data/benzene_move_presentations`` together with a
manifest used by ``web_explorer_v4.html``.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from audit_benzene_conjecture_20260803 import (
    cycle_edges,
    graph_model,
    induced_internal_six_cycles,
    is_benzene,
)
from audit_benzene_presentation_invariance_20260810 import rebuild_embedding_metadata
from check_benzene_surgery_pairing import (
    RibbonWeb,
    benzene_move_presentations,
    load_ribbon_web,
    validate_ribbon_web,
)
from make_benzene_pairing_tasks import graph_records, representative_indices


ROOT = Path(__file__).resolve().parent
DEFAULT_GRAPH_DIR = ROOT / "4x4_All_graph_data"
DEFAULT_REPRESENTATIVES = ROOT / "transpose_1522_tasks_latest.tsv"
OUTPUT_FOLDER = "benzene_move_presentations"


def word_to_tableau(word: str) -> List[List[int]]:
    rows: List[List[int]] = [[] for _ in range(4)]
    for entry, symbol in enumerate(word, start=1):
        rows[int(symbol) - 1].append(entry)
    return rows


def tableau_to_word(rows: Sequence[Sequence[int]]) -> str:
    row_of = {
        entry: row_index
        for row_index, row in enumerate(rows, start=1)
        for entry in row
    }
    return "".join(str(row_of[entry]) for entry in range(1, 17))


def promote_word_once(word: str) -> str:
    rows: List[List[int | None]] = [list(row) for row in word_to_tableau(word)]
    row_index, column_index = next(
        (r, row.index(1)) for r, row in enumerate(rows) if 1 in row
    )
    rows[row_index][column_index] = None
    while True:
        candidates: List[Tuple[int, int, int]] = []
        if column_index + 1 < len(rows[row_index]):
            value = rows[row_index][column_index + 1]
            if value is not None:
                candidates.append((value, row_index, column_index + 1))
        if row_index + 1 < len(rows) and column_index < len(rows[row_index + 1]):
            value = rows[row_index + 1][column_index]
            if value is not None:
                candidates.append((value, row_index + 1, column_index))
        if not candidates:
            break
        _, next_row, next_column = min(candidates)
        rows[row_index][column_index] = rows[next_row][next_column]
        rows[next_row][next_column] = None
        row_index, column_index = next_row, next_column
    for row in rows:
        for index, value in enumerate(row):
            if value is not None:
                row[index] = value - 1
    rows[row_index][column_index] = 16
    return tableau_to_word([[int(value) for value in row] for row in rows])


def promotion_orbit(word: str) -> List[str]:
    result: List[str] = []
    current = word
    while current not in result:
        result.append(current)
        current = promote_word_once(current)
    if current != word:
        raise ValueError(f"Promotion entered a cycle not rooted at {word}.")
    return result


def shifted_boundary_label(label: int, steps: int) -> int:
    return ((int(label) - 1 - steps) % 16) + 1


def rotate_point(point: Sequence[float], center: Tuple[float, float], theta: float) -> List[float]:
    x, y = float(point[0]) - center[0], float(point[1]) - center[1]
    cosine, sine = math.cos(theta), math.sin(theta)
    return [
        center[0] + cosine * x - sine * y,
        center[1] + sine * x + cosine * y,
    ]


def rotate_graph_data(data: Mapping[str, Any], promoted_word: str, steps: int) -> Dict[str, Any]:
    result = copy.deepcopy(data)
    boundary_nodes = [
        node for node in result.get("nodes", [])
        if node.get("boundary_label") is not None
    ]
    center = (
        sum(float(node["x"]) for node in boundary_nodes) / len(boundary_nodes),
        sum(float(node["y"]) for node in boundary_nodes) / len(boundary_nodes),
    )
    theta = steps * 2.0 * math.pi / 16.0
    for node in result.get("nodes", []):
        node["x"], node["y"] = rotate_point((node["x"], node["y"]), center, theta)
        if node.get("boundary_label") is not None:
            node["boundary_label"] = shifted_boundary_label(node["boundary_label"], steps)
        terminal = node.get("growth_terminal")
        if isinstance(terminal, int) and 1 <= terminal <= 16:
            node["growth_terminal"] = shifted_boundary_label(terminal, steps)
    nodes_by_id = {int(node["id"]): node for node in result.get("nodes", [])}
    for boundary in result.get("boundary", []):
        node = nodes_by_id[int(boundary["node"])]
        boundary["label"] = int(node["boundary_label"])
        boundary["x"] = float(node["x"])
        boundary["y"] = float(node["y"])
    result.get("boundary", []).sort(key=lambda item: int(item["label"]))
    for edge in result.get("edges", []):
        if isinstance(edge.get("route"), list):
            edge["route"] = [rotate_point(point, center, theta) for point in edge["route"]]
    labels = result.get("boundary_labels")
    if isinstance(labels, dict):
        result["boundary_labels"] = {
            key: shifted_boundary_label(value, steps) for key, value in labels.items()
        }
    elif isinstance(labels, list):
        result["boundary_labels"] = [shifted_boundary_label(value, steps) for value in labels]
    for entries in result.get("effective_rotation_system", {}).values():
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry.get("angle"), (int, float)):
                entry["angle"] = (float(entry["angle"]) + theta) % (2.0 * math.pi)
    result["word"] = promoted_word
    result.setdefault("metadata", {})["word"] = promoted_word
    return result


def apply_presentation(data: Mapping[str, Any], presentation: RibbonWeb) -> Dict[str, Any]:
    result = copy.deepcopy(data)
    observed = set()
    for edge in result.get("edges", []):
        key = frozenset((int(edge["src"]), int(edge["dst"])))
        kind = presentation.edges[key]
        observed.add(key)
        edge["kind"] = "hourglass" if kind == "H" else "ordinary"
        edge["double"] = kind == "H"
    if observed != set(presentation.edges):
        raise ValueError("The source JSON edge set differs from its RibbonWeb model.")
    rebuild_embedding_metadata(result)
    return result


def presentation_key(web: RibbonWeb) -> Tuple[Tuple[Tuple[int, int], str], ...]:
    return tuple(
        sorted((tuple(sorted(edge)), kind) for edge, kind in web.edges.items())
    )


def cycle_json(cycle: Iterable[int]) -> List[int]:
    return [int(vertex) for vertex in cycle]


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(graph_dir: Path, representatives_file: Path, output_dir: Path, *, clean: bool) -> Dict[str, Any]:
    records = graph_records(graph_dir)
    record_by_word = {record.word: record for record in records}
    representative_map = representative_indices(representatives_file)
    if len(representative_map) != 1522:
        raise ValueError(f"Expected 1,522 representatives, found {len(representative_map)}.")
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    classes: List[Dict[str, Any]] = []
    files: List[Dict[str, Any]] = []
    class_sizes: Dict[int, int] = {}
    generated_names = set()

    for rep_word, rep_index in sorted(representative_map.items(), key=lambda item: item[1]):
        source = record_by_word[rep_word]
        model = graph_model(source.path)
        all_cycles = induced_internal_six_cycles(model)
        active = [cycle for cycle in all_cycles if is_benzene(cycle, model.edge_kind)]
        if not active:
            continue
        web = load_ribbon_web(source.path)
        presentations = benzene_move_presentations(web, all_cycles)
        if len(presentations) <= 1:
            continue
        class_sizes[len(presentations)] = class_sizes.get(len(presentations), 0) + 1
        original_key = presentation_key(web)
        orbit = promotion_orbit(rep_word)
        class_record: Dict[str, Any] = {
            "representative_index": rep_index,
            "representative_word": rep_word,
            "source_global_index": source.index,
            "source_json": source.path.name,
            "class_size": len(presentations),
            "promotion_orbit_size": len(orbit),
            "presentations": [],
        }
        moved_number = 0
        for presentation, path in presentations:
            if presentation_key(presentation) == original_key:
                continue
            moved_number += 1
            moved_data = apply_presentation(json.loads(source.path.read_text()), presentation)
            presentation_record: Dict[str, Any] = {
                "presentation": moved_number,
                "move_count": len(path),
                "move_path": [cycle_json(cycle) for cycle in path],
                "rotations": [],
            }
            for step, promoted_word in enumerate(orbit):
                promoted_source = record_by_word[promoted_word]
                file_name = (
                    f"{promoted_source.index:05d}_{promoted_word}"
                    f"__benzene_rep{rep_index:04d}_p{moved_number:02d}_rho{step:02d}.json"
                )
                if file_name in generated_names:
                    raise ValueError(f"Duplicate generated name: {file_name}")
                generated_names.add(file_name)
                rotated = rotate_graph_data(moved_data, promoted_word, step)
                metadata = rotated.setdefault("metadata", {})
                metadata["benzene_move_presentation"] = {
                    "catalogue_representative_index": rep_index,
                    "catalogue_representative_word": rep_word,
                    "catalogue_source_json": source.path.name,
                    "presentation": moved_number,
                    "class_size": len(presentations),
                    "move_path": [cycle_json(cycle) for cycle in path],
                    "promotion_step": step,
                    "promotion_orbit_size": len(orbit),
                    "promoted_word": promoted_word,
                }
                destination = output_dir / file_name
                write_json(destination, rotated)
                validate_ribbon_web(load_ribbon_web(destination))
                relative = f"{OUTPUT_FOLDER}/{file_name}"
                rotation_record = {
                    "word": promoted_word,
                    "global_index": promoted_source.index,
                    "promotion_step": step,
                    "json": relative,
                }
                presentation_record["rotations"].append(rotation_record)
                files.append({
                    **rotation_record,
                    "representative_index": rep_index,
                    "representative_word": rep_word,
                    "presentation": moved_number,
                    "class_size": len(presentations),
                    "move_count": len(path),
                })
            class_record["presentations"].append(presentation_record)
        classes.append(class_record)

    manifest: Dict[str, Any] = {
        "schema": "sl4-benzene-move-presentations-v1",
        "graph_folder": graph_dir.name,
        "presentation_folder": OUTPUT_FOLDER,
        "representative_count": len(classes),
        "class_size_distribution": {str(key): value for key, value in sorted(class_sizes.items())},
        "noncatalogue_representative_presentations": sum(item["class_size"] - 1 for item in classes),
        "generated_json_count": len(files),
        "classes": classes,
        "files": files,
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-dir", type=Path, default=DEFAULT_GRAPH_DIR)
    parser.add_argument("--representatives", type=Path, default=DEFAULT_REPRESENTATIVES)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--no-clean", action="store_true", help="Keep unrelated existing files in the output folder.")
    args = parser.parse_args()
    graph_dir = args.graph_dir.expanduser().resolve()
    output_dir = (args.output_dir or graph_dir / OUTPUT_FOLDER).expanduser().resolve()
    manifest = build(
        graph_dir,
        args.representatives.expanduser().resolve(),
        output_dir,
        clean=not args.no_clean,
    )
    print(f"benzene representatives: {manifest['representative_count']}")
    print(f"class sizes: {manifest['class_size_distribution']}")
    print(f"noncatalogue representative presentations: {manifest['noncatalogue_representative_presentations']}")
    print(f"generated promoted JSONs: {manifest['generated_json_count']}")
    print(f"manifest: {output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
