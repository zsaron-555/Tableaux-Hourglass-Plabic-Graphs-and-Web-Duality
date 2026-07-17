#!/usr/bin/env python3
"""Expand hourglass webs using the BCGMMW Figure 4 wrench relation.

This script works with the primal hourglass web JSONs produced by the SL4
renderer.  Each hourglass is treated as the local wrench piece: remove the two
hourglass endpoints and replace the four incident ordinary half-edges by

    crossing smoothing  -  parallel smoothing.

Supported Figure 43 four-cycle rewrites are separate from the local wrench
relation; the implemented left/right-hourglass case is horizontal - 2 vertical.

The optional reference pruning is deliberately separate from the local wrench
relation, so the expansion can be inspected without hidden filtering.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import itertools
import os
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Set, Tuple


Adjacency = Dict[int, Any]
BoundaryLabels = Dict[int, int]
Hourglass = Dict[str, Any]
NodeColors = Dict[int, str]
NodeXY = Dict[int, Tuple[float, float]]

APP_DIR = Path(__file__).resolve().parent
VALUE_ONLY_MODE = os.environ.get("HG_VALUE_ONLY", "") == "1"


def term_history(term: Dict[str, Any]) -> List[Dict[str, Any]]:
    if VALUE_ONLY_MODE:
        return []
    return term.get("history", [])


def extend_history(term: Dict[str, Any], move: Dict[str, Any]) -> List[Dict[str, Any]]:
    if VALUE_ONLY_MODE:
        return []
    return term.get("history", []) + [move]

DEFAULT_PROJECT_ROOTS = [
    Path(os.environ.get("PROBLEM3_ROOT", APP_DIR)).expanduser().resolve(),
    Path.cwd().resolve(),
]

GRAPH_DATA_DIRS = [
    "hourglass_disk_4x4_promotion_reps_graph_data",
    "hourglass_disk_4x4_transpose_words_graph_data",
    "hourglass_disk_4x3_graph_data",
]


def _as_int_key_map(items: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {int(item["id"]): item for item in items}


def resolve_json_path(name_or_path: str, project_root: Optional[Path] = None) -> Path:
    """Resolve either a path or a graph-data filename such as 0447_...json."""
    candidate = Path(name_or_path).expanduser()
    if candidate.exists():
        return candidate

    roots = [project_root] if project_root else []
    roots.extend(DEFAULT_PROJECT_ROOTS)
    seen: Set[Path] = set()
    for root in roots:
        if root is None:
            continue
        root = root.expanduser()
        if root in seen:
            continue
        seen.add(root)
        for subdir in ["", *GRAPH_DATA_DIRS]:
            path = root / subdir / name_or_path
            if path.exists():
                return path

    raise FileNotFoundError(f"Could not find JSON file: {name_or_path}")


def ordinary_neighbors_from_rotation(node_id: int, rot_sys: Dict[str, Any]) -> List[int]:
    entries = sorted(rot_sys[str(node_id)], key=lambda item: item["ccw_slot"])
    ordinary = [int(item["neighbor"]) for item in entries if item["kind"] == "ordinary"]
    if len(ordinary) != 2:
        raise ValueError(
            f"Hourglass endpoint {node_id} should have exactly two ordinary neighbors; "
            f"found {ordinary}."
        )
    return ordinary


def _node_xy(node_id: int, nodes: Dict[int, Dict[str, Any]]) -> Tuple[float, float]:
    node = nodes[node_id]
    return float(node["x"]), float(node["y"])


def _dot_with_perp(
    endpoint: int,
    neighbor: int,
    perp: Tuple[float, float],
    nodes: Dict[int, Dict[str, Any]],
) -> float:
    ex, ey = _node_xy(endpoint, nodes)
    nx, ny = _node_xy(neighbor, nodes)
    return (nx - ex) * perp[0] + (ny - ey) * perp[1]


def orient_hourglass_ports(
    white: int,
    black: int,
    nodes: Dict[int, Dict[str, Any]],
    rot_sys: Dict[str, Any],
    left_endpoint: str,
    local_case: str = "",
) -> Hourglass:
    """Name the four ports around one hourglass.

    The top/bottom split is geometric: use the line from the chosen left
    endpoint to the chosen right endpoint as the local horizontal axis.  The
    two ordinary neighbors on each side are then ordered by their projection on
    the perpendicular axis.  This avoids relying on a fragile rotation-slot
    offset and makes the Figure 4 pairing explicit.
    """
    if left_endpoint not in {"white", "black"}:
        raise ValueError("left_endpoint must be 'white' or 'black'.")

    left = white if left_endpoint == "white" else black
    right = black if left_endpoint == "white" else white

    lx, ly = _node_xy(left, nodes)
    rx, ry = _node_xy(right, nodes)
    ax, ay = rx - lx, ry - ly
    norm = math.hypot(ax, ay)
    if norm == 0:
        raise ValueError(f"Hourglass endpoints {white}, {black} have identical coordinates.")
    perp = (-ay / norm, ax / norm)

    left_neighbors = ordinary_neighbors_from_rotation(left, rot_sys)
    right_neighbors = ordinary_neighbors_from_rotation(right, rot_sys)

    left_sorted = sorted(
        left_neighbors,
        key=lambda n: _dot_with_perp(left, n, perp, nodes),
        reverse=True,
    )
    # Use the same geometric perpendicular direction at both endpoints.
    # Reversing the right endpoint here swaps the mathematical meanings of the
    # two smoothings: the branch named ``crossing`` becomes top-to-top and the
    # branch named ``parallel`` becomes top-to-bottom.  Keeping both endpoint
    # orders geometric makes the names, pictures, and coefficients agree.
    right_sorted = sorted(
        right_neighbors,
        key=lambda n: _dot_with_perp(right, n, perp, nodes),
        reverse=True,
    )

    ports = {
        "white": white,
        "black": black,
        "left": left,
        "right": right,
        "left_top": left_sorted[0],
        "left_bot": left_sorted[1],
        "right_top": right_sorted[0],
        "right_bot": right_sorted[1],
        "left_endpoint": left_endpoint,
        "local_case": local_case,
    }
    if len({ports["left_top"], ports["left_bot"], ports["right_top"], ports["right_bot"]}) < 4:
        raise ValueError(f"Hourglass {white}-{black} has repeated ordinary ports: {ports}")
    return ports


def parse_web(
    filepath: str | Path,
    *,
    left_endpoint: str = "black",
) -> Tuple[Adjacency, BoundaryLabels, List[Hourglass]]:
    with Path(filepath).open("r") as handle:
        data = json.load(handle)

    schema = data.get("schema", "")
    if "dual" in schema or "boundary" not in data:
        raise ValueError(
            f"Loaded a dual or non-primal graph file: {filepath}\n"
            "The wrench expansion needs the primal hourglass web JSON."
        )

    nodes = _as_int_key_map(data["nodes"])
    rot_sys = data.get("effective_rotation_system", {})
    if not rot_sys:
        raise ValueError(f"{filepath} has no effective_rotation_system.")

    boundary_labels = {int(b["node"]): int(b["label"]) for b in data["boundary"]}
    adj: Adjacency = {int(n["id"]): [] for n in data["nodes"]}

    hourglasses: List[Hourglass] = []
    hourglass_nodes: Set[int] = set()
    for h in data.get("hourglasses", []):
        white = int(h["white"])
        black = int(h["black"])
        hourglass_nodes.update({white, black})
        local_case = str(nodes[white].get("local_case") or nodes[black].get("local_case") or "")
        hg = orient_hourglass_ports(white, black, nodes, rot_sys, left_endpoint, local_case)
        hourglasses.append(hg)
        adj[white] = {"top": None, "bot": None}
        adj[black] = {"top": None, "bot": None}

    for edge in data["edges"]:
        if edge.get("double", False):
            continue
        u, v = int(edge["src"]), int(edge["dst"])
        if isinstance(adj[u], list):
            adj[u].append(v)
        if isinstance(adj[v], list):
            adj[v].append(u)

    for hg in hourglasses:
        left = int(hg["left"])
        right = int(hg["right"])
        adj[left]["top"] = int(hg["left_top"])
        adj[left]["bot"] = int(hg["left_bot"])
        adj[right]["top"] = int(hg["right_top"])
        adj[right]["bot"] = int(hg["right_bot"])

    validate_adjacency(adj)
    return adj, boundary_labels, hourglasses


def parse_web_metadata(filepath: str | Path) -> Tuple[NodeColors, NodeXY]:
    """Return fixed node metadata needed by local relation detectors."""
    with Path(filepath).open("r") as handle:
        data = json.load(handle)
    colors = {int(node["id"]): str(node.get("color", "")) for node in data.get("nodes", [])}
    xy = {
        int(node["id"]): (float(node.get("x", 0.0)), float(node.get("y", 0.0)))
        for node in data.get("nodes", [])
    }
    return colors, xy


def neighbor_list(neighbors: Any) -> List[int]:
    if isinstance(neighbors, dict):
        return [int(v) for v in neighbors.values() if v is not None]
    return [int(v) for v in neighbors]


def validate_adjacency(adj: Adjacency) -> None:
    for u, neighbors in adj.items():
        for v in neighbor_list(neighbors):
            if v not in adj:
                raise ValueError(f"Adjacency references missing node {v} from node {u}.")
            if u not in neighbor_list(adj[v]):
                raise ValueError(f"Adjacency is not reciprocal: {u} -> {v}, but not {v} -> {u}.")


def drop_nonreciprocal_references(adj: Adjacency) -> Adjacency:
    """Return a copy with one-sided adjacency artifacts removed."""
    new_adj = copy.deepcopy(adj)
    for u, neighbors in list(new_adj.items()):
        if isinstance(neighbors, dict):
            for port, v in list(neighbors.items()):
                if v is None or v not in new_adj or u not in neighbor_list(new_adj[v]):
                    neighbors[port] = None
        else:
            new_adj[u] = [
                int(v)
                for v in neighbors
                if v in new_adj and u in neighbor_list(new_adj[v])
            ]
    return new_adj


def clean_hourglasses_for_adj(adj: Adjacency, hourglasses: List[Hourglass]) -> List[Hourglass]:
    cleaned: List[Hourglass] = []
    for hg in hourglasses:
        left = int(hg["left"])
        right = int(hg["right"])
        if left not in adj or right not in adj:
            continue
        if not isinstance(adj[left], dict) or not isinstance(adj[right], dict):
            continue
        # Keep the metadata whenever the two hourglass endpoint records still
        # exist.  Some later local rewrites can temporarily change one ordinary
        # port before the branch is colored; discarding the metadata here leaves
        # orphan dict-shaped endpoints that the coloring stage quite rightly
        # rejects.  Individual expansion routines still validate the ports
        # before applying a wrench move.
        cleaned.append(hg)
    return cleaned


def normalize_pair_term(term: Dict[str, Any]) -> Dict[str, Any]:
    x_adj = drop_nonreciprocal_references(term["x_adj"])
    w_adj = drop_nonreciprocal_references(term["w_adj"])
    return {
        **term,
        "x_adj": x_adj,
        "w_adj": w_adj,
        "x_remaining": clean_hourglasses_for_adj(x_adj, term["x_remaining"]),
        "w_remaining": clean_hourglasses_for_adj(w_adj, term["w_remaining"]),
    }


def sort_hourglasses_by_boundary_distance(
    adj: Adjacency,
    boundary_labels: BoundaryLabels,
    hourglasses: List[Hourglass],
) -> List[Hourglass]:
    simple_adj: Dict[int, Set[int]] = {n: set() for n in adj}
    for u, neighbors in adj.items():
        for v in neighbor_list(neighbors):
            simple_adj[u].add(v)
            simple_adj[v].add(u)

    distances = {n: 0 for n in boundary_labels}
    queue: deque[int] = deque(boundary_labels)
    while queue:
        curr = queue.popleft()
        for neighbor in simple_adj.get(curr, set()):
            if neighbor not in distances:
                distances[neighbor] = distances[curr] + 1
                queue.append(neighbor)

    return sorted(
        hourglasses,
        key=lambda hg: min(distances.get(int(hg["white"]), 999), distances.get(int(hg["black"]), 999)),
    )


def get_forks(adj: Adjacency, boundary_labels: BoundaryLabels) -> Set[frozenset[int]]:
    forks: Set[frozenset[int]] = set()
    for node_id, neighbors in adj.items():
        if node_id in boundary_labels:
            continue
        boundary_neighbors = [boundary_labels[n] for n in neighbor_list(neighbors) if n in boundary_labels]
        for i in range(len(boundary_neighbors)):
            for j in range(i + 1, len(boundary_neighbors)):
                forks.add(frozenset([boundary_neighbors[i], boundary_neighbors[j]]))
    return forks


def get_direct_boundary_edges(adj: Adjacency, boundary_labels: BoundaryLabels) -> Set[frozenset[int]]:
    direct_edges: Set[frozenset[int]] = set()
    for u, neighbors in adj.items():
        if u not in boundary_labels:
            continue
        for v in neighbor_list(neighbors):
            if v in boundary_labels and u != v:
                direct_edges.add(frozenset([boundary_labels[u], boundary_labels[v]]))
    return direct_edges


def replace_neighbor(node: int, old_neighbor: int, new_neighbor: int, adj: Adjacency) -> None:
    neighbors = adj[node]
    if isinstance(neighbors, dict):
        for port, neighbor in neighbors.items():
            if neighbor == old_neighbor:
                neighbors[port] = new_neighbor
                return
    else:
        replaced = False
        for i, neighbor in enumerate(neighbors):
            if neighbor == old_neighbor:
                neighbors[i] = new_neighbor
                replaced = True
        if replaced:
            return
    raise ValueError(f"Node {node} is not adjacent to {old_neighbor}; cannot replace by {new_neighbor}.")


def splice_pair(adj: Adjacency, a_endpoint: int, a_port: int, b_endpoint: int, b_port: int) -> None:
    replace_neighbor(a_port, a_endpoint, b_port, adj)
    replace_neighbor(b_port, b_endpoint, a_port, adj)


def _edge_pair(u: int, v: int) -> Tuple[int, int]:
    return tuple(sorted((int(u), int(v))))


def ordinary_edge_pairs(adj: Adjacency) -> Set[Tuple[int, int]]:
    return {_edge_pair(u, v) for u, ns in adj.items() for v in neighbor_list(ns)}


def _hourglass_pairs(hourglasses: List[Hourglass]) -> Set[Tuple[int, int]]:
    return {_edge_pair(hg["white"], hg["black"]) for hg in hourglasses}


def _ordered_cycle_vertices(vertices: Iterable[int], node_xy: NodeXY) -> List[int]:
    verts = list(vertices)
    cx = sum(node_xy[v][0] for v in verts) / len(verts)
    cy = sum(node_xy[v][1] for v in verts) / len(verts)
    ordered = sorted(verts, key=lambda v: math.atan2(node_xy[v][1] - cy, node_xy[v][0] - cx), reverse=True)
    start = min(range(len(ordered)), key=lambda i: (-node_xy[ordered[i]][1], node_xy[ordered[i]][0]))
    return ordered[start:] + ordered[:start]


def detect_figure43_moves(
    adj: Adjacency,
    remaining_hourglasses: List[Hourglass],
    node_colors: Optional[NodeColors],
    node_xy: Optional[NodeXY],
) -> List[Dict[str, Any]]:
    """Detect live Figure 43 rewrites that the engine knows how to apply.

    At present this applies the bottom row of the screenshot/Figure 43:
    ordinary top and bottom sides, hourglass left and right sides, alternating
    black-white-black-white vertices.  At q=1 the local relation is

        horizontal term - 2 * vertical term.

    The other Figure 43 rows are deliberately not guessed here; they should be
    added as separate RHS constructors once their port-level rewrites are
    specified.
    """
    if not node_colors or not node_xy:
        return []
    ordinary = ordinary_edge_pairs(adj)
    hourglass_pairs = _hourglass_pairs(remaining_hourglasses)
    usable = ordinary | hourglass_pairs
    combined: Dict[int, Set[int]] = {node: set() for node in adj}
    for u, v in usable:
        if u in adj and v in adj:
            combined.setdefault(u, set()).add(v)
            combined.setdefault(v, set()).add(u)

    candidates: Set[Tuple[int, int, int, int]] = set()
    for a in combined:
        for b in combined.get(a, set()):
            for c in combined.get(b, set()):
                if c in {a, b}:
                    continue
                for d in combined.get(c, set()):
                    if d in {a, b, c}:
                        continue
                    if a in combined.get(d, set()):
                        candidates.add(tuple(sorted((a, b, c, d))))

    matches: List[Dict[str, Any]] = []
    seen: Set[Tuple[int, int, int, int]] = set()
    for quad in candidates:
        if any(v not in node_xy or v not in node_colors for v in quad):
            continue
        ordered = _ordered_cycle_vertices(quad, node_xy)
        sides = [
            _edge_pair(ordered[0], ordered[1]),
            _edge_pair(ordered[1], ordered[2]),
            _edge_pair(ordered[2], ordered[3]),
            _edge_pair(ordered[3], ordered[0]),
        ]
        if not all(side in usable for side in sides):
            continue
        if _edge_pair(ordered[0], ordered[2]) in usable or _edge_pair(ordered[1], ordered[3]) in usable:
            continue
        side_types = tuple("hourglass" if side in hourglass_pairs else "ordinary" for side in sides)
        colors = tuple(node_colors.get(v, "") for v in ordered)
        if side_types != ("ordinary", "hourglass", "ordinary", "hourglass"):
            continue
        if colors != ("black", "white", "black", "white"):
            continue
        ports = _figure43_external_ports(adj, *ordered)
        if ports is None:
            continue
        rhs_terms = [
            {"smoothing": "horizontal", "coefficient_multiplier": 1},
            {"smoothing": "vertical", "coefficient_multiplier": -2},
        ]
        if not all(
            _figure43_pairings_are_bipartite(
                _figure43_pairings_from_ports(ports, str(rhs["smoothing"])),
                ports,
                node_colors,
            )
            for rhs in rhs_terms
        ):
            continue
        key = tuple(ordered)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            {
                "rule": "GPPSS_F43_left_right_hourglasses",
                "vertices_top_right_bottom_left": ordered,
                "side_types_top_right_bottom_left": list(side_types),
                "colors_top_right_bottom_left": list(colors),
                "external_ports_top_right_bottom_left": [
                    ports["top_left"],
                    ports["top_right"],
                    ports["bottom_right"],
                    ports["bottom_left"],
                ],
                "external_port_colors_top_right_bottom_left": [
                    node_colors.get(ports["top_left"]),
                    node_colors.get(ports["top_right"]),
                    node_colors.get(ports["bottom_right"]),
                    node_colors.get(ports["bottom_left"]),
                ],
                "rhs_terms": rhs_terms,
            }
        )
    return matches


def _external_port_for_cycle_vertex(adj: Adjacency, vertex: int, cycle_neighbors: Iterable[int]) -> Optional[int]:
    excluded = {int(n) for n in cycle_neighbors}
    candidates = [n for n in neighbor_list(adj.get(vertex, [])) if int(n) not in excluded]
    if len(candidates) != 1:
        return None
    return int(candidates[0])


def _colors_are_opposite(color_a: Optional[str], color_b: Optional[str]) -> bool:
    if color_a not in {"black", "white"} or color_b not in {"black", "white"}:
        return True
    return color_a != color_b


def _figure43_external_ports(
    adj: Adjacency,
    tl: int,
    tr: int,
    br: int,
    bl: int,
) -> Optional[Dict[str, int]]:
    # The four outside half-edges are determined by the Figure 43 square, not
    # by a geometric guess.  Exclude both local cycle neighbors at each corner:
    # one ordinary side and one hourglass side.
    ext_tl = _external_port_for_cycle_vertex(adj, tl, (tr, bl))
    ext_tr = _external_port_for_cycle_vertex(adj, tr, (tl, br))
    ext_br = _external_port_for_cycle_vertex(adj, br, (tr, bl))
    ext_bl = _external_port_for_cycle_vertex(adj, bl, (br, tl))
    if None in {ext_tl, ext_tr, ext_br, ext_bl}:
        return None
    return {
        "top_left": int(ext_tl),
        "top_right": int(ext_tr),
        "bottom_right": int(ext_br),
        "bottom_left": int(ext_bl),
    }


def _figure43_pairings_from_ports(
    ports: Dict[str, int],
    smoothing: str,
) -> List[Tuple[str, str]]:
    if smoothing == "horizontal":
        # The +1 term in the displayed Figure 43 row: the two outside top
        # ports are joined, and the two outside bottom ports are joined.
        return [("top_left", "top_right"), ("bottom_left", "bottom_right")]
    if smoothing == "vertical":
        # The -2 term: the two outside left ports are joined, and the two
        # outside right ports are joined.
        return [("top_left", "bottom_left"), ("top_right", "bottom_right")]
    raise ValueError("Figure 43 smoothing must be horizontal or vertical.")


def _figure43_pairings_are_bipartite(
    pairings: Iterable[Tuple[str, str]],
    ports: Dict[str, int],
    node_colors: Optional[NodeColors],
) -> bool:
    if not node_colors:
        return True
    for a_name, b_name in pairings:
        a = ports[a_name]
        b = ports[b_name]
        if not _colors_are_opposite(node_colors.get(a), node_colors.get(b)):
            return False
    return True


def _splice_external_pair(adj: Adjacency, local_a: int, ext_a: int, local_b: int, ext_b: int) -> None:
    if ext_a == ext_b:
        raise ValueError("Figure 43 rewrite would create a self-loop external splice.")
    replace_neighbor(ext_a, local_a, ext_b, adj)
    replace_neighbor(ext_b, local_b, ext_a, adj)


def apply_figure43_move(
    adj: Adjacency,
    remaining_hourglasses: List[Hourglass],
    match: Dict[str, Any],
    smoothing: str,
) -> Tuple[Adjacency, List[Hourglass]]:
    """Apply a supported Figure 43 local rewrite to one web state."""
    if match.get("rule") != "GPPSS_F43_left_right_hourglasses":
        raise ValueError(f"Unsupported Figure 43 rule: {match.get('rule')}")
    if smoothing not in {"horizontal", "vertical"}:
        raise ValueError("Figure 43 smoothing must be horizontal or vertical.")

    tl, tr, br, bl = [int(v) for v in match["vertices_top_right_bottom_left"]]
    new_adj = copy.deepcopy(adj)
    ports = _figure43_external_ports(new_adj, tl, tr, br, bl)
    if ports is None:
        raise ValueError("Figure 43 rewrite could not identify four external ports.")

    local_by_port = {
        "top_left": tl,
        "top_right": tr,
        "bottom_right": br,
        "bottom_left": bl,
    }
    pairings = _figure43_pairings_from_ports(ports, smoothing)
    port_color_list = match.get("external_port_colors_top_right_bottom_left")
    if isinstance(port_color_list, list) and len(port_color_list) == 4:
        port_colors = {
            "top_left": port_color_list[0],
            "top_right": port_color_list[1],
            "bottom_right": port_color_list[2],
            "bottom_left": port_color_list[3],
        }
        for a_name, b_name in pairings:
            if not _colors_are_opposite(port_colors.get(a_name), port_colors.get(b_name)):
                raise ValueError(
                    "Figure 43 rewrite would connect same-colored outside ports: "
                    f"{a_name}-{b_name} for {smoothing}."
                )

    for a_name, b_name in pairings:
        _splice_external_pair(
            new_adj,
            local_by_port[a_name],
            ports[a_name],
            local_by_port[b_name],
            ports[b_name],
        )

    for vertex in (tl, tr, br, bl):
        if vertex in new_adj:
            del new_adj[vertex]
    new_adj = drop_nonreciprocal_references(new_adj)
    new_hgs = [
        hg
        for hg in remaining_hourglasses
        if _edge_pair(hg["white"], hg["black"]) not in {_edge_pair(tr, br), _edge_pair(bl, tl)}
    ]
    new_hgs = clean_hourglasses_for_adj(new_adj, new_hgs)
    validate_adjacency(new_adj)
    return new_adj, new_hgs


ANTISYMMETRIZER_TERMS: List[Tuple[Tuple[int, int, int], int]] = [
    ((1, 2, 3), -1),
    ((1, 3, 2), 1),
    ((2, 1, 3), 1),
    ((2, 3, 1), -1),
    ((3, 1, 2), -1),
    ((3, 2, 1), 1),
]


def _ordered_ports_across_edge(
    center: int,
    opposite: int,
    ports: Iterable[int],
    node_xy: Optional[NodeXY],
) -> List[int]:
    ports = [int(port) for port in ports]
    if not node_xy or center not in node_xy or opposite not in node_xy:
        return sorted(ports)
    cx, cy = node_xy[center]
    ox, oy = node_xy[opposite]
    ax, ay = ox - cx, oy - cy
    norm = math.hypot(ax, ay)
    if norm == 0:
        return sorted(ports)
    perp = (-ay / norm, ax / norm)

    def key(port: int) -> Tuple[float, float, int]:
        if port not in node_xy:
            return (0.0, 0.0, port)
        px, py = node_xy[port]
        proj = (px - cx) * perp[0] + (py - cy) * perp[1]
        along = (px - cx) * ax / norm + (py - cy) * ay / norm
        return (-proj, along, port)

    return sorted(ports, key=key)


def _all_antisym_pairings_are_bipartite(
    input_ports: List[int],
    output_ports: List[int],
    node_colors: Optional[NodeColors],
) -> bool:
    if not node_colors:
        return True
    for left in input_ports:
        for right in output_ports:
            if not _colors_are_opposite(node_colors.get(left), node_colors.get(right)):
                return False
    return True


def detect_antisymmetrizer_moves(
    adj: Adjacency,
    node_colors: Optional[NodeColors],
    node_xy: Optional[NodeXY],
) -> List[Dict[str, Any]]:
    """Detect the white-black 4-valent antisymmetrizer relation.

    This is the relation from the supplied JSON: a 4-valent white vertex joined
    by one internal edge to a 4-valent black vertex expands into the six
    permutations of the three outside strands with coefficient -sign(sigma).
    """
    if not node_colors:
        return []
    matches: List[Dict[str, Any]] = []
    seen: Set[Tuple[int, int]] = set()
    for u, neighbors in adj.items():
        for v in neighbor_list(neighbors):
            edge = _edge_pair(u, v)
            if edge in seen:
                continue
            seen.add(edge)
            cu = node_colors.get(int(u))
            cv = node_colors.get(int(v))
            if {cu, cv} != {"white", "black"}:
                continue
            white = int(u) if cu == "white" else int(v)
            black = int(v) if white == int(u) else int(u)
            white_neighbors = neighbor_list(adj.get(white, []))
            black_neighbors = neighbor_list(adj.get(black, []))
            if len(white_neighbors) != 4 or len(black_neighbors) != 4:
                continue
            input_ports = [int(port) for port in white_neighbors if int(port) != black]
            output_ports = [int(port) for port in black_neighbors if int(port) != white]
            if len(input_ports) != 3 or len(output_ports) != 3:
                continue
            if len(set(input_ports + output_ports)) != 6:
                continue
            input_ports = _ordered_ports_across_edge(white, black, input_ports, node_xy)
            output_ports = _ordered_ports_across_edge(black, white, output_ports, node_xy)
            if not _all_antisym_pairings_are_bipartite(input_ports, output_ports, node_colors):
                continue
            matches.append(
                {
                    "rule": "WB_4VALENT_ANTISYMMETRIZER",
                    "white": white,
                    "black": black,
                    "vertices": [white, black],
                    "input_ports": input_ports,
                    "output_ports": output_ports,
                    "rhs_terms": [
                        {
                            "permutation": list(perm),
                            "coefficient_multiplier": coeff,
                            "smoothing": "perm_" + "".join(str(x) for x in perm),
                        }
                        for perm, coeff in ANTISYMMETRIZER_TERMS
                    ],
                }
            )
    return matches


def apply_antisymmetrizer_move(
    adj: Adjacency,
    match: Dict[str, Any],
    permutation: Iterable[int],
) -> Adjacency:
    if match.get("rule") != "WB_4VALENT_ANTISYMMETRIZER":
        raise ValueError(f"Unsupported antisymmetrizer rule: {match.get('rule')}")
    white = int(match["white"])
    black = int(match["black"])
    input_ports = [int(port) for port in match["input_ports"]]
    output_ports = [int(port) for port in match["output_ports"]]
    permutation = [int(item) for item in permutation]
    if len(input_ports) != 3 or len(output_ports) != 3 or sorted(permutation) != [1, 2, 3]:
        raise ValueError("Antisymmetrizer move needs three inputs, three outputs, and a permutation of 1,2,3.")
    new_adj = copy.deepcopy(adj)
    for input_index, output_index in enumerate(permutation):
        _splice_external_pair(
            new_adj,
            white,
            input_ports[input_index],
            black,
            output_ports[output_index - 1],
        )
    for vertex in (white, black):
        if vertex in new_adj:
            del new_adj[vertex]
    new_adj = drop_nonreciprocal_references(new_adj)
    validate_adjacency(new_adj)
    return new_adj


def smooth_one_hourglass(adj: Adjacency, hg: Hourglass, smoothing: str) -> Adjacency:
    """Remove one wrench/hourglass and perform one of the Figure 4 smoothings."""
    if smoothing not in {"crossing", "parallel"}:
        raise ValueError("smoothing must be 'crossing' or 'parallel'.")

    left = int(hg["left"])
    right = int(hg["right"])
    if left not in adj or right not in adj:
        raise ValueError(f"Hourglass endpoint already removed: {left}-{right}.")
    if not isinstance(adj[left], dict) or not isinstance(adj[right], dict):
        raise ValueError(f"Hourglass endpoints must carry current top/bot ports: {left}-{right}.")
    if any(adj[left].get(port) is None for port in ("top", "bot")) or any(
        adj[right].get(port) is None for port in ("top", "bot")
    ):
        raise ValueError(f"Hourglass endpoint ports are no longer available: {left}-{right}.")

    # Important: read the current ports from adj, not just the original cached
    # ports in hg. Earlier wrench moves may have rewired a neighboring endpoint.
    lt, lb = int(adj[left]["top"]), int(adj[left]["bot"])
    rt, rb = int(adj[right]["top"]), int(adj[right]["bot"])

    new_adj = copy.deepcopy(adj)
    if smoothing == "crossing":
        splice_pair(new_adj, left, lt, right, rb)
        splice_pair(new_adj, left, lb, right, rt)
    else:
        # Parallel term in the wrench relation: both replacement edges run
        # across the hourglass region, but they do not use the diagonal
        # i_2--j_1-style splice.  That diagonal belongs to the crossing term.
        splice_pair(new_adj, left, lt, right, rt)
        splice_pair(new_adj, left, lb, right, rb)

    del new_adj[left]
    del new_adj[right]
    new_adj = drop_nonreciprocal_references(new_adj)
    validate_adjacency(new_adj)
    return new_adj


def fork_to_list(fork: frozenset[int]) -> List[int]:
    return sorted(int(x) for x in fork)


def parse_fork_label(value: str) -> frozenset[int]:
    parts = value.replace(",", " ").split()
    if len(parts) != 2:
        raise ValueError("Fork labels must look like 'i,j' or 'i j'.")
    return frozenset([int(parts[0]), int(parts[1])])


def hourglass_key(hg: Hourglass) -> Tuple[int, int]:
    return tuple(sorted((int(hg["white"]), int(hg["black"]))))


def remaining_after_move(hourglasses: List[Hourglass], moved: Hourglass) -> List[Hourglass]:
    moved_key = hourglass_key(moved)
    return [hg for hg in hourglasses if hourglass_key(hg) != moved_key]


def move_multiplier(smoothing: str) -> int:
    return 1 if smoothing == "crossing" else -1


def common_target_forks(
    adj: Adjacency,
    boundary_labels: BoundaryLabels,
    target_forks: Set[frozenset[int]],
) -> Set[frozenset[int]]:
    return get_forks(adj, boundary_labels).intersection(target_forks)


def score_strategic_branch(
    adj: Adjacency,
    boundary_labels: BoundaryLabels,
    target_forks: Set[frozenset[int]],
    starting_common: Set[frozenset[int]],
    remaining_count: int,
) -> Tuple[int, int, int, int]:
    common = common_target_forks(adj, boundary_labels, target_forks)
    new_common = common.difference(starting_common)
    all_forks = get_forks(adj, boundary_labels)
    return (len(common), len(new_common), len(all_forks), -remaining_count)


def strategic_fork_search(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    x_hourglasses: List[Hourglass],
    target_forks: Set[frozenset[int]],
    *,
    beam_width: int = 20,
    max_depth: Optional[int] = None,
    stop_when_common_fork_created: bool = True,
) -> Dict[str, Any]:
    """Search for wrench moves on X that create a fork also present in W.

    This is not a random expansion.  At every step, every remaining hourglass
    and both Figure 4 smoothings are tested.  Branches are scored by how many
    target forks from W they contain, with priority on newly-created common
    forks.  The beam keeps only the best-scoring branches.
    """
    if max_depth is None:
        max_depth = len(x_hourglasses)

    starting_common = common_target_forks(x_adj, x_boundary_labels, target_forks)
    initial = {
        "adj": x_adj,
        "remaining": x_hourglasses,
        "coeff": 1,
        "moves": [],
        "score": score_strategic_branch(
            x_adj,
            x_boundary_labels,
            target_forks,
            starting_common,
            len(x_hourglasses),
        ),
    }
    if starting_common and stop_when_common_fork_created:
        return {
            "status": "already_has_common_fork",
            "target_forks": sorted([fork_to_list(f) for f in target_forks]),
            "starting_common_forks": sorted([fork_to_list(f) for f in starting_common]),
            "branches": [strategic_branch_summary(initial, x_boundary_labels, target_forks)],
        }

    beam = [initial]
    completed: List[Dict[str, Any]] = []
    best_seen = initial

    for depth in range(max_depth):
        candidates: List[Dict[str, Any]] = []
        for branch in beam:
            if not branch["remaining"]:
                completed.append(branch)
                continue
            before_common = common_target_forks(branch["adj"], x_boundary_labels, target_forks)
            for hg in branch["remaining"]:
                for smoothing in ("crossing", "parallel"):
                    try:
                        next_adj = smooth_one_hourglass(branch["adj"], hg, smoothing)
                    except ValueError:
                        continue
                    next_remaining = remaining_after_move(branch["remaining"], hg)
                    after_common = common_target_forks(next_adj, x_boundary_labels, target_forks)
                    created_common = after_common.difference(before_common)
                    move = {
                        "depth": depth + 1,
                        "smoothing": smoothing,
                        "coefficient_multiplier": move_multiplier(smoothing),
                        "white": int(hg["white"]),
                        "black": int(hg["black"]),
                        "left": int(hg["left"]),
                        "right": int(hg["right"]),
                        "local_case": hg.get("local_case", ""),
                        "common_forks_after_move": sorted([fork_to_list(f) for f in after_common]),
                        "new_common_forks": sorted([fork_to_list(f) for f in created_common]),
                    }
                    next_branch = {
                        "adj": next_adj,
                        "remaining": next_remaining,
                        "coeff": branch["coeff"] * move_multiplier(smoothing),
                        "moves": branch["moves"] + [move],
                        "score": score_strategic_branch(
                            next_adj,
                            x_boundary_labels,
                            target_forks,
                            starting_common,
                            len(next_remaining),
                        ),
                    }
                    candidates.append(next_branch)
                    if next_branch["score"] > best_seen["score"]:
                        best_seen = next_branch
                    if stop_when_common_fork_created and created_common:
                        completed.append(next_branch)

        if completed and stop_when_common_fork_created:
            completed.sort(key=lambda b: b["score"], reverse=True)
            break
        if not candidates:
            break

        deduped: Dict[Tuple[Tuple[int, int], ...], Dict[str, Any]] = {}
        for branch in candidates:
            key = get_edge_tuple(branch["adj"])
            old = deduped.get(key)
            if old is None or branch["score"] > old["score"]:
                deduped[key] = branch
        beam = sorted(deduped.values(), key=lambda b: b["score"], reverse=True)[:beam_width]

    branches = completed if completed else [best_seen]
    branches = sorted(branches, key=lambda b: b["score"], reverse=True)[:beam_width]
    status = "found_common_fork" if any(
        common_target_forks(b["adj"], x_boundary_labels, target_forks).difference(starting_common)
        for b in branches
    ) else "no_new_common_fork_found"
    return {
        "status": status,
        "target_forks": sorted([fork_to_list(f) for f in target_forks]),
        "starting_common_forks": sorted([fork_to_list(f) for f in starting_common]),
        "searched_depth": min(max_depth, len(x_hourglasses)),
        "beam_width": beam_width,
        "branches": [strategic_branch_summary(b, x_boundary_labels, target_forks) for b in branches],
    }


def strategic_branch_summary(
    branch: Dict[str, Any],
    boundary_labels: BoundaryLabels,
    target_forks: Set[frozenset[int]],
) -> Dict[str, Any]:
    common = common_target_forks(branch["adj"], boundary_labels, target_forks)
    return {
        "coeff": branch["coeff"],
        "score": list(branch["score"]),
        "common_forks": sorted([fork_to_list(f) for f in common]),
        "all_forks": sorted([fork_to_list(f) for f in get_forks(branch["adj"], boundary_labels)]),
        "remaining_hourglasses": len(branch["remaining"]),
        "moves": branch["moves"],
        "edges": [list(edge) for edge in get_edge_tuple(branch["adj"])],
    }


def has_common_fork(
    adj: Adjacency,
    boundary_labels: BoundaryLabels,
    target_forks: Set[frozenset[int]],
) -> Tuple[bool, Set[frozenset[int]]]:
    common = common_target_forks(adj, boundary_labels, target_forks)
    return bool(common), common


def term_key(term: Dict[str, Any]) -> Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]]:
    remaining_keys = tuple(sorted(hourglass_key(hg) for hg in term["remaining"]))
    return get_edge_tuple(term["adj"]), remaining_keys


def consolidate_terms(terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    consolidated: Dict[
        Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]],
        Dict[str, Any],
    ] = {}
    for term in terms:
        key = term_key(term)
        if key not in consolidated:
            consolidated[key] = {
                "adj": term["adj"],
                "remaining": term["remaining"],
                "coeff": 0,
                "history": term_history(term),
            }
        consolidated[key]["coeff"] += term["coeff"]
    return [term for term in consolidated.values() if term["coeff"] != 0]


def discharge_terms_by_fork(
    terms: List[Dict[str, Any]],
    boundary_labels: BoundaryLabels,
    target_forks: Set[frozenset[int]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    active: List[Dict[str, Any]] = []
    discharged: List[Dict[str, Any]] = []
    for term in terms:
        ok, common = has_common_fork(term["adj"], boundary_labels, target_forks)
        if ok:
            discharged.append(
                {
                    "coeff": term["coeff"],
                    "common_forks": sorted([fork_to_list(f) for f in common]),
                    "history": term_history(term),
                    "reason": "fork_lemma",
                }
            )
        else:
            active.append(term)
    return active, discharged


def score_proof_state(
    active: List[Dict[str, Any]],
    discharged: List[Dict[str, Any]],
    boundary_labels: BoundaryLabels,
    target_forks: Set[frozenset[int]],
) -> Tuple[int, int, int, int]:
    if active:
        best_common = max(
            len(common_target_forks(term["adj"], boundary_labels, target_forks)) for term in active
        )
        remaining_hg = sum(len(term["remaining"]) for term in active)
    else:
        best_common = 0
        remaining_hg = 0
    return (len(discharged), -len(active), best_common, -remaining_hg)


def expand_one_term_at_hourglass(term: Dict[str, Any], hg: Hourglass) -> List[Dict[str, Any]]:
    children = []
    for smoothing in ("crossing", "parallel"):
        child_adj = smooth_one_hourglass(term["adj"], hg, smoothing)
        child_remaining = remaining_after_move(term["remaining"], hg)
        move = {
            "hourglass": [int(hg["white"]), int(hg["black"])],
            "smoothing": smoothing,
            "coefficient_multiplier": move_multiplier(smoothing),
            "local_case": hg.get("local_case", ""),
        }
        children.append(
            {
                "adj": child_adj,
                "remaining": child_remaining,
                "coeff": term["coeff"] * move_multiplier(smoothing),
                "history": extend_history(term, move),
            }
        )
    return children


def choose_strategic_expansions_for_state(
    active: List[Dict[str, Any]],
    discharged: List[Dict[str, Any]],
    boundary_labels: BoundaryLabels,
    target_forks: Set[frozenset[int]],
) -> List[Dict[str, Any]]:
    """Generate all one-wrench successors, scored by how many branches die."""
    successors: List[Dict[str, Any]] = []
    for term_idx, term in enumerate(active):
        if not term["remaining"]:
            continue
        for hg in term["remaining"]:
            try:
                children = expand_one_term_at_hourglass(term, hg)
            except ValueError:
                continue
            next_terms = active[:term_idx] + active[term_idx + 1 :] + children
            next_terms = consolidate_terms(next_terms)
            next_active, newly_discharged = discharge_terms_by_fork(
                next_terms,
                boundary_labels,
                target_forks,
            )
            next_discharged = discharged + newly_discharged
            successors.append(
                {
                    "active": next_active,
                    "discharged": next_discharged,
                    "expanded_term_index": term_idx,
                    "expanded_hourglass": [int(hg["white"]), int(hg["black"])],
                    "score": score_proof_state(
                        next_active,
                        next_discharged,
                        boundary_labels,
                        target_forks,
                    ),
                }
            )
    return successors


def prove_pair_zero_by_wrench_and_forks(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    x_hourglasses: List[Hourglass],
    target_forks: Set[frozenset[int]],
    *,
    beam_width: int = 40,
    max_steps: Optional[int] = None,
) -> Dict[str, Any]:
    """Try to prove <X,W>=0 by expanding X and killing branches by forks.

    The state is a linear combination of current X-terms paired with the fixed
    reference W.  Whenever a term has a fork also present in W, that term is
    discharged by the BCGMMW fork lemma.  Otherwise the algorithm chooses a
    wrench in one active term and replaces that term by the two Figure 4
    smoothings.  A beam search keeps the most promising states.
    """
    if max_steps is None:
        max_steps = len(x_hourglasses)

    initial_terms = [
        {
            "adj": x_adj,
            "remaining": x_hourglasses,
            "coeff": 1,
            "history": [],
        }
    ]
    active, discharged = discharge_terms_by_fork(initial_terms, x_boundary_labels, target_forks)
    initial_state = {
        "active": active,
        "discharged": discharged,
        "score": score_proof_state(active, discharged, x_boundary_labels, target_forks),
    }
    beam = [initial_state]
    best_state = initial_state
    step_summaries: List[Dict[str, Any]] = []

    for step in range(max_steps):
        if any(not state["active"] for state in beam):
            best_state = next(state for state in beam if not state["active"])
            break

        candidates: List[Dict[str, Any]] = []
        for state in beam:
            candidates.extend(
                choose_strategic_expansions_for_state(
                    state["active"],
                    state["discharged"],
                    x_boundary_labels,
                    target_forks,
                )
            )
        if not candidates:
            break

        candidates.sort(key=lambda state: state["score"], reverse=True)
        beam = candidates[:beam_width]
        if beam[0]["score"] > best_state["score"]:
            best_state = beam[0]
        step_summaries.append(
            {
                "step": step + 1,
                "best_score": list(beam[0]["score"]),
                "active_terms": len(beam[0]["active"]),
                "discharged_terms": len(beam[0]["discharged"]),
                "expanded_hourglass": beam[0].get("expanded_hourglass"),
            }
        )

    status = "proved_zero" if not best_state["active"] else "partial"
    return {
        "status": status,
        "target_forks": sorted([fork_to_list(f) for f in target_forks]),
        "steps_requested": max_steps,
        "steps": step_summaries,
        "discharged_terms": best_state["discharged"],
        "active_terms": [active_term_summary(t, x_boundary_labels, target_forks) for t in best_state["active"]],
        "active_term_count": len(best_state["active"]),
        "discharged_term_count": len(best_state["discharged"]),
        "score": list(best_state["score"]),
    }


def active_term_summary(
    term: Dict[str, Any],
    boundary_labels: BoundaryLabels,
    target_forks: Set[frozenset[int]],
) -> Dict[str, Any]:
    common = common_target_forks(term["adj"], boundary_labels, target_forks)
    return {
        "coeff": term["coeff"],
        "common_forks": sorted([fork_to_list(f) for f in common]),
        "all_forks": sorted([fork_to_list(f) for f in get_forks(term["adj"], boundary_labels)]),
        "remaining_hourglasses": len(term["remaining"]),
        "history": term_history(term),
        "edges": [list(edge) for edge in get_edge_tuple(term["adj"])],
    }


def common_pair_forks(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    w_adj: Adjacency,
    w_boundary_labels: BoundaryLabels,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
) -> Set[frozenset[int]]:
    common = get_forks(x_adj, x_boundary_labels).intersection(get_forks(w_adj, w_boundary_labels))
    if allowed_forks is not None:
        common = common.intersection(allowed_forks)
    return common


def pair_term_key(term: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        get_edge_tuple(term["x_adj"]),
        tuple(sorted(hourglass_key(hg) for hg in term["x_remaining"])),
        get_edge_tuple(term["w_adj"]),
        tuple(sorted(hourglass_key(hg) for hg in term["w_remaining"])),
    )


def consolidate_pair_terms(terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    consolidated: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for term in terms:
        key = pair_term_key(term)
        if key not in consolidated:
            consolidated[key] = {
                "x_adj": term["x_adj"],
                "x_remaining": term["x_remaining"],
                "w_adj": term["w_adj"],
                "w_remaining": term["w_remaining"],
                "coeff": 0,
                "history": term_history(term),
            }
        consolidated[key]["coeff"] += term["coeff"]
    return [term for term in consolidated.values() if term["coeff"] != 0]


def discharge_pair_terms_by_common_fork(
    terms: List[Dict[str, Any]],
    x_boundary_labels: BoundaryLabels,
    w_boundary_labels: BoundaryLabels,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    active: List[Dict[str, Any]] = []
    discharged: List[Dict[str, Any]] = []
    for term in terms:
        common = common_pair_forks(
            term["x_adj"],
            x_boundary_labels,
            term["w_adj"],
            w_boundary_labels,
            allowed_forks,
        )
        if common:
            discharged.append(
                {
                    "coeff": term["coeff"],
                    "common_forks": sorted([fork_to_list(f) for f in common]),
                    "history": term_history(term),
                    "reason": "fork_lemma",
                }
            )
        else:
            active.append(term)
    return active, discharged


def expand_pair_term(term: Dict[str, Any], side: str, hg: Hourglass) -> List[Dict[str, Any]]:
    if side not in {"X", "W"}:
        raise ValueError("side must be X or W.")
    children = []
    for smoothing in ("crossing", "parallel"):
        if side == "X":
            child_x_adj = smooth_one_hourglass(term["x_adj"], hg, smoothing)
            child_x_remaining = remaining_after_move(term["x_remaining"], hg)
            child_w_adj = term["w_adj"]
            child_w_remaining = term["w_remaining"]
        else:
            child_x_adj = term["x_adj"]
            child_x_remaining = term["x_remaining"]
            child_w_adj = smooth_one_hourglass(term["w_adj"], hg, smoothing)
            child_w_remaining = remaining_after_move(term["w_remaining"], hg)
        move = {
            "side": side,
            "hourglass": [int(hg["white"]), int(hg["black"])],
            "smoothing": smoothing,
            "coefficient_multiplier": move_multiplier(smoothing),
            "local_case": hg.get("local_case", ""),
        }
        children.append(
            {
                "x_adj": child_x_adj,
                "x_remaining": child_x_remaining,
                "w_adj": child_w_adj,
                "w_remaining": child_w_remaining,
                "coeff": term["coeff"] * move_multiplier(smoothing),
                "history": extend_history(term, move),
            }
        )
    return children


def expand_pair_term_by_figure43(
    term: Dict[str, Any],
    side: str,
    match: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if side not in {"X", "W"}:
        raise ValueError("side must be X or W.")
    children = []
    for rhs in match.get("rhs_terms", []):
        smoothing = str(rhs["smoothing"])
        multiplier = int(rhs["coefficient_multiplier"])
        if side == "X":
            child_x_adj, child_x_remaining = apply_figure43_move(
                term["x_adj"],
                term["x_remaining"],
                match,
                smoothing,
            )
            child_w_adj = term["w_adj"]
            child_w_remaining = term["w_remaining"]
        else:
            child_x_adj = term["x_adj"]
            child_x_remaining = term["x_remaining"]
            child_w_adj, child_w_remaining = apply_figure43_move(
                term["w_adj"],
                term["w_remaining"],
                match,
                smoothing,
            )
        move = {
            "phase": "figure43",
            "side": side,
            "rule": match["rule"],
            "vertices": [int(v) for v in match["vertices_top_right_bottom_left"]],
            "smoothing": smoothing,
            "coefficient_multiplier": multiplier,
        }
        children.append(
            {
                "x_adj": child_x_adj,
                "x_remaining": child_x_remaining,
                "w_adj": child_w_adj,
                "w_remaining": child_w_remaining,
                "coeff": term["coeff"] * multiplier,
                "history": extend_history(term, move),
            }
        )
    return children




def expand_pair_term_by_antisymmetrizer(
    term: Dict[str, Any],
    match: Dict[str, Any],
) -> List[Dict[str, Any]]:
    children = []
    for rhs in match.get("rhs_terms", []):
        permutation = [int(item) for item in rhs["permutation"]]
        multiplier = int(rhs["coefficient_multiplier"])
        child_x_adj = apply_antisymmetrizer_move(term["x_adj"], match, permutation)
        child_x_remaining = clean_hourglasses_for_adj(child_x_adj, term["x_remaining"])
        move = {
            "phase": "antisymmetrizer",
            "side": "X",
            "rule": match["rule"],
            "vertices": [int(match["white"]), int(match["black"])],
            "white": int(match["white"]),
            "black": int(match["black"]),
            "input_ports": [int(port) for port in match["input_ports"]],
            "output_ports": [int(port) for port in match["output_ports"]],
            "permutation": permutation,
            "smoothing": str(rhs.get("smoothing", "perm_" + "".join(str(x) for x in permutation))),
            "coefficient_multiplier": multiplier,
        }
        children.append(
            {
                "x_adj": child_x_adj,
                "x_remaining": child_x_remaining,
                "w_adj": term["w_adj"],
                "w_remaining": term["w_remaining"],
                "coeff": term["coeff"] * multiplier,
                "history": extend_history(term, move),
            }
        )
    return children


def score_pair_state(
    active: List[Dict[str, Any]],
    discharged: List[Dict[str, Any]],
    x_boundary_labels: BoundaryLabels,
    w_boundary_labels: BoundaryLabels,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
) -> Tuple[int, int, int, int]:
    if active:
        remaining_hg = sum(len(term["x_remaining"]) + len(term["w_remaining"]) for term in active)
        total_forks = max(
            len(get_forks(term["x_adj"], x_boundary_labels))
            + len(get_forks(term["w_adj"], w_boundary_labels))
            for term in active
        )
    else:
        remaining_hg = 0
        total_forks = 0
    return (len(discharged), -len(active), total_forks, -remaining_hg)


def choose_pair_successors(
    active: List[Dict[str, Any]],
    discharged: List[Dict[str, Any]],
    x_boundary_labels: BoundaryLabels,
    w_boundary_labels: BoundaryLabels,
    *,
    allow_w_wrench: bool,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
    x_node_colors: Optional[NodeColors] = None,
    x_node_xy: Optional[NodeXY] = None,
    w_node_colors: Optional[NodeColors] = None,
    w_node_xy: Optional[NodeXY] = None,
) -> List[Dict[str, Any]]:
    successors: List[Dict[str, Any]] = []
    for term_idx, term in enumerate(active):
        choices: List[Tuple[str, Hourglass]] = [("X", hg) for hg in term["x_remaining"]]
        if allow_w_wrench:
            choices.extend(("W", hg) for hg in term["w_remaining"])
        for side, hg in choices:
            try:
                children = expand_pair_term(term, side, hg)
            except ValueError:
                continue
            next_terms = active[:term_idx] + active[term_idx + 1 :] + children
            next_terms = consolidate_pair_terms(next_terms)
            next_active, newly_discharged = discharge_pair_terms_by_common_fork(
                next_terms,
                x_boundary_labels,
                w_boundary_labels,
                allowed_forks,
            )
            next_discharged = discharged + newly_discharged
            successors.append(
                {
                    "active": next_active,
                    "discharged": next_discharged,
                    "expanded_relation": "wrench",
                    "expanded_side": side,
                    "expanded_hourglass": [int(hg["white"]), int(hg["black"])],
                    "score": score_pair_state(
                        next_active,
                        next_discharged,
                        x_boundary_labels,
                        w_boundary_labels,
                        allowed_forks,
                    ),
                }
            )
        relation_choices: List[Tuple[str, Dict[str, Any]]] = []
        relation_choices.extend(
            ("X", match)
            for match in detect_figure43_moves(
                term["x_adj"],
                term["x_remaining"],
                x_node_colors,
                x_node_xy,
            )
        )
        if allow_w_wrench:
            relation_choices.extend(
                ("W", match)
                for match in detect_figure43_moves(
                    term["w_adj"],
                    term["w_remaining"],
                    w_node_colors,
                    w_node_xy,
                )
            )
        for side, match in relation_choices:
            try:
                children = expand_pair_term_by_figure43(term, side, match)
            except ValueError:
                continue
            next_terms = active[:term_idx] + active[term_idx + 1 :] + children
            next_terms = consolidate_pair_terms(next_terms)
            next_active, newly_discharged = discharge_pair_terms_by_common_fork(
                next_terms,
                x_boundary_labels,
                w_boundary_labels,
                allowed_forks,
            )
            next_discharged = discharged + newly_discharged
            successors.append(
                {
                    "active": next_active,
                    "discharged": next_discharged,
                    "expanded_relation": "figure43",
                    "expanded_side": side,
                    "expanded_rule": match["rule"],
                    "expanded_vertices": [int(v) for v in match["vertices_top_right_bottom_left"]],
                    "score": score_pair_state(
                        next_active,
                        next_discharged,
                        x_boundary_labels,
                        w_boundary_labels,
                        allowed_forks,
                    ),
                }
            )
    return successors


def pair_state_remaining_hourglasses(state: Dict[str, Any]) -> int:
    return sum(
        len(term["x_remaining"]) + len(term["w_remaining"])
        for term in state["active"]
    )


def pair_state_has_expandable_term(state: Dict[str, Any]) -> bool:
    return any(
        term["x_remaining"] or term["w_remaining"]
        for term in state["active"]
    )


def evaluate_pair_state_by_coloring(
    state: Dict[str, Any],
    x_boundary_labels: BoundaryLabels,
    w_boundary_labels: BoundaryLabels,
    *,
    r: int = 4,
) -> Optional[Tuple[int, List[Dict[str, Any]]]]:
    """Evaluate a pair-state once every surviving hourglass is resolved."""
    total = 0
    evaluations: List[Dict[str, Any]] = []
    for term in state["active"]:
        try:
            evaluation = evaluate_pair_by_coloring(
                term["x_adj"],
                x_boundary_labels,
                term["w_adj"],
                w_boundary_labels,
                x_hourglasses=term["x_remaining"],
                w_hourglasses=term["w_remaining"],
                r=r,
            )
        except ValueError as exc:
            evaluation = {
                "status": "not_computed",
                "reason": str(exc),
            }
        evaluation["coeff"] = term["coeff"]
        evaluation["history"] = term_history(term)
        evaluation["common_forks"] = []
        evaluation["source_adj"] = term["x_adj"]
        evaluation["source_hourglasses"] = term["x_remaining"]
        evaluation["colored_adj"] = term["w_adj"]
        evaluation["colored_hourglasses"] = term["w_remaining"]
        evaluation["colored_side"] = "W"
        if evaluation["status"] != "computed":
            evaluation["term_value"] = None
            return None
        evaluation["term_value"] = term["coeff"] * int(evaluation["coloring_count"])
        total += int(evaluation["term_value"])
        evaluations.append(evaluation)
    return total, evaluations


def component_boundary_condition_from_x(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    *,
    r: int = 4,
) -> Optional[Dict[int, int]]:
    """Color each connected component of X and return boundary label colors.

    This is the component-coloring fallback requested for unresolved terms:
    after all X-hourglasses have been expanded, vertices in the same connected
    component of X receive the same color.  Components are colored in canonical
    order by their smallest boundary label.
    """
    components = []
    for comp in graph_components(x_adj):
        labels = sorted(x_boundary_labels[n] for n in comp if n in x_boundary_labels)
        if labels:
            components.append((labels[0], labels, comp))
    if len(components) != r:
        return None
    components.sort(key=lambda item: item[0])
    condition: Dict[int, int] = {}
    for color, (_min_label, labels, _comp) in enumerate(components, start=1):
        for label in labels:
            if label in condition:
                return None
            condition[int(label)] = color
    if sorted(condition) != list(range(1, r * r + 1)):
        return None
    return condition


def evaluate_pair_by_x_component_coloring(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    x_hourglasses: List[Hourglass],
    w_adj: Adjacency,
    w_boundary_labels: BoundaryLabels,
    w_hourglasses: List[Hourglass],
    *,
    r: int = 4,
) -> Dict[str, Any]:
    """Evaluate by coloring X components, then W edges.

    This assumes X-hourglasses have already been removed by wrench expansion.
    W may still have hourglasses, which are counted as two parallel internal
    edges in ``count_consistent_colorings``.
    """
    if x_hourglasses:
        return {
            "status": "not_computed",
            "reason": f"X still has {len(x_hourglasses)} hourglass(es)",
        }
    condition = component_boundary_condition_from_x(x_adj, x_boundary_labels, r=r)
    if condition is None:
        return {
            "status": "not_computed",
            "reason": "X does not have exactly four boundary-bearing connected components",
        }
    count = count_consistent_colorings(
        w_adj,
        w_boundary_labels,
        condition,
        hourglasses=w_hourglasses,
        r=r,
    )
    return {
        "status": "computed",
        "source_side": "X_components",
        "boundary_color_by_label": condition,
        "coloring_count": count,
    }


def evaluate_pair_state_by_x_component_coloring(
    state: Dict[str, Any],
    x_boundary_labels: BoundaryLabels,
    w_boundary_labels: BoundaryLabels,
    *,
    r: int = 4,
) -> Optional[Tuple[int, List[Dict[str, Any]]]]:
    total = 0
    evaluations: List[Dict[str, Any]] = []
    for term in state["active"]:
        term = normalize_pair_term(term)
        evaluation = evaluate_pair_by_x_component_coloring(
            term["x_adj"],
            x_boundary_labels,
            term["x_remaining"],
            term["w_adj"],
            w_boundary_labels,
            term["w_remaining"],
            r=r,
        )
        evaluation["coeff"] = term["coeff"]
        evaluation["history"] = term_history(term)
        evaluation["common_forks"] = []
        evaluation["source_adj"] = term["x_adj"]
        evaluation["source_hourglasses"] = term["x_remaining"]
        evaluation["colored_adj"] = term["w_adj"]
        evaluation["colored_hourglasses"] = term["w_remaining"]
        evaluation["colored_side"] = "W"
        if evaluation["status"] != "computed":
            evaluation["term_value"] = None
            return None
        evaluation["term_value"] = term["coeff"] * int(evaluation["coloring_count"])
        total += int(evaluation["term_value"])
        evaluations.append(evaluation)
    return total, evaluations


def replay_pair_history(
    x_adj: Adjacency,
    x_hourglasses: List[Hourglass],
    w_adj: Adjacency,
    w_hourglasses: List[Hourglass],
    history: List[Dict[str, Any]],
) -> Tuple[Adjacency, List[Hourglass], Adjacency, List[Hourglass]]:
    """Replay a branch history from the original pair state.

    ``active_terms`` in proof summaries store histories rather than full
    adjacency payloads.  Replaying the history lets the final fallback continue
    the same branch instead of silently dropping it.
    """
    current_x = copy.deepcopy(x_adj)
    current_w = copy.deepcopy(w_adj)
    current_xh = copy.deepcopy(x_hourglasses)
    current_wh = copy.deepcopy(w_hourglasses)
    for move in history:
        side = move["side"]
        smoothing = move["smoothing"]
        if move.get("phase") == "antisymmetrizer":
            match = {
                "rule": move["rule"],
                "white": int(move["white"]),
                "black": int(move["black"]),
                "input_ports": [int(port) for port in move["input_ports"]],
                "output_ports": [int(port) for port in move["output_ports"]],
            }
            if side != "X":
                raise ValueError("Antisymmetrizer history moves are currently X-side only.")
            current_x = apply_antisymmetrizer_move(current_x, match, move["permutation"])
            current_x = drop_nonreciprocal_references(current_x)
            current_xh = clean_hourglasses_for_adj(current_x, current_xh)
            continue
        if move.get("phase") == "figure43":
            match = {
                "rule": move["rule"],
                "vertices_top_right_bottom_left": [int(v) for v in move["vertices"]],
            }
            if side == "X":
                current_x, current_xh = apply_figure43_move(current_x, current_xh, match, smoothing)
                current_x = drop_nonreciprocal_references(current_x)
                current_xh = clean_hourglasses_for_adj(current_x, current_xh)
            elif side == "W":
                current_w, current_wh = apply_figure43_move(current_w, current_wh, match, smoothing)
                current_w = drop_nonreciprocal_references(current_w)
                current_wh = clean_hourglasses_for_adj(current_w, current_wh)
            else:
                raise ValueError(f"Unknown branch side in history: {side!r}")
            continue
        key = tuple(sorted(int(x) for x in move["hourglass"]))
        if side == "X":
            hg = next(h for h in current_xh if tuple(sorted((int(h["white"]), int(h["black"])))) == key)
            current_x = smooth_one_hourglass(current_x, hg, smoothing)
            current_xh = remaining_after_move(current_xh, hg)
            current_x = drop_nonreciprocal_references(current_x)
            current_xh = clean_hourglasses_for_adj(current_x, current_xh)
        elif side == "W":
            hg = next(h for h in current_wh if tuple(sorted((int(h["white"]), int(h["black"])))) == key)
            current_w = smooth_one_hourglass(current_w, hg, smoothing)
            current_wh = remaining_after_move(current_wh, hg)
            current_w = drop_nonreciprocal_references(current_w)
            current_wh = clean_hourglasses_for_adj(current_w, current_wh)
        else:
            raise ValueError(f"Unknown branch side in history: {side!r}")
    return current_x, current_xh, current_w, current_wh


def evaluate_active_terms_by_expanding_w_then_coloring(
    proof: Dict[str, Any],
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    x_hourglasses: List[Hourglass],
    w_adj: Adjacency,
    w_boundary_labels: BoundaryLabels,
    w_hourglasses: List[Hourglass],
    *,
    max_w_expansions_per_branch: int = 16,
    w_node_colors: Optional[NodeColors] = None,
    w_node_xy: Optional[NodeXY] = None,
    r: int = 4,
) -> Tuple[Optional[int], Dict[str, Any]]:
    """Evaluate surviving branches after X-component coloring stalls.

    This is the corrected-skein fallback folded into the core code path:
    every active branch is replayed, all remaining X-hourglasses must be gone,
    and then W-hourglasses are expanded branch-by-branch.  A branch is removed
    by the fork lemma only when ``common_pair_forks`` is nonempty; an empty
    fork list is never a proof of zero.
    """
    if not proof.get("active_terms"):
        return 0, {
            "status": "proved_zero",
            "w_expanded_terms": 0,
            "w_expanded_fork_killed": 0,
            "w_direct_colored_terms": 0,
            "branch_evaluations": [],
            "reason": "",
        }

    total = 0
    expanded_terms = 0
    fork_killed = 0
    direct_colored_terms = 0
    branch_evaluations: List[Dict[str, Any]] = []
    for term in proof["active_terms"]:
        x_now, x_now_hgs, w_now, w_now_hgs = replay_pair_history(
            x_adj,
            x_hourglasses,
            w_adj,
            w_hourglasses,
            term_history(term),
        )
        x_now = drop_nonreciprocal_references(x_now)
        w_now = drop_nonreciprocal_references(w_now)
        x_now_hgs = clean_hourglasses_for_adj(x_now, x_now_hgs)
        w_now_hgs = clean_hourglasses_for_adj(w_now, w_now_hgs)
        if x_now_hgs:
            return None, {
                "status": "not_computed",
                "w_expanded_terms": expanded_terms,
                "w_expanded_fork_killed": fork_killed,
                "w_direct_colored_terms": direct_colored_terms,
                "branch_evaluations": branch_evaluations,
                "reason": f"X still has {len(x_now_hgs)} hourglass(es)",
            }

        condition = component_boundary_condition_from_x(x_now, x_boundary_labels, r=r)

        stack = [(w_now, w_now_hgs, int(term["coeff"]), list(term_history(term)))]
        branch_expansions = 0
        while stack:
            current_w, current_wh, coeff, current_history = stack.pop()
            current_w = drop_nonreciprocal_references(current_w)
            current_wh = clean_hourglasses_for_adj(current_w, current_wh)
            common_forks = common_pair_forks(x_now, x_boundary_labels, current_w, w_boundary_labels)
            if common_forks:
                fork_killed += 1
                branch_evaluations.append(
                    {
                        "status": "fork_killed",
                        "coeff": coeff,
                        "coloring_count": 0,
                        "term_value": 0,
                        "common_forks": [fork_to_list(f) for f in sorted(common_forks, key=fork_to_list)],
                        "source_side": "X_components",
                        "boundary_color_by_label": condition or {},
                        "history": current_history,
                    }
                )
                continue
            figure43_matches = detect_figure43_moves(current_w, current_wh, w_node_colors, w_node_xy)
            if figure43_matches:
                if branch_expansions >= max_w_expansions_per_branch:
                    if condition is None:
                        return None, {
                            "status": "not_computed",
                            "w_expanded_terms": expanded_terms,
                            "w_expanded_fork_killed": fork_killed,
                            "w_direct_colored_terms": direct_colored_terms,
                            "branch_evaluations": branch_evaluations,
                            "reason": (
                                "W expansion cap reached before applying a Figure 43 relation, "
                                "and X does not have exactly four boundary-bearing connected components"
                            ),
                        }
                    coloring = consistent_coloring_data(
                        current_w,
                        w_boundary_labels,
                        condition,
                        hourglasses=current_wh,
                        r=r,
                    )
                    count = int(coloring["count"])
                    total += coeff * count
                    direct_colored_terms += 1
                    branch_evaluations.append(
                        {
                            "status": "computed_direct_w_hourglass_coloring",
                            "coeff": coeff,
                            "coloring_count": count,
                            "term_value": coeff * count,
                            "source_side": "X_components",
                            "boundary_color_by_label": condition,
                            "sample_edge_colors": coloring.get("sample_edge_colors", []),
                            "sample_hourglass_colors": coloring.get("sample_hourglass_colors", []),
                            "hourglass_swap_quotient": coloring.get("hourglass_swap_quotient", True),
                            "colored_side": "W",
                            "colored_adj": current_w,
                            "colored_hourglasses": current_wh,
                            "source_adj": x_now,
                            "history": current_history,
                            "remaining_w_hourglasses": [
                                [int(hg["white"]), int(hg["black"])] for hg in current_wh
                            ],
                        }
                    )
                    continue
                match = figure43_matches[0]
                for rhs in match.get("rhs_terms", []):
                    smoothing = str(rhs["smoothing"])
                    multiplier = int(rhs["coefficient_multiplier"])
                    try:
                        child_w, child_wh = apply_figure43_move(current_w, current_wh, match, smoothing)
                    except ValueError:
                        continue
                    move = {
                        "phase": "figure43",
                        "side": "W",
                        "rule": match["rule"],
                        "vertices": [int(v) for v in match["vertices_top_right_bottom_left"]],
                        "smoothing": smoothing,
                        "coefficient_multiplier": multiplier,
                    }
                    stack.append((child_w, child_wh, coeff * multiplier, current_history + [move]))
                branch_expansions += 1
                continue
            if current_wh:
                if branch_expansions >= max_w_expansions_per_branch:
                    if condition is None:
                        return None, {
                            "status": "not_computed",
                            "w_expanded_terms": expanded_terms,
                            "w_expanded_fork_killed": fork_killed,
                            "w_direct_colored_terms": direct_colored_terms,
                            "branch_evaluations": branch_evaluations,
                            "reason": (
                                "W expansion cap reached before a fork kill, and X does not have "
                                "exactly four boundary-bearing connected components"
                            ),
                        }
                    coloring = consistent_coloring_data(
                        current_w,
                        w_boundary_labels,
                        condition,
                        hourglasses=current_wh,
                        r=r,
                    )
                    count = int(coloring["count"])
                    total += coeff * count
                    direct_colored_terms += 1
                    branch_evaluations.append(
                        {
                            "status": "computed_direct_w_hourglass_coloring",
                            "coeff": coeff,
                            "coloring_count": count,
                            "term_value": coeff * count,
                            "source_side": "X_components",
                            "boundary_color_by_label": condition,
                            "sample_edge_colors": coloring.get("sample_edge_colors", []),
                            "sample_hourglass_colors": coloring.get("sample_hourglass_colors", []),
                            "hourglass_swap_quotient": coloring.get("hourglass_swap_quotient", True),
                            "colored_side": "W",
                            "colored_adj": current_w,
                            "colored_hourglasses": current_wh,
                            "source_adj": x_now,
                            "history": current_history,
                            "remaining_w_hourglasses": [
                                [int(hg["white"]), int(hg["black"])] for hg in current_wh
                            ],
                        }
                    )
                    continue
                hg = current_wh[0]
                for smoothing in ("crossing", "parallel"):
                    try:
                        child_w = smooth_one_hourglass(current_w, hg, smoothing)
                    except ValueError:
                        continue
                    child_wh = remaining_after_move(current_wh, hg)
                    child_w = drop_nonreciprocal_references(child_w)
                    child_wh = clean_hourglasses_for_adj(child_w, child_wh)
                    move = {
                        "side": "W",
                        "hourglass": [int(hg["white"]), int(hg["black"])],
                        "smoothing": smoothing,
                        "coefficient_multiplier": move_multiplier(smoothing),
                        "local_case": hg.get("local_case", ""),
                        "phase": "w_expansion_fallback",
                    }
                    stack.append(
                        (
                            child_w,
                            child_wh,
                            coeff * move_multiplier(smoothing),
                            current_history + [move],
                        )
                    )
                branch_expansions += 1
                continue

            expanded_terms += 1
            if condition is None:
                return None, {
                    "status": "not_computed",
                    "w_expanded_terms": expanded_terms,
                    "w_expanded_fork_killed": fork_killed,
                    "w_direct_colored_terms": direct_colored_terms,
                    "branch_evaluations": branch_evaluations,
                    "reason": (
                        "No W hourglasses remain, but X does not have exactly four "
                        "boundary-bearing connected components"
                    ),
                }
            coloring = consistent_coloring_data(
                current_w,
                w_boundary_labels,
                condition,
                hourglasses=[],
                r=r,
            )
            count = int(coloring["count"])
            total += coeff * count
            branch_evaluations.append(
                {
                    "status": "computed",
                    "coeff": coeff,
                    "coloring_count": count,
                    "term_value": coeff * count,
                    "source_side": "X_components",
                    "boundary_color_by_label": condition,
                    "sample_edge_colors": coloring.get("sample_edge_colors", []),
                    "sample_hourglass_colors": coloring.get("sample_hourglass_colors", []),
                    "hourglass_swap_quotient": coloring.get("hourglass_swap_quotient", True),
                    "colored_side": "W",
                    "colored_adj": current_w,
                    "colored_hourglasses": [],
                    "source_adj": x_now,
                    "history": current_history,
                }
            )

    status = "computed_after_w_expansion"
    if direct_colored_terms:
        status = "computed_after_w_expansion_with_direct_w_fallback"
    return total, {
        "status": status,
        "w_expanded_terms": expanded_terms,
        "w_expanded_fork_killed": fork_killed,
        "w_direct_colored_terms": direct_colored_terms,
        "branch_evaluations": branch_evaluations,
        "reason": "",
    }


def prove_pair_value_complete_pipeline(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    x_hourglasses: List[Hourglass],
    w_adj: Adjacency,
    w_boundary_labels: BoundaryLabels,
    w_hourglasses: List[Hourglass],
    *,
    allow_w_wrench: bool = True,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
    guided_beam_width: int = 200,
    x_beam_width: int = 500,
    guided_steps: Optional[int] = None,
    x_resolution_steps: Optional[int] = None,
    max_w_expansions_per_branch: int = 16,
    x_node_colors: Optional[NodeColors] = None,
    x_node_xy: Optional[NodeXY] = None,
    w_node_colors: Optional[NodeColors] = None,
    w_node_xy: Optional[NodeXY] = None,
) -> Dict[str, Any]:
    """Run the website pairing pipeline without changing W.

    Relations are applied only to X.  Coloring starts only after X has no
    remaining hourglass metadata and no internal black vertices.  W is then
    edge-colored as-is from the boundary colors determined by X.
    """
    proof = prove_pair_value_by_x_component_coloring(
        x_adj,
        x_boundary_labels,
        x_hourglasses,
        w_adj,
        w_boundary_labels,
        w_hourglasses,
        allow_w_wrench=False,
        allowed_forks=allowed_forks,
        guided_beam_width=guided_beam_width,
        x_beam_width=x_beam_width,
        guided_steps=guided_steps,
        x_resolution_steps=x_resolution_steps,
        x_node_colors=x_node_colors,
        x_node_xy=x_node_xy,
        w_node_colors=w_node_colors,
        w_node_xy=w_node_xy,
    )
    proof = copy.deepcopy(proof)
    proof["allow_w_wrench"] = False
    proof["w_expansion_fallback"] = {
        "status": "disabled",
        "w_expanded_terms": 0,
        "w_expanded_fork_killed": 0,
        "w_direct_colored_terms": 0,
        "branch_evaluations": [],
        "reason": "W is passive: relations are applied only to X before coloring.",
    }
    proof["w_expanded_terms"] = 0
    proof["w_expanded_fork_killed"] = 0
    proof["w_direct_colored_terms"] = 0
    proof["linear_combination_terms"] = proof.get("coloring_evaluations", [])
    return proof


def has_x_hourglasses(state: Dict[str, Any]) -> bool:
    return any(normalize_pair_term(term)["x_remaining"] for term in state["active"])


def term_x_internal_black_vertices(
    term: Dict[str, Any],
    x_boundary_labels: BoundaryLabels,
    x_node_colors: Optional[NodeColors],
) -> List[int]:
    if not x_node_colors:
        return []
    normalized = normalize_pair_term(term)
    return sorted(
        int(node)
        for node in normalized["x_adj"]
        if int(node) not in x_boundary_labels and x_node_colors.get(int(node)) == "black"
    )


def has_x_internal_black_vertices(
    state: Dict[str, Any],
    x_boundary_labels: BoundaryLabels,
    x_node_colors: Optional[NodeColors],
) -> bool:
    return any(term_x_internal_black_vertices(term, x_boundary_labels, x_node_colors) for term in state["active"])


def x_state_ready_for_coloring(
    state: Dict[str, Any],
    x_boundary_labels: BoundaryLabels,
    x_node_colors: Optional[NodeColors],
) -> bool:
    return not has_x_hourglasses(state) and not has_x_internal_black_vertices(
        state,
        x_boundary_labels,
        x_node_colors,
    )


def choose_x_resolution_successors(
    active: List[Dict[str, Any]],
    discharged: List[Dict[str, Any]],
    x_boundary_labels: BoundaryLabels,
    w_boundary_labels: BoundaryLabels,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
    x_node_colors: Optional[NodeColors] = None,
    x_node_xy: Optional[NodeXY] = None,
) -> List[Dict[str, Any]]:
    """Resolve one X-hourglass in one active term; do not expand W."""
    successors: List[Dict[str, Any]] = []
    for term_idx, term in enumerate(active):
        term = normalize_pair_term(term)
        if not term["x_remaining"]:
            if plucker_product_components(term["x_adj"], x_boundary_labels, r=4) is None:
                for match in detect_antisymmetrizer_moves(term["x_adj"], x_node_colors, x_node_xy):
                    try:
                        children = expand_pair_term_by_antisymmetrizer(term, match)
                    except ValueError:
                        continue
                    next_terms = active[:term_idx] + active[term_idx + 1 :] + children
                    next_terms = consolidate_pair_terms(next_terms)
                    next_active, newly_discharged = discharge_pair_terms_by_common_fork(
                        next_terms,
                        x_boundary_labels,
                        w_boundary_labels,
                        allowed_forks,
                    )
                    next_discharged = discharged + newly_discharged
                    successors.append(
                        {
                            "active": next_active,
                            "discharged": next_discharged,
                            "expanded_relation": "antisymmetrizer",
                            "expanded_side": "X",
                            "expanded_rule": match["rule"],
                            "expanded_vertices": [int(match["white"]), int(match["black"])],
                            "score": score_pair_state(
                                next_active,
                                next_discharged,
                                x_boundary_labels,
                                w_boundary_labels,
                                allowed_forks,
                            ),
                        }
                    )
            continue
        for hg in term["x_remaining"]:
            try:
                children = expand_pair_term(term, "X", hg)
            except ValueError:
                continue
            next_terms = active[:term_idx] + active[term_idx + 1 :] + children
            next_terms = consolidate_pair_terms(next_terms)
            next_active, newly_discharged = discharge_pair_terms_by_common_fork(
                next_terms,
                x_boundary_labels,
                w_boundary_labels,
                allowed_forks,
            )
            next_discharged = discharged + newly_discharged
            state = {
                "active": next_active,
                "discharged": next_discharged,
                "expanded_relation": "wrench",
                "expanded_side": "X",
                "expanded_hourglass": [int(hg["white"]), int(hg["black"])],
                "score": score_pair_state(
                    next_active,
                    next_discharged,
                    x_boundary_labels,
                    w_boundary_labels,
                    allowed_forks,
                ),
            }
            successors.append(state)
        for match in detect_figure43_moves(term["x_adj"], term["x_remaining"], x_node_colors, x_node_xy):
            try:
                children = expand_pair_term_by_figure43(term, "X", match)
            except ValueError:
                continue
            next_terms = active[:term_idx] + active[term_idx + 1 :] + children
            next_terms = consolidate_pair_terms(next_terms)
            next_active, newly_discharged = discharge_pair_terms_by_common_fork(
                next_terms,
                x_boundary_labels,
                w_boundary_labels,
                allowed_forks,
            )
            next_discharged = discharged + newly_discharged
            successors.append(
                {
                    "active": next_active,
                    "discharged": next_discharged,
                    "expanded_relation": "figure43",
                    "expanded_side": "X",
                    "expanded_rule": match["rule"],
                    "expanded_vertices": [int(v) for v in match["vertices_top_right_bottom_left"]],
                    "score": score_pair_state(
                        next_active,
                        next_discharged,
                        x_boundary_labels,
                        w_boundary_labels,
                        allowed_forks,
                    ),
                }
            )
    return successors


def complete_pair_state_score(
    state: Dict[str, Any],
    x_boundary_labels: BoundaryLabels,
    w_boundary_labels: BoundaryLabels,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
) -> Tuple[int, int, int, int, int]:
    """Score for the second-stage search.

    The first proof search is intentionally guided by immediate fork kills.
    This score is used after those easy cancellations have stalled: it still
    rewards fork kills, but it primarily keeps states that continue resolving
    hourglasses in surviving branches.  Dead terminal states that cannot be
    colored are ranked below expandable states.
    """
    remaining_hg = pair_state_remaining_hourglasses(state)
    expandable = pair_state_has_expandable_term(state)
    base = score_pair_state(
        state["active"],
        state["discharged"],
        x_boundary_labels,
        w_boundary_labels,
        allowed_forks,
    )
    return (
        0 if remaining_hg == 0 and state["active"] and not expandable else 1,
        -remaining_hg,
        len(state["discharged"]),
        -len(state["active"]),
        base[2],
    )


def pair_proof_result_from_state(
    state: Dict[str, Any],
    x_boundary_labels: BoundaryLabels,
    w_boundary_labels: BoundaryLabels,
    allowed_forks: Optional[Set[frozenset[int]]],
    steps_requested: int,
    step_summaries: List[Dict[str, Any]],
    *,
    status: str,
    final_pairing_value: Optional[int],
    coloring_evaluations: Optional[List[Dict[str, Any]]] = None,
    allow_w_wrench: bool = True,
) -> Dict[str, Any]:
    return {
        "status": status,
        "allow_w_wrench": allow_w_wrench,
        "allowed_forks": None if allowed_forks is None else sorted([fork_to_list(f) for f in allowed_forks]),
        "steps_requested": steps_requested,
        "steps": step_summaries,
        "discharged_terms": state["discharged"],
        "active_terms": [
            pair_active_term_summary(t, x_boundary_labels, w_boundary_labels, allowed_forks)
            for t in state["active"]
        ],
        "active_term_count": len(state["active"]),
        "discharged_term_count": len(state["discharged"]),
        "score": list(
            score_pair_state(
                state["active"],
                state["discharged"],
                x_boundary_labels,
                w_boundary_labels,
                allowed_forks,
            )
        ),
        "coloring_evaluations": coloring_evaluations or [],
        "final_pairing_value": final_pairing_value,
    }


def prove_pair_value_by_wrench_forks_complete(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    x_hourglasses: List[Hourglass],
    w_adj: Adjacency,
    w_boundary_labels: BoundaryLabels,
    w_hourglasses: List[Hourglass],
    *,
    allow_w_wrench: bool = True,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
    beam_width: int = 500,
    max_steps: Optional[int] = None,
    x_node_colors: Optional[NodeColors] = None,
    x_node_xy: Optional[NodeXY] = None,
    w_node_colors: Optional[NodeColors] = None,
    w_node_xy: Optional[NodeXY] = None,
) -> Dict[str, Any]:
    """Evaluate a pair by continuing wrench expansion after guided stalls.

    ``prove_pair_zero_allowing_w_wrench`` is optimized for quick zero proofs:
    it follows branches that immediately create fork cancellations.  Some hard
    pairs require neutral wrench moves first, then later fork cancellations or
    coloring.  This routine keeps applying wrench moves to surviving branches
    until either all active terms are discharged, every surviving term is
    colorable, or the step/beam limits are reached.
    """
    initial_remaining = len(x_hourglasses) + (len(w_hourglasses) if allow_w_wrench else 0)
    if max_steps is None:
        max_steps = max(80, 8 * initial_remaining)

    initial_terms = [
        {
            "x_adj": x_adj,
            "x_remaining": x_hourglasses,
            "w_adj": w_adj,
            "w_remaining": w_hourglasses,
            "coeff": 1,
            "history": [],
        }
    ]
    active, discharged = discharge_pair_terms_by_common_fork(
        initial_terms,
        x_boundary_labels,
        w_boundary_labels,
        allowed_forks,
    )
    initial_state = {
        "active": active,
        "discharged": discharged,
        "score": score_pair_state(active, discharged, x_boundary_labels, w_boundary_labels, allowed_forks),
    }
    beam = [initial_state]
    best_state = initial_state
    step_summaries: List[Dict[str, Any]] = []

    for step in range(max_steps + 1):
        for state in beam:
            if not state["active"]:
                return pair_proof_result_from_state(
                    state,
                    x_boundary_labels,
                    w_boundary_labels,
                    allowed_forks,
                    max_steps,
                    step_summaries,
                    status="proved_zero",
                    final_pairing_value=0,
                    allow_w_wrench=allow_w_wrench,
                )
            evaluated = evaluate_pair_state_by_coloring(state, x_boundary_labels, w_boundary_labels, r=4)
            if evaluated is not None:
                value, evaluations = evaluated
                return pair_proof_result_from_state(
                    state,
                    x_boundary_labels,
                    w_boundary_labels,
                    allowed_forks,
                    max_steps,
                    step_summaries,
                    status="evaluated_by_coloring",
                    final_pairing_value=value,
                    coloring_evaluations=evaluations,
                    allow_w_wrench=allow_w_wrench,
                )
        if step == max_steps:
            break

        candidates: List[Dict[str, Any]] = []
        for state in beam:
            candidates.extend(
                choose_pair_successors(
                    state["active"],
                    state["discharged"],
                    x_boundary_labels,
                    w_boundary_labels,
                    allow_w_wrench=allow_w_wrench,
                    allowed_forks=allowed_forks,
                    x_node_colors=x_node_colors,
                    x_node_xy=x_node_xy,
                    w_node_colors=w_node_colors,
                    w_node_xy=w_node_xy,
                )
            )
        if not candidates:
            break

        candidates.sort(
            key=lambda state: complete_pair_state_score(
                state,
                x_boundary_labels,
                w_boundary_labels,
                allowed_forks,
            ),
            reverse=True,
        )
        beam = candidates[:beam_width]
        if complete_pair_state_score(
            beam[0],
            x_boundary_labels,
            w_boundary_labels,
            allowed_forks,
        ) > complete_pair_state_score(
            best_state,
            x_boundary_labels,
            w_boundary_labels,
            allowed_forks,
        ):
            best_state = beam[0]
        step_summaries.append(
            {
                "step": step + 1,
                "best_score": list(
                    complete_pair_state_score(
                        beam[0],
                        x_boundary_labels,
                        w_boundary_labels,
                        allowed_forks,
                    )
                ),
                "active_terms": len(beam[0]["active"]),
                "discharged_terms": len(beam[0]["discharged"]),
                "remaining_hourglasses": pair_state_remaining_hourglasses(beam[0]),
                "expanded_side": beam[0].get("expanded_side"),
                "expanded_hourglass": beam[0].get("expanded_hourglass"),
                "expanded_relation": beam[0].get("expanded_relation"),
                "expanded_rule": beam[0].get("expanded_rule"),
                "expanded_vertices": beam[0].get("expanded_vertices"),
            }
        )

    return pair_proof_result_from_state(
        best_state,
        x_boundary_labels,
        w_boundary_labels,
        allowed_forks,
        max_steps,
        step_summaries,
        status="partial",
        final_pairing_value=None,
        allow_w_wrench=allow_w_wrench,
    )


def prove_pair_value_by_x_component_coloring(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    x_hourglasses: List[Hourglass],
    w_adj: Adjacency,
    w_boundary_labels: BoundaryLabels,
    w_hourglasses: List[Hourglass],
    *,
    allow_w_wrench: bool = True,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
    guided_beam_width: int = 200,
    x_beam_width: int = 500,
    guided_steps: Optional[int] = None,
    x_resolution_steps: Optional[int] = None,
    x_node_colors: Optional[NodeColors] = None,
    x_node_xy: Optional[NodeXY] = None,
    w_node_colors: Optional[NodeColors] = None,
    w_node_xy: Optional[NodeXY] = None,
) -> Dict[str, Any]:
    """Guided wrench/fork simplification, then X-component coloring.

    The phases are:
    1. Apply strategic wrench moves on W or X, discharging common forks.
    2. If active terms remain, remove all remaining X-hourglasses by applying
       wrench moves only to X.  W-hourglasses are left in place.
    3. Color each connected component of X, transfer boundary colors to W, and
       count W colorings.  Each remaining W-hourglass contributes two distinct
       strand colors, counted up to swapping the two hourglass strands.
    """
    initial_remaining = len(x_hourglasses) + (len(w_hourglasses) if allow_w_wrench else 0)
    if guided_steps is None:
        guided_steps = initial_remaining
    if x_resolution_steps is None:
        x_resolution_steps = max(40, 8 * max(1, len(x_hourglasses)))

    initial_terms = [
        {
            "x_adj": x_adj,
            "x_remaining": x_hourglasses,
            "w_adj": w_adj,
            "w_remaining": w_hourglasses,
            "coeff": 1,
            "history": [],
        }
    ]
    active, discharged = discharge_pair_terms_by_common_fork(
        initial_terms,
        x_boundary_labels,
        w_boundary_labels,
        allowed_forks,
    )
    beam = [
        {
            "active": active,
            "discharged": discharged,
            "score": score_pair_state(active, discharged, x_boundary_labels, w_boundary_labels, allowed_forks),
        }
    ]
    best_state = beam[0]
    step_summaries: List[Dict[str, Any]] = []

    for step in range(guided_steps):
        if any(not state["active"] for state in beam):
            best_state = next(state for state in beam if not state["active"])
            return pair_proof_result_from_state(
                best_state,
                x_boundary_labels,
                w_boundary_labels,
                allowed_forks,
                guided_steps + x_resolution_steps,
                step_summaries,
                status="proved_zero",
                final_pairing_value=0,
                allow_w_wrench=allow_w_wrench,
            )
        candidates: List[Dict[str, Any]] = []
        for state in beam:
            candidates.extend(
                choose_pair_successors(
                    state["active"],
                    state["discharged"],
                    x_boundary_labels,
                    w_boundary_labels,
                    allow_w_wrench=allow_w_wrench,
                    allowed_forks=allowed_forks,
                    x_node_colors=x_node_colors,
                    x_node_xy=x_node_xy,
                    w_node_colors=w_node_colors,
                    w_node_xy=w_node_xy,
                )
            )
        if not candidates:
            break
        candidates.sort(key=lambda state: state["score"], reverse=True)
        beam = candidates[:guided_beam_width]
        if beam[0]["score"] > best_state["score"]:
            best_state = beam[0]
        step_summaries.append(
            {
                "phase": "guided",
                "step": step + 1,
                "best_score": list(beam[0]["score"]),
                "active_terms": len(beam[0]["active"]),
                "discharged_terms": len(beam[0]["discharged"]),
                "remaining_hourglasses": pair_state_remaining_hourglasses(beam[0]),
                "x_remaining_hourglasses": sum(len(t["x_remaining"]) for t in beam[0]["active"]),
                "w_remaining_hourglasses": sum(len(t["w_remaining"]) for t in beam[0]["active"]),
                "expanded_side": beam[0].get("expanded_side"),
                "expanded_hourglass": beam[0].get("expanded_hourglass"),
                "expanded_relation": beam[0].get("expanded_relation"),
                "expanded_rule": beam[0].get("expanded_rule"),
                "expanded_vertices": beam[0].get("expanded_vertices"),
            }
        )

    # Phase 2: resolve X-hourglasses only.  Use the whole beam from phase 1, not
    # just best_state, because a slightly worse guided state may color better.
    for step in range(x_resolution_steps + 1):
        for state in beam:
            if not state["active"]:
                return pair_proof_result_from_state(
                    state,
                    x_boundary_labels,
                    w_boundary_labels,
                    allowed_forks,
                    guided_steps + x_resolution_steps,
                    step_summaries,
                    status="proved_zero",
                    final_pairing_value=0,
                    allow_w_wrench=allow_w_wrench,
                )
            if x_state_ready_for_coloring(state, x_boundary_labels, x_node_colors):
                evaluated = evaluate_pair_state_by_x_component_coloring(
                    state,
                    x_boundary_labels,
                    w_boundary_labels,
                    r=4,
                )
                if evaluated is not None:
                    value, evaluations = evaluated
                    return pair_proof_result_from_state(
                        state,
                        x_boundary_labels,
                        w_boundary_labels,
                        allowed_forks,
                        guided_steps + x_resolution_steps,
                        step_summaries,
                        status="evaluated_by_x_component_coloring",
                        final_pairing_value=value,
                        coloring_evaluations=evaluations,
                        allow_w_wrench=allow_w_wrench,
                    )
        if step == x_resolution_steps:
            break

        candidates = []
        for state in beam:
            candidates.extend(
                choose_x_resolution_successors(
                    state["active"],
                    state["discharged"],
                    x_boundary_labels,
                    w_boundary_labels,
                    allowed_forks,
                    x_node_colors=x_node_colors,
                    x_node_xy=x_node_xy,
                )
            )
        if not candidates:
            break

        def x_resolution_score(state: Dict[str, Any]) -> Tuple[int, int, int, int, int, int]:
            x_remaining = sum(len(t["x_remaining"]) for t in state["active"])
            x_black = sum(
                len(term_x_internal_black_vertices(t, x_boundary_labels, x_node_colors))
                for t in state["active"]
            )
            w_remaining = sum(len(t["w_remaining"]) for t in state["active"])
            return (
                1 if x_remaining == 0 and x_black == 0 else 0,
                -x_remaining,
                -x_black,
                len(state["discharged"]),
                -len(state["active"]),
                -w_remaining,
            )

        candidates.sort(key=x_resolution_score, reverse=True)
        beam = candidates[:x_beam_width]
        if x_resolution_score(beam[0]) > x_resolution_score(best_state):
            best_state = beam[0]
        step_summaries.append(
            {
                "phase": "resolve_x",
                "step": step + 1,
                "best_score": list(x_resolution_score(beam[0])),
                "active_terms": len(beam[0]["active"]),
                "discharged_terms": len(beam[0]["discharged"]),
                "remaining_hourglasses": pair_state_remaining_hourglasses(beam[0]),
                "x_remaining_hourglasses": sum(len(t["x_remaining"]) for t in beam[0]["active"]),
                "w_remaining_hourglasses": sum(len(t["w_remaining"]) for t in beam[0]["active"]),
                "expanded_side": beam[0].get("expanded_side"),
                "expanded_hourglass": beam[0].get("expanded_hourglass"),
                "expanded_relation": beam[0].get("expanded_relation"),
                "expanded_rule": beam[0].get("expanded_rule"),
                "expanded_vertices": beam[0].get("expanded_vertices"),
            }
        )

    return pair_proof_result_from_state(
        best_state,
        x_boundary_labels,
        w_boundary_labels,
        allowed_forks,
        guided_steps + x_resolution_steps,
        step_summaries,
        status="partial",
        final_pairing_value=None,
        allow_w_wrench=allow_w_wrench,
    )


def prove_pair_zero_allowing_w_wrench(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    x_hourglasses: List[Hourglass],
    w_adj: Adjacency,
    w_boundary_labels: BoundaryLabels,
    w_hourglasses: List[Hourglass],
    *,
    allow_w_wrench: bool = True,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
    beam_width: int = 80,
    max_steps: Optional[int] = None,
) -> Dict[str, Any]:
    if max_steps is None:
        max_steps = len(x_hourglasses) + (len(w_hourglasses) if allow_w_wrench else 0)

    initial_terms = [
        {
            "x_adj": x_adj,
            "x_remaining": x_hourglasses,
            "w_adj": w_adj,
            "w_remaining": w_hourglasses,
            "coeff": 1,
            "history": [],
        }
    ]
    active, discharged = discharge_pair_terms_by_common_fork(
        initial_terms,
        x_boundary_labels,
        w_boundary_labels,
        allowed_forks,
    )
    initial_state = {
        "active": active,
        "discharged": discharged,
        "score": score_pair_state(active, discharged, x_boundary_labels, w_boundary_labels, allowed_forks),
    }
    beam = [initial_state]
    best_state = initial_state
    step_summaries: List[Dict[str, Any]] = []

    for step in range(max_steps):
        if any(not state["active"] for state in beam):
            best_state = next(state for state in beam if not state["active"])
            break
        candidates: List[Dict[str, Any]] = []
        for state in beam:
            candidates.extend(
                choose_pair_successors(
                    state["active"],
                    state["discharged"],
                    x_boundary_labels,
                    w_boundary_labels,
                    allow_w_wrench=allow_w_wrench,
                    allowed_forks=allowed_forks,
                )
            )
        if not candidates:
            break
        candidates.sort(key=lambda state: state["score"], reverse=True)
        beam = candidates[:beam_width]
        if beam[0]["score"] > best_state["score"]:
            best_state = beam[0]
        step_summaries.append(
            {
                "step": step + 1,
                "best_score": list(beam[0]["score"]),
                "active_terms": len(beam[0]["active"]),
                "discharged_terms": len(beam[0]["discharged"]),
                "expanded_side": beam[0].get("expanded_side"),
                "expanded_hourglass": beam[0].get("expanded_hourglass"),
            }
        )

    status = "proved_zero" if not best_state["active"] else "partial"
    coloring_evaluations = []
    final_pairing_value: Optional[int] = 0 if not best_state["active"] else 0
    for term in best_state["active"]:
        try:
            evaluation = evaluate_pair_by_coloring(
                term["x_adj"],
                x_boundary_labels,
                term["w_adj"],
                w_boundary_labels,
                x_hourglasses=term["x_remaining"],
                w_hourglasses=term["w_remaining"],
                r=4,
            )
        except ValueError as exc:
            evaluation = {
                "status": "not_computed",
                "reason": str(exc),
            }
        evaluation["coeff"] = term["coeff"]
        if evaluation["status"] == "computed":
            evaluation["term_value"] = term["coeff"] * int(evaluation["coloring_count"])
            final_pairing_value = int(final_pairing_value or 0) + int(evaluation["term_value"])
        else:
            evaluation["term_value"] = None
            final_pairing_value = None
        coloring_evaluations.append(evaluation)

    if status != "proved_zero" and final_pairing_value is not None:
        status = "evaluated_by_coloring"

    return {
        "status": status,
        "allow_w_wrench": allow_w_wrench,
        "allowed_forks": None if allowed_forks is None else sorted([fork_to_list(f) for f in allowed_forks]),
        "steps_requested": max_steps,
        "steps": step_summaries,
        "discharged_terms": best_state["discharged"],
        "active_terms": [
            pair_active_term_summary(t, x_boundary_labels, w_boundary_labels, allowed_forks)
            for t in best_state["active"]
        ],
        "active_term_count": len(best_state["active"]),
        "discharged_term_count": len(best_state["discharged"]),
        "score": list(best_state["score"]),
        "coloring_evaluations": coloring_evaluations,
        "final_pairing_value": final_pairing_value,
    }


def pair_active_term_summary(
    term: Dict[str, Any],
    x_boundary_labels: BoundaryLabels,
    w_boundary_labels: BoundaryLabels,
    allowed_forks: Optional[Set[frozenset[int]]] = None,
) -> Dict[str, Any]:
    common = common_pair_forks(
        term["x_adj"],
        x_boundary_labels,
        term["w_adj"],
        w_boundary_labels,
        allowed_forks,
    )
    return {
        "coeff": term["coeff"],
        "common_forks": sorted([fork_to_list(f) for f in common]),
        "x_forks": sorted([fork_to_list(f) for f in get_forks(term["x_adj"], x_boundary_labels)]),
        "w_forks": sorted([fork_to_list(f) for f in get_forks(term["w_adj"], w_boundary_labels)]),
        "x_remaining_hourglasses": len(term["x_remaining"]),
        "w_remaining_hourglasses": len(term["w_remaining"]),
        "history": term_history(term),
        "x_edges": [list(edge) for edge in get_edge_tuple(term["x_adj"])],
        "w_edges": [list(edge) for edge in get_edge_tuple(term["w_adj"])],
    }


def graph_components(adj: Adjacency) -> List[Set[int]]:
    seen: Set[int] = set()
    comps: List[Set[int]] = []
    for start in adj:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        comp: Set[int] = set()
        while stack:
            u = stack.pop()
            comp.add(u)
            for v in neighbor_list(adj[u]):
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(comp)
    return comps


def plucker_product_components(
    adj: Adjacency,
    boundary_labels: BoundaryLabels,
    *,
    r: int = 4,
) -> Optional[List[List[int]]]:
    """Return Plucker factor boundary sets if the term is a product of claws.

    A product of Plucker coordinates appears as r connected components, each
    with exactly one internal vertex and r boundary vertices.  The component
    with boundary labels I represents one factor Delta_I.  Components are
    returned in canonical order by their smallest boundary label.
    """
    components: List[List[int]] = []
    for comp in graph_components(adj):
        b_labels = sorted(boundary_labels[n] for n in comp if n in boundary_labels)
        internal = [n for n in comp if n not in boundary_labels]
        if len(b_labels) != r or len(internal) != 1:
            return None
        hub = internal[0]
        hub_neighbors = set(neighbor_list(adj[hub]))
        if len(hub_neighbors) != r:
            return None
        if any(n not in boundary_labels for n in hub_neighbors):
            return None
        if sorted(boundary_labels[n] for n in hub_neighbors) != b_labels:
            return None
        components.append(b_labels)
    if len(components) != r:
        return None
    all_labels = sorted(label for component in components for label in component)
    if all_labels != list(range(1, r * r + 1)):
        return None
    return sorted(components, key=lambda labels: (min(labels), labels))


def boundary_condition_from_plucker_components(
    components: List[List[int]],
) -> Dict[int, int]:
    """Assign color c to every boundary label in the c-th canonical factor."""
    color_of_label: Dict[int, int] = {}
    for color, labels in enumerate(components, start=1):
        for label in labels:
            color_of_label[int(label)] = color
    return color_of_label


def count_consistent_colorings(
    adj: Adjacency,
    boundary_labels: BoundaryLabels,
    boundary_color_by_label: Dict[int, int],
    *,
    hourglasses: Optional[List[Hourglass]] = None,
    r: int = 4,
    limit: Optional[int] = None,
) -> int:
    """Count consistent SL_r edge labelings with fixed boundary colors."""
    return int(
        consistent_coloring_data(
            adj,
            boundary_labels,
            boundary_color_by_label,
            hourglasses=hourglasses,
            r=r,
            limit=limit,
        )["count"]
    )


def consistent_coloring_data(
    adj: Adjacency,
    boundary_labels: BoundaryLabels,
    boundary_color_by_label: Dict[int, int],
    *,
    hourglasses: Optional[List[Hourglass]] = None,
    r: int = 4,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Count colorings and keep one sample coloring for display.

    Ordinary edges have multiplicity one.  Each unresolved hourglass contributes
    two distinct strands between its endpoints, but the two hourglass strands
    are an unordered pair for counting.  Thus swapping just the two colors on
    an hourglass does not create a new coloring.  If an ordinary external edge
    also joins the same endpoints, it remains a separate edge; the vertex rule
    then forces the two hourglass colors and the external edge color to be
    three distinct colors.
    """
    hourglasses = hourglasses or []
    covered_hourglass_nodes = {
        int(endpoint)
        for hg in hourglasses
        for endpoint in (int(hg["white"]), int(hg["black"]))
        if int(endpoint) in adj
    }
    uncovered = [
        node
        for node, neighbors in adj.items()
        if isinstance(neighbors, dict) and node not in covered_hourglass_nodes
    ]
    if uncovered:
        raise ValueError(
            "Coloring fallback saw hourglass-style vertices without matching "
            f"remaining hourglass metadata: {uncovered}"
        )

    edges: List[Tuple[int, int]] = []
    edge_meta: List[Dict[str, Any]] = []
    for u, neighbors in adj.items():
        for v in neighbor_list(neighbors):
            if u <= v:
                edges.append((u, v))
                edge_meta.append({"kind": "ordinary"})
    hourglass_edge_pairs: List[Tuple[int, int]] = []
    for hg in hourglasses:
        white = int(hg["white"])
        black = int(hg["black"])
        if white in adj and black in adj:
            first = len(edges)
            edges.append((white, black))
            edge_meta.append({"kind": "hourglass", "hourglass": (white, black), "strand": 0})
            second = len(edges)
            edges.append((white, black))
            edge_meta.append({"kind": "hourglass", "hourglass": (white, black), "strand": 1})
            hourglass_edge_pairs.append((first, second))

    incident_edges: Dict[int, List[int]] = {n: [] for n in adj}
    fixed: Dict[int, int] = {}
    for idx, (u, v) in enumerate(edges):
        incident_edges[u].append(idx)
        incident_edges[v].append(idx)
        if u in boundary_labels and v in boundary_labels:
            raise ValueError("Boundary-boundary edge is not supported by the coloring fallback.")
        if u in boundary_labels or v in boundary_labels:
            bnode = u if u in boundary_labels else v
            label = boundary_labels[bnode]
            if label not in boundary_color_by_label:
                return {"count": 0, "sample_edge_colors": [], "sample_hourglass_colors": []}
            fixed[idx] = int(boundary_color_by_label[label])

    colors = [0] * len(edges)
    for idx, color in fixed.items():
        colors[idx] = color

    internal_vertices = [n for n in adj if n not in boundary_labels]
    for vertex in internal_vertices:
        if len(incident_edges[vertex]) != r:
            return {"count": 0, "sample_edge_colors": [], "sample_hourglass_colors": []}

    remaining_edges = [idx for idx in range(len(edges)) if idx not in fixed]
    # Branch on the most constrained edges first: internal-internal edges usually
    # sit in two vertex constraints.
    remaining_edges.sort(key=lambda idx: -sum(1 for endpoint in edges[idx] if endpoint not in boundary_labels))

    def vertex_possible(vertex: int) -> bool:
        seen: Set[int] = set()
        unknown = 0
        for idx in incident_edges[vertex]:
            color = colors[idx]
            if color == 0:
                unknown += 1
            elif color in seen:
                return False
            else:
                seen.add(color)
        return len(seen) + unknown == r

    def vertex_complete(vertex: int) -> bool:
        return {colors[idx] for idx in incident_edges[vertex]} == set(range(1, r + 1))

    def hourglass_order_possible() -> bool:
        for first, second in hourglass_edge_pairs:
            left = colors[first]
            right = colors[second]
            if left and right and left >= right:
                return False
        return True

    for vertex in internal_vertices:
        if not vertex_possible(vertex):
            return {"count": 0, "sample_edge_colors": [], "sample_hourglass_colors": []}

    total = 0
    sample: Optional[List[int]] = None

    def backtrack(pos: int) -> None:
        nonlocal total, sample
        if limit is not None and total >= limit:
            return
        if pos == len(remaining_edges):
            if hourglass_order_possible() and all(vertex_complete(vertex) for vertex in internal_vertices):
                total += 1
                if sample is None:
                    sample = list(colors)
            return

        edge_idx = remaining_edges[pos]
        endpoints = [endpoint for endpoint in edges[edge_idx] if endpoint not in boundary_labels]
        for color in range(1, r + 1):
            colors[edge_idx] = color
            if hourglass_order_possible() and all(vertex_possible(vertex) for vertex in endpoints):
                backtrack(pos + 1)
            colors[edge_idx] = 0

    backtrack(0)
    sample_edge_colors: List[Dict[str, Any]] = []
    sample_hourglass_colors: List[Dict[str, Any]] = []
    if sample is not None:
        hourglass_indices = {idx for pair in hourglass_edge_pairs for idx in pair}
        for idx, (u, v) in enumerate(edges):
            if idx in hourglass_indices:
                continue
            sample_edge_colors.append(
                {
                    "edge": [int(u), int(v)],
                    "kind": str(edge_meta[idx].get("kind", "ordinary")),
                    "color": int(sample[idx]),
                }
            )
        for first, second in hourglass_edge_pairs:
            u, v = edges[first]
            sample_hourglass_colors.append(
                {
                    "edge": [int(u), int(v)],
                    "colors": [int(sample[first]), int(sample[second])],
                    "unordered": True,
                }
            )
    return {
        "count": total,
        "sample_edge_colors": sample_edge_colors,
        "sample_hourglass_colors": sample_hourglass_colors,
        "hourglass_edge_pairs": len(hourglass_edge_pairs),
        "hourglass_swap_quotient": True,
    }


