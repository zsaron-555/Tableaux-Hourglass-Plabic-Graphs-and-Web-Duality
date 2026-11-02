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
import os
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Set, Tuple


Pair = Tuple[int, int]
APP_DIR = Path(__file__).resolve().parent


def _asset_roots() -> List[Path]:
    """Return likely locations for relation-rule assets, in priority order."""
    roots = [
        Path(os.environ.get("PROBLEM3_APP_DIR", APP_DIR)).expanduser(),
        APP_DIR,
        Path.cwd(),
        Path(os.environ.get("PROBLEM3_ROOT", APP_DIR)).expanduser(),
        APP_DIR.parent,
        Path.cwd().parent,
        Path.home() / "Desktop" / "Problem 3",
        Path.home() / "Documents" / "Problem 3",
        Path.home() / "Downloads" / "Problem 3",
    ]
    unique: List[Path] = []
    seen: Set[Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _find_asset(name: str, *, directory: bool) -> Path:
    """Locate a bundled relation asset without tying it to the graph-data root."""
    attempted: List[Path] = []
    for root in _asset_roots():
        candidate = root / name
        attempted.append(candidate)
        exists = candidate.is_dir() if directory else candidate.is_file()
        if exists:
            if not directory or (candidate / "manifest.json").is_file():
                return candidate

    expected = "directory containing manifest.json" if directory else "file"
    searched = "\n  - ".join(str(path) for path in attempted)
    raise FileNotFoundError(
        f"Could not find relation-rule asset {name!r} ({expected}). "
        f"Set PROBLEM3_APP_DIR to the folder containing the website code and "
        f"relation assets. Searched:\n  - {searched}"
    )


LEMMA49_EXEMPLAR_PATH = _find_asset("bcgmmw_lemma49_exemplars_0714.json", directory=False)
SL4_LEMMA49_ZERO_PATTERN_DIR = _find_asset("sl4_lemma49_zero_patterns", directory=True)
SL4_LEMMA48_ZERO_PATTERN_DIR = _find_asset("sl4_lemma48_zero_patterns", directory=True)


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


@lru_cache(maxsize=8)
def load_lemma49_exemplars(path: str | Path = LEMMA49_EXEMPLAR_PATH) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=8)
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
    manifest_matching = manifest.get("matching_convention", {})
    matching_defaults = {
        "same_boundary_interval": bool(manifest_matching.get("same_cyclic_boundary_interval", True)),
        "allow_disk_rotation": bool(
            manifest_matching.get(
                "allow_disk_rotation",
                manifest_matching.get("allow_cyclic_shift_of_disk_labels", True),
            )
        ),
        "allow_reflection": bool(manifest_matching.get("allow_reflection", True)),
        "allow_pair_swap": bool(manifest_matching.get("allow_swap_W_X", False)),
        "crossings_are_not_vertices": bool(manifest_matching.get("crossings_are_not_vertices", True)),
    }

    patterns = []
    for entry in manifest.get("patterns", []):
        with (root / entry["file"]).open("r", encoding="utf-8") as handle:
            pattern = json.load(handle)
        conclusion = pattern.get("conclusion", {})
        if conclusion.get("action") != "discharge_pair" or conclusion.get("pairing_value") != 0:
            raise ValueError(f"{entry['file']} is not an SL4 zero-discharge pattern")
        pattern["matching"] = {**matching_defaults, **pattern.get("matching", {})}
        patterns.append(pattern)
    return {"manifest": manifest, "patterns": patterns}


def sl4_lemma49_zero_rule_catalog() -> List[Dict[str, Any]]:
    """Return the paired SL4 Lemma 4.9 analogue and generalized zero rules."""
    return load_sl4_lemma49_zero_patterns()["patterns"]


