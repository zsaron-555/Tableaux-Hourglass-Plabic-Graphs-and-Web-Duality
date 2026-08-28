"""Exact original-pair adapters for the paper's planar vanishing prefilter.

Lemma 3.11 says that the original planar webs contain one of the displayed
boundary configurations.  The boundary of such a displayed local window is
not an ordinary edge requirement: continuation outside the window is ambient
and may begin with either an ordinary edge or an hourglass.  This module keeps
that original-input-only semantics separate from the stricter generated-state
certificate used by the exact reduction scheduler.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

from exact_zero_certificates_20260819 import (
    _is_standard_sl4_state,
    _match_exact_pattern_side,
    exact_lemma48_zero_certificate,
)
from halfedge_web_20260812 import ExactRibbonState, validate_exact_web
from web_relation_rules_optimized_20260726 import (
    _paired_pattern_required_graph_connected,
    _pattern_boundary_windows,
    load_sl4_lemma49_zero_patterns,
)


ROOT = Path(__file__).resolve().parent
INITIAL_PATTERN_DIR = ROOT / "sl4_lemma49_initial_zero_patterns_20260827"
INITIAL_PORT_POLICY = "unrestricted_noninduced_continuation"
GENERATED_BRANCH_PORT_POLICY = "required_ordinary_continuation"


def _remove_window_ports(pattern_web: dict[str, Any]) -> dict[str, Any]:
    """Return the required local subgraph, excluding ambient cut ports."""

    result = copy.deepcopy(pattern_web)
    ports = {str(node) for node in result.get("ports", [])}
    result["nodes"] = [
        node for node in result.get("nodes", []) if str(node["id"]) not in ports
    ]
    result["edges"] = [
        edge
        for edge in result.get("edges", [])
        if str(edge["u"]) not in ports and str(edge["v"]) not in ports
    ]
    result["ports"] = []
    # The strict exact matcher derives the actual multiplicity from the edge
    # kind/resource.  Generalized catalogue entries encode [1,2] only to say
    # that ordinary_or_hourglass is allowed; normalize that schema union for
    # the exact matcher without changing the allowed kind.
    for edge in result["edges"]:
        if isinstance(edge.get("multiplicity"), list):
            edge["multiplicity"] = 1
    return result


@lru_cache(maxsize=1)
def initial_lemma49_rule_catalog() -> tuple[dict[str, Any], ...]:
    loaded = load_sl4_lemma49_zero_patterns(INITIAL_PATTERN_DIR)["patterns"]
    patterns: list[dict[str, Any]] = []
    for item in loaded:
        pattern = copy.deepcopy(item)
        pattern["W"] = _remove_window_ports(pattern["W"])
        pattern["X"] = _remove_window_ports(pattern["X"])
        patterns.append(pattern)
    return tuple(patterns)


def exact_initial_lemma49_zero_certificates(
    w: ExactRibbonState,
    x: ExactRibbonState,
    *,
    max_matches: int = 1,
) -> list[dict[str, Any]]:
    """Return exact Lemma 3.11 witnesses for one original planar pair."""

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
    for pattern in initial_lemma49_rule_catalog():
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
                        w_match = {
                            **w_match,
                            "ambient_port_policy": INITIAL_PORT_POLICY,
                        }
                        x_match = {
                            **x_match,
                            "ambient_port_policy": INITIAL_PORT_POLICY,
                        }
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
                                "application_scope": "original_planar_pair_only",
                                "ambient_port_policy": INITIAL_PORT_POLICY,
                                "W": w_match,
                                "X": x_match,
                            }
                        )
                        if len(found) >= max_matches:
                            return found
    return found


def exact_initial_lemma49_zero_certificate(
    w: ExactRibbonState, x: ExactRibbonState
) -> dict[str, Any] | None:
    matches = exact_initial_lemma49_zero_certificates(w, x, max_matches=1)
    return None if not matches else matches[0]


def exact_initial_pair_pattern_zero_certificate(
    w: ExactRibbonState, x: ExactRibbonState
) -> dict[str, Any] | None:
    """Apply supported original-pair planar vanishing lemmas before reduction."""

    return exact_initial_lemma49_zero_certificate(
        w, x
    ) or exact_lemma48_zero_certificate(w, x)
