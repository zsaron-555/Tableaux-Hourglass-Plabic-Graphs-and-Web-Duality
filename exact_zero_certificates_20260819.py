"""Exact-state adapters for the proved SL4 Lemma 4.8/4.9 zero rules.

The legacy rule catalogue describes these zero certificates as colored local
subgraphs.  This module extracts only that sign-independent incidence data
directly from the exact dart/mate/bundle state.  It never reconstructs a web
from neighbour lists and never changes the exact state being certified.
"""

from __future__ import annotations

import math
from typing import Any

from halfedge_web_20260812 import (
    EdgeKind,
    ExactRibbonState,
    VertexColor,
    bundle_ids,
    validate_exact_web,
    vertex_cycle_ccw,
)
from web_relation_rules_optimized_20260726 import (
    detect_sl4_lemma48_zero_pair,
    _paired_pattern_required_graph_connected,
    _pattern_boundary_windows,
    sl4_lemma49_zero_rule_catalog,
)


def _color_name(color: VertexColor) -> str:
    if color == VertexColor.BLACK:
        return "black"
    if color == VertexColor.WHITE:
        return "white"
    return "boundary"


def exact_pattern_graph(web: ExactRibbonState) -> dict[str, Any]:
    """Return the local-pattern view extracted from an exact ribbon state.

    Ordinary physical edges and hourglass bundles are enumerated from the
    mate involution and bundle IDs, respectively.  Parallel ordinary edges
    remain separate records even though the Lemma matchers only ask whether a
    required incidence exists.
    """

    validate_exact_web(web)
    nodes = [
        {"id": int(vertex), "color": _color_name(web.color[vertex])}
        for vertex in sorted(web.color)
    ]
    boundary = [
        {"node": int(vertex), "label": int(label)}
        for vertex, label in sorted(web.boundary_label.items())
        if label is not None
    ]

    edges: list[dict[str, Any]] = []
    seen_physical: set[int] = set()
    for dart in sorted(web.vertex_of):
        if web.edge_kind[dart] != EdgeKind.ORDINARY:
            continue
        physical = int(web.physical_edge_of[dart])
        if physical in seen_physical:
            continue
        seen_physical.add(physical)
        mate = web.mate[dart]
        edges.append(
            {
                "id": physical,
                "src": int(web.vertex_of[dart]),
                "dst": int(web.vertex_of[mate]),
                "kind": "ordinary",
            }
        )

    hourglasses: list[dict[str, Any]] = []
    for bundle in bundle_ids(web):
        endpoints = {
            int(web.vertex_of[dart])
            for dart, candidate in web.bundle_of.items()
            if candidate == bundle
        }
        if len(endpoints) != 2:
            raise ValueError(
                f"Exact hourglass bundle {bundle} has endpoints {sorted(endpoints)}."
            )
        white = [v for v in endpoints if web.color[v] == VertexColor.WHITE]
        black = [v for v in endpoints if web.color[v] == VertexColor.BLACK]
        if len(white) != 1 or len(black) != 1:
            raise ValueError(
                f"Exact hourglass bundle {bundle} is not white-black: {sorted(endpoints)}."
            )
        hourglasses.append(
            {"id": int(bundle), "white": white[0], "black": black[0]}
        )

    return {
        "nodes": nodes,
        "boundary": boundary,
        "edges": edges,
        "hourglasses": hourglasses,
    }


def _pair(left: int, right: int) -> tuple[int, int]:
    return (left, right) if left <= right else (right, left)


def _is_standard_sl4_state(web: ExactRibbonState) -> bool:
    """Return whether every tensor is in the standard SL4 web domain.

    Figure 43 and other local computations may temporarily create deliberately
    lower-valence helper tensors.  Lemma 4.9 is a statement about standard web
    tensors, so such helpers must not be discharged merely because their
    incidence graph happens to contain one of the catalogue pictures.
    """

    for vertex, color in web.color.items():
        wanted = 1 if color == VertexColor.BOUNDARY else 4
        if int(web.tensor_valence.get(vertex, wanted)) != wanted:
            return False
        if len(vertex_cycle_ccw(web, vertex)) != wanted:
            return False
    return True


