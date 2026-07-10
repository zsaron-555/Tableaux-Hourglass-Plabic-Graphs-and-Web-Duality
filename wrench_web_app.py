#!/usr/bin/env python3
"""Local interactive webpage for wrench/fork/coloring pairing computations."""

from __future__ import annotations

import argparse
import ast
import csv
import html
import json
import math
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import Wrench_or_Skein as wrench


APP_DIR = Path(__file__).resolve().parent
X_FOLDER_NAME = "hourglass_disk_4x4_promotion_reps_graph_data"
W_FOLDER_NAME = "hourglass_disk_4x4_transpose_words_graph_data"
ALL_FOLDER_NAME = "hourglass_disk_4x4_all_graph_data"
ALL_FOLDER_ALIASES = (ALL_FOLDER_NAME, "4x4_All_graph_data")
SURVIVOR_CSV_NAME = "lemma46_survivors.csv"
PROMOTION_TABLE_PATH = Path("hourglass_disk_4x4_promotion_reps") / "promotion_orbits_4x4.tsv"
PROJECT_ROOT = Path(os.environ.get("PROBLEM3_ROOT", APP_DIR)).expanduser().resolve()
X_DIR = PROJECT_ROOT / X_FOLDER_NAME
W_DIR = PROJECT_ROOT / W_FOLDER_NAME
ALL_DIR = PROJECT_ROOT / ALL_FOLDER_NAME
SURVIVOR_CSV = PROJECT_ROOT / SURVIVOR_CSV_NAME
PROMOTION_TABLE = PROJECT_ROOT / PROMOTION_TABLE_PATH
_SURVIVOR_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None
_PROMOTION_ORBIT_CACHE: Optional[Dict[int, List[str]]] = None

DEFAULT_X = "0447_1112122334344234.json"
DEFAULT_W = "0447_1231423121323444.json"
DEFAULT_REP = "0447"

COLORS = {
    1: "#df454f",
    2: "#2586d8",
    3: "#23a267",
    4: "#9958be",
}


