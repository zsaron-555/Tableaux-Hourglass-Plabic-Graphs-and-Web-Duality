#!/usr/bin/env python3
"""Audit the benzene-support conjectures against All_Pairings_0802.tsv.

The audit uses the graph JSONs, not rendered PNG geometry.  A benzene is an
induced internal 6-cycle whose edge kinds alternate ordinary/hourglass.  A
benzene move is modeled by toggling those six edge kinds.  It has a chain
reaction when this creates a different benzene 6-cycle that was not present
before the move.

The pairing table contains the pairs surviving the proved-zero filters.  Rows
absent from that table are therefore treated as certified zero, while every
recorded numerical value is retained verbatim.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Set, Tuple


Edge = frozenset[int]
Cycle = Tuple[int, ...]


@dataclass(frozen=True)
class GraphModel:
    word: str
    boundary_nodes: frozenset[int]
    adjacency: Mapping[int, frozenset[int]]
    edge_kind: Mapping[Edge, str]
    node_color: Mapping[int, str]
    hourglass_count: int
    internal_vertex_count: int
    cycle_rank: int


def read_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Iterable[Mapping[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def canonical_cycle(cycle: Sequence[int]) -> Cycle:
    values = list(cycle)
    rotations: List[Cycle] = []
    for oriented in (values, list(reversed(values))):
        rotations.extend(
            tuple(oriented[offset:] + oriented[:offset]) for offset in range(len(values))
        )
    return min(rotations)


def cycle_edges(cycle: Cycle) -> Tuple[Edge, ...]:
    return tuple(
        frozenset((cycle[index], cycle[(index + 1) % len(cycle)]))
        for index in range(len(cycle))
    )


def graph_model(path: Path) -> GraphModel:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    boundary_nodes = frozenset(int(item["node"]) for item in data.get("boundary", []))
    adjacency_sets: Dict[int, Set[int]] = defaultdict(set)
    edge_kind: Dict[Edge, str] = {}
    for edge in data.get("edges", []):
        source = int(edge["src"])
        target = int(edge["dst"])
        adjacency_sets[source].add(target)
        adjacency_sets[target].add(source)
        is_hourglass = edge.get("kind") == "hourglass" or bool(edge.get("double"))
        edge_kind[frozenset((source, target))] = (
            "hourglass" if is_hourglass else "ordinary"
        )

    all_nodes = {int(node["id"]) for node in data.get("nodes", [])}
    all_nodes.update(adjacency_sets)
    adjacency = {
        node: frozenset(adjacency_sets.get(node, set())) for node in sorted(all_nodes)
    }
    node_color = {
        int(node["id"]): str(node.get("color", "")) for node in data.get("nodes", [])
    }
    vertices = len(all_nodes)
    edges = len(edge_kind)
    components = component_count(adjacency)
    return GraphModel(
        word=str(data.get("word") or path.stem.split("_", 1)[-1]),
        boundary_nodes=boundary_nodes,
        adjacency=adjacency,
        edge_kind=edge_kind,
        node_color=node_color,
        hourglass_count=sum(kind == "hourglass" for kind in edge_kind.values()),
        internal_vertex_count=len(all_nodes - set(boundary_nodes)),
        cycle_rank=edges - vertices + components,
    )


def component_count(adjacency: Mapping[int, frozenset[int]]) -> int:
    unseen = set(adjacency)
    count = 0
    while unseen:
        count += 1
        stack = [unseen.pop()]
        while stack:
            current = stack.pop()
            for neighbor in adjacency.get(current, frozenset()):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
    return count


def induced_internal_six_cycles(model: GraphModel) -> List[Cycle]:
    internal = set(model.adjacency) - set(model.boundary_nodes)
    found: Set[Cycle] = set()

    def visit(start: int, path_nodes: List[int]) -> None:
        current = path_nodes[-1]
        if len(path_nodes) == 6:
            if start not in model.adjacency.get(current, frozenset()):
                return
            cycle = canonical_cycle(path_nodes)
            expected = set(cycle_edges(cycle))
            actual = {
                frozenset((cycle[left], cycle[right]))
                for left in range(6)
                for right in range(left + 1, 6)
                if cycle[right] in model.adjacency.get(cycle[left], frozenset())
            }
            if actual == expected:
                found.add(cycle)
            return

        for neighbor in model.adjacency.get(current, frozenset()):
            if neighbor not in internal:
                continue
            if neighbor == start or neighbor in path_nodes or neighbor < start:
                continue
            visit(start, path_nodes + [neighbor])

    for start in sorted(internal):
        visit(start, [start])
    return sorted(found)


def is_benzene(cycle: Cycle, edge_kind: Mapping[Edge, str]) -> bool:
    kinds = [edge_kind[edge] for edge in cycle_edges(cycle)]
    return all(kinds[index] != kinds[(index + 1) % 6] for index in range(6))


def benzene_move_reactions(
    all_cycles: Sequence[Cycle], edge_kind: Mapping[Edge, str]
) -> Dict[Cycle, Tuple[Cycle, ...]]:
    original = {cycle for cycle in all_cycles if is_benzene(cycle, edge_kind)}
    result: Dict[Cycle, Tuple[Cycle, ...]] = {}
    for moved_cycle in sorted(original):
        toggled = dict(edge_kind)
        for edge in cycle_edges(moved_cycle):
            toggled[edge] = "ordinary" if toggled[edge] == "hourglass" else "hourglass"
        after = {cycle for cycle in all_cycles if is_benzene(cycle, toggled)}
        result[moved_cycle] = tuple(sorted(after - original - {moved_cycle}))
    return result


def benzene_move_orbit(
    all_cycles: Sequence[Cycle], edge_kind: Mapping[Edge, str]
) -> Tuple[int, int]:
    """Return (number of move states, number of faces benzene somewhere in orbit)."""
    ordered_edges = tuple(sorted(edge_kind, key=lambda edge: tuple(sorted(edge))))
    initial = tuple(edge_kind[edge] for edge in ordered_edges)
    seen = {initial}
    stack = [initial]
    reachable_faces: Set[Cycle] = set()
    while stack:
        state = stack.pop()
        kinds = dict(zip(ordered_edges, state))
        active = [cycle for cycle in all_cycles if is_benzene(cycle, kinds)]
        reachable_faces.update(active)
        for cycle in active:
            toggled = dict(kinds)
            for edge in cycle_edges(cycle):
                toggled[edge] = (
                    "ordinary" if toggled[edge] == "hourglass" else "hourglass"
                )
            child = tuple(toggled[edge] for edge in ordered_edges)
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return len(seen), len(reachable_faces)


def indexed_graph_paths(graph_dir: Path) -> Dict[str, Path]:
    result: Dict[str, Path] = {}
    for path in graph_dir.glob("*.json"):
        parts = path.stem.split("_", 1)
        if len(parts) == 2 and len(parts[1]) == 16:
            result[parts[1]] = path
    return result


def numeric_value(row: Mapping[str, str]) -> int | None:
    text = row.get("final_pairing_value", "").strip()
    try:
        return int(text)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root_default = Path(__file__).resolve().parent
    parser.add_argument("--project-root", default=str(root_default))
    parser.add_argument("--pairings", default="all_pairings_0802/All_Pairings_0802.tsv")
    parser.add_argument("--representatives", default="transpose_1522_tasks_latest.tsv")
    parser.add_argument("--graph-dir", default="4x4_All_graph_data")
    parser.add_argument(
        "--w-summary-out", default="output/tsv/benzene_conjecture_W_summary_20260803.tsv"
    )
    parser.add_argument(
        "--nonzero-out", default="output/tsv/benzene_conjecture_nonzero_pairs_20260803.tsv"
    )
    parser.add_argument(
        "--summary-out", default="output/json/benzene_conjecture_audit_20260803.json"
    )
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve()
    reps = read_tsv(root / args.representatives)
    pairings = read_tsv(root / args.pairings)
    graph_paths = indexed_graph_paths(root / args.graph_dir)
    rows_by_w: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in pairings:
        rows_by_w[row["w_word"]].append(row)

    model_cache: Dict[str, GraphModel] = {}
    cycle_cache: Dict[str, List[Cycle]] = {}
    benzene_cache: Dict[str, List[Cycle]] = {}

    def features(word: str) -> Tuple[GraphModel, List[Cycle], List[Cycle]]:
        if word not in model_cache:
            model_cache[word] = graph_model(graph_paths[word])
            cycle_cache[word] = induced_internal_six_cycles(model_cache[word])
            benzene_cache[word] = [
                cycle
                for cycle in cycle_cache[word]
                if is_benzene(cycle, model_cache[word].edge_kind)
            ]
        return model_cache[word], cycle_cache[word], benzene_cache[word]

    benzene_reps: List[Dict[str, str]] = []
    for rep in reps:
        _, _, benzenes = features(rep["w_word"])
        if benzenes:
            benzene_reps.append(rep)

    nonzero_rows: List[Dict[str, object]] = []
    w_summary: List[Dict[str, object]] = []
    for rep in benzene_reps:
        w_word = rep["w_word"]
        transpose_word = rep["x_word"]
        w_model, all_cycles, w_benzenes = features(w_word)
        reactions = benzene_move_reactions(all_cycles, w_model.edge_kind)
        move_orbit_state_count, reachable_benzene_face_count = benzene_move_orbit(
            all_cycles, w_model.edge_kind
        )
        reaction_targets = {cycle for targets in reactions.values() for cycle in targets}
        chain_sources = sum(bool(targets) for targets in reactions.values())
        chain_reaction = bool(reaction_targets)

        rows = rows_by_w.get(w_word, [])
        nonzero = [row for row in rows if (numeric_value(row) or 0) != 0]
        unresolved = [row for row in rows if numeric_value(row) is None]
        transpose_row = next((row for row in rows if row["x_word"] == transpose_word), None)
        transpose_value = numeric_value(transpose_row) if transpose_row else 0
        predicted_count = 3 if chain_reaction else 2
        orbit_predicted_count = 1 + reachable_benzene_face_count
        observed_count = len(nonzero)

        for row in nonzero:
            x_word = row["x_word"]
            x_model, _, x_benzenes = features(x_word)
            nonzero_rows.append(
                {
                    "w_rep_index": rep["w_idx"],
                    "w_word": w_word,
                    "w_transpose_word": transpose_word,
                    "w_benzene_count": len(w_benzenes),
                    "w_chain_reaction": "yes" if chain_reaction else "no",
                    "w_chain_source_count": chain_sources,
                    "w_reaction_target_count": len(reaction_targets),
                    "x_word": x_word,
                    "x_index": row["x_index"],
                    "pairing_value": row["final_pairing_value"],
                    "is_transpose": "yes" if x_word == transpose_word else "no",
                    "x_benzene_count": len(x_benzenes),
                    "x_hourglass_count": x_model.hourglass_count,
                    "x_cycle_rank": x_model.cycle_rank,
                    "used_double_trident": row["used_three_strand_relation"],
                    "warning": row["pairing_value_warning"],
                    "status": row["status"],
                }
            )

        verdict = "matches_support_count" if observed_count == predicted_count else "mismatch"
        if unresolved:
            verdict = "inconclusive_incomplete_rows"
        w_summary.append(
            {
                "w_rep_index": rep["w_idx"],
                "w_word": w_word,
                "transpose_word": transpose_word,
                "w_benzene_count": len(w_benzenes),
                "induced_internal_six_cycle_count": len(all_cycles),
                "chain_reaction": "yes" if chain_reaction else "no",
                "chain_source_count": chain_sources,
                "reaction_target_count": len(reaction_targets),
                "benzene_move_orbit_state_count": move_orbit_state_count,
                "reachable_benzene_face_count": reachable_benzene_face_count,
                "predicted_nonzero_count": predicted_count,
                "orbit_predicted_nonzero_count": orbit_predicted_count,
                "observed_nonzero_count": observed_count,
                "transpose_value": transpose_value,
                "transpose_is_nonzero": "yes" if transpose_value else "no",
                "nonzero_x_words": ",".join(row["x_word"] for row in nonzero),
                "nonzero_values": ",".join(row["final_pairing_value"] for row in nonzero),
                "recorded_survivor_rows": len(rows),
                "incomplete_row_count": len(unresolved),
                "support_count_verdict": verdict,
                "orbit_support_count_verdict": (
                    "matches_support_count"
                    if observed_count == orbit_predicted_count
                    else "mismatch"
                ),
            }
        )

    w_fields = [
        "w_rep_index", "w_word", "transpose_word", "w_benzene_count",
        "induced_internal_six_cycle_count", "chain_reaction", "chain_source_count",
        "reaction_target_count", "benzene_move_orbit_state_count",
        "reachable_benzene_face_count", "predicted_nonzero_count",
        "orbit_predicted_nonzero_count", "observed_nonzero_count",
        "transpose_value", "transpose_is_nonzero", "nonzero_x_words", "nonzero_values",
        "recorded_survivor_rows", "incomplete_row_count", "support_count_verdict",
        "orbit_support_count_verdict",
    ]
    nonzero_fields = [
        "w_rep_index", "w_word", "w_transpose_word", "w_benzene_count",
        "w_chain_reaction", "w_chain_source_count", "w_reaction_target_count",
        "x_word", "x_index", "pairing_value", "is_transpose", "x_benzene_count",
        "x_hourglass_count", "x_cycle_rank", "used_double_trident", "warning", "status",
    ]
    write_tsv(root / args.w_summary_out, w_summary, w_fields)
    write_tsv(root / args.nonzero_out, nonzero_rows, nonzero_fields)

    summary = {
        "source_pairing_table": str((root / args.pairings).resolve()),
        "source_pairing_rows": len(pairings),
        "benzene_representative_count": len(benzene_reps),
        "chain_reaction_representative_count": sum(
            row["chain_reaction"] == "yes" for row in w_summary
        ),
        "isolated_benzene_representative_count": sum(
            row["chain_reaction"] == "no" for row in w_summary
        ),
        "support_count_verdicts": dict(Counter(row["support_count_verdict"] for row in w_summary)),
        "orbit_support_count_verdicts": dict(
            Counter(row["orbit_support_count_verdict"] for row in w_summary)
        ),
        "benzene_move_orbit_state_count_distribution": dict(
            sorted(Counter(int(row["benzene_move_orbit_state_count"]) for row in w_summary).items())
        ),
        "reachable_benzene_face_count_distribution": dict(
            sorted(Counter(int(row["reachable_benzene_face_count"]) for row in w_summary).items())
        ),
        "observed_nonzero_count_distribution": dict(
            sorted(Counter(int(row["observed_nonzero_count"]) for row in w_summary).items())
        ),
        "predicted_nonzero_count_distribution": dict(
            sorted(Counter(int(row["predicted_nonzero_count"]) for row in w_summary).items())
        ),
        "transpose_nonzero_count": sum(
            row["transpose_is_nonzero"] == "yes" for row in w_summary
        ),
        "nonzero_pair_count": len(nonzero_rows),
        "nonzero_X_benzene_count_distribution": dict(
            sorted(Counter(int(row["x_benzene_count"]) for row in nonzero_rows).items())
        ),
        "nonzero_pair_value_distribution": dict(
            sorted(Counter(int(row["pairing_value"]) for row in nonzero_rows).items())
        ),
        "double_trident_nonzero_pair_count": sum(
            row["used_double_trident"] == "yes" for row in nonzero_rows
        ),
        "definitions": {
            "benzene": "induced internal 6-cycle with alternating ordinary/hourglass edge kinds",
            "benzene_move": "toggle ordinary/hourglass kinds on all six edges of a benzene cycle",
            "chain_reaction": "a benzene move creates a distinct new benzene cycle that was absent before",
            "support_count_test": "2 nonzero X for no chain reaction; 3 for a chain reaction",
        },
        "limitations": [
            "This audit tests the support count and graph features of nonzero X rows.",
            "It does not identify an arbitrary X as Surgery(W)^T because no certified surgery-to-word map is currently implemented.",
            "Signs are recorded but are not used in the support-count verdict.",
        ],
        "W_summary_output": str((root / args.w_summary_out).resolve()),
        "nonzero_pairs_output": str((root / args.nonzero_out).resolve()),
    }
    summary_path = root / args.summary_out
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
