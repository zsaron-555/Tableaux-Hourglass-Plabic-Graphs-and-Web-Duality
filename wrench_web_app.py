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
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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
_PROMOTION_REP_CACHE: Optional[Dict[str, Tuple[int, str]]] = None
_ACTUAL_SURVIVOR_CACHE: Dict[Tuple[str, str, float], Dict[str, Any]] = {}
_GRAPH_DIR_CACHE: Dict[Path, Dict[str, Dict[Any, Path]]] = {}
_FORK_CACHE: Dict[Path, Set[frozenset[int]]] = {}
_PROMOTED_WORD_CACHE: Dict[Tuple[str, int], str] = {}

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
    global PROJECT_ROOT, X_DIR, W_DIR, ALL_DIR, SURVIVOR_CSV, PROMOTION_TABLE, _SURVIVOR_CACHE, _PROMOTION_ORBIT_CACHE, _PROMOTION_REP_CACHE, _ACTUAL_SURVIVOR_CACHE, _GRAPH_DIR_CACHE, _FORK_CACHE, _PROMOTED_WORD_CACHE
    PROJECT_ROOT = locate_project_root(project_root)
    X_DIR = PROJECT_ROOT / X_FOLDER_NAME
    W_DIR = PROJECT_ROOT / W_FOLDER_NAME
    ALL_DIR = next((PROJECT_ROOT / name for name in ALL_FOLDER_ALIASES if (PROJECT_ROOT / name).exists()), PROJECT_ROOT / ALL_FOLDER_NAME)
    SURVIVOR_CSV = PROJECT_ROOT / SURVIVOR_CSV_NAME
    PROMOTION_TABLE = PROJECT_ROOT / PROMOTION_TABLE_PATH
    _SURVIVOR_CACHE = None
    _PROMOTION_ORBIT_CACHE = None
    _PROMOTION_REP_CACHE = None
    _ACTUAL_SURVIVOR_CACHE = {}
    _GRAPH_DIR_CACHE = {}
    _FORK_CACHE = {}
    _PROMOTED_WORD_CACHE = {}


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def graph_dir_index(graph_dir: Path) -> Dict[str, Dict[Any, Path]]:
    graph_dir = graph_dir.resolve()
    cached = _GRAPH_DIR_CACHE.get(graph_dir)
    if cached is not None:
        return cached

    by_index: Dict[int, Path] = {}
    by_word: Dict[str, Path] = {}
    by_name: Dict[str, Path] = {}
    if graph_dir.exists():
        for path in graph_dir.glob("*.json"):
            stem = path.stem
            by_name[path.name] = path
            if "_" not in stem:
                continue
            prefix, word = stem.split("_", 1)
            by_word[word] = path
            if prefix.isdigit():
                by_index[int(prefix)] = path
    index = {"by_index": by_index, "by_word": by_word, "by_name": by_name}
    _GRAPH_DIR_CACHE[graph_dir] = index
    return index


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
        index = graph_dir_index(graph_dir)
        if value.isdigit() and len(value) <= 5:
            idx = int(value)
            match = index["by_index"].get(idx)
            if match:
                return match

        exact = graph_dir / value
        if exact.exists():
            return exact

        match = index["by_name"].get(value) or index["by_word"].get(value)
        if match:
            return match

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
    else:
        all_words_path = ALL_DIR / "all_4x4_words.tsv"
        if all_words_path.exists():
            all_words = []
            with all_words_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    word = (row.get("word") or "").strip()
                    if word:
                        all_words.append(word)
            orbits = build_promotion_orbits(all_words)
    _PROMOTION_ORBIT_CACHE = orbits
    return orbits


def word_to_tableau(word: str) -> List[List[int]]:
    rows: List[List[int]] = [[] for _ in range(4)]
    for number, letter in enumerate(word, start=1):
        rows[int(letter) - 1].append(number)
    return rows


def tableau_to_word(tableau: List[List[int]]) -> str:
    n = sum(len(row) for row in tableau)
    letters = [""] * n
    for row_index, row in enumerate(tableau, start=1):
        for entry in row:
            letters[entry - 1] = str(row_index)
    return "".join(letters)


def promote_word(word: str) -> str:
    tableau = word_to_tableau(word)
    n = len(word)
    row = col = None
    for r, entries in enumerate(tableau):
        if 1 in entries:
            row, col = r, entries.index(1)
            break
    if row is None or col is None:
        raise ValueError(f"Could not find 1 in tableau for word {word}")

    tableau[row][col] = None  # type: ignore[index]
    while True:
        candidates = []
        if col + 1 < len(tableau[row]) and tableau[row][col + 1] is not None:
            candidates.append((tableau[row][col + 1], row, col + 1))
        if row + 1 < len(tableau) and col < len(tableau[row + 1]) and tableau[row + 1][col] is not None:
            candidates.append((tableau[row + 1][col], row + 1, col))
        if not candidates:
            break
        _, next_row, next_col = min(candidates)
        tableau[row][col] = tableau[next_row][next_col]
        tableau[next_row][next_col] = None  # type: ignore[index]
        row, col = next_row, next_col

    tableau[row][col] = n + 1  # type: ignore[index]
    promoted = [[int(entry) - 1 for entry in entries] for entries in tableau]
    return tableau_to_word(promoted)


