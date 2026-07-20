#!/usr/bin/env python3
"""Validate the executable SL4 Lemma 4.9 zero-pattern catalogue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_PATTERN_DIR = Path(__file__).with_name("sl4_lemma49_zero_patterns")


def fail(path: Path, message: str) -> None:
    raise ValueError(f"{path.name}: {message}")


def validate_web(path: Path, side: str, web: dict) -> None:
    nodes = web["nodes"]
    edges = web["edges"]
    node_by_id = {node["id"]: node for node in nodes}
    edge_by_id = {edge["id"]: edge for edge in edges}

    if len(node_by_id) != len(nodes):
        fail(path, f"{side} has duplicate node ids")
    if len(edge_by_id) != len(edges):
        fail(path, f"{side} has duplicate edge ids")

    boundary = web["boundary_order"]
    ports = web["ports"]
    if len(boundary) != len(set(boundary)):
        fail(path, f"{side} boundary_order contains duplicates")
    if len(ports) != len(set(ports)):
        fail(path, f"{side} ports contains duplicates")

    for node_id in boundary:
        node = node_by_id.get(node_id)
        if node is None or node["role"] != "disk_boundary" or node["color"] != "black":
            fail(path, f"{side} boundary node {node_id!r} is not a black disk_boundary")
    for node_id in ports:
        node = node_by_id.get(node_id)
        if node is None or node["role"] != "window_port" or node["color"] != "open":
            fail(path, f"{side} port {node_id!r} is not an open window_port")

    for edge in edges:
        if edge["u"] not in node_by_id or edge["v"] not in node_by_id:
            fail(path, f"{side} edge {edge['id']} has an unknown endpoint")
        expected_mult = 2 if edge["kind"] == "hourglass" else 1
        if edge["multiplicity"] != expected_mult:
            fail(path, f"{side} edge {edge['id']} has incorrect multiplicity")

        u = node_by_id[edge["u"]]
        v = node_by_id[edge["v"]]
        if u["color"] != "open" and v["color"] != "open" and u["color"] == v["color"]:
            fail(path, f"{side} edge {edge['id']} violates bipartiteness")
        if edge["kind"] == "hourglass" and {u["color"], v["color"]} != {"black", "white"}:
            fail(path, f"{side} hourglass {edge['id']} does not join black to white")

    for crossing in web.get("crossings", []):
        crossing_edges = crossing.get("edges", [])
        if len(crossing_edges) != 2 or any(edge_id not in edge_by_id for edge_id in crossing_edges):
            fail(path, f"{side} has an invalid crossing edge pair")
        if crossing.get("vertex") is not None:
            fail(path, f"{side} crossing must not be represented as a vertex")


def validate_catalog(pattern_dir: Path) -> list[str]:
    manifest_path = pattern_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    seen_ids: set[str] = set()
    validated: list[str] = []

    for entry in manifest["patterns"]:
        path = pattern_dir / entry["file"]
        if not path.is_file():
            fail(manifest_path, f"missing pattern file {entry['file']}")
        pattern = json.loads(path.read_text())
        if pattern["id"] in seen_ids:
            fail(path, f"duplicate pattern id {pattern['id']}")
        seen_ids.add(pattern["id"])
        manifest_case = entry["id"].rsplit("_", 1)[-1]
        if pattern["source"]["case"] != manifest_case:
            fail(path, "case disagrees with manifest")
        conclusion = pattern["conclusion"]
        if conclusion.get("action") != "discharge_pair" or conclusion.get("pairing_value") != 0:
            fail(path, "conclusion is not a zero-pairing discharge")
        validate_web(path, "W", pattern["W"])
        validate_web(path, "X", pattern["X"])
        if len(pattern["W"]["boundary_order"]) != len(pattern["X"]["boundary_order"]):
            fail(path, "W and X use different boundary-window sizes")
        validated.append(pattern["id"])

    return validated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pattern_dir", nargs="?", type=Path, default=DEFAULT_PATTERN_DIR)
    args = parser.parse_args()
    validated = validate_catalog(args.pattern_dir)
    print(f"validated {len(validated)} patterns: {', '.join(validated)}")


if __name__ == "__main__":
    main()