def _pattern_side(pattern_web: dict[str, Any]) -> dict[str, Any]:
    nodes = {str(item["id"]): item for item in pattern_web.get("nodes", [])}
    ports = {str(item) for item in pattern_web.get("ports", [])}
    boundary = tuple(str(item) for item in pattern_web.get("boundary_order", []))
    internal = tuple(
        node
        for node, item in nodes.items()
        if node not in ports and item.get("role") == "internal"
    )
    nonports = set(boundary) | set(internal)
    edges: list[dict[str, Any]] = []
    incident: dict[str, list[str]] = {node: [] for node in internal}
    port_edges: list[dict[str, Any]] = []
    required_edges: list[dict[str, Any]] = []
    for raw in pattern_web.get("edges", []):
        edge = {
            "id": str(raw["id"]),
            "u": str(raw["u"]),
            "v": str(raw["v"]),
            "kind": str(raw.get("kind", "ordinary")),
            "multiplicity": int(raw.get("multiplicity", 1)),
        }
        edges.append(edge)
        for endpoint in (edge["u"], edge["v"]):
            if endpoint in incident:
                incident[endpoint].append(edge["id"])
        if edge["u"] in ports or edge["v"] in ports:
            if edge["u"] in ports and edge["v"] in ports:
                raise ValueError("A Lemma 4.9 port edge cannot join two ports.")
            port = edge["u"] if edge["u"] in ports else edge["v"]
            local = edge["v"] if edge["u"] in ports else edge["u"]
            if local not in internal:
                raise ValueError(
                    f"Lemma 4.9 port {port} is not attached to an internal vertex."
                )
            if edge["kind"] != "ordinary" or edge["multiplicity"] != 1:
                raise ValueError(
                    "Exact Lemma 4.9 currently requires named ports to be "
                    "ordinary one-dart half-edges."
                )
            port_edges.append({**edge, "port": port, "local": local})
        else:
            if edge["u"] not in nonports or edge["v"] not in nonports:
                raise ValueError(f"Unknown pattern endpoint in edge {edge['id']}.")
            required_edges.append(edge)

    by_id = {edge["id"]: edge for edge in edges}
    return {
        "nodes": nodes,
        "ports": ports,
        "boundary": boundary,
        "internal": internal,
        "edges": tuple(edges),
        "edge_by_id": by_id,
        "required_edges": tuple(required_edges),
        "port_edges": tuple(port_edges),
        "incident": incident,
        "constraints": tuple(pattern_web.get("constraints", [])),
    }


def _actual_edge_indexes(web: ExactRibbonState) -> dict[str, Any]:
    ordinary_by_physical: dict[int, list[int]] = {}
    bundles: dict[int, list[int]] = {}
    for dart in web.vertex_of:
        if web.edge_kind[dart] == EdgeKind.ORDINARY:
            ordinary_by_physical.setdefault(
                int(web.physical_edge_of[dart]), []
            ).append(int(dart))
        else:
            bundle = web.bundle_of[dart]
            if bundle is None:
                raise ValueError(f"Hourglass dart {dart} has no bundle ID.")
            bundles.setdefault(int(bundle), []).append(int(dart))

    ordinary: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for physical, darts in ordinary_by_physical.items():
        if len(darts) != 2:
            raise ValueError(f"Ordinary edge {physical} has {len(darts)} darts.")
        endpoints = tuple(web.vertex_of[dart] for dart in darts)
        record = {
            "kind": "ordinary",
            "resource": int(physical),
            "darts": {
                int(vertex): tuple(
                    dart for dart in darts if web.vertex_of[dart] == vertex
                )
                for vertex in set(endpoints)
            },
        }
        ordinary.setdefault(_pair(*endpoints), []).append(record)

    hourglass: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for bundle, darts in bundles.items():
        by_vertex: dict[int, list[int]] = {}
        for dart in darts:
            by_vertex.setdefault(int(web.vertex_of[dart]), []).append(dart)
        if len(by_vertex) != 2 or any(len(local) != 2 for local in by_vertex.values()):
            raise ValueError(f"Hourglass bundle {bundle} is not a two-by-two bundle.")
        endpoints = tuple(by_vertex)
        record = {
            "kind": "hourglass",
            "resource": int(bundle),
            "darts": {vertex: tuple(local) for vertex, local in by_vertex.items()},
        }
        hourglass.setdefault(_pair(*endpoints), []).append(record)

    return {"ordinary": ordinary, "hourglass": hourglass}


def _allowed_kinds(edge: dict[str, Any]) -> tuple[str, ...]:
    kind = str(edge["kind"])
    if kind == "ordinary_or_hourglass":
        return ("ordinary", "hourglass")
    if kind not in {"ordinary", "hourglass"}:
        raise ValueError(f"Unsupported Lemma 4.9 edge kind {kind!r}.")
    return (kind,)