def locate_project_root(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    if any((root / name).exists() for name in ALL_FOLDER_ALIASES) or (
        (root / X_FOLDER_NAME).exists() and (root / W_FOLDER_NAME).exists()
    ):
        return root

    for x_dir in root.rglob(X_FOLDER_NAME):
        candidate = x_dir.parent
        if (candidate / W_FOLDER_NAME).exists():
            return candidate
    for name in ALL_FOLDER_ALIASES:
        for all_dir in root.rglob(name):
            return all_dir.parent

    return root


def configure_project_root(project_root: str | Path) -> None:
    global PROJECT_ROOT, X_DIR, W_DIR, ALL_DIR, SURVIVOR_CSV, PROMOTION_TABLE, _SURVIVOR_CACHE, _PROMOTION_ORBIT_CACHE
    PROJECT_ROOT = locate_project_root(project_root)
    X_DIR = PROJECT_ROOT / X_FOLDER_NAME
    W_DIR = PROJECT_ROOT / W_FOLDER_NAME
    ALL_DIR = next((PROJECT_ROOT / name for name in ALL_FOLDER_ALIASES if (PROJECT_ROOT / name).exists()), PROJECT_ROOT / ALL_FOLDER_NAME)
    SURVIVOR_CSV = PROJECT_ROOT / SURVIVOR_CSV_NAME
    PROMOTION_TABLE = PROJECT_ROOT / PROMOTION_TABLE_PATH
    _SURVIVOR_CACHE = None
    _PROMOTION_ORBIT_CACHE = None


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_graph(value: str, side: str, *, prefer_all: bool = True) -> Path:
    """Resolve an index, word, filename, or path into a graph JSON path."""
    value = value.strip()
    if not value:
        value = DEFAULT_X if side == "X" else DEFAULT_W

    candidate = Path(value).expanduser()
    if candidate.exists():
        return candidate

    preferred_dir = X_DIR if side == "X" else W_DIR
    fallback_dir = W_DIR if side == "X" else X_DIR
    search_dirs = []
    if prefer_all:
        search_dirs.append(ALL_DIR)
    search_dirs.append(preferred_dir)
    if fallback_dir != preferred_dir:
        search_dirs.append(fallback_dir)
    if not any(path.exists() for path in search_dirs):
        raise FileNotFoundError(
            f"Could not find graph-data folders under {PROJECT_ROOT}. "
            f"Expected {ALL_FOLDER_NAME} / 4x4_All_graph_data, or the representative folders. "
            "Put the JSON folders next to wrench_web_app.py, or start the app with "
            "--project-root /path/to/the/folder-that-contains-the-json-folders."
        )

    for graph_dir in search_dirs:
        if not graph_dir.exists():
            continue
        if value.isdigit() and len(value) <= 5:
            idx = int(value)
            matches = sorted(graph_dir.glob(f"{idx:05d}_*.json"))
            if not matches:
                matches = sorted(graph_dir.glob(f"{idx:04d}_*.json"))
            if matches:
                return matches[0]

        exact = graph_dir / value
        if exact.exists():
            return exact

        matches = sorted(graph_dir.glob(f"*_{value}.json"))
        if matches:
            return matches[0]

    raise FileNotFoundError(f"Could not find {side} graph for input: {value}")


def graph_index(path: Path) -> int:
    prefix = path.name.split("_", 1)[0]
    if prefix.isdigit():
        return int(prefix)
    data = load_json(path)
    metadata = data.get("metadata", {})
    if "source_index" in metadata:
        return int(metadata["source_index"])
    raise ValueError(f"Could not determine representative index from {path.name}")


def graph_word(path: Path) -> str:
    stem = path.stem
    if "_" in stem:
        return stem.split("_", 1)[1]
    data = load_json(path)
    return str(data.get("metadata", {}).get("word", stem))


def promotion_orbit_words_by_index() -> Dict[int, List[str]]:
    """Return promotion orbit words keyed by the 1-based orbit index in the survivor CSV."""
    global _PROMOTION_ORBIT_CACHE
    if _PROMOTION_ORBIT_CACHE is not None:
        return _PROMOTION_ORBIT_CACHE

    orbits: Dict[int, List[str]] = {}
    if PROMOTION_TABLE.exists():
        with PROMOTION_TABLE.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                idx = int(row.get("orbit_index") or row["index"])
                words = [w.strip() for w in row["orbit_words"].split(",") if w.strip()]
                orbits[idx] = words
    _PROMOTION_ORBIT_CACHE = orbits
    return orbits


def parse_survivor_words(row: Dict[str, str]) -> List[str]:
    raw_words = row.get("survivor_words", "").strip()
    if raw_words:
        try:
            return [str(word) for word in ast.literal_eval(raw_words)]
        except (SyntaxError, ValueError):
            return []

    raw_pairs = row.get("survivor_pairs", "").strip()
    if not raw_pairs:
        return []
    orbits = promotion_orbit_words_by_index()
    if not orbits:
        return []

    words = []
    try:
        pairs = ast.literal_eval(raw_pairs)
    except (SyntaxError, ValueError):
        return []
    for orbit_idx, position in pairs:
        orbit_words = orbits.get(int(orbit_idx), [])
        if not orbit_words:
            continue
        pos = int(position)
        if 0 <= pos < len(orbit_words):
            words.append(orbit_words[pos])
        else:
            words.append(orbit_words[pos % len(orbit_words)])
    return words


def load_survivor_index() -> Dict[str, Any]:
    global _SURVIVOR_CACHE
    if not SURVIVOR_CSV.exists():
        return {"by_idx": {}, "by_word": {}, "mtime": None}

    mtime = SURVIVOR_CSV.stat().st_mtime
    if _SURVIVOR_CACHE is not None and _SURVIVOR_CACHE[0] == mtime:
        return _SURVIVOR_CACHE[1]

    by_idx: Dict[int, Dict[str, Any]] = {}
    by_word: Dict[str, Dict[str, Any]] = {}
    with SURVIVOR_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("w_idx") or not row.get("w_word"):
                continue
            entry = {
                "w_idx": int(row["w_idx"]),
                "w_word": row["w_word"].strip(),
                "n_survivor_pairs": int(row.get("n_survivor_pairs") or 0),
                "n_survivor_orbits": int(row.get("n_survivor_orbits") or 0),
                "forks_W": row.get("forks_W", ""),
                "survivor_words": parse_survivor_words(row),
            }
            by_idx[entry["w_idx"]] = entry
            by_word[entry["w_word"]] = entry

    data = {"by_idx": by_idx, "by_word": by_word, "mtime": mtime}
    _SURVIVOR_CACHE = (mtime, data)
    return data


def survivor_entry_for_w(value: str) -> Optional[Dict[str, Any]]:
    value = value.strip()
    survivors = load_survivor_index()
    if not value:
        value = DEFAULT_W
    if value in survivors["by_word"]:
        return survivors["by_word"][value]

    try:
        path = resolve_graph(value, "W")
    except Exception:  # noqa: BLE001 - form hints should not break the page.
        if value.isdigit():
            return survivors["by_idx"].get(int(value))
        return None
    word = graph_word(path)
    entry = survivors["by_word"].get(word)
    if entry:
        return entry

    # Numeric manual inputs refer to the all-graph JSON index when that folder
    # is present. Only fall back to CSV row index if graph resolution did not
    # identify a survivor row for the resolved word.
    if value.isdigit() and not ALL_DIR.exists():
        return survivors["by_idx"].get(int(value))
    return None


def selected_survivor_for_params(params: Dict[str, str]) -> str:
    value = params.get("survivor_x", "").strip()
    if not value:
        return ""
    entry = survivor_entry_for_w(params.get("w", ""))
    if entry and value in set(entry.get("survivor_words", [])):
        return value
    return ""


def survivor_selector_html(params: Dict[str, str]) -> str:
    entry = survivor_entry_for_w(params.get("w", ""))
    if not entry:
        return ""

    survivor_words = entry.get("survivor_words", [])
    if not survivor_words:
        return f"""
        <details class="survivor-panel" open>
          <summary>Lemma 4.6 survivors for W = {html.escape(entry['w_word'])}</summary>
          <p class="muted">This W has survivor data in {html.escape(SURVIVOR_CSV_NAME)}, but this copy of the project does not contain the orbit table needed to expand the survivor-pair list into words.</p>
        </details>
        """

    selected = selected_survivor_for_params(params)
    options = [
        '<option value="">Choose a survivor X word</option>',
    ]
    for idx, word in enumerate(survivor_words, start=1):
        choice = " selected" if word == selected else ""
        options.append(f'<option value="{html.escape(word)}"{choice}>{idx:04d} {html.escape(word)}</option>')

    selected_note = (
        f'<p class="muted">Selected survivor overrides the X field: <span class="word">{html.escape(selected)}</span></p>'
        if selected
        else '<p class="muted">Choose one survivor, then run proof search. The selected survivor will be used as X.</p>'
    )
    return f"""
    <details class="survivor-panel" open>
      <summary>Lemma 4.6 survivors for W = {html.escape(entry['w_word'])}</summary>
      <div class="survivor-grid">
        <label>Survivor X word
          <select name="survivor_x" id="survivor-x-select">
            {''.join(options)}
          </select>
        </label>
        <div class="survivor-meta">
          <p><strong>{len(survivor_words)}</strong> selectable survivors</p>
          <p><strong>{entry['n_survivor_pairs']}</strong> survivor pairs, <strong>{entry['n_survivor_orbits']}</strong> survivor orbits</p>
          <p><strong>Forks of W:</strong> {html.escape(entry.get('forks_W', ''))}</p>
          {selected_note}
        </div>
      </div>
    </details>
    """


def resolve_transpose_for_original(x_path: Path) -> Path:
    idx = graph_index(x_path)
    matches = sorted(W_DIR.glob(f"{idx:04d}_*.json"))
    if not matches:
        raise FileNotFoundError(f"Could not find transpose graph with representative index {idx:04d}")
    return matches[0]


def resolve_pair(params: Dict[str, str]) -> Tuple[Path, Path, str]:
    """Resolve the requested pairing.

    Normal mode: explicit W and X inputs are resolved independently.  The old
    representative-transpose shortcut is still available with use_transpose=1.
    """
    use_transpose = params.get("use_transpose") == "1"
    w_value = params.get("w", "").strip()
    survivor_value = selected_survivor_for_params(params)
    x_value = survivor_value or params.get("x", "").strip()
    has_both_manual_inputs = bool(w_value and x_value)
    if (use_transpose and not has_both_manual_inputs) or (
        not has_both_manual_inputs and "rep" in params and not (w_value or x_value)
    ):
        rep = params.get("rep", DEFAULT_REP)
        x_path = resolve_graph(rep, "X", prefer_all=False)
        w_path = resolve_transpose_for_original(x_path)
        return x_path, w_path, "transpose"

    w_path = resolve_graph(w_value or DEFAULT_W, "W")
    x_path = resolve_graph(x_value or DEFAULT_X, "X")
    mode = "lemma46_survivor" if survivor_value else "manual"
    return x_path, w_path, mode


def node_maps(graph: Dict[str, Any]):
    nodes = {int(n["id"]): n for n in graph["nodes"]}
    xy = {i: (float(n["x"]), float(n["y"])) for i, n in nodes.items()}
    boundary = {int(b["node"]): int(b["label"]) for b in graph["boundary"]}
    label_to_node = {label: node for node, label in boundary.items()}
    return nodes, xy, boundary, label_to_node


def edge_set(adj: wrench.Adjacency) -> set[Tuple[int, int]]:
    return {tuple(sorted((u, v))) for u, ns in adj.items() for v in wrench.neighbor_list(ns)}


def transform(x: float, y: float, size: int = 330) -> Tuple[float, float]:
    scale = size * 0.39
    cx = cy = size / 2
    return cx + scale * x, cy - scale * y


def svg_line(p1, p2, color="#111", width=2.0, klass="") -> str:
    return (
        f'<line class="{klass}" x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" '
        f'x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" stroke="{color}" '
        f'stroke-width="{width}" stroke-linecap="round" />'
    )


def cubic_path(points: List[Tuple[float, float]]) -> str:
    if not points:
        return ""
    start, c1, c2, end = points
    return (
        f"M {start[0]:.2f},{start[1]:.2f} "
        f"C {c1[0]:.2f},{c1[1]:.2f} {c2[0]:.2f},{c2[1]:.2f} {end[0]:.2f},{end[1]:.2f}"
    )


def hourglass_paths(a: int, b: int, xy: Dict[int, Tuple[float, float]], size: int = 330):
    x1, y1 = xy[a]
    x2, y2 = xy[b]
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return []
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    amp = min(0.10, length * 0.42)
    inset = 0.27 * length
    p0 = (x1, y1)
    p3 = (x2, y2)
    c1a = (x1 + ux * inset + px * amp, y1 + uy * inset + py * amp)
    c2a = (x2 - ux * inset - px * amp, y2 - uy * inset - py * amp)
    c1b = (x1 + ux * inset - px * amp, y1 + uy * inset - py * amp)
    c2b = (x2 - ux * inset + px * amp, y2 - uy * inset + py * amp)
    return [
        [transform(*p, size=size) for p in (p0, c1a, c2a, p3)],
        [transform(*p, size=size) for p in (p0, c1b, c2b, p3)],
    ]


def draw_web_svg(
    title: str,
    graph: Dict[str, Any],
    adj: wrench.Adjacency,
    remaining_hourglasses: List[wrench.Hourglass],
    *,
    selected_hg: Optional[Tuple[int, int]] = None,
    highlight_fork: Optional[List[int]] = None,
    edge_colors: Optional[Dict[Tuple[int, int], str]] = None,
    node_ring_colors: Optional[Dict[int, str]] = None,
    subtitle: str = "",
    size: int = 330,
) -> str:
    nodes, xy, boundary, label_to_node = node_maps(graph)
    edge_colors = edge_colors or {}
    node_ring_colors = node_ring_colors or {}
    selected_key = tuple(sorted(selected_hg)) if selected_hg else None

    highlight_nodes = dict(node_ring_colors)
    if highlight_fork:
        for label in highlight_fork:
            if label in label_to_node:
                highlight_nodes[label_to_node[label]] = "#149451"
        want = set(highlight_fork)
        for node, ns in adj.items():
            if node in boundary:
                continue
            labels = {boundary[v] for v in wrench.neighbor_list(ns) if v in boundary}
            if want.issubset(labels):
                highlight_nodes[node] = "#149451"

    out = [
        f'<div class="web-card"><div class="web-title">{html.escape(title)}</div>',
        f'<div class="web-subtitle">{html.escape(subtitle)}</div>' if subtitle else "",
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">',
        f'<circle cx="{size/2}" cy="{size/2}" r="{size*0.39}" fill="none" stroke="#111" stroke-width="2" />',
    ]

    for u, v in sorted(edge_set(adj)):
        if u not in xy or v not in xy:
            continue
        color = edge_colors.get(tuple(sorted((u, v))), "#111")
        width = 4 if tuple(sorted((u, v))) in edge_colors else 2
        out.append(svg_line(transform(*xy[u], size=size), transform(*xy[v], size=size), color, width))

    for hg in remaining_hourglasses:
        w, b = int(hg["white"]), int(hg["black"])
        if w not in adj or b not in adj:
            continue
        key = tuple(sorted((w, b)))
        color = "#cf2f2f" if key == selected_key else "#111"
        width = 4 if key == selected_key else 2
        for path_points in hourglass_paths(w, b, xy, size=size):
            out.append(
                f'<path d="{cubic_path(path_points)}" fill="none" stroke="{color}" '
                f'stroke-width="{width}" stroke-linecap="round" />'
            )

    for node in sorted(adj):
        if node not in xy:
            continue
        x, y = transform(*xy[node], size=size)
        if node in boundary:
            out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="6.5" fill="#000" />')
            lx, ly = transform(xy[node][0] * 1.15, xy[node][1] * 1.15, size=size)
            out.append(
                f'<text x="{lx:.2f}" y="{ly:.2f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="12">{boundary[node]}</text>'
            )
        else:
            fill = "#000" if nodes[node].get("color") == "black" else "#fff"
            out.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="6.5" fill="{fill}" '
                f'stroke="#000" stroke-width="2" />'
            )
        if node in highlight_nodes:
            out.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="13" fill="none" '
                f'stroke="{highlight_nodes[node]}" stroke-width="3" />'
            )

    out.extend(["</svg>", "</div>"])
    return "\n".join(out)


