"""Deterministic exact-dart scheduler, checkpointing, and audit serialization.

This is deliberately independent of the legacy neighbor-list scheduler.  It
only consumes ``ExactRibbonState`` objects and exact relation branches.  The
first production target is the current X-active/W-passive pairing pipeline.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from exact_pairing_kernel_20260819 import (
    EXACT_STATE_KEY_SCHEMA,
    FLL_TERMINAL_CONVENTION_ID,
    ExactDoubleEdgeMove,
    ExactPairTerm,
    ExactRelationBranch,
    ProvenanceRoute,
    apply_exact_double_edge_move,
    apply_exact_figure43_move,
    apply_exact_square_relation,
    consolidate_exact_pair_terms,
    detect_exact_double_edge_moves,
    detect_exact_double_tridents,
    detect_exact_figure43_moves,
    evaluate_exact_pair_by_coloring,
    exact_double_trident_relation,
    exact_pair_fork_zero_certificate,
    exact_state_digest,
    exact_wrench_relation,
    expand_exact_pair_term,
    production_square_moves,
    require_production_relation_certificate,
    UncertifiedRelationError,
    unsupported_tagged_figure9_witnesses,
    validated_provenance_routes,
)
from exact_zero_certificates_20260819 import exact_pair_pattern_zero_certificate
from halfedge_web_20260812 import (
    EdgeKind,
    ExactRibbonState,
    HalfEdgeWeb,
    VertexColor,
    bundle_ids,
    canonical_web_key,
    legacy_source_presence_web_key,
    refresh_bundle_frames,
    validate_exact_web,
)


SCHEMA = "problem3.exact_pairing_checkpoint.v2"
LEGACY_SCHEMAS = {"problem3.exact_pairing_checkpoint.v1"}


def word_inversion_sign(word: str) -> int:
    """BCGMMW source sign for the exact presentation's boundary word."""

    letters = [int(letter) for letter in str(word).strip()]
    inversions = sum(
        letters[left] > letters[right]
        for left in range(len(letters))
        for right in range(left + 1, len(letters))
    )
    return -1 if inversions % 2 else 1


@dataclass(frozen=True)
class ExactSchedulerLimits:
    max_expansions: int = 100_000
    max_active_terms: int = 100_000


@dataclass
class ExactSchedulerResult:
    status: str
    value: int | None
    expansions: int
    relation_counts: dict[str, int]
    terminal_terms: list[dict[str, Any]]
    zero_terms: list[dict[str, Any]]
    unresolved_terms: list[ExactPairTerm]
    active_terms: list[ExactPairTerm]
    reason: str = ""
    initial_w: dict[str, Any] | None = None
    initial_x: dict[str, Any] | None = None
    source_web_sign: int = 1
    reason_code: str = ""
    unresolved_witnesses: list[dict[str, Any]] = field(default_factory=list)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (EdgeKind, VertexColor)):
        return int(value)
    if isinstance(value, Path):
        return str(value)
    return value


def serialize_exact_web(web: ExactRibbonState) -> dict[str, Any]:
    """Lossless JSON payload for replay and the website branch inspector."""

    validate_exact_web(web)
    return {
        "schema": "problem3.exact_ribbon_state.v4",
        "digest_schema": EXACT_STATE_KEY_SCHEMA,
        "digest": exact_state_digest(web),
        "bundle_frames": [
            {
                "bundle": int(bundle),
                "roots": {
                    str(vertex): int(root)
                    for vertex, root in sorted(roots.items())
                },
            }
            for bundle, roots in sorted(web.bundle_frame_root.items())
        ],
        "square_undo_stack": [
            serialize_exact_web(snapshot) for snapshot in web.square_undo_stack
        ],
        "square_undo_multipliers": [
            int(value) for value in web.square_undo_multipliers
        ],
        "vertices": [
            {
                "id": int(vertex),
                "color": int(web.color[vertex]),
                "boundary_label": web.boundary_label[vertex],
                "tag_after_ccw": web.tag_after_ccw[vertex],
                "tensor_valence": int(
                    web.tensor_valence.get(
                        vertex,
                        1 if web.color[vertex] == VertexColor.BOUNDARY else 4,
                    )
                ),
                "source_xy": list(web.source_xy[vertex]) if vertex in web.source_xy else None,
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
                # Retained for reading older development checkpoints.  Exact
                # roots now live in top-level ``bundle_frames`` because a
                # bundle frame may be rooted at an ordinary endpoint dart.
                "bundle_frame_root": any(
                    roots.get(web.vertex_of[dart]) == dart
                    for roots in web.bundle_frame_root.values()
                ),
            }
            for dart in sorted(web.vertex_of)
        ],
    }


