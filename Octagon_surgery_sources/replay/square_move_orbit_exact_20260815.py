#!/usr/bin/env python3
"""Exact Figure 2 square moves and square-orbit exploration for SL4 webs.

The four square moves in GPPSS Figure 2 are instances of one local rewrite.
An ordinary facial square has, at each corner, either

* one outward 2-hourglass, or
* two outward ordinary edges.

The move complements those four corner types.  This module performs that
rewrite directly on :class:`halfedge_web_20260812.HalfEdgeWeb`: cyclic orders,
individual hourglass strand mates, boundary labels, and colors are retained.
No screen coordinates or unordered adjacency lists are used to reconstruct
the result.

This is an audit/orbit layer.  It deliberately does not alter the production
pairing evaluator.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Hashable, Iterable, Mapping, Sequence

from halfedge_web_20260812 import (
    EdgeKind,
    HalfEdgeWeb,
    VertexColor,
    follow_trip_exact,
    load_halfedge_web,
    refresh_bundle_frames,
    validate_exact_web,
    vertex_cycle_ccw,
)


@dataclass(frozen=True)
class ExactSquareMove:
    """One oriented facial square and its four external corner types."""

    cycle: tuple[int, int, int, int]
    facial_turn: int
    corner_kinds: tuple[str, str, str, str]
    side_physical_edges: tuple[int, int, int, int] = ()

    @property
    def hourglass_count(self) -> int:
        return self.corner_kinds.count("H")


@dataclass(frozen=True)
class SquareOrbitResult:
    state_count: int
    edge_count: int
    maximum_depth: int
    benzene_found: bool
    benzene_depth: int | None
    benzene_cycles: tuple[tuple[int, ...], ...]
    truncated: bool
    trip_invariant_failures: int


@dataclass(frozen=True)
class _AbstractEdge:
    kind: str
    endpoints: tuple[int, int]
    darts_by_vertex: Mapping[int, tuple[int, ...]]
    physical_id: int | None = None
    bundle_id: int | None = None


def _abstract_edges(web: HalfEdgeWeb) -> tuple[_AbstractEdge, ...]:
    ordinary: dict[int, list[int]] = {}
    bundles: dict[int, list[int]] = {}
    for dart in web.vertex_of:
        if web.edge_kind[dart] == EdgeKind.ORDINARY:
            ordinary.setdefault(web.physical_edge_of[dart], []).append(dart)
        else:
            bundle = web.bundle_of[dart]
            if bundle is None:
                raise ValueError(f"Hourglass dart {dart} has no bundle.")
            bundles.setdefault(bundle, []).append(dart)

    result: list[_AbstractEdge] = []
    for physical_id, darts in ordinary.items():
        if len(darts) != 2:
            raise ValueError(f"Ordinary physical edge {physical_id} has {len(darts)} darts.")
        u, v = (web.vertex_of[dart] for dart in darts)
        result.append(
            _AbstractEdge(
                kind="O",
                endpoints=(u, v),
                darts_by_vertex={u: (darts[0],), v: (darts[1],)},
                physical_id=physical_id,
            )
        )
    for bundle_id, darts in bundles.items():
        by_vertex: dict[int, list[int]] = {}
        for dart in darts:
            by_vertex.setdefault(web.vertex_of[dart], []).append(dart)
        if len(by_vertex) != 2 or any(len(items) != 2 for items in by_vertex.values()):
            raise ValueError(f"Hourglass bundle {bundle_id} has invalid endpoints.")
        u, v = sorted(by_vertex)
        result.append(
            _AbstractEdge(
                kind="H",
                endpoints=(u, v),
                darts_by_vertex={u: tuple(by_vertex[u]), v: tuple(by_vertex[v])},
                bundle_id=bundle_id,
            )
        )
    return tuple(result)


def _edge_lookup(web: HalfEdgeWeb) -> dict[frozenset[int], _AbstractEdge]:
    lookup: dict[frozenset[int], _AbstractEdge] = {}
    for edge in _abstract_edges(web):
        key = frozenset(edge.endpoints)
        if key in lookup:
            raise ValueError(f"Parallel abstract edges at {sorted(key)} are unsupported here.")
        lookup[key] = edge
    return lookup


def _canonical_cycle(cycle: Sequence[int]) -> tuple[int, ...]:
    values = tuple(int(vertex) for vertex in cycle)
    variants = []
    for oriented in (values, tuple(reversed(values))):
        variants.extend(oriented[offset:] + oriented[:offset] for offset in range(len(values)))
    return min(variants)


def exact_square_move_key(
    move: ExactSquareMove,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Identify one exact facial square, including parallel side choices."""

    return tuple(int(value) for value in move.cycle), tuple(
        int(value) for value in move.side_physical_edges
    )


