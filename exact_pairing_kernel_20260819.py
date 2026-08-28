"""Representation-preserving production kernel for SL4 web pairings.

This module is the migration boundary between the exact dart model and the
legacy neighbor-list evaluator.  Nothing in this file projects a web to a list
of neighboring vertex IDs.  In particular, term consolidation retains the
mate involution, rooted cyclic orders, vertex colors, and hourglass bundles.

Implemented here:

* exact single-web and pair-term consolidation with complete route provenance;
* the two q=1 double-edge reductions;
* fail-closed witness detection for unsupported tagged Figure 9 topology;
* the executable opposite-hourglass Figure 43 row;
* exact fork/direct-boundary tests;
* exact terminal Plucker-claw detection and coloring;
* fail-closed detection of the not-yet-certifiable lower-valence Figure 43 row; and
* tensor- and confluence-certified application of the right-hourglass Figure 43 row 4; and
* guarded access to all four Figure 2 square moves.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
from dataclasses import dataclass, field, replace
from typing import Any, Hashable, Iterable, Mapping, Sequence

from halfedge_web_20260812 import (
    EdgeKind,
    ExactRibbonState,
    HalfEdgeWeb,
    VertexColor,
    apply_exact_double_trident,
    apply_exact_wrench,
    bundle_ids,
    canonical_unlabeled_boundary_web_key,
    canonical_web_key,
    enforce_paper_hourglass_half_twist,
    intrinsic_tag_root,
    normalize_intrinsic_tags,
    paper_incident_edge_blocks_clockwise,
    paper_tag_transport_sign,
    paper_vertex_labeling_data,
    refresh_bundle_frames,
    validate_exact_web,
    vertex_cycle_ccw,
)
from square_move_orbit_exact_20260815 import (
    ExactSquareMove,
    apply_exact_square_move,
    canonical_untagged_web_key,
    detect_exact_square_moves,
    exact_square_move_key,
)
from exact_local_tensor_oracle_20260819 import (
    certify_exact_linear_relation,
    certify_two_hourglass_contraction,
    exact_boundary_tensor,
    extract_exact_local_tensor_fixture,
    exact_local_boundary_port_label_map,
    two_hourglass_contraction_topology,
)
from exact_local_tensor_fast_20260820 import (
    certify_exact_linear_relation_fast,
    exact_boundary_tensor_fast,
)


LOCAL_RULE_CERTIFICATE_SCHEMA = "problem3.local_rule_certificate.v2"
LOCAL_RULE_TENSOR_CONVENTION = (
    "project_paper_cyclic_order_all_internal_black_white_v1"
    "__GPPSS_Definition_2.8_subset_coinversion_tensor"
)
FLL_TERMINAL_CONVENTION_ID = (
    "fll_prop2_20_source_orientation_unsigned_count_v1"
)


class UncertifiedRelationError(ValueError):
    """Raised when a relation lacks a complete local tensor certificate."""


# A certificate may prove one named linear identity whose displayed summands
# have more specific production route names.  Keep those bindings explicit and
# positional: this is certificate validation metadata, never coefficient
# arithmetic.  Prefix matching remains sufficient for rule families whose
# branch names are direct refinements of the certificate relation name.
_CERTIFICATE_BRANCH_RELATION_BINDINGS = {
    "benzene_surgery": (
        "benzene_toggle_bottom",
        "benzene_smoothing_O",
        "benzene_smoothing_H",
    ),
    "figure43_single_right_hourglass": (
        "figure43_single_right_open_path",
        "figure43_single_right_hourglass_splice",
    ),
}


@dataclass(frozen=True)
class ExactLocalRuleCertificate:
    """Replayable proof record for one tagged local relation application."""

    schema: str
    certificate_id: str
    relation: str
    paper_reference: str
    convention: str
    production_approved: bool
    affected_vertices: tuple[Mapping[str, Any], ...]
    input_state: Mapping[str, Any]
    output_states: tuple[Mapping[str, Any], ...]
    local_input_state: Mapping[str, Any]
    local_output_states: tuple[Mapping[str, Any], ...]
    formal_coefficients: tuple[int, ...]
    tag_transport_multipliers: tuple[int, ...]
    final_coefficients: tuple[int, ...]
    boundary_labels: tuple[int, ...]
    assignments_checked: int
    nonzero_left_assignments: int
    nonzero_right_assignments: int
    verification_status: str
    semantic_digest: str = ""
    local_input_semantic_digest: str = ""
    local_output_semantic_digests: tuple[str, ...] = ()
    boundary_leg_count: int = 0
    expected_assignments: int = 0
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    input_tag_transport_factor: int = 1
    output_tag_transport_factors: tuple[int, ...] = ()
    total_tag_transport_multipliers: tuple[int, ...] = ()
    boundary_order_transport_factors: tuple[int, ...] = ()
    boundary_order_transport_records: tuple[
        tuple[Mapping[str, Any], ...], ...
    ] = ()
    tensor_ratio_residual_transport_factors: tuple[int, ...] = ()


@dataclass(frozen=True)
class ProvenanceRoute:
    """One complete route into a coefficient bucket."""

    coefficient: int
    moves: tuple[Mapping[str, Any], ...] = ()
    label: str = ""
    # Keep this field last so the historical positional constructor
    # ProvenanceRoute(coefficient, moves, label) retains its meaning.  ``None``
    # is reserved for legacy serialized routes that predate an independently
    # recorded coefficient-chain anchor.
    initial_route_coefficient: int | None = None


@dataclass
class ExactWebTerm:
    coefficient: int
    web: ExactRibbonState
    routes: list[ProvenanceRoute] = field(default_factory=list)


@dataclass
class ExactPairTerm:
    coefficient: int
    w: ExactRibbonState
    x: ExactRibbonState
    routes: list[ProvenanceRoute] = field(default_factory=list)


@dataclass(frozen=True)
class ExactRelationBranch:
    relation: str
    coefficient_multiplier: int
    web: ExactRibbonState
    local_data: Mapping[str, Any]
    certificate: ExactLocalRuleCertificate


def require_production_relation_certificate(
    branch: ExactRelationBranch,
    *,
    input_web: ExactRibbonState | None = None,
) -> ExactLocalRuleCertificate:
    """Reject a relation branch unless its mandatory certificate is complete.

    This guard lives at the expansion boundary, so custom schedulers and audit
    callers cannot accidentally send an internal draft branch into production.
    """

    certificate = branch.certificate
    if certificate.schema != LOCAL_RULE_CERTIFICATE_SCHEMA:
        raise UncertifiedRelationError(
            f"Relation {branch.relation} uses unsupported certificate schema "
            f"{certificate.schema!r}."
        )
    if not certificate.production_approved:
        raise UncertifiedRelationError(
            f"Relation {branch.relation} has no production-approved certificate."
        )
    if certificate.verification_status != "verified_pointwise_tensor_identity":
        raise UncertifiedRelationError(
            f"Relation {branch.relation} is not pointwise tensor verified."
        )
    positional_branch_relations = _CERTIFICATE_BRANCH_RELATION_BINDINGS.get(
        certificate.relation
    )
    relation_name_matches = (
        certificate.relation == branch.relation
        or branch.relation.startswith(f"{certificate.relation}_")
        or (
            positional_branch_relations is not None
            and branch.relation in positional_branch_relations
        )
    )
    if not relation_name_matches:
        raise UncertifiedRelationError(
            f"Relation {branch.relation} uses a certificate for "
            f"{certificate.relation}."
        )
    if certificate.convention != LOCAL_RULE_TENSOR_CONVENTION:
        raise UncertifiedRelationError(
            f"Relation {branch.relation} uses unsupported tensor convention "
            f"{certificate.convention!r}."
        )
    if (
        not str(certificate.paper_reference).strip()
        or str(certificate.paper_reference).lower().startswith("internal")
    ):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} has no external paper reference."
        )
    state_payloads = (
        certificate.input_state,
        *certificate.output_states,
        certificate.local_input_state,
        *certificate.local_output_states,
    )
    if any(
        state.get("schema") != "problem3.exact_ribbon_state.v4"
        for state in state_payloads
    ):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} certificate does not embed exact v4 states."
        )
    if (
        not certificate.semantic_digest
        or certificate.certificate_id != certificate.semantic_digest
    ):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} has an invalid semantic certificate digest."
        )
    if int(branch.coefficient_multiplier) not in certificate.final_coefficients:
        raise UncertifiedRelationError(
            f"Relation {branch.relation} coefficient is absent from its certificate."
        )
    branch_count = len(certificate.output_states)
    if not all(
        len(values) == branch_count
        for values in (
            certificate.local_output_states,
            certificate.local_output_semantic_digests,
            certificate.formal_coefficients,
            certificate.total_tag_transport_multipliers,
            certificate.final_coefficients,
            certificate.output_tag_transport_factors,
            certificate.boundary_order_transport_factors,
            certificate.boundary_order_transport_records,
            certificate.tensor_ratio_residual_transport_factors,
        )
    ):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} certificate branch vectors disagree."
        )
    if branch_count == 1 and int(certificate.nonzero_right_assignments) <= 0:
        raise UncertifiedRelationError(
            f"Relation {branch.relation} has no unique single-branch tensor ratio: "
            "its certified RHS tensor is identically zero."
        )
    if not str(certificate.local_input_semantic_digest):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} has no local-input semantic digest."
        )
    reconstructed_boundary_factors = tuple(
        _boundary_order_transport_factor(records)
        for records in certificate.boundary_order_transport_records
    )
    if reconstructed_boundary_factors != tuple(
        certificate.boundary_order_transport_factors
    ):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} boundary-order transport records do "
            "not reconstruct their certified factors."
        )
    reconstructed_transports = tuple(
        int(certificate.input_tag_transport_factor)
        * int(output_factor)
        * int(boundary_factor)
        * int(tensor_residual)
        for output_factor, boundary_factor, tensor_residual in zip(
            certificate.output_tag_transport_factors,
            certificate.boundary_order_transport_factors,
            certificate.tensor_ratio_residual_transport_factors,
        )
    )
    if any(
        int(value) not in {-1, 1}
        for value in certificate.tensor_ratio_residual_transport_factors
    ) or (
        any(
            int(value) != 1
            for value in certificate.tensor_ratio_residual_transport_factors
        )
        and branch_count != 1
    ):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} has an invalid tensor-ratio residual."
        )
    if reconstructed_transports != tuple(
        certificate.total_tag_transport_multipliers
    ):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} total transport is not reconstructed "
            "from its vertex and boundary-order permutations."
        )
    derived_coefficients = tuple(
        int(formal) * int(transport)
        for formal, transport in zip(
            certificate.formal_coefficients,
            certificate.total_tag_transport_multipliers,
        )
    )
    if derived_coefficients != tuple(certificate.final_coefficients):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} violates formal coefficient × tag "
            "transport = final coefficient."
        )
    if input_web is not None:
        observed_input_digest = exact_state_digest(input_web)
        if str(certificate.input_state.get("digest")) != observed_input_digest:
            raise UncertifiedRelationError(
                f"Relation {branch.relation} certificate input digest does not "
                "match the expanded exact state."
            )
    output_digest = exact_state_digest(branch.web)
    certified_outputs = [
        index
        for index, state in enumerate(certificate.output_states)
        if str(state.get("digest")) == output_digest
        and int(certificate.final_coefficients[index])
        == int(branch.coefficient_multiplier)
    ]
    if not certified_outputs:
        raise UncertifiedRelationError(
            f"Relation {branch.relation} output/coefficient pair is absent from "
            "its certificate."
        )
    if positional_branch_relations is not None and not any(
        index < len(positional_branch_relations)
        and positional_branch_relations[index] == branch.relation
        for index in certified_outputs
    ):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} is not bound to its certified output "
            f"position for {certificate.relation}."
        )
    if certificate.assignments_checked != certificate.expected_assignments:
        raise UncertifiedRelationError(
            f"Relation {branch.relation} certificate is not exhaustive."
        )
    if certificate.boundary_leg_count != len(certificate.boundary_labels):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} certificate boundary-leg metadata "
            "does not match its labels."
        )
    if certificate.expected_assignments != 4**certificate.boundary_leg_count:
        raise UncertifiedRelationError(
            f"Relation {branch.relation} certificate has an invalid exhaustive "
            "assignment count."
        )
    if not all(
        0 <= int(value) <= int(certificate.assignments_checked)
        for value in (
            certificate.nonzero_left_assignments,
            certificate.nonzero_right_assignments,
        )
    ):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} certificate has invalid nonzero "
            "assignment counts."
        )
    if _certificate_semantic_digest(
        _certificate_semantic_core_from_certificate(certificate)
    ) != str(certificate.semantic_digest):
        raise UncertifiedRelationError(
            f"Relation {branch.relation} semantic certificate digest does not "
            "match its certified fields."
        )
    return certificate


def _internal_relation_draft_certificate(relation: str) -> ExactLocalRuleCertificate:
    """Create a non-exportable certificate used only while assembling a relation.

    Public relation functions replace this object before returning.  Keeping a
    typed object, rather than ``None``, makes the branch interface total and
    lets production reject accidental draft leakage deterministically.
    """

    return ExactLocalRuleCertificate(
        schema=LOCAL_RULE_CERTIFICATE_SCHEMA,
        certificate_id="internal-draft",
        relation=str(relation),
        paper_reference="internal assembly only",
        convention=LOCAL_RULE_TENSOR_CONVENTION,
        production_approved=False,
        affected_vertices=(),
        input_state={},
        output_states=(),
        local_input_state={},
        local_output_states=(),
        formal_coefficients=(),
        tag_transport_multipliers=(),
        final_coefficients=(),
        boundary_labels=(),
        assignments_checked=0,
        nonzero_left_assignments=0,
        nonzero_right_assignments=0,
        verification_status="internal_draft",
        diagnostics={"exportable": False},
    )


@dataclass(frozen=True)
class ExactDoubleEdgeMove:
    kind: str
    white: int
    black: int
    ordinary_physical_edges: tuple[int, ...]
    bundle_id: int | None = None


@dataclass(frozen=True)
class ExactFigure43Move:
    """A Figure 43 configuration in order (top-left, top-right, bottom-right, bottom-left)."""

    cycle: tuple[int, int, int, int]
    side_kinds: tuple[str, str, str, str]
    facial_turn: int
    rule: str = "opposite_hourglasses"


@dataclass(frozen=True)
class _AuditOnlyTaggedFigure9Candidate:
    """Figure 9 contraction of a 2-hourglass/2-hourglass chain."""

    center: int
    bundles: tuple[int, int]
    outer_vertices: tuple[int, int]


def _root_shift(web: ExactRibbonState, vertex: int, target_root: int) -> int:
    """Counterclockwise slots from the live tensor tag to an exact root."""

    cycle = vertex_cycle_ccw(web, int(vertex))
    current = web.tag_after_ccw[int(vertex)]
    if current not in cycle or int(target_root) not in cycle:
        raise ValueError(
            f"Cannot compare roots {current} and {target_root} at vertex {vertex}."
        )
    return (cycle.index(int(target_root)) - cycle.index(current)) % len(cycle)


def _local_intrinsic_tag_transport(
    web: ExactRibbonState, vertices: Iterable[int]
) -> tuple[int, dict[int, int], dict[int, int], dict[int, int]]:
    """Return intrinsic-root transport data on one relation support only."""

    sign = 1
    shifts: dict[int, int] = {}
    roots: dict[int, int] = {}
    factors: dict[int, int] = {}
    for vertex in sorted(set(int(value) for value in vertices)):
        if web.color.get(vertex) == VertexColor.BOUNDARY:
            continue
        root = intrinsic_tag_root(web, vertex)
        if root is None:
            raise UncertifiedRelationError(
                f"Affected vertex {vertex} has no paper-supported intrinsic tag root."
            )
        factor = int(paper_tag_transport_sign(web, vertex, int(root), r=4))
        roots[vertex] = int(root)
        shifts[vertex] = int(_root_shift(web, vertex, int(root)))
        factors[vertex] = factor
        sign *= factor
    return int(sign), shifts, roots, factors


def _local_square_paper_tag_transport(
    web: ExactRibbonState, vertices: Iterable[int]
) -> tuple[
    int,
    dict[int, int],
    dict[int, int],
    dict[int, int],
    dict[int, str],
]:
    """Return paper tag transport on a possibly non-fully-reduced square state.

    GPPSS Definition 6.3 supplies an intrinsic base-face sector only for fully
    reduced contracted graphs.  Square reduction intermediates can fall
    outside that domain.  On those vertices the exact live tag is retained as
    the paper root; Figure 2 together with Lemma 2.5 then transports that tag
    through the local rewrite, and the exhaustive tensor certificate remains
    the fail-closed check on the resulting coefficient.
    """

    sign = 1
    shifts: dict[int, int] = {}
    roots: dict[int, int] = {}
    factors: dict[int, int] = {}
    modes: dict[int, str] = {}
    for vertex in sorted(set(int(value) for value in vertices)):
        if web.color.get(vertex) == VertexColor.BOUNDARY:
            continue
        try:
            root = intrinsic_tag_root(web, vertex)
            mode = "gppss_definition_6_3_intrinsic"
        except ValueError:
            root = web.tag_after_ccw.get(vertex)
            mode = "figure2_live_tag_transport_outside_definition_6_3_domain"
        if root is None:
            raise UncertifiedRelationError(
                f"Affected square vertex {vertex} has no supported tag root."
            )
        factor = int(paper_tag_transport_sign(web, vertex, int(root), r=4))
        roots[vertex] = int(root)
        shifts[vertex] = int(_root_shift(web, vertex, int(root)))
        factors[vertex] = factor
        modes[vertex] = mode
        sign *= factor
    return int(sign), shifts, roots, factors, modes


_DOUBLE_EDGE_TENSOR_COEFFICIENT_CACHE: dict[tuple[Hashable, Hashable], int] = {}
_SQUARE_TENSOR_COEFFICIENT_CACHE: dict[tuple[Hashable, Hashable], int] = {}


def _multiplicity_closed_local_vertices(
    web: ExactRibbonState, seeds: Iterable[int]
) -> tuple[int, ...]:
    """Close a local vertex set under every incident multiplicity-two edge."""

    selected_order = list(dict.fromkeys(int(vertex) for vertex in seeds))
    selected = set(selected_order)
    position = 0
    while position < len(selected_order):
        vertex = int(selected_order[position])
        position += 1
        cycle = vertex_cycle_ccw(web, vertex)
        root = web.tag_after_ccw.get(vertex)
        if root in cycle:
            offset = cycle.index(int(root))
            cycle = cycle[offset:] + cycle[:offset]
        for dart in cycle:
            if web.bundle_of[dart] is None:
                continue
            other = int(web.vertex_of[web.mate[dart]])
            if web.color.get(other) == VertexColor.BOUNDARY or other in selected:
                continue
            selected.add(other)
            selected_order.append(other)
    return tuple(selected_order)


def _certified_square_local_coefficient(
    left: ExactRibbonState,
    right: ExactRibbonState,
    left_vertices: Sequence[int],
    right_vertices: Sequence[int],
) -> int:
    """Return the unique tagged Figure-2 coefficient from exact cyclic data.

    Figure 2 has formal coefficient +1.  Definition 6.3 determines the tag
    roots on fully reduced graphs; outside that definition's domain, the
    transported live roots and Definition 2.8 vertex tensors determine the
    tag-transport multiplier.  This routine is intentionally blind to vertex
    colors as arithmetic inputs, IDs, topology names, ancestry, and bundle
    IDs.  The complete certificate independently rechecks the returned ratio
    on all boundary assignments.
    """

    boundary_port_labels = exact_local_boundary_port_label_map(
        left, left_vertices
    )
    local_left = extract_exact_local_tensor_fixture(
        left,
        left_vertices,
        boundary_label_by_outside_dart=boundary_port_labels,
    )
    local_right = extract_exact_local_tensor_fixture(
        right,
        right_vertices,
        boundary_label_by_outside_dart=boundary_port_labels,
    )
    cache_key = (canonical_web_key(local_left), canonical_web_key(local_right))
    cached = _SQUARE_TENSOR_COEFFICIENT_CACHE.get(cache_key)
    if cached is not None:
        return int(cached)

    left_tensor = exact_boundary_tensor_fast(local_left)
    right_tensor = exact_boundary_tensor_fast(local_right)
    if set(left_tensor) != set(right_tensor):
        raise UncertifiedRelationError(
            "Tagged square input and output do not share one boundary type."
        )
    ratios: set[int] = set()
    for assignment, left_value in left_tensor.items():
        right_value = int(right_tensor[assignment])
        left_value = int(left_value)
        if right_value == 0:
            if left_value != 0:
                raise UncertifiedRelationError(
                    "Tagged square input is not proportional to its output."
                )
            continue
        if left_value % right_value:
            raise UncertifiedRelationError(
                "Tagged square transport coefficient is not integral."
            )
        ratios.add(left_value // right_value)
    if ratios not in ({1}, {-1}):
        raise UncertifiedRelationError(
            f"Tagged square relation has no unique sign ratio: {sorted(ratios)}."
        )
    coefficient = int(next(iter(ratios)))
    _SQUARE_TENSOR_COEFFICIENT_CACHE[cache_key] = coefficient
    return coefficient


def _certified_single_branch_local_coefficient(
    left: ExactRibbonState,
    right: ExactRibbonState,
    vertices: Sequence[int],
) -> tuple[int, int]:
    """Return the unique Definition-2.8 coefficient ``left = c * right``.

    The closure may contain an adjacent hourglass endpoint, so this checks the
    complete tagged input/output gauge rather than multiplying independent
    input-endpoint shifts.  Results are cached by the two exact local ribbon
    states; the relation has at most four simple boundary legs in production.
    """

    boundary_port_labels = exact_local_boundary_port_label_map(left, vertices)
    local_left = extract_exact_local_tensor_fixture(
        left,
        vertices,
        boundary_label_by_outside_dart=boundary_port_labels,
    )
    local_right = extract_exact_local_tensor_fixture(
        right,
        vertices,
        boundary_label_by_outside_dart=boundary_port_labels,
    )
    cache_key = (
        canonical_web_key(local_left),
        canonical_web_key(local_right),
    )
    cached = _DOUBLE_EDGE_TENSOR_COEFFICIENT_CACHE.get(cache_key)
    assignments_checked = 4 ** sum(
        color == VertexColor.BOUNDARY for color in local_left.color.values()
    )
    if cached is not None:
        return int(cached), int(assignments_checked)

    left_tensor = exact_boundary_tensor(local_left)
    right_tensor = exact_boundary_tensor(local_right)
    if set(left_tensor) != set(right_tensor):
        raise ValueError("Tagged double-edge tensors do not share one boundary type.")
    ratios: set[int] = set()
    for assignment in left_tensor:
        left_value = int(left_tensor[assignment])
        right_value = int(right_tensor[assignment])
        if right_value == 0:
            if left_value != 0:
                raise ValueError(
                    "Tagged double-edge input is not proportional to its output."
                )
            continue
        if left_value % right_value:
            raise ValueError("Tagged double-edge coefficient is not integral.")
        ratios.add(left_value // right_value)
    if len(ratios) != 1:
        raise ValueError(
            f"Tagged double-edge relation has no single coefficient: {sorted(ratios)}."
        )
    coefficient = int(next(iter(ratios)))
    if abs(coefficient) != 2:
        raise ValueError(
            f"GPPSS Figure 43 [2] relation produced coefficient {coefficient}, not ±2."
        )
    _DOUBLE_EDGE_TENSOR_COEFFICIENT_CACHE[cache_key] = coefficient
    return coefficient, int(assignments_checked)


def exact_wrench_relation(
    web: ExactRibbonState, bundle_id: int, *, _certify: bool = True
) -> tuple[ExactRelationBranch, ExactRelationBranch]:
    """Expose the q=1 Figure-42 relation in its canonical tagged gauge.

    At each endpoint the relation tag is the Definition-6.3 gap between the
    two simple outside edges.  Moving the live tag there uses Lemma 2.5 and is
    counted at both the black and white endpoint.  The persistent two-strand
    frame remains topology/replay metadata; it is not an additional scalar.
    The two rooted endpoint cycles face one another in the paper picture, so
    :func:`apply_exact_wrench` maps their same-index ports to the geometric
    crossing before attaching the printed coefficients ``(+1, -1)``.
    """

    endpoints = {
        web.vertex_of[dart]
        for dart, candidate in web.bundle_of.items()
        if candidate == int(bundle_id)
    }
    if len(endpoints) != 2:
        raise ValueError(
            f"Wrench bundle {bundle_id} does not have exactly two endpoints."
        )
    outside_ports = {
        int(vertex): tuple(
            dart
            for dart in vertex_cycle_ccw(web, int(vertex))
            if web.bundle_of[dart] != int(bundle_id)
        )
        for vertex in endpoints
    }
    if any(
        len(darts) != 2
        or any(
            web.edge_kind[dart] != EdgeKind.ORDINARY
            or web.bundle_of[dart] is not None
            for dart in darts
        )
        for darts in outside_ports.values()
    ):
        raise ValueError(
            "The exact Wrench relation requires two simple ordinary outside "
            "ports at each endpoint; cable-valued outside ports need their "
            "dedicated contraction relation."
        )
    adjacent_bundles = sorted(
        {
            int(candidate)
            for dart, candidate in web.bundle_of.items()
            if candidate is not None
            and candidate != int(bundle_id)
            and web.vertex_of[dart] in endpoints
        }
    )
    frame_roots = web.bundle_frame_root.get(int(bundle_id), {})
    if endpoints != set(frame_roots):
        raise ValueError(
            f"Bundle {bundle_id} has endpoints {sorted(endpoints)} but frame roots "
            f"for {sorted(frame_roots)}."
        )
    adjacent_frame_transport: list[dict[str, Any]] = []
    for adjacent in adjacent_bundles:
        for vertex, root in sorted(web.bundle_frame_root[int(adjacent)].items()):
            if vertex not in endpoints:
                continue
            selected_root = frame_roots.get(vertex)
            if selected_root is None:
                continue
            cycle = vertex_cycle_ccw(web, vertex)
            adjacent_frame_transport.append(
                {
                    "bundle": int(adjacent),
                    "vertex": int(vertex),
                    "selected_bundle_root": int(selected_root),
                    "adjacent_bundle_root": int(root),
                    "selected_to_adjacent_shift": (
                        cycle.index(int(root)) - cycle.index(int(selected_root))
                    )
                    % len(cycle),
                }
            )
    relation_tag_roots = {
        int(vertex): int(intrinsic_tag_root(web, int(vertex)))
        for vertex in endpoints
    }
    tag_transport_factors = {
        int(vertex): paper_tag_transport_sign(
            web, int(vertex), int(relation_tag_roots[int(vertex)]), r=4
        )
        for vertex in endpoints
    }
    tag_transport_multiplier = 1
    for factor in tag_transport_factors.values():
        tag_transport_multiplier *= int(factor)
    # Drawn-dart offsets are retained for audit readability only.  They are
    # not the mathematical tag-transport rule for a multiplicity-two edge.
    relation_tag_shifts = {
        int(vertex): _root_shift(
            web, int(vertex), int(relation_tag_roots[int(vertex)])
        )
        for vertex in endpoints
    }
    white = next(
        vertex for vertex in endpoints if web.color[vertex] == VertexColor.WHITE
    )
    black = next(
        vertex for vertex in endpoints if web.color[vertex] == VertexColor.BLACK
    )

    def framed_strands(vertex: int) -> tuple[int, int]:
        cycle = vertex_cycle_ccw(web, int(vertex))
        root = int(frame_roots[int(vertex)])
        position = cycle.index(root)
        rotated = cycle[position:] + cycle[:position]
        strands = tuple(
            dart for dart in rotated if web.bundle_of[dart] == int(bundle_id)
        )
        if len(strands) != 2:
            raise ValueError(
                f"Bundle {bundle_id} does not expose two framed strands at {vertex}."
            )
        return strands  # type: ignore[return-value]

    white_strands = framed_strands(int(white))
    black_strands = framed_strands(int(black))
    strand_matching = tuple(
        black_strands.index(web.mate[dart]) for dart in white_strands
    )
    if strand_matching == (0, 1):
        strand_matching_multiplier = 1
    elif strand_matching == (1, 0):
        strand_matching_multiplier = -1
    else:  # pragma: no cover - exact two-strand validation makes this impossible
        raise ValueError(
            f"Bundle {bundle_id} has invalid framed strand matching {strand_matching}."
        )
    relation_tagged = copy.deepcopy(web)
    for vertex, root in relation_tag_roots.items():
        relation_tagged.tag_after_ccw[int(vertex)] = int(root)
        paper_incident_edge_blocks_clockwise(relation_tagged, int(vertex))
    branches = apply_exact_wrench(relation_tagged, int(bundle_id))
    drafts = tuple(
        ExactRelationBranch(
            relation=f"wrench_{branch.name}",
            coefficient_multiplier=(
                int(branch.formal_coefficient)
                * tag_transport_multiplier
            ),
            web=branch.web,
            certificate=_internal_relation_draft_certificate(
                f"wrench_{branch.name}"
            ),
            local_data={
                "bundle": int(bundle_id),
                "branch": branch.name,
                "formal_coefficient": int(branch.formal_coefficient),
                "frame_roots": {
                    str(vertex): int(root) for vertex, root in sorted(frame_roots.items())
                },
                "live_tag_roots": {
                    str(vertex): int(web.tag_after_ccw[vertex])
                    for vertex in sorted(endpoints)
                },
                "relation_tag_roots": {
                    str(vertex): int(root)
                    for vertex, root in sorted(relation_tag_roots.items())
                },
                "relation_tag_shifts": {
                    str(vertex): int(shift)
                    for vertex, shift in sorted(relation_tag_shifts.items())
                },
                "tag_transport_factors": {
                    str(vertex): int(factor)
                    for vertex, factor in sorted(tag_transport_factors.items())
                },
                "tag_transport_multiplier": tag_transport_multiplier,
                "strand_matching": strand_matching,
                "strand_matching_multiplier": strand_matching_multiplier,
                "strand_matching_affects_coefficient": False,
                "coefficient_source": (
                    "GPPSS Figure 42 geometric crossing-minus-parallel "
                    "coefficient times Lemma 2.5 tag transport at both "
                    "internal endpoints; endpoint CCW port lists are mapped "
                    "in opposite boundary orientations"
                ),
                "port_pairing": branch.port_pairing,
                "consumed_adjacent_bundles": adjacent_bundles,
                "consumed_adjacent_frame_transport": adjacent_frame_transport,
            },
        )
        for branch in branches
    )
    if not _certify:
        return drafts  # type: ignore[return-value]
    local_input = extract_exact_local_tensor_fixture(
        web, (int(white), int(black))
    )
    local_drafts = exact_wrench_relation(
        local_input, int(bundle_id), _certify=False
    )
    certified = certify_exact_relation_branches(
        relation="wrench",
        paper_reference="GPPSS Figure 42; project Proposition 2.15",
        input_web=web,
        output_branches=drafts,
        local_input=local_input,
        local_output_branches=local_drafts,
        formal_coefficients=tuple(
            int(branch.local_data["formal_coefficient"]) for branch in drafts
        ),
        tag_transport_multipliers=(
            int(tag_transport_multiplier),
            int(tag_transport_multiplier),
        ),
        input_paper_tag_roots=relation_tag_roots,
        diagnostics={
            "bundle": int(bundle_id),
            "coefficient_excludes_topology_names": True,
            "coefficient_excludes_vertex_colors": True,
            "coefficient_excludes_source_ancestry": True,
            "coefficient_excludes_bundle_id": True,
        },
    )
    return certified  # type: ignore[return-value]


def detect_exact_double_tridents(web: ExactRibbonState) -> tuple[tuple[int, int], ...]:
    """Ordinary internal white-black edges eligible for exact six-term expansion."""

    validate_exact_web(web)
    result = []
    for darts in _physical_edges(web).values():
        if web.edge_kind[darts[0]] != EdgeKind.ORDINARY:
            continue
        u, v = _endpoints(web, darts)
        if {web.color[u], web.color[v]} != {VertexColor.WHITE, VertexColor.BLACK}:
            continue
        white = u if web.color[u] == VertexColor.WHITE else v
        black = u if web.color[u] == VertexColor.BLACK else v
        central = {
            int(vertex): next(
                dart for dart in darts if web.vertex_of[dart] == int(vertex)
            )
            for vertex in (white, black)
        }
        endpoint_set = {int(white), int(black)}
        admissible = True
        for vertex in (white, black):
            cycle = vertex_cycle_ccw(web, int(vertex))
            outside = tuple(dart for dart in cycle if dart != central[int(vertex)])
            if (
                len(cycle) != 4
                or len(outside) != 3
                or any(
                    web.edge_kind[dart] != EdgeKind.ORDINARY
                    or web.bundle_of[dart] is not None
                    or web.vertex_of[web.mate[dart]] in endpoint_set
                    for dart in outside
                )
            ):
                admissible = False
                break
        if not admissible:
            continue
        result.append((white, black))
    return tuple(sorted(set(result)))


def exact_double_trident_relation(
    web: ExactRibbonState,
    white: int,
    black: int,
    *,
    _certify: bool = True,
) -> tuple[ExactRelationBranch, ...]:
    """Expose the six exact Double Trident terms with paper and tag signs separate."""

    if (int(white), int(black)) not in set(detect_exact_double_tridents(web)):
        raise ValueError(
            "The exact Double Trident relation requires one central ordinary "
            "edge and three simple ordinary outside ports at each endpoint."
        )

    drafts = tuple(
        ExactRelationBranch(
            relation="double_trident",
            coefficient_multiplier=(
                int(branch.paper_coefficient)
                * int(branch.tag_transport_multiplier)
            ),
            web=branch.web,
            certificate=_internal_relation_draft_certificate("double_trident"),
            local_data={
                "white": int(white),
                "black": int(black),
                "permutation": branch.permutation,
                "paper_coefficient": branch.paper_coefficient,
                "endpoint_tag_transport_multiplier": (
                    branch.endpoint_tag_transport_multiplier
                ),
                "boundary_order_multiplier": branch.boundary_order_multiplier,
                "boundary_paper_order": branch.boundary_paper_order,
                "boundary_engine_order": branch.boundary_engine_order,
                "boundary_order_permutation": (
                    branch.boundary_order_permutation
                ),
                "tag_transport_multiplier": branch.tag_transport_multiplier,
                "coefficient_source": (
                    "printed -sgn(permutation), transported from the two "
                    "live tags and from the paper diagram's opposite "
                    "three-port boundary orientations"
                ),
                "port_pairing": branch.port_pairing,
            },
        )
        for branch in apply_exact_double_trident(web, int(white), int(black))
    )
    if not _certify:
        return drafts
    local_input = extract_exact_local_tensor_fixture(
        web, (int(white), int(black))
    )
    local_drafts = exact_double_trident_relation(
        local_input, int(white), int(black), _certify=False
    )
    central_roots = {}
    for vertex, opposite in ((int(white), int(black)), (int(black), int(white))):
        candidates = [
            int(dart)
            for dart in vertex_cycle_ccw(web, vertex)
            if web.vertex_of[web.mate[dart]] == opposite
            and web.edge_kind[dart] == EdgeKind.ORDINARY
            and web.bundle_of[dart] is None
        ]
        if len(candidates) != 1:
            raise UncertifiedRelationError(
                "Double Trident has no unique displayed central-edge tag root."
            )
        central_roots[vertex] = candidates[0]
    return certify_exact_relation_branches(
        relation="double_trident",
        paper_reference="project Figure 3; GPPSS antisymmetrizer relation",
        input_web=web,
        output_branches=drafts,
        local_input=local_input,
        local_output_branches=local_drafts,
        formal_coefficients=tuple(
            int(branch.local_data["paper_coefficient"]) for branch in drafts
        ),
        tag_transport_multipliers=tuple(
            int(branch.local_data["tag_transport_multiplier"])
            for branch in drafts
        ),
        input_paper_tag_roots=central_roots,
        boundary_order_transport_records=tuple(
            (
                _make_boundary_order_transport_record(
                    kind="opposite_three_port_boundary_orientation",
                    paper_reference=(
                        "project Figure 3 Double Trident; the two displayed "
                        "three-port boundaries face in opposite orientations"
                    ),
                    paper_order=("B2", "B1", "B0"),
                    engine_order=("B0", "B1", "B2"),
                    diagnostics={
                        "recorded_permutation": branch.local_data[
                            "boundary_order_permutation"
                        ],
                        "exact_label_binding": {
                            f"B{index}": int(port)
                            for index, port in enumerate(
                                branch.local_data["boundary_engine_order"]
                            )
                        },
                    },
                ),
            )
            for branch in drafts
        ),
        diagnostics={
            "coefficient_excludes_permutation_name": False,
            "formal_coefficient_is_minus_permutation_sign": True,
            "coefficient_excludes_vertex_colors": True,
            "coefficient_excludes_source_ancestry": True,
        },
    )


def expand_exact_pair_term(
    term: ExactPairTerm,
    *,
    side: str,
    branches: Iterable[ExactRelationBranch],
) -> list[ExactPairTerm]:
    """Apply precomputed exact branches to W or X without dropping route history."""

    side = str(side).upper()
    if side not in {"W", "X"}:
        raise ValueError("Exact pair expansion side must be W or X.")
    source_routes = _route_list(term.coefficient, term.routes)
    result = []
    for branch in branches:
        source_web = term.w if side == "W" else term.x
        certificate = require_production_relation_certificate(
            branch, input_web=source_web
        )
        move_record_base = {
            "side": side,
            "relation": branch.relation,
            "coefficient_multiplier": branch.coefficient_multiplier,
            "local_data": dict(branch.local_data),
            "output_digest": exact_state_digest(branch.web),
            "certificate_schema": certificate.schema,
            "certificate_digest": certificate.semantic_digest,
            "certificate_relation": certificate.relation,
        }
        routes = []
        for route in source_routes:
            output_coefficient = (
                int(route.coefficient) * int(branch.coefficient_multiplier)
            )
            move_record = {
                **move_record_base,
                "input_route_coefficient": int(route.coefficient),
                "output_route_coefficient": output_coefficient,
            }
            routes.append(
                ProvenanceRoute(
                    coefficient=output_coefficient,
                    moves=tuple(route.moves) + (move_record,),
                    label=route.label,
                    initial_route_coefficient=route.initial_route_coefficient,
                )
            )
        result.append(
            ExactPairTerm(
                coefficient=int(term.coefficient) * int(branch.coefficient_multiplier),
                w=branch.web if side == "W" else copy.deepcopy(term.w),
                x=branch.web if side == "X" else copy.deepcopy(term.x),
                routes=routes,
            )
        )
    return result


def expand_exact_web_term(
    term: ExactWebTerm,
    *,
    branches: Iterable[ExactRelationBranch],
    side: str = "X",
) -> list[ExactWebTerm]:
    """Apply exact branches to one weighted web with complete provenance.

    Relation-diamond audits must compare linear combinations before a passive
    pairing web is introduced.  Keeping this operation beside
    :func:`expand_exact_pair_term` ensures that those audits use exactly the
    same coefficient multiplication, state digest, and replay record as the
    production scheduler.
    """

    side = str(side).upper()
    if side not in {"W", "X"}:
        raise ValueError("Exact web expansion side must be W or X.")
    source_routes = _route_list(term.coefficient, term.routes)
    result = []
    for branch in branches:
        certificate = require_production_relation_certificate(
            branch, input_web=term.web
        )
        move_record_base = {
            "side": side,
            "relation": branch.relation,
            "coefficient_multiplier": branch.coefficient_multiplier,
            "local_data": dict(branch.local_data),
            "output_digest": exact_state_digest(branch.web),
            "certificate_schema": certificate.schema,
            "certificate_digest": certificate.semantic_digest,
            "certificate_relation": certificate.relation,
        }
        routes = []
        for route in source_routes:
            output_coefficient = (
                int(route.coefficient) * int(branch.coefficient_multiplier)
            )
            move_record = {
                **move_record_base,
                "input_route_coefficient": int(route.coefficient),
                "output_route_coefficient": output_coefficient,
            }
            routes.append(
                ProvenanceRoute(
                    coefficient=output_coefficient,
                    moves=tuple(route.moves) + (move_record,),
                    label=route.label,
                    initial_route_coefficient=route.initial_route_coefficient,
                )
            )
        result.append(
            ExactWebTerm(
                coefficient=int(term.coefficient)
                * int(branch.coefficient_multiplier),
                web=branch.web,
                routes=routes,
            )
        )
    return result


EXACT_STATE_KEY_SCHEMA = "problem3.exact_ribbon_key.v4"
EXACT_SQUARE_GAUGE_KEY_SCHEMA = "problem3.exact_square_gauge_key.v1"


def exact_state_digest(web: ExactRibbonState) -> str:
    """Versioned audit digest of the complete canonical exact state."""

    validate_exact_web(web)
    payload = (EXACT_STATE_KEY_SCHEMA, canonical_web_key(web))
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def exact_local_tensor_fixture_semantic_digest(web: ExactRibbonState) -> str:
    """Digest a local fixture modulo simultaneous dummy boundary-slot names."""

    payload = (
        "problem3.local_tensor_fixture_unlabeled_boundary.v1",
        canonical_unlabeled_boundary_web_key(web),
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def _certificate_jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _certificate_jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_certificate_jsonable(item) for item in value]
    if isinstance(value, (EdgeKind, VertexColor)):
        return int(value)
    return value


def serialize_exact_local_rule_certificate(
    certificate: ExactLocalRuleCertificate,
) -> dict[str, Any]:
    """Return the stable JSON object written to certificate audit JSONL."""

    # Every nested state, vertex record, and diagnostics payload is normalized
    # when the immutable certificate is constructed.  ``json.dumps`` natively
    # serializes the remaining tuples as arrays.  Recursively copying the
    # complete 30-KB payload here used to dominate large closure runs while
    # producing byte-for-byte identical JSONL after ``sort_keys=True``.
    return {
        name: getattr(certificate, name)
        for name in certificate.__dataclass_fields__
    }


def exact_certificate_state_payload(web: ExactRibbonState) -> dict[str, Any]:
    """Losslessly serialize one tagged state for a local-rule certificate."""

    validate_exact_web(web)
    return {
        "schema": "problem3.exact_ribbon_state.v4",
        "digest_schema": EXACT_STATE_KEY_SCHEMA,
        "digest": exact_state_digest(web),
        "vertices": [
            {
                "id": int(vertex),
                "color": int(web.color[vertex]),
                "boundary_label": web.boundary_label.get(vertex),
                "tag_after_ccw": web.tag_after_ccw.get(vertex),
                "tensor_valence": int(
                    web.tensor_valence.get(
                        vertex,
                        1 if web.color[vertex] == VertexColor.BOUNDARY else 4,
                    )
                ),
            }
            for vertex in sorted(web.color)
        ],
        "darts": [
            {
                "id": int(dart),
                "vertex": int(web.vertex_of[dart]),
                "mate": int(web.mate[dart]),
                "next_ccw": int(web.next_ccw[dart]),
                "edge_kind": int(web.edge_kind[dart]),
                "physical_edge": int(web.physical_edge_of[dart]),
                "bundle": web.bundle_of[dart],
                "source_edge": web.source_edge_id.get(dart),
                "source_local_strand": web.source_local_strand.get(dart),
            }
            for dart in sorted(web.vertex_of)
        ],
        "bundle_frames": {
            str(bundle): {
                str(vertex): int(root)
                for vertex, root in sorted(roots.items())
            }
            for bundle, roots in sorted(web.bundle_frame_root.items())
        },
        "square_undo_stack": [
            exact_certificate_state_payload(snapshot)
            for snapshot in web.square_undo_stack
        ],
        "square_undo_multipliers": [
            int(value) for value in web.square_undo_multipliers
        ],
    }


def _certificate_vertex_record(
    web: ExactRibbonState,
    vertex: int,
    *,
    phase: str,
    branch_index: int | None,
    paper_tag_root: int | None = None,
) -> dict[str, Any]:
    cycle = tuple(int(dart) for dart in vertex_cycle_ccw(web, int(vertex)))
    live_root = web.tag_after_ccw.get(int(vertex))
    if live_root is None:
        raise UncertifiedRelationError(
            f"Internal certificate vertex {vertex} has no live tag root."
        )
    if paper_tag_root is None:
        paper_tag_root = int(live_root)
    if int(paper_tag_root) not in cycle:
        raise UncertifiedRelationError(
            f"Paper tag root {paper_tag_root} is not incident to vertex {vertex}."
        )
    try:
        blocks = paper_incident_edge_blocks_clockwise(web, int(vertex))
    except (ValueError, RuntimeError) as exc:
        raise UncertifiedRelationError(
            f"Cannot read paper edge blocks at vertex {vertex}: {exc}"
        ) from exc
    multiplicities = tuple(len(block) for block in blocks)
    permutation_sign = int(
        paper_tag_transport_sign(web, int(vertex), int(paper_tag_root), r=4)
    )
    live_position = cycle.index(int(live_root))
    paper_position = cycle.index(int(paper_tag_root))
    tag_permutation = tuple(
        (index + paper_position - live_position) % len(cycle)
        for index in range(len(cycle))
    )
    return {
        "phase": str(phase),
        "branch_index": branch_index,
        "vertex": int(vertex),
        "color": int(web.color[int(vertex)]),
        "ccw_dart_cycle": list(cycle),
        "edge_multiplicities_clockwise_from_live_tag": list(multiplicities),
        "live_tag_root": int(live_root),
        "paper_tag_root": int(paper_tag_root),
        "tag_permutation": list(tag_permutation),
        "tag_permutation_sign": permutation_sign,
    }


def _certificate_semantic_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _certificate_jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _affected_vertex_semantic_signatures(
    affected_vertices: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Remove temporary IDs and sort affected vertices by their local role."""

    signatures = [
        {
            "phase": item["phase"],
            "branch_index": item["branch_index"],
            "color": item["color"],
            "edge_multiplicities": item[
                "edge_multiplicities_clockwise_from_live_tag"
            ],
            "tag_permutation": item["tag_permutation"],
            "tag_permutation_sign": item["tag_permutation_sign"],
        }
        for item in affected_vertices
    ]
    return tuple(
        sorted(
            signatures,
            key=lambda item: json.dumps(
                _certificate_jsonable(item),
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    )


def _permutation_sign_from_orders(
    paper_order: Sequence[Any],
    engine_order: Sequence[Any],
) -> tuple[tuple[int, ...], int]:
    """Return the exact permutation and parity between two labeled orders."""

    paper = tuple(_certificate_jsonable(item) for item in paper_order)
    engine = tuple(_certificate_jsonable(item) for item in engine_order)
    paper_keys = tuple(
        json.dumps(item, sort_keys=True, separators=(",", ":")) for item in paper
    )
    engine_keys = tuple(
        json.dumps(item, sort_keys=True, separators=(",", ":")) for item in engine
    )
    if (
        len(paper_keys) < 2
        or len(set(paper_keys)) != len(paper_keys)
        or set(paper_keys) != set(engine_keys)
    ):
        raise UncertifiedRelationError(
            "A boundary-order transport needs two equal sets of distinct labels."
        )
    positions = {item: index for index, item in enumerate(paper_keys)}
    permutation = tuple(positions[item] for item in engine_keys)
    inversions = sum(
        permutation[left] > permutation[right]
        for left in range(len(permutation))
        for right in range(left + 1, len(permutation))
    )
    return permutation, (-1 if inversions % 2 else 1)


def _make_boundary_order_transport_record(
    *,
    kind: str,
    paper_reference: str,
    paper_order: Sequence[Any],
    engine_order: Sequence[Any],
    diagnostics: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Build a replayable non-vertex transport from explicit labeled orders."""

    if not str(kind).strip():
        raise UncertifiedRelationError("Boundary transport kind is empty.")
    if (
        not str(paper_reference).strip()
        or str(paper_reference).lower().startswith("internal")
    ):
        raise UncertifiedRelationError(
            "Boundary-order transport has no external paper reference."
        )
    permutation, sign = _permutation_sign_from_orders(
        paper_order, engine_order
    )
    return {
        "kind": str(kind),
        "paper_reference": str(paper_reference),
        "paper_order": _certificate_jsonable(tuple(paper_order)),
        "engine_order": _certificate_jsonable(tuple(engine_order)),
        "permutation": list(permutation),
        "permutation_sign": int(sign),
        "diagnostics": _certificate_jsonable(diagnostics or {}),
    }


def _validated_boundary_order_transport_record(
    record: Mapping[str, Any],
) -> Mapping[str, Any]:
    rebuilt = _make_boundary_order_transport_record(
        kind=str(record.get("kind", "")),
        paper_reference=str(record.get("paper_reference", "")),
        paper_order=tuple(record.get("paper_order", ())),
        engine_order=tuple(record.get("engine_order", ())),
        diagnostics=(
            record.get("diagnostics", {})
            if isinstance(record.get("diagnostics", {}), Mapping)
            else {}
        ),
    )
    if _certificate_jsonable(record) != _certificate_jsonable(rebuilt):
        raise UncertifiedRelationError(
            "Boundary-order transport record contains a stale or fitted sign."
        )
    binding = rebuilt.get("diagnostics", {}).get("exact_label_binding")
    if binding is not None:
        if not isinstance(binding, Mapping):
            raise UncertifiedRelationError(
                "Boundary-order exact-label binding is not a mapping."
            )
        ordered_labels = {
            str(item)
            for item in (
                *rebuilt["paper_order"],
                *rebuilt["engine_order"],
            )
        }
        if set(str(label) for label in binding) != ordered_labels:
            raise UncertifiedRelationError(
                "Boundary-order exact-label binding does not cover its roles."
            )
        bound_values = tuple(
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            for value in binding.values()
        )
        if len(set(bound_values)) != len(bound_values):
            raise UncertifiedRelationError(
                "Boundary-order exact-label binding is not injective."
            )
    return rebuilt


def _boundary_order_transport_factor(
    records: Sequence[Mapping[str, Any]],
) -> int:
    factor = 1
    for record in records:
        checked = _validated_boundary_order_transport_record(record)
        factor *= int(checked["permutation_sign"])
    return int(factor)


def _boundary_order_transport_semantic_record(
    record: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return the identifier-stable coefficient-bearing part of a record."""

    checked = _validated_boundary_order_transport_record(record)
    return {
        key: value
        for key, value in checked.items()
        if key != "diagnostics"
    }


def _certificate_semantic_core_from_certificate(
    certificate: ExactLocalRuleCertificate,
) -> dict[str, Any]:
    """Reconstruct the exact payload authenticated by a semantic digest."""

    return {
        "schema": certificate.schema,
        "relation": certificate.relation,
        "paper_reference": certificate.paper_reference,
        "convention": certificate.convention,
        "production_approved": bool(certificate.production_approved),
        "input_digest": certificate.input_state.get("digest"),
        "output_digests": [
            state.get("digest") for state in certificate.output_states
        ],
        "local_input_semantic_digest": (
            certificate.local_input_semantic_digest
        ),
        "local_output_semantic_digests": tuple(
            certificate.local_output_semantic_digests
        ),
        "formal_coefficients": tuple(certificate.formal_coefficients),
        "tag_transport_multipliers": tuple(
            certificate.tag_transport_multipliers
        ),
        "input_tag_transport_factor": int(
            certificate.input_tag_transport_factor
        ),
        "output_tag_transport_factors": tuple(
            certificate.output_tag_transport_factors
        ),
        "total_tag_transport_multipliers": tuple(
            certificate.total_tag_transport_multipliers
        ),
        "boundary_order_transport_factors": tuple(
            certificate.boundary_order_transport_factors
        ),
        "boundary_order_transport_records": tuple(
            tuple(
                _boundary_order_transport_semantic_record(record)
                for record in records
            )
            for records in certificate.boundary_order_transport_records
        ),
        "tensor_ratio_residual_transport_factors": tuple(
            certificate.tensor_ratio_residual_transport_factors
        ),
        "final_coefficients": tuple(certificate.final_coefficients),
        "boundary_labels": tuple(certificate.boundary_labels),
        "boundary_leg_count": int(certificate.boundary_leg_count),
        "assignments_checked": int(certificate.assignments_checked),
        "expected_assignments": int(certificate.expected_assignments),
        "nonzero_left_assignments": int(
            certificate.nonzero_left_assignments
        ),
        "nonzero_right_assignments": int(
            certificate.nonzero_right_assignments
        ),
        "verification_status": str(certificate.verification_status),
        "affected_vertex_signatures": _affected_vertex_semantic_signatures(
            certificate.affected_vertices
        ),
    }


def certify_exact_relation_branches(
    *,
    relation: str,
    paper_reference: str,
    input_web: ExactRibbonState,
    output_branches: Sequence[ExactRelationBranch],
    local_input: ExactRibbonState,
    local_output_branches: Sequence[ExactRelationBranch],
    formal_coefficients: Sequence[int],
    tag_transport_multipliers: Sequence[int],
    input_paper_tag_roots: Mapping[int, int] | None = None,
    output_paper_tag_roots: Sequence[Mapping[int, int]] | None = None,
    boundary_order_transport_records: Sequence[
        Sequence[Mapping[str, Any]]
    ] | None = None,
    allow_single_branch_tensor_ratio_residual: bool = False,
    production_approved: bool = True,
    diagnostics: Mapping[str, Any] | None = None,
) -> tuple[ExactRelationBranch, ...]:
    """Attach one complete pointwise tensor certificate to all relation branches."""

    outputs = tuple(output_branches)
    local_outputs = tuple(local_output_branches)
    formal = tuple(int(value) for value in formal_coefficients)
    transports = tuple(int(value) for value in tag_transport_multipliers)
    final = tuple(int(branch.coefficient_multiplier) for branch in outputs)
    local_final = tuple(
        int(branch.coefficient_multiplier) for branch in local_outputs
    )
    size = len(outputs)
    if not size or not (
        len(local_outputs) == len(formal) == len(transports) == size
    ):
        raise UncertifiedRelationError(
            f"Relation {relation} has inconsistent certificate branch counts."
        )
    raw_boundary_records = (
        tuple(tuple(records) for records in boundary_order_transport_records)
        if boundary_order_transport_records is not None
        else tuple(() for _branch in outputs)
    )
    if len(raw_boundary_records) != size:
        raise UncertifiedRelationError(
            f"Relation {relation} has inconsistent boundary transport branches."
        )
    boundary_records = tuple(
        tuple(
            _validated_boundary_order_transport_record(record)
            for record in records
        )
        for records in raw_boundary_records
    )
    boundary_transport_factors = tuple(
        _boundary_order_transport_factor(records)
        for records in boundary_records
    )
    if final != local_final:
        raise UncertifiedRelationError(
            f"Relation {relation} changed coefficients when localized: "
            f"{final} != {local_final}."
        )
    predicted = tuple(
        int(coefficient) * int(transport)
        for coefficient, transport in zip(formal, transports)
    )
    if predicted != final:
        raise UncertifiedRelationError(
            f"Relation {relation} has formal/transport coefficients {predicted}, "
            f"but returns {final}."
        )
    try:
        tensor = certify_exact_linear_relation_fast(
            local_input,
            tuple(
                (int(branch.coefficient_multiplier), branch.web)
                for branch in local_outputs
            ),
        )
    except (ValueError, RuntimeError) as exc:
        raise UncertifiedRelationError(
            f"Relation {relation} failed its exhaustive local tensor identity: {exc}"
        ) from exc
    if tuple(int(value) for value in tensor.branch_coefficients) != final:
        raise UncertifiedRelationError(
            f"Relation {relation} tensor coefficients do not equal final coefficients."
        )
    if size == 1 and int(tensor.nonzero_right_assignments) <= 0:
        raise UncertifiedRelationError(
            f"Relation {relation} has no unique single-branch tensor ratio: "
            "its RHS tensor is identically zero."
        )
    boundary_leg_count = len(tensor.boundary_labels)
    expected_assignments = 4**boundary_leg_count
    if int(tensor.assignments_checked) != expected_assignments:
        raise UncertifiedRelationError(
            f"Relation {relation} checked {tensor.assignments_checked} assignments; "
            f"expected 4^{boundary_leg_count}={expected_assignments}."
        )

    roots = {
        int(vertex): int(root)
        for vertex, root in (input_paper_tag_roots or {}).items()
    }
    output_roots = (
        tuple(
            {
                int(vertex): int(root)
                for vertex, root in branch_roots.items()
            }
            for branch_roots in output_paper_tag_roots
        )
        if output_paper_tag_roots is not None
        else tuple({} for _branch in local_outputs)
    )
    if len(output_roots) != size:
        raise UncertifiedRelationError(
            f"Relation {relation} has inconsistent output paper-tag branches."
        )
    affected: list[Mapping[str, Any]] = []
    for vertex in sorted(local_input.color):
        if local_input.color[vertex] == VertexColor.BOUNDARY:
            continue
        affected.append(
            _certificate_vertex_record(
                local_input,
                int(vertex),
                phase="input",
                branch_index=None,
                paper_tag_root=roots.get(int(vertex)),
            )
        )
    for index, branch in enumerate(local_outputs):
        for vertex in sorted(branch.web.color):
            if branch.web.color[vertex] == VertexColor.BOUNDARY:
                continue
            affected.append(
                _certificate_vertex_record(
                    branch.web,
                    int(vertex),
                    phase="output",
                    branch_index=index,
                    paper_tag_root=output_roots[index].get(int(vertex)),
                )
            )

    input_transport_factor = 1
    output_transport_factors = [1 for _branch in local_outputs]
    for item in affected:
        sign = int(item["tag_permutation_sign"])
        if item["phase"] == "input":
            input_transport_factor *= sign
        else:
            output_transport_factors[int(item["branch_index"])] *= sign

    # A transport multiplier is certificate evidence, not an adjustable sign.
    # Every factor must therefore be reconstructed from the recorded cyclic
    # orders and paper/live tag permutations above.  In particular, a
    # relation implementation may not insert a residual "RHS orientation"
    # or other legacy sign merely because it makes a multi-branch identity
    # close.  A single-branch relation is the one exception: once its RHS is
    # proved nonzero, the exhaustive pointwise identity determines one unique
    # tensor ratio, so an explicitly enabled residual sign is independently
    # reconstructible from the certified fixtures.  Multi-branch residuals
    # still require explicit paper/engine order records.
    vertex_and_boundary_transports = tuple(
        int(input_transport_factor)
        * int(output_factor)
        * int(boundary_factor)
        for output_factor, boundary_factor in zip(
            output_transport_factors,
            boundary_transport_factors,
        )
    )
    tensor_ratio_residuals = tuple(1 for _branch in outputs)
    if transports != vertex_and_boundary_transports:
        if not (allow_single_branch_tensor_ratio_residual and size == 1):
            raise UncertifiedRelationError(
                f"Relation {relation} declares tag transports {transports}, but "
                "its recorded input/output cyclic-order permutations reconstruct "
                f"{vertex_and_boundary_transports}. An unrepresented residual "
                "basis transport is prohibited."
            )
        base = int(vertex_and_boundary_transports[0])
        if base not in {-1, 1} or int(transports[0]) not in {-1, 1}:
            raise UncertifiedRelationError(
                f"Relation {relation} has a non-sign tensor-ratio residual."
            )
        tensor_ratio_residuals = (int(transports[0]) * base,)
    reconstructed_transports = tuple(
        int(base) * int(residual)
        for base, residual in zip(
            vertex_and_boundary_transports,
            tensor_ratio_residuals,
        )
    )

    input_state = exact_certificate_state_payload(input_web)
    output_states = tuple(
        exact_certificate_state_payload(branch.web) for branch in outputs
    )
    local_input_state = exact_certificate_state_payload(local_input)
    local_output_states = tuple(
        exact_certificate_state_payload(branch.web) for branch in local_outputs
    )
    local_input_semantic_digest = exact_local_tensor_fixture_semantic_digest(
        local_input
    )
    local_output_semantic_digests = tuple(
        exact_local_tensor_fixture_semantic_digest(branch.web)
        for branch in local_outputs
    )
    semantic_core = {
        "schema": LOCAL_RULE_CERTIFICATE_SCHEMA,
        "relation": str(relation),
        "paper_reference": str(paper_reference),
        "convention": LOCAL_RULE_TENSOR_CONVENTION,
        "production_approved": bool(production_approved),
        "input_digest": input_state["digest"],
        "output_digests": [state["digest"] for state in output_states],
        "local_input_semantic_digest": local_input_semantic_digest,
        "local_output_semantic_digests": local_output_semantic_digests,
        "formal_coefficients": formal,
        "tag_transport_multipliers": transports,
        "input_tag_transport_factor": input_transport_factor,
        "output_tag_transport_factors": output_transport_factors,
        "total_tag_transport_multipliers": reconstructed_transports,
        "boundary_order_transport_factors": boundary_transport_factors,
        "boundary_order_transport_records": tuple(
            tuple(
                _boundary_order_transport_semantic_record(record)
                for record in records
            )
            for records in boundary_records
        ),
        "tensor_ratio_residual_transport_factors": (
            tensor_ratio_residuals
        ),
        "final_coefficients": final,
        "boundary_labels": tensor.boundary_labels,
        "boundary_leg_count": boundary_leg_count,
        "assignments_checked": int(tensor.assignments_checked),
        "expected_assignments": expected_assignments,
        "nonzero_left_assignments": int(tensor.nonzero_left_assignments),
        "nonzero_right_assignments": int(tensor.nonzero_right_assignments),
        "verification_status": "verified_pointwise_tensor_identity",
        "affected_vertex_signatures": _affected_vertex_semantic_signatures(
            affected
        ),
    }
    digest = _certificate_semantic_digest(semantic_core)
    certificate = ExactLocalRuleCertificate(
        schema=LOCAL_RULE_CERTIFICATE_SCHEMA,
        certificate_id=digest,
        relation=str(relation),
        paper_reference=str(paper_reference),
        convention=LOCAL_RULE_TENSOR_CONVENTION,
        production_approved=bool(production_approved),
        affected_vertices=tuple(affected),
        input_state=input_state,
        output_states=output_states,
        local_input_state=local_input_state,
        local_output_states=local_output_states,
        formal_coefficients=formal,
        tag_transport_multipliers=transports,
        final_coefficients=final,
        boundary_labels=tuple(int(value) for value in tensor.boundary_labels),
        assignments_checked=int(tensor.assignments_checked),
        nonzero_left_assignments=int(tensor.nonzero_left_assignments),
        nonzero_right_assignments=int(tensor.nonzero_right_assignments),
        verification_status="verified_pointwise_tensor_identity",
        semantic_digest=digest,
        local_input_semantic_digest=local_input_semantic_digest,
        local_output_semantic_digests=local_output_semantic_digests,
        boundary_leg_count=boundary_leg_count,
        expected_assignments=expected_assignments,
        diagnostics=_certificate_jsonable(diagnostics or {}),
        input_tag_transport_factor=int(input_transport_factor),
        output_tag_transport_factors=tuple(
            int(value) for value in output_transport_factors
        ),
        total_tag_transport_multipliers=reconstructed_transports,
        boundary_order_transport_factors=boundary_transport_factors,
        boundary_order_transport_records=boundary_records,
        tensor_ratio_residual_transport_factors=(
            tensor_ratio_residuals
        ),
    )
    return tuple(replace(branch, certificate=certificate) for branch in outputs)


def replay_exact_local_rule_certificate(
    certificate: ExactLocalRuleCertificate,
    local_input: ExactRibbonState,
    local_outputs: Sequence[ExactRibbonState],
) -> Any:
    """Recompute every local, coefficient-bearing fact in a certificate.

    This is deliberately stronger than deserializing the embedded states.  It
    reconstructs the complete affected-vertex record from those states and
    reruns the exhaustive pointwise tensor identity.  Release validation uses
    this function so a ledger cannot pass by merely repeating stored counts or
    a stored ``verification_status`` string.
    """

    outputs = tuple(local_outputs)
    if certificate.schema != LOCAL_RULE_CERTIFICATE_SCHEMA:
        raise UncertifiedRelationError(
            f"Cannot replay unsupported certificate schema {certificate.schema!r}."
        )
    if len(outputs) != len(certificate.local_output_states):
        raise UncertifiedRelationError(
            "Certificate replay has the wrong number of local output states."
        )
    if exact_state_digest(local_input) != str(
        certificate.local_input_state.get("digest", "")
    ):
        raise UncertifiedRelationError(
            "Certificate replay local-input digest does not match."
        )
    if tuple(exact_state_digest(web) for web in outputs) != tuple(
        str(payload.get("digest", ""))
        for payload in certificate.local_output_states
    ):
        raise UncertifiedRelationError(
            "Certificate replay local-output digests do not match."
        )
    replayed_input_semantic_digest = exact_local_tensor_fixture_semantic_digest(
        local_input
    )
    replayed_output_semantic_digests = tuple(
        exact_local_tensor_fixture_semantic_digest(web) for web in outputs
    )
    if replayed_input_semantic_digest != str(
        certificate.local_input_semantic_digest
    ) or replayed_output_semantic_digests != tuple(
        str(value) for value in certificate.local_output_semantic_digests
    ):
        raise UncertifiedRelationError(
            "Certificate replay local semantic digests do not match."
        )

    recorded: dict[tuple[str, int | None, int], Mapping[str, Any]] = {}
    for raw in certificate.affected_vertices:
        if not isinstance(raw, Mapping):
            raise UncertifiedRelationError(
                "Certificate affected-vertex record is not a mapping."
            )
        phase = str(raw.get("phase", ""))
        raw_index = raw.get("branch_index")
        branch_index = None if raw_index is None else int(raw_index)
        vertex = int(raw.get("vertex"))
        key = (phase, branch_index, vertex)
        if key in recorded:
            raise UncertifiedRelationError(
                f"Certificate repeats affected-vertex record {key}."
            )
        recorded[key] = raw

    expected_keys: set[tuple[str, int | None, int]] = set()

    def check_state_vertices(
        web: ExactRibbonState,
        *,
        phase: str,
        branch_index: int | None,
    ) -> None:
        for vertex in sorted(web.color):
            if web.color[vertex] == VertexColor.BOUNDARY:
                continue
            key = (phase, branch_index, int(vertex))
            expected_keys.add(key)
            raw = recorded.get(key)
            if raw is None:
                raise UncertifiedRelationError(
                    f"Certificate is missing affected-vertex record {key}."
                )
            rebuilt = _certificate_vertex_record(
                web,
                int(vertex),
                phase=phase,
                branch_index=branch_index,
                paper_tag_root=int(raw.get("paper_tag_root")),
            )
            if _certificate_jsonable(raw) != _certificate_jsonable(rebuilt):
                raise UncertifiedRelationError(
                    f"Certificate affected-vertex record {key} is stale or fitted."
                )

    check_state_vertices(local_input, phase="input", branch_index=None)
    for index, web in enumerate(outputs):
        check_state_vertices(web, phase="output", branch_index=index)
    if set(recorded) != expected_keys:
        extras = sorted(set(recorded) - expected_keys)
        raise UncertifiedRelationError(
            f"Certificate has extraneous affected-vertex records: {extras}."
        )

    tensor = certify_exact_linear_relation_fast(
        local_input,
        tuple(
            (int(coefficient), web)
            for coefficient, web in zip(
                certificate.final_coefficients,
                outputs,
            )
        ),
    )
    replayed = {
        "boundary_labels": tuple(int(value) for value in tensor.boundary_labels),
        "branch_coefficients": tuple(
            int(value) for value in tensor.branch_coefficients
        ),
        "assignments_checked": int(tensor.assignments_checked),
        "nonzero_left_assignments": int(tensor.nonzero_left_assignments),
        "nonzero_right_assignments": int(tensor.nonzero_right_assignments),
    }
    stored = {
        "boundary_labels": tuple(int(value) for value in certificate.boundary_labels),
        "branch_coefficients": tuple(
            int(value) for value in certificate.final_coefficients
        ),
        "assignments_checked": int(certificate.assignments_checked),
        "nonzero_left_assignments": int(
            certificate.nonzero_left_assignments
        ),
        "nonzero_right_assignments": int(
            certificate.nonzero_right_assignments
        ),
    }
    if replayed != stored:
        raise UncertifiedRelationError(
            f"Certificate tensor replay disagrees with stored evidence: "
            f"{replayed} != {stored}."
        )
    if int(tensor.assignments_checked) != 4 ** len(tensor.boundary_labels):
        raise UncertifiedRelationError(
            "Certificate tensor replay was not exhaustive over all boundary assignments."
        )
    if _certificate_semantic_digest(
        _certificate_semantic_core_from_certificate(certificate)
    ) != str(certificate.semantic_digest):
        raise UncertifiedRelationError(
            "Certificate tensor replay found a semantic digest mismatch."
        )
    return tensor


def normalize_exact_square_gauge(
    web: ExactRibbonState,
) -> tuple[ExactRibbonState, int, dict[int, int]]:
    """Return the finite mathematical gauge used for square equivalence.

    Raw v4 states deliberately retain two kinds of data that a literal square
    rewrite need not reproduce:

    * ``source_edge_id`` / ``source_local_strand`` are replay lineage; and
    * a live tensor tag can differ from the intrinsic root by an
      antisymmetric sign.

    This normalizer masks only that lineage and transports every live tag to
    its intrinsic root.  It does **not** alter the mate involution, cyclic
    order, vertex colors, boundary labels, hourglass bundles, or persistent
    ``bundle_frame_root`` data.  In particular, independent hourglass frames
    remain part of the mathematical state.

    The returned sign ``nu`` uses the established convention
    ``S_raw = nu * S_intrinsic``.  A raw relation ``S -> c T`` therefore has
    gauge coefficient ``nu(S) * c * nu(T)``.

    Square histories are rejected rather than silently discarded: callers
    must explicitly serialize/replay them or construct a standalone state.
    The function is intentionally square-specific because intrinsic tag
    normalization is not yet total on every possible closed/lower-valence
    skein output.
    """

    validate_exact_web(web)
    if web.square_undo_stack or web.square_undo_multipliers:
        raise ValueError(
            "Square-gauge normalization requires a standalone state with no undo history."
        )
    normalized, normalization_sign, shifts = normalize_intrinsic_tags(web)
    for dart in normalized.source_edge_id:
        normalized.source_edge_id[dart] = None
    for dart in normalized.source_local_strand:
        normalized.source_local_strand[dart] = None
    validate_exact_web(normalized)
    return normalized, int(normalization_sign), {
        int(vertex): int(shift) for vertex, shift in shifts.items()
    }


def exact_square_gauge_key(web: ExactRibbonState) -> Hashable:
    """Canonical finite square-equivalence key, distinct from raw v4 replay."""

    normalized, _sign, _shifts = normalize_exact_square_gauge(web)
    return (EXACT_SQUARE_GAUGE_KEY_SCHEMA, canonical_web_key(normalized))


def exact_square_gauge_digest(web: ExactRibbonState) -> str:
    """SHA-256 digest of :func:`exact_square_gauge_key`."""

    return hashlib.sha256(
        repr(exact_square_gauge_key(web)).encode("utf-8")
    ).hexdigest()


def exact_square_gauge_coefficient(
    source: ExactRibbonState,
    raw_coefficient: int,
    target: ExactRibbonState,
) -> int:
    """Transport one raw Figure-2 coefficient into the square gauge."""

    _source, source_sign, _source_shifts = normalize_exact_square_gauge(source)
    _target, target_sign, _target_shifts = normalize_exact_square_gauge(target)
    return int(source_sign) * int(raw_coefficient) * int(target_sign)


def _frame_blind_web_key(web: ExactRibbonState) -> Hashable:
    """Mask temporary source-edge provenance for a square inverse assertion.

    Square moves create temporary physical edges, so an inverse need not
    restore their catalogue provenance bit literally.  Bundle frames and
    square undo provenance remain visible: losing either changes later
    relation signs and must fail the inverse assertion.
    """

    masked = copy.deepcopy(web)
    for dart in masked.source_edge_id:
        masked.source_edge_id[dart] = None
    return canonical_web_key(masked)


def _square_topology_key(web: ExactRibbonState) -> Hashable:
    """Compare a generated square output to an exact saved parent topology."""

    masked = copy.deepcopy(web)
    for dart in masked.source_edge_id:
        masked.source_edge_id[dart] = None
    masked.bundle_frame_root = {}
    masked.square_undo_stack = ()
    masked.square_undo_multipliers = ()
    return canonical_untagged_web_key(masked)


def validated_provenance_routes(
    coefficient: int,
    routes: Iterable[ProvenanceRoute],
) -> list[ProvenanceRoute]:
    """Return a complete route ledger whose signed total is ``coefficient``."""

    result = list(routes)
    if not result:
        result = [
            ProvenanceRoute(
                coefficient=int(coefficient),
                initial_route_coefficient=int(coefficient),
            )
        ]
    if sum(int(route.coefficient) for route in result) != int(coefficient):
        raise AssertionError(
            "Provenance route coefficients do not sum to the enclosing term coefficient."
        )
    return result


def _route_list(coefficient: int, routes: Iterable[ProvenanceRoute]) -> list[ProvenanceRoute]:
    """Backward-compatible internal alias for route-ledger normalization."""

    return validated_provenance_routes(coefficient, routes)


def consolidate_exact_web_terms(terms: Iterable[ExactWebTerm]) -> list[ExactWebTerm]:
    """Merge only exact ribbon-isomorphic states and retain every incoming route."""

    buckets: dict[Hashable, ExactWebTerm] = {}
    for term in terms:
        validate_exact_web(term.web)
        key = canonical_web_key(term.web)
        routes = _route_list(term.coefficient, term.routes)
        if key not in buckets:
            buckets[key] = ExactWebTerm(int(term.coefficient), copy.deepcopy(term.web), routes)
        else:
            buckets[key].coefficient += int(term.coefficient)
            buckets[key].routes.extend(routes)
    return [term for term in buckets.values() if term.coefficient]


def consolidate_exact_pair_terms(terms: Iterable[ExactPairTerm]) -> list[ExactPairTerm]:
    """Consolidate a pairing state without changing either selected presentation.

    Canonical keys remove temporary dart/vertex IDs only.  A different benzene
    presentation, a different rooted cyclic order, or a different hourglass
    mate involution is a different bucket.
    """

    buckets: dict[tuple[Hashable, Hashable], ExactPairTerm] = {}
    for term in terms:
        validate_exact_web(term.w)
        validate_exact_web(term.x)
        key = (canonical_web_key(term.w), canonical_web_key(term.x))
        routes = _route_list(term.coefficient, term.routes)
        if key not in buckets:
            buckets[key] = ExactPairTerm(
                int(term.coefficient), copy.deepcopy(term.w), copy.deepcopy(term.x), routes
            )
        else:
            buckets[key].coefficient += int(term.coefficient)
            buckets[key].routes.extend(routes)
    return [term for term in buckets.values() if term.coefficient]


def _physical_edges(web: HalfEdgeWeb) -> dict[int, tuple[int, int]]:
    members: dict[int, list[int]] = {}
    for dart, physical in web.physical_edge_of.items():
        members.setdefault(physical, []).append(dart)
    result: dict[int, tuple[int, int]] = {}
    for physical, darts in members.items():
        if len(darts) != 2 or web.mate[darts[0]] != darts[1]:
            raise ValueError(f"Physical edge {physical} is not one exact mate pair.")
        result[physical] = (darts[0], darts[1])
    return result


def _endpoints(web: HalfEdgeWeb, darts: Sequence[int]) -> tuple[int, int]:
    if len(darts) != 2:
        raise ValueError("An exact physical edge must have two darts.")
    return web.vertex_of[darts[0]], web.vertex_of[darts[1]]


def _detect_audit_only_tagged_figure9_candidates(
    web: ExactRibbonState,
) -> tuple[_AuditOnlyTaggedFigure9Candidate, ...]:
    """Detect the r=4, a=2 contraction move from Figure 9.

    The center is incident to two complete 2-hourglasses and no simple edge.
    Each same-colored outer vertex exposes two remaining ports.  Those ports
    may be two ordinary edges or one complete surviving hourglass block; the
    latter is required to contract two consecutive cables inside a longer
    hourglass chain without opening that surviving cable as a generic Wrench.
    """

    validate_exact_web(web)
    moves = []
    for center in sorted(web.color):
        try:
            topology = two_hourglass_contraction_topology(web, int(center))
        except ValueError:
            continue
        port_modes = []
        valid = True
        for block in topology.residual_blocks:
            if all(
                web.edge_kind[dart] == EdgeKind.ORDINARY
                and web.bundle_of[dart] is None
                for dart in block
            ):
                port_modes.append("ordinary")
                continue
            surviving = {web.bundle_of[dart] for dart in block}
            if (
                len(surviving) == 1
                and None not in surviving
                and all(
                    web.edge_kind[dart] == EdgeKind.HOURGLASS_STRAND
                    for dart in block
                )
            ):
                port_modes.append("hourglass")
                continue
            valid = False
            break
        # The ordinary/ordinary Figure 9 move and the one-sided cable case
        # have independent exact checks.  A contraction embedded between two
        # surviving cables is deliberately withheld until separately audited.
        if not valid or port_modes.count("hourglass") > 1:
            continue
        moves.append(
            _AuditOnlyTaggedFigure9Candidate(
                center=topology.center,
                bundles=topology.ordered_bundles,
                outer_vertices=topology.ordered_outer_vertices,
            )
        )
    return tuple(moves)


def _apply_audit_only_tagged_figure9_candidate(
    web: ExactRibbonState,
    move: _AuditOnlyTaggedFigure9Candidate,
) -> ExactRelationBranch:
    """Apply Figure 9 with its sign certified by direct q=1 tensors."""

    available = {
        (candidate.center, frozenset(candidate.bundles)): candidate
        for candidate in _detect_audit_only_tagged_figure9_candidates(web)
    }
    key = (int(move.center), frozenset(int(bundle) for bundle in move.bundles))
    if key not in available:
        raise ValueError("The requested two-hourglass contraction is no longer applicable.")
    move = available[key]
    topology = two_hourglass_contraction_topology(
        web, move.center, move.bundles
    )
    result = copy.deepcopy(web)
    local_vertices = {
        int(move.center),
        *[int(vertex) for vertex in topology.ordered_outer_vertices],
    }
    merged_cycle = tuple(int(dart) for dart in topology.merged_cycle)
    external = set(merged_cycle)
    local_darts = {
        dart for dart, vertex in result.vertex_of.items() if vertex in local_vertices
    }
    internal = {
        dart
        for dart in local_darts
        if result.vertex_of[result.mate[dart]] in local_vertices
    }
    if local_darts != internal | external or internal & external:
        raise ValueError(
            "Two-hourglass contraction did not partition local darts into "
            "internal bundle strands and four outside ports."
        )
    retained = int(topology.ordered_outer_vertices[0])
    removed_vertices = local_vertices - {retained}
    consumed_bundles = {int(bundle) for bundle in topology.ordered_bundles}
    slot_maps = {
        int(vertex): {int(old): int(new) for old, new in mapping}
        for vertex, mapping in zip(
            topology.ordered_outer_vertices, topology.outer_slot_maps
        )
    }
    surviving_frame_transport: dict[int, dict[int, tuple[int, int]]] = {}
    for bundle, roots in result.bundle_frame_root.items():
        if int(bundle) in consumed_bundles:
            continue
        local_roots: dict[int, tuple[int, int]] = {}
        for vertex, root in roots.items():
            if int(vertex) not in local_vertices:
                continue
            if int(vertex) not in slot_maps or int(root) not in slot_maps[int(vertex)]:
                raise ValueError(
                    "A surviving hourglass frame has no Figure 9 slot transport."
                )
            local_roots[int(vertex)] = (
                int(root),
                int(slot_maps[int(vertex)][int(root)]),
            )
        if not local_roots:
            continue
        surviving_frame_transport[int(bundle)] = local_roots
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
        for dart in internal:
            mapping.pop(dart, None)
    for dart in merged_cycle:
        result.vertex_of[dart] = retained
    for dart, following in zip(merged_cycle, merged_cycle[1:] + merged_cycle[:1]):
        result.next_ccw[dart] = following
    for vertex in removed_vertices:
        result.color.pop(vertex, None)
        result.boundary_label.pop(vertex, None)
        result.tag_after_ccw.pop(vertex, None)
        result.source_xy.pop(vertex, None)
        result.tensor_valence.pop(vertex, None)
    # Install a temporary valid root.  The generated tensor receives its
    # intrinsic presentation root after every surviving frame is transported;
    # no consumed live tag is allowed to change the output topology.
    result.tag_after_ccw[retained] = int(merged_cycle[0])
    result.tensor_valence[retained] = 4
    transported_surviving_frames: dict[int, dict[str, Any]] = {}
    for bundle, local_roots in surviving_frame_transport.items():
        roots = result.bundle_frame_root[int(bundle)]
        for vertex in local_roots:
            roots.pop(int(vertex), None)
        transported_root_values = {
            int(projected) for _source, projected in local_roots.values()
        }
        if len(transported_root_values) != 1:
            raise ValueError(
                "A surviving hourglass cannot meet the contraction through "
                "two distinct local endpoints."
            )
        transported_root = int(next(iter(transported_root_values)))
        if retained in roots and roots[retained] != transported_root:
            raise ValueError(
                "Two surviving hourglass frame roots would collide at the "
                "contracted vertex."
            )
        roots[retained] = transported_root
        transported_surviving_frames[int(bundle)] = {
            "retained_vertex": retained,
            "root": transported_root,
            "source_roots": {
                str(vertex): int(source)
                for vertex, (source, _projected) in sorted(local_roots.items())
            },
            "projected_roots": {
                str(vertex): int(projected)
                for vertex, (_source, projected) in sorted(local_roots.items())
            },
            "rebased_from_consumed_dart": any(
                int(source) != int(projected)
                for source, projected in local_roots.values()
            ),
        }
    for bundle in consumed_bundles:
        result.bundle_frame_root.pop(int(bundle), None)
    expected_surviving_frames = copy.deepcopy(result.bundle_frame_root)
    refresh_bundle_frames(result)
    if result.bundle_frame_root != expected_surviving_frames:
        raise ValueError(
            "Figure 9 attempted to reconstruct, rather than transport, a "
            "surviving hourglass frame."
        )
    validate_exact_web(result)
    try:
        generated_tag = intrinsic_tag_root(result, retained)
        generated_tag_convention = "intrinsic_generated_tensor"
        intrinsic_tag_error = None
    except (ValueError, RuntimeError) as exc:
        # A generated ordinary tensor can lack a Definition 6.3 base-face tag
        # (including on a closed component).  Choose among its four exact tag
        # presentations by the ID-free complete-state key.  This avoids both a
        # scheduler crash and a raw-dart-dependent algebraic root.  If several
        # candidates tie, they are isomorphic exact states; the position only
        # makes replay deterministic for this raw serialization.
        candidates = []
        for position, root in enumerate(merged_cycle):
            candidate = copy.deepcopy(result)
            candidate.tag_after_ccw[retained] = int(root)
            validate_exact_web(candidate)
            candidates.append(
                (repr(canonical_web_key(candidate)), int(position), int(root))
            )
        _key, _position, generated_tag = min(candidates)
        generated_tag_convention = "canonical_generated_tensor_fallback"
        intrinsic_tag_error = f"{type(exc).__name__}: {exc}"
    if generated_tag is None or generated_tag not in merged_cycle:
        raise ValueError("The contracted tensor has no exact generated tag root.")
    result.tag_after_ccw[retained] = int(generated_tag)
    validate_exact_web(result)
    root_position = merged_cycle.index(int(generated_tag))
    rooted_merged_cycle = (
        merged_cycle[root_position:] + merged_cycle[:root_position]
    )
    certificate = certify_two_hourglass_contraction(
        web,
        move.center,
        move.bundles,
        topology=topology,
        merged_cycle=rooted_merged_cycle,
    )
    if (
        certificate.splice_cycle != topology.merged_cycle
        or certificate.residual_blocks != topology.residual_blocks
        or certificate.outer_slot_maps != topology.outer_slot_maps
    ):
        raise ValueError(
            "Figure 9 tensor certificate does not match the applied ribbon splice."
        )
    return ExactRelationBranch(
        relation="two_hourglass_contraction",
        coefficient_multiplier=int(certificate.coefficient),
        web=result,
        certificate=_internal_relation_draft_certificate(
            "two_hourglass_contraction"
        ),
        local_data={
            "center": int(move.center),
            "consumed_bundles": list(topology.ordered_bundles),
            "outer_vertices": list(topology.ordered_outer_vertices),
            "retained_vertex": retained,
            "merged_cycle": list(rooted_merged_cycle),
            "unrooted_merged_cycle": list(merged_cycle),
            "tensor_splice_cycle": list(certificate.splice_cycle),
            "merged_tag_root": int(certificate.merged_tag_root),
            "merged_tag_convention": generated_tag_convention,
            "intrinsic_tag_fallback_reason": intrinsic_tag_error,
            "residual_blocks": [list(block) for block in topology.residual_blocks],
            "outer_slot_maps": [
                {str(old): int(new) for old, new in mapping}
                for mapping in topology.outer_slot_maps
            ],
            "outer_slot_map_pairs": [
                [[int(old), int(new)] for old, new in mapping]
                for mapping in topology.outer_slot_maps
            ],
            "tensor_coefficient": int(certificate.coefficient),
            "tensor_convention": certificate.convention,
            "assignments_checked": certificate.assignments_checked,
            "nonzero_assignments": certificate.nonzero_assignments,
            "transported_surviving_frames": transported_surviving_frames,
        },
    )


def _next_id(values: Iterable[int]) -> int:
    return max(values, default=-1) + 1


def _cyclic_block(web: HalfEdgeWeb, vertex: int, darts: Iterable[int]) -> bool:
    cycle = vertex_cycle_ccw(web, vertex)
    wanted = set(darts)
    if not wanted:
        return False
    return any(
        {cycle[(start + offset) % len(cycle)] for offset in range(len(wanted))} == wanted
        for start in range(len(cycle))
    )


def _ribbon_lens_frame_roots(
    web: ExactRibbonState,
    white: int,
    black: int,
    lens_darts: Iterable[int],
) -> dict[int, int]:
    """Frame any two-edge lens from its exact color/ribbon block.

    At white, the two lens darts form one proper cyclic block.  Its first dart
    is the one immediately preceded by a non-lens dart.  That physical strand
    is transported through the mate involution to black.  The color convention
    roots white immediately after the distinguished strand and black on the
    transported strand itself.  No live tag, temporary ID ordering, source-edge
    ancestry, or blanket generated-edge sign enters this construction.

    Earlier code selected three different frame policies according to whether
    zero, one, or two lens edges had a non-null ``source_edge_id``.  That field
    is replay lineage, not tensor data.  The three policies satisfy the same
    local tensor identities, but branching on lineage made a standalone square
    inverse observationally different after the square rewrite regenerated
    temporary edges.  One ribbon-local convention removes that false history
    dependence while retaining the exact persistent hourglass frame.
    """

    wanted = set(int(dart) for dart in lens_darts)
    white_cycle = vertex_cycle_ccw(web, int(white))
    local = [dart for dart in white_cycle if dart in wanted]
    if len(local) != 2:
        raise ValueError("A generated lens must have exactly two darts at white.")
    starts = [
        dart
        for dart in local
        if white_cycle[(white_cycle.index(dart) - 1) % len(white_cycle)] not in wanted
    ]
    if len(starts) != 1:
        raise ValueError("The generated lens is not one rooted cyclic block at white.")
    distinguished_white = starts[0]
    distinguished_black = web.mate[distinguished_white]
    if web.vertex_of[distinguished_black] != int(black):
        raise ValueError("The distinguished generated lens strand does not reach black.")
    return {
        int(white): int(web.next_ccw[distinguished_white]),
        int(black): int(distinguished_black),
    }


def detect_exact_double_edge_moves(web: ExactRibbonState) -> tuple[ExactDoubleEdgeMove, ...]:
    """Detect exact facial lenses and hourglass-plus-edge triples."""

    validate_exact_web(web)
    physical = _physical_edges(web)
    ordinary_by_pair: dict[frozenset[int], list[int]] = {}
    for physical_id, darts in physical.items():
        if web.edge_kind[darts[0]] != EdgeKind.ORDINARY:
            continue
        u, v = _endpoints(web, darts)
        ordinary_by_pair.setdefault(frozenset((u, v)), []).append(physical_id)

    bundle_by_pair: dict[frozenset[int], int] = {}
    for bundle in sorted({b for b in web.bundle_of.values() if b is not None}):
        members = [dart for dart, candidate in web.bundle_of.items() if candidate == bundle]
        pair = frozenset(web.vertex_of[dart] for dart in members)
        if pair in bundle_by_pair:
            raise ValueError(f"Parallel hourglass bundles at {sorted(pair)} are unsupported.")
        bundle_by_pair[pair] = int(bundle)

    result: list[ExactDoubleEdgeMove] = []
    all_pairs = set(ordinary_by_pair) | set(bundle_by_pair)
    for pair in sorted(all_pairs, key=lambda item: tuple(sorted(item))):
        if len(pair) != 2:
            continue
        u, v = sorted(pair)
        white = u if web.color.get(u) == VertexColor.WHITE else v
        black = u if web.color.get(u) == VertexColor.BLACK else v
        if web.color.get(white) != VertexColor.WHITE or web.color.get(black) != VertexColor.BLACK:
            continue
        ordinary = tuple(sorted(ordinary_by_pair.get(pair, ())))
        bundle = bundle_by_pair.get(pair)
        if bundle is not None and len(ordinary) == 1:
            local_count = {
                endpoint: sum(
                    web.vertex_of[dart] == endpoint
                    for dart in web.vertex_of
                    if web.bundle_of[dart] == bundle
                    or web.physical_edge_of[dart] == ordinary[0]
                )
                for endpoint in (white, black)
            }
            if local_count == {white: 3, black: 3}:
                result.append(
                    ExactDoubleEdgeMove(
                        "hourglass_plus_edge", white, black, ordinary, bundle
                    )
                )
        if bundle is None and len(ordinary) == 2:
            local = {
                endpoint: [
                    dart
                    for dart in vertex_cycle_ccw(web, endpoint)
                    if web.physical_edge_of[dart] in ordinary
                ]
                for endpoint in (white, black)
            }
            if all(len(darts) == 2 and _cyclic_block(web, endpoint, darts) for endpoint, darts in local.items()):
                result.append(ExactDoubleEdgeMove("double_edge", white, black, ordinary))
    return tuple(result)


def _delete_vertices_and_join_outside_darts(
    web: ExactRibbonState,
    removed_vertices: Iterable[int],
    pairings: Iterable[tuple[int, int]],
) -> ExactRibbonState:
    removed = set(int(vertex) for vertex in removed_vertices)
    pairs = tuple((int(a), int(b)) for a, b in pairings)
    result = copy.deepcopy(web)
    local_darts = {dart for dart, vertex in result.vertex_of.items() if vertex in removed}
    outside = {result.mate[dart] for dart in local_darts if result.mate[dart] not in local_darts}
    expected = {dart for pair in pairs for dart in pair}
    if outside != expected or len(expected) != 2 * len(pairs):
        raise ValueError(
            "Local rewrite did not account for each preserved outside dart exactly once."
        )
    if any(a == b or result.vertex_of[a] == result.vertex_of[b] for a, b in pairs):
        raise ValueError("Local rewrite would create a loop.")

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
    for vertex in removed:
        result.color.pop(vertex, None)
        result.boundary_label.pop(vertex, None)
        result.tag_after_ccw.pop(vertex, None)
        result.source_xy.pop(vertex, None)
        result.tensor_valence.pop(vertex, None)

    next_physical = _next_id(result.physical_edge_of.values())
    for a, b in pairs:
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


def apply_exact_double_edge_move(
    web: ExactRibbonState,
    move: ExactDoubleEdgeMove,
    *,
    _certify: bool = True,
) -> ExactRelationBranch:
    """Apply one detected q=1 double-edge relation with exact dart transport."""

    available = {
        (item.kind, item.white, item.black, item.ordinary_physical_edges, item.bundle_id): item
        for item in detect_exact_double_edge_moves(web)
    }
    key = (move.kind, move.white, move.black, move.ordinary_physical_edges, move.bundle_id)
    if key not in available:
        raise ValueError("The requested exact double-edge move is no longer applicable.")
    move = available[key]

    if move.kind == "double_edge":
        result = copy.deepcopy(web)
        lens_physical = set(move.ordinary_physical_edges)

        # Figure 43's [2]_q lens relation is a relation between specifically
        # tagged diagrams.  Before the two simple lens edges become one
        # multiplicity-two edge, choose the unique gap between the two outside
        # simple edges at each endpoint.  This is also the legal tag gap of the
        # output hourglass endpoint.  Proposition 2.15 of the project paper
        # applies untwist parity at every affected internal vertex.  The
        # current paper draft says "black" here, but the authors' corrected
        # convention includes both black and white vertices.
        canonical_lens_tags: dict[int, int] = {}
        lens_tag_factors: dict[int, int] = {}
        for vertex in (int(move.white), int(move.black)):
            cycle = vertex_cycle_ccw(web, vertex)
            outside = tuple(
                int(dart)
                for dart in cycle
                if int(web.physical_edge_of[dart]) not in lens_physical
            )
            if len(outside) != 2:
                raise ValueError(
                    "The [2] lens relation needs total outside multiplicity two at "
                    f"endpoint {vertex}."
                )
            outside_bundles = {web.bundle_of[dart] for dart in outside}
            if outside_bundles == {None}:
                # One output 2-edge plus two simple edges: the Figure 43 tag
                # is in the unique gap between the two simple edges.
                starts = [
                    dart
                    for dart in outside
                    if cycle[(cycle.index(dart) - 1) % len(cycle)] not in outside
                ]
                if len(starts) != 1:
                    raise ValueError(
                        f"The outside ports at lens endpoint {vertex} are not one block."
                    )
                target = int(web.next_ccw[int(starts[0])])
                if target not in outside:
                    raise ValueError(
                        f"The outside tag gap at lens endpoint {vertex} is incomplete."
                    )
            elif len(outside_bundles) == 1 and None not in outside_bundles:
                # Gluing the local [2] relation to an existing 2-edge gives
                # two abstract multiplicity-two edges.  Root at their block
                # boundary.  The opposite boundary has the same sign because
                # Lemma 2.5 gives +1 across multiplicity two in SL4.
                lens_darts = tuple(
                    int(dart)
                    for dart in cycle
                    if int(web.physical_edge_of[dart]) in lens_physical
                )
                starts = [
                    dart
                    for dart in lens_darts
                    if cycle[(cycle.index(dart) - 1) % len(cycle)] not in lens_darts
                ]
                if len(starts) != 1:
                    raise ValueError(
                        f"The lens ports at cable endpoint {vertex} are not one block."
                    )
                target = int(starts[0])
            else:
                raise ValueError(
                    f"The [2] lens relation has mixed outside multiplicities at {vertex}."
                )
            canonical_lens_tags[vertex] = target
            lens_tag_factors[vertex] = paper_tag_transport_sign(
                web, vertex, target, r=4
            )
        skein_untwist_multiplier = 1
        for factor in lens_tag_factors.values():
            skein_untwist_multiplier *= int(factor)

        def generated_physical(physical: int) -> bool:
            members = [
                dart
                for dart, candidate in web.physical_edge_of.items()
                if candidate == physical
            ]
            return bool(members) and all(
                web.source_edge_id.get(dart) is None for dart in members
            )

        generated_lens_edge_count = sum(
            generated_physical(physical) for physical in lens_physical
        )
        endpoint_set = {move.white, move.black}
        generated_external_edges = {
            physical
            for dart, physical in web.physical_edge_of.items()
            if web.vertex_of[dart] in endpoint_set
            and physical not in lens_physical
            and generated_physical(physical)
        }
        live_generated_external_edge_count = len(generated_external_edges)
        bundle = _next_id(b for b in result.bundle_of.values() if b is not None)
        darts = [
            dart
            for dart, physical in result.physical_edge_of.items()
            if physical in move.ordinary_physical_edges
        ]
        for dart in darts:
            result.edge_kind[dart] = EdgeKind.HOURGLASS_STRAND
            result.bundle_of[dart] = bundle
            # The persistent bundle frame below supersedes catalogue-local
            # strand labels.  Keep source_edge_id untouched for replay lineage,
            # but never consult it when choosing the mathematical frame.
            result.source_local_strand[dart] = None
        repaired_half_twist = enforce_paper_hourglass_half_twist(result, bundle)
        # The promoted hourglass receives one deterministic color/ribbon frame.
        # Source-edge ancestry remains available below as audit metadata but
        # never selects a mathematical frame or coefficient.
        frame_roots = _ribbon_lens_frame_roots(
            result,
            move.white,
            move.black,
            darts,
        )
        frame_policy = "color_ribbon_lens_block"
        result.bundle_frame_root[bundle] = frame_roots
        for vertex, root in canonical_lens_tags.items():
            result.tag_after_ccw[int(vertex)] = int(root)
            paper_incident_edge_blocks_clockwise(result, int(vertex))
        frame_shifts = {
            vertex: _root_shift(result, vertex, root)
            for vertex, root in frame_roots.items()
        }
        legacy_drawn_slot_frame_parity = (
            -1 if sum(frame_shifts.values()) % 2 else 1
        )
        refresh_bundle_frames(result)
        validate_exact_web(result)
        local_tensor_vertices = _multiplicity_closed_local_vertices(
            web, (int(move.white), int(move.black))
        )
        (
            certified_coefficient,
            certified_assignments_checked,
        ) = _certified_single_branch_local_coefficient(
            web,
            result,
            local_tensor_vertices,
        )
        input_endpoint_candidate = 2 * int(skein_untwist_multiplier)
        draft = ExactRelationBranch(
            relation="double_edge_to_hourglass",
            coefficient_multiplier=certified_coefficient,
            web=result,
            certificate=_internal_relation_draft_certificate(
                "double_edge_to_hourglass"
            ),
            local_data={
                "white": move.white,
                "black": move.black,
                "consumed_physical_edges": move.ordinary_physical_edges,
                "created_bundle": bundle,
                "formal_coefficient": 2,
                "live_input_tags": {
                    str(vertex): int(web.tag_after_ccw[vertex])
                    for vertex in sorted(canonical_lens_tags)
                },
                "canonical_relation_tags": {
                    str(vertex): int(root)
                    for vertex, root in sorted(canonical_lens_tags.items())
                },
                "tag_transport_factors": {
                    str(vertex): int(factor)
                    for vertex, factor in sorted(lens_tag_factors.items())
                },
                "skein_sign_source": (
                    "GPPSS Figure 43 formal coefficient [2] in the complete "
                    "tagged input/output gauge, certified using Definition "
                    "2.8 on the multiplicity-closed local neighborhood"
                ),
                "skein_untwist_multiplier": skein_untwist_multiplier,
                "lens_transport_multiplier": skein_untwist_multiplier,
                "input_endpoint_candidate_coefficient": input_endpoint_candidate,
                "certified_coefficient": certified_coefficient,
                "tensor_certificate_vertices": local_tensor_vertices,
                "tensor_certificate_assignments_checked": (
                    certified_assignments_checked
                ),
                "tensor_certificate_convention": (
                    "GPPSS_Definition_2.8_subset_coinversion_v2"
                ),
                "output_gauge_compensation_multiplier": (
                    int(certified_coefficient) // int(input_endpoint_candidate)
                ),
                "total_tag_transport_multiplier": (
                    int(certified_coefficient) // 2
                ),
                "frame_transport_multiplier": legacy_drawn_slot_frame_parity,
                "legacy_drawn_slot_frame_parity": legacy_drawn_slot_frame_parity,
                "frame_policy": frame_policy,
                "paper_half_twist_repaired": bool(repaired_half_twist),
                "frame_roots": {
                    str(vertex): int(root) for vertex, root in sorted(frame_roots.items())
                },
                "frame_shifts": {
                    str(vertex): int(shift)
                    for vertex, shift in sorted(frame_shifts.items())
                },
                "generated_lens_edge_count": generated_lens_edge_count,
                "source_ancestry_affects_frame": False,
                "live_generated_external_edge_count": live_generated_external_edge_count,
            },
        )
        if not _certify:
            return draft
        boundary_port_labels = exact_local_boundary_port_label_map(
            web, local_tensor_vertices
        )
        local_input = extract_exact_local_tensor_fixture(
            web,
            local_tensor_vertices,
            boundary_label_by_outside_dart=boundary_port_labels,
        )
        local_draft = apply_exact_double_edge_move(
            local_input, move, _certify=False
        )
        return certify_exact_relation_branches(
            relation="double_edge_to_hourglass",
            paper_reference="GPPSS Figure 43 coefficient [2]_q at q=1",
            input_web=web,
            output_branches=(draft,),
            local_input=local_input,
            local_output_branches=(local_draft,),
            formal_coefficients=(2,),
            tag_transport_multipliers=(int(certified_coefficient) // 2,),
            input_paper_tag_roots=canonical_lens_tags,
            output_paper_tag_roots=(canonical_lens_tags,),
            # This is a single-branch relation whose complete tagged local
            # tensors have already been proved proportional above.  The
            # remaining sign is therefore the unique exhaustive tensor ratio
            # between the paper coefficient +2 and the live output gauge; it
            # is not inferred from vertex color, ancestry, bundle IDs, or a
            # legacy stored sign.
            allow_single_branch_tensor_ratio_residual=True,
            diagnostics={
                "unique_tensor_ratio": int(certified_coefficient),
                "coefficient_excludes_source_ancestry": True,
                "coefficient_excludes_bundle_id": True,
                "coefficient_excludes_vertex_colors": True,
                "single_branch_tensor_ratio_residual_allowed": True,
            },
        )[0]

    if move.kind != "hourglass_plus_edge" or move.bundle_id is None:
        raise ValueError(f"Unsupported exact double-edge move {move.kind!r}.")
    local = {
        dart
        for dart in web.vertex_of
        if web.vertex_of[dart] in {move.white, move.black}
    }
    outside_local = [
        dart
        for dart in local
        if web.mate[dart] not in local
    ]
    if len(outside_local) != 2:
        raise ValueError("Hourglass-plus-edge collapse requires one outside dart per endpoint.")
    outside_dart_by_vertex = {
        int(web.vertex_of[dart]): int(dart) for dart in outside_local
    }
    endpoints = {int(move.white), int(move.black)}
    if set(outside_dart_by_vertex) != endpoints:
        raise ValueError(
            "Hourglass-plus-edge collapse requires one outside ordinary dart "
            "at each endpoint."
        )
    frame_roots = web.bundle_frame_root.get(int(move.bundle_id), {})
    if set(frame_roots) != endpoints:
        raise ValueError(
            "Hourglass-plus-edge collapse requires one exact frame root at each endpoint."
        )
    # Figure 43 draws the red tag in the outside-leg sector at each endpoint
    # of the hourglass-plus-edge tensor.  That displayed sector, not a
    # presentation-dependent intrinsic trip root or stored strand frame, is
    # the relation's canonical tag.  Transport every live tag to this sector
    # using Lemma 2.5 at both the white and black endpoint.
    relation_tag_roots = {
        int(vertex): int(outside_dart_by_vertex[int(vertex)])
        for vertex in endpoints
    }
    tag_transport_factors = {
        int(vertex): paper_tag_transport_sign(
            web, int(vertex), int(relation_tag_roots[int(vertex)]), r=4
        )
        for vertex in endpoints
    }
    tag_transport_multiplier = 1
    for factor in tag_transport_factors.values():
        tag_transport_multiplier *= int(factor)
    relation_tag_shifts = {
        int(vertex): _root_shift(
            web, int(vertex), int(relation_tag_roots[int(vertex)])
        )
        for vertex in endpoints
    }

    # Retain the frame-to-outside comparison as a diagnostic.  It often
    # exposes the historical failure after a Wrench-created presentation, but
    # it is not multiplied separately: the actual scalar is already obtained
    # by transporting the live tensor tags directly to the displayed outside-
    # leg sectors above.
    frame_to_outside_shifts = {}
    for vertex in endpoints:
        cycle = vertex_cycle_ccw(web, int(vertex))
        frame_to_outside_shifts[int(vertex)] = (
            cycle.index(outside_dart_by_vertex[int(vertex)])
            - cycle.index(int(frame_roots[int(vertex)]))
        ) % len(cycle)
    frame_to_outside_multiplier = (
        -1 if sum(frame_to_outside_shifts.values()) % 2 else 1
    )

    def framed_strands(vertex: int) -> tuple[int, int]:
        cycle = vertex_cycle_ccw(web, int(vertex))
        root = int(frame_roots[int(vertex)])
        rotated = cycle[cycle.index(root) :] + cycle[: cycle.index(root)]
        members = tuple(
            dart for dart in rotated if web.bundle_of[dart] == int(move.bundle_id)
        )
        if len(members) != 2:
            raise ValueError(
                "Hourglass-plus-edge collapse needs two framed strands per endpoint."
            )
        return members  # type: ignore[return-value]

    white_strands = framed_strands(int(move.white))
    black_strands = framed_strands(int(move.black))

    def canonical_strands(vertex: int) -> tuple[int, int]:
        cycle = vertex_cycle_ccw(web, int(vertex))
        members = {
            int(dart)
            for dart in cycle
            if web.bundle_of[dart] == int(move.bundle_id)
        }
        if len(members) != 2:
            raise ValueError(
                "Hourglass-plus-edge collapse needs one two-strand block per endpoint."
            )
        starts = [
            int(dart)
            for dart in members
            if cycle[(cycle.index(dart) - 1) % len(cycle)] not in members
        ]
        if len(starts) != 1:
            raise ValueError(
                "Hourglass-plus-edge strands are not one exact cyclic block."
            )
        first = starts[0]
        second = int(web.next_ccw[first])
        if second not in members:
            raise ValueError(
                "Hourglass-plus-edge canonical strand block is incomplete."
            )
        return first, second

    canonical_by_vertex = {
        int(move.white): canonical_strands(int(move.white)),
        int(move.black): canonical_strands(int(move.black)),
    }
    framed_by_vertex = {
        int(move.white): white_strands,
        int(move.black): black_strands,
    }
    frame_phase_multipliers = {}
    for vertex in endpoints:
        framed = framed_by_vertex[int(vertex)]
        canonical = canonical_by_vertex[int(vertex)]
        if framed == canonical:
            frame_phase_multipliers[int(vertex)] = 1
        elif framed == tuple(reversed(canonical)):
            frame_phase_multipliers[int(vertex)] = -1
        else:  # pragma: no cover - exact cyclic-block checks exclude this
            raise ValueError(
                "Hourglass-plus-edge frame does not order its two strands exactly."
            )
    frame_phase_multiplier = (
        frame_phase_multipliers[int(move.white)]
        * frame_phase_multipliers[int(move.black)]
    )

    strand_matching = tuple(
        black_strands.index(web.mate[dart]) for dart in white_strands
    )
    if strand_matching == (0, 1):
        strand_matching_multiplier = 1
    elif strand_matching == (1, 0):
        strand_matching_multiplier = -1
    else:  # pragma: no cover - exact bundle validation makes this impossible
        raise ValueError(
            f"Invalid hourglass-plus-edge strand matching {strand_matching}."
        )
    # GPPSS Figure 43 gives +[3]_q for this tagged reduction, hence +3 at
    # q=1.  Definition 2.8 treats the two cable colors as one subset, so a
    # drawn strand matching or stored frame phase cannot change this scalar.
    coefficient = 3 * int(tag_transport_multiplier)
    outside_by_vertex = {web.vertex_of[dart]: web.mate[dart] for dart in outside_local}
    result = _delete_vertices_and_join_outside_darts(
        web,
        (move.white, move.black),
        ((outside_by_vertex[move.white], outside_by_vertex[move.black]),),
    )
    draft = ExactRelationBranch(
        relation="hourglass_plus_edge_to_edge",
        coefficient_multiplier=coefficient,
        web=result,
        certificate=_internal_relation_draft_certificate(
            "hourglass_plus_edge_to_edge"
        ),
        local_data={
            "white": move.white,
            "black": move.black,
            "consumed_bundle": move.bundle_id,
            "consumed_ordinary_edge": move.ordinary_physical_edges[0],
            "formal_coefficient": 3,
            "frame_roots": {
                str(vertex): int(root)
                for vertex, root in sorted(frame_roots.items())
            },
            "relation_tag_roots": {
                str(vertex): int(root)
                for vertex, root in sorted(relation_tag_roots.items())
            },
            "relation_tag_shifts": {
                str(vertex): int(shift)
                for vertex, shift in sorted(relation_tag_shifts.items())
            },
            "tag_transport_factors": {
                str(vertex): int(factor)
                for vertex, factor in sorted(tag_transport_factors.items())
            },
            "tag_transport_multiplier": tag_transport_multiplier,
            "total_tag_transport_multiplier": tag_transport_multiplier,
            "canonical_strands": {
                str(vertex): list(strands)
                for vertex, strands in sorted(canonical_by_vertex.items())
            },
            "frame_phase_multipliers": {
                str(vertex): int(multiplier)
                for vertex, multiplier in sorted(frame_phase_multipliers.items())
            },
            "frame_phase_multiplier": int(frame_phase_multiplier),
            "frame_phase_affects_coefficient": False,
            "strand_matching": strand_matching,
            "strand_matching_multiplier": strand_matching_multiplier,
            "strand_matching_affects_coefficient": False,
            "outside_darts": {
                str(vertex): int(dart)
                for vertex, dart in sorted(outside_dart_by_vertex.items())
            },
            "frame_to_outside_shifts": {
                str(vertex): int(shift)
                for vertex, shift in sorted(frame_to_outside_shifts.items())
            },
            "frame_to_outside_multiplier": frame_to_outside_multiplier,
            "frame_to_outside_affects_coefficient": False,
            "coefficient_source": (
                "GPPSS Figure 43 coefficient +[3]_q at q=1, times Lemma "
                "2.5 transport from both live tags to the displayed "
                "outside-leg tag sectors"
            ),
        },
    )
    if not _certify:
        return draft
    local_input = extract_exact_local_tensor_fixture(
        web, (int(move.white), int(move.black))
    )
    local_draft = apply_exact_double_edge_move(
        local_input, move, _certify=False
    )
    return certify_exact_relation_branches(
        relation="hourglass_plus_edge_to_edge",
        paper_reference="GPPSS Figure 43 coefficient [3]_q at q=1",
        input_web=web,
        output_branches=(draft,),
        local_input=local_input,
        local_output_branches=(local_draft,),
        formal_coefficients=(3,),
        tag_transport_multipliers=(int(tag_transport_multiplier),),
        input_paper_tag_roots=relation_tag_roots,
        diagnostics={
            "unique_tensor_ratio": int(coefficient),
            "coefficient_excludes_strand_matching": True,
            "coefficient_excludes_frame_phase": True,
            "coefficient_excludes_source_ancestry": True,
            "coefficient_excludes_bundle_id": True,
        },
    )[0]


def _abstract_token(web: HalfEdgeWeb, dart: int) -> tuple[str, int]:
    if web.edge_kind[dart] == EdgeKind.ORDINARY:
        return "O", int(web.physical_edge_of[dart])
    bundle = web.bundle_of[dart]
    if bundle is None:
        raise ValueError(f"Hourglass dart {dart} has no bundle.")
    return "H", int(bundle)


def _abstract_edges(web: HalfEdgeWeb) -> dict[tuple[str, int], tuple[int, int]]:
    endpoints: dict[tuple[str, int], set[int]] = {}
    for dart in web.vertex_of:
        endpoints.setdefault(_abstract_token(web, dart), set()).add(web.vertex_of[dart])
    result = {}
    for token, vertices in endpoints.items():
        if len(vertices) != 2:
            raise ValueError(f"Abstract edge {token} does not have two endpoints.")
        result[token] = tuple(sorted(vertices))
    return result


def _abstract_rotation(web: HalfEdgeWeb, vertex: int) -> tuple[tuple[str, int], ...]:
    raw = [_abstract_token(web, dart) for dart in vertex_cycle_ccw(web, vertex)]
    compressed: list[tuple[str, int]] = []
    for token in raw:
        if not compressed or token != compressed[-1]:
            compressed.append(token)
    if len(compressed) > 1 and compressed[0] == compressed[-1]:
        compressed.pop()
    if len(set(compressed)) != len(compressed):
        raise ValueError(f"Abstract edges do not form cyclic blocks at vertex {vertex}.")
    return tuple(compressed)


def _canonical_cycle(cycle: Sequence[int]) -> tuple[int, ...]:
    values = tuple(int(vertex) for vertex in cycle)
    variants = []
    for oriented in (values, tuple(reversed(values))):
        variants.extend(oriented[offset:] + oriented[:offset] for offset in range(len(values)))
    return min(variants)


def _edge_token_between(
    lookup: Mapping[frozenset[int], tuple[str, int]], u: int, v: int
) -> tuple[str, int]:
    try:
        return lookup[frozenset((u, v))]
    except KeyError as exc:
        raise ValueError(f"No unique abstract edge joins {u} and {v}.") from exc


def _mixed_facial_turn(
    web: HalfEdgeWeb,
    cycle: Sequence[int],
    lookup: Mapping[frozenset[int], tuple[str, int]],
) -> int | None:
    turns = []
    for index, vertex in enumerate(cycle):
        previous = cycle[(index - 1) % len(cycle)]
        following = cycle[(index + 1) % len(cycle)]
        incoming = _edge_token_between(lookup, vertex, previous)
        outgoing = _edge_token_between(lookup, vertex, following)
        rotation = _abstract_rotation(web, vertex)
        if incoming not in rotation or outgoing not in rotation:
            return None
        # With only two abstract incident tokens, clockwise and
        # counterclockwise adjacency are the same relation: the unique step
        # has size both 1 and len(rotation)-1.  Such a compressed corner must
        # not vote for either facial orientation.  Infer the common turn from
        # the remaining corners that have at least three tokens.
        if len(rotation) == 2:
            continue
        step = (rotation.index(outgoing) - rotation.index(incoming)) % len(rotation)
        if step == 1:
            turns.append(1)
        elif step == len(rotation) - 1:
            turns.append(-1)
        else:
            return None
    return turns[0] if turns and len(set(turns)) == 1 else None


def detect_exact_figure43_moves(web: ExactRibbonState) -> tuple[ExactFigure43Move, ...]:
    """Detect exact executable Figure 43 rows, including right-hourglass row 4.

    The abstract four-cycle must be facial in the cyclic order obtained by
    collapsing each two-dart hourglass block to one ribbon edge.  Rows 3 and 4
    are distinguished by the hourglass's color-preserving side position.
    """

    validate_exact_web(web)
    abstract = _abstract_edges(web)
    by_pair: dict[frozenset[int], list[tuple[str, int]]] = {}
    adjacency: dict[int, set[int]] = {vertex: set() for vertex in web.color}
    for token, (u, v) in abstract.items():
        if web.color[u] == VertexColor.BOUNDARY or web.color[v] == VertexColor.BOUNDARY:
            continue
        by_pair.setdefault(frozenset((u, v)), []).append(token)
        adjacency[u].add(v)
        adjacency[v].add(u)
    lookup = {pair: tokens[0] for pair, tokens in by_pair.items() if len(tokens) == 1}

    raw: set[tuple[int, ...]] = set()
    for a in adjacency:
        for b in adjacency[a]:
            for c in adjacency[b] - {a}:
                for d in adjacency[c] - {a, b}:
                    if a in adjacency[d] and len({a, b, c, d}) == 4:
                        raw.add(_canonical_cycle((a, b, c, d)))

    matches: dict[tuple[int, ...], ExactFigure43Move] = {}
    for base in sorted(raw):
        candidates = []
        for oriented in (base, tuple(reversed(base))):
            for offset in range(4):
                cycle = oriented[offset:] + oriented[:offset]
                if tuple(web.color[v] for v in cycle) != (
                    VertexColor.BLACK,
                    VertexColor.WHITE,
                    VertexColor.BLACK,
                    VertexColor.WHITE,
                ):
                    continue
                try:
                    tokens = tuple(
                        _edge_token_between(lookup, cycle[i], cycle[(i + 1) % 4])
                        for i in range(4)
                    )
                except ValueError:
                    continue
                kinds = tuple(token[0] for token in tokens)
                if kinds == ("O", "H", "O", "H"):
                    rule = "opposite_hourglasses"
                elif kinds == ("H", "O", "O", "O"):
                    rule = "single_top_hourglass"
                elif kinds == ("O", "H", "O", "O"):
                    rule = "single_right_hourglass"
                else:
                    continue
                expected_outside = {
                    "opposite_hourglasses": (1, 1, 1, 1),
                    # Figure 43 row 3 has one ordinary outside port at every
                    # corner.  Its top tensors have four exact darts
                    # (hourglass, side, outside), while the two bottom
                    # tensors are the explicitly tagged three-valent
                    # tensors in the paper.  The collapse transports the two
                    # top ports to the bottom tensors; treating the row as
                    # (0,0,2,2) silently deletes that transport data.
                    "single_top_hourglass": (1, 1, 1, 1),
                    "single_right_hourglass": (2, 1, 1, 2),
                }[rule]
                local_shape_ok = True
                for index, vertex in enumerate(cycle):
                    incident_tokens = {
                        tokens[(index - 1) % 4],
                        tokens[index],
                    }
                    outside = [
                        dart
                        for dart in vertex_cycle_ccw(web, vertex)
                        if _abstract_token(web, dart) not in incident_tokens
                    ]
                    if (
                        len(outside) != expected_outside[index]
                        or any(web.edge_kind[dart] != EdgeKind.ORDINARY for dart in outside)
                    ):
                        local_shape_ok = False
                        break
                if not local_shape_ok:
                    continue
                turn = _mixed_facial_turn(web, cycle, lookup)
                if turn is not None:
                    candidates.append((tuple(cycle), kinds, turn, rule))
        if candidates:
            cycle, kinds, turn, rule = min(candidates)
            matches[_canonical_cycle(cycle)] = ExactFigure43Move(cycle, kinds, turn, rule)

    return tuple(matches[key] for key in sorted(matches))


def _figure43_outside_darts(
    web: HalfEdgeWeb, move: ExactFigure43Move
) -> tuple[int, int, int, int]:
    cycle = move.cycle
    abstract = _abstract_edges(web)
    by_pair = {frozenset(endpoints): token for token, endpoints in abstract.items()}
    result = []
    for index, vertex in enumerate(cycle):
        local_tokens = {
            _edge_token_between(by_pair, vertex, cycle[(index - 1) % 4]),
            _edge_token_between(by_pair, vertex, cycle[(index + 1) % 4]),
        }
        outside_local = [
            dart
            for dart in vertex_cycle_ccw(web, vertex)
            if _abstract_token(web, dart) not in local_tokens
        ]
        if len(outside_local) != 1 or web.edge_kind[outside_local[0]] != EdgeKind.ORDINARY:
            raise ValueError(
                f"Figure 43 corner {vertex} does not have exactly one ordinary outside dart."
            )
        result.append(web.mate[outside_local[0]])
    return tuple(result)  # type: ignore[return-value]


def apply_exact_figure43_move(
    web: ExactRibbonState,
    move: ExactFigure43Move,
    *,
    _certify: bool = True,
) -> tuple[ExactRelationBranch, ...]:
    """Apply an exact executable Figure 43 row."""

    available = {_canonical_cycle(item.cycle): item for item in detect_exact_figure43_moves(web)}
    key = _canonical_cycle(move.cycle)
    if key not in available:
        raise ValueError("The requested exact Figure 43 move is no longer applicable.")
    move = available[key]

    def finalize(
        drafts: Sequence[ExactRelationBranch],
        *,
        formal: Sequence[int],
        transports: Sequence[int],
        paper_roots: Mapping[int, int],
        row_reference: str,
        boundary_records: Sequence[
            Sequence[Mapping[str, Any]]
        ] | None = None,
    ) -> tuple[ExactRelationBranch, ...]:
        drafts = tuple(drafts)
        if not _certify:
            return drafts
        local_input = extract_exact_local_tensor_fixture(web, move.cycle)
        local_drafts = apply_exact_figure43_move(
            local_input, move, _certify=False
        )
        return certify_exact_relation_branches(
            relation=f"figure43_{move.rule}",
            paper_reference=row_reference,
            input_web=web,
            output_branches=drafts,
            local_input=local_input,
            local_output_branches=local_drafts,
            formal_coefficients=formal,
            tag_transport_multipliers=transports,
            input_paper_tag_roots=paper_roots,
            boundary_order_transport_records=boundary_records,
            diagnostics={
                "figure43_rule": move.rule,
                "coefficient_excludes_topology_name": True,
                "coefficient_excludes_vertex_colors": True,
                "coefficient_excludes_source_ancestry": True,
                "coefficient_excludes_bundle_ids": True,
            },
        )

    if move.rule == "single_top_hourglass":
        draft = _apply_exact_figure43_single_top_hourglass(web, move)
        if _certify:
            raise UncertifiedRelationError(
                "GPPSS Figure 43's single-top-hourglass row contains tagged "
                "trivalent vertices.  The current exact state records their "
                "cyclic darts but not the oriented representation labels needed "
                "for a paper-faithful pointwise tensor certificate; production "
                "therefore rejects this branch."
            )
        roots = {
            int(vertex): int(root)
            for vertex, root in draft.local_data[
                "canonical_removed_tags"
            ].items()
        }
        return finalize(
            (draft,),
            formal=(2,),
            transports=(
                int(draft.local_data["removed_tag_transport_multiplier"]),
            ),
            paper_roots=roots,
            row_reference="GPPSS Figure 43 single-top-hourglass row",
        )
    if move.rule == "single_right_hourglass":
        drafts = _apply_exact_figure43_single_right_hourglass(web, move)
        roots = {
            int(vertex): int(root)
            for vertex, root in drafts[0].local_data[
                "canonical_input_tags"
            ].items()
        }
        transport = int(drafts[0].local_data["tag_transport_multiplier"])
        splice_transport = transport * int(
            drafts[1].local_data["splice_orientation_multiplier"]
        )
        return finalize(
            drafts,
            formal=(1, 1),
            transports=(transport, splice_transport),
            paper_roots=roots,
            row_reference="GPPSS Figure 43 single-right-hourglass row",
            boundary_records=(
                (),
                (
                    drafts[1].local_data[
                        "splice_boundary_order_transport_record"
                    ],
                ),
            ),
        )
    if move.rule != "opposite_hourglasses":
        raise ValueError(f"Unsupported exact Figure 43 rule {move.rule!r}.")
    tl, tr, br, bl = move.cycle
    # Figure 43 is printed with one canonical tag at each of its four input
    # tensors.  All four tensors disappear on the right-hand side, so any
    # live-to-canonical tag parity has to be carried by *both* branch
    # coefficients.  The previous implementation hard-coded effective
    # coefficients (1, 2).  That was correct only when the four live tags had
    # even total parity; a square-created presentation with odd parity then
    # failed its exact local tensor identity and produced a spurious -4.
    canonical_input_tags = {
        int(vertex): int(intrinsic_tag_root(web, int(vertex)))
        for vertex in move.cycle
    }
    input_tag_shifts = {
        int(vertex): _root_shift(web, int(vertex), canonical_input_tags[int(vertex)])
        for vertex in move.cycle
    }
    input_tag_transport_multiplier = (
        -1 if sum(input_tag_shifts.values()) % 2 else 1
    )
    e_tl, e_tr, e_br, e_bl = _figure43_outside_darts(web, move)
    horizontal = _delete_vertices_and_join_outside_darts(
        web, move.cycle, ((e_tl, e_tr), (e_bl, e_br))
    )
    vertical = _delete_vertices_and_join_outside_darts(
        web, move.cycle, ((e_tl, e_bl), (e_tr, e_br))
    )
    base = {
        "cycle": move.cycle,
        "side_kinds": move.side_kinds,
        "facial_turn": move.facial_turn,
    }
    horizontal_boundary_order = ("TL", "TR", "BL", "BR")
    vertical_boundary_order = ("TL", "BL", "TR", "BR")
    exact_corner_binding = {
        "TL": int(e_tl),
        "TR": int(e_tr),
        "BR": int(e_br),
        "BL": int(e_bl),
    }
    horizontal_boundary_record = _make_boundary_order_transport_record(
        kind="figure43_output_pairing_basis_order",
        paper_reference=(
            "GPPSS Figure 43 opposite-hourglasses row; output basis order "
            "anchored to the first displayed RHS smoothing"
        ),
        paper_order=horizontal_boundary_order,
        engine_order=horizontal_boundary_order,
        diagnostics={
            "pairing_roles": (("TL", "TR"), ("BL", "BR")),
            "exact_label_binding": exact_corner_binding,
            "side_kinds": move.side_kinds,
        },
    )
    vertical_boundary_record = _make_boundary_order_transport_record(
        kind="figure43_output_pairing_basis_order",
        paper_reference=(
            "GPPSS Figure 43 opposite-hourglasses row; output basis order "
            "anchored to the first displayed RHS smoothing"
        ),
        paper_order=horizontal_boundary_order,
        engine_order=vertical_boundary_order,
        diagnostics={
            "pairing_roles": (("TL", "BL"), ("TR", "BR")),
            "exact_label_binding": exact_corner_binding,
            "side_kinds": move.side_kinds,
        },
    )
    horizontal_boundary_factor = int(
        horizontal_boundary_record["permutation_sign"]
    )
    vertical_boundary_factor = int(
        vertical_boundary_record["permutation_sign"]
    )
    drafts = (
        ExactRelationBranch(
            "figure43_opposite_hourglasses_horizontal",
            input_tag_transport_multiplier * horizontal_boundary_factor,
            horizontal,
            {
                **base,
                "smoothing": "horizontal",
                "paper_coefficient": 1,
                "canonical_input_tags": canonical_input_tags,
                "input_tag_shifts": input_tag_shifts,
                "input_tag_transport_multiplier": input_tag_transport_multiplier,
                "boundary_order_transport_multiplier": (
                    horizontal_boundary_factor
                ),
                "tag_transport_multiplier": (
                    input_tag_transport_multiplier * horizontal_boundary_factor
                ),
            },
            _internal_relation_draft_certificate(
                "figure43_opposite_hourglasses_horizontal"
            ),
        ),
        ExactRelationBranch(
            "figure43_opposite_hourglasses_vertical",
            -2 * input_tag_transport_multiplier * vertical_boundary_factor,
            vertical,
            {
                **base,
                "smoothing": "vertical",
                # Figure 43 prints coefficient -[2]_q.  The two displayed RHS
                # smoothings induce different orders of the same four labeled
                # boundary ports.  The exact permutation between those orders
                # is recorded and replayed below; no nonexistent RHS vertex
                # tag or stored legacy sign is used.
                "paper_coefficient": -2,
                "canonical_input_tags": canonical_input_tags,
                "input_tag_shifts": input_tag_shifts,
                "input_tag_transport_multiplier": input_tag_transport_multiplier,
                "boundary_order_transport_multiplier": (
                    vertical_boundary_factor
                ),
                "tag_transport_multiplier": (
                    input_tag_transport_multiplier * vertical_boundary_factor
                ),
            },
            _internal_relation_draft_certificate(
                "figure43_opposite_hourglasses_vertical"
            ),
        ),
    )
    return finalize(
        drafts,
        formal=(1, -2),
        transports=(
            int(input_tag_transport_multiplier * horizontal_boundary_factor),
            int(input_tag_transport_multiplier * vertical_boundary_factor),
        ),
        paper_roots=canonical_input_tags,
        row_reference="GPPSS Figure 43 opposite-hourglasses row",
        boundary_records=(
            (horizontal_boundary_record,),
            (vertical_boundary_record,),
        ),
    )


def _apply_exact_figure43_single_top_hourglass(
    web: ExactRibbonState,
    move: ExactFigure43Move,
) -> ExactRelationBranch:
    """Figure 43 row 3: transport four ports into one framed hourglass.

    The two bottom corners on the left-hand side are tagged three-valent
    tensors.  The top-left/right outside ports pass through the corresponding
    side edges and become the second ordinary port at those bottom tensors.
    The bottom edge expands to a two-strand hourglass carrying the input
    cable's exact frame and mate permutation.  This is the literal four-port
    relation in Figure 43; no outside dart is discarded.

    A one-slot rotation at either removed top tensor changes the sign of the
    input determinant, so its parity is carried by the scalar coefficient.
    The bottom tags survive and are transported through the one-to-two-dart
    bottom-edge expansion instead of being counted again in the coefficient.
    """

    tl, tr, br, bl = move.cycle

    def ordinary_dart(vertex: int, neighbor: int) -> int:
        matches = [
            dart
            for dart in vertex_cycle_ccw(web, vertex)
            if web.edge_kind[dart] == EdgeKind.ORDINARY
            and web.vertex_of[web.mate[dart]] == neighbor
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Figure 43 row 3 needs one ordinary dart from {vertex} to {neighbor}."
            )
        return matches[0]

    left_at_bl = ordinary_dart(bl, tl)
    left_at_tl = ordinary_dart(tl, bl)
    right_at_br = ordinary_dart(br, tr)
    right_at_tr = ordinary_dart(tr, br)
    bottom_at_bl = ordinary_dart(bl, br)
    bottom_at_br = ordinary_dart(br, bl)
    if web.mate[left_at_bl] != left_at_tl:
        raise ValueError("Figure 43 row 3 left edge darts are not mates.")
    if web.mate[right_at_br] != right_at_tr:
        raise ValueError("Figure 43 row 3 right edge darts are not mates.")
    if web.mate[bottom_at_bl] != bottom_at_br:
        raise ValueError("Figure 43 row 3 bottom edge darts are not mates.")

    outside = _figure43_outside_vertex_darts(web, move)
    if tuple(len(darts) for darts in outside) != (1, 1, 1, 1):
        raise ValueError("Figure 43 row 3 requires one outside port at every corner.")
    outside_tl, outside_tr, outside_br, outside_bl = (
        int(darts[0]) for darts in outside
    )
    transported_tl = int(web.mate[outside_tl])
    transported_tr = int(web.mate[outside_tr])

    top_token = _figure43_side_tokens(web, move)[0]
    if top_token[0] != "H":
        raise ValueError("Figure 43 row 3 top side is not one exact hourglass.")
    input_bundle = int(top_token[1])
    input_frame_roots = web.bundle_frame_root.get(input_bundle, {})
    if set(input_frame_roots) != {tl, tr}:
        raise ValueError("Figure 43 row 3 input hourglass frame is incomplete.")

    def input_block_strands(vertex: int) -> tuple[int, int]:
        cycle = vertex_cycle_ccw(web, int(vertex))
        members = {
            dart for dart in cycle if web.bundle_of[dart] == input_bundle
        }
        starts = [
            dart
            for dart in members
            if cycle[(cycle.index(dart) - 1) % len(cycle)] not in members
        ]
        if len(starts) != 1:
            raise ValueError("Figure 43 row 3 input hourglass is not one cyclic block.")
        start = int(starts[0])
        rotated = cycle[cycle.index(start) :] + cycle[: cycle.index(start)]
        strands = tuple(
            dart for dart in rotated if web.bundle_of[dart] == input_bundle
        )
        if len(strands) != 2:
            raise ValueError("Figure 43 row 3 input frame has no two-strand order.")
        return strands  # type: ignore[return-value]

    input_black_block = input_block_strands(tl)
    input_white_block = input_block_strands(tr)
    input_block_matching = tuple(
        input_white_block.index(web.mate[dart])
        for dart in input_black_block
    )
    if sorted(input_block_matching) != [0, 1]:
        raise ValueError("Figure 43 row 3 input strand matching is not bijective.")
    input_frame_offsets = {}
    for vertex, block in ((tl, input_black_block), (tr, input_white_block)):
        cycle = vertex_cycle_ccw(web, int(vertex))
        input_frame_offsets[int(vertex)] = (
            cycle.index(int(input_frame_roots[int(vertex)]))
            - cycle.index(int(block[0]))
        ) % len(cycle)

    def framed_order(vertex: int, block: tuple[int, int]) -> tuple[int, int]:
        cycle = vertex_cycle_ccw(web, int(vertex))
        root = int(input_frame_roots[int(vertex)])
        rotated = cycle[cycle.index(root) :] + cycle[: cycle.index(root)]
        return tuple(dart for dart in rotated if dart in set(block))  # type: ignore[return-value]

    input_black_framed = framed_order(tl, input_black_block)
    input_white_framed = framed_order(tr, input_white_block)
    input_strand_matching = tuple(
        input_white_framed.index(web.mate[dart])
        for dart in input_black_framed
    )

    canonical_removed_tags = {
        int(vertex): int(intrinsic_tag_root(web, int(vertex)))
        for vertex in (tl, tr)
    }
    removed_tag_shifts = {
        int(vertex): _root_shift(
            web, int(vertex), canonical_removed_tags[int(vertex)]
        )
        for vertex in (tl, tr)
    }
    removed_tag_transport_multiplier = (
        -1 if sum(removed_tag_shifts.values()) % 2 else 1
    )

    old_cycles = {bl: vertex_cycle_ccw(web, bl), br: vertex_cycle_ccw(web, br)}
    old_tags = {bl: int(web.tag_after_ccw[bl]), br: int(web.tag_after_ccw[br])}
    result = copy.deepcopy(web)
    removed_vertices = {tl, tr}
    removed_darts = {
        dart for dart, vertex in result.vertex_of.items() if vertex in removed_vertices
    }
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
        for dart in removed_darts:
            mapping.pop(dart, None)
    for vertex in removed_vertices:
        result.color.pop(vertex, None)
        result.boundary_label.pop(vertex, None)
        result.tag_after_ccw.pop(vertex, None)
        result.source_xy.pop(vertex, None)
        result.tensor_valence.pop(vertex, None)

    # Splice the two removed top outside ports through the surviving side
    # darts.  The outside mate darts can belong to arbitrary surrounding web,
    # so preserve them literally and allocate one exact physical edge per
    # splice.
    next_physical = _next_id(result.physical_edge_of.values())
    transported_pairs = (
        (left_at_bl, transported_tl),
        (right_at_br, transported_tr),
    )
    for local_dart, outside_dart in transported_pairs:
        result.mate[local_dart] = outside_dart
        result.mate[outside_dart] = local_dart
        result.physical_edge_of[local_dart] = next_physical
        result.physical_edge_of[outside_dart] = next_physical
        result.edge_kind[local_dart] = EdgeKind.ORDINARY
        result.edge_kind[outside_dart] = EdgeKind.ORDINARY
        result.bundle_of[local_dart] = None
        result.bundle_of[outside_dart] = None
        inherited = {
            result.source_edge_id.get(local_dart),
            result.source_edge_id.get(outside_dart),
        }
        inherited.discard(None)
        source = next(iter(inherited)) if len(inherited) == 1 else None
        result.source_edge_id[local_dart] = source
        result.source_edge_id[outside_dart] = source
        result.source_local_strand[local_dart] = None
        result.source_local_strand[outside_dart] = None
        next_physical += 1

    # Expand the bottom edge to a two-strand hourglass.  The old bottom darts
    # are retained as the first framed strand at each end; the second pair is
    # new.  The exact mate permutation is installed below from the consumed
    # top cable rather than guessed from the number of created strands.
    bundle = _next_id(b for b in result.bundle_of.values() if b is not None)
    next_dart = _next_id(result.vertex_of)
    new_at_bl, new_at_br = next_dart, next_dart + 1
    for dart, vertex in ((new_at_bl, bl), (new_at_br, br)):
        result.vertex_of[dart] = vertex
        result.edge_kind[dart] = EdgeKind.HOURGLASS_STRAND
        result.bundle_of[dart] = bundle
        result.source_edge_id[dart] = None
        result.source_local_strand[dart] = None
    for dart in (bottom_at_bl, bottom_at_br):
        result.edge_kind[dart] = EdgeKind.HOURGLASS_STRAND
        result.bundle_of[dart] = bundle
        result.source_edge_id[dart] = None
        result.source_local_strand[dart] = None
    # Carry the input cable's framed strand matching from its black/white top
    # endpoints to the same-colored black/white bottom endpoints.  This keeps
    # the presentation datum independent of the live tensor tags.
    output_black_strands = (bottom_at_br, new_at_br)
    output_white_strands = (bottom_at_bl, new_at_bl)
    for black_index, white_index in enumerate(input_block_matching):
        first = output_black_strands[black_index]
        second = output_white_strands[white_index]
        result.mate[first] = second
        result.mate[second] = first
        result.physical_edge_of[first] = next_physical
        result.physical_edge_of[second] = next_physical
        next_physical += 1

    replacement_blocks = {
        bl: (bottom_at_bl, new_at_bl),
        br: (bottom_at_br, new_at_br),
    }
    transported_bottom_tags = {}
    for vertex, cycle in old_cycles.items():
        built = []
        for dart in cycle:
            if dart == (bottom_at_bl if vertex == bl else bottom_at_br):
                built.extend(replacement_blocks[vertex])
            else:
                built.append(dart)
        retained_cycle = tuple(
            int(dart) for dart in built if dart in result.vertex_of
        )
        if len(retained_cycle) != 4:
            raise ValueError(
                f"Figure 43 row 3 gives degree {len(retained_cycle)} at {vertex}."
            )
        for current, following in zip(
            retained_cycle, retained_cycle[1:] + retained_cycle[:1]
        ):
            result.next_ccw[current] = following
        old_tag = old_tags[vertex]
        transported_tag = (
            replacement_blocks[vertex][0]
            if old_tag == (bottom_at_bl if vertex == bl else bottom_at_br)
            else old_tag
        )
        if transported_tag not in retained_cycle:
            raise ValueError("Figure 43 row-3 bottom tag was not transported.")
        result.tag_after_ccw[vertex] = int(transported_tag)
        transported_bottom_tags[int(vertex)] = int(transported_tag)
        result.tensor_valence[vertex] = 4

    # Transport the full four-slot strand-frame origin, not merely the mate
    # permutation.  In particular, moving an input frame root through an
    # ordinary slot changes the later Wrench parity even if the order of the
    # two hourglass darts happens to stay the same.
    output_blocks = {
        int(br): output_black_strands,
        int(bl): output_white_strands,
    }
    frame_source_vertex = {int(br): int(tl), int(bl): int(tr)}
    transported_frame_roots = {}
    for output_vertex, block in output_blocks.items():
        cycle = vertex_cycle_ccw(result, output_vertex)
        start_index = cycle.index(int(block[0]))
        offset = input_frame_offsets[frame_source_vertex[output_vertex]]
        transported_frame_roots[output_vertex] = int(
            cycle[(start_index + offset) % len(cycle)]
        )
    result.bundle_frame_root[bundle] = transported_frame_roots
    refresh_bundle_frames(result)
    validate_exact_web(result)
    return ExactRelationBranch(
        relation="figure43_single_top_hourglass_collapse",
        coefficient_multiplier=2 * removed_tag_transport_multiplier,
        web=result,
        certificate=_internal_relation_draft_certificate(
            "figure43_single_top_hourglass_collapse"
        ),
        local_data={
            "cycle": move.cycle,
            "side_kinds": move.side_kinds,
            "facial_turn": move.facial_turn,
            "created_bundle": bundle,
            "input_bundle": input_bundle,
            "input_bundle_frame_roots": {
                str(vertex): int(root)
                for vertex, root in sorted(input_frame_roots.items())
            },
            "input_strand_matching": input_strand_matching,
            "input_block_matching": input_block_matching,
            "input_frame_offsets": input_frame_offsets,
            "created_bundle_frame_roots": {
                str(vertex): int(root)
                for vertex, root in sorted(result.bundle_frame_root[bundle].items())
            },
            "canonical_removed_tags": canonical_removed_tags,
            "removed_tag_shifts": removed_tag_shifts,
            "removed_tag_transport_multiplier": removed_tag_transport_multiplier,
            "transported_bottom_tags": transported_bottom_tags,
            "outside_vertex_darts": {
                "top_left": outside_tl,
                "top_right": outside_tr,
                "bottom_right": outside_br,
                "bottom_left": outside_bl,
            },
            "transported_top_outside_mates": {
                "top_left": transported_tl,
                "top_right": transported_tr,
            },
            "lower_valence_tensor_certificate": "not_available",
            "removed_vertices": (tl, tr),
            "retained_vertices": (br, bl),
        },
    )


def _figure43_side_tokens(
    web: ExactRibbonState, move: ExactFigure43Move
) -> tuple[tuple[str, int], tuple[str, int], tuple[str, int], tuple[str, int]]:
    abstract = _abstract_edges(web)
    lookup = {frozenset(endpoints): token for token, endpoints in abstract.items()}
    return tuple(
        _edge_token_between(lookup, move.cycle[index], move.cycle[(index + 1) % 4])
        for index in range(4)
    )  # type: ignore[return-value]


def _figure43_outside_vertex_darts(
    web: ExactRibbonState, move: ExactFigure43Move
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    tokens = set(_figure43_side_tokens(web, move))
    return tuple(
        tuple(
            dart
            for dart in vertex_cycle_ccw(web, vertex)
            if _abstract_token(web, dart) not in tokens
        )
        for vertex in move.cycle
    )  # type: ignore[return-value]


def _apply_exact_figure43_single_right_hourglass(
    web: ExactRibbonState,
    move: ExactFigure43Move,
) -> tuple[ExactRelationBranch, ExactRelationBranch]:
    """Figure 43 row 4: the two coefficient-one exact branches."""

    if move.rule != "single_right_hourglass":
        raise ValueError("Figure 43 row 4 requires the right-hourglass input.")
    tl, tr, br, bl = move.cycle
    top, right, bottom, left = _figure43_side_tokens(web, move)
    outside = _figure43_outside_vertex_darts(web, move)
    if tuple(len(darts) for darts in outside) != (2, 1, 1, 2):
        raise ValueError("Figure 43 row 4 requires outside-port counts (2,1,1,2).")

    def unique_token_dart(vertex: int, token: tuple[str, int]) -> int:
        matches = [
            dart
            for dart in vertex_cycle_ccw(web, vertex)
            if _abstract_token(web, dart) == token
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one {token} dart at Figure 43 vertex {vertex}.")
        return matches[0]

    right_at_br = [
        dart
        for dart in vertex_cycle_ccw(web, br)
        if _abstract_token(web, dart) == right
    ]
    first_right_at_br = next(
        (
            dart
            for dart in right_at_br
            if _abstract_token(web, web.next_ccw[dart]) == right
        ),
        None,
    )
    if first_right_at_br is None:
        raise ValueError("Figure 43 row-4 input hourglass is not one cyclic block.")
    canonical_input_tags = {
        tl: unique_token_dart(tl, left),
        tr: unique_token_dart(tr, top),
        br: int(first_right_at_br),
        bl: unique_token_dart(bl, left),
    }
    input_tag_shifts = {
        vertex: _root_shift(web, vertex, root)
        for vertex, root in canonical_input_tags.items()
    }
    tag_transport_multiplier = -1 if sum(input_tag_shifts.values()) % 2 else 1

    # First RHS: remove the left edge, turn top and bottom into hourglasses,
    # and turn the right hourglass into one ordinary edge.  External darts,
    # their order, and the red-tag gaps are transported literally.
    open_path = copy.deepcopy(web)
    old_cycles = {vertex: vertex_cycle_ccw(web, vertex) for vertex in move.cycle}
    old_tags = canonical_input_tags
    local_tokens = {top, right, bottom, left}
    removed_darts = {
        dart for dart in web.vertex_of if _abstract_token(web, dart) in local_tokens
    }
    for mapping in (
        open_path.vertex_of,
        open_path.mate,
        open_path.next_ccw,
        open_path.edge_kind,
        open_path.physical_edge_of,
        open_path.bundle_of,
        open_path.source_edge_id,
        open_path.source_local_strand,
    ):
        for dart in removed_darts:
            mapping.pop(dart, None)

    next_dart = _next_id(open_path.vertex_of)
    next_physical = _next_id(open_path.physical_edge_of.values())
    next_bundle = _next_id(
        bundle for bundle in open_path.bundle_of.values() if bundle is not None
    )

    def add_ordinary(u: int, v: int) -> dict[int, tuple[int, ...]]:
        nonlocal next_dart, next_physical
        a, b = next_dart, next_dart + 1
        next_dart += 2
        for dart, vertex in ((a, u), (b, v)):
            open_path.vertex_of[dart] = vertex
            open_path.edge_kind[dart] = EdgeKind.ORDINARY
            open_path.physical_edge_of[dart] = next_physical
            open_path.bundle_of[dart] = None
            open_path.source_edge_id[dart] = None
            open_path.source_local_strand[dart] = None
        open_path.mate[a], open_path.mate[b] = b, a
        next_physical += 1
        return {u: (a,), v: (b,)}

    def add_hourglass(u: int, v: int) -> tuple[int, dict[int, tuple[int, ...]]]:
        nonlocal next_dart, next_physical, next_bundle
        u0, u1, v0, v1 = range(next_dart, next_dart + 4)
        next_dart += 4
        bundle = next_bundle
        next_bundle += 1
        for first, second in ((u0, v0), (u1, v1)):
            for dart, vertex in ((first, u), (second, v)):
                open_path.vertex_of[dart] = vertex
                open_path.edge_kind[dart] = EdgeKind.HOURGLASS_STRAND
                open_path.physical_edge_of[dart] = next_physical
                open_path.bundle_of[dart] = bundle
                open_path.source_edge_id[dart] = None
                open_path.source_local_strand[dart] = None
            open_path.mate[first], open_path.mate[second] = second, first
            next_physical += 1
        return bundle, {u: (u0, u1), v: (v0, v1)}

    top_bundle, top_blocks = add_hourglass(tl, tr)
    right_blocks = add_ordinary(tr, br)
    bottom_bundle, bottom_blocks = add_hourglass(br, bl)
    replacements: dict[tuple[str, int], dict[int, tuple[int, ...]]] = {
        top: top_blocks,
        right: right_blocks,
        bottom: bottom_blocks,
        left: {tl: (), bl: ()},
    }

    def expanded(vertex: int, start: int | None = None) -> tuple[int, ...]:
        cycle = list(old_cycles[vertex])
        if start is not None:
            position = cycle.index(start)
            cycle = cycle[position:] + cycle[:position]
        built: list[int] = []
        handled: set[tuple[str, int]] = set()
        for dart in cycle:
            token = _abstract_token(web, dart)
            if token not in local_tokens:
                built.append(dart)
            elif token not in handled:
                built.extend(replacements[token].get(vertex, ()))
                handled.add(token)
        return tuple(built)

    for vertex in move.cycle:
        cycle = expanded(vertex)
        if len(cycle) != 4:
            raise ValueError(f"Figure 43 row-4 open branch gives degree {len(cycle)} at {vertex}.")
        for current, following in zip(cycle, cycle[1:] + cycle[:1]):
            open_path.next_ccw[current] = following
        rooted = expanded(vertex, old_tags[vertex])
        if not rooted:
            raise ValueError("Figure 43 row-4 tag transport produced an empty cycle.")
        open_path.tag_after_ccw[vertex] = rooted[0]
        open_path.tensor_valence[vertex] = 4
    open_path.bundle_frame_root.pop(int(right[1]), None)
    open_path.bundle_frame_root[top_bundle] = {
        tl: int(top_blocks[tl][0]),
        tr: int(top_blocks[tr][0]),
    }
    open_path.bundle_frame_root[bottom_bundle] = {
        br: int(bottom_blocks[br][0]),
        bl: int(bottom_blocks[bl][0]),
    }
    refresh_bundle_frames(open_path)
    validate_exact_web(open_path)

    # Second RHS: delete the two right vertices, splice their external ports,
    # and reinterpret the two surviving A--D edges as one crossed hourglass.
    top_at_tl = next(
        dart for dart in vertex_cycle_ccw(web, tl) if _abstract_token(web, dart) == top
    )
    bottom_at_bl = next(
        dart for dart in vertex_cycle_ccw(web, bl) if _abstract_token(web, dart) == bottom
    )
    external_tr = web.mate[outside[1][0]]
    external_br = web.mate[outside[2][0]]
    # Figure 43's second row-4 summand splices the two right external ports.
    # A reflected local face reverses their order relative to the displayed
    # paper diagram.  Represent that comparison as an exact labeled
    # permutation; do not turn ``facial_turn`` itself into a coefficient.
    paper_splice_order = ("TR_EXTERNAL", "BR_EXTERNAL")
    engine_splice_order = (
        tuple(reversed(paper_splice_order))
        if int(move.facial_turn) == 1
        else paper_splice_order
    )
    splice_boundary_record = _make_boundary_order_transport_record(
        kind="figure43_splice_boundary_orientation",
        paper_reference="GPPSS Figure 43 single-right-hourglass row",
        paper_order=paper_splice_order,
        engine_order=engine_splice_order,
        diagnostics={
            "facial_turn_replay": int(move.facial_turn),
            "side_kinds": move.side_kinds,
            "exact_label_binding": {
                "TR_EXTERNAL": int(external_tr),
                "BR_EXTERNAL": int(external_br),
            },
        },
    )
    splice_orientation_multiplier = int(
        splice_boundary_record["permutation_sign"]
    )
    splice_coefficient_multiplier = (
        tag_transport_multiplier * splice_orientation_multiplier
    )
    splice = _delete_vertices_and_join_outside_darts(
        web,
        (tr, br),
        ((top_at_tl, bottom_at_bl), (external_tr, external_br)),
    )
    parallel = [
        dart
        for dart in splice.vertex_of
        if {splice.vertex_of[dart], splice.vertex_of[splice.mate[dart]]} == {tl, bl}
        and splice.edge_kind[dart] == EdgeKind.ORDINARY
    ]
    physicals = sorted({splice.physical_edge_of[dart] for dart in parallel})
    if len(parallel) != 4 or len(physicals) != 2:
        raise ValueError("Figure 43 row-4 splice did not produce two A--D strands.")
    splice_bundle = _next_id(
        bundle for bundle in splice.bundle_of.values() if bundle is not None
    )
    for dart in parallel:
        splice.edge_kind[dart] = EdgeKind.HOURGLASS_STRAND
        splice.bundle_of[dart] = splice_bundle
        splice.source_edge_id[dart] = None
        splice.source_local_strand[dart] = None
    splice_half_twist_repaired = enforce_paper_hourglass_half_twist(
        splice, splice_bundle
    )
    # In the displayed second summand the tag at the surviving top-left
    # vertex lies in the gap between
    # its two simple outside ports, while the new hourglass frame remains
    # rooted at the first strand of the crossed block.  Conflating those two
    # roots loses the sign supplied by that local cyclic-order transport.
    tl_cycle = vertex_cycle_ccw(splice, tl)
    tl_outside = [dart for dart in tl_cycle if splice.edge_kind[dart] == EdgeKind.ORDINARY]
    tl_hourglass = [dart for dart in tl_cycle if splice.edge_kind[dart] == EdgeKind.HOURGLASS_STRAND]
    bl_cycle = vertex_cycle_ccw(splice, bl)
    bl_hourglass = [dart for dart in bl_cycle if splice.edge_kind[dart] == EdgeKind.HOURGLASS_STRAND]
    if len(tl_outside) != 2 or len(tl_hourglass) != 2 or len(bl_hourglass) != 2:
        raise ValueError("Figure 43 row-4 splice tag/frame blocks are incomplete.")

    def cyclic_block_start(cycle: tuple[int, ...], members: Iterable[int]) -> int:
        wanted = set(int(dart) for dart in members)
        starts = [
            dart
            for dart in wanted
            if cycle[(cycle.index(dart) - 1) % len(cycle)] not in wanted
        ]
        if len(starts) != 1:
            raise ValueError("Figure 43 row-4 output is not one cyclic block.")
        return int(starts[0])

    tl_outside_start = cyclic_block_start(tl_cycle, tl_outside)
    tl_hourglass_start = cyclic_block_start(tl_cycle, tl_hourglass)
    bl_hourglass_start = cyclic_block_start(bl_cycle, bl_hourglass)
    tl_second_outside = splice.next_ccw[tl_outside_start]
    if tl_second_outside not in set(tl_outside):
        raise ValueError("Figure 43 row-4 outside tag gap is not contiguous.")
    splice.tag_after_ccw[tl] = tl_second_outside
    splice.tag_after_ccw[bl] = bl_hourglass_start
    splice.bundle_frame_root[splice_bundle] = {
        tl: tl_hourglass_start,
        bl: bl_hourglass_start,
    }
    refresh_bundle_frames(splice)
    validate_exact_web(splice)

    base = {
        "cycle": move.cycle,
        "side_kinds": move.side_kinds,
        "facial_turn": move.facial_turn,
        "input_bundle": int(right[1]),
        "canonical_input_tags": {
            str(vertex): int(root) for vertex, root in sorted(canonical_input_tags.items())
        },
        "input_tag_shifts": {
            str(vertex): int(shift) for vertex, shift in sorted(input_tag_shifts.items())
        },
        "tag_transport_multiplier": tag_transport_multiplier,
        "splice_orientation_multiplier": splice_orientation_multiplier,
        "splice_boundary_order_transport_record": (
            splice_boundary_record
        ),
    }
    return (
        ExactRelationBranch(
            "figure43_single_right_open_path",
            tag_transport_multiplier,
            open_path,
            {
                **base,
                "created_bundles": (top_bundle, bottom_bundle),
                "created_bundle_frame_roots": {
                    str(bundle): {
                        str(vertex): int(root)
                        for vertex, root in sorted(open_path.bundle_frame_root[bundle].items())
                    }
                    for bundle in (top_bundle, bottom_bundle)
                },
            },
            _internal_relation_draft_certificate(
                "figure43_single_right_open_path"
            ),
        ),
        ExactRelationBranch(
            "figure43_single_right_hourglass_splice",
            splice_coefficient_multiplier,
            splice,
            {
                **base,
                "created_bundle": splice_bundle,
                "paper_half_twist_repaired": bool(splice_half_twist_repaired),
                "created_bundle_frame_roots": {
                    str(vertex): int(root)
                    for vertex, root in sorted(splice.bundle_frame_root[splice_bundle].items())
                },
                "removed_vertices": (tr, br),
            },
            _internal_relation_draft_certificate(
                "figure43_single_right_hourglass_splice"
            ),
        ),
    )


def exact_forks(web: ExactRibbonState) -> set[frozenset[int]]:
    """Boundary-label pairs incident to one exact internal vertex."""

    validate_exact_web(web)
    result: set[frozenset[int]] = set()
    for vertex, color in web.color.items():
        if color == VertexColor.BOUNDARY:
            continue
        labels = []
        for dart in vertex_cycle_ccw(web, vertex):
            other = web.vertex_of[web.mate[dart]]
            label = web.boundary_label.get(other)
            if label is not None:
                labels.append(int(label))
        result.update(frozenset(pair) for pair in itertools.combinations(labels, 2))
    return result


def exact_direct_boundary_edges(web: ExactRibbonState) -> set[frozenset[int]]:
    validate_exact_web(web)
    result = set()
    for darts in _physical_edges(web).values():
        u, v = _endpoints(web, darts)
        lu, lv = web.boundary_label.get(u), web.boundary_label.get(v)
        if lu is not None and lv is not None:
            result.add(frozenset((int(lu), int(lv))))
    return result


def exact_pair_has_fork_conflict(w: ExactRibbonState, x: ExactRibbonState) -> bool:
    """Symmetric exact common-fork and fork/direct-edge zero tests."""

    return bool(
        exact_forks(w).intersection(exact_forks(x))
        or exact_forks(w).intersection(exact_direct_boundary_edges(x))
        or exact_forks(x).intersection(exact_direct_boundary_edges(w))
    )


def exact_pair_fork_zero_certificate(
    w: ExactRibbonState, x: ExactRibbonState
) -> dict[str, Any] | None:
    """Explain the first exact fork zero rule applicable to a pair state."""

    w_forks = exact_forks(w)
    x_forks = exact_forks(x)
    common = w_forks.intersection(x_forks)
    if common:
        return {
            "reason": "exact_common_fork_lemma",
            "boundary_pairs": sorted(tuple(sorted(pair)) for pair in common),
        }
    w_to_x = w_forks.intersection(exact_direct_boundary_edges(x))
    x_to_w = x_forks.intersection(exact_direct_boundary_edges(w))
    if w_to_x or x_to_w:
        return {
            "reason": "exact_fork_direct_boundary_conflict",
            "w_fork_x_direct": sorted(tuple(sorted(pair)) for pair in w_to_x),
            "x_fork_w_direct": sorted(tuple(sorted(pair)) for pair in x_to_w),
        }
    return None


def _graph_components(web: HalfEdgeWeb) -> list[set[int]]:
    adjacency = {vertex: set() for vertex in web.color}
    for darts in _physical_edges(web).values():
        u, v = _endpoints(web, darts)
        adjacency[u].add(v)
        adjacency[v].add(u)
    result = []
    remaining = set(adjacency)
    while remaining:
        root = min(remaining)
        component = {root}
        frontier = [root]
        while frontier:
            current = frontier.pop()
            for neighbor in adjacency[current] - component:
                component.add(neighbor)
                frontier.append(neighbor)
        remaining.difference_update(component)
        result.append(component)
    return result


def exact_plucker_product_components(
    web: ExactRibbonState, *, r: int = 4
) -> list[list[int]] | None:
    """Return canonical boundary sets when the exact web is a product of r claws."""

    validate_exact_web(web)
    components = []
    for component in _graph_components(web):
        internal = [v for v in component if web.color[v] != VertexColor.BOUNDARY]
        labels = sorted(
            int(web.boundary_label[v])
            for v in component
            if web.boundary_label[v] is not None
        )
        if len(internal) != 1 or len(labels) != r:
            return None
        hub = internal[0]
        cycle = vertex_cycle_ccw(web, hub)
        if len(cycle) != r or any(
            web.color[web.vertex_of[web.mate[dart]]] != VertexColor.BOUNDARY
            or web.edge_kind[dart] != EdgeKind.ORDINARY
            for dart in cycle
        ):
            return None
        components.append(labels)
    if len(components) != r:
        return None
    all_labels = sorted(label for component in components for label in component)
    if all_labels != list(range(1, r * r + 1)):
        return None
    return sorted(components, key=lambda labels: (min(labels), labels))


def _permutation_sign(values: Sequence[int]) -> int:
    inversions = sum(
        values[i] > values[j]
        for i in range(len(values))
        for j in range(i + 1, len(values))
    )
    return -1 if inversions % 2 else 1


def exact_plucker_component_word(
    components: Sequence[Sequence[int]], *, r: int = 4
) -> tuple[int, ...]:
    """Record which terminal Plucker component contains each boundary label.

    The terminal coloring fixes component ``j`` to color ``j``.  Reading those
    colors in boundary-label order produces a word of length ``r**2``.  Its
    inversion parity is a separate orientation datum: it is not the input
    word sign and it is not visible in the cyclic order at any one Plucker
    claw.
    """

    if len(components) != r or any(len(component) != r for component in components):
        raise ValueError(f"Expected {r} terminal components of size {r}.")
    color_by_label: dict[int, int] = {}
    for color, labels in enumerate(components, start=1):
        for raw_label in labels:
            label = int(raw_label)
            if label in color_by_label:
                raise ValueError(f"Boundary label {label} occurs in two components.")
            color_by_label[label] = int(color)
    expected = set(range(1, r * r + 1))
    if set(color_by_label) != expected:
        raise ValueError("Terminal components do not partition all boundary labels.")
    return tuple(color_by_label[label] for label in range(1, r * r + 1))


def exact_plucker_component_word_sign(
    components: Sequence[Sequence[int]], *, r: int = 4
) -> int:
    """Inversion sign of :func:`exact_plucker_component_word`."""

    return _permutation_sign(exact_plucker_component_word(components, r=r))


def exact_plucker_orientation_sign(web: ExactRibbonState, *, r: int = 4) -> int | None:
    if exact_plucker_product_components(web, r=r) is None:
        return None
    sign = 1
    for component in _graph_components(web):
        hub = next(v for v in component if web.color[v] != VertexColor.BOUNDARY)
        labels = [
            int(web.boundary_label[web.vertex_of[web.mate[dart]]])
            for dart in _rooted_cycle(web, hub)
        ]
        ranks = {label: index + 1 for index, label in enumerate(sorted(labels))}
        sign *= _permutation_sign([ranks[label] for label in labels])
    return sign


def exact_plucker_determinant_color_sign(
    web: ExactRibbonState, *, r: int = 4
) -> int | None:
    """Compatibility field for the former determinant-color normalization.

    Black and white vertices are the determinant and dual determinant, with
    dual volume forms normalized consistently.  Color therefore contributes
    no independent scalar.  The actual source sign is already computed by
    :func:`exact_plucker_orientation_sign` from every rooted cyclic order.

    Returning ``1`` for a valid Plucker product keeps older checkpoint/display
    readers fail-safe while making the retired color normalization explicit.
    """

    if exact_plucker_product_components(web, r=r) is None:
        return None
    return 1


def _rooted_cycle(web: HalfEdgeWeb, vertex: int) -> tuple[int, ...]:
    cycle = vertex_cycle_ccw(web, vertex)
    tag = web.tag_after_ccw.get(vertex)
    if tag is None:
        return cycle
    position = cycle.index(tag)
    return cycle[position:] + cycle[:position]


def exact_boundary_condition(components: Sequence[Sequence[int]]) -> dict[int, int]:
    return {
        int(label): color
        for color, labels in enumerate(components, start=1)
        for label in labels
    }


def exact_coloring_data(
    web: ExactRibbonState,
    boundary_color_by_label: Mapping[int, int],
    *,
    r: int = 4,
    limit: int | None = None,
    sample_limit: int = 6,
) -> dict[str, Any]:
    """Count proper colorings and record the paper's local labeling signs.

    ``count`` is the unsigned FLL count from Proposition 2.20.  The separate
    diagnostic ``colored_tensor_signed_count`` sums

        product_v (-1) ** ell_v = (-1) ** sum_v ell_v

    over the same proper colorings.  Following GPPSS Definitions 2.7--2.8,
    every 2-hourglass is one two-subset, and incident subsets are read
    clockwise from the tag.  This signed polynomial-web diagnostic is not
    substituted for the unsigned FLL pairing.  Vertex color contributes no
    independent scalar.

    A 2-hourglass is one unordered pair of distinct colors.  Its canonical
    representative is chosen from the persistent strand frame at its white
    endpoint and transported to the other endpoint by the exact mate
    involution; raw physical-edge IDs never choose the strand order.
    """

    validate_exact_web(web)
    physical = _physical_edges(web)
    edge_ids = sorted(physical)
    incident: dict[int, list[int]] = {vertex: [] for vertex in web.color}
    fixed: dict[int, int] = {}
    for edge in edge_ids:
        u, v = _endpoints(web, physical[edge])
        incident[u].append(edge)
        incident[v].append(edge)
        boundary = [node for node in (u, v) if web.color[node] == VertexColor.BOUNDARY]
        if len(boundary) == 2:
            raise ValueError("Boundary-boundary physical edges are unsupported at coloring.")
        if boundary:
            label = int(web.boundary_label[boundary[0]])
            if label not in boundary_color_by_label:
                raise ValueError(f"Boundary label {label} has no prescribed color.")
            fixed[edge] = int(boundary_color_by_label[label])

    bundle_edges: list[tuple[int, int, int]] = []
    bundle_frame_order: list[dict[str, Any]] = []
    for bundle in sorted({b for b in web.bundle_of.values() if b is not None}):
        members = [
            int(dart)
            for dart, candidate in web.bundle_of.items()
            if candidate == bundle
        ]
        endpoints = sorted({int(web.vertex_of[dart]) for dart in members})
        if len(endpoints) != 2:
            raise ValueError(f"Hourglass bundle {bundle} does not have two endpoints.")
        white_endpoints = [
            vertex for vertex in endpoints if web.color[vertex] == VertexColor.WHITE
        ]
        if len(white_endpoints) != 1:
            raise ValueError(
                f"Hourglass bundle {bundle} does not have one white frame endpoint."
            )
        anchor = int(white_endpoints[0])
        frame_roots = web.bundle_frame_root.get(int(bundle), {})
        if set(frame_roots) != set(endpoints):
            raise ValueError(
                f"Hourglass bundle {bundle} frame endpoints do not match its darts."
            )
        cycle = vertex_cycle_ccw(web, anchor)
        root = int(frame_roots[anchor])
        position = cycle.index(root)
        framed_cycle = cycle[position:] + cycle[:position]
        anchor_darts = tuple(
            int(dart)
            for dart in framed_cycle
            if web.bundle_of[dart] == int(bundle)
        )
        if len(anchor_darts) != 2:
            raise ValueError(
                f"Hourglass bundle {bundle} does not expose two framed strands."
            )
        mate_darts = tuple(int(web.mate[dart]) for dart in anchor_darts)
        physicals = tuple(int(web.physical_edge_of[dart]) for dart in anchor_darts)
        if len(set(physicals)) != 2:
            raise ValueError(f"Hourglass bundle {bundle} does not have two physical strands.")
        if tuple(int(web.physical_edge_of[dart]) for dart in mate_darts) != physicals:
            raise ValueError(
                f"Hourglass bundle {bundle} mate transport changes strand identity."
            )
        bundle_edges.append((int(bundle), physicals[0], physicals[1]))
        bundle_frame_order.append(
            {
                "bundle": int(bundle),
                "anchor_vertex": anchor,
                "anchor_frame_root": root,
                "ordered_anchor_darts": list(anchor_darts),
                "ordered_mate_darts": list(mate_darts),
                "ordered_physical_edges": list(physicals),
            }
        )

    colors = {edge: int(fixed.get(edge, 0)) for edge in edge_ids}
    internal = [v for v, color in web.color.items() if color != VertexColor.BOUNDARY]

    def vertex_possible(vertex: int) -> bool:
        values = [colors[edge] for edge in incident[vertex] if colors[edge]]
        return len(values) == len(set(values))

    def hourglass_possible() -> bool:
        return all(
            not colors[first] or not colors[second] or colors[first] < colors[second]
            for _bundle, first, second in bundle_edges
        )

    for vertex in internal:
        if len(incident[vertex]) != r:
            raise ValueError(
                f"Internal vertex {vertex} has physical degree {len(incident[vertex])}, expected {r}."
            )
        if not vertex_possible(vertex):
            return {
                "count": 0,
                "colored_tensor_signed_count": 0,
                "colored_tensor_positive_count": 0,
                "colored_tensor_negative_count": 0,
                "coloring_samples": [],
                "displayed_coloring_count": 0,
                "coloring_samples_truncated": False,
                "count_is_exact": True,
                "colored_tensor_signed_count_is_exact": True,
                "hourglass_swap_quotient": True,
                "hourglass_bundle_count": len(bundle_edges),
                "hourglass_bundle_frame_order": bundle_frame_order,
                "colored_tensor_sign_convention": (
                    "GPPSS Definition 2.8: product of clockwise-from-tag "
                    "subset coinversion signs; no independent vertex-color scalar"
                ),
                "reason": f"fixed boundary colors conflict at vertex {vertex}",
            }

    free = [edge for edge in edge_ids if edge not in fixed]
    free.sort(
        key=lambda edge: -sum(
            web.color[node] != VertexColor.BOUNDARY
            for node in _endpoints(web, physical[edge])
        )
    )
    count = 0
    colored_tensor_signed_count = 0
    colored_tensor_positive_count = 0
    colored_tensor_negative_count = 0
    samples: list[dict[str, Any]] = []

    def tensor_sign_and_factors() -> tuple[int, list[dict[str, Any]]]:
        sign = 1
        factors = []
        for vertex in sorted(internal):
            rooted_darts = _rooted_cycle(web, int(vertex))
            rooted_physical_edges = tuple(
                int(web.physical_edge_of[dart]) for dart in rooted_darts
            )
            rooted_colors = tuple(colors[edge] for edge in rooted_physical_edges)
            legacy_flattened_levi_sign = _permutation_sign(rooted_colors)
            paper_data = paper_vertex_labeling_data(
                web, int(vertex), colors, r=r
            )
            vertex_sign = int(paper_data["sign"])
            if not paper_data["proper"] or vertex_sign not in {-1, 1}:
                raise ValueError(
                    f"Completed coloring is not a proper subset labeling at vertex {vertex}."
                )
            sign *= vertex_sign
            factors.append(
                {
                    "vertex": int(vertex),
                    "vertex_color": web.color[vertex].name.lower(),
                    "live_tag_root": int(web.tag_after_ccw[vertex]),
                    "rooted_darts": list(rooted_darts),
                    "rooted_physical_edges": list(rooted_physical_edges),
                    "rooted_colors": list(rooted_colors),
                    "legacy_flattened_levi_civita_sign": int(
                        legacy_flattened_levi_sign
                    ),
                    "clockwise_dart_blocks": paper_data[
                        "clockwise_dart_blocks"
                    ],
                    "clockwise_physical_edge_blocks": paper_data[
                        "clockwise_physical_edge_blocks"
                    ],
                    "clockwise_edge_label_subsets": paper_data[
                        "clockwise_edge_label_subsets"
                    ],
                    "coinversion_number": paper_data["coinversion_number"],
                    "paper_coinversion_sign": vertex_sign,
                    "vertex_color_normalization_sign": 1,
                    "vertex_tensor_sign": vertex_sign,
                }
            )
        return int(sign), factors

    def serialize(
        colored_tensor_sign: int,
        rooted_vertex_tensor_factors: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return {
            "colored_tensor_sign": int(colored_tensor_sign),
            "rooted_vertex_tensor_factors": list(rooted_vertex_tensor_factors),
            "physical_edge_colors": [
                {
                    "physical_edge": edge,
                    "endpoints": list(_endpoints(web, physical[edge])),
                    "kind": "hourglass" if web.edge_kind[physical[edge][0]] == EdgeKind.HOURGLASS_STRAND else "ordinary",
                    "bundle": web.bundle_of[physical[edge][0]],
                    "color": colors[edge],
                }
                for edge in edge_ids
            ],
            "hourglass_bundle_color_pairs": [
                {
                    **frame,
                    "ordered_colors": [
                        int(colors[edge])
                        for edge in frame["ordered_physical_edges"]
                    ],
                }
                for frame in bundle_frame_order
            ],
        }

    def backtrack(position: int) -> None:
        nonlocal count
        nonlocal colored_tensor_signed_count
        nonlocal colored_tensor_positive_count
        nonlocal colored_tensor_negative_count
        if limit is not None and count >= limit:
            return
        if position == len(free):
            if hourglass_possible() and all(
                {colors[edge] for edge in incident[vertex]} == set(range(1, r + 1))
                for vertex in internal
            ):
                colored_tensor_sign, vertex_factors = tensor_sign_and_factors()
                count += 1
                colored_tensor_signed_count += int(colored_tensor_sign)
                if colored_tensor_sign > 0:
                    colored_tensor_positive_count += 1
                else:
                    colored_tensor_negative_count += 1
                if len(samples) < max(1, int(sample_limit)):
                    samples.append(serialize(colored_tensor_sign, vertex_factors))
            return
        edge = free[position]
        endpoints = [
            node
            for node in _endpoints(web, physical[edge])
            if web.color[node] != VertexColor.BOUNDARY
        ]
        for color in range(1, r + 1):
            colors[edge] = color
            if hourglass_possible() and all(vertex_possible(vertex) for vertex in endpoints):
                backtrack(position + 1)
            colors[edge] = 0

    backtrack(0)
    count_is_exact = limit is None or count < limit
    return {
        "count": count,
        "colored_tensor_signed_count": colored_tensor_signed_count,
        "colored_tensor_positive_count": colored_tensor_positive_count,
        "colored_tensor_negative_count": colored_tensor_negative_count,
        "coloring_samples": samples,
        "displayed_coloring_count": len(samples),
        "coloring_samples_truncated": count > len(samples),
        "count_is_exact": count_is_exact,
        "colored_tensor_signed_count_is_exact": count_is_exact,
        "hourglass_swap_quotient": True,
        "hourglass_bundle_count": len(bundle_edges),
        "hourglass_bundle_frame_order": bundle_frame_order,
        "colored_tensor_sign_convention": (
            "GPPSS Definition 2.8: product of clockwise-from-tag subset "
            "coinversion signs; no independent vertex-color scalar"
        ),
    }


def evaluate_exact_pair_by_coloring(
    w: ExactRibbonState,
    x: ExactRibbonState,
    *,
    r: int = 4,
    source_side: str | None = None,
) -> dict[str, Any]:
    """Evaluate a terminal pair when a permitted side is a Plucker product.

    With ``source_side=None`` this remains a symmetric standalone diagnostic.
    The production X-active/W-passive scheduler passes ``source_side="X"``:
    a passive Plucker-product W is not permission to stop before reducing X.

    Proposition 2.20 makes the FLL pairing with a canonical Plucker monomial
    the unsigned consistent-labeling count.  The exact tagged Plucker source
    can differ from the canonical Plucker monomial by the product of its local
    cyclic-order parities, so the terminal conversion is exactly

        source rooted Plucker orientation * unsigned count.

    The component-word inversion and the product of local vertex signs on the
    colored web remain diagnostics for the tagged tensor/basis conventions.
    They are not factors in the FLL terminal scalar.

    The scheduler's input ``source_web_sign`` is a separate task-level factor
    and remains outside this function.
    """

    if source_side not in {None, "X", "W"}:
        raise ValueError("source_side must be None, 'X', or 'W'.")
    candidates = (("X", x, w), ("W", w, x))
    for source_name, source, colored in candidates:
        if source_side is not None and source_name != source_side:
            continue
        components = exact_plucker_product_components(source, r=r)
        if components is None:
            continue
        orientation = exact_plucker_orientation_sign(source, r=r)
        if orientation not in {-1, 1}:
            raise UncertifiedRelationError(
                "A recognized Plucker terminal has no certified source "
                "orientation sign."
            )
        source_determinant_color_sign = exact_plucker_determinant_color_sign(
            source, r=r
        )
        component_word = exact_plucker_component_word(components, r=r)
        component_word_sign = _permutation_sign(component_word)
        # Keep intrinsic normalization only as a diagnostic.  Proposition
        # 2.20 uses the unsigned count, so neither this colored-web tag sign
        # nor the FP tensor-sign sum below enters the FLL terminal scalar.
        colored_tag_diagnostic_available = True
        colored_tag_diagnostic_error = ""
        try:
            _normalized_colored, colored_tag_sign, colored_tag_shifts = (
                normalize_intrinsic_tags(colored)
            )
        except (RuntimeError, ValueError) as exc:
            # This normalization is legacy diagnostic metadata, not part of
            # the exact terminal scalar.  An unsupported intrinsic-root
            # search must not abort an otherwise valid tensor contraction.
            colored_tag_diagnostic_available = False
            colored_tag_diagnostic_error = f"{type(exc).__name__}: {exc}"
            colored_tag_sign = None
            colored_tag_shifts = {}
        coloring = exact_coloring_data(colored, exact_boundary_condition(components), r=r)
        diagnostic_coloring_keys = {
            "colored_tensor_signed_count",
            "colored_tensor_positive_count",
            "colored_tensor_negative_count",
            "colored_tensor_signed_count_is_exact",
            "colored_tensor_sign_convention",
            "coloring_samples",
        }
        terminal_coloring = {
            key: value
            for key, value in coloring.items()
            if key not in diagnostic_coloring_keys
        }
        tensor_diagnostics = {
            key: value
            for key, value in coloring.items()
            if key in diagnostic_coloring_keys
        }
        fll_terminal_conversion_sign = int(orientation)
        fll_unsigned_coloring_count = int(coloring["count"])
        fll_pairing_value = (
            fll_terminal_conversion_sign * fll_unsigned_coloring_count
        )
        return {
            **terminal_coloring,
            "status": "computed",
            "source_side": source_name,
            "plucker_factors": components,
            "source_orientation_sign": orientation,
            "source_determinant_color_sign": source_determinant_color_sign,
            "terminal_component_word": component_word,
            "terminal_component_word_inversion_sign": component_word_sign,
            "fll_unsigned_coloring_count": fll_unsigned_coloring_count,
            "fll_terminal_conversion_sign": fll_terminal_conversion_sign,
            "fll_pairing_value": fll_pairing_value,
            "fll_terminal_convention_id": FLL_TERMINAL_CONVENTION_ID,
            "diagnostics_only": {
                **tensor_diagnostics,
                "colored_web_tag_sign": colored_tag_sign,
                "colored_web_tag_shifts": colored_tag_shifts,
                "colored_web_tag_diagnostic_available": (
                    colored_tag_diagnostic_available
                ),
                "colored_web_tag_diagnostic_error": colored_tag_diagnostic_error,
            },
            "terminal_sign_convention": (
                "source rooted Plucker orientation * unsigned FLL consistent-"
                "labeling count; component-word and colored-web local vertex-sign "
                "products are diagnostics only"
            ),
        }
    return {
        "status": "not_computed",
        "reason": "neither exact side is a product of four tagged Plucker claws",
    }


def production_square_moves(web: ExactRibbonState) -> tuple[ExactSquareMove, ...]:
    """Return every Figure 2 move (0/1/2/3/4 outward hourglasses)."""

    validate_exact_web(web)
    return detect_exact_square_moves(web)


def apply_exact_square_relation(
    web: ExactRibbonState,
    move: ExactSquareMove,
    *,
    verify_round_trip: bool = True,
    _certify: bool = True,
) -> ExactRelationBranch:
    """Apply a canonically tagged Figure 2 square relation.

    The author-corrected project convention supplies the skein coefficient
    sign: untwist parity is applied at every affected internal black and white
    vertex.  (The current draft's black-only wording is known to be
    inaccurate.)  GPPSS Definition 6.3 supplies the missing canonical tag
    sectors, and Theorem 6.10 says square moves do not change the invariant
    with those tags.  Drawn strand frames remain replay/topology data and never
    contribute a square coefficient.
    """

    available = {
        exact_square_move_key(candidate): candidate
        for candidate in detect_exact_square_moves(web)
    }
    key = exact_square_move_key(move)
    if not move.side_physical_edges:
        compatible = [
            candidate
            for candidate in available.values()
            if _canonical_cycle(candidate.cycle) == _canonical_cycle(move.cycle)
        ]
        if len(compatible) == 1:
            key = exact_square_move_key(compatible[0])
    if key not in available:
        raise ValueError("The requested exact square move is no longer applicable.")
    move = available[key]
    local_vertices = _multiplicity_closed_local_vertices(web, move.cycle)
    (
        source_global_tag_sign,
        source_shifts,
        source_paper_roots,
        source_vertex_untwist_factors,
        source_tag_root_modes,
    ) = _local_square_paper_tag_transport(
        web, local_vertices
    )
    # A local relation transports tags only at vertices in its
    # multiplicity-closed support.  The old implementation multiplied the
    # intrinsic-tag parity of *every* vertex in the ambient web, allowing an
    # unrelated odd tag (often several faces away) to flip a square
    # coefficient.  That violated locality and the paper convention that the
    # sign is the product of cyclic-order permutations at affected vertices.
    source_vertex_untwist_multiplier = 1
    for factor in source_vertex_untwist_factors.values():
        source_vertex_untwist_multiplier *= int(factor)
    raw_child = apply_exact_square_move(web, move)
    child = copy.deepcopy(raw_child)
    transported_raw_child_tags = {
        int(vertex): int(root)
        for vertex, root in raw_child.tag_after_ccw.items()
        if root is not None
    }
    new_vertices = set(child.color) - set(web.color)
    source_bundles = {bundle for bundle in web.bundle_of.values() if bundle is not None}
    child_bundles = {bundle for bundle in child.bundle_of.values() if bundle is not None}
    new_bundles = child_bundles - source_bundles
    # ``apply_exact_square_move`` roots every new vertex at the transported
    # first square-side dart.  That is algebraic ribbon data, not a temporary
    # implementation choice.  Replacing it with ``intrinsic_tag_root`` used
    # to rotate every newly created tensor by one slot.  A 1<->3 move creates
    # one tensor and consequently acquired a spurious minus; a 2<->2 move
    # creates two and hid the same bug through cancellation.  Keep the
    # transported tensor roots.  The hourglass frame is deliberately
    # independent: initialize both endpoints from the intrinsic strand
    # reference after the complete output ribbon state exists.  Equating this
    # frame with the live tag lost the odd orientation of a generated H-corner
    # and made later square coefficients path-dependent.
    for bundle in new_bundles:
        roots: dict[int, int] = {}
        for vertex in child.bundle_frame_root[int(bundle)]:
            try:
                root = intrinsic_tag_root(child, int(vertex))
            except ValueError:
                root = child.tag_after_ccw.get(int(vertex))
            if root is None:
                raise UncertifiedRelationError(
                    f"New square bundle endpoint {vertex} has no supported frame root."
                )
            roots[int(vertex)] = int(root)
        child.bundle_frame_root[int(bundle)] = roots
    refresh_bundle_frames(child)
    output_seed_vertices = (
        set(local_vertices) & set(child.color)
    ) | set(new_vertices)
    output_local_vertices = _multiplicity_closed_local_vertices(
        child, tuple(sorted(output_seed_vertices))
    )
    raw_child_paper_roots: dict[int, int] = {}
    output_tag_root_modes: dict[int, str] = {}
    for vertex in output_local_vertices:
        try:
            root = intrinsic_tag_root(child, int(vertex))
            output_tag_root_modes[int(vertex)] = "gppss_definition_6_3_intrinsic"
        except ValueError:
            root = child.tag_after_ccw.get(int(vertex))
            output_tag_root_modes[int(vertex)] = (
                "figure2_live_tag_transport_outside_definition_6_3_domain"
            )
        if root is None:
            raise UncertifiedRelationError(
                f"Affected square output vertex {vertex} has no supported tag root."
            )
        raw_child_paper_roots[int(vertex)] = int(root)
    canonicalized_child_tags: dict[int, dict[str, int]] = {}
    for vertex in output_local_vertices:
        current = int(child.tag_after_ccw[int(vertex)])
        target = int(raw_child_paper_roots[int(vertex)])
        child.tag_after_ccw[int(vertex)] = int(target)
        paper_incident_edge_blocks_clockwise(child, int(vertex))
        if current != int(target):
            canonicalized_child_tags[int(vertex)] = {
                "transported_raw_root": current,
                "canonical_root": int(target),
            }
    (
        raw_child_tag_sign,
        raw_child_tag_shifts,
        _canonical_child_paper_roots,
        _canonical_child_tag_factors,
        _raw_child_tag_root_modes,
    ) = _local_square_paper_tag_transport(child, output_local_vertices)
    new_bundle_frame_audit = {
        str(bundle): {
            str(vertex): int(root)
            for vertex, root in sorted(child.bundle_frame_root[int(bundle)].items())
        }
        for bundle in sorted(new_bundles)
    }
    validate_exact_web(child)

    # H corners disappear.  Their tag parities cannot be carried by a vertex
    # that no longer exists, so their real antisymmetric sign is recorded on
    # the relation coefficient.  Tags on every retained vertex are transported
    # in-place by the exact dart rewrite.  O corners create new vertices whose
    # tag roots are transported from the ordered square-side block.
    removed_vertices = {
        vertex
        for vertex, kind in zip(move.cycle, move.corner_kinds)
        if kind == "H"
    }
    removed_tag_shifts = {vertex: source_shifts[vertex] for vertex in removed_vertices}
    removed_frame_shifts: dict[int, int] = {}
    removed_frame_bundles: dict[int, int] = {}
    for vertex in removed_vertices:
        local_bundles = {
            int(web.bundle_of[dart])
            for dart in vertex_cycle_ccw(web, vertex)
            if web.bundle_of[dart] is not None
        }
        if len(local_bundles) != 1:
            raise ValueError(
                f"Square H-corner {vertex} does not expose exactly one framed bundle."
            )
        bundle = next(iter(local_bundles))
        removed_frame_bundles[vertex] = bundle
        removed_frame_shifts[vertex] = _root_shift(
            web, vertex, web.bundle_frame_root[bundle][vertex]
        )
    # A disappearing H-corner must carry the parity from its live tensor tag
    # to the independently stored hourglass frame.  ``removed_tag_shifts`` is
    # retained as an intrinsic-root diagnostic only.  Adding that shift to the
    # frame shift would count the live-tag rotation twice: both quantities are
    # measured from the same live root, so a one-slot tag change would cancel
    # itself and incorrectly leave coefficient +1.
    removed_tag_parity = sum(removed_tag_shifts.values()) % 2
    removed_frame_parity = sum(removed_frame_shifts.values()) % 2
    tensor_certified_multiplier = _certified_square_local_coefficient(
        web,
        child,
        local_vertices,
        output_local_vertices,
    )
    multiplier = int(tensor_certified_multiplier)
    raw_candidate_relation_multiplier = int(multiplier)
    raw_candidate_passive_coloring_multiplier = (
        int(source_global_tag_sign) * int(raw_child_tag_sign)
    )
    raw_candidate_digest = exact_state_digest(child)
    history_action = "push"
    if web.square_undo_stack:
        saved_parent = web.square_undo_stack[-1]
        if _square_topology_key(child) == _square_topology_key(saved_parent):
            child = copy.deepcopy(saved_parent)
            child.square_undo_stack = tuple(
                copy.deepcopy(snapshot)
                for snapshot in web.square_undo_stack[:-1]
            )
            child.square_undo_multipliers = tuple(
                int(value) for value in web.square_undo_multipliers[:-1]
            )
            multiplier = int(web.square_undo_multipliers[-1])
            history_action = "pop"

    if history_action == "push":
        snapshot = copy.deepcopy(web)
        snapshot.square_undo_stack = ()
        snapshot.square_undo_multipliers = ()
        child.square_undo_stack = tuple(
            copy.deepcopy(item) for item in web.square_undo_stack
        ) + (snapshot,)
        child.square_undo_multipliers = tuple(
            int(value) for value in web.square_undo_multipliers
        ) + (int(multiplier),)

    validate_exact_web(child)
    returned_output_seed_vertices = (
        set(local_vertices) & set(child.color)
    ) | (set(child.color) - set(web.color))
    returned_output_local_vertices = _multiplicity_closed_local_vertices(
        child, tuple(sorted(returned_output_seed_vertices))
    )
    (
        child_global_tag_sign,
        child_shifts,
        child_paper_roots,
        _child_tag_factors,
        returned_child_tag_root_modes,
    ) = _local_square_paper_tag_transport(
        child, returned_output_local_vertices
    )
    # The exact square coefficient is bilinear and therefore governs either
    # argument.  The ratio below is retained only to diagnose the superseded
    # terminal shortcut ``intrinsic_tag_sign * unsigned_coloring_count``.  It
    # is not a second mathematical square coefficient: the full live-root
    # tensor sum already contains those tag parities locally.
    legacy_passive_tag_multiplier = (
        int(source_global_tag_sign) * int(child_global_tag_sign)
    )
    returned_new_vertices = set(child.color) - set(web.color)
    returned_child_bundles = {
        bundle for bundle in child.bundle_of.values() if bundle is not None
    }
    returned_new_bundles = returned_child_bundles - source_bundles
    returned_bundle_frame_audit = {
        str(bundle): {
            str(vertex): int(root)
            for vertex, root in sorted(child.bundle_frame_root[int(bundle)].items())
        }
        for bundle in sorted(returned_new_bundles)
    }
    retained_vertex_tag_changes = {
        int(vertex): {
            "source_root": int(web.tag_after_ccw[int(vertex)]),
            "returned_root": int(child.tag_after_ccw[int(vertex)]),
        }
        for vertex in sorted(set(web.color) & set(child.color))
        if web.color[int(vertex)] != VertexColor.BOUNDARY
        and int(web.tag_after_ccw[int(vertex)])
        != int(child.tag_after_ccw[int(vertex)])
    }
    if verify_round_trip and history_action == "push":
        # The inverse assertion is local and the undo snapshot retains the
        # exact source tags.  Globally normalizing every ambient vertex here
        # made an unrelated parallel-edge component veto an otherwise valid
        # square.  Compare the exact saved source (masking only temporary edge
        # lineage) to the exact inverse output instead.
        source_key = _frame_blind_web_key(web)
        recovered = []
        for inverse in detect_exact_square_moves(child):
            inverse_branch = apply_exact_square_relation(
                child, inverse, verify_round_trip=False, _certify=False
            )
            recovered.append(inverse_branch.web)
        if not any(_frame_blind_web_key(candidate) == source_key for candidate in recovered):
            raise AssertionError(
                f"Exact square move {move.cycle} is not reversible after exact tag transport."
            )
    draft = ExactRelationBranch(
        relation=f"figure2_square_{move.hourglass_count}hg_to_{4 - move.hourglass_count}hg",
        coefficient_multiplier=multiplier,
        web=child,
        certificate=_internal_relation_draft_certificate(
            f"figure2_square_{move.hourglass_count}hg_to_{4 - move.hourglass_count}hg"
        ),
        local_data={
            "cycle": move.cycle,
            "side_physical_edges": move.side_physical_edges,
            "facial_turn": move.facial_turn,
            "corner_kinds": move.corner_kinds,
            # Backward-compatible name for the raw local relation sign.  New
            # audit consumers should use the explicit raw/applied fields.
            "removed_tag_sign": raw_candidate_relation_multiplier,
            "raw_candidate_relation_multiplier": raw_candidate_relation_multiplier,
            "applied_coefficient_multiplier": int(multiplier),
            "removed_tag_shifts": removed_tag_shifts,
            "removed_tag_parity": removed_tag_parity,
            "removed_frame_shifts": removed_frame_shifts,
            "removed_frame_parity": removed_frame_parity,
            "removed_frame_bundles": removed_frame_bundles,
            "source_global_tag_sign": source_global_tag_sign,
            "source_vertex_untwist_factors": source_vertex_untwist_factors,
            "source_tag_root_modes": source_tag_root_modes,
            "source_vertex_untwist_multiplier": source_vertex_untwist_multiplier,
            "tensor_certified_tag_transport_multiplier": (
                tensor_certified_multiplier
            ),
            "skein_sign_source": (
                "author-corrected all-internal-vertex untwist parity; "
                "GPPSS Theorem 6.10 canonical square coefficient +1"
            ),
            "transported_raw_child_tags": transported_raw_child_tags,
            "canonicalized_child_tags": canonicalized_child_tags,
            "output_tag_root_modes": output_tag_root_modes,
            "raw_child_global_tag_sign": raw_child_tag_sign,
            "child_global_tag_sign": child_global_tag_sign,
            "raw_candidate_passive_coloring_multiplier": (
                raw_candidate_passive_coloring_multiplier
            ),
            # Deprecated compatibility alias.  New code must use
            # ``coefficient_multiplier`` on both sides.
            "passive_coloring_multiplier": legacy_passive_tag_multiplier,
            "legacy_passive_tag_multiplier": legacy_passive_tag_multiplier,
            "source_tag_shifts": source_shifts,
            "raw_child_tag_shifts": raw_child_tag_shifts,
            "child_tag_shifts": child_shifts,
            "returned_child_tag_root_modes": returned_child_tag_root_modes,
            "retained_vertex_tags_preserved": not retained_vertex_tag_changes,
            "retained_vertex_tag_changes": retained_vertex_tag_changes,
            "child_tag_policy": (
                "use the GPPSS Definition-6.3 sector inside its fully-reduced "
                "domain; otherwise retain the exact Figure-2 transported tag"
            ),
            "raw_candidate": {
                "digest": raw_candidate_digest,
                "relation_multiplier": raw_candidate_relation_multiplier,
                "passive_coloring_multiplier": (
                    raw_candidate_passive_coloring_multiplier
                ),
                "global_tag_sign": raw_child_tag_sign,
                "tag_shifts": raw_child_tag_shifts,
                "new_vertices": tuple(sorted(new_vertices)),
                "new_bundle_frames": new_bundle_frame_audit,
            },
            "returned_child": {
                "digest": exact_state_digest(child),
                "applied_multiplier": int(multiplier),
                "passive_coloring_multiplier": legacy_passive_tag_multiplier,
                "legacy_passive_tag_multiplier": legacy_passive_tag_multiplier,
                "global_tag_sign": child_global_tag_sign,
                "tag_shifts": child_shifts,
                "new_vertices": tuple(sorted(returned_new_vertices)),
                "new_bundle_frames": returned_bundle_frame_audit,
            },
            "new_vertices_side_transport_tagged": tuple(
                sorted(returned_new_vertices)
            ),
            "new_bundle_frames": returned_bundle_frame_audit,
            "square_history_action": history_action,
            "square_history_depth": len(child.square_undo_stack),
        },
    )
    if not _certify:
        return draft
    boundary_port_labels = exact_local_boundary_port_label_map(
        web, local_vertices
    )
    local_input = extract_exact_local_tensor_fixture(
        web,
        local_vertices,
        boundary_label_by_outside_dart=boundary_port_labels,
    )
    local_output = extract_exact_local_tensor_fixture(
        draft.web,
        returned_output_local_vertices,
        boundary_label_by_outside_dart=boundary_port_labels,
    )
    local_draft = replace(draft, web=local_output)
    paper_roots = dict(source_paper_roots)
    return certify_exact_relation_branches(
        relation=draft.relation,
        paper_reference="GPPSS Figure 2 and Theorem 6.10; project Proposition 2.15",
        input_web=web,
        output_branches=(draft,),
        local_input=local_input,
        local_output_branches=(local_draft,),
        formal_coefficients=(1,),
        tag_transport_multipliers=(int(multiplier),),
        input_paper_tag_roots=paper_roots,
        output_paper_tag_roots=(child_paper_roots,),
        allow_single_branch_tensor_ratio_residual=True,
        diagnostics={
            "history_action": history_action,
            "square_hourglass_count": int(move.hourglass_count),
            "tensor_certificate_vertices": list(local_vertices),
            "tensor_certificate_output_vertices": list(
                returned_output_local_vertices
            ),
            "coefficient_excludes_vertex_colors": True,
            "coefficient_excludes_source_ancestry": True,
            "coefficient_excludes_bundle_ids": True,
            "single_branch_tensor_ratio_residual_allowed": True,
        },
    )[0]


def apply_production_square_move(
    web: ExactRibbonState, move: ExactSquareMove, *, verify_round_trip: bool = True
) -> ExactRibbonState:
    """Apply one exact square move and optionally prove an inverse move exists."""

    return apply_exact_square_relation(
        web,
        move,
        verify_round_trip=verify_round_trip,
    ).web


def unsupported_tagged_figure9_witnesses(
    web: ExactRibbonState,
) -> tuple[Mapping[str, Any], ...]:
    """Describe Figure-9 topologies without applying an uncertified rewrite.

    This fail-closed guard exposes the exact cyclic information needed for a
    future mathematical decision.  It never constructs an output state or a
    coefficient and is therefore not a production relation.
    """

    witnesses: list[Mapping[str, Any]] = []
    for move in _detect_audit_only_tagged_figure9_candidates(web):
        vertices = (int(move.center), *(int(v) for v in move.outer_vertices))
        cyclic_data = {
            str(vertex): {
                "color": int(web.color[vertex]),
                "ccw_dart_cycle": tuple(
                    int(dart) for dart in vertex_cycle_ccw(web, vertex)
                ),
                "live_tag_root": int(web.tag_after_ccw[vertex]),
            }
            for vertex in vertices
        }
        alternatives: list[str] = []
        for bundle in bundle_ids(web):
            try:
                exact_wrench_relation(web, int(bundle))
            except ValueError:
                continue
            alternatives.append(f"wrench_bundle_{int(bundle)}")
        witnesses.append(
            {
                "reason_code": "unsupported_tagged_figure9",
                "state_digest": exact_state_digest(web),
                "center": int(move.center),
                "bundles": tuple(int(bundle) for bundle in move.bundles),
                "outer_vertices": tuple(int(v) for v in move.outer_vertices),
                "cyclic_data": cyclic_data,
                "available_certifiable_alternatives": tuple(sorted(alternatives)),
            }
        )
    return tuple(witnesses)


def exact_relation_inventory(web: ExactRibbonState) -> dict[str, Any]:
    """Expose what the production kernel can apply without a lossy fallback."""

    double = detect_exact_double_edge_moves(web)
    figure43 = detect_exact_figure43_moves(web)
    squares = production_square_moves(web)
    return {
        "wrench_bundles": bundle_ids(web),
        "double_trident_edges": detect_exact_double_tridents(web),
        "double_edge_moves": double,
        "figure43_moves": figure43,
        "square_moves": squares,
        "square_move_hourglass_counts": sorted({move.hourglass_count for move in squares}),
        "square_move_tag_transport": (
            "explicit rooted cyclic-order parity at every vertex; retained tags "
            "preserved; new tags use ordered side transport"
        ),
        "square_move_frame_transport": (
            "lossless full-parent snapshots with exact signed inverse unwind"
        ),
        "square_move_side_signs": (
            "both arguments use framed relation parity; the old global colored-tag "
            "ratio is diagnostic only"
        ),
        "square_move_history_depth": len(web.square_undo_stack),
        "square_move_scheduler_policy": "unwind saved parents before skein reduction",
        "pair_pattern_zero_certificates": {
            "lemma49": "exact ports/resources/rotation; opt-in",
            "lemma48": "exact-state incidence adapter; opt-in",
        },
        "figure43_row4_status": "production_tensor_and_confluence_certified",
        "audit_only_relations": (
            "lemma48_pair_pattern_zero",
            "lemma49_pair_pattern_zero",
            "tagged_figure9_tensor_experiments",
        ),
        "unsupported_relations": (
            "compact frame transport across an un-unwound square/skein interleaving",
            "tagged Figure 9 contraction pending merged tag/cyclic-order proof",
            "Figure 43 single-top row pending oriented trivalent tensor encoding",
        ),
    }