def build_promotion_orbits(words: List[str]) -> Dict[int, List[str]]:
    word_set = set(words)
    seen = set()
    reps: List[Tuple[str, List[str]]] = []
    for word in sorted(word_set):
        if word in seen:
            continue
        orbit = []
        current = word
        while current not in orbit:
            orbit.append(current)
            seen.add(current)
            current = promote_word(current)
            if current not in word_set:
                raise ValueError(f"Promotion produced word not in all_4x4_words.tsv: {current}")
        reps.append((min(orbit), orbit))
    reps.sort(key=lambda item: item[0])
    return {idx: orbit for idx, (_, orbit) in enumerate(reps, start=1)}


def promotion_representative_for_word(word: str) -> Optional[Tuple[int, str]]:
    global _PROMOTION_REP_CACHE
    if _PROMOTION_REP_CACHE is None:
        reps: Dict[str, Tuple[int, str]] = {}
        for idx, words in promotion_orbit_words_by_index().items():
            if not words:
                continue
            representative = words[0]
            for orbit_word in words:
                reps[orbit_word] = (idx, representative)
        _PROMOTION_REP_CACHE = reps
    return _PROMOTION_REP_CACHE.get(word)


def promote_word_steps(word: str, steps: int) -> str:
    key = (word, steps)
    cached = _PROMOTED_WORD_CACHE.get(key)
    if cached is not None:
        return cached
    current = word
    for _ in range(steps):
        current = promote_word(current)
    _PROMOTED_WORD_CACHE[key] = current
    return current


def resolved_word(value: str, side: str) -> str:
    return graph_word(resolve_graph(value, side))


def promotion_shift_for_w(entry: Dict[str, Any], w_value: str) -> Tuple[str, int]:
    """Return the actual W word and its promotion distance from the CSV representative."""
    try:
        w_word = resolved_word(w_value or entry["w_word"], "W")
    except Exception:  # noqa: BLE001
        return entry["w_word"], 0

    rep = promotion_representative_for_word(w_word)
    if not rep:
        return w_word, 0
    rep_idx, _ = rep
    orbit = promotion_orbit_words_by_index().get(rep_idx, [])
    try:
        return w_word, orbit.index(w_word)
    except ValueError:
        return w_word, 0


def survivor_words_for_entered_w(entry: Dict[str, Any], w_value: str) -> Tuple[List[str], str, int]:
    w_word, shift = promotion_shift_for_w(entry, w_value)
    if shift == 0:
        return list(entry.get("survivor_words", [])), w_word, shift
    return [promote_word_steps(word, shift) for word in entry.get("survivor_words", [])], w_word, shift


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
    rep = promotion_representative_for_word(word)
    if rep:
        rep_idx, rep_word = rep
        return survivors["by_word"].get(rep_word) or survivors["by_idx"].get(rep_idx)

    # If the graph folders are not available, allow numeric inputs to mean CSV
    # row indices. When graph data exists, the numeric value has already been
    # interpreted as a graph index and, if possible, mapped to its promotion
    # representative above.
    if value.isdigit():
        return survivors["by_idx"].get(int(value))
    return None


def selected_survivor_for_params(params: Dict[str, str]) -> str:
    value = params.get("survivor_x", "").strip()
    if not value:
        return ""
    w_value = params.get("w", "").strip()
    entry = survivor_entry_for_w(w_value)
    if entry and value in set(actual_survivor_words(entry, w_value)["words"]):
        return value
    return ""


def forks_for_graph(value: str, side: str) -> Set[frozenset[int]]:
    path = resolve_graph(value, side)
    cache_key = path.resolve()
    cached = _FORK_CACHE.get(cache_key)
    if cached is not None:
        return cached
    adj, boundary_labels, _ = wrench.parse_web(path)
    forks = wrench.get_forks(adj, boundary_labels)
    _FORK_CACHE[cache_key] = forks
    return forks