def evaluate_pair_by_coloring(
    x_adj: Adjacency,
    x_boundary_labels: BoundaryLabels,
    w_adj: Adjacency,
    w_boundary_labels: BoundaryLabels,
    *,
    x_hourglasses: Optional[List[Hourglass]] = None,
    w_hourglasses: Optional[List[Hourglass]] = None,
    r: int = 4,
) -> Dict[str, Any]:
    """Evaluate a surviving pair term by the Proposition 2.20 coloring count.

    We currently apply this when either side has become a product of Plucker
    claws.  The Plucker-product side supplies a canonical ordered list of
    factors, hence a boundary color condition; the value is the number of
    consistent colorings of the other side with that condition.
    """
    x_components = plucker_product_components(x_adj, x_boundary_labels, r=r)
    if x_components is not None:
        condition = boundary_condition_from_plucker_components(x_components)
        coloring = consistent_coloring_data(
            w_adj,
            w_boundary_labels,
            condition,
            hourglasses=w_hourglasses,
            r=r,
        )
        return {
            "status": "computed",
            "source_side": "X",
            "plucker_factors": x_components,
            "boundary_color_by_label": condition,
            "coloring_count": int(coloring["count"]),
            "sample_edge_colors": coloring.get("sample_edge_colors", []),
            "sample_hourglass_colors": coloring.get("sample_hourglass_colors", []),
            "hourglass_swap_quotient": coloring.get("hourglass_swap_quotient", True),
        }

    w_components = plucker_product_components(w_adj, w_boundary_labels, r=r)
    if w_components is not None:
        condition = boundary_condition_from_plucker_components(w_components)
        coloring = consistent_coloring_data(
            x_adj,
            x_boundary_labels,
            condition,
            hourglasses=x_hourglasses,
            r=r,
        )
        return {
            "status": "computed",
            "source_side": "W",
            "plucker_factors": w_components,
            "boundary_color_by_label": condition,
            "coloring_count": int(coloring["count"]),
            "sample_edge_colors": coloring.get("sample_edge_colors", []),
            "sample_hourglass_colors": coloring.get("sample_hourglass_colors", []),
            "hourglass_swap_quotient": coloring.get("hourglass_swap_quotient", True),
        }

    return {
        "status": "not_computed",
        "reason": "neither surviving side is a detected Plucker-product term",
    }