def _resource_candidates(
    indexes: dict[str, Any],
    edge: dict[str, Any],
    mapping: dict[str, int],
) -> list[dict[str, Any]]:
    endpoints = _pair(mapping[edge["u"]], mapping[edge["v"]])
    result: list[dict[str, Any]] = []
    for kind in _allowed_kinds(edge):
        result.extend(indexes[kind].get(endpoints, ()))
    return result


def _cyclic_equal(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if len(left) != len(right):
        return False
    if not left:
        return True
    doubled = left + left
    width = len(left)
    return any(doubled[offset : offset + width] == right for offset in range(width))


def _pattern_rotation(
    side: dict[str, Any],
    vertex: str,
    assignments: dict[str, dict[str, Any]],
    *,
    reflected: bool,
) -> tuple[str, ...]:
    center = side["nodes"][vertex]
    cx, cy = float(center["x"]), float(center["y"])
    blocks: list[tuple[float, str, int]] = []
    for edge_id in side["incident"][vertex]:
        edge = side["edge_by_id"][edge_id]
        other = edge["v"] if edge["u"] == vertex else edge["u"]
        point = side["nodes"][other]
        angle = math.atan2(float(point["y"]) - cy, float(point["x"]) - cx)
        assigned = assignments[edge_id]
        multiplicity = 2 if assigned["kind"] == "hourglass" else 1
        blocks.append((angle, edge_id, multiplicity))
    blocks.sort(key=lambda item: (item[0], item[1]))
    tokens = tuple(
        edge_id
        for _angle, edge_id, multiplicity in blocks
        for _ in range(multiplicity)
    )
    return tuple(reversed(tokens)) if reflected else tokens


def _rotation_system_ok(
    web: ExactRibbonState,
    side: dict[str, Any],
    mapping: dict[str, int],
    assignments: dict[str, dict[str, Any]],
    *,
    reflected: bool,
) -> bool:
    dart_token: dict[int, str] = {}
    for edge_id, assigned in assignments.items():
        edge = side["edge_by_id"][edge_id]
        if "port_dart" in assigned:
            dart_token[int(assigned["port_dart"])] = edge_id
            continue
        for pattern_vertex in (edge["u"], edge["v"]):
            if pattern_vertex not in side["internal"]:
                continue
            actual_vertex = mapping[pattern_vertex]
            local = tuple(assigned["darts"].get(actual_vertex, ()))
            wanted = 2 if assigned["kind"] == "hourglass" else 1
            if len(local) != wanted:
                return False
            if assigned["kind"] == "hourglass":
                cycle = vertex_cycle_ccw(web, actual_vertex)
                positions = sorted(cycle.index(dart) for dart in local)
                if (positions[1] - positions[0]) % len(cycle) not in {
                    1,
                    len(cycle) - 1,
                }:
                    return False
            for dart in local:
                if dart in dart_token:
                    return False
                dart_token[dart] = edge_id

    for pattern_vertex in side["internal"]:
        actual_vertex = mapping[pattern_vertex]
        actual = tuple(
            dart_token[dart]
            for dart in vertex_cycle_ccw(web, actual_vertex)
            if dart in dart_token
        )
        expected = _pattern_rotation(
            side,
            pattern_vertex,
            assignments,
            # The catalogue drawings place b1,...,bn from left to right along
            # the bottom of the disk.  That is the reverse of the disk's CCW
            # boundary orientation.  Consequently an increasing (unreflected)
            # boundary window reverses the drawn local rotations, while the
            # reflected/decreasing window uses the drawn rotations verbatim.
            reflected=not reflected,
        )
        if not _cyclic_equal(actual, expected):
            return False
    return True


def _constraints_ok(
    side: dict[str, Any], assignments: dict[str, dict[str, Any]]
) -> bool:
    for constraint in side["constraints"]:
        if constraint.get("type") != "exact_edge_kind_count":
            continue
        wanted_kind = str(constraint["kind"])
        actual = sum(
            assignments[str(edge_id)]["kind"] == wanted_kind
            for edge_id in constraint.get("edge_ids", [])
        )
        if actual != int(constraint["count"]):
            return False
    return True


def _match_exact_pattern_side(
    web: ExactRibbonState,
    pattern_web: dict[str, Any],
    boundary_labels: tuple[int, ...],
    *,
    reflected: bool,
    max_matches: int,
) -> list[dict[str, Any]]:
    """Search exact node, edge, port, and ribbon embeddings for one side."""

    side = _pattern_side(pattern_web)
    if len(side["boundary"]) != len(boundary_labels):
        return []
    boundary_by_label = {
        int(label): int(vertex)
        for vertex, label in web.boundary_label.items()
        if label is not None
    }
    if any(label not in boundary_by_label for label in boundary_labels):
        return []
    mapping: dict[str, int] = {
        node: boundary_by_label[label]
        for node, label in zip(side["boundary"], boundary_labels)
    }
    indexes = _actual_edge_indexes(web)

    relation_edges: dict[str, list[dict[str, Any]]] = {
        node: [] for node in side["internal"]
    }
    for edge in side["required_edges"]:
        for endpoint in (edge["u"], edge["v"]):
            if endpoint in relation_edges:
                relation_edges[endpoint].append(edge)

    internal_candidates: dict[str, list[int]] = {}
    boundary_vertices = set(boundary_by_label.values())
    for node in side["internal"]:
        wanted = str(side["nodes"][node].get("color", ""))
        color = VertexColor.WHITE if wanted == "white" else VertexColor.BLACK
        candidates = [
            vertex
            for vertex, actual_color in web.color.items()
            if actual_color == color and vertex not in boundary_vertices
        ]
        for edge in relation_edges[node]:
            other = edge["v"] if edge["u"] == node else edge["u"]
            if other not in mapping:
                continue
            filtered = []
            for candidate in candidates:
                trial = {**mapping, node: candidate}
                if _resource_candidates(indexes, edge, trial):
                    filtered.append(candidate)
            candidates = filtered
        if not candidates:
            return []
        internal_candidates[node] = sorted(candidates)

    ordered_internal = sorted(
        side["internal"], key=lambda node: (len(internal_candidates[node]), node)
    )
    matches: list[dict[str, Any]] = []

    def exact_assignments() -> None:
        if len(matches) >= max_matches:
            return
        required = list(side["required_edges"])
        assignments: dict[str, dict[str, Any]] = {}
        used_resources: set[tuple[str, int]] = set()

        def assign_required(index: int) -> None:
            if len(matches) >= max_matches:
                return
            if index == len(required):
                assign_ports(0)
                return
            edge = required[index]
            for resource in _resource_candidates(indexes, edge, mapping):
                key = (str(resource["kind"]), int(resource["resource"]))
                if key in used_resources:
                    continue
                assignments[edge["id"]] = resource
                used_resources.add(key)
                assign_required(index + 1)
                used_resources.remove(key)
                del assignments[edge["id"]]

        ports = list(side["port_edges"])

        def assign_ports(index: int) -> None:
            if len(matches) >= max_matches:
                return
            if index == len(ports):
                if not _constraints_ok(side, assignments):
                    return
                if not _rotation_system_ok(
                    web,
                    side,
                    mapping,
                    assignments,
                    reflected=reflected,
                ):
                    return
                ordinary_edges = sorted(
                    {
                        _pair(mapping[edge["u"]], mapping[edge["v"]])
                        for edge in required
                        if assignments[edge["id"]]["kind"] == "ordinary"
                    }
                )
                hourglass_edges = sorted(
                    {
                        _pair(mapping[edge["u"]], mapping[edge["v"]])
                        for edge in required
                        if assignments[edge["id"]]["kind"] == "hourglass"
                    }
                )
                matches.append(
                    {
                        "node_map": dict(mapping),
                        "boundary_labels": list(boundary_labels),
                        "ordinary_edges": ordinary_edges,
                        "hourglass_edges": hourglass_edges,
                        "edge_map": {
                            edge_id: {
                                "kind": str(item["kind"]),
                                "resource": item.get("resource"),
                                "darts": {
                                    str(vertex): list(darts)
                                    for vertex, darts in item.get("darts", {}).items()
                                },
                            }
                            for edge_id, item in assignments.items()
                            if "port_dart" not in item
                        },
                        "port_darts": {
                            edge["port"]: int(assignments[edge["id"]]["port_dart"])
                            for edge in ports
                        },
                        "rotation_preserved": True,
                    }
                )
                return

            edge = ports[index]
            actual_vertex = mapping[edge["local"]]
            mapped_vertices = set(mapping.values())
            for dart in vertex_cycle_ccw(web, actual_vertex):
                if web.edge_kind[dart] != EdgeKind.ORDINARY:
                    continue
                physical = int(web.physical_edge_of[dart])
                key = ("ordinary", physical)
                if key in used_resources:
                    continue
                outside = int(web.vertex_of[web.mate[dart]])
                if outside in mapped_vertices:
                    continue
                assignments[edge["id"]] = {
                    "kind": "ordinary",
                    "resource": physical,
                    "darts": {actual_vertex: (int(dart),)},
                    "port_dart": int(dart),
                }
                used_resources.add(key)
                assign_ports(index + 1)
                used_resources.remove(key)
                del assignments[edge["id"]]

        assign_required(0)

    def map_nodes(index: int, used: set[int]) -> None:
        if len(matches) >= max_matches:
            return
        if index == len(ordered_internal):
            exact_assignments()
            return
        node = ordered_internal[index]
        for candidate in internal_candidates[node]:
            if candidate in used:
                continue
            mapping[node] = candidate
            compatible = True
            for edge in relation_edges[node]:
                other = edge["v"] if edge["u"] == node else edge["u"]
                if other in mapping and not _resource_candidates(indexes, edge, mapping):
                    compatible = False
                    break
            if compatible:
                used.add(candidate)
                map_nodes(index + 1, used)
                used.remove(candidate)
            del mapping[node]

    map_nodes(0, set(mapping.values()))
    return matches


def exact_lemma49_zero_certificates(
    w: ExactRibbonState,
    x: ExactRibbonState,
    *,
    max_matches: int = 1,
) -> list[dict[str, Any]]:
    """Return exact-dart Lemma 4.9 witnesses, continuing past bad embeddings."""

    validate_exact_web(w)
    validate_exact_web(x)
    if max_matches <= 0:
        return []
    boundary_count = sum(label is not None for label in w.boundary_label.values())
    if boundary_count == 0 or boundary_count != sum(
        label is not None for label in x.boundary_label.values()
    ):
        return []

    found: list[dict[str, Any]] = []
    for pattern in sl4_lemma49_zero_rule_catalog():
        if not _paired_pattern_required_graph_connected(pattern):
            continue
        matching = pattern.get("matching", {})
        allow_helpers = bool(
            matching.get("allow_non_valence_4_helper_tensors", False)
        )
        if not allow_helpers and (
            not _is_standard_sl4_state(w) or not _is_standard_sl4_state(x)
        ):
            continue
        if len(pattern["W"].get("boundary_order", ())) != len(
            pattern["X"].get("boundary_order", ())
        ):
            continue
        assignments = [(False, pattern["W"], pattern["X"])]
        if bool(matching.get("allow_pair_swap", False)):
            assignments.append((True, pattern["X"], pattern["W"]))
        for labels, reflected, start, disk_rotated in _pattern_boundary_windows(
            pattern, boundary_count
        ):
            label_tuple = tuple(int(label) for label in labels)
            for pair_swapped, pattern_w, pattern_x in assignments:
                remaining = max_matches - len(found)
                w_matches = _match_exact_pattern_side(
                    w,
                    pattern_w,
                    label_tuple,
                    reflected=bool(reflected),
                    max_matches=remaining,
                )
                if not w_matches:
                    continue
                x_matches = _match_exact_pattern_side(
                    x,
                    pattern_x,
                    label_tuple,
                    reflected=bool(reflected),
                    max_matches=remaining,
                )
                if not x_matches:
                    continue
                for w_match in w_matches:
                    for x_match in x_matches:
                        found.append(
                            {
                                "zero_rule": "sl4_lemma49",
                                "rule_id": pattern["id"],
                                "reason": pattern.get("conclusion", {}).get(
                                    "reason", pattern["id"]
                                ),
                                "source": pattern.get("source", {}),
                                "boundary_labels": list(label_tuple),
                                "reflected": bool(reflected),
                                "disk_rotation_start": int(start),
                                "disk_rotated": bool(disk_rotated),
                                "pair_swapped": bool(pair_swapped),
                                "W": w_match,
                                "X": x_match,
                            }
                        )
                        if len(found) >= max_matches:
                            return found
    return found


def exact_lemma49_zero_certificate(
    w: ExactRibbonState, x: ExactRibbonState
) -> dict[str, Any] | None:
    """Return the first exact embedded Lemma 4.9 witness, if present."""

    matches = exact_lemma49_zero_certificates(w, x, max_matches=1)
    if not matches:
        return None
    return matches[0]


def exact_lemma48_zero_certificate(
    w: ExactRibbonState, x: ExactRibbonState
) -> dict[str, Any] | None:
    """Return the first proved Lemma 4.8 witness, if present."""

    matches = detect_sl4_lemma48_zero_pair(
        exact_pattern_graph(w), exact_pattern_graph(x), max_matches=1
    )
    if not matches:
        return None
    return {"zero_rule": "sl4_lemma48", **matches[0]}


def exact_pair_pattern_zero_certificate(
    w: ExactRibbonState, x: ExactRibbonState
) -> dict[str, Any] | None:
    """Apply the proved pair-pattern zero rules in the legacy priority order."""

    return exact_lemma49_zero_certificate(w, x) or exact_lemma48_zero_certificate(w, x)