def actual_survivor_words(entry: Dict[str, Any], w_value: str = "") -> Dict[str, Any]:
    """Filter CSV survivors by the same immediate fork test used by proof search."""
    mtime = load_survivor_index().get("mtime") or 0.0
    filter_w_value = w_value.strip() or entry["w_word"]
    csv_words = list(entry.get("survivor_words", []))
    shifted_words, filter_w_word, promotion_shift = survivor_words_for_entered_w(entry, filter_w_value)
    key = (entry["w_word"], filter_w_word, float(mtime))
    cached = _ACTUAL_SURVIVOR_CACHE.get(key)
    if cached is not None:
        return cached

    result = {
        "words": [],
        "csv_count": len(csv_words),
        "shifted_count": len(shifted_words),
        "removed_count": 0,
        "unresolved_count": 0,
        "promotion_shift": promotion_shift,
        "filter_w_word": filter_w_word,
    }
    if not shifted_words:
        _ACTUAL_SURVIVOR_CACHE[key] = result
        return result

    try:
        w_forks = forks_for_graph(filter_w_value, "W")
    except Exception:  # noqa: BLE001 - keep the menu usable if validation cannot run.
        result["words"] = shifted_words
        result["unresolved_count"] = len(shifted_words)
        _ACTUAL_SURVIVOR_CACHE[key] = result
        return result

    actual_words = []
    removed = 0
    unresolved = 0
    for word in shifted_words:
        try:
            x_forks = forks_for_graph(word, "X")
        except Exception:  # noqa: BLE001 - skip only the validation for this candidate.
            unresolved += 1
            actual_words.append(word)
            continue
        if w_forks.intersection(x_forks):
            removed += 1
        else:
            actual_words.append(word)

    result = {
        "words": actual_words,
        "csv_count": len(csv_words),
        "shifted_count": len(shifted_words),
        "removed_count": removed,
        "unresolved_count": unresolved,
        "promotion_shift": promotion_shift,
        "filter_w_word": filter_w_word,
    }
    _ACTUAL_SURVIVOR_CACHE[key] = result
    return result


def survivor_selector_html(params: Dict[str, str]) -> str:
    entered_w = params.get("w", "").strip()
    if not entered_w:
        return ""
    if not SURVIVOR_CSV.exists():
        return f"""
        <details class="survivor-panel" open>
          <summary>Lemma 4.6 survivors unavailable</summary>
          <p class="muted">Could not find <span class="word">{html.escape(SURVIVOR_CSV_NAME)}</span> under <span class="word">{html.escape(str(PROJECT_ROOT))}</span>.</p>
          <p class="muted">Put {html.escape(SURVIVOR_CSV_NAME)} in the same folder as wrench_web_app.py, or start the app with --project-root pointing to the folder that contains it.</p>
        </details>
        """
    if not ALL_DIR.exists() and not X_DIR.exists() and not W_DIR.exists():
        return f"""
        <details class="survivor-panel" open>
          <summary>Lemma 4.6 survivors unavailable</summary>
          <p class="muted">Could not find graph data under <span class="word">{html.escape(str(PROJECT_ROOT))}</span>.</p>
          <p class="muted">Expected a folder named <span class="word">4x4_All_graph_data</span> or <span class="word">hourglass_disk_4x4_all_graph_data</span>.</p>
        </details>
        """
    entry = survivor_entry_for_w(entered_w)
    if not entry:
        resolved_note = ""
        try:
            resolved_note = f"<p class=\"muted\">Entered W resolves to <span class=\"word\">{html.escape(graph_word(resolve_graph(entered_w, 'W')))}</span>, but no Lemma 4.6 survivor row was found for it or its promotion representative.</p>"
        except Exception as exc:  # noqa: BLE001 - user-facing diagnostic.
            resolved_note = f"<p class=\"muted\">Could not resolve W input <span class=\"word\">{html.escape(entered_w)}</span>: {html.escape(str(exc))}</p>"
        return f"""
        <details class="survivor-panel" open>
          <summary>No Lemma 4.6 survivor menu for this W</summary>
          {resolved_note}
        </details>
        """

    survivor_info = actual_survivor_words(entry, entered_w)
    survivor_words = survivor_info["words"]
    if not survivor_words:
        return f"""
        <details class="survivor-panel" open>
          <summary>Lemma 4.6 survivors for W = {html.escape(entry['w_word'])}</summary>
          <p class="muted">The CSV lists {survivor_info['csv_count']} candidate survivors for this W, but none survive the app's immediate common-fork test.</p>
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
    resolved_w_note = ""
    if entered_w:
        try:
            entered_w_word = graph_word(resolve_graph(entered_w, "W"))
            if entered_w != entered_w_word:
                resolved_w_note = (
                    f'<p class="muted">Entered W resolves to <span class="word">{html.escape(entered_w_word)}</span>.</p>'
                )
        except Exception:  # noqa: BLE001 - purely informational.
            resolved_w_note = ""
    canonical_note = (
        f'<p class="muted">Survivor list comes from promotion-orbit representative <span class="word">{html.escape(entry["w_word"])}</span>; filtering is done against the entered W.</p>'
        if entered_w and entered_w != entry["w_word"]
        else ""
    )
    shift_note = (
        f'<p class="muted">Applied promotion shift {survivor_info["promotion_shift"]} to the survivor X words to match the entered W.</p>'
        if survivor_info.get("promotion_shift", 0)
        else ""
    )
    return f"""
    <details class="survivor-panel" open>
      <summary>Lemma 4.6 survivors for W = {html.escape(entry['w_word'])}</summary>
      <input type="hidden" name="survivor_w" id="survivor-w-word" value="{html.escape(entry['w_word'])}">
      <div class="survivor-grid">
        <label>Survivor X word
          <select name="survivor_x" id="survivor-x-select">
            {''.join(options)}
          </select>
        </label>
        <div class="survivor-meta">
          <p><strong>{len(survivor_words)}</strong> selectable survivors</p>
          <p><strong>{entry['n_survivor_pairs']}</strong> CSV survivor pairs, <strong>{entry['n_survivor_orbits']}</strong> CSV survivor orbits</p>
          <p><strong>{survivor_info['removed_count']}</strong> CSV candidates removed by immediate common-fork check</p>
          <p><strong>Forks of W:</strong> {html.escape(entry.get('forks_W', ''))}</p>
          {resolved_w_note}
          {canonical_note}
          {shift_note}
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