def should_prune(
    adj: Adjacency,
    boundary_labels: BoundaryLabels,
    ref_forks: Set[frozenset[int]],
    ref_direct: Set[frozenset[int]],
) -> bool:
    current_direct = get_direct_boundary_edges(adj, boundary_labels)
    if current_direct.intersection(ref_forks):
        return True
    current_forks = get_forks(adj, boundary_labels)
    return bool(current_forks.intersection(ref_direct))


def apply_wrench_expansion(
    adj: Adjacency,
    hourglasses: List[Hourglass],
    coeff: int,
    boundary_labels: BoundaryLabels,
    *,
    prune: bool = False,
    ref_forks: Optional[Set[frozenset[int]]] = None,
    ref_direct: Optional[Set[frozenset[int]]] = None,
) -> List[Dict[str, Any]]:
    if prune and should_prune(adj, boundary_labels, ref_forks or set(), ref_direct or set()):
        return []

    if not hourglasses:
        return [{"coeff": coeff, "adj": adj}]

    hg = hourglasses[0]
    remaining = hourglasses[1:]

    crossing_adj = smooth_one_hourglass(adj, hg, "crossing")
    parallel_adj = smooth_one_hourglass(adj, hg, "parallel")

    return (
        apply_wrench_expansion(
            crossing_adj,
            remaining,
            coeff,
            boundary_labels,
            prune=prune,
            ref_forks=ref_forks,
            ref_direct=ref_direct,
        )
        + apply_wrench_expansion(
            parallel_adj,
            remaining,
            -coeff,
            boundary_labels,
            prune=prune,
            ref_forks=ref_forks,
            ref_direct=ref_direct,
        )
    )


