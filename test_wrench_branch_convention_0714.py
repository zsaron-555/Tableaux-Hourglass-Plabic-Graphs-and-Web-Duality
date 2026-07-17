#!/usr/bin/env python3
"""Regression test for the geometric crossing/parallel wrench convention."""

from Wrench_or_Skein_0714 import (
    move_multiplier,
    orient_hourglass_ports,
    smooth_one_hourglass,
)


def edge_set(adj):
    return {
        tuple(sorted((node, neighbor)))
        for node, neighbors in adj.items()
        for neighbor in (neighbors.values() if isinstance(neighbors, dict) else neighbors)
        if neighbor is not None
    }


def test_crossing_and_parallel_match_geometry_and_signs():
    # White is the left endpoint and black is the right endpoint.  The four
    # ordinary ports occupy the corners of a rectangle around the hourglass.
    nodes = {
        1: {"x": -1.0, "y": 0.0},
        2: {"x": 1.0, "y": 0.0},
        3: {"x": -2.0, "y": 1.0},   # left top
        4: {"x": -2.0, "y": -1.0},  # left bottom
        5: {"x": 2.0, "y": 1.0},    # right top
        6: {"x": 2.0, "y": -1.0},   # right bottom
    }
    rotation = {
        "1": [
            {"neighbor": 3, "kind": "ordinary", "ccw_slot": 0},
            {"neighbor": 4, "kind": "ordinary", "ccw_slot": 1},
        ],
        "2": [
            {"neighbor": 5, "kind": "ordinary", "ccw_slot": 0},
            {"neighbor": 6, "kind": "ordinary", "ccw_slot": 1},
        ],
    }
    for left_endpoint in ("white", "black"):
        hg = orient_hourglass_ports(1, 2, nodes, rotation, left_endpoint)
        adj = {
            1: {"top": hg["left_top"], "bot": hg["left_bot"]}
            if hg["left"] == 1
            else {"top": hg["right_top"], "bot": hg["right_bot"]},
            2: {"top": hg["left_top"], "bot": hg["left_bot"]}
            if hg["left"] == 2
            else {"top": hg["right_top"], "bot": hg["right_bot"]},
            3: [1],
            4: [1],
            5: [2],
            6: [2],
        }
        crossing = edge_set(smooth_one_hourglass(adj, hg, "crossing"))
        parallel = edge_set(smooth_one_hourglass(adj, hg, "parallel"))

        assert crossing == {(3, 6), (4, 5)}
        assert parallel == {(3, 5), (4, 6)}
    assert move_multiplier("crossing") == 1
    assert move_multiplier("parallel") == -1


if __name__ == "__main__":
    test_crossing_and_parallel_match_geometry_and_signs()
    print("crossing/parallel convention: OK")
