"""Exact ribbon/half-edge state used by the representation-aware SL4 engine.

The selected graph JSON is loaded literally: every dart, mate, physical edge,
hourglass bundle, rooted counterclockwise vertex cycle, vertex color, and
boundary label remains explicit.  ``canonical_web_key`` only removes temporary
Python identifiers when terms are consolidated; it never replaces the chosen
top/middle/bottom presentation by a different web.

The older neighbor-list evaluator still exists for comparison and audit
replay.  New production relation code must use this state and must not rebuild
it from that lossy projection.
"""

from __future__ import annotations

import copy
import json
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Hashable, Iterable, Mapping

from Wrench_or_Skein_0714 import canonical_tagged_rotation_system


DartId = int
VertexId = int
PhysicalEdgeId = int
BundleId = int


class EdgeKind(IntEnum):
    ORDINARY = 0
    HOURGLASS_STRAND = 1


class VertexColor(IntEnum):
    BOUNDARY = 0
    BLACK = 1
    WHITE = 2


@dataclass
class HalfEdgeWeb:
    vertex_of: dict[DartId, VertexId]
    mate: dict[DartId, DartId]
    next_ccw: dict[DartId, DartId]

    edge_kind: dict[DartId, EdgeKind]
    physical_edge_of: dict[DartId, PhysicalEdgeId]
    bundle_of: dict[DartId, BundleId | None]

    color: dict[VertexId, VertexColor]
    boundary_label: dict[VertexId, int | None]
    tag_after_ccw: dict[VertexId, DartId | None]

    source_edge_id: dict[DartId, int | None] = field(default_factory=dict)
    source_local_strand: dict[DartId, int | None] = field(default_factory=dict)
    source_xy: dict[VertexId, tuple[float, float]] = field(default_factory=dict)
    # Boundary vertices have valence 1.  Catalogue vertices have valence 4;
    # Figure 43 can temporarily create explicitly tagged lower-valence tensors.
    tensor_valence: dict[VertexId, int] = field(default_factory=dict)
    # Persistent hourglass reference roots, one at each bundle endpoint.
    # These do not move when the live tensor tag moves.
    bundle_frame_root: dict[BundleId, dict[VertexId, DartId]] = field(
        default_factory=dict
    )
    # Full parent snapshots for generated square presentations.  Every
    # snapshot has an empty stack of its own, so this is finite, nonrecursive
    # exact provenance rather than a lossy path label.  Production can unwind
    # to the selected catalogue/presentation state before a skein reduction.
    square_undo_stack: tuple["HalfEdgeWeb", ...] = field(default_factory=tuple)
    square_undo_multipliers: tuple[int, ...] = field(default_factory=tuple)


# Semantic name used by the new production kernel.  Keeping the historical
# class name avoids breaking the already-audited exact square-move code.
ExactRibbonState = HalfEdgeWeb


@dataclass(frozen=True)
class ExactWrenchBranch:
    name: str
    formal_coefficient: int
    web: HalfEdgeWeb
    port_pairing: tuple[tuple[str, str], tuple[str, str]]


@dataclass(frozen=True)
class ExactDoubleTridentBranch:
    permutation: tuple[int, int, int]
    paper_coefficient: int
    endpoint_tag_transport_multiplier: int
    boundary_order_multiplier: int
    tag_transport_multiplier: int
    boundary_paper_order: tuple[int, int, int]
    boundary_engine_order: tuple[int, int, int]
    boundary_order_permutation: tuple[int, int, int]
    web: HalfEdgeWeb
    port_pairing: tuple[tuple[str, str], tuple[str, str], tuple[str, str]]