def one_coloring(
    adj: wrench.Adjacency,
    boundary_labels: wrench.BoundaryLabels,
    boundary_color_by_label: Dict[int, int],
    *,
    r: int = 4,
) -> Optional[Dict[Tuple[int, int], int]]:
    edges = list(wrench.get_edge_tuple(adj))
    incident = {n: [] for n in adj}
    fixed = {}
    for idx, (u, v) in enumerate(edges):
        incident[u].append(idx)
        incident[v].append(idx)
        if u in boundary_labels or v in boundary_labels:
            bnode = u if u in boundary_labels else v
            label = boundary_labels[bnode]
            fixed[idx] = boundary_color_by_label[label]

    colors = [0] * len(edges)
    for idx, color in fixed.items():
        colors[idx] = color

    internal = [n for n in adj if n not in boundary_labels]
    remaining = [i for i in range(len(edges)) if i not in fixed]
    remaining.sort(key=lambda i: -sum(1 for endpoint in edges[i] if endpoint not in boundary_labels))

    def possible(vertex: int) -> bool:
        seen = set()
        unknown = 0
        for idx in incident[vertex]:
            color = colors[idx]
            if color == 0:
                unknown += 1
            elif color in seen:
                return False
            else:
                seen.add(color)
        return len(seen) + unknown == r

    def complete(vertex: int) -> bool:
        return {colors[idx] for idx in incident[vertex]} == set(range(1, r + 1))

    def backtrack(pos: int) -> bool:
        if pos == len(remaining):
            return all(complete(v) for v in internal)
        edge_idx = remaining[pos]
        endpoints = [n for n in edges[edge_idx] if n not in boundary_labels]
        for color in range(1, r + 1):
            colors[edge_idx] = color
            if all(possible(v) for v in endpoints) and backtrack(pos + 1):
                return True
            colors[edge_idx] = 0
        return False

    if not all(possible(v) for v in internal):
        return None
    if not backtrack(0):
        return None
    return {edges[i]: colors[i] for i in range(len(edges))}