def warm_lookup_caches() -> None:
    try:
        load_survivor_index()
        promotion_orbit_words_by_index()
        if ALL_DIR.exists():
            graph_dir_index(ALL_DIR)
    except Exception as exc:  # noqa: BLE001 - cache warming should not prevent the app from starting.
        print(f"[wrench-web] cache warming skipped: {exc}")


def resolve_pair(params: Dict[str, str]) -> Tuple[Path, Path, str]:
    """Resolve the requested pairing.

    Normal mode: explicit W and X inputs are resolved independently.  The old
    representative-transpose shortcut is still available with use_transpose=1.
    """
    use_transpose = params.get("use_transpose") == "1"
    w_value = params.get("w", "").strip()
    raw_survivor_value = params.get("survivor_x", "").strip()
    survivor_value = selected_survivor_for_params(params)
    x_value = survivor_value or params.get("x", "").strip()
    if raw_survivor_value and not survivor_value and x_value == raw_survivor_value:
        raise ValueError(
            "The selected Lemma 4.6 survivor is no longer selectable because it is "
            "immediately killed by the common-fork test. Pick another survivor from "
            "the refreshed menu."
        )
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
    selected_wrench_edges: set[Tuple[int, int]] = set()
    selected_wrench_nodes: set[int] = set()
    if selected_key:
        for hg in remaining_hourglasses:
            w, b = int(hg["white"]), int(hg["black"])
            if tuple(sorted((w, b))) != selected_key:
                continue
            selected_wrench_nodes.update({w, b})
            for endpoint in (w, b):
                for neighbor in wrench.neighbor_list(adj.get(endpoint, [])):
                    selected_wrench_edges.add(tuple(sorted((endpoint, neighbor))))
                    selected_wrench_nodes.add(neighbor)

    highlight_nodes = dict(node_ring_colors)
    for node in selected_wrench_nodes:
        highlight_nodes[node] = "#cf2f2f"
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
        edge_key = tuple(sorted((u, v)))
        if edge_key in selected_wrench_edges:
            color = "#cf2f2f"
            width = 5
        else:
            color = edge_colors.get(edge_key, "#111")
            width = 4 if edge_key in edge_colors else 2
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
    raw_x = params.get("x", DEFAULT_X)
    raw_selected_survivor = params.get("survivor_x", "").strip()
    if raw_selected_survivor and raw_x.strip() == raw_selected_survivor and not selected_survivor_for_params(params):
        raw_x = ""
    x = html.escape(raw_x)
    raw_w = params.get("w", DEFAULT_W)
    w = html.escape(raw_w)
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
          xInput.dataset.fromSurvivor = '1';
        }}
      }});
      if (survivorSelect.value) {{
        xInput.value = survivorSelect.value;
        xInput.dataset.fromSurvivor = '1';
      }}
    }}

    async function refreshSurvivorMenu() {{
      if (!survivorSlot || !wInput) {{
        return;
      }}
      const w = wInput.value.trim();
      if (xInput && xInput.dataset.fromSurvivor === '1') {{
        xInput.value = '';
        xInput.dataset.fromSurvivor = '';
      }}
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
    warm_lookup_caches()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Wrench Pairing Explorer running at http://{args.host}:{args.port}/")
    print(f"Using graph data from {PROJECT_ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