def _node_map(data: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    nodes = data.get("nodes", [])
    if isinstance(nodes, Mapping):
        return {int(k): dict(v) for k, v in nodes.items()}
    return {int(item["id"]): dict(item) for item in nodes}


def load_halfedge_web(source: Mapping[str, Any] | str | Path) -> HalfEdgeWeb:
    """Load one current graph JSON into the exact dart representation."""

    if isinstance(source, (str, Path)):
        with Path(source).open() as handle:
            data = json.load(handle)
    else:
        data = dict(source)

    nodes = _node_map(data)
    boundary_by_node = {
        int(item["node"]): int(item["label"])
        for item in data.get("boundary", [])
    }
    rotation = canonical_tagged_rotation_system(data)

    vertex_of: dict[int, int] = {}
    next_ccw: dict[int, int] = {}
    edge_kind: dict[int, EdgeKind] = {}
    source_edge_id: dict[int, int | None] = {}
    source_local_strand: dict[int, int | None] = {}
    tag_after_ccw: dict[int, int | None] = {}
    edge_groups: dict[int, list[int]] = {}
    local_key_to_dart: dict[tuple[int, int, int | None, int], int] = {}

    next_dart = 0
    for node_id in sorted(int(k) for k in rotation):
        entries = sorted(rotation[str(node_id)], key=lambda item: int(item["ccw_slot"]))
        local: list[int] = []
        seen: dict[tuple[int, int | None], int] = {}
        for item in entries:
            edge_id = int(item["edge"])
            strand = item.get("strand")
            strand = None if strand is None else int(strand)
            occurrence = seen.get((edge_id, strand), 0)
            seen[(edge_id, strand)] = occurrence + 1
            dart = next_dart
            next_dart += 1
            local_key_to_dart[(node_id, edge_id, strand, occurrence)] = dart
            vertex_of[dart] = node_id
            kind = str(item.get("kind", "ordinary"))
            edge_kind[dart] = (
                EdgeKind.HOURGLASS_STRAND
                if kind == "hourglass_strand"
                else EdgeKind.ORDINARY
            )
            source_edge_id[dart] = edge_id
            source_local_strand[dart] = strand
            edge_groups.setdefault(edge_id, []).append(dart)
            local.append(dart)
        if local:
            for current, following in zip(local, local[1:] + local[:1]):
                next_ccw[current] = following
        tag_after_ccw[node_id] = None if node_id in boundary_by_node else (local[0] if local else None)

    mate: dict[int, int] = {}
    physical_edge_of: dict[int, int] = {}
    bundle_of: dict[int, int | None] = {}
    next_physical = 0
    next_bundle = 0
    for source_edge, darts in sorted(edge_groups.items()):
        kinds = {edge_kind[dart] for dart in darts}
        if kinds == {EdgeKind.ORDINARY}:
            if len(darts) != 2:
                raise ValueError(f"Ordinary source edge {source_edge} has {len(darts)} darts.")
            a, b = darts
            mate[a] = b
            mate[b] = a
            physical_edge_of[a] = physical_edge_of[b] = next_physical
            bundle_of[a] = bundle_of[b] = None
            next_physical += 1
            continue

        if kinds != {EdgeKind.HOURGLASS_STRAND} or len(darts) != 4:
            raise ValueError(
                f"Source edge {source_edge} has unsupported kind/dart data: {kinds}, {darts}."
            )
        by_vertex: dict[int, dict[int, int]] = {}
        for dart in darts:
            strand = source_local_strand[dart]
            if strand not in (0, 1):
                raise ValueError(f"Hourglass dart {dart} has invalid local strand {strand!r}.")
            by_vertex.setdefault(vertex_of[dart], {})[int(strand)] = dart
        if len(by_vertex) != 2 or any(set(slots) != {0, 1} for slots in by_vertex.values()):
            raise ValueError(f"Hourglass source edge {source_edge} has invalid endpoint slots.")
        u, v = sorted(by_vertex)
        # Existing exporter convention: endpoint-local strand s crosses to 1-s.
        for strand in (0, 1):
            a = by_vertex[u][strand]
            b = by_vertex[v][1 - strand]
            mate[a] = b
            mate[b] = a
            physical_edge_of[a] = physical_edge_of[b] = next_physical
            next_physical += 1
        for dart in darts:
            bundle_of[dart] = next_bundle
        next_bundle += 1

    color: dict[int, VertexColor] = {}
    boundary_label: dict[int, int | None] = {}
    source_xy: dict[int, tuple[float, float]] = {}
    for node_id, item in nodes.items():
        boundary_label[node_id] = boundary_by_node.get(node_id)
        if node_id in boundary_by_node:
            color[node_id] = VertexColor.BOUNDARY
        else:
            raw_color = str(item.get("color", "")).lower()
            if raw_color == "black":
                color[node_id] = VertexColor.BLACK
            elif raw_color == "white":
                color[node_id] = VertexColor.WHITE
            else:
                raise ValueError(f"Internal node {node_id} has unsupported color {raw_color!r}.")
        if "x" in item and "y" in item:
            source_xy[node_id] = (float(item["x"]), float(item["y"]))

    web = HalfEdgeWeb(
        vertex_of=vertex_of,
        mate=mate,
        next_ccw=next_ccw,
        edge_kind=edge_kind,
        physical_edge_of=physical_edge_of,
        bundle_of=bundle_of,
        color=color,
        boundary_label=boundary_label,
        tag_after_ccw=tag_after_ccw,
        source_edge_id=source_edge_id,
        source_local_strand=source_local_strand,
        source_xy=source_xy,
        tensor_valence={
            node_id: (1 if node_id in boundary_by_node else 4)
            for node_id in nodes
        },
    )
    for bundle in sorted({b for b in bundle_of.values() if b is not None}):
        endpoints = {
            vertex_of[dart]
            for dart, candidate in bundle_of.items()
            if candidate == bundle
        }
        web.bundle_frame_root[int(bundle)] = {
            vertex: int(tag_after_ccw[vertex]) for vertex in endpoints
        }
    validate_exact_web(web)
    return web


def vertex_cycle_ccw(web: HalfEdgeWeb, vertex: int) -> tuple[int, ...]:
    darts = [dart for dart, owner in web.vertex_of.items() if owner == vertex]
    if not darts:
        return ()
    start = min(darts)
    result = [start]
    current = web.next_ccw[start]
    while current != start:
        if current in result:
            raise ValueError(f"next_ccw at vertex {vertex} contains a proper subcycle.")
        result.append(current)
        current = web.next_ccw[current]
    return tuple(result)


def rooted_cycle_ccw(web: HalfEdgeWeb, vertex: int) -> tuple[int, ...]:
    cycle = vertex_cycle_ccw(web, vertex)
    if not cycle:
        return ()
    root = web.tag_after_ccw.get(vertex)
    if root is None:
        return cycle
    position = cycle.index(root)
    return cycle[position:] + cycle[:position]


def rooted_cycle_clockwise(web: HalfEdgeWeb, vertex: int) -> tuple[int, ...]:
    return tuple(reversed(rooted_cycle_ccw(web, vertex)))


def _abstract_incident_edge_token(
    web: HalfEdgeWeb, dart: int
) -> tuple[str, int]:
    """Identify the abstract web edge represented by one drawn dart.

    A simple edge has one physical dart at the vertex.  The two adjacent
    strands of a 2-hourglass are one multiplicity-two web edge, not two
    independently tagged tensor slots.
    """

    bundle = web.bundle_of[dart]
    if bundle is not None:
        return ("bundle", int(bundle))
    return ("physical", int(web.physical_edge_of[dart]))


def paper_incident_edge_blocks_clockwise(
    web: HalfEdgeWeb, vertex: int
) -> tuple[tuple[int, ...], ...]:
    """Return incident abstract edges clockwise from the live tag.

    This is the literal input order in Gaetz--Pechenik--Pfannerer--Striker--
    Swanson, Definition 2.8.  A multiplicity-two edge is returned as one
    two-dart block.  ``tag_after_ccw`` records the first dart counterclockwise
    after the tag, so the first dart clockwise after the same tag is its
    counterclockwise predecessor.

    A tag between the two drawn strands of one hourglass is rejected: that is
    an internal strand-frame gap, not a tag position of the abstract web.
    """

    cycle = vertex_cycle_ccw(web, int(vertex))
    if not cycle:
        raise ValueError(f"Vertex {vertex} has no incident edge.")
    root = web.tag_after_ccw.get(int(vertex))
    if root not in cycle:
        raise ValueError(f"Vertex {vertex} has no live internal tag root.")
    position = cycle.index(int(root))
    previous = cycle[(position - 1) % len(cycle)]
    if _abstract_incident_edge_token(web, previous) == _abstract_incident_edge_token(
        web, int(root)
    ):
        raise ValueError(
            f"Tag at vertex {vertex} splits the two strands of one "
            "multiplicity-two edge."
        )

    clockwise = tuple(
        cycle[(position - 1 - offset) % len(cycle)]
        for offset in range(len(cycle))
    )
    blocks: list[list[int]] = []
    tokens: list[tuple[str, int]] = []
    for dart in clockwise:
        token = _abstract_incident_edge_token(web, int(dart))
        if not tokens or token != tokens[-1]:
            tokens.append(token)
            blocks.append([int(dart)])
        else:
            blocks[-1].append(int(dart))
    if len(tokens) > 1 and tokens[0] == tokens[-1]:
        raise ValueError(
            f"Tag at vertex {vertex} does not separate abstract incident edges."
        )
    if len(set(tokens)) != len(tokens):
        raise ValueError(
            f"Abstract incident edge blocks repeat around vertex {vertex}."
        )
    if any(len(block) not in {1, 2} for block in blocks):
        raise ValueError(
            f"Vertex {vertex} has an unsupported incident multiplicity."
        )
    return tuple(tuple(block) for block in blocks)


def paper_coinversion_number(
    ordered_subsets: Iterable[Iterable[int]],
) -> int:
    """Definition 2.8 coinversion number of clockwise incident subsets."""

    subsets = tuple(tuple(int(value) for value in subset) for subset in ordered_subsets)
    return sum(
        left_value <= right_value
        for left_index, left in enumerate(subsets)
        for right in subsets[left_index + 1 :]
        for left_value in left
        for right_value in right
    )


def paper_vertex_labeling_data(
    web: HalfEdgeWeb,
    vertex: int,
    physical_edge_colors: Mapping[int, int],
    *,
    r: int = 4,
) -> dict[str, Any]:
    """Evaluate the paper-supported local sign of one proper labeling.

    Edge labels are subsets, a 2-hourglass contributes one two-element
    subset, and the subsets are read clockwise from the tag.  There is no
    independent black/white vertex scalar.
    """

    blocks = paper_incident_edge_blocks_clockwise(web, int(vertex))
    subsets = tuple(
        tuple(
            sorted(
                int(physical_edge_colors[int(web.physical_edge_of[dart])])
                for dart in block
            )
        )
        for block in blocks
    )
    flattened = tuple(value for subset in subsets for value in subset)
    proper = (
        len(flattened) == int(r)
        and sorted(flattened) == list(range(1, int(r) + 1))
    )
    coinversion = paper_coinversion_number(subsets) if proper else None
    sign = 0 if not proper else (-1 if int(coinversion) % 2 else 1)
    return {
        "vertex": int(vertex),
        "clockwise_dart_blocks": [list(block) for block in blocks],
        "clockwise_physical_edge_blocks": [
            [int(web.physical_edge_of[dart]) for dart in block]
            for block in blocks
        ],
        "clockwise_edge_label_subsets": [list(subset) for subset in subsets],
        "coinversion_number": coinversion,
        "proper": bool(proper),
        "sign": int(sign),
        "convention": "GPPSS_Definition_2.8_clockwise_subset_coinversion",
    }


def paper_vertex_labeling_sign(
    web: HalfEdgeWeb,
    vertex: int,
    physical_edge_colors: Mapping[int, int],
    *,
    r: int = 4,
) -> int:
    """Return ``(-1)^ell_v`` from Definition 2.8, or zero if improper."""

    return int(
        paper_vertex_labeling_data(
            web, int(vertex), physical_edge_colors, r=int(r)
        )["sign"]
    )


def paper_tag_transport_sign(
    web: HalfEdgeWeb,
    vertex: int,
    target_root: int,
    *,
    r: int = 4,
) -> int:
    """Move a live tag to another abstract edge gap using Lemma 2.5.

    Crossing an edge of multiplicity ``c`` contributes
    ``(-1) ** (c * (r-c))``.  In particular for SL4, crossing a simple edge
    contributes ``-1`` while crossing a 2-hourglass contributes ``+1``.
    Strand-frame gaps are not legal source or target tags.
    """

    vertex = int(vertex)
    target_root = int(target_root)
    cycle = vertex_cycle_ccw(web, vertex)
    source_root = web.tag_after_ccw.get(vertex)
    if source_root not in cycle or target_root not in cycle:
        raise ValueError(f"Cannot transport the tag at vertex {vertex}.")

    # Validate the source gap through the paper-order constructor.
    paper_incident_edge_blocks_clockwise(web, vertex)
    target_web = copy.deepcopy(web)
    target_web.tag_after_ccw[vertex] = target_root
    paper_incident_edge_blocks_clockwise(target_web, vertex)

    position = cycle.index(int(source_root))
    target_position = cycle.index(target_root)
    exponent = 0
    while position != target_position:
        token = _abstract_incident_edge_token(web, cycle[position])
        multiplicity = 0
        while (
            position != target_position
            and _abstract_incident_edge_token(web, cycle[position]) == token
        ):
            multiplicity += 1
            position = (position + 1) % len(cycle)
        if position == target_position:
            # The validated target lies at an abstract block boundary.
            exponent += multiplicity * (int(r) - multiplicity)
            break
        exponent += multiplicity * (int(r) - multiplicity)
    return -1 if exponent % 2 else 1


def _trip2_ray_from_dart(web: HalfEdgeWeb, first_dart: int) -> int:
    """Boundary label reached by the outward trip-2 ray on ``first_dart``."""

    incoming = web.mate[first_dart]
    for _ in range(len(web.vertex_of) + 1):
        vertex = web.vertex_of[incoming]
        label = web.boundary_label.get(vertex)
        if label is not None:
            return int(label)
        cycle = vertex_cycle_ccw(web, vertex)
        # In degree four, the black/white trip-2 directions coincide modulo 4.
        outgoing = cycle[(cycle.index(incoming) + 2) % len(cycle)]
        incoming = web.mate[outgoing]
    raise RuntimeError(f"Trip-2 ray from dart {first_dart} did not reach the boundary.")


def intrinsic_tag_root(web: HalfEdgeWeb, vertex: int) -> int | None:
    """Reconstruct the Definition 6.3 tag from exact ribbon data.

    At an hourglass endpoint the tag is the gap between its two ordinary
    half-edges.  At a four-ordinary vertex it is the base-face gap between the
    outward trip-2 rays with smallest and largest boundary labels.
    """

    if web.color[vertex] == VertexColor.BOUNDARY:
        return None
    cycle = vertex_cycle_ccw(web, vertex)
    declared = web.tensor_valence.get(vertex, len(cycle))
    if declared != 4:
        # Lower-valence tensors carry an explicit red tag in Figure 43.  There
        # is no Definition 6.3 base-face reconstruction for that temporary
        # tensor, so its stored root is the exact algebraic datum.
        return web.tag_after_ccw.get(vertex)
    kinds = [web.edge_kind[dart] for dart in cycle]
    if kinds.count(EdgeKind.HOURGLASS_STRAND) == 2 and kinds.count(EdgeKind.ORDINARY) == 2:
        starts = [
            (index + 1) % len(cycle)
            for index, dart in enumerate(cycle)
            if web.edge_kind[dart] == EdgeKind.ORDINARY
            and web.edge_kind[cycle[(index + 1) % len(cycle)]] == EdgeKind.ORDINARY
        ]
        if len(starts) != 1:
            raise ValueError(f"The ordinary tag gap is ambiguous at hourglass vertex {vertex}.")
        return cycle[starts[0]]
    if all(kind == EdgeKind.ORDINARY for kind in kinds):
        endpoints = [_trip2_ray_from_dart(web, dart) for dart in cycle]
        low = endpoints.index(min(endpoints))
        high = endpoints.index(max(endpoints))
        if (low + 1) % len(cycle) == high:
            return cycle[high]
        if (high + 1) % len(cycle) == low:
            return cycle[low]
        raise ValueError(
            f"The extreme trip-2 rays are not adjacent at ordinary vertex {vertex}: {endpoints}."
        )
    raise ValueError(f"Vertex {vertex} has no supported intrinsic tag pattern: {kinds}.")


def normalize_intrinsic_tags(
    web: HalfEdgeWeb,
) -> tuple[HalfEdgeWeb, int, dict[int, int]]:
    """Return the intrinsically tagged state and its paper tag-transport sign.

    The reported shifts remain drawn-dart offsets for replay metadata.  The
    sign itself is computed from Lemma 2.5 on abstract incident edges: crossing
    multiplicity ``c`` contributes ``(-1) ** (c * (4-c))``.  In particular a
    2-hourglass is crossed as one thick edge, never as two independent slots.
    """

    result = copy.deepcopy(web)
    sign = 1
    shifts: dict[int, int] = {}
    for vertex, color in web.color.items():
        if color == VertexColor.BOUNDARY:
            continue
        cycle = vertex_cycle_ccw(web, vertex)
        current = web.tag_after_ccw[vertex]
        intrinsic = intrinsic_tag_root(web, vertex)
        if current is None or intrinsic is None:
            raise ValueError(f"Internal vertex {vertex} has no exact tag root.")
        shift = (cycle.index(intrinsic) - cycle.index(current)) % len(cycle)
        shifts[vertex] = shift
        sign *= paper_tag_transport_sign(web, vertex, int(intrinsic), r=4)
        result.tag_after_ccw[vertex] = intrinsic
    validate_exact_web(result)
    return result, sign, shifts


def refresh_bundle_frames(web: HalfEdgeWeb) -> None:
    """Transport surviving hourglass frames and initialize only new endpoints."""

    active = sorted({bundle for bundle in web.bundle_of.values() if bundle is not None})
    refreshed: dict[int, dict[int, int]] = {}
    for bundle in active:
        endpoints = {
            web.vertex_of[dart]
            for dart, candidate in web.bundle_of.items()
            if candidate == bundle
        }
        old = web.bundle_frame_root.get(int(bundle), {})
        roots: dict[int, int] = {}
        for vertex in endpoints:
            candidate = old.get(vertex)
            if candidate is not None and web.vertex_of.get(candidate) == vertex:
                roots[vertex] = candidate
            else:
                tag = web.tag_after_ccw.get(vertex)
                if tag is None:
                    raise ValueError(
                        f"Hourglass bundle {bundle} endpoint {vertex} has no frame root."
                    )
                roots[vertex] = tag
        refreshed[int(bundle)] = roots
    web.bundle_frame_root = refreshed


def neighbor_vertices_ccw(web: HalfEdgeWeb, vertex: int) -> tuple[int, ...]:
    return tuple(web.vertex_of[web.mate[dart]] for dart in vertex_cycle_ccw(web, vertex))


def follow_trip_exact(web: HalfEdgeWeb, start_label: int, turn: int) -> int:
    """Follow ``trip_turn`` using only the exact rotation system and mates."""

    if turn not in (1, 2, 3):
        raise ValueError(f"SL4 trip turn must be 1, 2, or 3, not {turn}.")
    boundary_by_label = {
        label: vertex
        for vertex, label in web.boundary_label.items()
        if label is not None
    }
    if start_label not in boundary_by_label:
        raise ValueError(f"Boundary label {start_label} is missing.")
    start_vertex = boundary_by_label[start_label]
    start_cycle = vertex_cycle_ccw(web, start_vertex)
    if len(start_cycle) != 1:
        raise ValueError(f"Boundary label {start_label} does not have degree one.")

    incoming = web.mate[start_cycle[0]]
    seen: set[int] = set()
    for _ in range(len(web.vertex_of) + 1):
        current = web.vertex_of[incoming]
        terminal_label = web.boundary_label.get(current)
        if terminal_label is not None:
            return terminal_label
        if incoming in seen:
            raise RuntimeError(
                f"Trip_{turn} from {start_label} entered a directed cycle at dart {incoming}."
            )
        seen.add(incoming)
        cycle = vertex_cycle_ccw(web, current)
        position = cycle.index(incoming)
        color = web.color[current]
        if color == VertexColor.WHITE:
            offset = -turn
        elif color == VertexColor.BLACK:
            offset = turn
        else:
            raise ValueError(f"Trip reached non-internal vertex {current} without terminating.")
        outgoing = cycle[(position + offset) % len(cycle)]
        incoming = web.mate[outgoing]
    raise RuntimeError(f"Trip_{turn} from {start_label} exceeded the dart bound.")


def trip_permutations_exact(web: HalfEdgeWeb) -> dict[int, list[int]]:
    """Return the three SL4 trip permutations in boundary-label order."""

    labels = sorted(label for label in web.boundary_label.values() if label is not None)
    return {
        turn: [follow_trip_exact(web, label, turn) for label in labels]
        for turn in (1, 2, 3)
    }


def _cyclic_positions_form_block(positions: list[int], degree: int) -> bool:
    if len(positions) <= 1:
        return True
    wanted = set(positions)
    return any({(start + offset) % degree for offset in range(len(positions))} == wanted for start in positions)


def hourglass_has_paper_half_twist(web: HalfEdgeWeb, bundle_id: int) -> bool:
    """Whether the two endpoint strand orders agree as in GPPSS.

    GPPSS defines an hourglass as a half-twisted multiple edge for which the
    clockwise orders of its strands at the two incident vertices are the
    same.  Reversing both clockwise lists gives the equivalent CCW test used
    here.  A two-valent endpoint has no distinguished start for its complete
    two-dart cycle, so the order condition is vacuous in that temporary
    lower-valence sector.
    """

    members = [
        int(dart)
        for dart, candidate in web.bundle_of.items()
        if candidate == int(bundle_id)
    ]
    endpoints = sorted({int(web.vertex_of[dart]) for dart in members})
    if len(members) != 4 or len(endpoints) != 2:
        return False

    ordered_blocks: list[tuple[int, int]] = []
    for endpoint in endpoints:
        cycle = vertex_cycle_ccw(web, endpoint)
        block = tuple(
            dart for dart in cycle if web.bundle_of[dart] == int(bundle_id)
        )
        if len(block) != 2:
            return False
        if len(cycle) == 2:
            return True
        starts = [dart for dart in block if web.next_ccw[dart] in block]
        if len(starts) != 1:
            return False
        first = int(starts[0])
        ordered_blocks.append((first, int(web.next_ccw[first])))

    left, right = ordered_blocks
    return tuple(int(web.mate[dart]) for dart in left) == right


def enforce_paper_hourglass_half_twist(
    web: HalfEdgeWeb, bundle_id: int
) -> bool:
    """Repair one newly constructed bundle to the GPPSS half-twist.

    This mutating helper is for relation constructors before their final
    validation.  It changes only the pairing and physical-edge partition of
    the four already selected bundle darts.  It returns whether a repair was
    necessary.
    """

    if hourglass_has_paper_half_twist(web, int(bundle_id)):
        return False
    members = [
        int(dart)
        for dart, candidate in web.bundle_of.items()
        if candidate == int(bundle_id)
    ]
    endpoints = sorted({int(web.vertex_of[dart]) for dart in members})
    if len(members) != 4 or len(endpoints) != 2:
        raise ValueError(f"Bundle {bundle_id} is not a two-strand hourglass.")
    blocks: list[tuple[int, int]] = []
    for endpoint in endpoints:
        cycle = vertex_cycle_ccw(web, endpoint)
        block = tuple(
            dart for dart in cycle if web.bundle_of[dart] == int(bundle_id)
        )
        starts = [dart for dart in block if web.next_ccw[dart] in block]
        if len(block) != 2 or len(starts) != 1:
            raise ValueError(
                f"Bundle {bundle_id} has no oriented two-dart block at {endpoint}."
            )
        first = int(starts[0])
        blocks.append((first, int(web.next_ccw[first])))
    left, right = blocks
    physical_ids = tuple(int(web.physical_edge_of[dart]) for dart in left)
    for index, (a, b) in enumerate(zip(left, right)):
        web.mate[a] = b
        web.mate[b] = a
        web.physical_edge_of[a] = web.physical_edge_of[b] = physical_ids[index]
        web.source_edge_id[a] = web.source_edge_id[b] = None
        web.source_local_strand[a] = web.source_local_strand[b] = None
    if not hourglass_has_paper_half_twist(web, int(bundle_id)):
        raise AssertionError(f"Failed to install GPPSS half-twist on bundle {bundle_id}.")
    return True


def validate_exact_web(web: HalfEdgeWeb) -> None:
    darts = set(web.vertex_of)
    if not darts:
        raise ValueError("An exact web must contain at least one live dart.")
    for name, mapping in (
        ("mate", web.mate),
        ("next_ccw", web.next_ccw),
        ("edge_kind", web.edge_kind),
        ("physical_edge_of", web.physical_edge_of),
        ("bundle_of", web.bundle_of),
    ):
        if set(mapping) != darts:
            raise ValueError(f"{name} is not total on live darts.")
    for dart in darts:
        partner = web.mate[dart]
        if partner == dart or partner not in darts or web.mate.get(partner) != dart:
            raise ValueError(f"mate is not a fixed-point-free involution at dart {dart}.")
        following = web.next_ccw[dart]
        if following not in darts or web.vertex_of[following] != web.vertex_of[dart]:
            raise ValueError(f"next_ccw leaves the vertex cycle at dart {dart}.")
        if web.edge_kind[partner] != web.edge_kind[dart]:
            raise ValueError(f"Mate kind mismatch at dart {dart}.")
        if web.physical_edge_of[partner] != web.physical_edge_of[dart]:
            raise ValueError(f"Mate physical-edge mismatch at dart {dart}.")

    vertices = set(web.color)
    if set(web.boundary_label) != vertices or set(web.tag_after_ccw) != vertices:
        raise ValueError("Vertex metadata maps disagree.")
    visited: set[int] = set()
    labels: list[int] = []
    for vertex in vertices:
        cycle = vertex_cycle_ccw(web, vertex)
        if not cycle:
            raise ValueError(f"Vertex {vertex} has no darts.")
        if visited.intersection(cycle):
            raise ValueError(f"Dart occurs in multiple vertex cycles at vertex {vertex}.")
        visited.update(cycle)
        expected_degree = web.tensor_valence.get(
            vertex,
            1 if web.color[vertex] == VertexColor.BOUNDARY else 4,
        )
        if expected_degree < 1 or expected_degree > 4:
            raise ValueError(f"Vertex {vertex} declares unsupported valence {expected_degree}.")
        if web.color[vertex] == VertexColor.BOUNDARY and expected_degree != 1:
            raise ValueError(f"Boundary vertex {vertex} must have declared valence one.")
        if len(cycle) != expected_degree:
            raise ValueError(f"Vertex {vertex} has degree {len(cycle)}, expected {expected_degree}.")
        tag = web.tag_after_ccw[vertex]
        if web.color[vertex] == VertexColor.BOUNDARY:
            if tag is not None:
                raise ValueError(f"Boundary vertex {vertex} unexpectedly has a tag.")
            label = web.boundary_label[vertex]
            if label is None:
                raise ValueError(f"Boundary vertex {vertex} has no boundary label.")
            labels.append(label)
        elif tag not in cycle:
            raise ValueError(f"Internal tag at vertex {vertex} is not incident to that vertex.")
    if visited != darts:
        raise ValueError("Some live darts do not belong to a vertex cycle.")
    if len(labels) != len(set(labels)):
        raise ValueError("Boundary labels are not unique.")

    physical: dict[int, list[int]] = {}
    bundles: dict[int, list[int]] = {}
    for dart in darts:
        physical.setdefault(web.physical_edge_of[dart], []).append(dart)
        bundle = web.bundle_of[dart]
        if bundle is not None:
            bundles.setdefault(bundle, []).append(dart)
    for physical_id, members in physical.items():
        if len(members) != 2 or web.mate[members[0]] != members[1]:
            raise ValueError(f"Physical edge {physical_id} is not exactly one mate pair.")
        if web.edge_kind[members[0]] == EdgeKind.ORDINARY:
            if any(web.bundle_of[dart] is not None for dart in members):
                raise ValueError(f"Ordinary physical edge {physical_id} belongs to a bundle.")
        elif any(web.bundle_of[dart] is None for dart in members):
            raise ValueError(f"Hourglass physical edge {physical_id} lacks a bundle.")
    if set(web.bundle_frame_root) != set(bundles):
        missing = sorted(set(bundles) - set(web.bundle_frame_root))
        stale = sorted(set(web.bundle_frame_root) - set(bundles))
        raise ValueError(
            f"Hourglass frame table is not exact (missing={missing}, stale={stale})."
        )
    for bundle_id, members in bundles.items():
        if len(members) != 4:
            raise ValueError(f"Hourglass bundle {bundle_id} has {len(members)} darts.")
        if len({web.physical_edge_of[dart] for dart in members}) != 2:
            raise ValueError(f"Hourglass bundle {bundle_id} does not have two physical edges.")
        endpoints = {web.vertex_of[dart] for dart in members}
        if len(endpoints) != 2:
            raise ValueError(f"Hourglass bundle {bundle_id} does not have two endpoints.")
        frames = web.bundle_frame_root.get(bundle_id, {})
        if set(frames) != endpoints:
            raise ValueError(f"Hourglass bundle {bundle_id} has incomplete frame roots.")
        for endpoint, root in frames.items():
            if web.vertex_of.get(root) != endpoint:
                raise ValueError(
                    f"Hourglass bundle {bundle_id} frame root {root} is not at {endpoint}."
                )
        for endpoint in endpoints:
            cycle = vertex_cycle_ccw(web, endpoint)
            positions = [i for i, dart in enumerate(cycle) if web.bundle_of[dart] == bundle_id]
            if len(positions) != 2 or not _cyclic_positions_form_block(positions, len(cycle)):
                raise ValueError(f"Hourglass bundle {bundle_id} is not a local block at {endpoint}.")
        if not hourglass_has_paper_half_twist(web, int(bundle_id)):
            raise ValueError(
                f"Hourglass bundle {bundle_id} reverses its endpoint strand "
                "orders; this is a parallel double edge, not the GPPSS "
                "half-twisted hourglass."
            )
    for dart in darts:
        if dart > web.mate[dart]:
            continue
        u = web.vertex_of[dart]
        v = web.vertex_of[web.mate[dart]]
        cu, cv = web.color[u], web.color[v]
        if cu != VertexColor.BOUNDARY and cv != VertexColor.BOUNDARY and cu == cv:
            raise ValueError(f"Internal edge {dart}-{web.mate[dart]} is not bipartite.")
    if len(web.square_undo_stack) != len(web.square_undo_multipliers):
        raise ValueError("Square undo snapshots and multipliers have different lengths.")
    if any(int(value) not in {-1, 1} for value in web.square_undo_multipliers):
        raise ValueError("Square undo multipliers must be signs.")
    if any(
        snapshot.square_undo_stack or snapshot.square_undo_multipliers
        for snapshot in web.square_undo_stack
    ):
        raise ValueError("Square undo snapshots must not contain nested undo histories.")


def to_legacy_view(web: HalfEdgeWeb) -> Mapping[str, Any]:
    """Return a read-only diagnostic projection; never reconstruct topology from it."""

    rotations = {
        vertex: tuple(
            (
                int(web.edge_kind[dart]),
                web.vertex_of[web.mate[dart]],
                web.bundle_of[dart],
                web.source_local_strand.get(dart),
            )
            for dart in rooted_cycle_ccw(web, vertex)
        )
        for vertex in sorted(web.color)
    }
    return MappingProxyType(
        {
            "rotations": MappingProxyType(rotations),
            "colors": MappingProxyType(dict(web.color)),
            "boundary_labels": MappingProxyType(dict(web.boundary_label)),
        }
    )


def legacy_projection_key(web: HalfEdgeWeb) -> Hashable:
    """Model the information retained by neighbor/slot-based legacy states.

    It intentionally omits the exact ``mate`` permutation between the two
    endpoint-local hourglass strands.  The collision audit uses this key to
    prove when the old representation cannot distinguish two ribbon states.
    """

    rows = []
    for vertex in sorted(web.color):
        rows.append(
            (
                vertex,
                int(web.color[vertex]),
                web.boundary_label[vertex],
                tuple(
                    (
                        int(web.edge_kind[dart]),
                        web.vertex_of[web.mate[dart]],
                        web.bundle_of[dart] is not None,
                        web.source_local_strand.get(dart),
                    )
                    for dart in rooted_cycle_ccw(web, vertex)
                ),
            )
        )
    return tuple(rows)


def _dart_components(web: HalfEdgeWeb) -> list[set[int]]:
    remaining = set(web.vertex_of)
    result: list[set[int]] = []
    while remaining:
        root = min(remaining)
        component = {root}
        queue = deque([root])
        while queue:
            dart = queue.popleft()
            for neighbor in (web.mate[dart], web.next_ccw[dart]):
                if neighbor not in component:
                    component.add(neighbor)
                    queue.append(neighbor)
        remaining.difference_update(component)
        result.append(component)
    return result


def _serialize_component(
    web: HalfEdgeWeb,
    component: set[int],
    root: int,
    *,
    preserve_source_partition: bool = True,
) -> tuple[Any, ...]:
    dart_number = {root: 0}
    order = [root]
    queue = deque([root])
    while queue:
        dart = queue.popleft()
        # This generator order fixes orientation and therefore does not identify reflections.
        for neighbor in (web.mate[dart], web.next_ccw[dart]):
            if neighbor not in component:
                raise ValueError("Component traversal encountered an external dart.")
            if neighbor not in dart_number:
                dart_number[neighbor] = len(dart_number)
                order.append(neighbor)
                queue.append(neighbor)
    if set(order) != component:
        raise ValueError("Canonical traversal did not cover its component.")

    vertex_number: dict[int, int] = {}
    physical_number: dict[int, int] = {}
    bundle_number: dict[int, int] = {}
    source_number: dict[int, int] = {}
    for dart in order:
        vertex_number.setdefault(web.vertex_of[dart], len(vertex_number))
        physical_number.setdefault(web.physical_edge_of[dart], len(physical_number))
        bundle = web.bundle_of[dart]
        if bundle is not None:
            bundle_number.setdefault(bundle, len(bundle_number))
        source = web.source_edge_id.get(dart)
        if source is not None:
            source_number.setdefault(int(source), len(source_number))

    rows = []
    for dart in order:
        vertex = web.vertex_of[dart]
        bundle = web.bundle_of[dart]
        rows.append(
            (
                vertex_number[vertex],
                int(web.color[vertex]),
                web.boundary_label[vertex],
                web.tensor_valence.get(
                    vertex,
                    1 if web.color[vertex] == VertexColor.BOUNDARY else len(vertex_cycle_ccw(web, vertex)),
                ),
                web.tag_after_ccw[vertex] == dart,
                int(web.edge_kind[dart]),
                physical_number[web.physical_edge_of[dart]],
                None if bundle is None else bundle_number[bundle],
                # Relations do not care about the temporary numeric source
                # edge ID, but they do compare source ancestry for equality
                # when two outside darts are spliced.  Preserve that complete
                # equivalence relation with traversal-local canonical labels.
                # Recording only ``is None`` used to merge states whose next
                # Wrench/splice outputs were different.
                (
                    (0, 0)
                    if web.source_edge_id.get(dart) is None
                    else (1, source_number[int(web.source_edge_id[dart])])
                )
                if preserve_source_partition
                else web.source_edge_id.get(dart) is None,
                # A frame root is a gap in the complete endpoint cycle, not
                # necessarily one of this bundle's two strand darts.  Record
                # every bundle whose frame is rooted at this dart; gating this
                # on ``bundle_of[dart]`` silently lost ordinary-dart roots.
                tuple(
                    sorted(
                        bundle_number[candidate]
                        for candidate, roots in web.bundle_frame_root.items()
                        if candidate in bundle_number and roots.get(vertex) == dart
                    )
                ),
                dart_number[web.mate[dart]],
                dart_number[web.next_ccw[dart]],
            )
        )
    return tuple(rows)


def _canonical_web_key(
    web: HalfEdgeWeb,
    *,
    preserve_source_partition: bool,
) -> Hashable:
    """Return a canonical key under the requested source-ancestry contract."""

    serialized = []
    for component in _dart_components(web):
        boundary_roots = [
            dart
            for dart in component
            if web.color[web.vertex_of[dart]] == VertexColor.BOUNDARY
        ]
        if boundary_roots:
            root = min(
                boundary_roots,
                key=lambda dart: int(web.boundary_label[web.vertex_of[dart]] or 0),
            )
            key = _serialize_component(
                web,
                component,
                root,
                preserve_source_partition=preserve_source_partition,
            )
            component_order = (0, int(web.boundary_label[web.vertex_of[root]] or 0))
        else:
            key = min(
                _serialize_component(
                    web,
                    component,
                    root,
                    preserve_source_partition=preserve_source_partition,
                )
                for root in component
            )
            component_order = (1, key)
        serialized.append((component_order, key))
    serialized.sort(key=lambda item: item[0])
    current = tuple(key for _, key in serialized)
    if not web.square_undo_stack:
        return current
    return (
        current,
        (
            "square_undo_stack",
            tuple(
                (
                    int(multiplier),
                    _canonical_web_key(
                        snapshot,
                        preserve_source_partition=preserve_source_partition,
                    ),
                )
                for multiplier, snapshot in zip(
                    web.square_undo_multipliers, web.square_undo_stack
                )
            ),
        ),
    )


def canonical_web_key(web: HalfEdgeWeb) -> Hashable:
    """Canonical key preserving every relation-relevant exact-state field.

    Numeric source-edge IDs are temporary, but equality between those IDs is
    not: Wrench, Figure 43, and splice relations use it to decide whether two
    outside darts descend from the same edge.  The key therefore canonically
    records the complete source-ancestry partition inside each connected
    component.  Relations never compare ancestry across disconnected
    components, so cross-component numeric-ID coincidence is intentionally
    immaterial.
    """

    return _canonical_web_key(web, preserve_source_partition=True)


def canonical_unlabeled_boundary_web_key(web: HalfEdgeWeb) -> Hashable:
    """Canonical exact key after forgetting only boundary-label *names*.

    Local tensor fixtures introduce artificial labels for cut boundary ports.
    Those positive integers name tensor slots; a simultaneous permutation of
    them on every side of a local identity is not a different mathematical
    certificate.  This key retains the boundary vertices, their incidence,
    every internal rooted cyclic order, colors, multiplicities, frames, and
    source-ancestry partition, while canonically treating boundary ports as
    unlabeled.  It is not used for production state consolidation.
    """

    validate_exact_web(web)
    masked = copy.copy(web)
    masked.boundary_label = {
        int(vertex): (
            None
            if web.color[int(vertex)] == VertexColor.BOUNDARY
            else web.boundary_label[int(vertex)]
        )
        for vertex in web.color
    }
    serialized = []
    for component in _dart_components(masked):
        serialized.append(
            min(
                _serialize_component(
                    masked,
                    component,
                    root,
                    preserve_source_partition=True,
                )
                for root in component
            )
        )
    serialized.sort()
    current = tuple(serialized)
    if not web.square_undo_stack:
        return current
    return (
        current,
        (
            "square_undo_stack",
            tuple(
                (
                    int(multiplier),
                    canonical_unlabeled_boundary_web_key(snapshot),
                )
                for multiplier, snapshot in zip(
                    web.square_undo_multipliers,
                    web.square_undo_stack,
                )
            ),
        ),
    )


def legacy_source_presence_web_key(web: HalfEdgeWeb) -> Hashable:
    """Reproduce the v2/v3 checkpoint key's lossy source-presence field.

    This exists only to authenticate historical serialized states after the
    v4 digest contract began preserving source-edge equality classes.  New
    consolidation, computation, and serialization must use
    :func:`canonical_web_key` instead.
    """

    return _canonical_web_key(web, preserve_source_partition=False)


# This alias makes the consolidation contract explicit at call sites.
exact_ribbon_state_key = canonical_web_key


def renamed_copy(
    web: HalfEdgeWeb,
    *,
    vertex_map: Mapping[int, int],
    dart_map: Mapping[int, int],
    physical_map: Mapping[int, int],
    bundle_map: Mapping[int, int],
) -> HalfEdgeWeb:
    def remap_vertex_dict(mapping: Mapping[int, Any]) -> dict[int, Any]:
        return {vertex_map[k]: v for k, v in mapping.items()}

    copied = HalfEdgeWeb(
        vertex_of={dart_map[d]: vertex_map[v] for d, v in web.vertex_of.items()},
        mate={dart_map[d]: dart_map[p] for d, p in web.mate.items()},
        next_ccw={dart_map[d]: dart_map[n] for d, n in web.next_ccw.items()},
        edge_kind={dart_map[d]: kind for d, kind in web.edge_kind.items()},
        physical_edge_of={dart_map[d]: physical_map[p] for d, p in web.physical_edge_of.items()},
        bundle_of={
            dart_map[d]: None if b is None else bundle_map[b]
            for d, b in web.bundle_of.items()
        },
        color=remap_vertex_dict(web.color),
        boundary_label=remap_vertex_dict(web.boundary_label),
        tag_after_ccw={
            vertex_map[v]: None if d is None else dart_map[d]
            for v, d in web.tag_after_ccw.items()
        },
        source_edge_id={dart_map[d]: value for d, value in web.source_edge_id.items()},
        source_local_strand={
            dart_map[d]: value for d, value in web.source_local_strand.items()
        },
        source_xy={vertex_map[v]: xy for v, xy in web.source_xy.items()},
        tensor_valence={
            vertex_map[v]: value for v, value in web.tensor_valence.items()
        },
        bundle_frame_root={
            bundle_map[bundle]: {
                vertex_map[vertex]: dart_map[dart]
                for vertex, dart in roots.items()
            }
            for bundle, roots in web.bundle_frame_root.items()
        },
        # Undo snapshots are independent exact states with their own raw IDs;
        # their canonical keys are ID-free, so they do not use the current
        # state's renaming maps.
        square_undo_stack=tuple(copy.deepcopy(item) for item in web.square_undo_stack),
        square_undo_multipliers=tuple(
            int(value) for value in web.square_undo_multipliers
        ),
    )
    validate_exact_web(copied)
    return copied


def rotate_boundary_labels(web: HalfEdgeWeb, shift: int) -> HalfEdgeWeb:
    result = copy.deepcopy(web)
    labels = [label for label in result.boundary_label.values() if label is not None]
    if not labels:
        return result
    n = max(labels)
    for vertex, label in result.boundary_label.items():
        if label is not None:
            result.boundary_label[vertex] = ((label - 1 + shift) % n) + 1
    validate_exact_web(result)
    return result


def switch_hourglass_mating(
    web: HalfEdgeWeb,
    bundle_id: int,
    *,
    allow_parallel_diagnostic: bool = False,
) -> HalfEdgeWeb:
    """Construct the legacy parallel-mating diagnostic.

    The switched result is not a GPPSS hourglass and is rejected by exact
    production validation.  ``allow_parallel_diagnostic=True`` exists only
    for historical projection/canonical-key audits that need to exhibit the
    information lost by the legacy representation.
    """

    result = copy.deepcopy(web)
    members = [dart for dart, bundle in result.bundle_of.items() if bundle == bundle_id]
    endpoints: dict[int, list[int]] = {}
    for dart in members:
        endpoints.setdefault(result.vertex_of[dart], []).append(dart)
    if len(endpoints) != 2 or any(len(darts) != 2 for darts in endpoints.values()):
        raise ValueError(f"Bundle {bundle_id} is not a two-strand hourglass.")
    endpoint = min(endpoints)
    first, second = sorted(endpoints[endpoint])
    first_partner = result.mate[first]
    second_partner = result.mate[second]
    result.mate[first] = second_partner
    result.mate[second_partner] = first
    result.mate[second] = first_partner
    result.mate[first_partner] = second
    next_physical = max(result.physical_edge_of.values(), default=-1) + 1
    for a, b in ((first, second_partner), (second, first_partner)):
        result.physical_edge_of[a] = result.physical_edge_of[b] = next_physical
        next_physical += 1
    if not allow_parallel_diagnostic:
        validate_exact_web(result)
    return result


def _delete_vertex_pair_and_join_ports(
    web: HalfEdgeWeb,
    white: int,
    black: int,
    pairings: Iterable[tuple[int, int]],
) -> HalfEdgeWeb:
    pairings = tuple(pairings)
    result = copy.deepcopy(web)
    local_darts = {
        dart for dart, vertex in result.vertex_of.items() if vertex in {white, black}
    }
    outside_darts = {result.mate[dart] for dart in local_darts if result.mate[dart] not in local_darts}
    expected_outside = {dart for pair in pairings for dart in pair}
    if outside_darts != expected_outside:
        raise ValueError("Local rewrite ports do not equal the preserved outside darts.")

    for mapping in (
        result.vertex_of,
        result.mate,
        result.next_ccw,
        result.edge_kind,
        result.physical_edge_of,
        result.bundle_of,
        result.source_edge_id,
        result.source_local_strand,
    ):
        for dart in local_darts:
            mapping.pop(dart, None)
    for vertex in (white, black):
        result.color.pop(vertex, None)
        result.boundary_label.pop(vertex, None)
        result.tag_after_ccw.pop(vertex, None)
        result.source_xy.pop(vertex, None)
        result.tensor_valence.pop(vertex, None)

    next_physical = max(result.physical_edge_of.values(), default=-1) + 1
    for a, b in pairings:
        source_ids = {result.source_edge_id.get(a), result.source_edge_id.get(b)}
        inherited_source = (
            next(iter(source_ids))
            if len(source_ids) == 1 and None not in source_ids
            else None
        )
        result.mate[a] = b
        result.mate[b] = a
        result.edge_kind[a] = result.edge_kind[b] = EdgeKind.ORDINARY
        result.physical_edge_of[a] = result.physical_edge_of[b] = next_physical
        result.bundle_of[a] = result.bundle_of[b] = None
        result.source_edge_id[a] = result.source_edge_id[b] = inherited_source
        result.source_local_strand[a] = result.source_local_strand[b] = None
        next_physical += 1
    refresh_bundle_frames(result)
    validate_exact_web(result)
    return result


def _permutation_sign_3(permutation: tuple[int, int, int]) -> int:
    inversions = sum(
        permutation[i] > permutation[j]
        for i in range(3)
        for j in range(i + 1, 3)
    )
    return -1 if inversions % 2 else 1


def _relative_order_permutation_3(
    paper_order: tuple[int, int, int],
    engine_order: tuple[int, int, int],
) -> tuple[tuple[int, int, int], int]:
    """Compare two explicit three-port orders without a stored sign."""

    if len(set(paper_order)) != 3 or set(paper_order) != set(engine_order):
        raise ValueError("Double Trident boundary orders are not bijective.")
    positions = {port: index for index, port in enumerate(paper_order)}
    permutation = tuple(positions[port] for port in engine_order)
    return permutation, _permutation_sign_3(permutation)  # type: ignore[arg-type]


def apply_exact_double_trident(
    web: HalfEdgeWeb,
    white: int,
    black: int,
) -> tuple[ExactDoubleTridentBranch, ...]:
    """Expand one tagged white-black edge into its six exact dart splices.

    This mirrors the production Double Trident convention without using
    coordinates.  The outside ports are read immediately after the central
    dart in each rooted counterclockwise cycle.  Paper and tag-transport
    coefficients remain separate so audits can identify which one diverges.
    """

    if web.color.get(white) != VertexColor.WHITE:
        raise ValueError(f"Double Trident white endpoint {white} is not white.")
    if web.color.get(black) != VertexColor.BLACK:
        raise ValueError(f"Double Trident black endpoint {black} is not black.")

    def central_and_ports(center: int, opposite: int) -> tuple[int, int, tuple[int, int, int]]:
        cycle = rooted_cycle_ccw(web, center)
        central = [
            dart
            for dart in cycle
            if web.vertex_of[web.mate[dart]] == opposite
            and web.edge_kind[dart] == EdgeKind.ORDINARY
            and web.bundle_of[dart] is None
        ]
        if len(cycle) != 4 or len(central) != 1:
            raise ValueError(
                f"Double Trident endpoint {center} does not have one ordinary central dart."
            )
        central_dart = central[0]
        slot = cycle.index(central_dart)
        rotated = cycle[slot + 1 :] + cycle[:slot]
        ports = tuple(web.mate[dart] for dart in rotated if dart != central_dart)
        if len(ports) != 3:
            raise ValueError(f"Double Trident endpoint {center} does not have three outside ports.")
        return central_dart, slot, ports

    white_central, white_slot, white_ports = central_and_ports(white, black)
    black_central, black_slot, black_ports = central_and_ports(black, white)
    if web.mate[white_central] != black_central:
        raise ValueError("The selected Double Trident central darts are not mates.")

    # ``paper_coefficient = -sgn(permutation)`` below retains the printed
    # formal coefficient as provenance.  Transport the two live cyclic tags
    # to the displayed central-edge roots using Lemma 2.5 at *both* endpoints.
    endpoint_tag_transport = int(
        paper_tag_transport_sign(web, int(white), int(white_central), r=4)
        * paper_tag_transport_sign(web, int(black), int(black_central), r=4)
    )
    # The three ports at the two ends of the displayed relation are read in
    # opposite boundary orientations.  Our exact state stores both endpoint
    # cycles counterclockwise, so identifying those two rooted port triples
    # requires one odd reversal.  This is a cyclic-order comparison, not a
    # sign attached to the color or to the number of black vertices.
    boundary_engine_order = tuple(int(port) for port in black_ports)
    boundary_paper_order = tuple(reversed(boundary_engine_order))
    boundary_order_permutation, boundary_order_multiplier = (
        _relative_order_permutation_3(
            boundary_paper_order,
            boundary_engine_order,
        )
    )
    tag_transport = int(endpoint_tag_transport * boundary_order_multiplier)
    permutations = (
        (1, 2, 3),
        (1, 3, 2),
        (2, 1, 3),
        (2, 3, 1),
        (3, 1, 2),
        (3, 2, 1),
    )
    branches = []
    for permutation in permutations:
        pairings = tuple(
            (white_ports[index], black_ports[output - 1])
            for index, output in enumerate(permutation)
        )
        branches.append(
            ExactDoubleTridentBranch(
                permutation=permutation,
                paper_coefficient=-_permutation_sign_3(permutation),
                endpoint_tag_transport_multiplier=endpoint_tag_transport,
                boundary_order_multiplier=boundary_order_multiplier,
                tag_transport_multiplier=tag_transport,
                boundary_paper_order=boundary_paper_order,
                boundary_engine_order=boundary_engine_order,
                boundary_order_permutation=boundary_order_permutation,
                web=_delete_vertex_pair_and_join_ports(
                    web,
                    white,
                    black,
                    pairings,
                ),
                port_pairing=tuple(
                    (f"W{index}", f"B{output - 1}")
                    for index, output in enumerate(permutation)
                ),
            )
        )
    return tuple(branches)


def apply_exact_wrench(web: HalfEdgeWeb, bundle_id: int) -> tuple[ExactWrenchBranch, ExactWrenchBranch]:
    """Apply Figure 42 with ports read from the exact rooted local cycles."""

    members = [dart for dart, bundle in web.bundle_of.items() if bundle == bundle_id]
    endpoints = {web.vertex_of[dart] for dart in members}
    if len(endpoints) != 2:
        raise ValueError(f"Bundle {bundle_id} does not have two endpoints.")
    white = next((v for v in endpoints if web.color[v] == VertexColor.WHITE), None)
    black = next((v for v in endpoints if web.color[v] == VertexColor.BLACK), None)
    if white is None or black is None:
        raise ValueError(f"Bundle {bundle_id} is not between one white and one black vertex.")

    def outside_ports(vertex: int) -> tuple[int, int]:
        local = [dart for dart in rooted_cycle_ccw(web, vertex) if web.bundle_of[dart] != bundle_id]
        if len(local) != 2:
            raise ValueError(f"Wrench endpoint {vertex} does not have two outside ports.")
        kinds = {web.edge_kind[dart] for dart in local}
        if kinds == {EdgeKind.ORDINARY}:
            if any(web.bundle_of[dart] is not None for dart in local):
                raise ValueError(f"Wrench endpoint {vertex} has malformed ordinary ports.")
        elif kinds == {EdgeKind.HOURGLASS_STRAND}:
            adjacent = {web.bundle_of[dart] for dart in local}
            if len(adjacent) != 1 or None in adjacent or bundle_id in adjacent:
                raise ValueError(
                    f"Wrench endpoint {vertex} does not expose one complete adjacent hourglass."
                )
            outer = {web.vertex_of[web.mate[dart]] for dart in local}
            if len(outer) != 1:
                raise ValueError(
                    f"Wrench endpoint {vertex} exposes hourglass strands with different endpoints."
                )
            # These two outside arms are themselves an ordered hourglass
            # strand pair.  Read their order from that bundle's persistent
            # frame, not from the selected Wrench bundle or the live tag.
            adjacent_bundle = int(next(iter(adjacent)))
            adjacent_root = web.bundle_frame_root[adjacent_bundle][vertex]
            cycle = vertex_cycle_ccw(web, vertex)
            position = cycle.index(adjacent_root)
            adjacent_cycle = cycle[position:] + cycle[:position]
            local = [
                dart
                for dart in adjacent_cycle
                if web.bundle_of[dart] == adjacent_bundle
            ]
        else:
            raise ValueError(
                f"Wrench endpoint {vertex} mixes ordinary and hourglass outside ports."
            )
        return web.mate[local[0]], web.mate[local[1]]

    w0, w1 = outside_ports(white)
    b0, b1 = outside_ports(black)
    # The two endpoint cycles are both stored counterclockwise, but they face
    # one another in Figure 42.  Consequently equal list indices describe the
    # geometric crossing, while opposite indices describe the geometric
    # parallel smoothing.  The previous names were reversed and turned the
    # paper identity into its negative even though the two output topologies
    # themselves were correct.
    crossing_pairs = ((w0, b0), (w1, b1))
    parallel_pairs = ((w0, b1), (w1, b0))
    crossing = ExactWrenchBranch(
        name="crossing",
        formal_coefficient=1,
        web=_delete_vertex_pair_and_join_ports(web, white, black, crossing_pairs),
        port_pairing=(("W0", "B0"), ("W1", "B1")),
    )
    parallel = ExactWrenchBranch(
        name="parallel",
        formal_coefficient=-1,
        web=_delete_vertex_pair_and_join_ports(web, white, black, parallel_pairs),
        port_pairing=(("W0", "B1"), ("W1", "B0")),
    )
    return crossing, parallel


def bundle_ids(web: HalfEdgeWeb) -> tuple[int, ...]:
    return tuple(sorted({bundle for bundle in web.bundle_of.values() if bundle is not None}))


def weighted_wrench_key(branches: Iterable[ExactWrenchBranch]) -> tuple[tuple[int, Hashable], ...]:
    return tuple(sorted((branch.formal_coefficient, canonical_web_key(branch.web)) for branch in branches))
