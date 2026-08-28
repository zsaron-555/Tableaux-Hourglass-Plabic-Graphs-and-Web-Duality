#!/usr/bin/env python3
"""Minimal interactive exact-checker reduction tree for Problem 3 pairings.

The application is implemented in Python and uses the authoritative exact
pairing scheduler.  The browser is only a viewer: it never invents a branch,
coefficient, tag sign, or terminal value.

Local tagging and tag transport use the GPPSS convention.  FLL is used only
for the final terminal conversion (source orientation times unsigned count).
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import math
import os
import sys
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Mapping

from benzene_representations import presentation_paths_for_word


APP_ROOT = Path(__file__).resolve().parent
# Compatibility alias used by existing regression tests and local launchers.
ROOT = APP_ROOT
PROJECT_ROOT = Path(os.environ.get("PROBLEM3_ROOT", APP_ROOT)).expanduser().resolve()
GRAPH_DATA_DOWNLOAD_URL = (
    "https://github.com/zsaron-555/"
    "Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality/releases/download/"
    "sl4-web-data-v1/4x4_All_graph_data_260815.zip"
)
WEB_EXPLORER_URL = os.environ.get(
    "PROBLEM3_WEB_EXPLORER_URL",
    "http://127.0.0.1:8766/",
).strip()
GRAPH_DIRECTORY_NAMES = (
    "4x4_All_graph_data",
    "hourglass_disk_4x4_all_graph_data",
    "hourglass_disk_4x4_promotion_reps_graph_data",
    "hourglass_disk_4x4_transpose_words_graph_data",
)
TREE_BUILDER_PATH = APP_ROOT / "exact_checker_tree_data_20260826.py"


def graph_directories(project_root: Path) -> tuple[Path, ...]:
    """Accept either the extracted graph folder or the folder containing it."""
    root = project_root.expanduser().resolve()
    if root.name in GRAPH_DIRECTORY_NAMES and root.is_dir():
        parent = root.parent
        return (root, *(parent / name for name in GRAPH_DIRECTORY_NAMES if name != root.name))
    return tuple(root / name for name in GRAPH_DIRECTORY_NAMES)


ALL_GRAPH_DIRS = graph_directories(PROJECT_ROOT)


def configure_project_root(project_root: str | Path) -> None:
    """Point graph lookup at an extracted data folder anywhere on this laptop."""
    global PROJECT_ROOT, ALL_GRAPH_DIRS
    candidate = Path(project_root).expanduser().resolve()
    if candidate.is_file():
        raise ValueError(
            "--project-root must name the extracted 4x4_All_graph_data folder "
            "or the folder containing it. Extract the downloaded ZIP first."
        )
    PROJECT_ROOT = candidate
    ALL_GRAPH_DIRS = graph_directories(candidate)
    graph_index.cache_clear()

MAGENTA = "#cf2f2f"
BRANCH_BLUE = "#2586d8"
ORANGE = "#e48124"
INK = "#17202a"
MUTED = "#667481"


@dataclass(frozen=True)
class RuntimePair:
    slug: str
    title: str
    description: str
    w_path: Path
    x_path: Path

    @property
    def w_filename(self) -> str:
        return self.w_path.name

    @property
    def x_filename(self) -> str:
        return self.x_path.name

    @property
    def w_word(self) -> str:
        return word_from_path(self.w_path)

    @property
    def x_word(self) -> str:
        return word_from_path(self.x_path)


DEMO_PAIRS = (
    (
        "simple-wrench",
        "Two-step wrench",
        "23563_1234111222333444.json",
        "00210_1111223344234234.json",
    ),
    (
        "double-trident",
        "Six-branch double trident",
        "21634_1231142132233444.json",
        "02391_1112312423434234.json",
    ),
    (
        "rolling-wrench",
        "Six-level wrench tree",
        "23563_1234111222333444.json",
        "00001_1111222233334444.json",
    ),
)


def load_tree_builder():
    """Load the checker-tree serializer without importing any website code."""
    name = "problem3_exact_tree_builder_runtime"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, TREE_BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load exact tree builder at {TREE_BUILDER_PATH}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def graph_index() -> dict[str, Path]:
    """Index the same graph folders accepted by the first wrench explorer."""
    found: dict[str, Path] = {}
    for directory in ALL_GRAPH_DIRS:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            found.setdefault(path.name, path)
            found.setdefault(path.stem, path)
            if "_" in path.stem:
                prefix, word = path.stem.split("_", 1)
                found.setdefault(word, path)
                if prefix.isdigit():
                    found.setdefault(str(int(prefix)), path)
                    found.setdefault(prefix, path)
    return found


def resolve_graph(value: str) -> Path:
    value = value.strip()
    direct = Path(value).expanduser()
    if value and direct.is_file():
        return direct.resolve()
    for directory in ALL_GRAPH_DIRS:
        candidate = directory / value
        if value and candidate.is_file():
            return candidate.resolve()
    match = graph_index().get(value)
    if match is None and value.endswith(".json"):
        match = graph_index().get(Path(value).name)
    if match is None:
        raise FileNotFoundError(
            f"Could not find graph {value!r}. Enter a Yamanouchi word, index, "
            "JSON filename, or full JSON path."
        )
    return match.resolve()


def catalogue_graph_dir() -> Path:
    for directory in ALL_GRAPH_DIRS[:2]:
        if directory.is_dir() and (directory / "benzene_move_presentations" / "manifest.json").is_file():
            return directory.resolve()
    raise FileNotFoundError("Could not find the all-web graph directory and benzene presentation manifest.")


def benzene_presentation_options(value: str) -> dict[str, Any]:
    """Return exact, presentation-dependent choices for one W or X input."""
    if not value.strip():
        return {"word": "", "selected": "", "requiresSelection": False, "options": []}
    path = resolve_graph(value)
    word = word_from_path(path)
    directory = catalogue_graph_dir()
    records = presentation_paths_for_word(directory, word)
    if not any(int(record["benzene_count"]) > 0 for record in records):
        return {"word": word, "selected": "", "requiresSelection": False, "options": []}

    options = []
    selected = ""
    for record in records:
        option_path = Path(record["path"]).resolve()
        option_value = option_path.relative_to(directory).as_posix()
        representation = str(record["representation"])
        origin = str(record["origin"])
        origin_label = "catalogue presentation" if origin == "catalogue" else "benzene-move presentation"
        options.append(
            {
                "value": option_value,
                "label": f"{representation.title()} — {origin_label}",
                "representation": representation,
                "benzeneCount": int(record["benzene_count"]),
                "origin": origin,
            }
        )
        raw = value.strip()
        if path == option_path and (
            raw == option_value
            or raw == option_path.name
            or Path(raw).expanduser().is_absolute()
        ):
            selected = option_value
    return {
        "word": word,
        "selected": selected,
        "requiresSelection": True,
        "options": options,
    }


def resolve_selected_graph(value: str, selected: str, side: str) -> Path:
    """Resolve one side without silently choosing its catalogue presentation."""
    payload = benzene_presentation_options(value)
    if not payload["requiresSelection"]:
        return resolve_graph(value)
    allowed = {str(option["value"]) for option in payload["options"]}
    choice = selected.strip() or str(payload.get("selected", ""))
    if not choice:
        raise ValueError(
            f"{side} contains a benzene. Select its exact top, middle, or bottom presentation before running the checker."
        )
    if choice not in allowed:
        raise ValueError(f"The selected {side} presentation is not an available exact presentation for {payload['word']}.")
    return resolve_graph(choice)


def word_from_path(path: Path) -> str:
    stem = path.stem
    if "_" in stem:
        candidate = stem.split("_", 1)[1][:16]
        if len(candidate) == 16 and set(candidate) <= set("1234"):
            return candidate
    payload = json.loads(path.read_text(encoding="utf-8"))
    word = payload.get("word") or payload.get("metadata", {}).get("word")
    return str(word or stem)


@lru_cache(maxsize=16)
def compute_tree(w_path_text: str, x_path_text: str) -> dict[str, Any]:
    builder = load_tree_builder()
    pair = RuntimePair(
        slug="interactive-pair",
        title="Exact pairing reduction",
        description="Every branch is replayed from its certified exact route.",
        w_path=Path(w_path_text),
        x_path=Path(x_path_text),
    )
    return builder.build_tree(pair)


def signed(value: int) -> str:
    return f"{value:+d}"


def point(vertex: Mapping[str, Any], size: int) -> tuple[float, float]:
    x, y = vertex.get("source_xy") or (0.0, 0.0)
    scale = size * 0.39
    return size / 2 + scale * float(x), size / 2 - scale * float(y)


def cubic_hourglass(
    first: tuple[float, float],
    second: tuple[float, float],
    strand: int,
) -> str:
    """Use the crossing-hourglass geometry from wrench_web_app_0714.py."""
    x1, y1 = first
    x2, y2 = second
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    amplitude = min(15.0, length * 0.34)
    c1 = (x1 + 0.28 * dx + strand * amplitude * nx, y1 + 0.28 * dy + strand * amplitude * ny)
    c2 = (x1 + 0.72 * dx - strand * amplitude * nx, y1 + 0.72 * dy - strand * amplitude * ny)
    return (
        f"M {x1:.2f} {y1:.2f} C {c1[0]:.2f} {c1[1]:.2f}, "
        f"{c2[0]:.2f} {c2[1]:.2f}, {x2:.2f} {y2:.2f}"
    )


def live_tag_point(
    vertex: Mapping[str, Any],
    vertex_by_id: Mapping[int, Mapping[str, Any]],
    dart_by_id: Mapping[int, Mapping[str, Any]],
    size: int,
) -> tuple[float, float] | None:
    root_id = vertex.get("tag_after_ccw")
    source = vertex.get("source_xy")
    if root_id is None or source is None:
        return None
    root = dart_by_id.get(int(root_id))
    nxt = dart_by_id.get(int(root["next_ccw"])) if root else None
    root_mate = dart_by_id.get(int(root["mate"])) if root else None
    next_mate = dart_by_id.get(int(nxt["mate"])) if nxt else None
    first = vertex_by_id.get(int(root_mate["vertex"])) if root_mate else None
    second = vertex_by_id.get(int(next_mate["vertex"])) if next_mate else None
    if not first or not second or first.get("source_xy") is None or second.get("source_xy") is None:
        return None
    x0, y0 = map(float, source)
    x1, y1 = map(float, first["source_xy"])
    x2, y2 = map(float, second["source_xy"])
    a0 = math.atan2(y1 - y0, x1 - x0)
    a1 = math.atan2(y2 - y0, x2 - x0)
    delta = (a1 - a0) % (2 * math.pi)
    if delta < 0.08:
        delta = 0.28
    angle = a0 + delta / 2
    tag_vertex = {"source_xy": [x0 + 0.075 * math.cos(angle), y0 + 0.075 * math.sin(angle)]}
    return point(tag_vertex, size)


def selected_relation_parts(
    web: Mapping[str, Any], outgoing: Mapping[str, Any] | None
) -> tuple[set[int], set[int], set[int]]:
    """Return all vertices, ordinary edges, and bundles in the selected move.

    This is the complete-local-piece rule used by the first wrench explorer:
    a wrench includes both hourglass strands and every arm at its endpoints;
    a double trident includes its central edge and all six outer arms.
    """
    if not outgoing:
        return set(), set(), set()
    affected = {int(value) for value in outgoing.get("affectedVertices", [])}
    physical_edges: set[int] = set()
    bundles: set[int] = set()
    for dart in web["darts"]:
        if int(dart["vertex"]) not in affected:
            continue
        if dart.get("bundle") is None:
            physical_edges.add(int(dart["physical_edge"]))
        else:
            bundles.add(int(dart["bundle"]))
    bundle = outgoing.get("bundle")
    if bundle is not None:
        bundles.add(int(bundle))
    return affected, physical_edges, bundles


def exact_edge_inventory(
    web: Mapping[str, Any],
) -> list[tuple[str, int, tuple[int, int]]]:
    """Describe ordinary edges and hourglass bundles by their endpoints."""
    darts = {int(dart["id"]): dart for dart in web["darts"]}
    records: list[tuple[str, int, tuple[int, int]]] = []
    seen_bundles: set[int] = set()
    for dart_id, dart in sorted(darts.items()):
        mate = darts[int(dart["mate"])]
        endpoints = tuple(sorted((int(dart["vertex"]), int(mate["vertex"]))))
        if dart.get("bundle") is not None:
            bundle = int(dart["bundle"])
            if bundle in seen_bundles:
                continue
            seen_bundles.add(bundle)
            records.append(("bundle", bundle, endpoints))
        elif dart_id < int(dart["mate"]):
            records.append(("ordinary", int(dart["physical_edge"]), endpoints))
    return records


def resulting_branch_parts(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[set[int], set[int], set[int]]:
    """Find the branch edges created by one exact relation.

    This is the exact-state analogue of the first wrench app's ``after edge
    set - before edge set`` display. A multiset comparison is required because
    exact states can contain parallel edges with identical endpoints.
    """
    remaining = Counter(
        (kind, endpoints) for kind, _identifier, endpoints in exact_edge_inventory(before)
    )
    ordinary: set[int] = set()
    bundles: set[int] = set()
    vertices: set[int] = set()
    for kind, identifier, endpoints in exact_edge_inventory(after):
        signature = (kind, endpoints)
        if remaining[signature]:
            remaining[signature] -= 1
            continue
        vertices.update(endpoints)
        if kind == "bundle":
            bundles.add(identifier)
        else:
            ordinary.add(identifier)
    return vertices, ordinary, bundles


def render_web_svg(
    title: str,
    web: Mapping[str, Any],
    outgoing: Mapping[str, Any] | None,
    selected: bool,
    branch_vertices: set[int] | None = None,
    branch_edges: set[int] | None = None,
    branch_bundles: set[int] | None = None,
    size: int = 260,
) -> str:
    vertices = {int(vertex["id"]): vertex for vertex in web["vertices"]}
    darts = {int(dart["id"]): dart for dart in web["darts"]}
    affected, selected_edges, selected_bundles = (
        selected_relation_parts(web, outgoing) if selected else (set(), set(), set())
    )
    branch_vertices = branch_vertices or set()
    branch_edges = branch_edges or set()
    branch_bundles = branch_bundles or set()
    lines = [
        '<div class="web-card">',
        f'<div class="web-title">{html.escape(title)}</div>',
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" aria-label="{html.escape(title)}">',
        f'<circle cx="{size/2}" cy="{size/2}" r="{size*0.39}" fill="none" stroke="#111" stroke-width="1.5"/>',
    ]

    for dart_id, dart in sorted(darts.items()):
        mate_id = int(dart["mate"])
        if dart_id > mate_id or dart.get("bundle") is not None:
            continue
        first = vertices[int(dart["vertex"])]
        second = vertices[int(darts[mate_id]["vertex"])]
        p1, p2 = point(first, size), point(second, size)
        selected_edge = int(dart["physical_edge"]) in selected_edges
        result_edge = int(dart["physical_edge"]) in branch_edges
        if selected_edge:
            color, width = MAGENTA, 4.5
        elif result_edge:
            color, width = BRANCH_BLUE, 4.5
        else:
            color, width = "#111", 1.8
        lines.append(
            f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" '
            f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'
        )

    bundle_groups: dict[int, list[Mapping[str, Any]]] = {}
    for dart in darts.values():
        if dart.get("bundle") is not None:
            bundle_groups.setdefault(int(dart["bundle"]), []).append(dart)
    for bundle_id, bundle_darts in sorted(bundle_groups.items()):
        dart = min(bundle_darts, key=lambda item: int(item["id"]))
        mate = darts[int(dart["mate"])]
        first = vertices[int(dart["vertex"])]
        second = vertices[int(mate["vertex"])]
        p1, p2 = point(first, size), point(second, size)
        selected_bundle = bundle_id in selected_bundles
        result_bundle = bundle_id in branch_bundles
        if selected_bundle:
            color, width = MAGENTA, 4.5
        elif result_bundle:
            color, width = BRANCH_BLUE, 4.5
        else:
            color, width = "#111", 1.8
        for strand in (-1, 1):
            path = cubic_hourglass(p1, p2, strand)
            if strand == 1:
                lines.append(f'<path d="{path}" fill="none" stroke="#fff" stroke-width="{width + 2.5}"/>')
            lines.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'
            )

    for vertex_id, vertex in sorted(vertices.items()):
        x, y = point(vertex, size)
        boundary = vertex.get("boundary_label")
        color_code = int(vertex.get("color", 0))
        fill = "#111" if boundary is not None or color_code == 1 else "#fff"
        radius = 4.8 if boundary is not None else 5.8
        lines.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="{fill}" stroke="#111" stroke-width="1.6"/>'
        )
        if vertex_id in affected:
            lines.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="10.5" fill="none" stroke="{MAGENTA}" stroke-width="2.5"/>'
            )
        elif vertex_id in branch_vertices:
            lines.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="10.5" fill="none" stroke="{BRANCH_BLUE}" stroke-width="2.5"/>'
            )
        if boundary is not None:
            sx, sy = vertex.get("source_xy") or (0.0, 0.0)
            label_point = point({"source_xy": [1.14 * float(sx), 1.14 * float(sy)]}, size)
            lines.append(
                f'<text x="{label_point[0]:.2f}" y="{label_point[1]:.2f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="9">{int(boundary)}</text>'
            )
        tag = live_tag_point(vertex, vertices, darts, size)
        if tag is not None:
            x0, y0 = tag
            points = f"{x0:.2f},{y0-4:.2f} {x0+4:.2f},{y0:.2f} {x0:.2f},{y0+4:.2f} {x0-4:.2f},{y0:.2f}"
            lines.append(f'<polygon points="{points}" fill="{ORANGE}" stroke="#8b4a0c" stroke-width=".7"/>')

    if selected and outgoing:
        label = str(outgoing.get("relationFamily", "relation")).replace("_", " ")
        lines.append(
            f'<text x="{size/2:.1f}" y="{size-8}" text-anchor="middle" fill="{MAGENTA}" font-size="10" font-weight="bold">selected {html.escape(label)}</text>'
        )
    if branch_edges or branch_bundles:
        lines.append(
            f'<text x="{size/2:.1f}" y="12" text-anchor="middle" fill="{BRANCH_BLUE}" font-size="10" font-weight="bold">resulting branch edges</text>'
        )
    lines.extend(["</svg>", "</div>"])
    return "".join(lines)


def certificate_html(outgoing: Mapping[str, Any] | None) -> str:
    if not outgoing:
        return ""
    rows = []
    for record in outgoing.get("tagging", []):
        rows.append(
            "<tr>"
            f"<td>{record['vertex']} ({html.escape(str(record['color']))})</td>"
            f"<td>{html.escape(str(record.get('ccwDartCycle', [])))}</td>"
            f"<td>{html.escape(str(record.get('liveTagRoot')))}</td>"
            f"<td>{html.escape(str(record.get('paperTagRoot')))}</td>"
            f"<td>{html.escape(str(record.get('tagPermutation', [])))}</td>"
            f"<td>{signed(int(record.get('permutationSign', 1)))}</td>"
            "</tr>"
        )
    branches = " + ".join(
        f"({signed(int(branch['multiplier']))}) {html.escape(str(branch.get('branch') or branch['relation']))}"
        for branch in outgoing.get("branches", [])
    )
    return f"""
      <details class="certificate">
        <summary>GPPSS tagging and certified coefficients</summary>
        <p><strong>Relation:</strong> {html.escape(str(outgoing.get('relationFamily', ''))).replace('_', ' ')}</p>
        <p><strong>Certified branches:</strong> {branches}</p>
        <table><thead><tr><th>vertex</th><th>CCW darts</th><th>live root</th><th>paper root</th><th>tag permutation</th><th>sign</th></tr></thead>
        <tbody>{''.join(rows)}</tbody></table>
        <p class="muted"><strong>Paper:</strong> {html.escape(str(outgoing.get('paperReference', '')))}</p>
        <p class="muted"><strong>Convention:</strong> {html.escape(str(outgoing.get('certificateConvention', '')))}</p>
        <p class="mono">certificate {html.escape(str(outgoing.get('certificateDigest', '')))}</p>
      </details>
    """


def render_node(
    node: Mapping[str, Any],
    parent: Mapping[str, Any] | None = None,
) -> str:
    outgoing = node.get("outgoing")
    selected_side = str(outgoing.get("side", "")) if outgoing else ""
    incoming = node.get("incoming")
    endpoint = node.get("endpoint")
    branch_w = (set(), set(), set())
    branch_x = (set(), set(), set())
    if parent is not None and incoming is not None:
        side = str(incoming["side"]).lower()
        branch_parts = resulting_branch_parts(parent[side], node[side])
        if side == "w":
            branch_w = branch_parts
        else:
            branch_x = branch_parts
    incoming_line = "input pair"
    if incoming:
        incoming_line = (
            f"{html.escape(str(incoming['side']))} · "
            f"{html.escape(str(incoming['relation']).replace('_', ' '))} · "
            f"branch {html.escape(str(incoming.get('branch') or ''))} · multiplier {signed(int(incoming['multiplier']))}"
        )
    status_text = str(node["status"])
    endpoint_html = ""
    if endpoint:
        if endpoint["kind"] == "killed":
            endpoint_html = f'<p class="killed"><strong>Killed:</strong> {html.escape(str(endpoint.get("reason", "zero certificate")))}</p>'
        else:
            endpoint_html = (
                '<p class="terminal"><strong>Terminal:</strong> '
                f'FLL value {signed(int(endpoint.get("fllPairingValue", 0)))}; '
                f'unsigned consistent-labeling count {int(endpoint.get("unsignedColoringCount", 0))}; '
                f'weighted contribution {signed(int(endpoint.get("contribution", 0)))}</p>'
            )
    apply_button = ""
    if node["status"] == "active":
        relation = str(outgoing.get("relationFamily", "relation")).replace("_", " ") if outgoing else "relation"
        apply_button = f'<button type="button" class="expand" data-node="{node["id"]}">Apply next {html.escape(relation)}</button>'
    actions = (
        '<div class="node-actions">'
        f'{apply_button}'
        '<button type="button" class="back-local" disabled>Back to previous layer</button>'
        '</div>'
    )
    return f"""
      <article id="node-card-{html.escape(str(node['id']))}" class="node-card status-{html.escape(status_text)}">
        <div class="node-head"><strong>{html.escape(str(node['id']))}</strong><span>{html.escape(status_text)}</span><b>coefficient {signed(int(node['coefficient']))}</b></div>
        <p class="muted">{incoming_line}</p>
        <div class="pair-pictures">
          {render_web_svg('W', node['w'], outgoing, selected_side == 'W', *branch_w)}
          {render_web_svg('X', node['x'], outgoing, selected_side == 'X', *branch_x)}
        </div>
        {certificate_html(outgoing)}
        {endpoint_html}
        {actions}
      </article>
    """


def embedded_tree_payload(tree: Mapping[str, Any]) -> str:
    node_by_id = {node["id"]: node for node in tree["nodes"]}
    payload = {
        "input": tree["input"],
        "result": tree["result"],
        "provenance": tree["provenance"],
        "nodes": [
            {
                "id": node["id"],
                "parentId": node["parentId"],
                "depth": node["depth"],
                "status": node["status"],
                "coefficient": node["coefficient"],
                "children": node["children"],
                "incoming": node["incoming"],
                "endpoint": node["endpoint"],
                "card": render_node(
                    node,
                    node_by_id.get(node["parentId"]),
                ),
            }
            for node in tree["nodes"]
        ],
    }
    return json.dumps(payload, separators=(",", ":")).replace("</", "<" + "\\/")


def form_value(value: str) -> str:
    return html.escape(value, quote=True)


def page(
    tree: Mapping[str, Any],
    w_value: str,
    x_value: str,
    w_presentation: str = "",
    x_presentation: str = "",
    initial_view: str = "picture",
) -> str:
    if initial_view not in {"picture", "ledger", "summary"}:
        raise ValueError(f"Unknown initial view {initial_view!r}.")
    explorer_name = "Pairing Explorer"
    explorer_description = (
        "Authoritative tagged pairing value, complete reduction tree, branch pictures, and branch ledger."
    )
    demos = "".join(
        f'<option value="{slug}" data-w="{form_value(w)}" data-x="{form_value(x)}">{html.escape(title)}</option>'
        for slug, title, w, x in DEMO_PAIRS
    )
    payload = embedded_tree_payload(tree)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{explorer_name} — Exact Tagged Checker</title>
<style>
:root{{--ink:{INK};--muted:{MUTED};--line:#d8dee6;--bg:#f6f8fb;--panel:#fff;--red:{MAGENTA};}}
*{{box-sizing:border-box}} body{{margin:0;font-family:Arial,Helvetica,sans-serif;color:var(--ink);background:var(--bg)}}
header{{padding:24px 30px 18px;background:#fff;border-bottom:1px solid var(--line)}} h1{{margin:0 0 6px;font-size:28px}} h2{{font-size:19px}}
.site-switch{{display:inline-block;margin-top:10px;padding:8px 12px;border-radius:6px;background:#17202a;color:#fff;text-decoration:none;font-size:13px;font-weight:bold}}
p{{margin:6px 0}} .muted{{color:var(--muted);font-size:13px}} .mono{{font-family:monospace;font-size:11px;overflow-wrap:anywhere}}
form{{display:grid;grid-template-columns:1fr 1fr 220px 130px;gap:10px;align-items:end;margin-top:16px}} label{{display:flex;flex-direction:column;gap:5px;color:var(--muted);font-size:13px}}
input,select,button{{height:39px;border:1px solid var(--line);border-radius:7px;padding:8px 10px;background:#fff;color:var(--ink)}} button{{border:0;background:var(--ink);color:#fff;cursor:pointer}}
.web-input-group{{display:flex;flex-direction:column;gap:8px;min-width:0}} .presentation-choice{{padding:8px;border:1px solid #b8d3e8;border-radius:7px;background:#f2f8fc}} .presentation-choice[hidden]{{display:none}} .presentation-status{{min-height:14px;color:#536c80;font-size:11px}}
main{{padding:20px 30px 44px}} .controls,.run-summary,.level,.summary-view{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:15px}}
.controls{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}} .controls label{{flex-direction:row;align-items:center}} .controls input{{height:auto}} .controls button{{height:34px}}
.run-summary{{display:grid;grid-template-columns:1fr repeat(4,auto);gap:18px;align-items:center}} .metric{{display:flex;flex-direction:column;gap:3px}} .metric strong{{font-size:22px}}
.level-head{{display:flex;gap:14px;align-items:baseline;margin-bottom:10px}} .level-head span{{color:var(--muted);font-size:12px}} .level-nodes{{display:grid;grid-template-columns:repeat(auto-fit,minmax(540px,1fr));gap:12px}}
.node-card{{border:1px solid var(--line);border-radius:8px;padding:10px;min-width:0}} .node-head{{display:flex;gap:12px;align-items:center}} .node-head span{{padding:3px 7px;border-radius:999px;background:#eef1f4;font-size:11px}} .node-head b{{margin-left:auto}}
.pair-pictures{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}} .web-card{{border:1px solid var(--line);border-radius:7px;padding:6px;text-align:center}} .web-title{{font-weight:bold}} .web-card svg{{display:block;max-width:100%;height:auto;margin:auto}}
.certificate{{margin-top:8px;padding:8px;border:1px solid var(--line);border-radius:7px;background:#fafbfd}} details summary{{cursor:pointer;color:var(--muted)}} table{{width:100%;border-collapse:collapse;font-size:12px}} th,td{{padding:5px;border-bottom:1px solid var(--line);text-align:left}}
.killed{{padding:8px;background:#fff1f1;color:#8d1f1f}} .terminal{{padding:8px;background:#edf8f2;color:#0e6f3c}} .node-actions{{display:flex;gap:8px;align-items:center;margin-top:8px}} .node-actions .expand{{flex:1}} .back-local{{background:#eef1f4;color:var(--ink);border:1px solid var(--line);white-space:nowrap}} .hidden-note{{padding:8px 12px;background:#fff4d6;border:1px solid #d99a22;border-radius:7px;margin-bottom:10px;font-size:12px}}
.summary-tree{{overflow:auto;padding:12px;border:1px solid var(--line);border-radius:7px;background:#fff}} .summary-tree svg{{display:block;margin:0 auto;min-width:100%}} .summary-edge{{stroke:#8b969f;stroke-width:1.4}} .summary-edge-label{{font-size:11px;font-weight:bold;fill:#53616c}} .summary-node-label{{font-size:11px;font-weight:bold;fill:var(--ink)}} .summary-node-detail{{font-size:9px;fill:var(--muted)}} .summary-node-target{{cursor:pointer;outline:none}} .summary-node-target .summary-hit{{fill:transparent}} .summary-node-target:hover .summary-hit,.summary-node-target:focus .summary-hit{{fill:#e8f2fb;stroke:{BRANCH_BLUE};stroke-width:2}} .summary-node-target:focus-visible{{outline:none}} .summary-view[hidden],#picture-view[hidden]{{display:none}}
.branch-ledger{{overflow:auto}} .branch-ledger table{{min-width:920px}} .branch-ledger .focus-node{{height:30px;padding:5px 9px;background:#eef1f4;color:var(--ink);border:1px solid var(--line)}} .controls button:disabled,.expand:disabled,.back-local:disabled{{cursor:default;opacity:.5}}
.convention-note{{margin-top:12px;padding:10px;border-left:4px solid {ORANGE};background:#fff}} @media(max-width:950px){{form,.run-summary,.pair-pictures{{grid-template-columns:1fr}}.level-nodes{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>{explorer_name}</h1><p class="muted">{explorer_description}</p>
<a class="site-switch" href="{html.escape(WEB_EXPLORER_URL, quote=True)}">Open Web Explorer</a>
<p class="muted"><a href="{GRAPH_DATA_DOWNLOAD_URL}">Download the 4x4 graph data from GitHub</a>. Extract the ZIP anywhere, then start this app with <span class="mono">--project-root "/path/to/folder-containing-4x4_All_graph_data"</span>.</p>
<form action="/run" method="get"><input type="hidden" name="view" value="{form_value(initial_view)}">
<div class="web-input-group"><label>W word, index, or JSON file<input id="w" name="w" value="{form_value(w_value)}"></label><label id="w-presentation-box" class="presentation-choice" hidden>Exact W benzene presentation<select id="w-presentation" name="w_presentation" data-selected="{form_value(w_presentation)}" disabled><option>Checking presentations...</option></select><span id="w-presentation-status" class="presentation-status"></span></label></div>
<div class="web-input-group"><label>X word, index, or JSON file<input id="x" name="x" value="{form_value(x_value)}"></label><label id="x-presentation-box" class="presentation-choice" hidden>Exact X benzene presentation<select id="x-presentation" name="x_presentation" data-selected="{form_value(x_presentation)}" disabled><option>Checking presentations...</option></select><span id="x-presentation-status" class="presentation-status"></span></label></div>
<label>Example<select id="demo"><option value="">choose an example</option>{demos}</select></label>
<button type="submit">Compute pairing and tree</button></form></header>
<main>
<section class="run-summary"><div><h2>Authoritative tagged pairing</h2><p><b>W</b> {html.escape(str(tree['input']['wWord']))}</p><p><b>X</b> {html.escape(str(tree['input']['xWord']))}</p><p class="muted">The value and every displayed branch come from the same exact scheduler result.</p></div>
<div class="metric"><span>expansions</span><strong>{int(tree['result']['expansions'])}</strong></div><div class="metric"><span>killed</span><strong>{int(tree['result']['killedCount'])}</strong></div><div class="metric"><span>terminal</span><strong>{int(tree['result']['terminalCount'])}</strong></div><div class="metric"><span>pairing</span><strong id="final-value">{signed(int(tree['result']['value']))}</strong></div></section>
<section class="controls"><button id="picture-button" type="button">Interactive branch pictures</button><button id="ledger-button" type="button">Branch pairing ledger</button><button id="summary-button" type="button">Whole reduction tree</button><button id="back" type="button" disabled>Back to previous layer</button><label><input id="automatic" type="checkbox"> automatically show every branch picture</label><button id="reset" type="button">Reset replay</button></section>
<div id="picture-view"></div><section id="ledger-view" class="summary-view" hidden><h2>Branch pairing ledger</h2><p class="muted">Every terminal or killed branch in the authoritative tagged computation. Open a branch to reveal its exact picture route in the interactive tree.</p><div id="branch-ledger" class="branch-ledger"></div></section><section id="summary-view" class="summary-view" hidden><h2>Entire reduction tree</h2><p class="muted">Root at the top. Each line is a certified branch; its label is the branch multiplier. Green nodes are terminal, red nodes are killed, and black nodes are expandable. Click any labeled node to open that exact node in the interactive branch pictures and continue from there.</p><div id="summary-tree" class="summary-tree"></div></section>
<section class="convention-note"><strong>Convention and highlighting</strong><p>Orange diamonds are live GPPSS tag gaps. Local tag transport and certified skein coefficients use GPPSS, not FLL. FLL is used only at terminal conversion: source Plücker orientation × unsigned consistent-labeling count.</p><p><span style="color:{MAGENTA};font-weight:bold">Magenta</span> highlights the complete wrench or double trident being expanded, including every incident arm. <span style="color:{BRANCH_BLUE};font-weight:bold">Blue</span> highlights every new edge created in each resulting branch.</p></section>
</main><script id="tree-data" type="application/json">{payload}</script>
<script>
const data=JSON.parse(document.getElementById('tree-data').textContent);const byId=new Map(data.nodes.map(n=>[n.id,n]));const active=data.nodes.filter(n=>n.status==='active').map(n=>n.id);let expanded=new Set();let history=[];let automatic=false;
function sign(v){{return v>=0?'+'+v:String(v)}}
function revealed(){{if(automatic)return new Set(data.nodes.map(n=>n.id));const root=data.nodes.find(n=>n.parentId===null),seen=new Set([root.id]),queue=[root.id];while(queue.length){{const id=queue.shift(),node=byId.get(id);if(!expanded.has(id))continue;for(const child of node.children){{seen.add(child);queue.push(child)}}}}return seen}}
function undoLast(){{if(automatic||history.length===0)return;expanded=history.pop();showView('picture');renderPictures()}}
function bindExpand(){{document.querySelectorAll('button.expand').forEach(button=>{{const applied=expanded.has(button.dataset.node);button.disabled=applied;button.textContent=applied?'relation applied':button.textContent;button.onclick=()=>{{history.push(new Set(expanded));expanded.add(button.dataset.node);renderPictures()}}}});document.querySelectorAll('button.back-local').forEach(button=>button.onclick=undoLast)}}
function updateBackButton(){{const disabled=automatic||history.length===0,title=automatic?'Turn off automatic mode to step backward':(history.length?'Undo the most recent relation':'No earlier layer');for(const button of [document.getElementById('back'),...document.querySelectorAll('button.back-local')]){{button.disabled=disabled;button.title=title}}}}
function renderPictures(){{const seen=revealed(),nodes=data.nodes.filter(n=>seen.has(n.id)),maximum=Math.max(0,...nodes.map(n=>n.depth)),minimum=automatic?0:Math.max(0,maximum-2);let out=minimum>0?`<div class="hidden-note">Levels 0-${{minimum-1}} are hidden; manual mode keeps the latest three picture levels.</div>`:'';for(let depth=minimum;depth<=maximum;depth++){{const level=nodes.filter(n=>n.depth===depth);out+=`<section class="level"><div class="level-head"><strong>Level ${{depth}}</strong><span>${{depth===0?'input':'after '+depth+' relation'+(depth===1?'':'s')}}</span><span>${{level.length}} node${{level.length===1?'':'s'}}</span></div><div class="level-nodes">${{level.map(n=>n.card).join('')}}</div></section>`}}document.getElementById('picture-view').innerHTML=out;bindExpand();updateBackButton()}}
function summarySvg(){{const root=data.nodes.find(n=>n.parentId===null),positions=new Map();let leafIndex=0;const horizontal=145,vertical=105,padding=65;function place(id){{const node=byId.get(id);let x;if(node.children.length===0){{x=padding+leafIndex*horizontal;leafIndex++}}else{{const childXs=node.children.map(place);x=childXs.reduce((a,b)=>a+b,0)/childXs.length}}const y=padding+node.depth*vertical;positions.set(id,{{x,y}});return x}}place(root.id);const maximumDepth=Math.max(...data.nodes.map(n=>n.depth)),width=Math.max(760,padding*2+Math.max(1,leafIndex-1)*horizontal),height=padding*2+maximumDepth*vertical;let edges='',nodes='';for(const node of data.nodes){{const p=positions.get(node.id);if(node.parentId){{const q=positions.get(node.parentId),multiplier=node.incoming?sign(node.incoming.multiplier):'';edges+=`<line class="summary-edge" x1="${{q.x}}" y1="${{q.y}}" x2="${{p.x}}" y2="${{p.y}}"/><rect x="${{(q.x+p.x)/2-13}}" y="${{(q.y+p.y)/2-10}}" width="26" height="16" rx="4" fill="#fff"/><text class="summary-edge-label" x="${{(q.x+p.x)/2}}" y="${{(q.y+p.y)/2+2}}" text-anchor="middle">${{multiplier}}</text>`}}const color=node.status==='terminal'?'#149451':node.status==='killed'?'#ba2b31':'#17202a',detail=node.status==='terminal'?`terminal ${{sign(node.endpoint?.contribution??0)}}`:node.status;nodes+=`<g class="summary-node-target" data-node="${{node.id}}" role="button" tabindex="0" aria-label="Open ${{node.id}} in interactive branch pictures"><rect class="summary-hit" x="${{p.x-14}}" y="${{p.y-18}}" width="116" height="40" rx="8"/><circle cx="${{p.x}}" cy="${{p.y}}" r="9" fill="${{color}}"/><text class="summary-node-label" x="${{p.x+14}}" y="${{p.y-2}}">${{node.id}}</text><text class="summary-node-detail" x="${{p.x+14}}" y="${{p.y+11}}">coeff ${{sign(node.coefficient)}} · ${{detail}}</text></g>`}}return `<svg class="summary-svg" viewBox="0 0 ${{width}} ${{height}}" width="${{width}}" height="${{height}}" role="img" aria-label="Entire exact reduction tree">${{edges}}${{nodes}}</svg><p><b>Sum of terminal contributions = ${{sign(data.result.value)}}</b></p>`}}
function branchRoute(node){{const parts=[];let current=node;while(current&&current.parentId){{if(current.incoming)parts.push(`${{current.incoming.side}} ${{String(current.incoming.relation).replaceAll('_',' ')}} · ${{current.incoming.branch||''}} (${{sign(current.incoming.multiplier)}})`);current=byId.get(current.parentId)}}return parts.reverse().join(' → ')||'input'}}
function branchLedger(){{const leaves=data.nodes.filter(node=>node.children.length===0),rows=leaves.map(node=>{{const terminal=node.endpoint?.kind==='terminal',value=terminal?sign(node.endpoint.fllPairingValue):'0',contribution=sign(node.endpoint?.contribution??0),rule=terminal?'FLL terminal':'zero certificate';return `<tr><td><b>${{node.id}}</b></td><td>${{node.status}}</td><td>${{sign(node.coefficient)}}</td><td>${{rule}}</td><td>${{value}}</td><td>${{contribution}}</td><td class="muted">${{branchRoute(node)}}</td><td><button type="button" class="focus-node" data-node="${{node.id}}">Show branch pictures</button></td></tr>`}}).join('');return `<table><thead><tr><th>branch</th><th>status</th><th>coefficient</th><th>endpoint</th><th>pairing</th><th>contribution</th><th>certified route</th><th>pictures</th></tr></thead><tbody>${{rows}}</tbody></table><p><b>Sum of terminal contributions = ${{sign(data.result.value)}}</b></p>`}}
function showView(name){{document.getElementById('picture-view').hidden=name!=='picture';document.getElementById('ledger-view').hidden=name!=='ledger';document.getElementById('summary-view').hidden=name!=='summary'}}
function focusBranch(id){{history.push(new Set(expanded));let node=byId.get(id);while(node&&node.parentId){{const parent=byId.get(node.parentId);expanded.add(parent.id);node=parent}}showView('picture');renderPictures();requestAnimationFrame(()=>document.getElementById('node-card-'+id)?.scrollIntoView({{behavior:'smooth',block:'center'}}))}}
function showLedger(){{showView('ledger');document.getElementById('branch-ledger').innerHTML=branchLedger();document.querySelectorAll('button.focus-node').forEach(button=>button.onclick=()=>focusBranch(button.dataset.node))}}
function bindSummaryNodes(){{document.querySelectorAll('.summary-node-target').forEach(target=>{{const open=()=>focusBranch(target.dataset.node);target.onclick=open;target.onkeydown=event=>{{if(event.key==='Enter'||event.key===' '){{event.preventDefault();open()}}}}}})}}
function showSummary(){{showView('summary');document.getElementById('summary-tree').innerHTML=summarySvg();bindSummaryNodes()}}
document.getElementById('picture-button').onclick=()=>showView('picture');document.getElementById('ledger-button').onclick=showLedger;document.getElementById('summary-button').onclick=showSummary;
document.getElementById('back').onclick=undoLast;
document.getElementById('automatic').onchange=e=>{{automatic=e.target.checked;history=[];expanded=automatic?new Set(active):new Set();showView('picture');renderPictures()}};document.getElementById('reset').onclick=()=>{{automatic=false;expanded=new Set();history=[];document.getElementById('automatic').checked=false;showView('picture');renderPictures()}};
document.getElementById('demo').onchange=e=>{{const option=e.target.selectedOptions[0];if(!option||!option.dataset.w)return;document.getElementById('w').value=option.dataset.w;document.getElementById('x').value=option.dataset.x}};renderPictures();
async function refreshPresentation(side){{const lower=side.toLowerCase(),input=document.getElementById(lower),box=document.getElementById(lower+'-presentation-box'),select=document.getElementById(lower+'-presentation'),status=document.getElementById(lower+'-presentation-status'),value=input.value.trim();select.disabled=true;select.required=false;if(!value){{box.hidden=true;return}}try{{const response=await fetch('/presentations?side='+side+'&value='+encodeURIComponent(value),{{cache:'no-store'}}),payload=await response.json();if(!response.ok||payload.error)throw new Error(payload.error||'Could not load presentations');if(!payload.requiresSelection){{box.hidden=true;select.innerHTML='';status.textContent='';return}}box.hidden=false;select.innerHTML='<option value="">Select an exact presentation...</option>';for(const item of payload.options){{const option=document.createElement('option');option.value=item.value;option.textContent=item.label;select.appendChild(option)}}const remembered=select.dataset.selected||payload.selected||'';if(remembered&&[...select.options].some(option=>option.value===remembered))select.value=remembered;select.disabled=false;select.required=true;status.textContent=payload.options.length+' presentation-dependent choices. The catalogue presentation is not chosen automatically.'}}catch(error){{box.hidden=false;select.innerHTML='<option value="">Presentations unavailable</option>';status.textContent=error.message}}}}
function debounce(fn,delay){{let timer;return()=>{{clearTimeout(timer);timer=setTimeout(fn,delay)}}}}for(const side of ['W','X']){{const lower=side.toLowerCase(),input=document.getElementById(lower),select=document.getElementById(lower+'-presentation'),delayed=debounce(()=>{{select.dataset.selected='';refreshPresentation(side)}},300);input.addEventListener('input',delayed);input.addEventListener('change',()=>{{select.dataset.selected='';refreshPresentation(side)}})}}document.getElementById('demo').addEventListener('change',()=>{{for(const side of ['W','X']){{const select=document.getElementById(side.toLowerCase()+'-presentation');select.dataset.selected='';refreshPresentation(side)}}}});refreshPresentation('W');refreshPresentation('X');
const initialView={json.dumps(initial_view)};if(initialView==='summary')showSummary();else if(initialView==='ledger')showLedger();else showView('picture');
</script></body></html>"""