def _ordinary_facial_four_cycles(
    web: HalfEdgeWeb,
) -> tuple[tuple[tuple[int, int, int, int], int, tuple[int, int, int, int]], ...]:
    """Enumerate facial ordinary four-cycles by exact darts.

    Vertex-neighbor adjacency is insufficient when two ordinary physical
    edges share endpoints.  Following one fixed left/right ribbon turn keeps
    the physical side identity and therefore distinguishes a generated square
    side from an unrelated parallel edge.
    """

    candidates: dict[
        tuple[int, ...],
        list[tuple[tuple[int, int, int, int], int, tuple[int, int, int, int]]],
    ] = {}
    for starting in sorted(web.vertex_of):
        if web.edge_kind[starting] != EdgeKind.ORDINARY:
            continue
        if web.color[web.vertex_of[starting]] == VertexColor.BOUNDARY:
            continue
        for turn in (1, -1):
            current = int(starting)
            vertices: list[int] = []
            physical_edges: list[int] = []
            valid = True
            for _step in range(4):
                vertex = int(web.vertex_of[current])
                following_vertex = int(web.vertex_of[web.mate[current]])
                if (
                    web.color.get(vertex) == VertexColor.BOUNDARY
                    or web.color.get(following_vertex) == VertexColor.BOUNDARY
                    or web.edge_kind[current] != EdgeKind.ORDINARY
                ):
                    valid = False
                    break
                vertices.append(vertex)
                physical_edges.append(int(web.physical_edge_of[current]))
                incoming = int(web.mate[current])
                local = vertex_cycle_ccw(web, following_vertex)
                position = local.index(incoming)
                current = int(local[(position + turn) % len(local)])
            if (
                not valid
                or current != int(starting)
                or len(set(vertices)) != 4
                or len(set(physical_edges)) != 4
            ):
                continue
            record = (
                tuple(vertices),
                int(turn),
                tuple(physical_edges),
            )
            candidates.setdefault(tuple(sorted(physical_edges)), []).append(record)
    return tuple(
        min(records, key=lambda item: (item[0], item[2], item[1]))
        for _key, records in sorted(candidates.items())
    )


def _dart_to_neighbor(web: HalfEdgeWeb, vertex: int, neighbor: int) -> int:
    matches = [
        dart
        for dart in vertex_cycle_ccw(web, vertex)
        if web.vertex_of[web.mate[dart]] == neighbor
        and web.edge_kind[dart] == EdgeKind.ORDINARY
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one ordinary dart from {vertex} to {neighbor}, found {matches}."
        )
    return matches[0]


def _facial_turn(web: HalfEdgeWeb, cycle: Sequence[int]) -> int | None:
    turns = []
    for index, vertex in enumerate(cycle):
        previous = cycle[(index - 1) % len(cycle)]
        following = cycle[(index + 1) % len(cycle)]
        local = vertex_cycle_ccw(web, vertex)
        incoming = _dart_to_neighbor(web, vertex, previous)
        outgoing = _dart_to_neighbor(web, vertex, following)
        step = (local.index(outgoing) - local.index(incoming)) % len(local)
        if step == 1:
            turns.append(1)
        elif step == len(local) - 1:
            turns.append(-1)
        else:
            return None
    return turns[0] if len(set(turns)) == 1 else None