def reconstruct_run(x_path: Path, w_path: Path, proof: Dict[str, Any]):
    x_graph = load_json(x_path)
    w_graph = load_json(w_path)
    x_adj, x_bounds, x_hgs = wrench.parse_web(x_path)
    w_adj, w_bounds, w_hgs = wrench.parse_web(w_path)
    x_hgs = wrench.sort_hourglasses_by_boundary_distance(x_adj, x_bounds, x_hgs)
    w_hgs = wrench.sort_hourglasses_by_boundary_distance(w_adj, w_bounds, w_hgs)

    def move_key(move: Dict[str, Any]) -> Tuple[str, Tuple[int, int], str]:
        return (
            str(move.get("side", "X")),
            tuple(sorted(int(x) for x in move.get("hourglass", []))),
            str(move.get("smoothing", "")),
        )

    def same_hourglass(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        return move_key(a)[:2] == move_key(b)[:2]

    def history_matches(history: List[Dict[str, Any]], prefix: List[Dict[str, Any]]) -> bool:
        if len(history) < len(prefix):
            return False
        return [move_key(m) for m in history[: len(prefix)]] == [move_key(m) for m in prefix]

    def opposite_smoothing(smoothing: str) -> str:
        return "parallel" if smoothing == "crossing" else "crossing"

    def sibling_discharge(prefix: List[Dict[str, Any]], continue_move: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for discharged in proof.get("discharged_terms", []):
            history = discharged.get("history", [])
            if len(history) != len(prefix) + 1:
                continue
            if not history_matches(history, prefix):
                continue
            move = history[-1]
            if same_hourglass(move, continue_move) and move.get("smoothing") != continue_move.get("smoothing"):
                return discharged
        return None

    if proof.get("active_terms"):
        active_history = proof["active_terms"][0].get("history", [])
    else:
        discharged_terms = proof.get("discharged_terms", [])
        active_history = max((d.get("history", []) for d in discharged_terms), key=len, default=[])

    steps = []
    current_x, current_w = x_adj, w_adj
    current_xh, current_wh = x_hgs, w_hgs
    for idx, continue_move in enumerate(active_history):
        side = continue_move.get("side", "X")
        selected = tuple(sorted(int(x) for x in continue_move["hourglass"]))
        hgs = current_xh if side == "X" else current_wh
        hg = next(
            h
            for h in hgs
            if tuple(sorted((int(h["white"]), int(h["black"])))) == selected
        )
        killed = sibling_discharge(active_history[:idx], continue_move) or {
            "common_forks": [],
            "coeff": "",
            "history": [],
            "reason": "not_found_on_display_path",
        }
        killed_move = (
            killed.get("history", [])[-1]
            if killed.get("history")
            else {"smoothing": opposite_smoothing(continue_move["smoothing"])}
        )

        def branch(smoothing: str):
            if side == "X":
                bx = wrench.smooth_one_hourglass(current_x, hg, smoothing)
                bw = current_w
                bxh = wrench.remaining_after_move(current_xh, hg)
                bwh = current_wh
                new_x = edge_set(bx) - edge_set(current_x)
                new_w = set()
            else:
                bx = current_x
                bw = wrench.smooth_one_hourglass(current_w, hg, smoothing)
                bxh = current_xh
                bwh = wrench.remaining_after_move(current_wh, hg)
                new_x = set()
                new_w = edge_set(bw) - edge_set(current_w)
            return bx, bw, bxh, bwh, new_x, new_w

        killed_x, killed_w, killed_xh, killed_wh, killed_new_x, killed_new_w = branch(killed_move["smoothing"])
        cont_x, cont_w, cont_xh, cont_wh, cont_new_x, cont_new_w = branch(continue_move["smoothing"])
        steps.append(
            {
                "side": side,
                "selected": selected,
                "current_x": current_x,
                "current_w": current_w,
                "current_xh": current_xh,
                "current_wh": current_wh,
                "killed": killed,
                "killed_smoothing": killed_move["smoothing"],
                "continue_smoothing": continue_move["smoothing"],
                "killed_x": killed_x,
                "killed_w": killed_w,
                "killed_xh": killed_xh,
                "killed_wh": killed_wh,
                "killed_new_x": killed_new_x,
                "killed_new_w": killed_new_w,
                "continue_x": cont_x,
                "continue_w": cont_w,
                "continue_xh": cont_xh,
                "continue_wh": cont_wh,
                "continue_new_x": cont_new_x,
                "continue_new_w": cont_new_w,
            }
        )
        current_x, current_w, current_xh, current_wh = cont_x, cont_w, cont_xh, cont_wh

    return x_graph, w_graph, x_bounds, w_bounds, steps, current_x, current_w, current_xh, current_wh


def run_pair(params: Dict[str, str]) -> str:
    x_path, w_path, pair_mode = resolve_pair(params)
    max_steps_raw = params.get("max_steps", "").strip()
    max_steps = None if max_steps_raw in {"", "auto", "8"} else int(max_steps_raw)
    beam_width = int(params.get("beam_width", "120") or "120")
    allow_w = params.get("allow_w", "1") == "1"
    show_steps = params.get("show_steps") == "1"

    x_adj, x_bounds, x_hgs = wrench.parse_web(x_path)
    w_adj, w_bounds, w_hgs = wrench.parse_web(w_path)
    x_hgs = wrench.sort_hourglasses_by_boundary_distance(x_adj, x_bounds, x_hgs)
    w_hgs = wrench.sort_hourglasses_by_boundary_distance(w_adj, w_bounds, w_hgs)
    proof = wrench.prove_pair_zero_allowing_w_wrench(
        x_adj,
        x_bounds,
        x_hgs,
        w_adj,
        w_bounds,
        w_hgs,
        allow_w_wrench=allow_w,
        beam_width=beam_width,
        max_steps=max_steps,
    )
    x_graph, w_graph, x_bounds, w_bounds, steps, final_x, final_w, final_xh, final_wh = reconstruct_run(
        x_path, w_path, proof
    )
    x_word = graph_word(x_path)
    w_word = graph_word(w_path)
    x_index = graph_index(x_path)
    w_index = graph_index(w_path)

    step_html = []
    if show_steps:
        for idx, step in enumerate(steps, start=1):
            killed_forks = step["killed"].get("common_forks", [])
            fork = killed_forks[0] if killed_forks else None
            selected = step["selected"]
            step_html.append(
                f"""
                <section class="step">
                  <div class="step-head">
                    <div><strong>Step {idx}</strong>: expand {step['side']} hourglass {list(selected)}</div>
                    <div class="muted">{html.escape(step['continue_smoothing'])} branch continues; {html.escape(step['killed_smoothing'])} branch is killed</div>
                  </div>
                  <div class="grid four">
                    {draw_web_svg('Current W', w_graph, step['current_w'], step['current_wh'], selected_hg=selected if step['side']=='W' else None)}
                    {draw_web_svg('Current X', x_graph, step['current_x'], step['current_xh'], selected_hg=selected if step['side']=='X' else None)}
                    <div class="pair-card">
                      <div class="pair-title">Killed branch by fork lemma</div>
                      <div class="pair-note">fork(s): {html.escape(str(killed_forks))}, coeff {html.escape(str(step['killed'].get('coeff')))}</div>
                      <div class="mini-pair">
                        {draw_web_svg('W', w_graph, step['killed_w'], step['killed_wh'], highlight_fork=fork, edge_colors={e:'#2586d8' for e in step['killed_new_w']}, size=250)}
                        {draw_web_svg('X', x_graph, step['killed_x'], step['killed_xh'], highlight_fork=fork, edge_colors={e:'#2586d8' for e in step['killed_new_x']}, size=250)}
                      </div>
                    </div>
                    <div class="pair-card">
                      <div class="pair-title">Continuing branch</div>
                      <div class="pair-note">new smoothing edges are blue</div>
                      <div class="mini-pair">
                        {draw_web_svg('W', w_graph, step['continue_w'], step['continue_wh'], edge_colors={e:'#2586d8' for e in step['continue_new_w']}, size=250)}
                        {draw_web_svg('X', x_graph, step['continue_x'], step['continue_xh'], edge_colors={e:'#2586d8' for e in step['continue_new_x']}, size=250)}
                      </div>
                    </div>
                  </div>
                </section>
                """
            )
    else:
        rows = []
        for idx, step in enumerate(steps, start=1):
            killed_forks = step["killed"].get("common_forks", [])
            rows.append(
                "<tr>"
                f"<td>{idx}</td>"
                f"<td>{html.escape(step['side'])}</td>"
                f"<td>{html.escape(str(list(step['selected'])))}</td>"
                f"<td>{html.escape(step['continue_smoothing'])}</td>"
                f"<td>{html.escape(step['killed_smoothing'])}</td>"
                f"<td>{html.escape(str(killed_forks))}</td>"
                "</tr>"
            )
        step_html.append(
            f"""
            <section class="step">
              <div class="step-head">
                <div><strong>Wrench Move Summary</strong></div>
                <div class="muted">Full step pictures are off for faster loading. Turn them on in the form if needed.</div>
              </div>
              <table class="step-table">
                <thead><tr><th>#</th><th>side</th><th>hourglass</th><th>continuing branch</th><th>killed branch</th><th>fork(s)</th></tr></thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
            </section>
            """
        )

    coloring_html = render_coloring_section(x_graph, w_graph, x_bounds, w_bounds, final_x, final_w, proof)
    return page_shell(
        params,
        f"""
        <section class="summary">
          <div>
            <h2>Pairing Result</h2>
            <p><strong>Mode:</strong> {html.escape(pair_mode)}</p>
            <p><strong>W:</strong> <span class="muted">{w_index:04d}</span> <span class="word">{html.escape(w_word)}</span></p>
            <p><strong>X:</strong> <span class="muted">{x_index:04d}</span> <span class="word">{html.escape(x_word)}</span></p>
          </div>
          <div class="result-pill">{html.escape(proof['status'])}</div>
          <div class="metric"><span>Fork-killed branches</span><strong>{proof['discharged_term_count']}</strong></div>
          <div class="metric"><span>Active branches left</span><strong>{proof['active_term_count']}</strong></div>
          <div class="metric"><span>Final pairing value</span><strong>{proof.get('final_pairing_value')}</strong></div>
        </section>
        <section class="toc">
          <h2>What the page is showing</h2>
          <p>Each wrench move replaces the active pair by two branches. Branches with a common fork are killed by the fork lemma. If anything survives, the app tries the BCGMMW coloring count.</p>
        </section>
        {''.join(step_html)}
        {coloring_html}
        """,
    )


def render_coloring_section(
    x_graph,
    w_graph,
    x_bounds,
    w_bounds,
    final_x,
    final_w,
    proof,
) -> str:
    evaluations = proof.get("coloring_evaluations", [])
    if not evaluations:
        return ""
    ev = evaluations[0]
    if ev.get("status") != "computed":
        return f'<section class="step"><h2>Coloring fallback</h2><p>{html.escape(ev.get("reason", "not computed"))}</p></section>'

    source = ev["source_side"]
    factors = ev["plucker_factors"]
    condition = {int(k): int(v) for k, v in ev["boundary_color_by_label"].items()}
    w_edge_colors: Dict[Tuple[int, int], str] = {}
    x_edge_colors: Dict[Tuple[int, int], str] = {}
    w_node_ring_colors: Dict[int, str] = {}
    x_node_ring_colors: Dict[int, str] = {}
    if source == "X":
        coloring = one_coloring(final_w, w_bounds, condition) or {}
        w_edge_colors = {edge: COLORS[color] for edge, color in coloring.items()}
        _, _, _, x_label_to_node = node_maps(x_graph)
        for label, color in condition.items():
            if label in x_label_to_node:
                x_node_ring_colors[x_label_to_node[label]] = COLORS[color]
        w_subtitle = f"colored from X boundary condition; count = {ev['coloring_count']}"
        x_subtitle = "Plucker-product side; boundary colors come from the factors"
    else:
        coloring = one_coloring(final_x, x_bounds, condition) or {}
        x_edge_colors = {edge: COLORS[color] for edge, color in coloring.items()}
        _, _, _, w_label_to_node = node_maps(w_graph)
        for label, color in condition.items():
            if label in w_label_to_node:
                w_node_ring_colors[w_label_to_node[label]] = COLORS[color]
        w_subtitle = "Plucker-product side; boundary colors come from the factors"
        x_subtitle = f"colored from W boundary condition; count = {ev['coloring_count']}"

    factors_html = []
    for i, labels in enumerate(factors, start=1):
        labels_text = ",".join(str(x) for x in labels)
        factors_html.append(
            f'<li><span class="swatch" style="background:{COLORS[i]}"></span> color {i}: '
            f'<span class="word">Δ_{{{labels_text}}}</span></li>'
        )

    return f"""
    <section class="step coloring">
      <div class="step-head">
        <div><strong>Coloring fallback</strong></div>
        <div class="muted">The surviving branch is evaluated by Proposition 2.20 as a consistent-coloring count.</div>
      </div>
      <div class="grid two">
        {draw_web_svg('W', w_graph, final_w, [], edge_colors=w_edge_colors, node_ring_colors=w_node_ring_colors, subtitle=w_subtitle)}
        {draw_web_svg('X', x_graph, final_x, [], edge_colors=x_edge_colors, node_ring_colors=x_node_ring_colors, subtitle=x_subtitle)}
      </div>
      <div class="factor-box">
        <h3>Detected Plücker Factors</h3>
        <ul>{''.join(factors_html)}</ul>
        <p><strong>Surviving coefficient:</strong> {ev['coeff']}</p>
        <p><strong>Coloring count:</strong> {ev['coloring_count']}</p>
        <p><strong>Surviving contribution:</strong> {ev['term_value']}</p>
        <p><strong>Final pairing value:</strong> {proof.get('final_pairing_value')}</p>
      </div>
    </section>
    """


def page_shell(params: Dict[str, str], body: str = "") -> str:
    rep = html.escape(params.get("rep", DEFAULT_REP))
    x = html.escape(params.get("x", DEFAULT_X))
    w = html.escape(params.get("w", DEFAULT_W))
    raw_max_steps = params.get("max_steps", "")
    max_steps = "" if raw_max_steps in {"8", "auto"} else html.escape(raw_max_steps)
    beam = html.escape(params.get("beam_width", "120"))
    allow_w = "checked" if params.get("allow_w", "1") == "1" else ""
    show_steps = "checked" if params.get("show_steps") == "1" else ""
    has_visible_manual_pair = bool(params.get("w", "").strip() and params.get("x", "").strip())
    use_transpose = "checked" if params.get("use_transpose") == "1" and not has_visible_manual_pair else ""
    survivor_menu = survivor_selector_html(params)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wrench Pairing Explorer</title>
  <style>
    :root {{ --ink:#17202a; --muted:#667481; --line:#d8dee6; --bg:#f6f8fb; --panel:#fff; --blue:#2586d8; --green:#149451; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Arial, Helvetica, sans-serif; color:var(--ink); background:var(--bg); }}
    header {{ padding:28px 34px 18px; background:#fff; border-bottom:1px solid var(--line); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin:0 0 10px; font-size:20px; }}
    h3 {{ margin:0 0 8px; font-size:17px; }}
    p {{ margin:6px 0; }}
    form {{ display:grid; grid-template-columns: minmax(260px, 1fr) minmax(260px, 1fr) 120px 120px 180px 150px 130px; gap:12px; align-items:end; margin-top:18px; }}
    label {{ display:flex; flex-direction:column; gap:6px; color:var(--muted); font-size:13px; }}
    input[type=text], input[type=number], select {{ padding:10px 11px; border:1px solid var(--line); border-radius:7px; font-size:14px; background:#fff; color:var(--ink); }}
    select {{ width:100%; }}
    .check {{ flex-direction:row; align-items:center; gap:9px; padding-bottom:10px; }}
    #survivor-menu-slot {{ grid-column: 1 / -1; }}
    #survivor-menu-slot:empty {{ display:none; }}
    details {{ grid-column: 1 / -1; border:1px solid var(--line); border-radius:8px; padding:10px 12px; background:#fafbfd; }}
    summary {{ cursor:pointer; color:var(--muted); }}
    .advanced-grid {{ display:grid; grid-template-columns: minmax(260px, 1fr) 210px; gap:12px; margin-top:12px; align-items:end; }}
    .survivor-panel {{ background:#f8fbff; }}
    .survivor-grid {{ display:grid; grid-template-columns: minmax(320px, 1fr) minmax(300px, 520px); gap:14px; margin-top:12px; align-items:start; }}
    .survivor-meta {{ border:1px solid var(--line); border-radius:7px; padding:10px 12px; background:#fff; }}
    button {{ height:40px; border:0; border-radius:7px; background:var(--ink); color:#fff; font-size:14px; cursor:pointer; }}
    main {{ padding:24px 34px 50px; }}
    .summary, .toc, .step {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; margin-bottom:18px; }}
    .summary {{ display:grid; grid-template-columns: 1fr auto auto auto auto; gap:16px; align-items:center; }}
    .result-pill {{ padding:10px 14px; border-radius:999px; background:#e8f4ed; color:#0e7c43; font-weight:bold; }}
    .metric {{ display:flex; flex-direction:column; gap:4px; min-width:120px; }}
    .metric span, .muted, .web-subtitle, .pair-note {{ color:var(--muted); font-size:13px; }}
    .metric strong {{ font-size:24px; }}
    .word {{ font-family: Georgia, serif; letter-spacing:.5px; }}
    .step-head {{ display:flex; justify-content:space-between; align-items:baseline; gap:20px; margin-bottom:14px; }}
    .grid {{ display:grid; gap:14px; }}
    .grid.four {{ grid-template-columns: repeat(4, minmax(260px, 1fr)); }}
    .grid.two {{ grid-template-columns: repeat(2, minmax(330px, 1fr)); }}
    .web-card, .pair-card {{ border:1px solid var(--line); border-radius:8px; padding:10px; background:#fff; min-width:0; }}
    .web-title, .pair-title {{ text-align:center; font-weight:bold; margin-bottom:4px; }}
    .web-subtitle, .pair-note {{ text-align:center; min-height:18px; }}
    .web-card svg {{ display:block; margin:0 auto; max-width:100%; height:auto; }}
    .mini-pair {{ display:grid; grid-template-columns: 1fr 1fr; gap:8px; }}
    .mini-pair .web-card {{ padding:6px; }}
    .factor-box {{ margin-top:14px; border:1px solid var(--line); border-radius:8px; padding:14px; }}
    .factor-box ul {{ list-style:none; padding:0; margin:0 0 12px; display:grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap:8px; }}
    .swatch {{ width:18px; height:18px; display:inline-block; border-radius:4px; vertical-align:middle; margin-right:8px; }}
    .step-table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    .step-table th, .step-table td {{ border-bottom:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }}
    .step-table th {{ color:var(--muted); font-size:12px; font-weight:normal; }}
    @media (max-width: 1300px) {{ form, .summary, .grid.four, .grid.two {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Wrench Pairing Explorer</h1>
    <p class="muted">Enter W and X directly. They do not need to be transposes of each other.</p>
    <form method="get" action="/run">
      <label>W web index, word, or JSON file<input id="w-input" name="w" type="text" value="{w}" placeholder="0447_1231423121323444.json"></label>
      <label>X web index, word, or JSON file<input id="x-input" name="x" type="text" value="{x}" placeholder="0447_1112122334344234.json"></label>
      <label>Step cap, optional<input name="max_steps" type="number" value="{max_steps}" min="0" placeholder="auto"></label>
      <label>Beam width<input name="beam_width" type="number" value="{beam}" min="1"></label>
      <label class="check"><input type="checkbox" name="allow_w" value="1" {allow_w}> allow wrench moves on W</label>
      <label class="check"><input type="checkbox" name="show_steps" value="1" {show_steps}> show full step pictures</label>
      <button type="submit">Run proof search</button>
      <div id="survivor-menu-slot">
        {survivor_menu}
      </div>
      <details>
        <summary>Shortcut: use a representative and its transpose instead</summary>
        <div class="advanced-grid">
          <label>Representative index or word<input name="rep" type="text" value="{rep}" placeholder="447 or 1112122334344234"></label>
          <label class="check"><input type="checkbox" name="use_transpose" value="1" {use_transpose}> use transpose pair when W/X are blank</label>
        </div>
      </details>
    </form>
  </header>
  <main>
    {body or '<section class="toc"><h2>Ready</h2><p>Enter a W web and an X web above, then run wrench moves and coloring. The two webs do not have to be a transpose pair.</p></section>'}
  </main>
  <script>
    const survivorSlot = document.getElementById('survivor-menu-slot');
    const wInput = document.getElementById('w-input');
    const xInput = document.getElementById('x-input');

    function bindSurvivorSelect() {{
      const survivorSelect = document.getElementById('survivor-x-select');
      if (!survivorSelect || !xInput) {{
        return;
      }}
      survivorSelect.addEventListener('change', () => {{
        if (survivorSelect.value) {{
          xInput.value = survivorSelect.value;
        }}
      }});
      if (survivorSelect.value) {{
        xInput.value = survivorSelect.value;
      }}
    }}

    async function refreshSurvivorMenu() {{
      if (!survivorSlot || !wInput) {{
        return;
      }}
      const w = wInput.value.trim();
      survivorSlot.innerHTML = '';
      if (!w) {{
        return;
      }}
      try {{
        const response = await fetch('/survivors?w=' + encodeURIComponent(w), {{cache: 'no-store'}});
        if (!response.ok) {{
          return;
        }}
        survivorSlot.innerHTML = await response.text();
        bindSurvivorSelect();
      }} catch (error) {{
        console.warn('Could not refresh survivor menu', error);
      }}
    }}

    function debounce(fn, delay) {{
      let timer = null;
      return () => {{
        window.clearTimeout(timer);
        timer = window.setTimeout(fn, delay);
      }};
    }}

    bindSurvivorSelect();
    if (wInput) {{
      const delayedRefresh = debounce(refreshSurvivorMenu, 350);
      wInput.addEventListener('input', delayedRefresh);
      wInput.addEventListener('change', refreshSurvivorMenu);
      wInput.addEventListener('blur', refreshSurvivorMenu);
    }}
  </script>
</body>
</html>"""


class AppHandler(BaseHTTPRequestHandler):
    def send_html(self, content: str, status: int = 200) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if parsed.path == "/":
            self.send_html(page_shell(params))
            return
        if parsed.path == "/run":
            try:
                self.send_html(run_pair(params))
            except Exception as exc:  # noqa: BLE001 - show mathematical/debugging failure in page.
                body = (
                    '<section class="summary"><div><h2>Could not run this pairing</h2>'
                    f"<p>{html.escape(str(exc))}</p></div></section>"
                )
                self.send_html(page_shell(params, body), status=500)
            return
        if parsed.path == "/survivors":
            self.send_html(survivor_selector_html(params))
            return
        self.send_html(page_shell(params, "<section class='summary'><h2>Not found</h2></section>"), status=404)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[wrench-web] {self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help=(
            "Folder containing hourglass_disk_4x4_promotion_reps_graph_data "
            "and hourglass_disk_4x4_transpose_words_graph_data. Defaults to "
            "the folder containing this Python file."
        ),
    )
    args = parser.parse_args()
    configure_project_root(args.project_root)
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Wrench Pairing Explorer running at http://{args.host}:{args.port}/")
    print(f"Using graph data from {PROJECT_ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