def deserialize_exact_web(payload: Mapping[str, Any]) -> ExactRibbonState:
    state_schema = payload.get("schema")
    if state_schema not in {
        "problem3.exact_ribbon_state.v1",
        "problem3.exact_ribbon_state.v2",
        "problem3.exact_ribbon_state.v3",
        "problem3.exact_ribbon_state.v4",
    }:
        raise ValueError(f"Unsupported exact ribbon schema {payload.get('schema')!r}.")
    if (
        state_schema == "problem3.exact_ribbon_state.v4"
        and payload.get("digest_schema") != EXACT_STATE_KEY_SCHEMA
    ):
        raise ValueError(
            "Exact ribbon v4 payload has an unsupported canonical-key digest schema."
        )
    vertices = {int(item["id"]): item for item in payload.get("vertices", [])}
    darts = {int(item["id"]): item for item in payload.get("darts", [])}
    web = HalfEdgeWeb(
        vertex_of={dart: int(item["vertex"]) for dart, item in darts.items()},
        mate={dart: int(item["mate"]) for dart, item in darts.items()},
        next_ccw={dart: int(item["next_ccw"]) for dart, item in darts.items()},
        edge_kind={dart: EdgeKind(int(item["edge_kind"])) for dart, item in darts.items()},
        physical_edge_of={dart: int(item["physical_edge"]) for dart, item in darts.items()},
        bundle_of={
            dart: None if item.get("bundle") is None else int(item["bundle"])
            for dart, item in darts.items()
        },
        color={vertex: VertexColor(int(item["color"])) for vertex, item in vertices.items()},
        boundary_label={
            vertex: None if item.get("boundary_label") is None else int(item["boundary_label"])
            for vertex, item in vertices.items()
        },
        tag_after_ccw={
            vertex: None if item.get("tag_after_ccw") is None else int(item["tag_after_ccw"])
            for vertex, item in vertices.items()
        },
        source_edge_id={
            dart: None if item.get("source_edge") is None else int(item["source_edge"])
            for dart, item in darts.items()
        },
        source_local_strand={
            dart: None
            if item.get("source_local_strand") is None
            else int(item["source_local_strand"])
            for dart, item in darts.items()
        },
        source_xy={
            vertex: (float(item["source_xy"][0]), float(item["source_xy"][1]))
            for vertex, item in vertices.items()
            if item.get("source_xy") is not None
        },
        tensor_valence={
            vertex: int(item.get("tensor_valence", 1 if int(item["color"]) == 0 else 4))
            for vertex, item in vertices.items()
        },
        square_undo_stack=tuple(
            deserialize_exact_web(item)
            for item in payload.get("square_undo_stack", [])
        ),
        square_undo_multipliers=tuple(
            int(value) for value in payload.get("square_undo_multipliers", [])
        ),
    )
    if "bundle_frames" in payload:
        web.bundle_frame_root = {
            int(item["bundle"]): {
                int(vertex): int(root)
                for vertex, root in item.get("roots", {}).items()
            }
            for item in payload.get("bundle_frames", [])
        }
    else:
        # Legacy fallback: old checkpoints could only mark a root when the
        # root dart itself belonged to that bundle.
        for dart, item in darts.items():
            bundle = web.bundle_of[dart]
            if bundle is not None and item.get("bundle_frame_root"):
                web.bundle_frame_root.setdefault(bundle, {})[web.vertex_of[dart]] = dart
        refresh_bundle_frames(web)
    validate_exact_web(web)
    expected = payload.get("digest")
    # v1 omitted ordinary-dart bundle-frame roots, so its old digest cannot
    # certify the reconstructed semantic state.  v2/v3 digests used the
    # historical source-presence-only key; v4 preserves the complete source
    # ancestry equivalence partition used by exact splice relations.
    if state_schema != "problem3.exact_ribbon_state.v1" and not (
        isinstance(expected, str) and expected
    ):
        raise ValueError("Exact ribbon v2+ payload is missing its required digest.")
    if state_schema in {
        "problem3.exact_ribbon_state.v2",
        "problem3.exact_ribbon_state.v3",
    }:
        actual_digest = hashlib.sha256(
            repr(legacy_source_presence_web_key(web)).encode("utf-8")
        ).hexdigest()
    else:
        actual_digest = exact_state_digest(web)
    if state_schema != "problem3.exact_ribbon_state.v1" and actual_digest != expected:
        raise ValueError("Deserialized exact ribbon digest does not match its checkpoint.")
    return web