def detect_exact_square_moves(web: HalfEdgeWeb) -> tuple[ExactSquareMove, ...]:
    """Find every GPPSS Figure 2 square move in an exact ribbon state."""

    validate_exact_web(web)
    matches: list[ExactSquareMove] = []
    for cycle, turn, side_physical_edges in _ordinary_facial_four_cycles(web):

        colors = tuple(web.color[vertex] for vertex in cycle)
        if colors not in {
            (VertexColor.BLACK, VertexColor.WHITE, VertexColor.BLACK, VertexColor.WHITE),
            (VertexColor.WHITE, VertexColor.BLACK, VertexColor.WHITE, VertexColor.BLACK),
        }:
            continue

        corner_kinds: list[str] = []
        hourglass_outers: list[int] = []
        valid = True
        for index, vertex in enumerate(cycle):
            previous_physical = side_physical_edges[(index - 1) % 4]
            following_physical = side_physical_edges[index]
            square_darts = {
                dart
                for dart in vertex_cycle_ccw(web, vertex)
                if int(web.physical_edge_of[dart])
                in {int(previous_physical), int(following_physical)}
                and web.edge_kind[dart] == EdgeKind.ORDINARY
            }
            if len(square_darts) != 2:
                valid = False
                break
            local = vertex_cycle_ccw(web, vertex)
            outside = [dart for dart in local if dart not in square_darts]
            if len(outside) != 2:
                valid = False
                break
            outside_kinds = {web.edge_kind[dart] for dart in outside}
            if outside_kinds == {EdgeKind.ORDINARY}:
                if any(web.bundle_of[dart] is not None for dart in outside):
                    valid = False
                    break
                corner_kinds.append("O")
                continue
            if outside_kinds != {EdgeKind.HOURGLASS_STRAND}:
                valid = False
                break
            bundles = {web.bundle_of[dart] for dart in outside}
            if len(bundles) != 1 or None in bundles:
                valid = False
                break
            outer = web.vertex_of[web.mate[outside[0]]]
            if (
                outer in cycle
                or web.color.get(outer) == VertexColor.BOUNDARY
                or any(web.vertex_of[web.mate[dart]] != outer for dart in outside)
            ):
                valid = False
                break
            outer_cycle = vertex_cycle_ccw(web, outer)
            bundle = next(iter(bundles))
            outer_other = [dart for dart in outer_cycle if web.bundle_of[dart] != bundle]
            if len(outer_other) != 2 or any(
                web.edge_kind[dart] != EdgeKind.ORDINARY for dart in outer_other
            ):
                valid = False
                break
            corner_kinds.append("H")
            hourglass_outers.append(outer)

        if not valid or len(hourglass_outers) != len(set(hourglass_outers)):
            continue
        matches.append(
            ExactSquareMove(
                cycle=tuple(cycle),
                facial_turn=int(turn),
                corner_kinds=tuple(corner_kinds),
                side_physical_edges=tuple(side_physical_edges),
            )
        )

    unique: dict[tuple[tuple[int, ...], tuple[int, ...]], ExactSquareMove] = {}
    for match in matches:
        unique[exact_square_move_key(match)] = match
    return tuple(unique[key] for key in sorted(unique))


def _opposite_color(color: VertexColor) -> VertexColor:
    if color == VertexColor.BLACK:
        return VertexColor.WHITE
    if color == VertexColor.WHITE:
        return VertexColor.BLACK
    raise ValueError("Square corners must be internal black or white vertices.")


def _ordered_two_dart_block(
    web: HalfEdgeWeb,
    vertex: int,
    members: Iterable[int],
) -> tuple[int, int]:
    """Order a two-dart block by the stored counterclockwise successor map."""

    wanted = set(members)
    if len(wanted) != 2:
        raise ValueError(f"Expected a two-dart block at {vertex}, found {wanted}.")
    starts = [dart for dart in wanted if web.next_ccw[dart] in wanted]
    if len(starts) != 1:
        raise ValueError(f"Darts {wanted} are not one oriented block at vertex {vertex}.")
    first = starts[0]
    return first, web.next_ccw[first]


