#!/usr/bin/env python3
"""Standalone script to build all benzene-move presentation JSONs and manifest.json.

It scans 4x4_All_graph_data, identifies every web with benzene faces, computes all
alternative presentations in its benzene-move equivalence class, generates all
promotions (rotations), and writes them to 4x4_All_graph_data/benzene_move_presentations/.
"""

import copy
import json
import math
import shutil
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parent
GRAPH_DIR = ROOT / "4x4_All_graph_data"
OUTPUT_DIR = GRAPH_DIR / "benzene_move_presentations"
OUTPUT_FOLDER_NAME = "benzene_move_presentations"

EdgeKey = FrozenSet[int]
Port = Tuple[int, str]
Cycle = Tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class RibbonWeb:
    word: str
    colors: Mapping[int, str]
    boundary_labels: Mapping[int, int]
    edges: Mapping[EdgeKey, str]
    rotations: Mapping[int, Tuple[Port, ...]]


def _edge_kind(edge: Mapping[str, object]) -> str:
    return "H" if edge.get("kind") == "hourglass" or edge.get("double") else "O"


def load_ribbon_web(path: Path) -> RibbonWeb:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    colors = {
        int(node["id"]): str(node.get("color", ""))
        for node in data.get("nodes", [])
    }
    boundary_labels = {
        int(item["node"]): int(item["label"])
        for item in data.get("boundary", [])
    }
    edges: Dict[EdgeKey, str] = {}
    for edge in data.get("edges", []):
        source, target = int(edge["src"]), int(edge["dst"])
        key = frozenset((source, target))
        edges[key] = _edge_kind(edge)

    rotations: Dict[int, Tuple[Port, ...]] = {}
    raw_rotation = data.get("effective_rotation_system", {})
    for node_text, entries in raw_rotation.items():
        node = int(node_text)
        ordered = sorted(entries, key=lambda item: int(item["ccw_slot"]))
        rotations[node] = tuple(
            (
                int(item["neighbor"]),
                "H" if str(item.get("kind", "")).startswith("hourglass") else "O",
            )
            for item in ordered
        )

    return RibbonWeb(
        word=str(data.get("word") or path.stem.split("_", 1)[-1]),
        colors=colors,
        boundary_labels=boundary_labels,
        edges=edges,
        rotations=rotations,
    )


def _neighbors(web: RibbonWeb) -> Mapping[int, FrozenSet[int]]:
    result: Dict[int, Set[int]] = {node: set() for node in web.colors}
    for key in web.edges:
        source, target = tuple(key)
        result[source].add(target)
        result[target].add(source)
    return {node: frozenset(values) for node, values in result.items()}


def _canonical_cycle(nodes: Sequence[int]) -> Cycle:
    values = tuple(nodes)
    candidates = []
    for oriented in (values, tuple(reversed(values))):
        for offset in range(len(oriented)):
            candidates.append(oriented[offset:] + oriented[:offset])
    return min(candidates)


def cycle_edges(cycle: Sequence[int]) -> List[EdgeKey]:
    n = len(cycle)
    return [frozenset((cycle[i], cycle[(i + 1) % n])) for i in range(n)]


def induced_internal_six_cycles(web: RibbonWeb) -> List[Cycle]:
    neighbors = _neighbors(web)
    internal = sorted(set(web.colors) - set(web.boundary_labels))
    found: Set[Cycle] = set()

    for chosen in combinations(internal, 6):
        chosen_set = set(chosen)
        degrees = {node: len(neighbors[node] & chosen_set) for node in chosen}
        if any(d != 2 for d in degrees.values()):
            continue
        if any(len(neighbors[node] - chosen_set) != 1 for node in chosen):
            continue

        start = min(chosen)
        first_options = sorted(neighbors[start] & chosen_set)
        if len(first_options) != 2:
            continue
        ordered = [start, first_options[0]]
        while len(ordered) < 6:
            prev, curr = ordered[-2], ordered[-1]
            nxt = [n for n in (neighbors[curr] & chosen_set) - {prev} if n not in ordered]
            if len(nxt) != 1:
                break
            ordered.append(nxt[0])
        if len(ordered) == 6 and start in neighbors[ordered[-1]]:
            found.add(_canonical_cycle(ordered))
    return sorted(found)