def serialize_route(route: ProvenanceRoute) -> dict[str, Any]:
    return {
        "coefficient": int(route.coefficient),
        "label": route.label,
        "moves": _jsonable(route.moves),
        "initial_route_coefficient": (
            None
            if route.initial_route_coefficient is None
            else int(route.initial_route_coefficient)
        ),
    }


def deserialize_route(payload: Mapping[str, Any]) -> ProvenanceRoute:
    initial_route_coefficient = payload.get("initial_route_coefficient")
    return ProvenanceRoute(
        coefficient=int(payload["coefficient"]),
        label=str(payload.get("label", "")),
        moves=tuple(dict(move) for move in payload.get("moves", [])),
        initial_route_coefficient=(
            None
            if initial_route_coefficient is None
            else int(initial_route_coefficient)
        ),
    )


def route_coefficient_authentication(
    route: ProvenanceRoute,
    *,
    expected_initial_route_coefficient: int | None = None,
) -> dict[str, Any]:
    """Audit one route's complete coefficient chain without inferring an anchor.

    Old checkpoints did not store ``initial_route_coefficient``.  They remain
    state-replayable, but the coefficient chain is not fully authenticated
    unless a caller supplies an independently trusted expected initial value.
    """

    stored_initial = route.initial_route_coefficient
    trusted_initial = (
        None
        if expected_initial_route_coefficient is None
        else int(expected_initial_route_coefficient)
    )
    errors: list[str] = []
    authentication_gaps: list[str] = []
    if (
        stored_initial is not None
        and trusted_initial is not None
        and int(stored_initial) != trusted_initial
    ):
        errors.append(
            "stored initial route coefficient does not match the trusted expected value"
        )
    effective_initial = (
        trusted_initial
        if trusted_initial is not None
        else None if stored_initial is None else int(stored_initial)
    )
    running_coefficient = effective_initial
    authenticated_move_count = 0
    required_fields = {
        "coefficient_multiplier",
        "input_route_coefficient",
        "output_route_coefficient",
    }
    for move_index, move in enumerate(route.moves):
        missing = sorted(required_fields - set(move))
        if missing:
            message = (
                f"move {move_index} lacks coefficient-authentication fields {missing}"
            )
            if stored_initial is None:
                # A pre-anchor legacy route remains state-replayable, but this
                # missing chain segment is explicitly not authenticated.
                authentication_gaps.append(message)
            else:
                # Current anchored routes always emit these fields.  Their
                # removal is tampering, not a legacy compatibility case.
                errors.append(message)
            running_coefficient = None
            continue
        input_coefficient = int(move["input_route_coefficient"])
        output_coefficient = int(move["output_route_coefficient"])
        multiplier = int(move["coefficient_multiplier"])
        if (
            running_coefficient is not None
            and input_coefficient != running_coefficient
        ):
            errors.append(
                f"move {move_index} input coefficient does not continue the route chain"
            )
        if output_coefficient != input_coefficient * multiplier:
            errors.append(
                f"move {move_index} output coefficient is not input times multiplier"
            )
        running_coefficient = output_coefficient
        authenticated_move_count += 1

    if route.moves:
        if (
            running_coefficient is not None
            and running_coefficient != int(route.coefficient)
        ):
            errors.append(
                "final route coefficient does not match the authenticated move chain"
            )
    elif (
        effective_initial is not None
        and effective_initial != int(route.coefficient)
    ):
        errors.append(
            "zero-move route coefficient does not match its initial coefficient"
        )

    legacy_unanchored = stored_initial is None
    anchor_available = effective_initial is not None
    fully_authenticated = (
        not errors
        and not authentication_gaps
        and anchor_available
        and authenticated_move_count == len(route.moves)
    )
    return {
        "stored_initial_route_coefficient": (
            None if stored_initial is None else int(stored_initial)
        ),
        "expected_initial_route_coefficient": trusted_initial,
        "effective_initial_route_coefficient": effective_initial,
        "anchor_source": (
            "trusted_expected"
            if trusted_initial is not None
            else "stored" if stored_initial is not None else "missing"
        ),
        "legacy_unanchored": legacy_unanchored,
        "move_count": len(route.moves),
        "authenticated_move_count": authenticated_move_count,
        "coefficient_chain_valid": not errors,
        "fully_authenticated": fully_authenticated,
        "errors": errors,
        "authentication_gaps": authentication_gaps,
    }