def _repair_collapsed_square_face_tag(
    web: HalfEdgeWeb, vertex: int
) -> None:
    """Move a tag out of the interior of a newly created hourglass block.

    At an ordinary corner, the square-face gap lies between the two square
    sides.  The Figure-2 rewrite turns those two slots into the two strands of
    one multiplicity-two edge, where that same drawn gap is no longer a legal
    abstract-web tag position.  Collapse it to the preceding boundary of the
    new block.  The alternative boundary differs by moving across a
    multiplicity-two edge and hence has the same SL4 tensor sign by GPPSS
    Lemma 2.5.

    This is tag transport through the local rewrite, not an intrinsic
    base-face reconstruction.  Definition 6.3 only supplies the latter for
    fully reduced graphs, whereas certified reduction intermediates need not
    satisfy that hypothesis.
    """

    root = web.tag_after_ccw.get(int(vertex))
    if root is None:
        return
    cycle = vertex_cycle_ccw(web, int(vertex))
    position = cycle.index(int(root))
    bundle = web.bundle_of[int(root)]
    previous = cycle[(position - 1) % len(cycle)]
    if bundle is None or web.bundle_of[previous] != bundle:
        return
    while web.bundle_of[cycle[(position - 1) % len(cycle)]] == bundle:
        position = (position - 1) % len(cycle)
    web.tag_after_ccw[int(vertex)] = int(cycle[position])