def apply_skein(*args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """Backward-compatible alias for older notebooks/scripts."""
    return apply_wrench_expansion(*args, **kwargs)


def get_edge_tuple(adj: Adjacency) -> Tuple[Tuple[int, int], ...]:
    edges = []
    for u, neighbors in adj.items():
        for v in neighbor_list(neighbors):
            if u <= v:
                edges.append((u, v))
    return tuple(sorted(edges))


def consolidate_webs(webs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    consolidated: Dict[Tuple[Tuple[int, int], ...], Dict[str, Any]] = {}
    for web in webs:
        edge_tuple = get_edge_tuple(web["adj"])
        if edge_tuple not in consolidated:
            consolidated[edge_tuple] = {"coeff": 0, "adj": web["adj"]}
        consolidated[edge_tuple]["coeff"] += web["coeff"]
    return [web for web in consolidated.values() if web["coeff"] != 0]


def web_to_jsonable(web: Dict[str, Any], boundary_labels: BoundaryLabels) -> Dict[str, Any]:
    return {
        "coeff": web["coeff"],
        "edges": [list(edge) for edge in get_edge_tuple(web["adj"])],
        "boundary_labels": {str(k): v for k, v in sorted(boundary_labels.items())},
    }


def visualize_summation(
    surviving_webs: List[Dict[str, Any]],
    boundary_labels: BoundaryLabels,
    *,
    max_display: int = 50,
) -> None:
    try:
        import matplotlib.pyplot as plt
        import networkx as nx
    except ImportError as exc:
        raise SystemExit(
            "Visualization needs matplotlib and networkx. The algebraic expansion was computed; "
            "install those packages or rerun without --visualize."
        ) from exc

    n_webs = len(surviving_webs)
    if n_webs == 0:
        print("No surviving webs to visualize.")
        return

    display_webs = surviving_webs[:max_display]
    cols = min(5, len(display_webs))
    rows = math.ceil(len(display_webs) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
    axes_flat = [axes] if rows == 1 and cols == 1 else axes.flatten()

    for idx, (web_data, ax) in enumerate(zip(display_webs, axes_flat)):
        graph = nx.MultiGraph()
        for u, neighbors in web_data["adj"].items():
            for v in neighbor_list(neighbors):
                if u <= v:
                    graph.add_edge(u, v)

        boundaries = sorted([n for n in graph.nodes if n in boundary_labels], key=boundary_labels.get)
        fixed_pos = {}
        for i, node in enumerate(boundaries):
            angle = -2 * math.pi * i / len(boundaries) + math.pi / 2
            fixed_pos[node] = (math.cos(angle), math.sin(angle))
        pos = nx.spring_layout(graph, pos=fixed_pos, fixed=boundaries, seed=42)

        internals = [n for n in graph.nodes if n not in boundary_labels]
        nx.draw_networkx_nodes(graph, pos, nodelist=boundaries, node_color="black", node_size=100, ax=ax)
        nx.draw_networkx_nodes(
            graph,
            pos,
            nodelist=internals,
            node_color="white",
            edgecolors="black",
            node_size=60,
            ax=ax,
        )
        nx.draw_networkx_edges(graph, pos, ax=ax, width=1.5)

        label_pos = {n: (pos[n][0] * 1.15, pos[n][1] * 1.15) for n in boundaries}
        nx.draw_networkx_labels(
            graph,
            label_pos,
            labels={n: boundary_labels[n] for n in boundaries},
            font_size=10,
            ax=ax,
        )

        ax.set_title(f"{web_data['coeff']} * Web", fontsize=14, fontweight="bold")
        ax.axis("off")

    for ax in axes_flat[len(display_webs) :]:
        ax.axis("off")
    if n_webs > max_display:
        plt.figtext(0.5, 0.01, f"... and {n_webs - max_display} more webs not shown", ha="center")
    plt.tight_layout()
    plt.show()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        default="0447_1112122334344234.json",
        help="Target primal web JSON path or filename.",
    )
    parser.add_argument(
        "--reference",
        default="0447_1231423121323444.json",
        help="Optional reference web JSON used only when --prune-with-reference is set.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=DEFAULT_PROJECT_ROOTS[0],
        help="Project folder used when resolving bare JSON filenames.",
    )
    parser.add_argument(
        "--left-endpoint",
        choices=["black", "white"],
        default="black",
        help="Which hourglass endpoint is treated as the left side of the Figure 4 local relation.",
    )
    parser.add_argument(
        "--prune-with-reference",
        action="store_true",
        help="Apply the old reference-based pruning after each local expansion step.",
    )
    parser.add_argument("--json-out", type=Path, help="Write consolidated expansion data as JSON.")
    parser.add_argument("--visualize", action="store_true", help="Show a quick NetworkX visualization.")
    parser.add_argument("--max-display", type=int, default=50)
    parser.add_argument(
        "--strategic-forks",
        action="store_true",
        help="Search for wrench moves on the target X that create forks appearing in the reference W.",
    )
    parser.add_argument(
        "--target-fork",
        help="Restrict the strategic search to one W fork, written like 'i,j'.",
    )
    parser.add_argument("--beam-width", type=int, default=20, help="Number of strategic branches to keep.")
    parser.add_argument(
        "--max-depth",
        type=int,
        help="Maximum number of successive wrench moves in the strategic search.",
    )
    parser.add_argument(
        "--strategy-json-out",
        type=Path,
        help="Write the strategic fork-search result as JSON.",
    )
    parser.add_argument(
        "--prove-pair-zero",
        action="store_true",
        help=(
            "Beam-search a full linear proof: expand X by wrench moves until branches "
            "are discharged by common forks with the reference W."
        ),
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        help="Maximum number of total strategic wrench expansions for --prove-pair-zero.",
    )
    parser.add_argument(
        "--proof-json-out",
        type=Path,
        help="Write the full pair-zero proof-search result as JSON.",
    )
    parser.add_argument(
        "--allow-w-wrench",
        action="store_true",
        help="In --prove-pair-zero mode, also allow strategic wrench moves on the reference/transpose web W.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    target_path = resolve_json_path(args.target, args.project_root)
    adj, boundary_labels, hourglasses = parse_web(target_path, left_endpoint=args.left_endpoint)
    hourglasses = sort_hourglasses_by_boundary_distance(adj, boundary_labels, hourglasses)

    if args.prove_pair_zero:
        reference_path = resolve_json_path(args.reference, args.project_root)
        ref_adj, ref_boundary_labels, ref_hourglasses = parse_web(reference_path, left_endpoint=args.left_endpoint)
        ref_hourglasses = sort_hourglasses_by_boundary_distance(ref_adj, ref_boundary_labels, ref_hourglasses)
        target_forks = get_forks(ref_adj, ref_boundary_labels)
        if args.target_fork:
            requested_fork = parse_fork_label(args.target_fork)
            if requested_fork not in target_forks:
                print(
                    f"Warning: requested fork {fork_to_list(requested_fork)} is not a fork in W; "
                    "the proof search will still target it."
                )
            target_forks = {requested_fork}

        if args.allow_w_wrench:
            proof = prove_pair_zero_allowing_w_wrench(
                adj,
                boundary_labels,
                hourglasses,
                ref_adj,
                ref_boundary_labels,
                ref_hourglasses,
                allow_w_wrench=True,
                allowed_forks={requested_fork} if args.target_fork else None,
                beam_width=args.beam_width,
                max_steps=args.max_steps,
            )
        else:
            proof = prove_pair_zero_by_wrench_and_forks(
                adj,
                boundary_labels,
                hourglasses,
                target_forks,
                beam_width=args.beam_width,
                max_steps=args.max_steps,
            )
        print(f"Target X: {target_path}")
        print(f"Reference W: {reference_path}")
        print(f"Allow wrench moves on W: {args.allow_w_wrench}")
        print(f"Proof-search status: {proof['status']}")
        print(f"Discharged terms: {proof['discharged_term_count']}")
        print(f"Active terms left: {proof['active_term_count']}")
        if "final_pairing_value" in proof:
            print(f"Final pairing value from coloring fallback: {proof['final_pairing_value']}")
        for step in proof["steps"]:
            print(
                f"  step {step['step']}: active={step['active_terms']}, "
                f"discharged={step['discharged_terms']}, "
                f"expanded_side={step.get('expanded_side', 'X')}, "
                f"expanded_hourglass={step['expanded_hourglass']}, score={step['best_score']}"
            )
        if proof["active_terms"]:
            print("Remaining active branches:")
            for idx, term in enumerate(proof["active_terms"][:10], start=1):
                print(
                    f"  {idx}. coeff={term['coeff']}, "
                    f"remaining_hourglasses="
                    f"{term.get('remaining_hourglasses', term.get('x_remaining_hourglasses'))}, "
                    f"forks={term.get('all_forks', term.get('x_forks'))}"
                )
        for idx, evaluation in enumerate(proof.get("coloring_evaluations", []), start=1):
            print(
                f"Coloring fallback term {idx}: status={evaluation['status']}, "
                f"source_side={evaluation.get('source_side')}, "
                f"count={evaluation.get('coloring_count')}, "
                f"term_value={evaluation.get('term_value')}"
            )
        if args.proof_json_out:
            args.proof_json_out.write_text(json.dumps(proof, indent=2), encoding="utf-8")
            print(f"Wrote {args.proof_json_out}")
        return

    if args.strategic_forks:
        reference_path = resolve_json_path(args.reference, args.project_root)
        ref_adj, ref_boundary_labels, _ = parse_web(reference_path, left_endpoint=args.left_endpoint)
        target_forks = get_forks(ref_adj, ref_boundary_labels)
        if args.target_fork:
            requested_fork = parse_fork_label(args.target_fork)
            if requested_fork not in target_forks:
                print(
                    f"Warning: requested fork {fork_to_list(requested_fork)} is not a fork in W; "
                    "the search will still target it."
                )
            target_forks = {requested_fork}

        result = strategic_fork_search(
            adj,
            boundary_labels,
            hourglasses,
            target_forks,
            beam_width=args.beam_width,
            max_depth=args.max_depth,
        )

        print(f"Target X: {target_path}")
        print(f"Reference W: {reference_path}")
        print(f"W target forks: {result['target_forks']}")
        print(f"Initial common forks: {result['starting_common_forks']}")
        print(f"Strategic search status: {result['status']}")
        if result["branches"]:
            best = result["branches"][0]
            print(f"Best common forks: {best['common_forks']}")
            print(f"Best coefficient: {best['coeff']}")
            print(f"Moves used: {len(best['moves'])}")
            for move in best["moves"]:
                print(
                    "  "
                    f"step {move['depth']}: hourglass ({move['white']},{move['black']}), "
                    f"{move['smoothing']}, new common forks {move['new_common_forks']}"
                )

        if args.strategy_json_out:
            args.strategy_json_out.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(f"Wrote {args.strategy_json_out}")
        return

    ref_forks: Set[frozenset[int]] = set()
    ref_direct: Set[frozenset[int]] = set()
    if args.prune_with_reference:
        reference_path = resolve_json_path(args.reference, args.project_root)
        ref_adj, ref_boundary_labels, _ = parse_web(reference_path, left_endpoint=args.left_endpoint)
        ref_forks = get_forks(ref_adj, ref_boundary_labels)
        ref_direct = get_direct_boundary_edges(ref_adj, ref_boundary_labels)
        print(f"Reference pruning enabled: {reference_path}")

    print(f"Target: {target_path}")
    print(f"Loaded {len(hourglasses)} hourglass(es).")
    if hourglasses:
        cases = {}
        for hg in hourglasses:
            cases[hg["local_case"]] = cases.get(hg["local_case"], 0) + 1
        print(f"Local cases: {cases}")

    expanded = apply_wrench_expansion(
        adj,
        hourglasses,
        1,
        boundary_labels,
        prune=args.prune_with_reference,
        ref_forks=ref_forks,
        ref_direct=ref_direct,
    )
    consolidated = consolidate_webs(expanded)

    print(f"Branches before consolidation: {len(expanded)}")
    print(f"Unique non-zero webs after consolidation: {len(consolidated)}")
    print(f"Algebraic sum of coefficients: {sum(web['coeff'] for web in consolidated)}")

    if args.json_out:
        payload = {
            "target": str(target_path),
            "left_endpoint": args.left_endpoint,
            "pruned_with_reference": args.prune_with_reference,
            "terms": [web_to_jsonable(web, boundary_labels) for web in consolidated],
        }
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {args.json_out}")

    if args.visualize:
        visualize_summation(consolidated, boundary_labels, max_display=args.max_display)


if __name__ == "__main__":
    main()
