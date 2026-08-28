"""Independent q=1, paper-convention checks for exact local SL4 rewrites.

This module does not call the skein scheduler or any relation implementation.
It evaluates local tagged tensors using Gaetz--Pechenik--Pfannerer--Striker--
Swanson, Definitions 2.7--2.8 and Theorem 2.9.  A 2-hourglass is one
multiplicity-two edge labeled by an unordered two-subset.  At a vertex, those
edge-label subsets are read clockwise from the tag and contribute
``(-1) ** ell_v``.  Vertex color contributes no independent scalar.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Mapping, Sequence

from halfedge_web_20260812 import (
    EdgeKind,
    ExactRibbonState,
    HalfEdgeWeb,
    VertexColor,
    paper_vertex_labeling_sign,
    validate_exact_web,
    vertex_cycle_ccw,
)


@dataclass(frozen=True)
class TwoHourglassContractionTopology:
    """Tag-independent ribbon splice underlying Figure 9."""

    center: int
    ordered_bundles: tuple[int, int]
    ordered_outer_vertices: tuple[int, int]
    residual_blocks: tuple[tuple[int, int], tuple[int, int]]
    merged_cycle: tuple[int, int, int, int]
    outer_slot_maps: tuple[
        tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]],
        tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]],
    ]


@dataclass(frozen=True)
class TwoHourglassTensorCertificate:
    center: int
    ordered_bundles: tuple[int, int]
    ordered_outer_vertices: tuple[int, int]
    splice_cycle: tuple[int, int, int, int]
    merged_cycle: tuple[int, int, int, int]
    merged_tag_root: int
    residual_blocks: tuple[tuple[int, int], tuple[int, int]]
    outer_slot_maps: tuple[
        tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]],
        tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]],
    ]
    coefficient: int
    assignments_checked: int
    nonzero_assignments: int
    convention: str = "GPPSS_Definition_2.8_subset_coinversion_v2"


@dataclass(frozen=True)
class OverlapTensorCertificate:
    local_vertices: tuple[int, int, int]
    ordinary_physical_edges: tuple[int, int]
    hourglass_bundle: int
    merged_cycle: tuple[int, int, int, int]
    coefficient: int
    assignments_checked: int
    nonzero_assignments: int
    convention: str = "GPPSS_Definition_2.8_subset_coinversion_v2"


@dataclass(frozen=True)
class ExactLinearRelationTensorCertificate:
    boundary_labels: tuple[int, ...]
    branch_coefficients: tuple[int, ...]
    assignments_checked: int
    nonzero_left_assignments: int
    nonzero_right_assignments: int
    convention: str = "GPPSS_Definition_2.8_subset_coinversion_v2"


def extract_exact_local_tensor_fixture(
    web: ExactRibbonState,
    internal_vertices: Sequence[int],
    *,
    boundary_label_by_outside_dart: Mapping[int, int] | None = None,
) -> ExactRibbonState:
    """Cut ordinary outside legs to boundary vertices without losing ribbon data.

    The selected vertices, their complete cyclic orders, live tags, internal
    mate involution, and hourglass frames are copied literally.  Every
    ordinary edge leaving the selected neighborhood becomes one uniquely
    labelled boundary leg.  A partial hourglass is rejected because cutting
    one strand bundle would erase precisely the frame information this oracle
    is intended to check.
    """

    validate_exact_web(web)
    selected_order = tuple(
        dict.fromkeys(int(vertex) for vertex in internal_vertices)
    )
    selected = set(selected_order)
    if not selected:
        raise ValueError("A local tensor fixture needs at least one internal vertex.")
    if any(
        web.color.get(vertex) == VertexColor.BOUNDARY for vertex in selected
    ):
        raise ValueError("Local tensor fixture vertices must be internal.")
    local_darts = {
        dart
        for vertex in selected
        for dart in vertex_cycle_ccw(web, vertex)
    }
    if any(len(vertex_cycle_ccw(web, vertex)) != 4 for vertex in selected):
        raise ValueError("Local tensor fixture vertices must each have four darts.")

    vertex_of = {dart: int(web.vertex_of[dart]) for dart in local_darts}
    mate: dict[int, int] = {}
    next_ccw = {dart: int(web.next_ccw[dart]) for dart in local_darts}
    edge_kind = {dart: web.edge_kind[dart] for dart in local_darts}
    physical_edge_of = {
        dart: int(web.physical_edge_of[dart]) for dart in local_darts
    }
    bundle_of = {dart: web.bundle_of[dart] for dart in local_darts}
    source_edge_id = {dart: web.source_edge_id[dart] for dart in local_darts}
    source_local_strand = {
        dart: web.source_local_strand[dart] for dart in local_darts
    }
    color = {vertex: web.color[vertex] for vertex in selected}
    boundary_label = {vertex: None for vertex in selected}
    tag_after_ccw = {
        vertex: int(web.tag_after_ccw[vertex]) for vertex in selected
    }
    tensor_valence = {vertex: 4 for vertex in selected}

    next_dart = max(web.vertex_of, default=-1) + 1
    next_vertex = max(web.color, default=-1) + 1
    supplied_boundary_labels = (
        {
            int(dart): int(label)
            for dart, label in boundary_label_by_outside_dart.items()
        }
        if boundary_label_by_outside_dart is not None
        else None
    )
    if supplied_boundary_labels is not None and (
        any(label <= 0 for label in supplied_boundary_labels.values())
        or len(set(supplied_boundary_labels.values()))
        != len(supplied_boundary_labels)
    ):
        raise ValueError("Local boundary-port labels must be distinct positive integers.")
    next_label = 1
    used_supplied_outside_darts: set[int] = set()
    # Boundary tensor slots are keyed by the untouched outside dart, not by
    # the temporary local dart that a rewrite may replace.  This makes input
    # and output fixtures of the same local relation share one literal
    # boundary labeling even when the rewrite allocates new internal darts.
    # Allocate artificial boundary labels by the caller's semantic vertex
    # roles and each live-tag-rooted cyclic order.  Sorting temporary dart or
    # vertex IDs made the same local relation acquire different fixture
    # digests after an otherwise harmless ID renaming.
    ordered_local_darts: list[int] = []
    for vertex in selected_order:
        cycle = vertex_cycle_ccw(web, int(vertex))
        root = web.tag_after_ccw.get(int(vertex))
        if root not in cycle:
            raise ValueError(
                f"Local tensor fixture vertex {vertex} has no exact tag root."
            )
        position = cycle.index(int(root))
        ordered_local_darts.extend(cycle[position:] + cycle[:position])
    for dart in ordered_local_darts:
        old_mate = int(web.mate[dart])
        mate_vertex = int(web.vertex_of[old_mate])
        if mate_vertex in selected:
            mate[dart] = old_mate
            continue
        if web.edge_kind[dart] != EdgeKind.ORDINARY or web.bundle_of[dart] is not None:
            raise ValueError(
                "A local tensor fixture cannot cut a partial hourglass bundle."
            )
        boundary_dart = next_dart
        boundary_vertex = next_vertex
        next_dart += 1
        next_vertex += 1
        mate[dart] = boundary_dart
        mate[boundary_dart] = dart
        vertex_of[boundary_dart] = boundary_vertex
        next_ccw[boundary_dart] = boundary_dart
        edge_kind[boundary_dart] = EdgeKind.ORDINARY
        physical_edge_of[boundary_dart] = int(web.physical_edge_of[dart])
        bundle_of[boundary_dart] = None
        source_edge_id[boundary_dart] = None
        source_local_strand[boundary_dart] = None
        color[boundary_vertex] = VertexColor.BOUNDARY
        if supplied_boundary_labels is None:
            assigned_label = next_label
            next_label += 1
        else:
            if old_mate not in supplied_boundary_labels:
                raise ValueError(
                    "A local output boundary port is absent from the shared "
                    f"input port map: outside dart {old_mate}."
                )
            assigned_label = int(supplied_boundary_labels[old_mate])
            used_supplied_outside_darts.add(old_mate)
        boundary_label[boundary_vertex] = assigned_label
        tag_after_ccw[boundary_vertex] = None
        tensor_valence[boundary_vertex] = 1

    if supplied_boundary_labels is not None and used_supplied_outside_darts != set(
        supplied_boundary_labels
    ):
        missing = sorted(set(supplied_boundary_labels) - used_supplied_outside_darts)
        raise ValueError(
            "A shared local boundary-port map contains ports absent from the "
            f"fixture: {missing}."
        )

    local_bundles = {
        int(bundle)
        for dart, bundle in bundle_of.items()
        if dart in local_darts and bundle is not None
    }
    bundle_frame_root = {}
    for bundle in sorted(local_bundles):
        members = {
            dart
            for dart, candidate in web.bundle_of.items()
            if candidate == bundle
        }
        if not members <= local_darts:
            raise ValueError(
                f"Local tensor fixture cuts hourglass bundle {bundle}."
            )
        bundle_frame_root[bundle] = {
            int(vertex): int(root)
            for vertex, root in web.bundle_frame_root[bundle].items()
        }

    fixture = HalfEdgeWeb(
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
        tensor_valence=tensor_valence,
        bundle_frame_root=bundle_frame_root,
    )
    validate_exact_web(fixture)
    return fixture


def exact_local_boundary_port_label_map(
    web: ExactRibbonState,
    internal_vertices: Sequence[int],
) -> dict[int, int]:
    """Label untouched outside darts in semantic vertex/tag-cycle order."""

    validate_exact_web(web)
    selected_order = tuple(
        dict.fromkeys(int(vertex) for vertex in internal_vertices)
    )
    selected = set(selected_order)
    labels: dict[int, int] = {}
    next_label = 1
    for vertex in selected_order:
        cycle = vertex_cycle_ccw(web, int(vertex))
        root = web.tag_after_ccw.get(int(vertex))
        if root not in cycle:
            raise ValueError(
                f"Local tensor fixture vertex {vertex} has no exact tag root."
            )
        position = cycle.index(int(root))
        rooted = cycle[position:] + cycle[:position]
        for dart in rooted:
            outside = int(web.mate[dart])
            if int(web.vertex_of[outside]) in selected:
                continue
            if web.edge_kind[dart] != EdgeKind.ORDINARY or web.bundle_of[dart] is not None:
                raise ValueError(
                    "A local tensor fixture cannot cut a partial hourglass bundle."
                )
            if outside in labels:
                raise ValueError("A local outside dart is incident to two selected ports.")
            labels[outside] = next_label
            next_label += 1
    if not labels:
        raise ValueError("A local tensor fixture has no boundary ports.")
    return labels


def levi_civita4(colors: tuple[int, int, int, int]) -> int:
    if len(set(colors)) != 4 or any(color not in {1, 2, 3, 4} for color in colors):
        return 0
    inversions = sum(
        colors[left] > colors[right]
        for left in range(4)
        for right in range(left + 1, 4)
    )
    return -1 if inversions % 2 else 1


def _vertex_tensor(web: ExactRibbonState, vertex: int, colors: dict[int, int]) -> int:
    physical_colors: dict[int, int] = {}
    for dart in vertex_cycle_ccw(web, int(vertex)):
        physical = int(web.physical_edge_of[dart])
        color = int(colors[dart])
        previous = physical_colors.get(physical)
        if previous is not None and previous != color:
            raise ValueError(
                f"Physical edge {physical} has inconsistent local colors."
            )
        physical_colors[physical] = color
    return paper_vertex_labeling_sign(
        web, int(vertex), physical_colors, r=4
    )


def _ordered_bundle_darts(
    web: ExactRibbonState, bundle: int, vertex: int
) -> tuple[int, int]:
    cycle = vertex_cycle_ccw(web, int(vertex))
    root = web.bundle_frame_root[int(bundle)][int(vertex)]
    position = cycle.index(root)
    rotated = cycle[position:] + cycle[:position]
    members = tuple(
        dart for dart in rotated if web.bundle_of[dart] == int(bundle)
    )
    if len(members) != 2:
        raise ValueError("A tensor-oracle 2-hourglass must expose two ordered darts.")
    return members


def exact_boundary_tensor(web: ExactRibbonState) -> dict[tuple[int, ...], int]:
    """Evaluate a finite exact web on every simple boundary-color assignment.

    This is an independent q=1 evaluator for local relation fixtures.  Every
    internal vertex must expose total multiplicity four.  Ordinary internal
    edges are summed over colors 1..4; each 2-hourglass is summed over the six
    unordered subset labels.  Direct boundary-to-boundary splices impose
    equality of their two boundary colors.
    """

    validate_exact_web(web)
    boundary = sorted(
        (int(label), int(vertex))
        for vertex, label in web.boundary_label.items()
        if label is not None
    )
    if len({label for label, _vertex in boundary}) != len(boundary):
        raise ValueError("Boundary tensor labels must be unique.")
    internal_vertices = [
        vertex
        for vertex in sorted(web.color)
        if web.color[vertex] != VertexColor.BOUNDARY
    ]
    if any(len(vertex_cycle_ccw(web, vertex)) != 4 for vertex in internal_vertices):
        raise ValueError("The exact tensor oracle requires four darts at every internal vertex.")

    boundary_darts = {
        vertex: vertex_cycle_ccw(web, vertex)[0] for _label, vertex in boundary
    }
    internal_ordinary: list[tuple[int, int]] = []
    seen_physical: set[int] = set()
    for dart in sorted(web.vertex_of):
        if web.edge_kind[dart] != EdgeKind.ORDINARY:
            continue
        physical = int(web.physical_edge_of[dart])
        if physical in seen_physical:
            continue
        seen_physical.add(physical)
        mate = web.mate[dart]
        endpoints = (web.vertex_of[dart], web.vertex_of[mate])
        if all(web.color[vertex] != VertexColor.BOUNDARY for vertex in endpoints):
            internal_ordinary.append((dart, mate))

    bundles = sorted({int(bundle) for bundle in web.bundle_of.values() if bundle is not None})
    bundle_data = []
    for bundle in bundles:
        endpoints = sorted(
            {
                int(web.vertex_of[dart])
                for dart, candidate in web.bundle_of.items()
                if candidate == bundle
            }
        )
        if len(endpoints) != 2:
            raise ValueError(f"Bundle {bundle} does not have two endpoints.")
        first = _ordered_bundle_darts(web, bundle, endpoints[0])
        bundle_data.append((first, tuple(web.mate[dart] for dart in first)))

    pairs = tuple(itertools.combinations((1, 2, 3, 4), 2))
    result: dict[tuple[int, ...], int] = {}
    for assignment in itertools.product((1, 2, 3, 4), repeat=len(boundary)):
        base: dict[int, int] = {}
        consistent = True
        for color, (_label, vertex) in zip(assignment, boundary):
            dart = boundary_darts[vertex]
            mate = web.mate[dart]
            for target in (dart, mate):
                previous = base.get(target)
                if previous is not None and previous != color:
                    consistent = False
                    break
                base[target] = int(color)
            if not consistent:
                break
        if not consistent:
            result[assignment] = 0
            continue

        total = 0
        for ordinary_colors in itertools.product(
            (1, 2, 3, 4), repeat=len(internal_ordinary)
        ):
            ordinary_base = dict(base)
            for darts, color in zip(internal_ordinary, ordinary_colors):
                ordinary_base[darts[0]] = ordinary_base[darts[1]] = int(color)
            for pair_colors in itertools.product(pairs, repeat=len(bundle_data)):
                colors = dict(ordinary_base)
                for (first, second), pair in zip(bundle_data, pair_colors):
                    for dart, color in zip(first, pair):
                        colors[dart] = int(color)
                    for dart, color in zip(second, pair):
                        colors[dart] = int(color)
                product = 1
                for vertex in internal_vertices:
                    product *= _vertex_tensor(web, vertex, colors)
                    if product == 0:
                        break
                total += product
        result[assignment] = int(total)
    return result


def certify_exact_linear_relation(
    left: ExactRibbonState,
    branches: Sequence[tuple[int, ExactRibbonState]],
) -> ExactLinearRelationTensorCertificate:
    """Prove one exact local tensor equals a weighted sum of exact tensors."""

    left_tensor = exact_boundary_tensor(left)
    right_tensors = [(int(coefficient), exact_boundary_tensor(web)) for coefficient, web in branches]
    left_keys = set(left_tensor)
    if any(set(tensor) != left_keys for _coefficient, tensor in right_tensors):
        raise ValueError("Exact tensor relation branches do not share one boundary type.")
    mismatches = []
    nonzero_right = 0
    for assignment in sorted(left_keys):
        right_value = sum(
            coefficient * tensor[assignment]
            for coefficient, tensor in right_tensors
        )
        nonzero_right += right_value != 0
        if left_tensor[assignment] != right_value:
            mismatches.append((assignment, left_tensor[assignment], right_value))
            if len(mismatches) >= 8:
                break
    if mismatches:
        raise ValueError(f"Exact tensor relation failed: {mismatches}")
    labels = tuple(
        label
        for label, _vertex in sorted(
            (int(label), int(vertex))
            for vertex, label in left.boundary_label.items()
            if label is not None
        )
    )
    return ExactLinearRelationTensorCertificate(
        boundary_labels=labels,
        branch_coefficients=tuple(coefficient for coefficient, _tensor in right_tensors),
        assignments_checked=len(left_keys),
        nonzero_left_assignments=sum(value != 0 for value in left_tensor.values()),
        nonzero_right_assignments=nonzero_right,
    )


def _two_dart_cyclic_block(
    web: ExactRibbonState, vertex: int, members: set[int]
) -> tuple[int, int]:
    """Return a two-dart CCW block from its unique incoming transition."""

    cycle = vertex_cycle_ccw(web, int(vertex))
    if len(cycle) != 4 or len(members) != 2 or not members <= set(cycle):
        raise ValueError("A Figure 9 block must contain two of four local darts.")
    starts = [
        dart
        for dart in members
        if next(
            candidate
            for candidate in cycle
            if web.next_ccw[candidate] == dart
        )
        not in members
    ]
    if len(starts) != 1:
        raise ValueError("A Figure 9 two-dart set is not one cyclic block.")
    first = int(starts[0])
    second = int(web.next_ccw[first])
    if second not in members or web.next_ccw[second] in members:
        raise ValueError("A Figure 9 two-dart block has an ambiguous boundary.")
    return first, second


def two_hourglass_contraction_topology(
    web: ExactRibbonState,
    center: int,
    bundles: tuple[int, int] | None = None,
) -> TwoHourglassContractionTopology:
    """Plan the tag-independent ribbon splice in Figure 9.

    Each outer residual block retains its literal CCW order.  The two blocks
    are concatenated to form the merged vertex; swapping their order only
    cyclically rotates the same unrooted four-cycle.  Full four-slot maps are
    returned so a surviving cable frame never loses an origin that happens to
    lie on a consumed dart.
    """

    validate_exact_web(web)
    center = int(center)
    if web.color.get(center) not in {VertexColor.WHITE, VertexColor.BLACK}:
        raise ValueError("A two-hourglass contraction center must be internal.")
    center_cycle = vertex_cycle_ccw(web, center)
    if len(center_cycle) != 4 or any(
        web.bundle_of[dart] is None for dart in center_cycle
    ):
        raise ValueError("The contraction center must have four hourglass darts.")
    ordered: list[int] = []
    for dart in center_cycle:
        bundle = int(web.bundle_of[dart])
        if bundle not in ordered:
            ordered.append(bundle)
    if len(ordered) != 2:
        raise ValueError("The contraction center must meet exactly two 2-hourglasses.")
    for bundle in ordered:
        members = {
            int(dart) for dart in center_cycle if web.bundle_of[dart] == bundle
        }
        _two_dart_cyclic_block(web, center, members)
    if bundles is not None and set(ordered) != {int(bundle) for bundle in bundles}:
        raise ValueError("Requested bundles do not match the contraction center.")

    outer_vertices: list[int] = []
    residual_blocks: list[tuple[int, int]] = []
    old_slot_cycles: list[tuple[int, int, int, int]] = []
    for bundle in ordered:
        endpoints = {
            web.vertex_of[dart]
            for dart, candidate in web.bundle_of.items()
            if candidate == bundle
        }
        if center not in endpoints or len(endpoints) != 2:
            raise ValueError("A contraction bundle does not have the selected center.")
        outer = int(next(vertex for vertex in endpoints if vertex != center))
        if web.color[outer] == web.color[center]:
            raise ValueError("Two-hourglass contraction is not bipartite.")
        outer_cycle = vertex_cycle_ccw(web, outer)
        consumed = {
            int(dart) for dart in outer_cycle if web.bundle_of[dart] == bundle
        }
        _two_dart_cyclic_block(web, outer, consumed)
        residual = set(int(dart) for dart in outer_cycle) - consumed
        block = _two_dart_cyclic_block(web, outer, residual)
        c0 = int(web.next_ccw[block[1]])
        c1 = int(web.next_ccw[c0])
        old_slots = (int(block[0]), int(block[1]), c0, c1)
        if set(old_slots) != set(outer_cycle) or web.next_ccw[c1] != block[0]:
            raise ValueError("Could not root an outer Figure 9 slot cycle.")
        outer_vertices.append(outer)
        residual_blocks.append(block)
        old_slot_cycles.append(old_slots)
    if len(set(outer_vertices)) != 2:
        raise ValueError("The two contraction bundles must have distinct outer vertices.")
    if any(web.color[outer] != web.color[outer_vertices[0]] for outer in outer_vertices):
        raise ValueError("Contraction outer vertices must have the same color.")
    local_vertices = {center, *outer_vertices}
    if any(
        web.vertex_of[web.mate[dart]] in local_vertices
        for block in residual_blocks
        for dart in block
    ):
        raise ValueError(
            "Each outer contraction vertex must have two outside tensor ports."
        )

    merged = tuple(dart for block in residual_blocks for dart in block)
    if len(set(merged)) != 4:
        raise ValueError("A contraction must expose four distinct merged darts.")
    slot_maps = []
    for index, old_slots in enumerate(old_slot_cycles):
        own = residual_blocks[index]
        other = residual_blocks[1 - index]
        new_slots = (*own, *other)
        slot_maps.append(tuple(zip(old_slots, new_slots)))
    return TwoHourglassContractionTopology(
        center=center,
        ordered_bundles=(int(ordered[0]), int(ordered[1])),
        ordered_outer_vertices=(int(outer_vertices[0]), int(outer_vertices[1])),
        residual_blocks=(residual_blocks[0], residual_blocks[1]),
        merged_cycle=(int(merged[0]), int(merged[1]), int(merged[2]), int(merged[3])),
        outer_slot_maps=(slot_maps[0], slot_maps[1]),  # type: ignore[arg-type]
    )


def certify_two_hourglass_contraction(
    web: ExactRibbonState,
    center: int,
    bundles: tuple[int, int] | None = None,
    *,
    topology: TwoHourglassContractionTopology | None = None,
    merged_cycle: tuple[int, int, int, int] | None = None,
) -> TwoHourglassTensorCertificate:
    """Evaluate a Figure 9 ``2-hourglass/2-hourglass`` contraction.

    ``merged_cycle`` is the exact rooted CCW order used by the generated
    four-valent tensor.  Its unrooted order is planned without consulting any
    live tag.  All 4^4 assignments to its exterior tensor ports are checked,
    so the resulting coefficient carries every consumed tag sign exactly once.
    """

    if topology is None:
        topology = two_hourglass_contraction_topology(web, center, bundles)
    else:
        if int(topology.center) != int(center):
            raise ValueError("Supplied Figure 9 topology has the wrong center.")
        if bundles is not None and set(topology.ordered_bundles) != {
            int(bundle) for bundle in bundles
        }:
            raise ValueError("Supplied Figure 9 topology has the wrong bundles.")
    natural = topology.merged_cycle
    if merged_cycle is None:
        merged_cycle = natural
    merged_cycle = tuple(int(dart) for dart in merged_cycle)
    rotations = {
        natural[offset:] + natural[:offset] for offset in range(len(natural))
    }
    if merged_cycle not in rotations:
        raise ValueError(
            "The requested merged root does not preserve the Figure 9 ribbon cycle."
        )

    outer_bundle_darts = [
        _ordered_bundle_darts(web, bundle, outer)
        for bundle, outer in zip(
            topology.ordered_bundles, topology.ordered_outer_vertices
        )
    ]
    merged_color = web.color[topology.ordered_outer_vertices[0]]
    ratios = set()
    nonzero = 0
    pairs = tuple(itertools.combinations((1, 2, 3, 4), 2))
    for external_colors in itertools.product((1, 2, 3, 4), repeat=4):
        base = dict(zip(merged_cycle, external_colors))
        chain_value = 0
        for pair_colors in itertools.product(pairs, repeat=2):
            colors = dict(base)
            for bundle_darts, pair in zip(outer_bundle_darts, pair_colors):
                for dart, color in zip(bundle_darts, pair):
                    colors[dart] = int(color)
                    colors[web.mate[dart]] = int(color)
            product = 1
            for vertex in (*topology.ordered_outer_vertices, topology.center):
                product *= _vertex_tensor(web, vertex, colors)
            chain_value += product

        merged_value = levi_civita4(tuple(external_colors))
        if merged_value == 0:
            if chain_value != 0:
                raise ValueError(
                    "The two-hourglass chain is not proportional to one merged tensor."
                )
            continue
        nonzero += 1
        if chain_value % merged_value:
            raise ValueError("The contraction tensor coefficient is not integral.")
        ratios.add(chain_value // merged_value)
    if len(ratios) != 1:
        raise ValueError(
            f"The contraction has no single tensor coefficient: {sorted(ratios)}."
        )
    return TwoHourglassTensorCertificate(
        center=topology.center,
        ordered_bundles=topology.ordered_bundles,
        ordered_outer_vertices=topology.ordered_outer_vertices,
        splice_cycle=topology.merged_cycle,
        merged_cycle=merged_cycle,
        merged_tag_root=int(merged_cycle[0]),
        residual_blocks=topology.residual_blocks,
        outer_slot_maps=topology.outer_slot_maps,
        coefficient=int(next(iter(ratios))),
        assignments_checked=4**4,
        nonzero_assignments=nonzero,
    )


def certify_double_edge_hourglass_overlap_to_merged_tensor(
    web: ExactRibbonState,
    *,
    local_vertices: tuple[int, int, int],
    ordinary_physical_edges: tuple[int, int],
    hourglass_bundle: int,
    merged_cycle: tuple[int, int, int, int],
) -> OverlapTensorCertificate:
    """Evaluate the unreduced lens/hourglass overlap against one merged tensor."""

    validate_exact_web(web)
    vertices = tuple(int(vertex) for vertex in local_vertices)
    if len(set(vertices)) != 3:
        raise ValueError("An overlap oracle requires three distinct local vertices.")
    merged_cycle = tuple(int(dart) for dart in merged_cycle)
    if len(set(merged_cycle)) != 4 or any(
        web.vertex_of[dart] not in vertices for dart in merged_cycle
    ):
        raise ValueError("Merged-cycle darts are not four distinct local outside ports.")
    physical_edges = tuple(int(physical) for physical in ordinary_physical_edges)
    ordinary_darts = []
    ordinary_endpoint_sets = []
    for physical in physical_edges:
        darts = tuple(
            dart
            for dart, candidate in web.physical_edge_of.items()
            if candidate == physical
        )
        if len(darts) != 2 or any(web.vertex_of[dart] not in vertices for dart in darts):
            raise ValueError("An overlap ordinary edge is not internal to the fixture.")
        ordinary_darts.append(darts)
        ordinary_endpoint_sets.append({web.vertex_of[dart] for dart in darts})

    bundle = int(hourglass_bundle)
    bundle_endpoints = {
        web.vertex_of[dart]
        for dart, candidate in web.bundle_of.items()
        if candidate == bundle
    }
    if len(bundle_endpoints) != 2 or not bundle_endpoints <= set(vertices):
        raise ValueError("The overlap hourglass is not internal to the fixture.")
    shared_ordinary = set.intersection(*ordinary_endpoint_sets)
    centers = bundle_endpoints & shared_ordinary
    if len(centers) != 1:
        raise ValueError("Could not identify the shared lens/hourglass endpoint.")
    center = next(iter(centers))
    outer = next(vertex for vertex in bundle_endpoints if vertex != center)
    ordered_hourglass = _ordered_bundle_darts(web, bundle, outer)

    merged_color = web.color[web.vertex_of[merged_cycle[0]]]
    if merged_color not in {VertexColor.WHITE, VertexColor.BLACK}:
        raise ValueError("Merged overlap tensor must be internal.")
    ratios = set()
    nonzero = 0
    pairs = tuple(itertools.combinations((1, 2, 3, 4), 2))
    for external_colors in itertools.product((1, 2, 3, 4), repeat=4):
        base = dict(zip(merged_cycle, external_colors))
        overlap_value = 0
        for pair in pairs:
            for ordinary_colors in itertools.product((1, 2, 3, 4), repeat=2):
                colors = dict(base)
                for dart, color in zip(ordered_hourglass, pair):
                    colors[dart] = int(color)
                    colors[web.mate[dart]] = int(color)
                for darts, color in zip(ordinary_darts, ordinary_colors):
                    colors[darts[0]] = colors[darts[1]] = int(color)
                product = 1
                for vertex in vertices:
                    product *= _vertex_tensor(web, vertex, colors)
                overlap_value += product
        merged_value = levi_civita4(tuple(external_colors))
        if merged_value == 0:
            if overlap_value != 0:
                raise ValueError("Overlap tensor is not proportional to the merged tensor.")
            continue
        nonzero += 1
        if overlap_value % merged_value:
            raise ValueError("The overlap tensor coefficient is not integral.")
        ratios.add(overlap_value // merged_value)
    if len(ratios) != 1:
        raise ValueError(f"Overlap has no single merged coefficient: {sorted(ratios)}.")
    return OverlapTensorCertificate(
        local_vertices=vertices,
        ordinary_physical_edges=physical_edges,
        hourglass_bundle=bundle,
        merged_cycle=merged_cycle,
        coefficient=int(next(iter(ratios))),
        assignments_checked=4**4,
        nonzero_assignments=nonzero,
    )