def apply_exact_square_move(web: HalfEdgeWeb, match: ExactSquareMove) -> HalfEdgeWeb:
    """Apply one square move with exact cyclic-order and strand transport."""

    detected = detect_exact_square_moves(web)
    available = {exact_square_move_key(item): item for item in detected}
    key = exact_square_move_key(match)
    if not match.side_physical_edges:
        compatible = [item for item in detected if item.cycle == match.cycle]
        if len(compatible) == 1:
            key = exact_square_move_key(compatible[0])
    if key not in available:
        raise ValueError(f"The requested square {match.cycle} is not currently applicable.")
    match = available[key]
    cycle = match.cycle

    old_cycles = {vertex: vertex_cycle_ccw(web, vertex) for vertex in web.color}
    old_tag = dict(web.tag_after_ccw)
    square_darts: dict[int, tuple[int, int]] = {}
    corner_kind: dict[int, str] = {}
    hourglass_bundle: dict[int, int] = {}
    hourglass_outer: dict[int, int] = {}
    hourglass_darts: dict[int, tuple[int, int]] = {}

    for index, vertex in enumerate(cycle):
        previous_physical = match.side_physical_edges[(index - 1) % 4]
        following_physical = match.side_physical_edges[index]
        unordered_pair = tuple(
            dart
            for dart in vertex_cycle_ccw(web, vertex)
            if web.edge_kind[dart] == EdgeKind.ORDINARY
            and int(web.physical_edge_of[dart])
            in {int(previous_physical), int(following_physical)}
        )
        if len(unordered_pair) != 2:
            raise ValueError(
                f"Square {match.cycle} lost an exact physical side at {vertex}."
            )
        pair = _ordered_two_dart_block(web, vertex, unordered_pair)
        square_darts[vertex] = pair
        outside = tuple(dart for dart in old_cycles[vertex] if dart not in pair)
        if all(web.edge_kind[dart] == EdgeKind.ORDINARY for dart in outside):
            corner_kind[vertex] = "O"
        else:
            corner_kind[vertex] = "H"
            bundle = web.bundle_of[outside[0]]
            if bundle is None or any(web.bundle_of[dart] != bundle for dart in outside):
                raise ValueError(f"Corner {vertex} has inconsistent hourglass darts.")
            outer = web.vertex_of[web.mate[outside[0]]]
            hourglass_bundle[vertex] = bundle
            hourglass_outer[vertex] = outer
            hourglass_darts[vertex] = outside

    next_vertex = max(web.color, default=-1) + 1
    next_dart = max(web.vertex_of, default=-1) + 1
    next_physical = max(web.physical_edge_of.values(), default=-1) + 1
    live_bundles = [bundle for bundle in web.bundle_of.values() if bundle is not None]
    next_bundle = max(live_bundles, default=-1) + 1

    def new_dart() -> int:
        nonlocal next_dart
        result = next_dart
        next_dart += 1
        return result

    new_corner: dict[int, int] = {}
    new_inner_for_ordinary: dict[int, int] = {}
    removed_vertices = {vertex for vertex in cycle if corner_kind[vertex] == "H"}
    for vertex in cycle:
        if corner_kind[vertex] == "H":
            new_corner[vertex] = hourglass_outer[vertex]
        else:
            new_inner_for_ordinary[vertex] = next_vertex
            new_corner[vertex] = next_vertex
            next_vertex += 1

    remove_darts: set[int] = set()
    for vertex in cycle:
        remove_darts.update(square_darts[vertex])
        if corner_kind[vertex] == "H":
            bundle = hourglass_bundle[vertex]
            remove_darts.update(
                dart for dart, candidate in web.bundle_of.items() if candidate == bundle
            )

    replacement_at_retained: dict[int, int] = {}
    new_square_dart: dict[int, int] = {}
    new_outer_h_dart: dict[int, int] = {}
    new_inner_h_dart: dict[int, int] = {}

    # Allocate the new square endpoint for every old square endpoint.
    for vertex in cycle:
        for old_side in square_darts[vertex]:
            new_square_dart[old_side] = new_dart()

    # Transport old side identity through a removed hourglass, or turn the old
    # side slot into the outer endpoint of a newly created hourglass.
    for index, vertex in enumerate(cycle):
        if corner_kind[vertex] == "H":
            previous_physical = int(match.side_physical_edges[(index - 1) % 4])
            following_physical = int(match.side_physical_edges[index])
            previous_side = next(
                dart
                for dart in square_darts[vertex]
                if int(web.physical_edge_of[dart]) == previous_physical
            )
            following_side = next(
                dart
                for dart in square_darts[vertex]
                if int(web.physical_edge_of[dart]) == following_physical
            )
            outer = int(hourglass_outer[vertex])
            outer_cycle = old_cycles[outer]
            outer_slots = tuple(
                int(web.mate[inner_h]) for inner_h in hourglass_darts[vertex]
            )
            assignments = []
            for previous_slot, following_slot in (
                outer_slots,
                tuple(reversed(outer_slots)),
            ):
                step = (
                    outer_cycle.index(following_slot)
                    - outer_cycle.index(previous_slot)
                ) % len(outer_cycle)
                if step == (1 if match.facial_turn == 1 else len(outer_cycle) - 1):
                    assignments.append((previous_slot, following_slot))
            if len(assignments) != 1:
                raise ValueError(
                    "Consumed hourglass does not induce one facial cyclic-order "
                    f"transport at square corner {vertex}: {assignments}."
                )
            previous_slot, following_slot = assignments[0]
            replacement_at_retained[previous_slot] = new_square_dart[previous_side]
            replacement_at_retained[following_slot] = new_square_dart[following_side]
        else:
            for old_side in square_darts[vertex]:
                outer_h = new_dart()
                inner_h = new_dart()
                new_outer_h_dart[old_side] = outer_h
                new_inner_h_dart[old_side] = inner_h
                replacement_at_retained[old_side] = outer_h

    result = copy.deepcopy(web)
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
        for dart in remove_darts:
            mapping.pop(dart, None)
    for vertex in removed_vertices:
        result.color.pop(vertex, None)
        result.boundary_label.pop(vertex, None)
        result.tag_after_ccw.pop(vertex, None)
        result.source_xy.pop(vertex, None)
        result.tensor_valence.pop(vertex, None)

    # Install new vertices and vertex ownership.
    for old_corner, new_vertex in new_inner_for_ordinary.items():
        result.color[new_vertex] = _opposite_color(web.color[old_corner])
        result.boundary_label[new_vertex] = None
        result.tensor_valence[new_vertex] = 4
        result.source_xy.pop(new_vertex, None)
        result.tag_after_ccw[new_vertex] = new_square_dart[square_darts[old_corner][0]]

    for old_corner in cycle:
        target = new_corner[old_corner]
        for old_side in square_darts[old_corner]:
            dart = new_square_dart[old_side]
            result.vertex_of[dart] = target
            result.edge_kind[dart] = EdgeKind.ORDINARY
            result.bundle_of[dart] = None
            result.source_edge_id[dart] = None
            result.source_local_strand[dart] = None

    # Pair endpoints of each transported square side.
    paired_old_sides: set[int] = set()
    for vertex in cycle:
        for old_side in square_darts[vertex]:
            if old_side in paired_old_sides:
                continue
            partner = web.mate[old_side]
            if partner not in new_square_dart:
                raise ValueError("A detected square side leaves the local four-cycle.")
            a, b = new_square_dart[old_side], new_square_dart[partner]
            result.mate[a] = b
            result.mate[b] = a
            result.physical_edge_of[a] = result.physical_edge_of[b] = next_physical
            next_physical += 1
            paired_old_sides.update({old_side, partner})

    # Create each new outward hourglass.  The reversed inner block below and
    # the side-identity mating here encode the required strand crossing.
    for old_corner, new_vertex in new_inner_for_ordinary.items():
        bundle = next_bundle
        next_bundle += 1
        for old_side in square_darts[old_corner]:
            outer_h = new_outer_h_dart[old_side]
            inner_h = new_inner_h_dart[old_side]
            result.vertex_of[outer_h] = old_corner
            result.vertex_of[inner_h] = new_vertex
            result.mate[outer_h] = inner_h
            result.mate[inner_h] = outer_h
            result.edge_kind[outer_h] = result.edge_kind[inner_h] = EdgeKind.HOURGLASS_STRAND
            result.physical_edge_of[outer_h] = result.physical_edge_of[inner_h] = next_physical
            next_physical += 1
            result.bundle_of[outer_h] = result.bundle_of[inner_h] = bundle
            result.source_edge_id[outer_h] = result.source_edge_id[inner_h] = None
            result.source_local_strand[outer_h] = result.source_local_strand[inner_h] = None

    # Rebuild exact vertex cycles.  Existing slots are replaced in place.
    rebuilt_cycles: dict[int, tuple[int, ...]] = {}
    for vertex, old_cycle in old_cycles.items():
        if vertex in removed_vertices:
            continue
        rebuilt = tuple(
            replacement_at_retained.get(dart, dart)
            for dart in old_cycle
            if dart not in remove_darts or dart in replacement_at_retained
        )
        rebuilt_cycles[vertex] = rebuilt
        tag = old_tag[vertex]
        if tag in replacement_at_retained:
            result.tag_after_ccw[vertex] = replacement_at_retained[tag]

    for old_corner, new_vertex in new_inner_for_ordinary.items():
        first, second = square_darts[old_corner]
        rebuilt_cycles[new_vertex] = (
            new_square_dart[first],
            new_square_dart[second],
            new_inner_h_dart[first],
            new_inner_h_dart[second],
        )

    result.next_ccw.clear()
    for vertex, local in rebuilt_cycles.items():
        if len(local) != (1 if result.color[vertex] == VertexColor.BOUNDARY else 4):
            raise ValueError(f"Rebuilt vertex {vertex} has invalid cycle {local}.")
        for current, following in zip(local, local[1:] + local[:1]):
            result.next_ccw[current] = following

    # A face-sector tag at an O-corner can land between the two strands of the
    # newly created hourglass.  Such a strand-frame gap is not a legal tag of
    # the abstract multiplicity-two edge; transport it to a block boundary.
    for old_corner in new_inner_for_ordinary:
        _repair_collapsed_square_face_tag(result, int(old_corner))

    # A square rewrite can replace a surviving endpoint dart in place.  Move
    # any stored hourglass frame root through that exact dart replacement;
    # frames belonging to consumed bundles are removed and newly created
    # bundles receive roots only after the new cyclic orders are complete.
    for roots in result.bundle_frame_root.values():
        for vertex, root in tuple(roots.items()):
            if root in replacement_at_retained:
                roots[vertex] = replacement_at_retained[root]

    refresh_bundle_frames(result)
    validate_exact_web(result)
    return result


