#!/usr/bin/env python3
"""Local diagram-pattern rules translated from the GPPSS/BCGMMW figures.

The goal of this module is deliberately modest: it gives exact JSON-level
detectors for the local configurations that can be recognized from our graph
data without guessing missing information.  For the current exploratory
pairing computations, GPPSS Figure 43 red tags are completely ignored: they
are not treated as graph edges, color constraints, or shape restrictions.
Algebraic signs and branch coefficients are still tracked by the pairing
engine.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


Pair = Tuple[int, int]
APP_DIR = Path(__file__).resolve().parent
LEMMA49_EXEMPLAR_PATH = APP_DIR / "bcgmmw_lemma49_exemplars_0714.json"
SL4_LEMMA49_ZERO_PATTERN_DIR = APP_DIR / "sl4_lemma49_zero_patterns"


FIGURE43_CASES: Dict[Tuple[Tuple[str, str, str, str], Tuple[str, str, str, str]], Dict[str, Any]] = {
    (
        ("hourglass", "ordinary", "hourglass", "ordinary"),
        ("black", "white", "black", "white"),
    ): {
        "name": "GPPSS_F43_top_bottom_hourglasses",
        "source": "GPPSS Figure 43, row 1",
        "relation": "forbidden 4-cycle with top and bottom hourglass sides; diagram reduces to a scalar line through the intermediate equalities",
        "requires_tags": False,
        "tag_convention": "red tags ignored completely; no edge, color, or shape restriction",
    },
    (
        ("hourglass", "hourglass", "ordinary", "ordinary"),
        ("black", "white", "black", "white"),
    ): {
        "name": "GPPSS_F43_adjacent_top_right_hourglasses",
        "source": "GPPSS Figure 43, row 2",
        "relation": "adjacent top/right hourglasses collapse to the diagonal hourglass piece shown in the figure",
        "requires_tags": False,
        "tag_convention": "red tags ignored completely; no edge, color, or shape restriction",
    },
    (
        ("hourglass", "ordinary", "ordinary", "ordinary"),
        ("black", "white", "black", "white"),
    ): {
        "name": "GPPSS_F43_single_top_hourglass",
        "source": "GPPSS Figure 43, row 3",
        "relation": "single top hourglass forbidden 4-cycle gives [2]_q times the tagged hourglass edge",
        "requires_tags": False,
        "tag_convention": "red tags ignored completely; no edge, color, or shape restriction",
    },
    (
        ("ordinary", "hourglass", "ordinary", "ordinary"),
        ("black", "white", "black", "white"),
    ): {
        "name": "GPPSS_F43_single_right_hourglass",
        "source": "GPPSS Figure 43, row 4",
        "relation": "single right hourglass forbidden 4-cycle splits as the horizontal-hourglass cycle plus the vertical hourglass term",
        "requires_tags": False,
        "tag_convention": "red tags ignored completely; no edge, color, or shape restriction",
    },
    (
        ("ordinary", "hourglass", "ordinary", "hourglass"),
        ("black", "white", "black", "white"),
    ): {
        "name": "GPPSS_F43_left_right_hourglasses",
        "source": "GPPSS Figure 43, row 5",
        "relation": "left/right hourglass forbidden 4-cycle gives crossing arcs minus [2]_q times parallel arcs",
        "requires_tags": False,
        "tag_convention": "red tags ignored completely; no edge, color, or shape restriction",
    },
}


def _pair(u: int, v: int) -> Pair:
    return tuple(sorted((int(u), int(v))))


def _node_maps(graph: Dict[str, Any]) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, str], Dict[int, Tuple[float, float]]]:
    nodes = {int(node["id"]): node for node in graph.get("nodes", [])}
    colors = {node_id: str(node.get("color", "")) for node_id, node in nodes.items()}
    xy = {
        node_id: (float(node.get("x", 0.0)), float(node.get("y", 0.0)))
        for node_id, node in nodes.items()
    }
    return nodes, colors, xy


def _ordinary_pairs(graph: Dict[str, Any]) -> Set[Pair]:
    pairs: Set[Pair] = set()
    for edge in graph.get("edges", []):
        if edge.get("double") or edge.get("kind") == "hourglass":
            continue
        pairs.add(_pair(edge["src"], edge["dst"]))
    return pairs


def _hourglass_pairs(graph: Dict[str, Any]) -> Set[Pair]:
    return {_pair(hg["white"], hg["black"]) for hg in graph.get("hourglasses", [])}


def _side_type(pair: Pair, ordinary: Set[Pair], hourglass: Set[Pair]) -> Optional[str]:
    if pair in hourglass:
        return "hourglass"
    if pair in ordinary:
        return "ordinary"
    return None


def _ordered_cycle_vertices(vertices: Iterable[int], xy: Dict[int, Tuple[float, float]]) -> List[int]:
    verts = list(vertices)
    cx = sum(xy[v][0] for v in verts) / len(verts)
    cy = sum(xy[v][1] for v in verts) / len(verts)
    ordered = sorted(verts, key=lambda v: math.atan2(xy[v][1] - cy, xy[v][0] - cx), reverse=True)
    # Rotate so that the first vertex is the top-left/topmost one.  This gives
    # the side order top, right, bottom, left for convex local squares.
    start = min(range(len(ordered)), key=lambda i: (-xy[ordered[i]][1], xy[ordered[i]][0]))
    return ordered[start:] + ordered[:start]


def detect_gppss_figure43_four_cycles(graph_or_path: Dict[str, Any] | str | Path) -> List[Dict[str, Any]]:
    """Return exact JSON-level matches for GPPSS Figure 43 left-hand sides.

    The side order in each match is ``top, right, bottom, left`` after ordering
    the four vertices geometrically around their centroid.  A match is reported
    only when the four sides are present as ordinary edges or hourglass pairs
    and the vertex colors match one of the translated Figure 43 cases.
    """
    if not isinstance(graph_or_path, dict):
        with Path(graph_or_path).open("r", encoding="utf-8") as handle:
            graph = json.load(handle)
    else:
        graph = graph_or_path

    nodes, colors, xy = _node_maps(graph)
    ordinary = _ordinary_pairs(graph)
    hourglass = _hourglass_pairs(graph)
    usable_pairs = ordinary | hourglass
    combined_adj: Dict[int, Set[int]] = {node_id: set() for node_id in nodes}
    for u, v in usable_pairs:
        combined_adj.setdefault(u, set()).add(v)
        combined_adj.setdefault(v, set()).add(u)
    matches: List[Dict[str, Any]] = []
    seen: Set[Tuple[int, int, int, int, str]] = set()

    candidate_quads: Set[Tuple[int, int, int, int]] = set()
    for a in combined_adj:
        for b in combined_adj[a]:
            for c in combined_adj.get(b, set()):
                if c in {a, b}:
                    continue
                for d in combined_adj.get(c, set()):
                    if d in {a, b, c}:
                        continue
                    if a not in combined_adj.get(d, set()):
                        continue
                    candidate_quads.add(tuple(sorted((a, b, c, d))))

    for quad in candidate_quads:
        ordered = _ordered_cycle_vertices(quad, xy)
        sides = [
            _pair(ordered[0], ordered[1]),
            _pair(ordered[1], ordered[2]),
            _pair(ordered[2], ordered[3]),
            _pair(ordered[3], ordered[0]),
        ]
        if not all(side in usable_pairs for side in sides):
            continue
        # Exclude diagonals from being sides of the same local square.  If a
        # diagonal is present, this is not one of the clean four-cycle pictures.
        if _pair(ordered[0], ordered[2]) in usable_pairs or _pair(ordered[1], ordered[3]) in usable_pairs:
            continue
        side_types = tuple(_side_type(side, ordinary, hourglass) or "" for side in sides)
        color_pattern = tuple(colors.get(v, "") for v in ordered)
        rule = FIGURE43_CASES.get((side_types, color_pattern))
        if rule is None:
            continue
        key = tuple(ordered) + (rule["name"],)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            {
                "rule": rule["name"],
                "source": rule["source"],
                "vertices_top_right_bottom_left": ordered,
                "side_types_top_right_bottom_left": list(side_types),
                "colors_top_right_bottom_left": list(color_pattern),
                "requires_tags": bool(rule.get("requires_tags", False)),
                "relation": rule["relation"],
            }
        )
    return matches


def lemma49_rule_catalog() -> List[Dict[str, Any]]:
    """Return the manually translated BCGMMW Lemma 4.9 exemplar snippets."""
    return load_lemma49_exemplars()["items"]


def load_lemma49_exemplars(path: str | Path = LEMMA49_EXEMPLAR_PATH) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_sl4_lemma49_zero_patterns(
    pattern_dir: str | Path = SL4_LEMMA49_ZERO_PATTERN_DIR,
) -> Dict[str, Any]:
    """Load the user-supplied SL4 analogue patterns as zero-discharge rules.

    These are paired embedded local patterns: a match requires both the W and
    X windows from the same catalogue entry.  The manifest records which
    cyclic shifts, reflections, and W/X swaps are allowed.
    """
    root = Path(pattern_dir)
    with (root / "manifest.json").open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    patterns = []
    for entry in manifest.get("patterns", []):
        with (root / entry["file"]).open("r", encoding="utf-8") as handle:
            pattern = json.load(handle)
        conclusion = pattern.get("conclusion", {})
        if conclusion.get("action") != "discharge_pair" or conclusion.get("pairing_value") != 0:
            raise ValueError(f"{entry['file']} is not an SL4 zero-discharge pattern")
        patterns.append(pattern)
    return {"manifest": manifest, "patterns": patterns}


def sl4_lemma49_zero_rule_catalog() -> List[Dict[str, Any]]:
    """Return the seven paired SL4 Lemma 4.9 analogue rules."""
    return load_sl4_lemma49_zero_patterns()["patterns"]


def _edge_endpoints(edge: Dict[str, Any]) -> Tuple[Any, Any]:
    if "src" in edge and "dst" in edge:
        return edge["src"], edge["dst"]
    return edge["u"], edge["v"]


def _actual_graph_parts(graph: Dict[str, Any]) -> Dict[str, Any]:
    nodes = {int(node["id"]): node for node in graph.get("nodes", [])}
    colors = {node_id: str(node.get("color", "")) for node_id, node in nodes.items()}
    boundary_by_label = {
        int(item["label"]): int(item["node"])
        for item in graph.get("boundary", [])
    }
    boundary_nodes = set(boundary_by_label.values())
    ordinary: Set[Pair] = set()
    ordinary_adj: Dict[int, Set[int]] = {node_id: set() for node_id in nodes}
    for edge in graph.get("edges", []):
        u_raw, v_raw = _edge_endpoints(edge)
        u, v = int(u_raw), int(v_raw)
        if edge.get("double") or edge.get("kind") == "hourglass":
            continue
        ordinary.add(_pair(u, v))
        ordinary_adj.setdefault(u, set()).add(v)
        ordinary_adj.setdefault(v, set()).add(u)
    hourglass = {
        _pair(item["white"], item["black"])
        for item in graph.get("hourglasses", [])
    }
    hourglass_adj: Dict[int, Set[int]] = {node_id: set() for node_id in nodes}
    for u, v in hourglass:
        hourglass_adj.setdefault(u, set()).add(v)
        hourglass_adj.setdefault(v, set()).add(u)
    return {
        "nodes": nodes,
        "colors": colors,
        "boundary_by_label": boundary_by_label,
        "boundary_nodes": boundary_nodes,
        "ordinary": ordinary,
        "ordinary_adj": ordinary_adj,
        "hourglass": hourglass,
        "hourglass_adj": hourglass_adj,
    }


def _pattern_web_parts(pattern_web: Dict[str, Any]) -> Dict[str, Any]:
    nodes = {str(node["id"]): node for node in pattern_web.get("nodes", [])}
    ports = {str(port) for port in pattern_web.get("ports", [])}
    nonports = [node_id for node_id in nodes if node_id not in ports]
    boundary = [str(node_id) for node_id in pattern_web.get("boundary_order", [])]
    internal = [
        node_id
        for node_id in nonports
        if nodes[node_id].get("role") == "internal"
    ]
    ordinary: Set[Tuple[str, str]] = set()
    hourglass: Set[Tuple[str, str]] = set()
    port_counts = {node_id: 0 for node_id in nonports}
    for edge in pattern_web.get("edges", []):
        u, v = str(edge["u"]), str(edge["v"])
        if u in ports or v in ports:
            local = v if u in ports else u
            if local in port_counts:
                port_counts[local] += 1
            continue
        key = tuple(sorted((u, v)))
        if edge.get("kind") == "hourglass":
            hourglass.add(key)
        else:
            ordinary.add(key)
    return {
        "nodes": nodes,
        "ports": ports,
        "nonports": nonports,
        "boundary": boundary,
        "internal": internal,
        "ordinary": ordinary,
        "hourglass": hourglass,
        "port_counts": port_counts,
    }


def _cyclic_interval(start: int, size: int, boundary_count: int, reflected: bool) -> List[int]:
    step = -1 if reflected else 1
    return [((start - 1 + step * offset) % boundary_count) + 1 for offset in range(size)]


def _pattern_relation(parts: Dict[str, Any], u: str, v: str) -> Optional[str]:
    key = tuple(sorted((str(u), str(v))))
    if key in parts["hourglass"]:
        return "hourglass"
    if key in parts["ordinary"]:
        return "ordinary"
    return None


def _actual_relation(parts: Dict[str, Any], u: int, v: int) -> Optional[str]:
    key = _pair(u, v)
    if key in parts["hourglass"]:
        return "hourglass"
    if key in parts["ordinary"]:
        return "ordinary"
    return None


def _match_pattern_side(
    graph_parts: Dict[str, Any],
    pattern_web: Dict[str, Any],
    boundary_labels: List[int],
    *,
    max_matches: int = 1,
) -> List[Dict[str, Any]]:
    parts = _pattern_web_parts(pattern_web)
    if len(parts["boundary"]) != len(boundary_labels):
        return []
    if any(label not in graph_parts["boundary_by_label"] for label in boundary_labels):
        return []

    mapping: Dict[str, int] = {
        pnode: graph_parts["boundary_by_label"][label]
        for pnode, label in zip(parts["boundary"], boundary_labels)
    }

    internal_candidates: Dict[str, List[int]] = {}
    mapped_boundary_nodes = set(mapping.values())
    for pnode in parts["internal"]:
        wanted_color = str(parts["nodes"][pnode].get("color", ""))
        candidates = [
            node_id
            for node_id, color in graph_parts["colors"].items()
            if color == wanted_color
            and node_id not in graph_parts["boundary_nodes"]
            and node_id not in mapped_boundary_nodes
        ]
        for qnode, actual in mapping.items():
            relation = _pattern_relation(parts, pnode, qnode)
            if relation == "ordinary":
                candidates = [node for node in candidates if _pair(node, actual) in graph_parts["ordinary"]]
            elif relation == "hourglass":
                candidates = [node for node in candidates if _pair(node, actual) in graph_parts["hourglass"]]
        internal_candidates[pnode] = candidates
        if not candidates:
            return []

    ordered_internal = sorted(parts["internal"], key=lambda node: len(internal_candidates[node]))
    matches: List[Dict[str, Any]] = []

    def relation_ok(pnode: str, actual: int, other_pnode: str, other_actual: int) -> bool:
        expected = _pattern_relation(parts, pnode, other_pnode)
        present = _actual_relation(graph_parts, actual, other_actual)
        if expected is not None:
            return present == expected
        return present is None

    def final_checks() -> bool:
        mapped_nonports = set(mapping.values())
        for pnode in parts["nonports"]:
            actual = mapping[pnode]
            local_ordinary = {
                mapping[other]
                for other in parts["nonports"]
                if other != pnode and _pattern_relation(parts, pnode, other) == "ordinary"
            }
            actual_local_ordinary = graph_parts["ordinary_adj"].get(actual, set()) & mapped_nonports
            if actual_local_ordinary != local_ordinary:
                return False
            local_hourglass = {
                mapping[other]
                for other in parts["nonports"]
                if other != pnode and _pattern_relation(parts, pnode, other) == "hourglass"
            }
            actual_local_hourglass = graph_parts["hourglass_adj"].get(actual, set()) & mapped_nonports
            if actual_local_hourglass != local_hourglass:
                return False
        return True

    def backtrack(index: int, used: Set[int]) -> None:
        if len(matches) >= max_matches:
            return
        if index == len(ordered_internal):
            if final_checks():
                ordinary_edges = [
                    _pair(mapping[u], mapping[v])
                    for u, v in parts["ordinary"]
                ]
                hourglass_edges = [
                    _pair(mapping[u], mapping[v])
                    for u, v in parts["hourglass"]
                ]
                matches.append(
                    {
                        "node_map": dict(mapping),
                        "boundary_labels": list(boundary_labels),
                        "ordinary_edges": sorted(set(ordinary_edges)),
                        "hourglass_edges": sorted(set(hourglass_edges)),
                    }
                )
            return

        pnode = ordered_internal[index]
        for actual in internal_candidates[pnode]:
            if actual in used:
                continue
            if any(
                not relation_ok(pnode, actual, other_pnode, other_actual)
                for other_pnode, other_actual in mapping.items()
            ):
                continue
            mapping[pnode] = actual
            used.add(actual)
            backtrack(index + 1, used)
            used.remove(actual)
            del mapping[pnode]

    backtrack(0, set(mapped_boundary_nodes))
    return matches


def detect_sl4_lemma49_zero_pair(
    w_graph: Dict[str, Any],
    x_graph: Dict[str, Any],
    *,
    max_matches: int = 1,
) -> List[Dict[str, Any]]:
    """Detect paired SL4 Lemma 4.9 zero patterns directly from graph JSON.

    This does not consult survivor TSV files.  It searches the actual W and X
    graph data for the paired local JSON snippets in
    ``sl4_lemma49_zero_patterns/``.  The drawn windows are interpreted as
    subgraph patterns: required internal edges and hourglasses must be present,
    but extra incident edges leaving the local window are allowed.
    """
    w_parts = _actual_graph_parts(w_graph)
    x_parts = _actual_graph_parts(x_graph)
    boundary_count = len(w_parts["boundary_by_label"])
    if boundary_count == 0 or boundary_count != len(x_parts["boundary_by_label"]):
        return []

    found: List[Dict[str, Any]] = []
    for pattern in sl4_lemma49_zero_rule_catalog():
        allow_reflection = bool(pattern.get("matching", {}).get("allow_reflection", False))
        allow_swap = bool(pattern.get("matching", {}).get("allow_pair_swap", False))
        orientations = [False] + ([True] if allow_reflection else [])
        assignments = [("W", "X", pattern["W"], pattern["X"])]
        if allow_swap:
            assignments.append(("X", "W", pattern["W"], pattern["X"]))
        window_size = len(pattern["W"].get("boundary_order", []))
        if window_size != len(pattern["X"].get("boundary_order", [])):
            continue

        for reflected in orientations:
            for start in range(1, boundary_count + 1):
                labels = _cyclic_interval(start, window_size, boundary_count, reflected)
                for pattern_w_side, pattern_x_side, pattern_w, pattern_x in assignments:
                    actual_w_parts = w_parts if pattern_w_side == "W" else x_parts
                    actual_x_parts = x_parts if pattern_x_side == "X" else w_parts
                    w_matches = _match_pattern_side(actual_w_parts, pattern_w, labels, max_matches=1)
                    if not w_matches:
                        continue
                    x_matches = _match_pattern_side(actual_x_parts, pattern_x, labels, max_matches=1)
                    if not x_matches:
                        continue
                    found.append(
                        {
                            "rule_id": pattern["id"],
                            "reason": pattern.get("conclusion", {}).get("reason", pattern["id"]),
                            "source": pattern.get("source", {}),
                            "boundary_labels": labels,
                            "reflected": reflected,
                            "pair_swapped": pattern_w_side != "W",
                            "W": w_matches[0] if pattern_w_side == "W" else x_matches[0],
                            "X": x_matches[0] if pattern_x_side == "X" else w_matches[0],
                        }
                    )
                    if len(found) >= max_matches:
                        return found
    return found