def serialize_pair_term(term: ExactPairTerm) -> dict[str, Any]:
    routes = validated_provenance_routes(term.coefficient, term.routes)
    return {
        "coefficient": int(term.coefficient),
        "w": serialize_exact_web(term.w),
        "x": serialize_exact_web(term.x),
        "routes": [serialize_route(route) for route in routes],
    }


def deserialize_pair_term(payload: Mapping[str, Any]) -> ExactPairTerm:
    return ExactPairTerm(
        coefficient=int(payload["coefficient"]),
        w=deserialize_exact_web(payload["w"]),
        x=deserialize_exact_web(payload["x"]),
        routes=[deserialize_route(route) for route in payload.get("routes", [])],
    )


def save_exact_checkpoint(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Atomically write a stable JSON checkpoint."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema": SCHEMA, **_jsonable(payload)}
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(body, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def load_exact_checkpoint(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("schema") not in {SCHEMA, *LEGACY_SCHEMAS}:
        raise ValueError(f"Unsupported exact checkpoint schema {payload.get('schema')!r}.")
    payload["historical_only"] = payload.get("schema") in LEGACY_SCHEMAS
    return payload


def _relation_candidates_for_move(
    web: ExactRibbonState, move: Mapping[str, Any]
) -> tuple[ExactRelationBranch, ...]:
    relation = str(move["relation"])
    local = move.get("local_data", {})
    if relation.startswith("wrench_"):
        return exact_wrench_relation(web, int(local["bundle"]))
    if relation == "double_trident":
        return exact_double_trident_relation(web, int(local["white"]), int(local["black"]))
    if relation.startswith("double_edge_to_") or relation.startswith("hourglass_plus_edge_"):
        matches = [
            candidate
            for candidate in detect_exact_double_edge_moves(web)
            if candidate.kind
            == ("double_edge" if relation.startswith("double_edge") else "hourglass_plus_edge")
            and candidate.white == int(local["white"])
            and candidate.black == int(local["black"])
        ]
        return tuple(apply_exact_double_edge_move(web, candidate) for candidate in matches)
    if relation.startswith("figure43_"):
        cycle = frozenset(int(vertex) for vertex in local["cycle"])
        matches = [
            candidate
            for candidate in detect_exact_figure43_moves(web)
            if frozenset(candidate.cycle) == cycle
        ]
        return tuple(
            branch
            for candidate in matches
            for branch in apply_exact_figure43_move(web, candidate)
        )
    if relation.startswith("figure2_square_"):
        cycle = frozenset(int(vertex) for vertex in local["cycle"])
        matches = [
            candidate
            for candidate in production_square_moves(web)
            if frozenset(candidate.cycle) == cycle
        ]
        return tuple(apply_exact_square_relation(web, candidate) for candidate in matches)
    if relation == "two_hourglass_contraction":
        raise UncertifiedRelationError(
            "Tagged Figure 9 is prohibited in production replay.  Historical "
            "routes may be inspected only through the explicitly audit-only API."
        )
    raise ValueError(f"Unsupported exact replay relation {relation!r}.")


def replay_exact_pair_route(
    initial_w: ExactRibbonState,
    initial_x: ExactRibbonState,
    route: ProvenanceRoute,
    *,
    expected_initial_route_coefficient: int | None = None,
    allow_legacy_unanchored: bool = False,
) -> tuple[ExactRibbonState, ExactRibbonState]:
    """Replay every certified route move and verify each exact output digest.

    Legacy routes can still be deserialized, but permissive replay of an
    unanchored or incomplete coefficient chain requires an explicit opt-in.
    Supplying a trusted expected initial coefficient can fully authenticate an
    otherwise unanchored route when every move carries the current chain fields.
    """

    w = copy.deepcopy(initial_w)
    x = copy.deepcopy(initial_x)
    coefficient_authentication = route_coefficient_authentication(
        route,
        expected_initial_route_coefficient=expected_initial_route_coefficient,
    )
    if not coefficient_authentication["coefficient_chain_valid"]:
        raise ValueError(
            "Replay route coefficient authentication failed: "
            + "; ".join(coefficient_authentication["errors"])
        )
    if (
        not allow_legacy_unanchored
        and (
            (
                coefficient_authentication["legacy_unanchored"]
                and expected_initial_route_coefficient is None
            )
            or coefficient_authentication["authentication_gaps"]
        )
    ):
        raise ValueError(
            "Replay route lacks current coefficient authentication; pass "
            "allow_legacy_unanchored=True only for a trusted legacy checkpoint."
        )
    for move in route.moves:
        side = str(move["side"]).upper()
        current = w if side == "W" else x if side == "X" else None
        if current is None:
            raise ValueError(f"Invalid replay side {side!r}.")
        expected_relation = str(move["relation"])
        expected_digest = str(move["output_digest"])
        expected_multiplier = int(move["coefficient_multiplier"])
        expected_local_data = _jsonable(move.get("local_data", {}))
        candidates = [
            branch
            for branch in _relation_candidates_for_move(current, move)
            if branch.relation == expected_relation
            and int(branch.coefficient_multiplier) == expected_multiplier
            and _jsonable(branch.local_data) == expected_local_data
            and exact_state_digest(branch.web) == expected_digest
        ]
        expected_certificate_digest = move.get("certificate_digest")
        if expected_certificate_digest is not None:
            candidates = [
                branch
                for branch in candidates
                if require_production_relation_certificate(branch).semantic_digest
                == str(expected_certificate_digest)
            ]
        if len(candidates) != 1:
            raise ValueError(
                f"Replay found {len(candidates)} exact matches for {expected_relation} "
                f"with digest {expected_digest}."
            )
        if side == "W":
            w = candidates[0].web
        else:
            x = candidates[0].web
    return w, x


def _decreasing_square_branch(web: ExactRibbonState) -> ExactRelationBranch | None:
    candidates = [move for move in production_square_moves(web) if move.hourglass_count > 2]
    if not candidates:
        return None
    move = min(candidates, key=lambda item: (item.hourglass_count * -1, item.cycle))
    return apply_exact_square_relation(web, move)


def _square_history_unwind_branch(
    web: ExactRibbonState,
) -> ExactRelationBranch | None:
    """Use the exact saved parent to undo one generated square presentation."""

    current_depth = len(web.square_undo_stack)
    if current_depth == 0:
        return None
    matches: list[tuple[tuple[int, ...], Any]] = []
    for move in production_square_moves(web):
        try:
            branch = apply_exact_square_relation(
                web, move, verify_round_trip=False
            )
        except ValueError:
            continue
        if (
            len(branch.web.square_undo_stack) == current_depth - 1
            and branch.local_data.get("square_history_action") == "pop"
        ):
            matches.append((tuple(move.cycle), move))
    if not matches:
        return None
    _cycle, move = min(matches)
    return apply_exact_square_relation(web, move)


def double_edge_overlaps_hourglass(
    web: ExactRibbonState, move: ExactDoubleEdgeMove
) -> bool:
    """Whether a two-edge lens shares either endpoint with an hourglass.

    This predicate remains public for confluence audits.  Production postpones
    this overlap because GPPSS Figure 9 specifies the untagged graph
    contraction but not the tagged merged root needed by the FLL scalar.  A
    Wrench-first route is used whenever it is available; an explicitly forced
    double-edge-first route remains a diagnostic until that tagged lift is
    proved.
    """

    if move.kind != "double_edge":
        return False
    endpoints = {int(move.white), int(move.black)}
    return any(
        bundle is not None and web.vertex_of[dart] in endpoints
        for dart, bundle in web.bundle_of.items()
    )


# Compatibility for the focused development tests and notebooks created
# before the critical-pair predicate became part of the public audit API.
_double_edge_overlaps_hourglass = double_edge_overlaps_hourglass


def choose_exact_x_relation(
    web: ExactRibbonState,
    *,
    enable_figure43_row4: bool = True,
) -> tuple[ExactRelationBranch, ...]:
    """Use exact local relations without any neighbor-list fallback.

    Exact relations with source-supported tagged coefficients take priority.
    Tagged Figure 9 is never a production candidate.  Double-edge lenses that
    overlap an existing hourglass are postponed in favor of a legal Wrench so
    production does not manufacture an unsupported tagged Figure-9 state.
    """

    if web.square_undo_stack:
        unwind = _square_history_unwind_branch(web)
        if unwind is not None:
            return (unwind,)
        # Do not apply a skein relation after losing the exact inverse path.
        return ()

    double = detect_exact_double_edge_moves(web)
    if double:
        safe_double = tuple(
            move
            for move in double
            if not double_edge_overlaps_hourglass(web, move)
        )
        # The coefficient-3 collapse is the stronger reduction.
        if safe_double:
            move = min(
                safe_double,
                key=lambda item: (
                    item.kind != "hourglass_plus_edge",
                    item.white,
                    item.black,
                ),
            )
            return (apply_exact_double_edge_move(web, move),)
        # Every remaining lens overlaps an hourglass.  Resolve that existing
        # hourglass first using Figure 42, whose tagged coefficients are
        # supported and independently tensor-certified.
        for move in sorted(double, key=lambda item: (item.white, item.black)):
            endpoints = {int(move.white), int(move.black)}
            incident_bundles = sorted(
                {
                    int(bundle)
                    for dart, bundle in web.bundle_of.items()
                    if bundle is not None and web.vertex_of[dart] in endpoints
                }
            )
            for bundle in incident_bundles:
                try:
                    return exact_wrench_relation(web, bundle)
                except ValueError:
                    continue
    figure43 = detect_exact_figure43_moves(web)
    # The optional gate is retained only for explicit reduction-order audits.
    # Production enables row 4: both orientations and the row-2683 overlap
    # with Wrench, double edge, and Double Trident have independent tensor and
    # end-to-end confluence regressions.
    production_figure43 = tuple(
        move
        for move in figure43
        if enable_figure43_row4 or move.rule != "single_right_hourglass"
    )
    if production_figure43:
        return apply_exact_figure43_move(web, production_figure43[0])
    bundles = bundle_ids(web)
    for bundle in bundles:
        try:
            return exact_wrench_relation(web, bundle)
        except ValueError:
            # A lower-valence tagged Figure 43 tensor is deliberately not a
            # four-port Wrench input.  Leave it for its dedicated relation.
            continue
    tridents = detect_exact_double_tridents(web)
    if tridents:
        white, black = tridents[0]
        return exact_double_trident_relation(web, white, black)
    # A square move is the last structural fallback.  Applying it before an
    # available skein relation manufactures dormant frame history and can
    # create a reduction/unwind loop.  Existing presentation history is
    # unwound at the top of this chooser; stack-free inputs reach this fallback
    # only when no exact skein relation is available.
    square = _decreasing_square_branch(web)
    if square is not None:
        return (square,)
    return ()


def _term_sort_key(term: ExactPairTerm) -> tuple[Any, ...]:
    return (canonical_web_key(term.x), canonical_web_key(term.w), term.coefficient)


def run_exact_pairing_scheduler(
    w: ExactRibbonState,
    x: ExactRibbonState,
    *,
    limits: ExactSchedulerLimits | None = None,
    source_web_sign: int = 1,
    use_pair_pattern_zero_certificates: bool = False,
    relation_chooser: Callable[
        [ExactRibbonState], tuple[ExactRelationBranch, ...]
    ]
    | None = None,
) -> ExactSchedulerResult:
    """Reduce X exactly, keep W passive, and evaluate terminal colorings.

    ``relation_chooser`` exists for controlled confluence audits.  Production
    callers omit it and use :func:`choose_exact_x_relation`; an audit can
    supply another deterministic legal order without monkeypatching module
    state.  Lemma 4.8/4.9 certificates are opt-in while their use on generated
    skein states is being checked against square-presentation controls.
    """

    validate_exact_web(w)
    validate_exact_web(x)
    if source_web_sign not in {-1, 1}:
        raise ValueError("source_web_sign must be +1 or -1.")
    limits = limits or ExactSchedulerLimits()
    choose_relation = relation_chooser or choose_exact_x_relation
    initial_w = serialize_exact_web(w)
    initial_x = serialize_exact_web(x)
    active = [
        ExactPairTerm(
            1,
            copy.deepcopy(w),
            copy.deepcopy(x),
            [
                ProvenanceRoute(
                    1,
                    label="root",
                    initial_route_coefficient=1,
                )
            ],
        )
    ]
    terminal_terms: list[dict[str, Any]] = []
    zero_terms: list[dict[str, Any]] = []
    unresolved: list[ExactPairTerm] = []
    unresolved_witnesses: list[dict[str, Any]] = []
    relation_counts: Counter[str] = Counter()
    value = 0
    expansions = 0

    def record_terminal(term: ExactPairTerm, evaluation: Mapping[str, Any]) -> None:
        nonlocal value
        contribution = (
            int(source_web_sign)
            * int(term.coefficient)
            * int(evaluation["fll_pairing_value"])
        )
        value += contribution
        terminal_terms.append(
            {
                **_jsonable(evaluation),
                "coefficient": term.coefficient,
                "source_web_sign": source_web_sign,
                "contribution": contribution,
                "routes": [serialize_route(route) for route in term.routes],
                "w_digest": exact_state_digest(term.w),
                "x_digest": exact_state_digest(term.x),
            }
        )

    while active:
        active = consolidate_exact_pair_terms(active)
        if len(active) > limits.max_active_terms:
            return ExactSchedulerResult(
                "limit", None, expansions, dict(relation_counts), terminal_terms,
                zero_terms, unresolved, active,
                f"active term count exceeded {limits.max_active_terms}",
                initial_w=initial_w,
                initial_x=initial_x,
                source_web_sign=source_web_sign,
            )
        active.sort(key=_term_sort_key)
        term = active.pop(0)
        fork_zero = exact_pair_fork_zero_certificate(term.w, term.x)
        if fork_zero is not None:
            zero_terms.append(
                {
                    **fork_zero,
                    "coefficient": term.coefficient,
                    "routes": [serialize_route(route) for route in term.routes],
                    "w_digest": exact_state_digest(term.w),
                    "x_digest": exact_state_digest(term.x),
                }
            )
            continue

        pattern_zero = (
            exact_pair_pattern_zero_certificate(term.w, term.x)
            if use_pair_pattern_zero_certificates
            else None
        )
        if pattern_zero is not None:
            zero_terms.append(
                {
                    **pattern_zero,
                    "coefficient": term.coefficient,
                    "routes": [serialize_route(route) for route in term.routes],
                    "w_digest": exact_state_digest(term.w),
                    "x_digest": exact_state_digest(term.x),
                }
            )
            continue

        # This is an X-active/W-passive evaluator.  Prefer an X product and,
        # while X still has a legal relation, do not stop merely because
        # passive W happens to be a product.  That early shortcut caused the
        # two rep-253 horizontal Figure-43 disagreements.  A W-product
        # coloring remains a last-resort terminal only after X has no exact
        # relation, preserving completion for otherwise irreducible X states.
        evaluation = evaluate_exact_pair_by_coloring(
            term.w, term.x, source_side="X"
        )
        if evaluation.get("status") == "computed":
            record_terminal(term, evaluation)
            continue

        try:
            branches = choose_relation(term.x)
        except UncertifiedRelationError as exc:
            unresolved.append(term)
            unresolved_witnesses.append(
                {
                    "reason_code": "uncertified_relation",
                    "state_digest": exact_state_digest(term.x),
                    "error": str(exc),
                }
            )
            continue
        if not branches:
            fallback = evaluate_exact_pair_by_coloring(
                term.w, term.x, source_side="W"
            )
            if fallback.get("status") == "computed":
                record_terminal(term, fallback)
                continue
            unresolved.append(term)
            figure9 = unsupported_tagged_figure9_witnesses(term.x)
            if figure9:
                unresolved_witnesses.extend(dict(item) for item in figure9)
            else:
                unresolved_witnesses.append(
                    {
                        "reason_code": "no_certified_relation_or_terminal",
                        "state_digest": exact_state_digest(term.x),
                    }
                )
            continue
        expansions += 1
        if expansions > limits.max_expansions:
            active.insert(0, term)
            return ExactSchedulerResult(
                "limit", None, expansions - 1, dict(relation_counts), terminal_terms,
                zero_terms, unresolved, active,
                f"expansion count exceeded {limits.max_expansions}",
                initial_w=initial_w,
                initial_x=initial_x,
                source_web_sign=source_web_sign,
            )
        relation_counts.update(branch.relation for branch in branches)
        active.extend(expand_exact_pair_term(term, side="X", branches=branches))

    if unresolved:
        reason_codes = {
            str(item.get("reason_code", "")) for item in unresolved_witnesses
        }
        reason_code = (
            "unsupported_tagged_figure9"
            if reason_codes == {"unsupported_tagged_figure9"}
            else "uncertified_relation"
            if "uncertified_relation" in reason_codes
            else "no_certified_relation_or_terminal"
        )
        return ExactSchedulerResult(
            "unresolved", None, expansions, dict(relation_counts), terminal_terms,
            zero_terms, unresolved, [],
            "one or more exact terms reached no implemented relation or terminal coloring",
            initial_w=initial_w,
            initial_x=initial_x,
            source_web_sign=source_web_sign,
            reason_code=reason_code,
            unresolved_witnesses=unresolved_witnesses,
        )
    return ExactSchedulerResult(
        "computed", value, expansions, dict(relation_counts), terminal_terms,
        zero_terms, [], [], "",
        initial_w=initial_w,
        initial_x=initial_x,
        source_web_sign=source_web_sign,
    )


def scheduler_result_checkpoint_payload(result: ExactSchedulerResult) -> dict[str, Any]:
    if result.initial_w is None or result.initial_x is None:
        raise ValueError("Exact scheduler results must retain both replay root states.")
    return {
        "audit_schema": "problem3.exact_pairing_audit.v2",
        "terminal_convention_id": FLL_TERMINAL_CONVENTION_ID,
        "initial_w": result.initial_w,
        "initial_x": result.initial_x,
        "source_web_sign": result.source_web_sign,
        "status": result.status,
        "value": result.value,
        "expansions": result.expansions,
        "relation_counts": result.relation_counts,
        "terminal_terms": result.terminal_terms,
        "zero_terms": result.zero_terms,
        "unresolved_terms": [serialize_pair_term(term) for term in result.unresolved_terms],
        "active_terms": [serialize_pair_term(term) for term in result.active_terms],
        "reason": result.reason,
        "reason_code": result.reason_code,
        "unresolved_witnesses": result.unresolved_witnesses,
    }