def _dart_components(web: HalfEdgeWeb) -> list[set[int]]:
    remaining = set(web.vertex_of)
    result = []
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


def _serialize_untagged_component(
    web: HalfEdgeWeb,
    component: set[int],
    root: int,
) -> tuple[Any, ...]:
    dart_number = {root: 0}
    order = [root]
    queue = deque([root])
    while queue:
        dart = queue.popleft()
        for neighbor in (web.mate[dart], web.next_ccw[dart]):
            if neighbor not in dart_number:
                dart_number[neighbor] = len(dart_number)
                order.append(neighbor)
                queue.append(neighbor)
    if set(order) != component:
        raise ValueError("Canonical traversal did not cover the component.")

    vertex_number: dict[int, int] = {}
    physical_number: dict[int, int] = {}
    bundle_number: dict[int, int] = {}
    for dart in order:
        vertex_number.setdefault(web.vertex_of[dart], len(vertex_number))
        physical_number.setdefault(web.physical_edge_of[dart], len(physical_number))
        bundle = web.bundle_of[dart]
        if bundle is not None:
            bundle_number.setdefault(bundle, len(bundle_number))

    return tuple(
        (
            vertex_number[web.vertex_of[dart]],
            int(web.color[web.vertex_of[dart]]),
            web.boundary_label[web.vertex_of[dart]],
            int(web.edge_kind[dart]),
            physical_number[web.physical_edge_of[dart]],
            None if web.bundle_of[dart] is None else bundle_number[web.bundle_of[dart]],
            dart_number[web.mate[dart]],
            dart_number[web.next_ccw[dart]],
        )
        for dart in order
    )