@lru_cache(maxsize=8)
def load_sl4_lemma48_zero_patterns(
    pattern_dir: str | Path = SL4_LEMMA48_ZERO_PATTERN_DIR,
) -> Dict[str, Any]:
    """Load metadata for the GL4 specialization of the Lemma 4.8 zero rule.

    The corrected rule has an exact five-boundary local model.  Its JSON file
    records the required W/X incidences and orientation orbit, while matching
    is carried out programmatically by
    :func:`detect_sl4_lemma48_zero_pair`.
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
            raise ValueError(f"{entry['file']} is not an SL4 Lemma 4.8 zero-discharge pattern")
        patterns.append(pattern)
    return {"manifest": manifest, "patterns": patterns}


def sl4_lemma48_zero_rule_catalog() -> List[Dict[str, Any]]:
    """Return the GL4 Lemma 4.8 analogue zero-rule metadata."""
    return load_sl4_lemma48_zero_patterns()["patterns"]


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


def actual_graph_parts_from_native(
    adj: Mapping[int, Any],
    boundary_labels: Mapping[int, int],
    hourglasses: Iterable[Mapping[str, Any]],
    node_colors: Mapping[int, str],
) -> Dict[str, Any]:
    """Build matcher input directly from an evaluator term.

    The legacy matcher first serialized this information to graph JSON and
    parsed it immediately afterwards.  This native adapter preserves the same
    ordinary-edge and hourglass sets without allocating that intermediate
    representation.
    """
    node_ids: Set[int] = {int(node) for node in adj}
    ordinary: Set[Pair] = set()
    for u_raw, neighbors in adj.items():
        u = int(u_raw)
        if isinstance(neighbors, MutableMapping):
            iterable = [value for value in neighbors.values() if value is not None]
        else:
            iterable = [value for value in neighbors if value is not None]
        for v_raw in iterable:
            v = int(v_raw)
            node_ids.add(v)
            ordinary.add(_pair(u, v))

    hourglass: Set[Pair] = set()
    for item in hourglasses:
        white = int(item["white"])
        black = int(item["black"])
        if white in node_ids and black in node_ids:
            hourglass.add(_pair(white, black))

    boundary_by_label = {
        int(label): int(node)
        for node, label in boundary_labels.items()
        if int(node) in node_ids
    }
    boundary_nodes = set(boundary_by_label.values())
    colors = {
        node: str(node_colors.get(node, "black" if node in boundary_nodes else ""))
        for node in node_ids
    }
    ordinary_adj: Dict[int, Set[int]] = {node: set() for node in node_ids}
    for u, v in ordinary:
        ordinary_adj[u].add(v)
        ordinary_adj[v].add(u)
    hourglass_adj: Dict[int, Set[int]] = {node: set() for node in node_ids}
    for u, v in hourglass:
        hourglass_adj[u].add(v)
        hourglass_adj[v].add(u)

    internal_by_color: Dict[str, Set[int]] = {}
    for node, color in colors.items():
        if node not in boundary_nodes:
            internal_by_color.setdefault(color, set()).add(node)

    return {
        "nodes": {node: {"id": node, "color": colors[node]} for node in node_ids},
        "colors": colors,
        "boundary_by_label": boundary_by_label,
        "boundary_nodes": boundary_nodes,
        "ordinary": ordinary,
        "ordinary_adj": ordinary_adj,
        "hourglass": hourglass,
        "hourglass_adj": hourglass_adj,
        "internal_by_color": internal_by_color,
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
    allowed_relations: Dict[Tuple[str, str], Set[str]] = {}
    edge_pairs_by_id: Dict[str, Tuple[str, str]] = {}
    port_counts = {node_id: 0 for node_id in nonports}
    for edge in pattern_web.get("edges", []):
        u, v = str(edge["u"]), str(edge["v"])
        if u in ports or v in ports:
            local = v if u in ports else u
            if local in port_counts:
                port_counts[local] += 1
            continue
        key = tuple(sorted((u, v)))
        edge_pairs_by_id[str(edge["id"])] = key
        kind = str(edge.get("kind", "ordinary"))
        if kind == "ordinary_or_hourglass":
            allowed_relations[key] = {"ordinary", "hourglass"}
        elif kind == "hourglass":
            hourglass.add(key)
            allowed_relations[key] = {"hourglass"}
        else:
            ordinary.add(key)
            allowed_relations[key] = {"ordinary"}
    return {
        "nodes": nodes,
        "ports": ports,
        "nonports": nonports,
        "boundary": boundary,
        "internal": internal,
        "ordinary": ordinary,
        "hourglass": hourglass,
        "allowed_relations": allowed_relations,
        "edge_pairs_by_id": edge_pairs_by_id,
        "constraints": list(pattern_web.get("constraints", [])),
        "port_counts": port_counts,
    }


def _paired_pattern_required_graph_connected(pattern: Dict[str, Any]) -> bool:
    """Return whether the required paired configuration is connected.

    Connectivity is tested after the W and X boundary vertices in the same
    positions of the local boundary window are identified.  External ports
    and all ambient incidences not drawn in the pattern are irrelevant.
    """
    w_parts = _pattern_web_parts(pattern["W"])
    x_parts = _pattern_web_parts(pattern["X"])
    if len(w_parts["boundary"]) != len(x_parts["boundary"]):
        return False

    adjacency: Dict[Tuple[str, Any], Set[Tuple[str, Any]]] = {}

    def add_side(side: str, parts: Dict[str, Any]) -> None:
        boundary_positions = {
            node_id: position
            for position, node_id in enumerate(parts["boundary"])
        }

        def merged_node(node_id: str) -> Tuple[str, Any]:
            if node_id in boundary_positions:
                return ("boundary", boundary_positions[node_id])
            return (side, node_id)

        for node_id in parts["nonports"]:
            adjacency.setdefault(merged_node(node_id), set())
        for u, v in parts["allowed_relations"]:
            merged_u = merged_node(u)
            merged_v = merged_node(v)
            adjacency.setdefault(merged_u, set()).add(merged_v)
            adjacency.setdefault(merged_v, set()).add(merged_u)

    add_side("W", w_parts)
    add_side("X", x_parts)
    if not adjacency:
        return False

    start = next(iter(adjacency))
    reached = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for neighbor in adjacency[node]:
            if neighbor not in reached:
                reached.add(neighbor)
                stack.append(neighbor)
    return len(reached) == len(adjacency)


def _cyclic_interval(start: int, size: int, boundary_count: int, reflected: bool) -> List[int]:
    step = -1 if reflected else 1
    return [((start - 1 + step * offset) % boundary_count) + 1 for offset in range(size)]


def _boundary_windows(
    boundary_count: int,
    window_size: int,
    *,
    allow_reflection: bool,
    allow_disk_rotation: bool = True,
) -> Iterable[Tuple[List[int], bool, int, bool]]:
    """Enumerate local boundary windows anywhere on the disk.

    The JSON pattern files are drawn in a fixed "bottom window" convention, but
    mathematically the forbidden configurations may appear after rotating the
    whole disk.  A disk rotation is implemented by moving the first boundary
    label of the local window through all labels 1, ..., n.  Reflection is the
    independent reversal of the cyclic boundary order.

    Yields ``(labels, reflected, start, disk_rotated)``.  ``start == 1`` and
    ``reflected is False`` is the original bottom-window placement; every other
    yield is a rotated and/or reflected copy of the same local pattern.
    """
    if window_size <= 0 or boundary_count <= 0 or window_size > boundary_count:
        return
    orientations = [False] + ([True] if allow_reflection else [])
    starts = range(1, boundary_count + 1) if allow_disk_rotation else range(1, 2)
    for reflected in orientations:
        for start in starts:
            labels = _cyclic_interval(start, window_size, boundary_count, reflected)
            yield labels, reflected, start, (start != 1 or reflected)


def _pattern_boundary_windows(
    pattern: Dict[str, Any],
    boundary_count: int,
) -> Iterable[Tuple[List[int], bool, int, bool]]:
    """Enumerate fixed or shared variable-span boundary placements.

    ``boundary_offsets`` lets a paired pattern retain a variable cyclic gap.
    Offsets are zero-based within a span; negative offsets count backward from
    the span's end.  The same resolved labels are used on W and X, which is the
    "both gaps have the same size" condition in Additional Zero Pairings.
    """
    matching = pattern.get("matching", {})
    allow_reflection = bool(matching.get("allow_reflection", False))
    allow_disk_rotation = bool(matching.get("allow_disk_rotation", True))
    offsets = matching.get("boundary_offsets")
    if offsets is None:
        yield from _boundary_windows(
            boundary_count,
            len(pattern["W"].get("boundary_order", [])),
            allow_reflection=allow_reflection,
            allow_disk_rotation=allow_disk_rotation,
        )
        return

    offsets = [int(offset) for offset in offsets]
    expected = len(pattern["W"].get("boundary_order", []))
    if len(offsets) != expected:
        return
    minimum_span = max(
        int(matching.get("minimum_boundary_span", expected)),
        1 + max((offset for offset in offsets if offset >= 0), default=-1),
        max((-offset for offset in offsets if offset < 0), default=0),
    )
    maximum_span = min(
        int(matching.get("maximum_boundary_span", boundary_count)),
        boundary_count,
    )
    orientations = [False] + ([True] if allow_reflection else [])
    starts = range(1, boundary_count + 1) if allow_disk_rotation else range(1, 2)
    seen: Set[Tuple[int, ...]] = set()
    for span in range(minimum_span, maximum_span + 1):
        resolved_offsets = [
            offset if offset >= 0 else span + offset
            for offset in offsets
        ]
        if len(set(resolved_offsets)) != len(resolved_offsets):
            continue
        if any(offset < 0 or offset >= span for offset in resolved_offsets):
            continue
        for reflected in orientations:
            step = -1 if reflected else 1
            for start in starts:
                labels = [
                    ((start - 1 + step * offset) % boundary_count) + 1
                    for offset in resolved_offsets
                ]
                key = tuple(labels)
                if key in seen:
                    continue
                seen.add(key)
                yield labels, reflected, start, (start != 1 or reflected)


def _pattern_relation(parts: Dict[str, Any], u: str, v: str) -> Optional[str]:
    key = tuple(sorted((str(u), str(v))))
    if key in parts["hourglass"]:
        return "hourglass"
    if key in parts["ordinary"]:
        return "ordinary"
    return None


def _pattern_allowed_relations(
    parts: Dict[str, Any],
    u: str,
    v: str,
) -> Set[str]:
    return set(parts["allowed_relations"].get(tuple(sorted((str(u), str(v)))), set()))


def _pattern_constraints_ok(
    parts: Dict[str, Any],
    mapping: Dict[str, int],
    graph_parts: Dict[str, Any],
) -> bool:
    for constraint in parts.get("constraints", []):
        if constraint.get("type") != "exact_edge_kind_count":
            continue
        wanted_kind = str(constraint["kind"])
        wanted_count = int(constraint["count"])
        actual_count = 0
        for edge_id in constraint.get("edge_ids", []):
            pair = parts["edge_pairs_by_id"].get(str(edge_id))
            if pair is None:
                return False
            u, v = pair
            if _actual_relation(graph_parts, mapping[u], mapping[v]) == wanted_kind:
                actual_count += 1
        if actual_count != wanted_count:
            return False
    return True


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
            allowed = _pattern_allowed_relations(parts, pnode, qnode)
            if allowed:
                candidates = [
                    node
                    for node in candidates
                    if _actual_relation(graph_parts, node, actual) in allowed
                ]
        internal_candidates[pnode] = candidates
        if not candidates:
            return []

    ordered_internal = sorted(parts["internal"], key=lambda node: len(internal_candidates[node]))
    matches: List[Dict[str, Any]] = []

    def relation_ok(pnode: str, actual: int, other_pnode: str, other_actual: int) -> bool:
        expected = _pattern_allowed_relations(parts, pnode, other_pnode)
        if not expected:
            # Lemma 4.9 asks for the displayed orange graph as a subgraph, not
            # as an induced subgraph. Additional edges between mapped vertices
            # therefore do not invalidate an otherwise valid match.
            return True
        return _actual_relation(graph_parts, actual, other_actual) in expected

    def final_checks() -> bool:
        # Do not inspect incidences outside the displayed orange subgraph.
        # Required edge kinds and colors were checked during backtracking.
        return _pattern_constraints_ok(parts, mapping, graph_parts)

    def backtrack(index: int, used: Set[int]) -> None:
        if len(matches) >= max_matches:
            return
        if index == len(ordered_internal):
            if final_checks():
                ordinary_edges = [
                    _pair(mapping[u], mapping[v])
                    for u, v in parts["allowed_relations"]
                    if _actual_relation(graph_parts, mapping[u], mapping[v]) == "ordinary"
                ]
                hourglass_edges = [
                    _pair(mapping[u], mapping[v])
                    for u, v in parts["allowed_relations"]
                    if _actual_relation(graph_parts, mapping[u], mapping[v]) == "hourglass"
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


def _ensure_graph_indexes(graph_parts: Dict[str, Any]) -> None:
    if "internal_by_color" in graph_parts:
        return
    boundary_nodes = graph_parts["boundary_nodes"]
    internal_by_color: Dict[str, Set[int]] = {}
    for node, color in graph_parts["colors"].items():
        if node not in boundary_nodes:
            internal_by_color.setdefault(str(color), set()).add(int(node))
    graph_parts["internal_by_color"] = internal_by_color


@dataclass(frozen=True)
class CompiledPatternSide:
    parts: Dict[str, Any]
    internal_color_counts: Tuple[Tuple[str, int], ...]


@dataclass(frozen=True)
class Lemma49ViableSlot:
    pattern: Dict[str, Any]
    boundary_labels: Tuple[int, ...]
    reflected: bool
    start: int
    disk_rotated: bool
    pair_swapped: bool
    fixed_w_match: Dict[str, Any]
    x_pattern: CompiledPatternSide


@dataclass
class Lemma49MatcherStats:
    compile_seconds: float = 0.0
    fixed_w_exact_checks: int = 0
    viable_slots: int = 0
    x_calls: int = 0
    x_cache_hits: int = 0
    x_slots_considered: int = 0
    x_fingerprint_rejects: int = 0
    x_exact_checks: int = 0
    x_exact_matches: int = 0
    x_seconds: float = 0.0


@lru_cache(maxsize=1)
def compiled_sl4_lemma49_pattern_catalog() -> Tuple[Dict[str, Any], ...]:
    """Parse and index the immutable pattern sides once per process."""
    compiled: List[Dict[str, Any]] = []
    for pattern in sl4_lemma49_zero_rule_catalog():
        if not _paired_pattern_required_graph_connected(pattern):
            continue
        item = dict(pattern)
        item["_compiled_W"] = _compile_pattern_side(pattern["W"])
        item["_compiled_X"] = _compile_pattern_side(pattern["X"])
        compiled.append(item)
    return tuple(compiled)


def _compile_pattern_side(pattern_web: Dict[str, Any]) -> CompiledPatternSide:
    parts = _pattern_web_parts(pattern_web)
    counts = Counter(
        str(parts["nodes"][node].get("color", ""))
        for node in parts["internal"]
    )
    return CompiledPatternSide(
        parts=parts,
        internal_color_counts=tuple(sorted(counts.items())),
    )


def _graph_parts_key(graph_parts: Dict[str, Any]) -> Tuple[Any, ...]:
    """ID-sensitive exact key for side-match memoization."""
    return (
        tuple(sorted(graph_parts["boundary_by_label"].items())),
        tuple(sorted(graph_parts["colors"].items())),
        tuple(sorted(graph_parts["ordinary"])),
        tuple(sorted(graph_parts["hourglass"])),
    )


def _compiled_side_prefilter(
    graph_parts: Dict[str, Any],
    compiled: CompiledPatternSide,
    boundary_labels: Tuple[int, ...],
) -> bool:
    """Cheap necessary conditions only; this function never certifies a match."""
    parts = compiled.parts
    if len(parts["boundary"]) != len(boundary_labels):
        return False
    if any(label not in graph_parts["boundary_by_label"] for label in boundary_labels):
        return False
    _ensure_graph_indexes(graph_parts)
    for color, count in compiled.internal_color_counts:
        if len(graph_parts["internal_by_color"].get(color, set())) < count:
            return False

    boundary_mapping = {
        pnode: graph_parts["boundary_by_label"][label]
        for pnode, label in zip(parts["boundary"], boundary_labels)
    }
    for pnode in parts["internal"]:
        color = str(parts["nodes"][pnode].get("color", ""))
        candidates = set(graph_parts["internal_by_color"].get(color, set()))
        for qnode, actual in boundary_mapping.items():
            allowed = _pattern_allowed_relations(parts, pnode, qnode)
            if allowed:
                permitted = set()
                if "ordinary" in allowed:
                    permitted |= graph_parts["ordinary_adj"].get(actual, set())
                if "hourglass" in allowed:
                    permitted |= graph_parts["hourglass_adj"].get(actual, set())
                candidates &= permitted
            if not candidates:
                return False
    return True


def _match_compiled_pattern_side(
    graph_parts: Dict[str, Any],
    compiled: CompiledPatternSide,
    boundary_labels: Tuple[int, ...],
    *,
    max_matches: int = 1,
) -> List[Dict[str, Any]]:
    """Indexed equivalent of :func:`_match_pattern_side`."""
    parts = compiled.parts
    if not _compiled_side_prefilter(graph_parts, compiled, boundary_labels):
        return []

    mapping: Dict[str, int] = {
        pnode: graph_parts["boundary_by_label"][label]
        for pnode, label in zip(parts["boundary"], boundary_labels)
    }
    mapped_boundary_nodes = set(mapping.values())
    internal_candidates: Dict[str, List[int]] = {}
    for pnode in parts["internal"]:
        wanted_color = str(parts["nodes"][pnode].get("color", ""))
        candidates = set(graph_parts["internal_by_color"].get(wanted_color, set()))
        candidates -= mapped_boundary_nodes
        for qnode, actual in mapping.items():
            allowed = _pattern_allowed_relations(parts, pnode, qnode)
            if allowed:
                permitted = set()
                if "ordinary" in allowed:
                    permitted |= graph_parts["ordinary_adj"].get(actual, set())
                if "hourglass" in allowed:
                    permitted |= graph_parts["hourglass_adj"].get(actual, set())
                candidates &= permitted
        if not candidates:
            return []
        internal_candidates[pnode] = sorted(candidates)

    ordered_internal = sorted(
        parts["internal"],
        key=lambda node: (len(internal_candidates[node]), node),
    )
    matches: List[Dict[str, Any]] = []

    def relation_ok(
        pnode: str,
        actual: int,
        other_pnode: str,
        other_actual: int,
    ) -> bool:
        expected = _pattern_allowed_relations(parts, pnode, other_pnode)
        if not expected:
            # Match a possibly non-induced subgraph: extra relations among
            # mapped vertices are allowed.
            return True
        return _actual_relation(graph_parts, actual, other_actual) in expected

    def final_checks() -> bool:
        # Outside ordinary edges and hourglasses are irrelevant. The orange
        # configuration need only occur as a subgraph.
        return _pattern_constraints_ok(parts, mapping, graph_parts)

    def backtrack(index: int, used: Set[int]) -> None:
        if len(matches) >= max_matches:
            return
        if index == len(ordered_internal):
            if final_checks():
                matches.append(
                    {
                        "node_map": dict(mapping),
                        "boundary_labels": list(boundary_labels),
                        "ordinary_edges": sorted(
                            {
                                _pair(mapping[u], mapping[v])
                                for u, v in parts["allowed_relations"]
                                if _actual_relation(
                                    graph_parts, mapping[u], mapping[v]
                                ) == "ordinary"
                            }
                        ),
                        "hourglass_edges": sorted(
                            {
                                _pair(mapping[u], mapping[v])
                                for u, v in parts["allowed_relations"]
                                if _actual_relation(
                                    graph_parts, mapping[u], mapping[v]
                                ) == "hourglass"
                            }
                        ),
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


class CompiledLemma49Matcher:
    """Fixed-W Lemma 4.9 matcher with indexed, memoized X-side checks."""

    def __init__(
        self,
        w_parts: Dict[str, Any],
        *,
        cache_size: int = 100_000,
    ) -> None:
        started = time.perf_counter()
        self.w_parts = w_parts
        _ensure_graph_indexes(self.w_parts)
        self.stats = Lemma49MatcherStats()
        self.cache_size = max(1, int(cache_size))
        self.x_cache: OrderedDict[Tuple[Any, ...], Optional[Dict[str, Any]]] = (
            OrderedDict()
        )
        self.slots: List[Lemma49ViableSlot] = []
        boundary_count = len(w_parts["boundary_by_label"])

        for pattern in compiled_sl4_lemma49_pattern_catalog():
            matching = pattern.get("matching", {})
            allow_reflection = bool(matching.get("allow_reflection", False))
            allow_swap = bool(matching.get("allow_pair_swap", False))
            allow_disk_rotation = bool(matching.get("allow_disk_rotation", True))
            if len(pattern["W"].get("boundary_order", [])) != len(
                pattern["X"].get("boundary_order", [])
            ):
                continue
            for labels_list, reflected, start, disk_rotated in _pattern_boundary_windows(
                pattern, boundary_count
            ):
                labels = tuple(labels_list)
                assignments = [
                    (
                        False,
                        pattern["_compiled_W"],
                        pattern["_compiled_X"],
                    )
                ]
                if allow_swap:
                    assignments.append(
                        (
                            True,
                            pattern["_compiled_X"],
                            pattern["_compiled_W"],
                        )
                    )
                for pair_swapped, w_pattern, x_pattern in assignments:
                    self.stats.fixed_w_exact_checks += 1
                    w_matches = _match_compiled_pattern_side(
                        self.w_parts,
                        w_pattern,
                        labels,
                        max_matches=1,
                    )
                    if not w_matches:
                        continue
                    self.slots.append(
                        Lemma49ViableSlot(
                            pattern=pattern,
                            boundary_labels=labels,
                            reflected=reflected,
                            start=start,
                            disk_rotated=disk_rotated,
                            pair_swapped=pair_swapped,
                            fixed_w_match=w_matches[0],
                            x_pattern=x_pattern,
                        )
                    )
        self.stats.viable_slots = len(self.slots)
        self.stats.compile_seconds = time.perf_counter() - started

    def match(
        self,
        x_parts: Dict[str, Any],
        *,
        x_key: Optional[Tuple[Any, ...]] = None,
    ) -> Optional[Dict[str, Any]]:
        started = time.perf_counter()
        self.stats.x_calls += 1
        _ensure_graph_indexes(x_parts)
        cache_key = x_key if x_key is not None else _graph_parts_key(x_parts)
        if cache_key in self.x_cache:
            self.stats.x_cache_hits += 1
            result = self.x_cache.pop(cache_key)
            self.x_cache[cache_key] = result
            self.stats.x_seconds += time.perf_counter() - started
            return result

        result: Optional[Dict[str, Any]] = None
        for slot in self.slots:
            self.stats.x_slots_considered += 1
            if not _compiled_side_prefilter(
                x_parts, slot.x_pattern, slot.boundary_labels
            ):
                self.stats.x_fingerprint_rejects += 1
                continue
            self.stats.x_exact_checks += 1
            x_matches = _match_compiled_pattern_side(
                x_parts,
                slot.x_pattern,
                slot.boundary_labels,
                max_matches=1,
            )
            if not x_matches:
                continue
            self.stats.x_exact_matches += 1
            pattern = slot.pattern
            result = {
                "rule_id": pattern["id"],
                "reason": pattern.get("conclusion", {}).get(
                    "reason", pattern["id"]
                ),
                "source": pattern.get("source", {}),
                "boundary_labels": list(slot.boundary_labels),
                "reflected": slot.reflected,
                "disk_rotation_start": slot.start,
                "disk_rotated": slot.disk_rotated,
                "pair_swapped": slot.pair_swapped,
                "W": slot.fixed_w_match,
                "X": x_matches[0],
            }
            break

        self.x_cache[cache_key] = result
        while len(self.x_cache) > self.cache_size:
            self.x_cache.popitem(last=False)
        self.stats.x_seconds += time.perf_counter() - started
        return result


def detect_sl4_lemma49_zero_pair(
    w_graph: Dict[str, Any],
    x_graph: Dict[str, Any],
    *,
    max_matches: int = 1,
) -> List[Dict[str, Any]]:
    """Detect paired SL4 Lemma 4.9 zero patterns directly from graph JSON.

    This does not consult survivor TSV files.  It searches the actual W and X
    graph data for the paired local JSON snippets in
    ``sl4_lemma49_zero_patterns/``. The drawn orange configuration is matched
    as a subgraph: its required colors, ordinary edges, hourglasses, boundary
    order, and explicit edge-kind constraints must be present. Any additional
    incidences outside that subgraph are unrestricted.  The required W/X
    configuration must be connected after corresponding boundary vertices are
    identified.
    """
    w_parts = _actual_graph_parts(w_graph)
    x_parts = _actual_graph_parts(x_graph)
    boundary_count = len(w_parts["boundary_by_label"])
    if boundary_count == 0 or boundary_count != len(x_parts["boundary_by_label"]):
        return []

    found: List[Dict[str, Any]] = []
    for pattern in sl4_lemma49_zero_rule_catalog():
        if not _paired_pattern_required_graph_connected(pattern):
            continue
        matching = pattern.get("matching", {})
        allow_reflection = bool(matching.get("allow_reflection", False))
        allow_swap = bool(matching.get("allow_pair_swap", False))
        allow_disk_rotation = bool(matching.get("allow_disk_rotation", True))
        assignments = [("W", "X", pattern["W"], pattern["X"])]
        if allow_swap:
            assignments.append(("X", "W", pattern["W"], pattern["X"]))
        if len(pattern["W"].get("boundary_order", [])) != len(
            pattern["X"].get("boundary_order", [])
        ):
            continue

        for labels, reflected, start, disk_rotated in _pattern_boundary_windows(
            pattern, boundary_count
        ):
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
                        "disk_rotation_start": start,
                        "disk_rotated": disk_rotated,
                        "pair_swapped": pattern_w_side != "W",
                        "W": w_matches[0] if pattern_w_side == "W" else x_matches[0],
                        "X": x_matches[0] if pattern_x_side == "X" else w_matches[0],
                    }
                )
                if len(found) >= max_matches:
                    return found
    return found


def _boundary_label_count(parts: Dict[str, Any]) -> int:
    return len(parts["boundary_by_label"])


def _same_colored_boundary_neighbor(
    parts: Dict[str, Any],
    labels: Iterable[int],
    color: str,
) -> Optional[int]:
    boundary_nodes = [parts["boundary_by_label"].get(int(label)) for label in labels]
    if any(node is None for node in boundary_nodes):
        return None
    common: Optional[Set[int]] = None
    for node in boundary_nodes:
        neighbors = {
            nbr
            for nbr in parts["ordinary_adj"].get(int(node), set())
            if nbr not in parts["boundary_nodes"] and parts["colors"].get(nbr) == color
        }
        common = set(neighbors) if common is None else common & neighbors
    if not common:
        return None
    return min(common)


def _combined_adj(parts: Dict[str, Any]) -> Dict[int, Set[int]]:
    adj = {node_id: set(neighbors) for node_id, neighbors in parts["ordinary_adj"].items()}
    for node_id, neighbors in parts["hourglass_adj"].items():
        adj.setdefault(node_id, set()).update(neighbors)
    return adj


def _shortest_path_edges(adj: Dict[int, Set[int]], start: int, goal: int) -> List[Pair]:
    if start == goal:
        return []
    queue = [start]
    parent: Dict[int, Optional[int]] = {start: None}
    for node in queue:
        for nbr in sorted(adj.get(node, set())):
            if nbr in parent:
                continue
            parent[nbr] = node
            if nbr == goal:
                path_edges: List[Pair] = []
                cur = goal
                while parent[cur] is not None:
                    prev = int(parent[cur])
                    path_edges.append(_pair(prev, cur))
                    cur = prev
                path_edges.reverse()
                return path_edges
            queue.append(nbr)
    return []


def detect_sl4_lemma48_zero_pair(
    w_graph: Dict[str, Any],
    x_graph: Dict[str, Any],
    *,
    max_matches: int = 1,
) -> List[Dict[str, Any]]:
    """Detect the corrected five-boundary GL4 Lemma 4.8 zero pattern.

    The local W and X incidences are matched exactly as drawn in
    ``IMG_5961.heic``.  Only incidences outside the displayed local subgraphs
    are unrestricted.  Every cyclic starting label and both cyclic
    orientations are tested, which realizes all disk rotations and
    reflections.
    """
    w_parts = _actual_graph_parts(w_graph)
    x_parts = _actual_graph_parts(x_graph)
    boundary_count = _boundary_label_count(w_parts)
    if boundary_count == 0 or boundary_count != _boundary_label_count(x_parts):
        return []

    def ordinary_white_neighbors(
        parts: Dict[str, Any],
        boundary_labels: Iterable[int],
    ) -> Set[int]:
        common: Optional[Set[int]] = None
        for label in boundary_labels:
            boundary_node = parts["boundary_by_label"].get(int(label))
            if boundary_node is None:
                return set()
            candidates = {
                nbr
                for nbr in parts["ordinary_adj"].get(boundary_node, set())
                if nbr not in parts["boundary_nodes"]
                and parts["colors"].get(nbr) == "white"
            }
            common = candidates if common is None else common & candidates
        return common or set()

    def w_local_matches(parts: Dict[str, Any], labels: List[int]) -> List[Dict[str, Any]]:
        v1, v2, v3, v4, v5 = labels
        boundary = parts["boundary_by_label"]
        matches: List[Dict[str, Any]] = []
        for w_left in sorted(ordinary_white_neighbors(parts, [v1])):
            for w_fan in sorted(ordinary_white_neighbors(parts, [v2, v3, v4])):
                for w_right in sorted(ordinary_white_neighbors(parts, [v5])):
                    if len({w_left, w_fan, w_right}) != 3:
                        continue
                    for b_hub, color in sorted(parts["colors"].items()):
                        if color != "black" or b_hub in parts["boundary_nodes"]:
                            continue
                        ordinary_required = {
                            _pair(w_left, boundary[v1]),
                            _pair(b_hub, w_left),
                            _pair(w_fan, boundary[v2]),
                            _pair(w_fan, boundary[v3]),
                            _pair(w_fan, boundary[v4]),
                            _pair(b_hub, w_fan),
                            _pair(w_right, boundary[v5]),
                        }
                        hourglass_required = {_pair(b_hub, w_right)}
                        if not ordinary_required <= parts["ordinary"]:
                            continue
                        if not hourglass_required <= parts["hourglass"]:
                            continue
                        matches.append(
                            {
                                "node_map": {
                                    "w_left": int(w_left),
                                    "w_fan": int(w_fan),
                                    "w_right": int(w_right),
                                    "b_hub": int(b_hub),
                                },
                                "boundary_labels": list(labels),
                                "ordinary_edges": sorted(ordinary_required),
                                "hourglass_edges": sorted(hourglass_required),
                            }
                        )
        return matches

    def x_local_matches(parts: Dict[str, Any], labels: List[int]) -> List[Dict[str, Any]]:
        v1, v2, v3, v4, v5 = labels
        boundary = parts["boundary_by_label"]
        matches: List[Dict[str, Any]] = []
        for xw1 in sorted(ordinary_white_neighbors(parts, [v1, v2])):
            for xw2 in sorted(ordinary_white_neighbors(parts, [v3])):
                for xw3 in sorted(ordinary_white_neighbors(parts, [v4, v5])):
                    if len({xw1, xw2, xw3}) != 3:
                        continue
                    for xb1, color1 in sorted(parts["colors"].items()):
                        if color1 != "black" or xb1 in parts["boundary_nodes"]:
                            continue
                        if _pair(xw1, xb1) not in parts["hourglass"]:
                            continue
                        if _pair(xb1, xw2) not in parts["ordinary"]:
                            continue
                        for xb2, color2 in sorted(parts["colors"].items()):
                            if (
                                color2 != "black"
                                or xb2 in parts["boundary_nodes"]
                                or xb2 == xb1
                            ):
                                continue
                            ordinary_required = {
                                _pair(xw1, boundary[v1]),
                                _pair(xw1, boundary[v2]),
                                _pair(xb1, xw2),
                                _pair(xw2, boundary[v3]),
                                _pair(xb2, xw3),
                                _pair(xw3, boundary[v4]),
                                _pair(xw3, boundary[v5]),
                            }
                            hourglass_required = {
                                _pair(xw1, xb1),
                                _pair(xw2, xb2),
                            }
                            if not ordinary_required <= parts["ordinary"]:
                                continue
                            if not hourglass_required <= parts["hourglass"]:
                                continue
                            matches.append(
                                {
                                    "node_map": {
                                        "xw1": int(xw1),
                                        "xb1": int(xb1),
                                        "xw2": int(xw2),
                                        "xb2": int(xb2),
                                        "xw3": int(xw3),
                                    },
                                    "boundary_labels": list(labels),
                                    "ordinary_edges": sorted(ordinary_required),
                                    "hourglass_edges": sorted(hourglass_required),
                                }
                            )
        return matches

    found: List[Dict[str, Any]] = []
    for pattern in sl4_lemma48_zero_rule_catalog():
        matching = pattern.get("matching", {})
        window_size = int(matching.get("boundary_window_size", 5))
        allow_reflection = bool(matching.get("allow_reflection", True))
        allow_swap = bool(matching.get("allow_pair_swap", False))
        allow_disk_rotation = bool(matching.get("allow_disk_rotation", True))
        assignments = [("W", "X")]
        if allow_swap:
            assignments.append(("X", "W"))

        for labels, reflected, start, disk_rotated in _boundary_windows(
            boundary_count,
            window_size,
            allow_reflection=allow_reflection,
            allow_disk_rotation=allow_disk_rotation,
        ):
            for w_side, x_side in assignments:
                actual_w_parts = w_parts if w_side == "W" else x_parts
                actual_x_parts = x_parts if x_side == "X" else w_parts
                if any(label not in actual_w_parts["boundary_by_label"] for label in labels):
                    continue
                if any(label not in actual_x_parts["boundary_by_label"] for label in labels):
                    continue
                w_candidates = w_local_matches(actual_w_parts, labels)
                if not w_candidates:
                    continue
                x_candidates = x_local_matches(actual_x_parts, labels)
                if not x_candidates:
                    continue
                for w_match in w_candidates:
                    for x_match in x_candidates:
                        found.append(
                            {
                                "rule_id": pattern["id"],
                                "reason": pattern.get("conclusion", {}).get(
                                    "reason", pattern["id"]
                                ),
                                "source": pattern.get("source", {}),
                                "boundary_labels": labels,
                                "reflected": reflected,
                                "disk_rotation_start": start,
                                "disk_rotated": disk_rotated,
                                "pair_swapped": w_side != "W",
                                "W": w_match if w_side == "W" else x_match,
                                "X": x_match if x_side == "X" else w_match,
                            }
                        )
                        if len(found) >= max_matches:
                            return found
    return found
