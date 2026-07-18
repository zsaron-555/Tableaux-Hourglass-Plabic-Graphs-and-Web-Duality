#!/usr/bin/env python3
"""Regression tests for tagged SL4 vertex signs in pairing colorings."""

from pathlib import Path

import Wrench_or_Skein_0714 as wrench


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "4x4_All_graph_data"


def test_hand_computed_pair_cancels_after_vertex_signs() -> None:
    w_path = DATA / "02958_1112323241342344.json"
    x_path = DATA / "21143_1231122413324434.json"

    x_adj, x_bounds, x_hgs = wrench.parse_web(x_path)
    w_adj, w_bounds, w_hgs = wrench.parse_web(w_path)
    x_colors, x_xy = wrench.parse_web_metadata(x_path)
    w_colors, w_xy = wrench.parse_web_metadata(w_path)
    x_hgs = wrench.sort_hourglasses_by_boundary_distance(x_adj, x_bounds, x_hgs)
    w_hgs = wrench.sort_hourglasses_by_boundary_distance(w_adj, w_bounds, w_hgs)

    proof = wrench.prove_pair_value_complete_pipeline(
        x_adj,
        x_bounds,
        x_hgs,
        w_adj,
        w_bounds,
        w_hgs,
        allow_w_wrench=False,
        guided_beam_width=120,
        x_beam_width=500,
        x_node_colors=x_colors,
        x_node_xy=x_xy,
        w_node_colors=w_colors,
        w_node_xy=w_xy,
    )

    evaluations = proof["coloring_evaluations"]
    assert proof["final_pairing_value"] == 0
    assert len(evaluations) == 2
    assert sorted(item["term_value"] for item in evaluations) == [-1, 1]
    # The hand computation's final cancellation uses one shared-leaf untwist
    # in one branch; this is the sign correction documented in the notes.
    assert sum(
        int(move.get("untwist_count", 0))
        for item in evaluations
        for move in item.get("history", [])
    ) == 1


def test_hourglass_endpoints_keep_all_four_tagged_slots() -> None:
    path = DATA / "00301_1111232234434234.json"
    adj, _bounds, hourglasses = wrench.parse_web(path)
    assert hourglasses
    for hg in hourglasses:
        for endpoint in (int(hg["white"]), int(hg["black"])):
            ports = adj[endpoint]
            assert isinstance(ports, wrench.HourglassPorts)
            assert len(ports.slot_pattern) == 4
            assert sorted(ports.slot_pattern) == ["bot", "strand:0", "strand:1", "top"]


def test_antisymmetrizer_ports_ignore_display_coordinates() -> None:
    adj = {
        1: [2, 3, 4, 5],
        2: [6, 7, 8, 1],
        3: [1],
        4: [1],
        5: [1],
        6: [2],
        7: [2],
        8: [2],
    }
    colors = {1: "white", 2: "black", 3: "black", 4: "black", 5: "black", 6: "white", 7: "white", 8: "white"}
    xy_a = {node: (float(node), float(node % 3)) for node in adj}
    xy_b = {node: (-float(node % 4), float(20 - node)) for node in adj}
    match_a = wrench.detect_antisymmetrizer_moves(adj, colors, xy_a)[0]
    match_b = wrench.detect_antisymmetrizer_moves(adj, colors, xy_b)[0]
    assert match_a["input_ports"] == match_b["input_ports"] == [3, 4, 5]
    assert match_a["output_ports"] == match_b["output_ports"] == [6, 7, 8]
    assert all(term["tag_transport_multiplier"] == -1 for term in match_a["rhs_terms"])


def test_figure43_detection_ignores_display_coordinates() -> None:
    adj = {
        1: {"top": 2, "bot": 5},
        2: {"top": 1, "bot": 6},
        3: {"top": 4, "bot": 7},
        4: {"top": 3, "bot": 8},
        5: [1],
        6: [2],
        7: [3],
        8: [4],
    }
    hourglasses = [{"white": 2, "black": 3}, {"white": 4, "black": 1}]
    colors = {1: "black", 2: "white", 3: "black", 4: "white", 5: "white", 6: "black", 7: "white", 8: "black"}
    xy_a = {node: (float(node), float(node % 3)) for node in adj}
    xy_b = {node: (-float(node % 4), float(20 - node)) for node in adj}
    match_a = wrench.detect_figure43_moves(adj, hourglasses, colors, xy_a)[0]
    match_b = wrench.detect_figure43_moves(adj, hourglasses, colors, xy_b)[0]
    assert match_a["vertices_top_right_bottom_left"] == match_b["vertices_top_right_bottom_left"]
    assert match_a["rhs_terms"] == match_b["rhs_terms"] == [
        {
            "smoothing": "horizontal",
            "coefficient_multiplier": 1,
            "tag_transport_multiplier": 1,
        },
        {
            "smoothing": "vertical",
            "coefficient_multiplier": -2,
            "tag_transport_multiplier": -1,
        },
    ]


def test_fll_plucker_pairing_converts_to_canonical_orientation_once() -> None:
    """The count is unsigned after converting to canonical Plucker orientation."""
    path = DATA / "00301_1111232234434234.json"
    adj, bounds, hourglasses = wrench.parse_web(path)
    colors, xy = wrench.parse_web_metadata(path)
    hourglasses = wrench.sort_hourglasses_by_boundary_distance(adj, bounds, hourglasses)

    # Produce terminal Plucker-product terms and verify the conversion sign is
    # applied once to the otherwise unsigned consistent-labeling count.
    proof = wrench.prove_pair_value_by_x_component_coloring(
        adj,
        bounds,
        hourglasses,
        adj,
        bounds,
        hourglasses,
        allow_w_wrench=False,
        guided_beam_width=40,
        x_beam_width=80,
        x_node_colors=colors,
        x_node_xy=xy,
        w_node_colors=colors,
        w_node_xy=xy,
    )
    for evaluation in proof.get("coloring_evaluations", []):
        if evaluation.get("status") == "computed":
            assert evaluation["source_orientation_sign"] in {-1, 1}
            assert evaluation["signed_coloring_count"] == (
                evaluation["coloring_count"] * evaluation["source_orientation_sign"]
            )


def test_relation_history_controls_terminal_tag_orientation() -> None:
    history = [
        {
            "phase": "antisymmetrizer",
            "side": "X",
            "tag_transport_multiplier": -1,
        },
        {
            "phase": "figure43",
            "side": "X",
            "tag_transport_multiplier": -1,
        },
        {
            "phase": "figure43",
            "side": "W",
            "tag_transport_multiplier": -1,
        },
    ]
    assert wrench.relation_history_orientation_sign(history, "X") == 1
    assert wrench.relation_history_orientation_sign(history, "W") == -1


if __name__ == "__main__":
    test_hourglass_endpoints_keep_all_four_tagged_slots()
    test_antisymmetrizer_ports_ignore_display_coordinates()
    test_figure43_detection_ignores_display_coordinates()
    test_hand_computed_pair_cancels_after_vertex_signs()
    test_fll_plucker_pairing_converts_to_canonical_orientation_once()
    test_relation_history_controls_terminal_tag_orientation()
    print("tagged SL4 pairing signs: OK")