def canonical_untagged_web_key(web: HalfEdgeWeb) -> Hashable:
    """Boundary-fixed colored ribbon key retaining exact strand mating, not tags."""

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
            key = _serialize_untagged_component(web, component, root)
            order = (0, int(web.boundary_label[web.vertex_of[root]] or 0))
        else:
            key = min(
                _serialize_untagged_component(web, component, root)
                for root in component
            )
            order = (1, key)
        serialized.append((order, key))
    serialized.sort(key=lambda item: item[0])
    return tuple(key for _order, key in serialized)


def exact_benzene_cycles(web: HalfEdgeWeb) -> tuple[tuple[int, ...], ...]:
    """Return induced internal alternating ordinary/hourglass six-cycles."""

    edges = _edge_lookup(web)
    adjacency: dict[int, set[int]] = {vertex: set() for vertex in web.color}
    for edge in edges.values():
        u, v = edge.endpoints
        if web.color[u] == VertexColor.BOUNDARY or web.color[v] == VertexColor.BOUNDARY:
            continue
        adjacency[u].add(v)
        adjacency[v].add(u)

    found: set[tuple[int, ...]] = set()

    def visit(start: int, path: list[int]) -> None:
        current = path[-1]
        if len(path) == 6:
            if start not in adjacency[current]:
                return
            cycle = _canonical_cycle(path)
            kinds = [
                edges[frozenset((cycle[index], cycle[(index + 1) % 6]))].kind
                for index in range(6)
            ]
            if any(kinds[index] == kinds[(index + 1) % 6] for index in range(6)):
                return
            cycle_edges = {
                frozenset((cycle[index], cycle[(index + 1) % 6]))
                for index in range(6)
            }
            induced = {
                frozenset((cycle[left], cycle[right]))
                for left in range(6)
                for right in range(left + 1, 6)
                if cycle[right] in adjacency[cycle[left]]
            }
            if induced == cycle_edges:
                found.add(cycle)
            return
        for neighbor in adjacency[current]:
            if neighbor == start or neighbor in path or neighbor < start:
                continue
            visit(start, path + [neighbor])

    for start in sorted(adjacency):
        visit(start, [start])
    return tuple(sorted(found))


def _trip_signature(web: HalfEdgeWeb) -> tuple[tuple[int, ...], ...]:
    labels = sorted(label for label in web.boundary_label.values() if label is not None)
    return tuple(
        tuple(follow_trip_exact(web, label, turn) for label in labels)
        for turn in (1, 2, 3)
    )


