#!/usr/bin/env python3
"""Build and serialize replayed exact-checker trees for the Python inspector.

The viewer never recomputes a skein coefficient. This module runs the
authoritative Python checker, replays every provenance route, and emits the
exact tagged states plus certificate data needed by the visual inspector.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from exact_pairing_kernel_20260819 import (  # noqa: E402
    ExactRibbonState,
    exact_state_digest,
    require_production_relation_certificate,
)
from exact_pairing_scheduler_20260819 import (  # noqa: E402
    _jsonable,
    _relation_candidates_for_move,
    deserialize_route,
    run_exact_pairing_scheduler,
    serialize_exact_web,
    word_inversion_sign,
)
from halfedge_web_20260812 import VertexColor, load_halfedge_web  # noqa: E402


OUTPUT_DIRECTORY = PROJECT_ROOT / "output" / "exact-tree-demos"
MANIFEST_OUTPUT = OUTPUT_DIRECTORY / "manifest.json"


@dataclass(frozen=True)
class DemoSpec:
    slug: str
    title: str
    description: str
    w_filename: str
    x_filename: str

    @property
    def w_word(self) -> str:
        return self.w_filename.split("_", 1)[1].removesuffix(".json")

    @property
    def x_word(self) -> str:
        return self.x_filename.split("_", 1)[1].removesuffix(".json")

    @property
    def w_path(self) -> Path:
        return PROJECT_ROOT / "4x4_All_graph_data" / self.w_filename

    @property
    def x_path(self) -> Path:
        return PROJECT_ROOT / "4x4_All_graph_data" / self.x_filename


DEMO_SPECS = (
    DemoSpec(
        slug="simple-wrench",
        title="Two-step wrench demo",
        description=(
            "Two certified wrench expansions, one terminal branch, and two "
            "common-fork zero certificates."
        ),
        w_filename="23563_1234111222333444.json",
        x_filename="00210_1111223344234234.json",
    ),
    DemoSpec(
        slug="double-trident",
        title="Double-trident sign demo",
        description=(
            "One certified double-trident antisymmetrizer expansion with six "
            "signed branches and final pairing value -1."
        ),
        w_filename="21634_1231142132233444.json",
        x_filename="02391_1112312423434234.json",
    ),
    DemoSpec(
        slug="rolling-wrench",
        title="Six-level rolling-window demo",
        description=(
            "A deeper exact wrench tree used to demonstrate that manual mode "
            "keeps only the latest three picture levels visible."
        ),
        w_filename="23563_1234111222333444.json",
        x_filename="00001_1111222233334444.json",
    ),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vertex_cycle(web: ExactRibbonState, vertex: int) -> list[int]:
    darts = sorted(dart for dart, owner in web.vertex_of.items() if owner == vertex)
    if not darts:
        return []
    cycle = [darts[0]]
    current = web.next_ccw[darts[0]]
    while current != darts[0]:
        cycle.append(current)
        current = web.next_ccw[current]
        if len(cycle) > len(darts):
            raise ValueError(f"Broken CCW dart cycle at vertex {vertex}.")
    return cycle


def affected_vertices(move: Mapping[str, Any]) -> list[int]:
    local = move.get("local_data", {})
    relation = str(move.get("relation", ""))
    result: set[int] = set()
    if relation.startswith("wrench_"):
        result.update(int(vertex) for vertex in local.get("frame_roots", {}))
    elif relation == "double_trident":
        result.update(int(local[key]) for key in ("white", "black") if key in local)
    elif relation.startswith("figure2_square_") or relation.startswith("figure43"):
        result.update(int(vertex) for vertex in local.get("cycle", []))
    elif relation == "two_hourglass_contraction" and "center" in local:
        result.add(int(local["center"]))
    return sorted(result)


def matching_branch(current: ExactRibbonState, move: Mapping[str, Any]):
    candidates = [
        branch
        for branch in _relation_candidates_for_move(current, move)
        if branch.relation == str(move["relation"])
        and int(branch.coefficient_multiplier) == int(move["coefficient_multiplier"])
        and _jsonable(branch.local_data) == _jsonable(move.get("local_data", {}))
        and exact_state_digest(branch.web) == str(move["output_digest"])
    ]
    expected_certificate = move.get("certificate_digest")
    if expected_certificate is not None:
        candidates = [
            branch
            for branch in candidates
            if require_production_relation_certificate(branch).semantic_digest
            == str(expected_certificate)
        ]
    if len(candidates) != 1:
        raise ValueError(
            f"Expected one replay branch for {move['relation']}, found {len(candidates)}."
        )
    return candidates[0]


def color_name(value: VertexColor) -> str:
    return {
        VertexColor.BOUNDARY: "boundary",
        VertexColor.BLACK: "black",
        VertexColor.WHITE: "white",
    }[value]


def dictionary_value(mapping: Mapping[str, Any] | Mapping[int, Any], key: int, fallback=None):
    if str(key) in mapping:
        return mapping[str(key)]
    if key in mapping:
        return mapping[key]
    return fallback


def tagging_record(
    web: ExactRibbonState,
    move: Mapping[str, Any],
    certificate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    certified = {
        int(record["vertex"]): record
        for record in certificate.get("affectedVertices", [])
        if record.get("phase") == "input"
    }
    local = move.get("local_data", {})
    live_roots = local.get("live_tag_roots", {})
    paper_roots = local.get("relation_tag_roots", {})
    shifts = local.get("relation_tag_shifts", {})
    factors = local.get("tag_transport_factors", {})
    records = []
    for vertex in affected_vertices(move):
        record = certified.get(vertex, {})
        records.append(
            {
                "vertex": vertex,
                "color": color_name(web.color[vertex]),
                "ccwDartCycle": record.get(
                    "ccw_dart_cycle", vertex_cycle(web, vertex)
                ),
                "edgeMultiplicities": record.get(
                    "edge_multiplicities_clockwise_from_live_tag", []
                ),
                "liveTagRoot": record.get(
                    "live_tag_root",
                    dictionary_value(live_roots, vertex, web.tag_after_ccw.get(vertex)),
                ),
                "paperTagRoot": record.get(
                    "paper_tag_root", dictionary_value(paper_roots, vertex)
                ),
                "tagShift": int(dictionary_value(shifts, vertex, 0)),
                "tagPermutation": record.get("tag_permutation", []),
                "permutationSign": int(
                    record.get(
                        "tag_permutation_sign",
                        dictionary_value(factors, vertex, 1),
                    )
                ),
            }
        )
    return records


def incoming_move(
    move: Mapping[str, Any], certificate: Mapping[str, Any]
) -> dict[str, Any]:
    local = move.get("local_data", {})
    branch_name = str(local.get("branch", ""))
    if not branch_name and local.get("permutation"):
        branch_name = f"permutation [{', '.join(map(str, local['permutation']))}]"
    return {
        "side": str(move["side"]).upper(),
        "relation": str(move["relation"]),
        "relationFamily": str(move.get("certificate_relation", move["relation"])),
        "branch": branch_name,
        "multiplier": int(move["coefficient_multiplier"]),
        "formalCoefficient": int(
            local.get(
                "formal_coefficient",
                local.get("paper_coefficient", move["coefficient_multiplier"]),
            )
        ),
        "tagTransportMultiplier": int(local.get("tag_transport_multiplier", 1)),
        "endpointTagTransportMultiplier": int(
            local.get("endpoint_tag_transport_multiplier", 1)
        ),
        "boundaryOrderMultiplier": int(local.get("boundary_order_multiplier", 1)),
        "bundle": local.get("bundle"),
        "affectedVertices": affected_vertices(move),
        "certificateDigest": str(move.get("certificate_digest", "")),
        "certificateSchema": str(move.get("certificate_schema", "")),
        "certificateConvention": str(certificate.get("convention", "")),
        "paperReference": str(certificate.get("paperReference", "")),
        "coefficientSource": str(local.get("coefficient_source", "")),
        "outputDigest": str(move["output_digest"]),
    }


def certificate_payload(branch) -> dict[str, Any]:
    certificate = require_production_relation_certificate(branch)
    return {
        "paperReference": certificate.paper_reference,
        "convention": certificate.convention,
        "affectedVertices": _jsonable(certificate.affected_vertices),
        "formalCoefficients": list(certificate.formal_coefficients),
        "totalTagTransportMultipliers": list(
            certificate.total_tag_transport_multipliers
        ),
        "finalCoefficients": list(certificate.final_coefficients),
        "verificationStatus": certificate.verification_status,
    }


def replay_route(
    initial_w: ExactRibbonState,
    initial_x: ExactRibbonState,
    route_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    route = deserialize_route(route_payload)
    w = copy.deepcopy(initial_w)
    x = copy.deepcopy(initial_x)
    coefficient = int(route_payload.get("initial_route_coefficient", 1) or 1)
    steps = [
        {
            "w": w,
            "x": x,
            "coefficient": coefficient,
            "move": None,
            "pathPart": "root",
        }
    ]
    for move in route.moves:
        side = str(move["side"]).upper()
        current = w if side == "W" else x
        branch = matching_branch(current, move)
        certificate = certificate_payload(branch)
        if side == "W":
            w = branch.web
        else:
            x = branch.web
        coefficient *= int(move["coefficient_multiplier"])
        steps.append(
            {
                "w": w,
                "x": x,
                "coefficient": coefficient,
                "move": _jsonable(move),
                "certificate": certificate,
                "pathPart": (
                    f"{side}:{move['relation']}:{move['output_digest']}:"
                    f"{move['coefficient_multiplier']}"
                ),
            }
        )
    if coefficient != int(route_payload["coefficient"]):
        raise ValueError(
            f"Replayed coefficient {coefficient} does not match route "
            f"coefficient {route_payload['coefficient']}."
        )
    return steps


def endpoint_payload(kind: str, record: Mapping[str, Any]) -> dict[str, Any]:
    if kind == "killed":
        return {
            "kind": "killed",
            "reason": str(record.get("reason", "zero certificate")),
            "boundaryPairs": record.get("boundary_pairs", []),
            "contribution": 0,
        }
    return {
        "kind": "terminal",
        "fllPairingValue": int(record["fll_pairing_value"]),
        "unsignedColoringCount": int(record["fll_unsigned_coloring_count"]),
        "terminalConversionSign": int(record["fll_terminal_conversion_sign"]),
        "sourceWebSign": int(record["source_web_sign"]),
        "contribution": int(record["contribution"]),
        "conventionId": str(record["fll_terminal_convention_id"]),
    }


def build_tree(spec: DemoSpec) -> dict[str, Any]:
    initial_w = load_halfedge_web(spec.w_path)
    initial_x = load_halfedge_web(spec.x_path)
    source_web_sign = word_inversion_sign(spec.x_word)
    result = run_exact_pairing_scheduler(
        initial_w, initial_x, source_web_sign=source_web_sign
    )
    if result.status != "computed":
        raise RuntimeError(f"Demo pair did not complete: {result.status} {result.reason}")

    nodes_by_path: dict[tuple[str, ...], dict[str, Any]] = {}
    nodes_by_path[()] = {
        "path": (),
        "depth": 0,
        "parentPath": None,
        "coefficient": 1,
        "incoming": None,
        "move": None,
        "w": copy.deepcopy(initial_w),
        "x": copy.deepcopy(initial_x),
        "endpoint": None,
    }

    records = [
        *(('terminal', record) for record in result.terminal_terms),
        *(('killed', record) for record in result.zero_terms),
    ]
    for kind, record in records:
        for route_payload in record.get("routes", []):
            steps = replay_route(initial_w, initial_x, route_payload)
            path: tuple[str, ...] = ()
            for depth, step in enumerate(steps[1:], 1):
                path = (*path, str(step["pathPart"]))
                nodes_by_path.setdefault(
                    path,
                    {
                        "path": path,
                        "depth": depth,
                        "parentPath": path[:-1],
                        "coefficient": int(step["coefficient"]),
                        "incoming": incoming_move(
                            step["move"], step["certificate"]
                        ),
                        "move": step["move"],
                        "certificate": step["certificate"],
                        "w": copy.deepcopy(step["w"]),
                        "x": copy.deepcopy(step["x"]),
                        "endpoint": None,
                    },
                )
            nodes_by_path[path]["endpoint"] = endpoint_payload(kind, record)

    ordered_paths = sorted(nodes_by_path, key=lambda path: (len(path), path))
    id_by_path = {path: f"N{index:03d}" for index, path in enumerate(ordered_paths)}
    children_by_path: dict[tuple[str, ...], list[tuple[str, ...]]] = defaultdict(list)
    for path in ordered_paths[1:]:
        children_by_path[path[:-1]].append(path)

    output_nodes = []
    for path in ordered_paths:
        raw = nodes_by_path[path]
        children = sorted(children_by_path.get(path, []))
        endpoint = raw["endpoint"]
        status = endpoint["kind"] if endpoint else "active"
        outgoing = None
        if children:
            first_child = nodes_by_path[children[0]]
            first_move = first_child["incoming"]
            active_web = raw["w"] if first_move["side"] == "W" else raw["x"]
            outgoing = {
                "side": first_move["side"],
                "relationFamily": first_move["relationFamily"],
                "bundle": first_move["bundle"],
                "affectedVertices": first_move["affectedVertices"],
                "certificateDigest": first_move["certificateDigest"],
                "certificateSchema": first_move["certificateSchema"],
                "certificateConvention": first_move["certificateConvention"],
                "paperReference": first_move["paperReference"],
                "coefficientSource": first_move["coefficientSource"],
                "tagging": tagging_record(
                    active_web,
                    first_child["move"],
                    first_child["certificate"],
                ),
                "branches": [nodes_by_path[child]["incoming"] for child in children],
            }
        output_nodes.append(
            {
                "id": id_by_path[path],
                "parentId": None if not path else id_by_path[path[:-1]],
                "depth": int(raw["depth"]),
                "status": status,
                "coefficient": int(raw["coefficient"]),
                "incoming": raw["incoming"],
                "outgoing": outgoing,
                "children": [id_by_path[child] for child in children],
                "w": serialize_exact_web(raw["w"]),
                "x": serialize_exact_web(raw["x"]),
                "endpoint": endpoint,
            }
        )

    return {
        "schema": "problem3.exact_pairing_tree_demo.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "slug": spec.slug,
        "title": spec.title,
        "description": spec.description,
        "input": {
            "wWord": spec.w_word,
            "xWord": spec.x_word,
            "wFile": spec.w_filename,
            "xFile": spec.x_filename,
            "sourceWebSign": source_web_sign,
        },
        "result": {
            "status": result.status,
            "value": result.value,
            "expansions": result.expansions,
            "relationCounts": result.relation_counts,
            "terminalCount": len(result.terminal_terms),
            "killedCount": len(result.zero_terms),
        },
        "provenance": {
            "checker": "exact_pairing_scheduler_20260819.run_exact_pairing_scheduler",
            "taggingConventionId": (
                "GPPSS Definition 2.8 local cyclic-order tagging and "
                "Lemma 2.5 tag transport"
            ),
            "terminalConventionId": "fll_prop2_20_source_orientation_unsigned_count_v1",
            "moduleHashes": {
                name: sha256(PROJECT_ROOT / name)
                for name in (
                    "exact_pairing_scheduler_20260819.py",
                    "exact_pairing_kernel_20260819.py",
                    "halfedge_web_20260812.py",
                )
            },
        },
        "nodes": output_nodes,
    }


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    manifest_entries = []
    for spec in DEMO_SPECS:
        payload = build_tree(spec)
        output = OUTPUT_DIRECTORY / f"{spec.slug}.json"
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        entry = {
            "slug": spec.slug,
            "title": spec.title,
            "description": spec.description,
            "path": f"/exact-tree-demos/{spec.slug}.json",
            "wWord": spec.w_word,
            "xWord": spec.x_word,
            "value": payload["result"]["value"],
            "nodeCount": len(payload["nodes"]),
            "maximumDepth": max(node["depth"] for node in payload["nodes"]),
            "relationFamilies": sorted(
                {
                    node["outgoing"]["relationFamily"]
                    for node in payload["nodes"]
                    if node["outgoing"]
                }
            ),
        }
        manifest_entries.append(entry)
        print(json.dumps({"output": str(output), **entry}, indent=2))
    MANIFEST_OUTPUT.write_text(
        json.dumps(
            {
                "schema": "problem3.exact_pairing_tree_demo_manifest.v1",
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "demos": manifest_entries,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
