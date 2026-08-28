"""Isolated vectorized evaluator for exact local SL4 tensor audits.

This module is deliberately separate from the frozen production tensor oracle.
It contracts the same finite tensor network as
``exact_local_tensor_oracle_20260819.exact_boundary_tensor`` but uses NumPy's
Einstein summation to eliminate internal color indices in bulk.  It is used by
large offline recurrence audits only; production pairing and skein relations
do not import it.

Every accepted contraction is exact over the integers.  The factors contain
only ``0``, ``1``, and ``-1``.  Before contracting, the evaluator checks a
conservative bound on every possible partial sum and refuses a network that
could overflow signed 64-bit arithmetic.  It also refuses NumPy networks with
more index labels than ``einsum`` supports, rather than silently changing the
calculation.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from typing import Sequence

import numpy as np

from exact_local_tensor_oracle_20260819 import (
    ExactLinearRelationTensorCertificate,
)
from halfedge_web_20260812 import (
    ExactRibbonState,
    VertexColor,
    paper_vertex_labeling_sign,
    validate_exact_web,
    vertex_cycle_ccw,
)


_COLORS = (1, 2, 3, 4)
_MAX_EINSUM_INDICES = 52
_INT64_MAX = int(np.iinfo(np.int64).max)


def _ordered_bundle_darts(
    web: ExactRibbonState, bundle: int, vertex: int
) -> tuple[int, int]:
    """Read a bundle's two darts from its persistent strand frame."""

    cycle = vertex_cycle_ccw(web, int(vertex))
    root = int(web.bundle_frame_root[int(bundle)][int(vertex)])
    position = cycle.index(root)
    rotated = cycle[position:] + cycle[:position]
    members = tuple(
        int(dart)
        for dart in rotated
        if web.bundle_of[dart] == int(bundle)
    )
    if len(members) != 2:
        raise ValueError("A fast tensor-oracle 2-hourglass needs two framed darts.")
    return members


def exact_boundary_tensor_fast(
    web: ExactRibbonState,
) -> dict[tuple[int, ...], int]:
    """Return the exact boundary tensor using vectorized contraction.

    Semantics match the frozen exhaustive evaluator:

    * ordinary mates carry one shared color;
    * a 2-hourglass carries an unordered distinct pair, ordered by its stored
      per-bundle frame at one endpoint and transported through the mate map;
    * each internal vertex is evaluated by Definition 2.8: incident subset
      labels are read clockwise from the tag and signed by coinversion parity;
    * a boundary-to-boundary edge contributes a Kronecker delta while retaining
      both boundary tensor slots.
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
        int(vertex)
        for vertex in sorted(web.color)
        if web.color[vertex] != VertexColor.BOUNDARY
    ]
    if any(
        len(vertex_cycle_ccw(web, vertex)) != 4
        for vertex in internal_vertices
    ):
        raise ValueError(
            "The fast exact tensor oracle requires four darts at every internal vertex."
        )

    by_physical: dict[int, list[int]] = defaultdict(list)
    for dart, physical in web.physical_edge_of.items():
        by_physical[int(physical)].append(int(dart))

    dart_index: dict[int, int] = {}
    factors: list[object] = []
    next_index = 0
    delta = np.eye(4, dtype=np.int64)
    for physical, darts in sorted(by_physical.items()):
        if len(darts) != 2:
            raise ValueError(
                f"Physical strand {physical} has {len(darts)} darts instead of two."
            )
        boundary_darts = [
            dart
            for dart in darts
            if web.color[web.vertex_of[dart]] == VertexColor.BOUNDARY
        ]
        if len(boundary_darts) == 2:
            first_index, second_index = next_index, next_index + 1
            next_index += 2
            dart_index[boundary_darts[0]] = first_index
            dart_index[boundary_darts[1]] = second_index
            factors.extend((delta, [first_index, second_index]))
        else:
            index = next_index
            next_index += 1
            for dart in darts:
                dart_index[dart] = index

    if next_index > _MAX_EINSUM_INDICES:
        raise ValueError(
            f"Fast tensor contraction needs {next_index} indices; NumPy einsum "
            f"supports at most {_MAX_EINSUM_INDICES}."
        )

    for vertex in internal_vertices:
        cycle = vertex_cycle_ccw(web, int(vertex))
        physicals = tuple(int(web.physical_edge_of[dart]) for dart in cycle)
        factor = np.zeros((4, 4, 4, 4), dtype=np.int64)
        for assignment in itertools.product(range(4), repeat=4):
            physical_colors = {
                physical: int(color) + 1
                for physical, color in zip(physicals, assignment)
            }
            factor[assignment] = paper_vertex_labeling_sign(
                web, int(vertex), physical_colors, r=4
            )
        indices = [
            dart_index[dart]
            for dart in cycle
        ]
        factors.extend((factor, indices))

    unordered_pair = np.triu(np.ones((4, 4), dtype=np.int64), 1)
    bundles = sorted(
        {
            int(bundle)
            for bundle in web.bundle_of.values()
            if bundle is not None
        }
    )
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
        framed = _ordered_bundle_darts(web, bundle, endpoints[0])
        factors.extend(
            (
                unordered_pair,
                [dart_index[framed[0]], dart_index[framed[1]]],
            )
        )

    output_indices = [
        dart_index[vertex_cycle_ccw(web, vertex)[0]]
        for _label, vertex in boundary
    ]
    if len(set(output_indices)) != len(output_indices):
        raise RuntimeError(
            "Distinct boundary slots unexpectedly share an einsum index."
        )
    summed_indices = set(range(next_index)) - set(output_indices)
    # Every local factor has absolute value at most one.  Thus 4**N bounds
    # every output entry and every partial contraction entry, where N is the
    # number of eliminated four-color indices.
    if 4 ** len(summed_indices) > _INT64_MAX:
        raise OverflowError(
            "Fast exact tensor contraction could overflow int64; use the "
            "exhaustive reference evaluator for this fixture."
        )

    if not factors:
        tensor = np.ones((4,) * len(output_indices), dtype=np.int64)
    else:
        tensor = np.einsum(
            *factors,
            output_indices,
            optimize="greedy",
            dtype=np.int64,
        )
    return {
        tuple(int(index) + 1 for index in assignment): int(tensor[assignment])
        for assignment in np.ndindex(tensor.shape)
    }


def certify_exact_linear_relation_fast(
    left: ExactRibbonState,
    branches: Sequence[tuple[int, ExactRibbonState]],
) -> ExactLinearRelationTensorCertificate:
    """Certify a local linear relation with the isolated fast evaluator."""

    left_tensor = exact_boundary_tensor_fast(left)
    right_tensors = [
        (int(coefficient), exact_boundary_tensor_fast(web))
        for coefficient, web in branches
    ]
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
        branch_coefficients=tuple(
            coefficient for coefficient, _tensor in right_tensors
        ),
        assignments_checked=len(left_keys),
        nonzero_left_assignments=sum(
            value != 0 for value in left_tensor.values()
        ),
        nonzero_right_assignments=nonzero_right,
    )