def is_benzene(cycle: Cycle, edge_kinds: Mapping[EdgeKey, str]) -> bool:
    kinds = [edge_kinds[edge] for edge in cycle_edges(cycle)]
    return kinds in (["H", "O", "H", "O", "H", "O"], ["O", "H", "O", "H", "O", "H"])


def web_with_edge_kinds(web: RibbonWeb, edge_kinds: Mapping[EdgeKey, str]) -> RibbonWeb:
    rotations: Dict[int, Tuple[Port, ...]] = {}
    for node, ports in web.rotations.items():
        rebuilt: List[Port] = []
        distinct_neighbors = []
        for neighbor, _ in ports:
            if not distinct_neighbors or neighbor != distinct_neighbors[-1]:
                distinct_neighbors.append(neighbor)
        if len(distinct_neighbors) > 1 and distinct_neighbors[0] == distinct_neighbors[-1]:
            distinct_neighbors.pop()

        for neighbor in distinct_neighbors:
            kind = edge_kinds[frozenset((node, neighbor))]
            rebuilt.extend([(neighbor, kind)] * (2 if kind == "H" else 1))
        rotations[node] = tuple(rebuilt)

    return RibbonWeb(
        word=web.word,
        colors=dict(web.colors),
        boundary_labels=dict(web.boundary_labels),
        edges=dict(edge_kinds),
        rotations=rotations,
    )


def benzene_move_presentations(
    web: RibbonWeb, all_cycles: Sequence[Cycle]
) -> List[Tuple[RibbonWeb, Tuple[Cycle, ...]]]:
    ordered_edges = tuple(sorted(web.edges, key=lambda edge: tuple(sorted(edge))))
    initial = tuple(web.edges[edge] for edge in ordered_edges)
    queue = deque([(initial, tuple())])
    seen = {initial}
    presentations: List[Tuple[RibbonWeb, Tuple[Cycle, ...]]] = []

    while queue:
        state, path = queue.popleft()
        kinds = dict(zip(ordered_edges, state))
        presentation = web_with_edge_kinds(web, kinds)
        presentations.append((presentation, path))
        active = [cycle for cycle in all_cycles if is_benzene(cycle, kinds)]
        for cycle in active:
            toggled = dict(kinds)
            for edge in cycle_edges(cycle):
                toggled[edge] = "O" if toggled[edge] == "H" else "H"
            child = tuple(toggled[edge] for edge in ordered_edges)
            if child not in seen:
                seen.add(child)
                queue.append((child, path + (cycle,)))
    return presentations


# --- Promotion and Rotation Utilities ---

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
    row_idx, col_idx = next((r, row.index(1)) for r, row in enumerate(rows) if 1 in row)
    rows[row_idx][col_idx] = None
    while True:
        candidates: List[Tuple[int, int, int]] = []
        if col_idx + 1 < len(rows[row_idx]) and rows[row_idx][col_idx + 1] is not None:
            candidates.append((rows[row_idx][col_idx + 1], row_idx, col_idx + 1))
        if row_idx + 1 < len(rows) and col_idx < len(rows[row_idx + 1]) and rows[row_idx + 1][col_idx] is not None:
            candidates.append((rows[row_idx + 1][col_idx], row_idx + 1, col_idx))
        if not candidates:
            break
        _, next_r, next_c = min(candidates)
        rows[row_idx][col_idx] = rows[next_r][next_c]
        rows[next_r][next_c] = None
        row_idx, col_idx = next_r, next_c

    for row in rows:
        for index, value in enumerate(row):
            if value is not None:
                row[index] = value - 1
    rows[row_idx][col_idx] = 16
    return tableau_to_word([[int(v) for v in row] for row in rows])


def promotion_orbit(word: str) -> List[str]:
    result = []
    current = word
    while current not in result:
        result.append(current)
        current = promote_word_once(current)
    return result


def shifted_boundary_label(label: int, steps: int) -> int:
    return ((int(label) - 1 - steps) % 16) + 1


def rotate_point(point: Sequence[float], center: Tuple[float, float], theta: float) -> List[float]:
    x, y = float(point[0]) - center[0], float(point[1]) - center[1]
    cosine, sine = math.cos(theta), math.sin(theta)
    return [center[0] + cosine * x - sine * y, center[1] + sine * x + cosine * y]