def default_pair() -> tuple[Path, Path]:
    _, _, w_name, x_name = DEMO_PAIRS[0]
    return resolve_graph(w_name), resolve_graph(x_name)


def error_page(message: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Exact Pairing Tree</title></head>
<body style="font-family:Arial;padding:30px"><h1>Could not run exact checker</h1><p>{html.escape(message)}</p>
<p><a href="{GRAPH_DATA_DOWNLOAD_URL}">Download 4x4_All_graph_data_260815.zip</a>, extract it anywhere, and restart with:</p>
<pre>python3 exact_checker_tree_app_20260826.py --project-root "/path/to/folder-containing-4x4_All_graph_data"</pre>
<p><a href="/">Return to the example</a></p></body></html>"""


class AppHandler(BaseHTTPRequestHandler):
    def send_html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: Mapping[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = {key: values[-1] for key, values in urllib.parse.parse_qs(parsed.query).items()}
        if parsed.path == "/health":
            self.send_html('{"status":"ready","app":"wrench_pairing_explorer"}')
            return
        if parsed.path == "/presentations":
            try:
                self.send_json(benzene_presentation_options(params.get("value", "")))
            except Exception as exc:  # noqa: BLE001 - return the exact resolution failure.
                self.send_json({"error": str(exc)}, status=400)
            return
        if parsed.path not in {"/", "/run", "/branch", "/tree", "/wrench"}:
            self.send_html(error_page("Page not found."), status=404)
            return
        try:
            initial_view = params.get(
                "view",
                "summary" if parsed.path in {"/", "/branch", "/tree"} else "picture",
            )
            if parsed.path == "/run":
                w_value = params.get("w", "")
                x_value = params.get("x", "")
                w_presentation = params.get("w_presentation", "")
                x_presentation = params.get("x_presentation", "")
                w_path = resolve_selected_graph(w_value, w_presentation, "W")
                x_path = resolve_selected_graph(x_value, x_presentation, "X")
            else:
                w_path, x_path = default_pair()
                w_value, x_value = w_path.name, x_path.name
                w_presentation = x_presentation = ""
            tree = compute_tree(str(w_path), str(x_path))
            self.send_html(
                page(
                    tree,
                    w_value,
                    x_value,
                    w_presentation,
                    x_presentation,
                    initial_view,
                )
            )
        except Exception as exc:  # noqa: BLE001 - the mathematical failure is shown verbatim.
            self.send_html(error_page(str(exc)), status=500)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[exact-tree] {self.address_string()} {fmt % args}")


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help=(
            "Extracted 4x4_All_graph_data folder, or the folder containing it. "
            "Defaults to PROBLEM3_ROOT or the folder containing this app."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    configure_project_root(args.project_root)
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Pairing Explorer running at http://{args.host}:{args.port}/branch")
    print("Local tagging convention: GPPSS. Terminal conversion only: FLL.")
    print("Graph data loaded.")
    server.serve_forever()


if __name__ == "__main__":
    main()
