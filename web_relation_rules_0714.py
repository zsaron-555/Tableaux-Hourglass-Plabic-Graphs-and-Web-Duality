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
