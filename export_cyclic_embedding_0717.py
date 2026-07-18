#!/usr/bin/env python3
"""Export a planar-embedding trace for an SL4 hourglass web.

The output separates combinatorial topology from display geometry:

* ``rotation`` is the authoritative, tag-started counterclockwise order of
  half-edges around every vertex;
* ``curve`` gives a line or cubic Bezier representative for drawing an edge;
* a wrench branch stores both the tangent replacement before untwisting and
  the rotation-preserving state after any required half-edge transpositions.

Changing a Bezier control point must never change ``rotation``.  Conversely,
an untwist must be represented explicitly as a slot transposition and a sign.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import Wrench_or_Skein_0714 as wrench


Edge = Tuple[int, int]


def edge_key(a: int, b: int) -> Edge:
    return tuple(sorted((int(a), int(b))))


def load_graph(path: Path) -> Dict[str, Any]:
    with path.open() as handle:
        return json.load(handle)


def graph_maps(data: Dict[str, Any]) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, Tuple[float, float]]]:
    nodes = {int(node["id"]): node for node in data["nodes"]}
    xy = {node: (float(record["x"]), float(record["y"])) for node, record in nodes.items()}
    return nodes, xy


def remaining_without(hourglasses: List[Dict[str, Any]], selected: Dict[str, Any]) -> List[Dict[str, Any]]:
    selected_key = wrench.hourglass_key(selected)
    return [hg for hg in hourglasses if wrench.hourglass_key(hg) != selected_key]


def curve_map(records: Iterable[Dict[str, Any]]) -> Dict[Edge, List[List[float]]]:
    return {
        edge_key(*record["edge"]): [[float(x), float(y)] for x, y in record["points"]]
        for record in records
    }


def rotation_for_state(
    data: Dict[str, Any],
    initial_adj: wrench.Adjacency,
    adj: wrench.Adjacency,
) -> Dict[int, List[Dict[str, Any]]]:
    """Return exact tag-started CCW half-edge slots for a derived state."""
    source_rotation = data["effective_rotation_system"]
    rotations: Dict[int, List[Dict[str, Any]]] = {}
    for node in sorted(adj):
        neighbors = adj[node]
        if isinstance(neighbors, list):
            rotations[node] = [
                {
                    "ccw_slot": slot,
                    "neighbor": int(neighbor),
                    "kind": "ordinary",
                    "strand": None,
                }
                for slot, neighbor in enumerate(neighbors)
            ]
            continue

        # An unexpanded hourglass endpoint still has two ordinary ports and
        # two distinct strands.  Keep the original strand slots and transport
        # the current top/bottom ordinary neighbors through their old slots.
        initial_ports = initial_adj[node]
        if not isinstance(initial_ports, dict):
            raise ValueError(f"Missing initial hourglass ports at node {node}.")
        entries: List[Dict[str, Any]] = []
        for source in sorted(source_rotation[str(node)], key=lambda item: int(item["ccw_slot"])):
            item = {
                "ccw_slot": int(source["ccw_slot"]),
                "neighbor": int(source["neighbor"]),
                "kind": str(source["kind"]),
                "strand": source.get("strand"),
            }
            if item["kind"] == "ordinary":
                port = next(
                    (name for name, value in initial_ports.items() if int(value) == item["neighbor"]),
                    None,
                )
                if port is None:
                    raise ValueError(f"Cannot identify ordinary port at hourglass node {node}.")
                item["neighbor"] = int(neighbors[port])
                item["port"] = port
            entries.append(item)
        rotations[node] = entries
    return rotations


def edge_records(
    data: Dict[str, Any],
    adj: wrench.Adjacency,
    rotations: Dict[int, List[Dict[str, Any]]],
    remaining_hourglasses: List[Dict[str, Any]],
    curves: Optional[Dict[Edge, List[List[float]]]] = None,
) -> List[Dict[str, Any]]:
    _, xy = graph_maps(data)
    curves = curves or {}
    slots: Dict[Edge, Dict[int, List[int]]] = {}
    for node, entries in rotations.items():
        for entry in entries:
            if entry["kind"] != "ordinary":
                continue
            key = edge_key(node, int(entry["neighbor"]))
            slots.setdefault(key, {}).setdefault(node, []).append(int(entry["ccw_slot"]))

    records: List[Dict[str, Any]] = []
    for key in sorted(slots):
        a, b = key
        points = curves.get(key)
        records.append(
            {
                "id": f"e:{a}-{b}",
                "kind": "ordinary",
                "endpoints": [a, b],
                "endpoint_ccw_slots": {
                    str(a): slots[key].get(a, []),
                    str(b): slots[key].get(b, []),
                },
                "curve": {
                    "kind": "cubic_bezier" if points else "line",
                    "points": points or [list(xy[a]), list(xy[b])],
                },
            }
        )

    for hg in sorted(remaining_hourglasses, key=wrench.hourglass_key):
        white, black = int(hg["white"]), int(hg["black"])
        strand_slots: Dict[str, List[int]] = {}
        for node, other in ((white, black), (black, white)):
            strand_slots[str(node)] = [
                int(entry["ccw_slot"])
                for entry in rotations[node]
                if entry["kind"] == "hourglass_strand" and int(entry["neighbor"]) == other
            ]
        records.append(
            {
                "id": f"h:{min(white, black)}-{max(white, black)}",
                "kind": "hourglass",
                "multiplicity": 2,
                "endpoints": [white, black],
                "endpoint_ccw_slots": strand_slots,
                "curve": {
                    "kind": "figure_eight_pair",
                    "centerline": [list(xy[white]), list(xy[black])],
                },
            }
        )
    return records


def serialize_state(
    name: str,
    data: Dict[str, Any],
    initial_adj: wrench.Adjacency,
    adj: wrench.Adjacency,
    remaining_hourglasses: List[Dict[str, Any]],
    curve_records: Iterable[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    nodes, _ = graph_maps(data)
    rotations = rotation_for_state(data, initial_adj, adj)
    vertex_records = []
    for node in sorted(adj):
        source = nodes[node]
        vertex_records.append(
            {
                "id": node,
                "color": source.get("color"),
                "boundary_label": source.get("boundary_label"),
                "position": [float(source["x"]), float(source["y"])],
                "tagged_ccw_rotation": rotations[node],
                "adjacency_encoding": copy.deepcopy(adj[node]),
            }
        )
    return {
        "name": name,
        "vertices": vertex_records,
        "edges": edge_records(
            data,
            adj,
            rotations,
            remaining_hourglasses,
            curve_map(curve_records),
        ),
    }


def ordinary_slot(adj: wrench.Adjacency, node: int, neighbor: int) -> Optional[Any]:
    neighbors = adj.get(int(node))
    if isinstance(neighbors, dict):
        return next(
            (str(port) for port, value in neighbors.items() if value is not None and int(value) == int(neighbor)),
            None,
        )
    if not isinstance(neighbors, list):
        return None
    try:
        return neighbors.index(int(neighbor))
    except ValueError:
        return None


def port_transport(
    before: wrench.Adjacency,
    pre_untwist: wrench.Adjacency,
    post_untwist: wrench.Adjacency,
    selected: Dict[str, Any],
    smoothing: str,
) -> List[Dict[str, Any]]:
    left, right = int(selected["left"]), int(selected["right"])
    lt, lb = int(before[left]["top"]), int(before[left]["bot"])
    rt, rb = int(before[right]["top"]), int(before[right]["bot"])
    pairings = (
        [(lt, left, rb, right), (lb, left, rt, right)]
        if smoothing == "crossing"
        else [(lt, left, rt, right), (lb, left, rb, right)]
    )
    records = []
    for a, removed_a, b, removed_b in pairings:
        for leaf, removed, replacement in ((a, removed_a, b), (b, removed_b, a)):
            records.append(
                {
                    "vertex": int(leaf),
                    "removed_neighbor": int(removed),
                    "replacement_neighbor": int(replacement),
                    "slot_before": ordinary_slot(before, leaf, removed),
                    "slot_pre_untwist": ordinary_slot(pre_untwist, leaf, replacement),
                    "slot_post_untwist": ordinary_slot(post_untwist, leaf, replacement),
                }
            )
    return records


def find_hourglass(hourglasses: List[Dict[str, Any]], value: str) -> Dict[str, Any]:
    requested = {int(part.strip()) for part in value.split(",")}
    if len(requested) != 2:
        raise ValueError("--hourglass must contain two node ids, for example 29,30.")
    return next(
        hg for hg in hourglasses if {int(hg["white"]), int(hg["black"])} == requested
    )


def export_trace(w_path: Path, x_path: Path, hourglass: str) -> Dict[str, Any]:
    w_data, x_data = load_graph(w_path), load_graph(x_path)
    w_adj, _, w_hgs = wrench.parse_web(w_path)
    x_adj, _, x_hgs = wrench.parse_web(x_path)
    _, x_xy = wrench.parse_web_metadata(x_path)
    selected = find_hourglass(x_hgs, hourglass)
    x_remaining = remaining_without(x_hgs, selected)

    branches = []
    for smoothing in ("crossing", "parallel"):
        pre_adj, pre_meta = wrench.smooth_one_hourglass_embedded(
            x_adj,
            selected,
            smoothing,
            node_xy=x_xy,
            forced_untwists=[],
        )
        post_adj, post_meta = wrench.smooth_one_hourglass_embedded(
            x_adj,
            selected,
            smoothing,
            node_xy=x_xy,
        )
        branches.append(
            {
                "smoothing": smoothing,
                "relation_multiplier": int(post_meta["relation_multiplier"]),
                "untwist_multiplier": int(post_meta["untwist_multiplier"]),
                "coefficient_multiplier": int(post_meta["coefficient_multiplier"]),
                "replacement_edges": post_meta["replacement_edges"],
                "untwists": post_meta["untwists"],
                "slot_transport": port_transport(x_adj, pre_adj, post_adj, selected, smoothing),
                "pre_untwist_state": serialize_state(
                    f"X {smoothing} tangent replacement before untwist",
                    x_data,
                    x_adj,
                    pre_adj,
                    x_remaining,
                    pre_meta["edge_curves"],
                ),
                "post_untwist_state": serialize_state(
                    f"X {smoothing} rotation-preserving representative",
                    x_data,
                    x_adj,
                    post_adj,
                    x_remaining,
                    post_meta["edge_curves"],
                ),
            }
        )

    return {
        "schema": "sl4_tagged_planar_embedding_trace_v1",
        "conventions": {
            "coordinates": "Cartesian: +x right, +y up",
            "rotation": "ccw_slot increases counterclockwise; slot 0 is the tag",
            "hourglass": "two separate half-edges with strand values 0 and 1",
            "cubic_points": "[P0, C1, C2, P3]",
            "topology_rule": "tagged_ccw_rotation is authoritative; curve crossings never redefine it",
            "replacement_rule": "C1 and C2 are tangent to the removed incident edges at P0 and P3",
            "untwist_rule": "transpose the recorded half-edge slots and multiply the coefficient by -1 per transposition",
        },
        "pair": {
            "W": {"word": w_data["word"], "source": str(w_path)},
            "X": {"word": x_data["word"], "source": str(x_path)},
        },
        "original_states": {
            "W": serialize_state("W original", w_data, w_adj, w_adj, w_hgs),
            "X": serialize_state("X original", x_data, x_adj, x_adj, x_hgs),
        },
        "move": {
            "side": "X",
            "selected_hourglass": {key: copy.deepcopy(value) for key, value in selected.items()},
            "branches": branches,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--w",
        type=Path,
        default=Path("4x4_All_graph_data/02958_1112323241342344.json"),
    )
    parser.add_argument(
        "--x",
        type=Path,
        default=Path("4x4_All_graph_data/21143_1231122413324434.json"),
    )
    parser.add_argument("--hourglass", default="29,30")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("cyclic_embedding_1112323241342344__1231122413324434_0717.json"),
    )
    args = parser.parse_args()
    output = export_trace(args.w, args.x, args.hourglass)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=False) + "\n")
    print(args.out.resolve())


if __name__ == "__main__":
    main()