def rotate_graph_data(data: Mapping[str, Any], promoted_word: str, steps: int) -> Dict[str, Any]:
    result = copy.deepcopy(data)
    boundary_nodes = [node for node in result.get("nodes", []) if node.get("boundary_label") is not None]
    center = (
        sum(float(n["x"]) for n in boundary_nodes) / len(boundary_nodes),
        sum(float(n["y"]) for n in boundary_nodes) / len(boundary_nodes),
    )
    theta = steps * 2.0 * math.pi / 16.0
    for node in result.get("nodes", []):
        node["x"], node["y"] = rotate_point((node["x"], node["y"]), center, theta)
        if node.get("boundary_label") is not None:
            node["boundary_label"] = shifted_boundary_label(node["boundary_label"], steps)
        terminal = node.get("growth_terminal")
        if isinstance(terminal, int) and 1 <= terminal <= 16:
            node["growth_terminal"] = shifted_boundary_label(terminal, steps)

    nodes_by_id = {int(n["id"]): n for n in result.get("nodes", [])}
    for boundary in result.get("boundary", []):
        node = nodes_by_id[int(boundary["node"])]
        boundary["label"] = int(node["boundary_label"])
        boundary["x"] = float(node["x"])
        boundary["y"] = float(node["y"])
    result.get("boundary", []).sort(key=lambda item: int(item["label"]))

    for edge in result.get("edges", []):
        if isinstance(edge.get("route"), list):
            edge["route"] = [rotate_point(pt, center, theta) for pt in edge["route"]]

    labels = result.get("boundary_labels")
    if isinstance(labels, dict):
        result["boundary_labels"] = {key: shifted_boundary_label(val, steps) for key, val in labels.items()}
    elif isinstance(labels, list):
        result["boundary_labels"] = [shifted_boundary_label(val, steps) for val in labels]

    for entries in result.get("effective_rotation_system", {}).values():
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry.get("angle"), (int, float)):
                entry["angle"] = (float(entry["angle"]) + theta) % (2.0 * math.pi)

    result["word"] = promoted_word
    result.setdefault("metadata", {})["word"] = promoted_word
    return result


def apply_presentation(data: Mapping[str, Any], presentation: RibbonWeb) -> Dict[str, Any]:
    result = copy.deepcopy(data)
    for edge in result.get("edges", []):
        key = frozenset((int(edge["src"]), int(edge["dst"])))
        kind = presentation.edges[key]
        edge["kind"] = "hourglass" if kind == "H" else "ordinary"
        edge["double"] = (kind == "H")

    # Rebuild hourglasses array and metadata
    new_hgs = []
    hg_idx = 0
    for edge in result.get("edges", []):
        if edge.get("kind") == "hourglass" or edge.get("double"):
            src_node = next(n for n in result["nodes"] if n["id"] == edge["src"])
            dst_node = next(n for n in result["nodes"] if n["id"] == edge["dst"])
            w = edge["src"] if src_node["color"] == "white" else edge["dst"]
            b = edge["dst"] if src_node["color"] == "white" else edge["src"]
            new_hgs.append({"edge": edge["id"], "white": w, "black": b})
            hg_idx += 1
    result["hourglasses"] = new_hgs
    result.setdefault("metadata", {})["hourglass_count"] = len(new_hgs)
    return result


def presentation_key(web: RibbonWeb) -> Tuple[Tuple[Tuple[int, int], str], ...]:
    return tuple(sorted((tuple(sorted(edge)), kind) for edge, kind in web.edges.items()))