def enumerate_square_orbit_states(
    source: HalfEdgeWeb | str | Path,
    *,
    max_states: int = 100_000,
) -> dict[Hashable, HalfEdgeWeb]:
    """Return every exact state in one complete Figure 2 square orbit.

    Keys are boundary-fixed, untagged exact ribbon keys.  Every transition is
    checked against the source trip tuple.  Raising on the state limit is safer
    for canonicalization than returning an incomplete orbit.
    """
    initial = load_halfedge_web(source) if isinstance(source, (str, Path)) else copy.deepcopy(source)
    validate_exact_web(initial)
    initial_trip = _trip_signature(initial)
    initial_key = canonical_untagged_web_key(initial)
    states = {initial_key: initial}
    queue = deque([initial])
    while queue:
        web = queue.popleft()
        for move in detect_exact_square_moves(web):
            child = apply_exact_square_move(web, move)
            if _trip_signature(child) != initial_trip:
                raise ValueError(f"Square move {move.cycle} changed the exact trip tuple.")
            key = canonical_untagged_web_key(child)
            if key in states:
                continue
            if len(states) >= max_states:
                raise RuntimeError(
                    f"Square orbit exceeded the canonicalization limit of {max_states} states."
                )
            states[key] = child
            queue.append(child)
    return states


def explore_square_orbit(
    source: HalfEdgeWeb | str | Path,
    *,
    max_states: int = 100_000,
    stop_at_benzene: bool = False,
) -> SquareOrbitResult:
    """Explore a complete exact square orbit, or flag it as truncated."""

    initial = load_halfedge_web(source) if isinstance(source, (str, Path)) else copy.deepcopy(source)
    validate_exact_web(initial)
    initial_trip = _trip_signature(initial)
    initial_key = canonical_untagged_web_key(initial)
    seen = {initial_key}
    queue = deque([(initial, 0)])
    edge_count = 0
    maximum_depth = 0
    benzene_found = False
    benzene_depth: int | None = None
    benzene_witnesses: tuple[tuple[int, ...], ...] = ()
    trip_failures = 0
    truncated = False

    while queue:
        web, depth = queue.popleft()
        maximum_depth = max(maximum_depth, depth)
        benzenes = exact_benzene_cycles(web)
        if benzenes:
            benzene_found = True
            if benzene_depth is None:
                benzene_depth = depth
                benzene_witnesses = benzenes
            if stop_at_benzene:
                break
        for move in detect_exact_square_moves(web):
            child = apply_exact_square_move(web, move)
            edge_count += 1
            if _trip_signature(child) != initial_trip:
                trip_failures += 1
                raise ValueError(
                    f"Square move {move.cycle} changed the exact trip tuple at depth {depth}."
                )
            key = canonical_untagged_web_key(child)
            if key in seen:
                continue
            if len(seen) >= max_states:
                truncated = True
                queue.clear()
                break
            seen.add(key)
            queue.append((child, depth + 1))

    return SquareOrbitResult(
        state_count=len(seen),
        edge_count=edge_count,
        maximum_depth=maximum_depth,
        benzene_found=benzene_found,
        benzene_depth=benzene_depth,
        benzene_cycles=benzene_witnesses,
        truncated=truncated,
        trip_invariant_failures=trip_failures,
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph_json", type=Path)
    parser.add_argument("--max-states", type=int, default=100_000)
    parser.add_argument("--stop-at-benzene", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    web = load_halfedge_web(args.graph_json)
    moves = detect_exact_square_moves(web)
    orbit = explore_square_orbit(
        web,
        max_states=args.max_states,
        stop_at_benzene=args.stop_at_benzene,
    )
    print(
        json.dumps(
            {
                "graph": str(args.graph_json.resolve()),
                "initial_square_moves": [
                    {
                        "cycle": move.cycle,
                        "corner_kinds": move.corner_kinds,
                        "hourglass_count": move.hourglass_count,
                    }
                    for move in moves
                ],
                "orbit": orbit.__dict__,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