def main():
    if not GRAPH_DIR.is_dir():
        raise FileNotFoundError(f"Directory not found: {GRAPH_DIR}")

    print(f"Scanning catalogue in {GRAPH_DIR}...")
    files = sorted(GRAPH_DIR.glob("*.json"))
    word_to_file: Dict[str, Path] = {}
    word_to_index: Dict[str, int] = {}

    for path in files:
        if "_" in path.stem:
            idx_str, word = path.stem.split("_", 1)
            if len(word) == 16:
                word_to_file[word] = path
                word_to_index[word] = int(idx_str)

    # Compute promotion orbits for all 24,024 words
    seen_words: Set[str] = set()
    representative_words: List[str] = []

    for word in sorted(word_to_file.keys()):
        if word not in seen_words:
            orbit = promotion_orbit(word)
            seen_words.update(orbit)
            representative_words.append(word)

    print(f"Total words: {len(word_to_file)}, Total promotion orbits: {len(representative_words)}")

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    classes: List[Dict[str, Any]] = []
    generated_files: List[Dict[str, Any]] = []
    class_sizes: Dict[int, int] = {}
    benzene_reps_found = 0

    for rep_idx, rep_word in enumerate(representative_words, start=1):
        source_path = word_to_file[rep_word]
        web = load_ribbon_web(source_path)
        all_cycles = induced_internal_six_cycles(web)
        active = [c for c in all_cycles if is_benzene(c, web.edges)]

        if not active:
            continue

        benzene_reps_found += 1
        presentations = benzene_move_presentations(web, all_cycles)
        if len(presentations) <= 1:
            continue

        class_sizes[len(presentations)] = class_sizes.get(len(presentations), 0) + 1
        original_key = presentation_key(web)
        orbit = promotion_orbit(rep_word)

        class_record: Dict[str, Any] = {
            "representative_index": rep_idx,
            "representative_word": rep_word,
            "source_global_index": word_to_index[rep_word],
            "source_json": source_path.name,
            "class_size": len(presentations),
            "promotion_orbit_size": len(orbit),
            "presentations": [],
        }

        moved_number = 0
        for presentation, path in presentations:
            if presentation_key(presentation) == original_key:
                continue
            moved_number += 1
            with source_path.open("r", encoding="utf-8") as f:
                base_json_data = json.load(f)

            moved_data = apply_presentation(base_json_data, presentation)
            pres_record: Dict[str, Any] = {
                "presentation": moved_number,
                "move_count": len(path),
                "move_path": [list(c) for c in path],
                "rotations": [],
            }

            for step, prom_word in enumerate(orbit):
                prom_idx = word_to_index.get(prom_word, 0)
                file_name = (
                    f"{prom_idx:05d}_{prom_word}"
                    f"__benzene_rep{rep_idx:04d}_p{moved_number:02d}_rho{step:02d}.json"
                )
                rotated = rotate_graph_data(moved_data, prom_word, step)
                rotated.setdefault("metadata", {})["benzene_move_presentation"] = {
                    "catalogue_representative_index": rep_idx,
                    "catalogue_representative_word": rep_word,
                    "catalogue_source_json": source_path.name,
                    "presentation": moved_number,
                    "class_size": len(presentations),
                    "move_path": [list(c) for c in path],
                    "promotion_step": step,
                    "promotion_orbit_size": len(orbit),
                    "promoted_word": prom_word,
                }

                dest_file = OUTPUT_DIR / file_name
                with dest_file.open("w", encoding="utf-8") as out_f:
                    json.dump(rotated, out_f, indent=2, sort_keys=True)

                rel_path = f"{OUTPUT_FOLDER_NAME}/{file_name}"
                rotation_rec = {
                    "word": prom_word,
                    "global_index": prom_idx,
                    "promotion_step": step,
                    "json": rel_path,
                }
                pres_record["rotations"].append(rotation_rec)
                generated_files.append({
                    **rotation_rec,
                    "representative_index": rep_idx,
                    "representative_word": rep_word,
                    "presentation": moved_number,
                    "class_size": len(presentations),
                    "move_count": len(path),
                })

            class_record["presentations"].append(pres_record)
        classes.append(class_record)

    manifest = {
        "schema": "sl4-benzene-move-presentations-v1",
        "graph_folder": GRAPH_DIR.name,
        "presentation_folder": OUTPUT_FOLDER_NAME,
        "representative_count": len(classes),
        "class_size_distribution": {str(k): v for k, v in sorted(class_sizes.items())},
        "noncatalogue_representative_presentations": sum(item["class_size"] - 1 for item in classes),
        "generated_json_count": len(generated_files),
        "classes": classes,
        "files": generated_files,
    }

    manifest_path = OUTPUT_DIR / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2, sort_keys=True)

    print("\n--- DONE ---")
    print(f"Benzene representative orbits found: {benzene_reps_found}")
    print(f"Move-classes with alternative presentations: {manifest['representative_count']}")
    print(f"Class size distribution: {manifest['class_size_distribution']}")
    print(f"Generated promoted JSON files: {manifest['generated_json_count']}")
    print(f"Created: {manifest_path}")


if __name__ == "__main__":
    main()