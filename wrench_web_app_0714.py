#!/usr/bin/env python3
"""Local interactive webpage for wrench/fork/coloring pairing computations."""

from __future__ import annotations

import argparse
import ast
import csv
import html
import json
import math
import mimetypes
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import Wrench_or_Skein_0714 as wrench
import web_relation_rules_0714 as relation_rules


APP_DIR = Path(__file__).resolve().parent
X_FOLDER_NAME = "hourglass_disk_4x4_promotion_reps_graph_data"
W_FOLDER_NAME = "hourglass_disk_4x4_transpose_words_graph_data"
ALL_FOLDER_NAME = "hourglass_disk_4x4_all_graph_data"
ALL_FOLDER_ALIASES = (ALL_FOLDER_NAME, "4x4_All_graph_data")
SURVIVOR_CSV_NAME = "lemma46_survivors.csv"
PROMOTION_TABLE_PATH = Path("hourglass_disk_4x4_promotion_reps") / "promotion_orbits_4x4.tsv"
IMAGE_EXPLORER_HTML_NAME = "web_explorer_v3.html"
REP_IMAGE_FOLDER_NAME = "hourglass_disk_4x4_promotion_reps"
PROJECT_ROOT = Path(os.environ.get("PROBLEM3_ROOT", APP_DIR)).expanduser().resolve()
X_DIR = PROJECT_ROOT / X_FOLDER_NAME
W_DIR = PROJECT_ROOT / W_FOLDER_NAME
ALL_DIR = PROJECT_ROOT / ALL_FOLDER_NAME
SURVIVOR_CSV = PROJECT_ROOT / SURVIVOR_CSV_NAME
PROMOTION_TABLE = PROJECT_ROOT / PROMOTION_TABLE_PATH
IMAGE_EXPLORER_HTML = PROJECT_ROOT / IMAGE_EXPLORER_HTML_NAME
REP_IMAGE_DIR = PROJECT_ROOT / REP_IMAGE_FOLDER_NAME
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


def unique_existing_paths(paths: Iterable[Path]) -> List[Path]:
    seen = set()
    out = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except Exception:  # noqa: BLE001 - best-effort path discovery.
            continue
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def search_roots(preferred_root: str | Path) -> List[Path]:
    root = Path(preferred_root).expanduser()
    home = Path.home()
    candidates = [
        root,
        APP_DIR,
        Path.cwd(),
        root.parent,
        APP_DIR.parent,
        Path.cwd().parent,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
    ]
    return unique_existing_paths(candidates)


def safe_rglob(root: Path, pattern: str):
    try:
        yield from root.rglob(pattern)
    except (OSError, PermissionError):
        return


def find_named_dir(names: Iterable[str], preferred_root: str | Path) -> Optional[Path]:
    name_set = set(names)
    for root in search_roots(preferred_root):
        for name in name_set:
            direct = root / name
            if direct.is_dir():
                return direct
        for path in safe_rglob(root, "*"):
            if path.is_dir() and path.name in name_set:
                return path
    return None


def find_named_file(name: str, preferred_root: str | Path, *, relative: Optional[Path] = None) -> Path:
    for root in search_roots(preferred_root):
        if relative is not None:
            direct_relative = root / relative
            if direct_relative.is_file():
                return direct_relative
        direct = root / name
        if direct.is_file():
            return direct
        for path in safe_rglob(root, name):
            if path.is_file():
                return path
    fallback_root = Path(preferred_root).expanduser().resolve()
    return fallback_root / (relative or Path(name))


def locate_project_root(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    if any((root / name).exists() for name in ALL_FOLDER_ALIASES) or (
        (root / X_FOLDER_NAME).exists() and (root / W_FOLDER_NAME).exists()
    ):
        return root

    for search_root in search_roots(root):
        for x_dir in safe_rglob(search_root, X_FOLDER_NAME):
            if not x_dir.is_dir():
                continue
            candidate = x_dir.parent
            if (candidate / W_FOLDER_NAME).exists():
                return candidate
    all_dir = find_named_dir(ALL_FOLDER_ALIASES, root)
    if all_dir:
        return all_dir.parent

    return root


def locate_all_dir(project_root: Path) -> Path:
    for name in ALL_FOLDER_ALIASES:
        direct = project_root / name
        if direct.exists():
            return direct
    found = find_named_dir(ALL_FOLDER_ALIASES, project_root)
    if found:
        return found
    return project_root / ALL_FOLDER_NAME


def locate_representative_dirs(project_root: Path) -> Tuple[Path, Path]:
    x_dir = project_root / X_FOLDER_NAME
    w_dir = project_root / W_FOLDER_NAME
    if x_dir.exists() and w_dir.exists():
        return x_dir, w_dir
    found_x = find_named_dir([X_FOLDER_NAME], project_root)
    found_w = find_named_dir([W_FOLDER_NAME], project_root)
    return found_x or x_dir, found_w or w_dir


def configure_project_root(project_root: str | Path) -> None:
    global PROJECT_ROOT, X_DIR, W_DIR, ALL_DIR, SURVIVOR_CSV, PROMOTION_TABLE, IMAGE_EXPLORER_HTML, REP_IMAGE_DIR, _SURVIVOR_CACHE, _PROMOTION_ORBIT_CACHE, _PROMOTION_REP_CACHE, _ACTUAL_SURVIVOR_CACHE, _GRAPH_DIR_CACHE, _FORK_CACHE, _PROMOTED_WORD_CACHE
    PROJECT_ROOT = locate_project_root(project_root)
    X_DIR, W_DIR = locate_representative_dirs(PROJECT_ROOT)
    ALL_DIR = locate_all_dir(PROJECT_ROOT)
    SURVIVOR_CSV = find_named_file(SURVIVOR_CSV_NAME, PROJECT_ROOT)
    PROMOTION_TABLE = find_named_file("promotion_orbits_4x4.tsv", PROJECT_ROOT, relative=PROMOTION_TABLE_PATH)
    IMAGE_EXPLORER_HTML = find_named_file(IMAGE_EXPLORER_HTML_NAME, PROJECT_ROOT)
    REP_IMAGE_DIR = find_named_dir([REP_IMAGE_FOLDER_NAME], PROJECT_ROOT) or (PROJECT_ROOT / REP_IMAGE_FOLDER_NAME)
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


def image_explorer_page() -> str:
    if not IMAGE_EXPLORER_HTML.exists():
        return page_shell(
            {},
            f"""
            <section class="summary">
              <div>
                <h2>Image Explorer Missing</h2>
                <p>Could not find <span class="word">{html.escape(IMAGE_EXPLORER_HTML_NAME)}</span>.</p>
                <p class="muted">Put it near <span class="word">wrench_web_app.py</span>, or somewhere under Desktop, Documents, or Downloads.</p>
              </div>
            </section>
            """,
        )
    text = IMAGE_EXPLORER_HTML.read_text(encoding="utf-8")
    nav = """
    <div style="margin:0 0 14px 0;padding:10px 12px;background:#eef5ff;border:1px solid #cbd8ea;border-radius:6px;font-family:Arial,Helvetica,sans-serif;font-size:14px">
      <a href="/" style="color:#17202a;font-weight:bold;text-decoration:none">Wrench Pairing Explorer</a>
      <span style="color:#667481;margin:0 8px">|</span>
      <span style="font-weight:bold">Image Survivor Explorer</span>
    </div>
    """
    if "<body>" in text:
        text = text.replace("<body>", "<body>\n" + nav, 1)
    else:
        text = nav + text
    return text


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
    hourglass_colors: Optional[Dict[Tuple[int, int], Tuple[str, str]]] = None,
    node_ring_colors: Optional[Dict[int, str]] = None,
    highlight_edges: Optional[Dict[Tuple[int, int], str]] = None,
    edge_curves: Optional[Dict[Tuple[int, int], List[Tuple[float, float]]]] = None,
    subtitle: str = "",
    size: int = 330,
) -> str:
    nodes, xy, boundary, label_to_node = node_maps(graph)
    edge_colors = edge_colors or {}
    hourglass_colors = hourglass_colors or {}
    node_ring_colors = node_ring_colors or {}
    highlight_edges = highlight_edges or {}
    edge_curves = edge_curves or {}
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
        elif edge_key in highlight_edges:
            color = highlight_edges[edge_key]
            width = 5
        else:
            color = edge_colors.get(edge_key, "#111")
            width = 4 if edge_key in edge_colors else 2
        if edge_key in edge_curves:
            points = [transform(*point, size=size) for point in edge_curves[edge_key]]
            out.append(
                f'<path d="{cubic_path(points)}" fill="none" stroke="{color}" '
                f'stroke-width="{width}" stroke-linecap="round" />'
            )
        else:
            out.append(svg_line(transform(*xy[u], size=size), transform(*xy[v], size=size), color, width))

    for hg in remaining_hourglasses:
        w, b = int(hg["white"]), int(hg["black"])
        if w not in adj or b not in adj:
            continue
        key = tuple(sorted((w, b)))
        width = 4 if key == selected_key else 2
        strand_colors = hourglass_colors.get(key)
        if key == selected_key:
            strand_colors = ("#cf2f2f", "#cf2f2f")
        if strand_colors is None:
            strand_colors = ("#111", "#111")
        for path_points, color in zip(hourglass_paths(w, b, xy, size=size), strand_colors):
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


def move_edge_curves(move: Dict[str, Any]) -> Dict[Tuple[int, int], List[Tuple[float, float]]]:
    curves: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    for record in move.get("edge_curves", []):
        edge = record.get("edge", [])
        points = record.get("points", [])
        if len(edge) != 2 or len(points) != 4:
            continue
        curves[tuple(sorted((int(edge[0]), int(edge[1]))))] = [
            (float(point[0]), float(point[1])) for point in points
        ]
    return curves


def clarify_pre_untwist_curves(
    move: Dict[str, Any],
    curves: Dict[Tuple[int, int], List[Tuple[float, float]]],
) -> Dict[Tuple[int, int], List[Tuple[float, float]]]:
    """Make a shared-leaf crossing visible without changing its tangents.

    A tangent cubic can cross the other edge extremely close to their shared
    endpoint, where the vertex marker hides it.  In the diagnostic pre-untwist
    picture, extend both tangent handles along their original rays so the same
    crossing occurs farther inside the disk.  Endpoints and tangent directions
    are unchanged; this adjustment is display-only.
    """
    clarified = {edge: list(points) for edge, points in curves.items()}
    handle_scale = 2.2
    for untwist in move.get("untwists", []):
        edge = tuple(
            sorted((int(untwist["vertex"]), int(untwist["new_neighbor"])))
        )
        points = clarified.get(edge)
        if not points or len(points) != 4:
            continue
        start, control_1, control_2, end = points
        clarified[edge] = [
            start,
            (
                start[0] + handle_scale * (control_1[0] - start[0]),
                start[1] + handle_scale * (control_1[1] - start[1]),
            ),
            (
                end[0] + handle_scale * (control_2[0] - end[0]),
                end[1] + handle_scale * (control_2[1] - end[1]),
            ),
            end,
        ]
    return clarified


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
    _x_colors, x_node_xy = wrench.parse_web_metadata(x_path)
    _w_colors, w_node_xy = wrench.parse_web_metadata(w_path)
    x_hgs = wrench.sort_hourglasses_by_boundary_distance(x_adj, x_bounds, x_hgs)
    w_hgs = wrench.sort_hourglasses_by_boundary_distance(w_adj, w_bounds, w_hgs)

    def move_key(move: Dict[str, Any]) -> Tuple[str, str, Tuple[int, ...], str]:
        local_piece = move.get("hourglass", move.get("vertices", []))
        return (
            str(move.get("phase", "wrench")),
            str(move.get("side", "X")),
            tuple(sorted(int(x) for x in local_piece)),
            str(move.get("smoothing", "")),
        )

    def same_hourglass(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        return move_key(a)[:3] == move_key(b)[:3]

    def history_matches(history: List[Dict[str, Any]], prefix: List[Dict[str, Any]]) -> bool:
        if len(history) < len(prefix):
            return False
        return [move_key(m) for m in history[: len(prefix)]] == [move_key(m) for m in prefix]

    def opposite_smoothing(smoothing: str) -> str:
        if smoothing == "crossing":
            return "parallel"
        if smoothing == "parallel":
            return "crossing"
        if smoothing == "horizontal":
            return "vertical"
        if smoothing == "vertical":
            return "horizontal"
        return smoothing

    def sibling_outcome(prefix: List[Dict[str, Any]], continue_move: Dict[str, Any]) -> Dict[str, Any]:
        sibling_prefix = list(prefix) + [
            {
                **continue_move,
                "smoothing": opposite_smoothing(continue_move["smoothing"]),
            }
        ]
        for discharged in proof.get("discharged_terms", []):
            history = discharged.get("history", [])
            if not history_matches(history, sibling_prefix):
                continue
            if not discharged.get("common_forks"):
                continue
            return {
                **discharged,
                "status": "fork_killed" if len(history) == len(sibling_prefix) else "continued_then_fork_killed",
                "continued_steps": max(0, len(history) - len(sibling_prefix)),
            }
        for active in proof.get("active_terms", []):
            history = active.get("history", [])
            if not history_matches(history, sibling_prefix):
                continue
            fallback = proof.get("w_expansion_fallback", {})
            status = "continued_active"
            if fallback.get("status") and fallback.get("status") != "not_computed":
                status = "continued_to_fallback"
            return {
                "common_forks": active.get("common_forks", []),
                "coeff": active.get("coeff", ""),
                "history": history,
                "reason": fallback.get("reason", ""),
                "status": status,
                "continued_steps": max(0, len(history) - len(sibling_prefix)),
            }
        return {
            "common_forks": [],
            "coeff": "",
            "history": sibling_prefix,
            "reason": "not_found_on_display_path",
            "status": "not_found",
            "continued_steps": 0,
        }

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
        phase = continue_move.get("phase", "main_search")
        if phase == "antisymmetrizer":
            before_x, before_w = current_x, current_w
            before_xh, before_wh = current_xh, current_wh
            current_x, current_xh, current_w, current_wh = wrench.replay_pair_history(
                x_adj,
                x_hgs,
                w_adj,
                w_hgs,
                active_history[: idx + 1],
            )
            steps.append(
                {
                    "move": dict(continue_move),
                    "side": side,
                    "selected": tuple(int(v) for v in continue_move.get("vertices", [])),
                    "current_x": before_x,
                    "current_w": before_w,
                    "current_xh": before_xh,
                    "current_wh": before_wh,
                    "killed": {"status": "six_term_relation", "common_forks": [], "coeff": ""},
                    "killed_smoothing": "other five permutations",
                    "sibling_smoothing": "other five permutations",
                    "continue_smoothing": continue_move.get("smoothing", ""),
                    "killed_x": before_x,
                    "killed_w": before_w,
                    "killed_xh": before_xh,
                    "killed_wh": before_wh,
                    "killed_new_x": set(),
                    "killed_new_w": set(),
                    "continue_x": current_x,
                    "continue_w": current_w,
                    "continue_xh": current_xh,
                    "continue_wh": current_wh,
                    "continue_new_x": edge_set(current_x) - edge_set(before_x),
                    "continue_new_w": edge_set(current_w) - edge_set(before_w),
                    "deferred_untwist_count": int(continue_move.get("deferred_untwist_count", 0) or 0),
                    "deferred_untwist_multiplier": int(continue_move.get("deferred_untwist_multiplier", 1) or 1),
                }
            )
            continue
        is_figure43 = phase == "figure43"
        selected = tuple(sorted(int(x) for x in continue_move.get("hourglass", continue_move.get("vertices", []))))
        hg = None
        if not is_figure43:
            hgs = current_xh if side == "X" else current_wh
            hg = next(
                h
                for h in hgs
                if tuple(sorted((int(h["white"]), int(h["black"])))) == selected
            )
        killed = sibling_outcome(active_history[:idx], continue_move)
        sibling_smoothing = opposite_smoothing(continue_move["smoothing"])

        def branch(smoothing: str):
            embedding: Dict[str, Any] = {}
            if is_figure43:
                match = {
                    "rule": continue_move["rule"],
                    "vertices_top_right_bottom_left": [int(v) for v in continue_move["vertices"]],
                }
                if side == "X":
                    bx, bxh = wrench.apply_figure43_move(current_x, current_xh, match, smoothing)
                    bw, bwh = current_w, current_wh
                    new_x = edge_set(bx) - edge_set(current_x)
                    new_w = set()
                else:
                    bx, bxh = current_x, current_xh
                    bw, bwh = wrench.apply_figure43_move(current_w, current_wh, match, smoothing)
                    new_x = set()
                    new_w = edge_set(bw) - edge_set(current_w)
            elif side == "X":
                assert hg is not None
                forced = continue_move.get("untwists") if smoothing == continue_move.get("smoothing") else None
                bx, embedding = wrench.smooth_one_hourglass_embedded(
                    current_x,
                    hg,
                    smoothing,
                    node_xy=x_node_xy,
                    forced_untwists=forced,
                )
                bw = current_w
                bxh = wrench.remaining_after_move(current_xh, hg)
                bwh = current_wh
                new_x = edge_set(bx) - edge_set(current_x)
                new_w = set()
            else:
                assert hg is not None
                bx = current_x
                forced = continue_move.get("untwists") if smoothing == continue_move.get("smoothing") else None
                bw, embedding = wrench.smooth_one_hourglass_embedded(
                    current_w,
                    hg,
                    smoothing,
                    node_xy=w_node_xy,
                    forced_untwists=forced,
                )
                bxh = current_xh
                bwh = wrench.remaining_after_move(current_wh, hg)
                new_x = set()
                new_w = edge_set(bw) - edge_set(current_w)
            return bx, bw, bxh, bwh, new_x, new_w, move_edge_curves(embedding)

        killed_x, killed_w, killed_xh, killed_wh, killed_new_x, killed_new_w, killed_curves = branch(sibling_smoothing)
        cont_x, cont_w, cont_xh, cont_wh, cont_new_x, cont_new_w, cont_curves = branch(continue_move["smoothing"])
        steps.append(
            {
                "move": dict(continue_move),
                "side": side,
                "selected": selected,
                "current_x": current_x,
                "current_w": current_w,
                "current_xh": current_xh,
                "current_wh": current_wh,
                "killed": killed,
                "killed_smoothing": sibling_smoothing,
                "sibling_smoothing": sibling_smoothing,
                "continue_smoothing": continue_move["smoothing"],
                "killed_x": killed_x,
                "killed_w": killed_w,
                "killed_xh": killed_xh,
                "killed_wh": killed_wh,
                "killed_new_x": killed_new_x,
                "killed_new_w": killed_new_w,
                "killed_curves": killed_curves,
                "continue_x": cont_x,
                "continue_w": cont_w,
                "continue_xh": cont_xh,
                "continue_wh": cont_wh,
                "continue_new_x": cont_new_x,
                "continue_new_w": cont_new_w,
                "continue_curves": cont_curves,
                "untwist_count": int(continue_move.get("untwist_count", 0) or 0),
                "untwist_multiplier": int(continue_move.get("untwist_multiplier", 1) or 1),
                "deferred_untwist_count": int(continue_move.get("deferred_untwist_count", 0) or 0),
                "deferred_untwist_multiplier": int(continue_move.get("deferred_untwist_multiplier", 1) or 1),
            }
        )
        current_x, current_w, current_xh, current_wh = cont_x, cont_w, cont_xh, cont_wh

    return x_graph, w_graph, x_bounds, w_bounds, steps, current_x, current_w, current_xh, current_wh, active_history


def move_key_for_display(move: Dict[str, Any]) -> Tuple[str, str, Tuple[int, ...], str]:
    local_piece = move.get("hourglass", move.get("vertices", []))
    return (
        str(move.get("phase", "wrench")),
        str(move.get("side", "X")),
        tuple(sorted(int(x) for x in local_piece)),
        str(move.get("smoothing", "")),
    )


def render_additional_branch_pictures(
    x_graph: Dict[str, Any],
    w_graph: Dict[str, Any],
    x_adj: wrench.Adjacency,
    x_hgs: List[wrench.Hourglass],
    w_adj: wrench.Adjacency,
    w_hgs: List[wrench.Hourglass],
    proof: Dict[str, Any],
    displayed_history: List[Dict[str, Any]],
    *,
    limit: int = 40,
) -> str:
    discharged_terms = proof.get("discharged_terms", [])
    if not discharged_terms:
        return ""

    displayed_keys = [move_key_for_display(move) for move in displayed_history]
    candidates = []
    for idx, term in enumerate(discharged_terms, start=1):
        history = term.get("history", [])
        history_keys = [move_key_for_display(move) for move in history]
        if history_keys == displayed_keys:
            continue
        candidates.append((idx, term, history, history_keys))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: (len(item[2]), item[0]), reverse=True)
    cards = []
    hidden_count = max(0, len(candidates) - limit)
    for idx, term, history, _history_keys in candidates[:limit]:
        try:
            branch_x, branch_xh, branch_w, branch_wh = wrench.replay_pair_history(
                x_adj,
                x_hgs,
                w_adj,
                w_hgs,
                history,
            )
        except Exception as exc:  # noqa: BLE001 - this is a diagnostic display.
            cards.append(
                f"""
                <div class="pair-card">
                  <div class="pair-title">Branch {idx}</div>
                  <div class="pair-note">Could not replay this branch for display: {html.escape(str(exc))}</div>
                </div>
                """
            )
            continue

        common_forks = term.get("common_forks", [])
        fork = common_forks[0] if common_forks else None
        last_move = history[-1] if history else {}
        last_text = (
            f"{last_move.get('side', '?')} {last_move.get('hourglass', [])} "
            f"{last_move.get('smoothing', '')}"
        ).strip()
        cards.append(
            f"""
            <div class="pair-card">
              <div class="pair-title">Fork-killed branch {idx}</div>
              <div class="pair-note">history length {len(history)}; coeff {html.escape(str(term.get('coeff', '')))}; fork(s): {html.escape(str(common_forks))}</div>
              <div class="pair-note">last move: {html.escape(last_text)}</div>
              <div class="mini-pair">
                {draw_web_svg('W', w_graph, branch_w, branch_wh, highlight_fork=fork, size=250)}
                {draw_web_svg('X', x_graph, branch_x, branch_xh, highlight_fork=fork, size=250)}
              </div>
            </div>
            """
        )

    hidden_note = (
        f"<p class=\"muted\">Showing {limit} of {len(candidates)} off-path discharged branches; {hidden_count} more are omitted to keep the page responsive.</p>"
        if hidden_count
        else f"<p class=\"muted\">Showing all {len(candidates)} off-path discharged branches.</p>"
    )
    return f"""
    <section class="step">
      <div class="step-head">
        <div><strong>Additional Fork-Killed Branches</strong></div>
        <div class="muted">These are real proof branches not lying on the single displayed continuing path.</div>
      </div>
      <p>The main trace follows one branch path. The full proof also expands sibling branches; those later branch endpoints are replayed here as pictures.</p>
      {hidden_note}
      <div class="grid two">{''.join(cards)}</div>
    </section>
    """


def phase_display_label(phase: str) -> str:
    if phase == "figure43":
        return "Figure 43"
    if phase == "antisymmetrizer":
        return "white-black antisymmetrizer"
    if phase == "w_expansion_fallback":
        return "W fallback"
    return "main search"


def move_piece_label(move: Dict[str, Any]) -> str:
    phase = str(move.get("phase", "main_search"))
    if phase == "figure43":
        return "Figure 43 piece"
    if phase == "antisymmetrizer":
        return "white-black pair"
    return "hourglass"


def relation_before_highlights(
    move: Dict[str, Any],
    side: str,
) -> Tuple[Dict[Tuple[int, int], str], Dict[int, str]]:
    """Highlight the complete local structure removed by a relation.

    For the white-black antisymmetrizer this is the central edge together with
    the three incident arms at each endpoint.  Keeping this construction in one
    helper ensures the main trace, branch pages, and lazy move pages all mark
    the same seven-edge local piece.
    """
    if move.get("phase") != "antisymmetrizer" or str(move.get("side", "X")) != side:
        return {}, {}

    white = int(move["white"])
    black = int(move["black"])
    input_ports = [int(port) for port in move.get("input_ports", [])]
    output_ports = [int(port) for port in move.get("output_ports", [])]
    color = "#cf2f2f"
    edges = {tuple(sorted((white, black))): color}
    edges.update({tuple(sorted((white, port))): color for port in input_ports})
    edges.update({tuple(sorted((black, port))): color for port in output_ports})
    nodes = {node: color for node in {white, black, *input_ports, *output_ports}}
    return edges, nodes


def move_sequence_table(history: List[Dict[str, Any]]) -> str:
    if not history:
        return '<p class="muted">No skein moves were applied on this branch.</p>'
    rows = []
    running_coeff = 1
    for idx, move in enumerate(history, start=1):
        smoothing = str(move.get("smoothing", ""))
        multiplier = int(move.get("coefficient_multiplier", wrench.move_multiplier(smoothing)))
        untwist_count = int(move.get("untwist_count", 0) or 0)
        branch_label = smoothing + (f"; untwist x{untwist_count}" if untwist_count else "")
        if move.get("phase") == "antisymmetrizer" and move.get("permutation_label"):
            branch_label += f" = {move['permutation_label']}"
        deferred_count = int(move.get("deferred_untwist_count", 0) or 0)
        if deferred_count:
            branch_label += (
                f"; defer untwist x{deferred_count} to coloring "
                f"({int(move.get('deferred_untwist_multiplier', 1)):+d})"
            )
        paper_multiplier = move.get("paper_coefficient_multiplier")
        tag_multiplier = int(move.get("tag_transport_multiplier", 1))
        if paper_multiplier is not None:
            branch_label += (
                f"; paper {int(paper_multiplier):+d}, tag transport {tag_multiplier:+d}, "
                f"effective {multiplier:+d}"
            )
        elif move.get("phase") == "antisymmetrizer" and not deferred_count:
            branch_label += f"; terminal tag transport {tag_multiplier:+d}"
        running_coeff *= multiplier
        phase = str(move.get("phase", "main_search"))
        phase_label = phase_display_label(phase)
        target = move.get("hourglass", move.get("vertices", []))
        rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{html.escape(phase_label)}</td>"
            f"<td>{html.escape(str(move.get('side', '')))}</td>"
            f"<td>{html.escape(str(target))}</td>"
            f"<td>{html.escape(branch_label)}</td>"
            f"<td>{multiplier:+d}</td>"
            f"<td>{running_coeff:+d}</td>"
            "</tr>"
        )
    return f"""
    <table class="step-table branch-moves">
      <thead>
        <tr><th>#</th><th>phase</th><th>web</th><th>local piece</th><th>branch</th><th>sign</th><th>running coeff</th></tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def history_sign(history: List[Dict[str, Any]]) -> int:
    sign = 1
    for move in history:
        smoothing = str(move.get("smoothing", ""))
        sign *= int(move.get("coefficient_multiplier", wrench.move_multiplier(smoothing)))
    return sign


def coefficient_explanation(record: Dict[str, Any]) -> str:
    history = record.get("history", [])
    path_sign = history_sign(history)
    try:
        coeff = int(record.get("coeff", path_sign))
    except (TypeError, ValueError):
        return ""
    if path_sign == 0:
        return ""
    if coeff == path_sign:
        return (
            f'<p class="muted"><strong>Coefficient check:</strong> the product of the displayed skein signs is '
            f'<span class="word">{path_sign:+d}</span>, matching the branch coefficient.</p>'
        )
    if coeff % path_sign == 0:
        multiplicity = coeff // path_sign
        return (
            f'<p class="muted"><strong>Coefficient check:</strong> the displayed path has sign '
            f'<span class="word">{path_sign:+d}</span>. The stored coefficient is '
            f'<span class="word">{coeff:+d}</span> because <span class="word">{abs(multiplicity)}</span> '
            f'equivalent branch path(s) reached the same W/X state and were consolidated: '
            f'<span class="word">{path_sign:+d} x {multiplicity:+d} = {coeff:+d}</span>.</p>'
        )
    return (
        f'<p class="muted"><strong>Coefficient check:</strong> the displayed path sign is '
        f'<span class="word">{path_sign:+d}</span>, while the consolidated branch coefficient is '
        f'<span class="word">{coeff:+d}</span>.</p>'
    )


def branch_terminal_picture(
    x_graph: Dict[str, Any],
    w_graph: Dict[str, Any],
    x_adj: wrench.Adjacency,
    x_hgs: List[wrench.Hourglass],
    w_adj: wrench.Adjacency,
    w_hgs: List[wrench.Hourglass],
    history: List[Dict[str, Any]],
    fork: Optional[List[int]],
) -> str:
    try:
        branch_x, branch_xh, branch_w, branch_wh = wrench.replay_pair_history(
            x_adj,
            x_hgs,
            w_adj,
            w_hgs,
            history,
        )
    except Exception as exc:  # noqa: BLE001 - this is a display diagnostic.
        return f'<p class="muted">Could not replay this branch picture: {html.escape(str(exc))}</p>'
    x_curves = wrench.edge_curves_from_history(history, "X", branch_x)
    w_curves = wrench.edge_curves_from_history(history, "W", branch_w)
    return f"""
    <div class="mini-pair branch-terminal-pair">
      {draw_web_svg('W terminal state', w_graph, branch_w, branch_wh, highlight_fork=fork, edge_curves=w_curves, size=270)}
      {draw_web_svg('X terminal state', x_graph, branch_x, branch_xh, highlight_fork=fork, edge_curves=x_curves, size=270)}
    </div>
    """


def branch_move_picture(
    x_graph: Dict[str, Any],
    w_graph: Dict[str, Any],
    x_adj: wrench.Adjacency,
    x_hgs: List[wrench.Hourglass],
    w_adj: wrench.Adjacency,
    w_hgs: List[wrench.Hourglass],
    history: List[Dict[str, Any]],
    move_index: int,
) -> str:
    if move_index < 1 or move_index > len(history):
        return f'<p class="muted">Move {move_index} is not in this branch.</p>'
    move = history[move_index - 1]
    prefix_before = history[: move_index - 1]
    prefix_after = history[:move_index]
    try:
        before_x, before_xh, before_w, before_wh = wrench.replay_pair_history(
            x_adj,
            x_hgs,
            w_adj,
            w_hgs,
            prefix_before,
        )
        after_x, after_xh, after_w, after_wh = wrench.replay_pair_history(
            x_adj,
            x_hgs,
            w_adj,
            w_hgs,
            prefix_after,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic display only.
        return f'<p class="muted">Could not replay this move for display: {html.escape(str(exc))}</p>'

    is_figure43 = move.get("phase") == "figure43"
    selected = tuple(sorted(int(x) for x in move.get("hourglass", [])))
    local_piece = move.get("vertices", list(selected))
    side = str(move.get("side", ""))
    smoothing = str(move.get("smoothing", ""))
    if move.get("phase") == "antisymmetrizer" and move.get("permutation_label"):
        smoothing += f" = {move['permutation_label']}"
    phase = str(move.get("phase", "main_search"))
    phase_label = phase_display_label(phase)
    before_x_curves = wrench.edge_curves_from_history(prefix_before, "X", before_x)
    before_w_curves = wrench.edge_curves_from_history(prefix_before, "W", before_w)
    after_x_curves = wrench.edge_curves_from_history(prefix_after, "X", after_x)
    after_w_curves = wrench.edge_curves_from_history(prefix_after, "W", after_w)
    untwist_count = int(move.get("untwist_count", 0) or 0)
    untwist_note = (
        f"; {untwist_count} shared-leaf untwist(s), sign {int(move.get('untwist_multiplier', 1)):+d}"
        if untwist_count
        else ""
    )
    deferred_count = int(move.get("deferred_untwist_count", 0) or 0)
    if deferred_count:
        untwist_note += (
            f"; preserve cyclic order now, defer {deferred_count} untwist(s) "
            f"to coloring with sign {int(move.get('deferred_untwist_multiplier', 1)):+d}"
        )
    new_x = edge_set(after_x) - edge_set(before_x)
    new_w = edge_set(after_w) - edge_set(before_w)
    before_w_highlight_edges, before_w_highlight_nodes = relation_before_highlights(move, "W")
    before_x_highlight_edges, before_x_highlight_nodes = relation_before_highlights(move, "X")
    return f"""
    <div class="branch-move-picture">
      <h4>Move {move_index}: {html.escape(phase_label)} applies {html.escape(side)} {move_piece_label(move)} {html.escape(str(local_piece))} as {html.escape(smoothing + untwist_note)}</h4>
      {render_pre_untwist_stage(move, x_graph, w_graph, before_x, before_xh, before_w, before_wh)}
      <div class="grid four">
        {draw_web_svg('Before W', w_graph, before_w, before_wh, selected_hg=None if move.get("phase") in {"figure43", "antisymmetrizer"} else (selected if side == 'W' else None), highlight_edges=before_w_highlight_edges, node_ring_colors=before_w_highlight_nodes, edge_curves=before_w_curves, size=250)}
        {draw_web_svg('Before X', x_graph, before_x, before_xh, selected_hg=None if move.get("phase") in {"figure43", "antisymmetrizer"} else (selected if side == 'X' else None), highlight_edges=before_x_highlight_edges, node_ring_colors=before_x_highlight_nodes, edge_curves=before_x_curves, size=250)}
        {draw_web_svg('After W', w_graph, after_w, after_wh, edge_colors={e: '#2586d8' for e in new_w}, edge_curves=after_w_curves, size=250)}
        {draw_web_svg('After X', x_graph, after_x, after_xh, edge_colors={e: '#2586d8' for e in new_x}, edge_curves=after_x_curves, size=250)}
      </div>
    </div>
    """


def render_pre_untwist_stage(
    move: Dict[str, Any],
    x_graph: Dict[str, Any],
    w_graph: Dict[str, Any],
    before_x: wrench.Adjacency,
    before_xh: List[wrench.Hourglass],
    before_w: wrench.Adjacency,
    before_wh: List[wrench.Hourglass],
) -> str:
    """Show the tangent-preserving stage before a signed local untwist."""
    untwist_count = int(move.get("untwist_count", 0) or 0)
    if not untwist_count or move.get("phase") in {"figure43", "antisymmetrizer"}:
        return ""
    side = str(move.get("side", "X"))
    selected = tuple(sorted(int(v) for v in move.get("hourglass", [])))
    adj = before_x if side == "X" else before_w
    hgs = before_xh if side == "X" else before_wh
    graph = x_graph if side == "X" else w_graph
    try:
        hg = next(
            candidate
            for candidate in hgs
            if tuple(sorted((int(candidate["white"]), int(candidate["black"])))) == selected
        )
        _nodes, node_xy, _boundary, _label_to_node = node_maps(graph)
        tangent_adj, embedding = wrench.smooth_one_hourglass_embedded(
            adj,
            hg,
            str(move.get("smoothing", "")),
            node_xy=node_xy,
            forced_untwists=[],
        )
        tangent_hgs = wrench.remaining_after_move(hgs, hg)
        tangent_new = edge_set(tangent_adj) - edge_set(adj)
        tangent_curves = move_edge_curves(embedding)
        tangent_curves = clarify_pre_untwist_curves(move, tangent_curves)
    except Exception as exc:  # noqa: BLE001 - diagnostic display only.
        return f'<p class="muted">Could not display the pre-untwist tangent stage: {html.escape(str(exc))}</p>'
    picture = draw_web_svg(
        f'Tangent replacement before untwist ({side})',
        graph,
        tangent_adj,
        tangent_hgs,
        edge_colors={edge: "#2586d8" for edge in tangent_new},
        edge_curves=tangent_curves,
        subtitle="Cyclic order is still the original one",
        size=250,
    )
    return f"""
    <div class="untwist-stage">
      <p><strong>Two-stage embedding:</strong> The picture below first places each replacement cubic in the half-edge slot of the deleted wrench edge, so its tangent and local cyclic order are preserved. The later <em>After</em> picture is the untwisted representative: the indicated incident slots are transposed and contribute the displayed sign {int(move.get('untwist_multiplier', 1)):+d}.</p>
      <div class="grid four">{picture}</div>
    </div>
    """


def branch_process_pictures(
    x_graph: Dict[str, Any],
    w_graph: Dict[str, Any],
    x_adj: wrench.Adjacency,
    x_hgs: List[wrench.Hourglass],
    w_adj: wrench.Adjacency,
    w_hgs: List[wrench.Hourglass],
    history: List[Dict[str, Any]],
) -> str:
    if not history:
        return '<p class="muted">There are no relation steps before this terminal state.</p>'

    blocks = []
    for idx, move in enumerate(history, start=1):
        prefix_before = history[: idx - 1]
        prefix_after = history[:idx]
        try:
            before_x, before_xh, before_w, before_wh = wrench.replay_pair_history(
                x_adj,
                x_hgs,
                w_adj,
                w_hgs,
                prefix_before,
            )
            after_x, after_xh, after_w, after_wh = wrench.replay_pair_history(
                x_adj,
                x_hgs,
                w_adj,
                w_hgs,
                prefix_after,
            )
        except Exception as exc:  # noqa: BLE001 - diagnostic display only.
            blocks.append(
                f"""
                <div class="branch-move-picture">
                  <h4>Move {idx}</h4>
                  <p class="muted">Could not replay this move for display: {html.escape(str(exc))}</p>
                </div>
                """
            )
            continue

        is_figure43 = move.get("phase") == "figure43"
        selected = tuple(sorted(int(x) for x in move.get("hourglass", [])))
        local_piece = move.get("vertices", list(selected))
        side = str(move.get("side", ""))
        smoothing = str(move.get("smoothing", ""))
        phase = str(move.get("phase", "main_search"))
        phase_label = phase_display_label(phase)
        before_x_curves = wrench.edge_curves_from_history(prefix_before, "X", before_x)
        before_w_curves = wrench.edge_curves_from_history(prefix_before, "W", before_w)
        after_x_curves = wrench.edge_curves_from_history(prefix_after, "X", after_x)
        after_w_curves = wrench.edge_curves_from_history(prefix_after, "W", after_w)
        untwist_count = int(move.get("untwist_count", 0) or 0)
        untwist_note = (
            f"; {untwist_count} shared-leaf untwist(s), sign {int(move.get('untwist_multiplier', 1)):+d}"
            if untwist_count
            else ""
        )
        deferred_count = int(move.get("deferred_untwist_count", 0) or 0)
        if deferred_count:
            untwist_note += (
                f"; preserve cyclic order now, defer {deferred_count} untwist(s) "
                f"to coloring with sign {int(move.get('deferred_untwist_multiplier', 1)):+d}"
            )
        new_x = edge_set(after_x) - edge_set(before_x)
        new_w = edge_set(after_w) - edge_set(before_w)
        before_w_highlight_edges, before_w_highlight_nodes = relation_before_highlights(move, "W")
        before_x_highlight_edges, before_x_highlight_nodes = relation_before_highlights(move, "X")
        blocks.append(
            f"""
            <div class="branch-move-picture">
              <h4>Move {idx}: {html.escape(phase_label)} applies {html.escape(side)} {move_piece_label(move)} {html.escape(str(local_piece))} as {html.escape(smoothing + untwist_note)}</h4>
              {render_pre_untwist_stage(move, x_graph, w_graph, before_x, before_xh, before_w, before_wh)}
              <div class="grid four">
                {draw_web_svg('Before W', w_graph, before_w, before_wh, selected_hg=None if move.get("phase") in {"figure43", "antisymmetrizer"} else (selected if side == 'W' else None), highlight_edges=before_w_highlight_edges, node_ring_colors=before_w_highlight_nodes, edge_curves=before_w_curves, size=250)}
                {draw_web_svg('Before X', x_graph, before_x, before_xh, selected_hg=None if move.get("phase") in {"figure43", "antisymmetrizer"} else (selected if side == 'X' else None), highlight_edges=before_x_highlight_edges, node_ring_colors=before_x_highlight_nodes, edge_curves=before_x_curves, size=250)}
                {draw_web_svg('After W', w_graph, after_w, after_wh, edge_colors={e: '#2586d8' for e in new_w}, edge_curves=after_w_curves, size=250)}
                {draw_web_svg('After X', x_graph, after_x, after_xh, edge_colors={e: '#2586d8' for e in new_x}, edge_curves=after_x_curves, size=250)}
              </div>
            </div>
            """
        )

    return f"""
    <div class="branch-process-pictures">
      <h3>Relation Pictures Along This Branch</h3>
      <p class="muted">Blue edges are the new smoothing edges created by that particular relation choice.</p>
      {''.join(blocks)}
    </div>
    """


def move_sequence_table_lazy(history: List[Dict[str, Any]], branch_id: str) -> str:
    if not history:
        return '<p class="muted">No skein moves were applied on this branch.</p>'
    rows = []
    running_coeff = 1
    for idx, move in enumerate(history, start=1):
        smoothing = str(move.get("smoothing", ""))
        multiplier = int(move.get("coefficient_multiplier", wrench.move_multiplier(smoothing)))
        untwist_count = int(move.get("untwist_count", 0) or 0)
        branch_label = smoothing + (f"; untwist x{untwist_count}" if untwist_count else "")
        if move.get("phase") == "antisymmetrizer" and move.get("permutation_label"):
            branch_label += f" = {move['permutation_label']}"
        deferred_count = int(move.get("deferred_untwist_count", 0) or 0)
        if deferred_count:
            branch_label += (
                f"; defer untwist x{deferred_count} to coloring "
                f"({int(move.get('deferred_untwist_multiplier', 1)):+d})"
            )
        paper_multiplier = move.get("paper_coefficient_multiplier")
        tag_multiplier = int(move.get("tag_transport_multiplier", 1))
        if paper_multiplier is not None:
            branch_label += (
                f"; paper {int(paper_multiplier):+d}, tag transport {tag_multiplier:+d}, "
                f"effective {multiplier:+d}"
            )
        elif move.get("phase") == "antisymmetrizer" and not deferred_count:
            branch_label += f"; terminal tag transport {tag_multiplier:+d}"
        running_coeff *= multiplier
        phase = str(move.get("phase", "main_search"))
        phase_label = phase_display_label(phase)
        target = move.get("hourglass", move.get("vertices", []))
        rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{html.escape(phase_label)}</td>"
            f"<td>{html.escape(str(move.get('side', '')))}</td>"
            f"<td>{html.escape(str(target))}</td>"
            f"<td>{html.escape(branch_label)}</td>"
            f"<td>{multiplier:+d}</td>"
            f"<td>{running_coeff:+d}</td>"
            f"<td><button class=\"tiny load-branch-view\" type=\"button\" data-branch=\"{html.escape(branch_id)}\" data-move=\"{idx}\">show pictures</button></td>"
            "</tr>"
        )
    return f"""
    <table class="step-table branch-moves">
      <thead>
        <tr><th>#</th><th>phase</th><th>web</th><th>local piece</th><th>branch</th><th>sign</th><th>running coeff</th><th>pictures</th></tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def terminal_branch_records(proof: Dict[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for idx, term in enumerate(proof.get("discharged_terms", []), start=1):
        records.append(
            {
                "id": f"K{idx:03d}",
                "kind": "fork lemma",
                "status": "killed",
                "coeff": term.get("coeff", ""),
                "value": 0,
                "history": term.get("history", []),
                "forks": term.get("common_forks", []),
                "reason": term.get("reason", "fork_lemma"),
                "raw": term,
            }
        )

    direct_coloring_evaluations = list(proof.get("coloring_evaluations", []))
    if direct_coloring_evaluations:
        for idx, term in enumerate(direct_coloring_evaluations, start=1):
            status = str(term.get("status", ""))
            value = term.get("term_value")
            records.append(
                {
                    "id": f"C{idx:03d}",
                    "kind": "coloring",
                    "status": "colored" if value is not None else "not computed",
                    "coeff": term.get("coeff", ""),
                    "value": value,
                    "history": term.get("history", []),
                    "forks": term.get("common_forks", []),
                    "reason": term.get("reason", status),
                    "coloring_count": term.get("coloring_count"),
                    "orientation_sign": term.get("source_orientation_sign", 1),
                    "signed_coloring_count": term.get(
                        "signed_coloring_count", term.get("coloring_count")
                    ),
                    "raw": term,
                }
            )

    fallback = proof.get("w_expansion_fallback", {})
    fallback_evaluations = list(fallback.get("branch_evaluations", []))
    for idx, term in enumerate(fallback.get("branch_evaluations", []), start=1):
        status = str(term.get("status", ""))
        if status == "fork_killed":
            kind = "fork lemma after W expansion"
            terminal_status = "killed"
            value = 0
        elif term.get("term_value") is not None:
            kind = "coloring"
            terminal_status = "colored"
            value = term.get("term_value")
        else:
            kind = "coloring"
            terminal_status = "not computed"
            value = None
        records.append(
            {
                "id": f"C{idx:03d}",
                "kind": kind,
                "status": terminal_status,
                "coeff": term.get("coeff", ""),
                "value": value,
                "history": term.get("history", []),
                "forks": term.get("common_forks", []),
                "reason": term.get("reason", status),
                "coloring_count": term.get("coloring_count"),
                "orientation_sign": term.get("source_orientation_sign", 1),
                "signed_coloring_count": term.get(
                    "signed_coloring_count", term.get("coloring_count")
                ),
                "raw": term,
            }
        )

    show_unresolved_active_terms = (
        proof.get("status") == "partial"
        and not fallback_evaluations
    )
    if fallback.get("status") == "not_computed" and not fallback_evaluations:
        show_unresolved_active_terms = True

    for idx, term in enumerate(proof.get("active_terms", []) if show_unresolved_active_terms else [], start=1):
        records.append(
            {
                "id": f"A{idx:03d}",
                "kind": "unresolved",
                "status": "active",
                "coeff": term.get("coeff", ""),
                "value": None,
                "history": term.get("history", []),
                "forks": term.get("common_forks", []),
                "reason": "branch still active",
                "raw": term,
            }
        )

    records.sort(key=lambda item: (len(item.get("history", [])), str(item.get("id", ""))))
    return records


def proof_used_three_strand_relation(proof: Dict[str, Any]) -> bool:
    """Return whether this particular proof used the three-strand relation."""
    def contains_relation(value: Any) -> bool:
        if isinstance(value, dict):
            if value.get("phase") == "antisymmetrizer":
                return True
            if value.get("expanded_relation") == "antisymmetrizer":
                return True
            if value.get("rule") == "WB_4VALENT_ANTISYMMETRIZER":
                return True
            return any(contains_relation(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(contains_relation(item) for item in value)
        return False

    return contains_relation(proof)


def final_active_branch_count(proof: Dict[str, Any]) -> int:
    """Count branches still unresolved after the full pipeline, not before fallback."""
    if proof.get("status") != "partial":
        return 0
    fallback = proof.get("w_expansion_fallback", {})
    evaluations = fallback.get("branch_evaluations", [])
    if evaluations:
        return sum(1 for item in evaluations if item.get("term_value") is None and item.get("status") != "fork_killed")
    return int(proof.get("active_term_count", 0) or 0)


def render_branch_ledger_section(
    x_graph: Dict[str, Any],
    w_graph: Dict[str, Any],
    x_adj: wrench.Adjacency,
    x_hgs: List[wrench.Hourglass],
    w_adj: wrench.Adjacency,
    w_hgs: List[wrench.Hourglass],
    proof: Dict[str, Any],
    params: Dict[str, str],
) -> str:
    records = terminal_branch_records(proof)
    if not records:
        return ""

    rows = []
    for record in records:
        history = record.get("history", [])
        forks = record.get("forks", [])
        value = record.get("value")
        value_text = "None" if value is None else str(value)
        branch_params = dict(params)
        branch_params["branch_id"] = str(record["id"])
        branch_href = "/branch?" + urllib.parse.urlencode(branch_params)
        branch_link = f'<a class="branch-link" href="{html.escape(branch_href)}">{html.escape(str(record["id"]))}</a>'
        details = f'<a class="tiny-link" href="{html.escape(branch_href)}">open branch page</a>'
        rows.append(
            "<tr>"
            f"<td>{branch_link}</td>"
            f"<td>{len(history)}</td>"
            f"<td>{html.escape(str(record.get('kind', '')))}</td>"
            f"<td>{html.escape(str(record.get('status', '')))}</td>"
            f"<td>{html.escape(str(record.get('coeff', '')))}</td>"
            f"<td>{html.escape(value_text)}</td>"
            f"<td>{html.escape(str(forks))}</td>"
            f"<td>{details}</td>"
            "</tr>"
        )

    contributing = [record for record in records if record.get("coloring_count") is not None]
    if contributing:
        pieces = [
            f"({record.get('coeff')})*({record.get('orientation_sign', 1)})*{record.get('coloring_count')}"
            for record in contributing
        ]
        total_value = sum(int(record.get("value") or 0) for record in contributing)
        combo = (" + ".join(pieces).replace("+ (-", "- (") + f" = {total_value}")
    elif any(record.get("value") == 0 for record in records):
        combo = "0"
    else:
        combo = "all displayed terminal branches currently have no computed value"

    return f"""
    <section class="step branch-ledger">
      <div class="step-head">
        <div><strong>Branch Ledger</strong></div>
        <div class="muted">Every terminal/open branch is listed; click a branch to open its full picture page.</div>
      </div>
      <p><strong>Linear combination:</strong> <span class="word">{html.escape(combo)}</span></p>
      <table class="step-table branch-ledger-table">
        <thead>
          <tr><th>branch</th><th>moves</th><th>terminal rule</th><th>status</th><th>coeff</th><th>value</th><th>fork(s)</th><th>details</th></tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """


def compute_pair_context(params: Dict[str, str]) -> Dict[str, Any]:
    x_path, w_path, pair_mode = resolve_pair(params)
    x_word = graph_word(x_path)
    max_steps_raw = params.get("max_steps", "").strip()
    max_steps = None if max_steps_raw in {"", "auto", "8"} else int(max_steps_raw)
    beam_width = int(params.get("beam_width", "120") or "120")

    allow_w = False


    x_adj, x_bounds, x_hgs = wrench.parse_web(x_path)
    w_adj, w_bounds, w_hgs = wrench.parse_web(w_path)
    x_node_colors, x_node_xy = wrench.parse_web_metadata(x_path)
    w_node_colors, w_node_xy = wrench.parse_web_metadata(w_path)
    x_hgs = wrench.sort_hourglasses_by_boundary_distance(x_adj, x_bounds, x_hgs)
    w_hgs = wrench.sort_hourglasses_by_boundary_distance(w_adj, w_bounds, w_hgs)
    proof = wrench.prove_pair_value_complete_pipeline(
        x_adj,
        x_bounds,
        x_hgs,
        w_adj,
        w_bounds,
        w_hgs,
        allow_w_wrench=allow_w,
        guided_beam_width=beam_width,
        x_beam_width=max(500, beam_width),
        guided_steps=max_steps,
        x_resolution_steps=None,
        max_w_expansions_per_branch=16,
        x_node_colors=x_node_colors,
        x_node_xy=x_node_xy,
        w_node_colors=w_node_colors,
        w_node_xy=w_node_xy,
        source_web_sign=wrench.word_inversion_sign(x_word),
    )
    if max_steps is not None and proof.get("active_term_count", 0):
        auto_proof = wrench.prove_pair_value_complete_pipeline(
            x_adj,
            x_bounds,
            x_hgs,
            w_adj,
            w_bounds,
            w_hgs,
            allow_w_wrench=allow_w,
            guided_beam_width=beam_width,
            x_beam_width=max(500, beam_width),
            guided_steps=None,
            x_resolution_steps=None,
            max_w_expansions_per_branch=16,
            x_node_colors=x_node_colors,
            x_node_xy=x_node_xy,
            w_node_colors=w_node_colors,
            w_node_xy=w_node_xy,
            source_web_sign=wrench.word_inversion_sign(x_word),
        )
        auto_proof["auto_continued_from_step_cap"] = max_steps
        proof = auto_proof

    x_graph = load_json(x_path)
    w_graph = load_json(w_path)
    return {
        "x_path": x_path,
        "w_path": w_path,
        "pair_mode": pair_mode,
        "x_adj": x_adj,
        "w_adj": w_adj,
        "x_bounds": x_bounds,
        "w_bounds": w_bounds,
        "x_hgs": x_hgs,
        "w_hgs": w_hgs,
        "proof": proof,
        "x_graph": x_graph,
        "w_graph": w_graph,
    }


def render_branch_view(params: Dict[str, str]) -> str:
    context = compute_pair_context(params)
    branch_id = params.get("branch_id", "").strip()
    move_raw = params.get("move", "").strip()
    records = terminal_branch_records(context["proof"])
    record = next((item for item in records if str(item.get("id")) == branch_id), None)
    if record is None:
        return f'<p class="muted">Could not find branch {html.escape(branch_id)}.</p>'

    history = record.get("history", [])
    if move_raw == "terminal":
        forks = record.get("forks", [])
        fork = forks[0] if forks else None
        raw = record.get("raw", {})
        terminal = branch_terminal_picture(
            context["x_graph"],
            context["w_graph"],
            context["x_adj"],
            context["x_hgs"],
            context["w_adj"],
            context["w_hgs"],
            history,
            fork,
        )
        if raw.get("term_value") is not None:
            coloring = render_coloring_section(
                context["x_graph"],
                context["w_graph"],
                context["x_bounds"],
                context["w_bounds"],
                context["x_adj"],
                context["w_adj"],
                context["x_hgs"],
                context["w_hgs"],
                {
                    "linear_combination_terms": [raw],
                    "final_pairing_value": raw.get("term_value"),
                    "status": "computed",
                    "active_term_count": 0,
                    "coloring_evaluations": [],
                },
            )
            return terminal + coloring
        return terminal

    try:
        move_index = int(move_raw)
    except ValueError:
        return f'<p class="muted">Unknown branch view request: {html.escape(move_raw)}</p>'

    return branch_move_picture(
        context["x_graph"],
        context["w_graph"],
        context["x_adj"],
        context["x_hgs"],
        context["w_adj"],
        context["w_hgs"],
        history,
        move_index,
    )


def render_branch_page(params: Dict[str, str]) -> str:
    context = compute_pair_context(params)
    branch_id = params.get("branch_id", "").strip()
    records = terminal_branch_records(context["proof"])
    record = next((item for item in records if str(item.get("id")) == branch_id), None)
    run_params = {k: v for k, v in params.items() if k not in {"branch_id", "move"}}
    back_href = "/run?" + urllib.parse.urlencode(run_params)
    if record is None:
        return page_shell(
            params,
            f"""
            <section class="summary">
              <div>
                <h2>Branch Not Found</h2>
                <p>Could not find branch <span class="word">{html.escape(branch_id)}</span>.</p>
                <p><a href="{html.escape(back_href)}">Back to Branch Ledger</a></p>
              </div>
            </section>
            """,
        )

    history = record.get("history", [])
    forks = record.get("forks", [])
    fork = forks[0] if forks else None
    raw = record.get("raw", {})
    count_text = ""
    if record.get("coloring_count") is not None:
        count_text = (
            f"; tagged source sign {record.get('orientation_sign', 1)}"
            f"; coloring count {record.get('coloring_count')}"
        )

    terminal = branch_terminal_picture(
        context["x_graph"],
        context["w_graph"],
        context["x_adj"],
        context["x_hgs"],
        context["w_adj"],
        context["w_hgs"],
        history,
        fork,
    )
    coloring = ""
    if raw.get("term_value") is not None:
        coloring = render_coloring_section(
            context["x_graph"],
            context["w_graph"],
            context["x_bounds"],
            context["w_bounds"],
            context["x_adj"],
            context["w_adj"],
            context["x_hgs"],
            context["w_hgs"],
            {
                "linear_combination_terms": [raw],
                "final_pairing_value": raw.get("term_value"),
                "status": "computed",
                "active_term_count": 0,
                "coloring_evaluations": [],
            },
        )

    return page_shell(
        params,
        f"""
        <section class="summary">
          <div>
            <h2>Branch {html.escape(branch_id)}</h2>
            <p><a href="{html.escape(back_href)}">Back to Branch Ledger</a></p>
            <p><strong>Terminal relation:</strong> {html.escape(str(record.get('kind', '')))}. <span class="muted">{html.escape(str(record.get('reason', '')))}{html.escape(count_text)}</span></p>
            <p><strong>Status:</strong> {html.escape(str(record.get('status', '')))} &nbsp; <strong>Coefficient:</strong> {html.escape(str(record.get('coeff', '')))} &nbsp; <strong>Value:</strong> {html.escape(str(record.get('value', 'None')))}</p>
            {coefficient_explanation(record)}
          </div>
        </section>
        <section class="step">
          <div class="step-head">
            <div><strong>Move Sequence</strong></div>
            <div class="muted">This is the complete sequence along this branch.</div>
          </div>
          {move_sequence_table(history)}
        </section>
        <section class="step">
          <div class="step-head">
            <div><strong>Branch Growth Pictures</strong></div>
            <div class="muted">Before/after pictures for every relation applied on this branch.</div>
          </div>
          {branch_process_pictures(context["x_graph"], context["w_graph"], context["x_adj"], context["x_hgs"], context["w_adj"], context["w_hgs"], history)}
        </section>
        <section class="step">
          <div class="step-head">
            <div><strong>Terminal Picture</strong></div>
            <div class="muted">Where this branch is killed, colored, or left unresolved.</div>
          </div>
          {terminal}
        </section>
        {coloring}
        """,
    )


def run_pair(params: Dict[str, str]) -> str:
    context = compute_pair_context(params)
    x_path = context["x_path"]
    w_path = context["w_path"]
    pair_mode = context["pair_mode"]
    x_adj = context["x_adj"]
    w_adj = context["w_adj"]
    x_bounds = context["x_bounds"]
    w_bounds = context["w_bounds"]
    x_hgs = context["x_hgs"]
    w_hgs = context["w_hgs"]
    proof = context["proof"]
    show_steps = params.get("show_steps") == "1"
    x_graph, w_graph, x_bounds, w_bounds, steps, final_x, final_w, final_xh, final_wh, displayed_history = reconstruct_run(
        x_path, w_path, proof
    )
    x_word = graph_word(x_path)
    w_word = graph_word(w_path)
    x_index = graph_index(x_path)
    w_index = graph_index(w_path)
    final_active_count = final_active_branch_count(proof)
    used_three_strand = proof_used_three_strand_relation(proof)
    three_strand_warning = ""
    if used_three_strand:
        three_strand_warning = (
            '<div class="relation-warning"><strong>Warning:</strong> '
            'the 3-strand relation was used to compute this pairing value.</div>'
        )
    branch_ledger_html = render_branch_ledger_section(
        x_graph,
        w_graph,
        x_adj,
        x_hgs,
        w_adj,
        w_hgs,
        proof,
        params,
    )

    step_html = []
    if show_steps:
        for idx, step in enumerate(steps, start=1):
            killed_forks = step["killed"].get("common_forks", [])
            sibling_status = step["killed"].get("status", "")
            fork = killed_forks[0] if sibling_status in {"fork_killed", "continued_then_fork_killed"} and killed_forks else None
            if sibling_status == "fork_killed":
                killed_title = "Killed branch by fork lemma"
                killed_note = f"fork(s): {html.escape(str(killed_forks))}, coeff {html.escape(str(step['killed'].get('coeff')))}"
                killed_branch_text = f"{html.escape(step['killed_smoothing'])} branch is killed"
                continue_title = "Continuing branch"
                continue_note = "new smoothing edges are blue"
            elif sibling_status == "continued_then_fork_killed":
                extra = int(step["killed"].get("continued_steps", 0) or 0)
                killed_title = "Other continuing branch"
                killed_note = f"after {extra} further move(s): fork(s): {html.escape(str(killed_forks))}, coeff {html.escape(str(step['killed'].get('coeff')))}"
                killed_branch_text = f"{html.escape(step['killed_smoothing'])} branch continues and is killed later"
                continue_title = "Displayed continuing branch"
                continue_note = "this is the branch followed in the trace"
            elif sibling_status == "continued_to_fallback":
                extra = int(step["killed"].get("continued_steps", 0) or 0)
                killed_title = "Other continuing branch"
                killed_note = f"after {extra} further move(s), this branch is evaluated by W-expansion/coloring, not by an immediate fork kill"
                killed_branch_text = f"{html.escape(step['killed_smoothing'])} branch continues to fallback"
                continue_title = "Displayed continuing branch"
                continue_note = "this is the branch followed in the trace"
            elif sibling_status == "continued_active":
                extra = int(step["killed"].get("continued_steps", 0) or 0)
                killed_title = "Other continuing branch"
                killed_note = f"after {extra} further move(s), no common fork kill was certified for this branch"
                killed_branch_text = f"{html.escape(step['killed_smoothing'])} branch remains active"
                continue_title = "Displayed continuing branch"
                continue_note = "this is the branch followed in the trace"
            else:
                killed_title = "Other branch not found in displayed path"
                killed_note = "This is not a fork-lemma kill; the full search/correction pipeline must continue or evaluate it."
                killed_branch_text = f"{html.escape(step['killed_smoothing'])} branch is not certified by fork lemma"
                continue_title = "Displayed continuing branch"
                continue_note = "this is the branch followed in the trace"
            selected = step["selected"]
            step_move = step.get("move", {})
            current_w_highlight_edges, current_w_highlight_nodes = relation_before_highlights(step_move, "W")
            current_x_highlight_edges, current_x_highlight_nodes = relation_before_highlights(step_move, "X")
            if step_move.get("phase") == "antisymmetrizer":
                step_action = (
                    f"apply {step['side']} white-black antisymmetrizer "
                    f"to vertices {list(selected)}"
                )
            else:
                step_action = f"expand {step['side']} hourglass {list(selected)}"
            if step.get("untwist_count"):
                continue_note += (
                    f"; {step['untwist_count']} shared-leaf untwist(s) contribute "
                    f"{step.get('untwist_multiplier', 1):+d}"
                )
            if step.get("deferred_untwist_count"):
                continue_note += (
                    f"; cyclic order is preserved here and {step['deferred_untwist_count']} "
                    f"untwist(s) are deferred to coloring, contributing "
                    f"{step.get('deferred_untwist_multiplier', 1):+d} there"
                )
            display_killed_w = step['killed_w']
            display_killed_x = step['killed_x']
            display_killed_wh = step['killed_wh']
            display_killed_xh = step['killed_xh']
            display_killed_new_w = step['killed_new_w']
            display_killed_new_x = step['killed_new_x']
            if sibling_status == "continued_then_fork_killed" and step["killed"].get("history"):
                try:
                    terminal_x, terminal_xh, terminal_w, terminal_wh = wrench.replay_pair_history(
                        x_adj,
                        x_hgs,
                        w_adj,
                        w_hgs,
                        step["killed"].get("history", []),
                    )
                    display_killed_w = terminal_w
                    display_killed_x = terminal_x
                    display_killed_wh = terminal_wh
                    display_killed_xh = terminal_xh
                    display_killed_new_w = set()
                    display_killed_new_x = set()
                    killed_title = "Later fork-killed branch"
                except Exception:
                    pass
            step_html.append(
                f"""
                <section class="step">
                  <div class="step-head">
                    <div><strong>Step {idx}</strong>: {html.escape(step_action)}</div>
                    <div class="muted">{html.escape(step['continue_smoothing'])} branch continues; {killed_branch_text}</div>
                  </div>
                  <div class="grid four">
                    {draw_web_svg('Current W', w_graph, step['current_w'], step['current_wh'], selected_hg=selected if step['side']=='W' and step_move.get('phase') != 'antisymmetrizer' else None, highlight_edges=current_w_highlight_edges, node_ring_colors=current_w_highlight_nodes)}
                    {draw_web_svg('Current X', x_graph, step['current_x'], step['current_xh'], selected_hg=selected if step['side']=='X' and step_move.get('phase') != 'antisymmetrizer' else None, highlight_edges=current_x_highlight_edges, node_ring_colors=current_x_highlight_nodes)}
                    <div class="pair-card">
                      <div class="pair-title">{killed_title}</div>
                      <div class="pair-note">{killed_note}</div>
                      <div class="mini-pair">
                        {draw_web_svg('W', w_graph, display_killed_w, display_killed_wh, highlight_fork=fork, edge_colors={e:'#2586d8' for e in display_killed_new_w}, edge_curves=step.get('killed_curves') if step['side']=='W' else None, size=250)}
                        {draw_web_svg('X', x_graph, display_killed_x, display_killed_xh, highlight_fork=fork, edge_colors={e:'#2586d8' for e in display_killed_new_x}, edge_curves=step.get('killed_curves') if step['side']=='X' else None, size=250)}
                      </div>
                    </div>
                    <div class="pair-card">
                      <div class="pair-title">{continue_title}</div>
                      <div class="pair-note">{continue_note}</div>
                      <div class="mini-pair">
                        {draw_web_svg('W', w_graph, step['continue_w'], step['continue_wh'], edge_colors={e:'#2586d8' for e in step['continue_new_w']}, edge_curves=step.get('continue_curves') if step['side']=='W' else None, size=250)}
                        {draw_web_svg('X', x_graph, step['continue_x'], step['continue_xh'], edge_colors={e:'#2586d8' for e in step['continue_new_x']}, edge_curves=step.get('continue_curves') if step['side']=='X' else None, size=250)}
                      </div>
                    </div>
                  </div>
                </section>
                """
            )
        if proof.get("status") == "proved_zero" and proof.get("active_term_count") == 0:
            step_html.append(
                f"""
                <section class="step">
                  <div class="step-head">
                    <div><strong>Trace Complete</strong></div>
                    <div class="muted">The displayed path has {len(steps)} wrench moves; the full proof discharged all branches.</div>
                  </div>
                  <p>No further continuing-branch pictures are shown because there is no surviving branch left to continue. The proof search killed {proof.get('discharged_term_count', 0)} branch(es) by the fork lemma and the final pairing value is 0.</p>
                </section>
                """
            )
    else:
        rows = []
        for idx, step in enumerate(steps, start=1):
            killed_forks = step["killed"].get("common_forks", [])
            sibling_status = step["killed"].get("status", "not_found")
            status_label = {
                "fork_killed": "fork-killed immediately",
                "continued_then_fork_killed": "continued, then fork-killed",
                "continued_to_fallback": "continued to W-expansion/coloring",
                "continued_active": "continued and remains active",
                "not_found": "not found on displayed path",
            }.get(sibling_status, str(sibling_status))
            extra = int(step["killed"].get("continued_steps", 0) or 0)
            extra_text = f" after {extra} further move(s)" if sibling_status == "continued_then_fork_killed" else ""
            rows.append(
                "<tr>"
                f"<td>{idx}</td>"
                f"<td>{html.escape(step['side'])}</td>"
                f"<td>{html.escape(str(list(step['selected'])))}</td>"
                f"<td>{html.escape(step['continue_smoothing'])}</td>"
                f"<td>{html.escape(step['killed_smoothing'])}</td>"
                f"<td>{html.escape(status_label + extra_text)}: {html.escape(str(killed_forks))}</td>"
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

    coloring_html = ""
    if not branch_ledger_html:
        coloring_html = render_coloring_section(
            x_graph,
            w_graph,
            x_bounds,
            w_bounds,
            final_x,
            final_w,
            final_xh,
            final_wh,
            proof,
        )
    relation_html = render_relation_rule_section(w_graph, x_graph)
    fallback = proof.get("w_expansion_fallback", {})
    fallback_note = ""
    if fallback:
        reason = fallback.get("reason", "")
        details = (
            f"W-expanded terms: {fallback.get('w_expanded_terms', 0)}; "
            f"W branches fork-killed: {fallback.get('w_expanded_fork_killed', 0)}; "
            f"direct W-coloring terms: {fallback.get('w_direct_colored_terms', 0)}"
        )
        fallback_note = (
            f'<p class="muted"><strong>Complete pipeline:</strong> {html.escape(str(fallback.get("status", "")))}. '
            f'{html.escape(details)}'
            f'{(" Reason: " + html.escape(str(reason))) if reason else ""}</p>'
        )
    if proof.get("auto_continued_from_step_cap") is not None:
        fallback_note += (
            f'<p class="muted"><strong>Auto-continued:</strong> the requested step cap '
            f'{html.escape(str(proof.get("auto_continued_from_step_cap")))} left open branches, so the app reran the proof with the cap removed.</p>'
        )
    return page_shell(
        params,
        f"""
        <section class="summary">
          <div>
            <h2>Pairing Result</h2>
            <p><strong>Mode:</strong> {html.escape(pair_mode)}</p>
            <p><strong>W:</strong> <span class="muted">{w_index:04d}</span> <span class="word">{html.escape(w_word)}</span></p>
            <p><strong>X:</strong> <span class="muted">{x_index:04d}</span> <span class="word">{html.escape(x_word)}</span></p>
            {fallback_note}
          </div>
          <div class="result-pill">{html.escape(proof['status'])}</div>
          <div class="metric"><span>Fork-killed branches</span><strong>{proof['discharged_term_count']}</strong></div>
          <div class="metric"><span>Active branches left</span><strong>{final_active_count}</strong></div>
          <div class="metric"><span>Final pairing value</span><strong>{proof.get('final_pairing_value')}</strong>{three_strand_warning}</div>
        </section>
        <section class="toc">
          <h2>What the page is showing</h2>
          <p>Relations are applied only to X. W is kept fixed and is colored only after X has no hourglasses and no internal black vertices. The Branch Ledger lists every terminal or still-open branch.</p>
        </section>
        {branch_ledger_html}
        {''.join(step_html)}
        {relation_html}
        {coloring_html}
        """,
    )


def render_relation_rule_section(w_graph: Dict[str, Any], x_graph: Dict[str, Any]) -> str:
    w_matches = relation_rules.detect_gppss_figure43_four_cycles(w_graph)
    x_matches = relation_rules.detect_gppss_figure43_four_cycles(x_graph)
    lemma49_items = relation_rules.lemma49_rule_catalog()
    sl4_lemma49_items = relation_rules.sl4_lemma49_zero_rule_catalog()
    if not w_matches and not x_matches and not lemma49_items and not sl4_lemma49_items:
        return ""

    def rows(side: str, matches: List[Dict[str, Any]]) -> str:
        out = []
        for match in matches:
            out.append(
                "<tr>"
                f"<td>{html.escape(side)}</td>"
                f"<td>{html.escape(match['rule'])}</td>"
                f"<td>{html.escape(str(match['vertices_top_right_bottom_left']))}</td>"
                f"<td>{html.escape(str(match['side_types_top_right_bottom_left']))}</td>"
                f"<td>{'yes' if match.get('requires_tags') else 'no'}</td>"
                f"<td>{html.escape(match['relation'])}</td>"
                "</tr>"
            )
        return "".join(out)

    lemma_summary = (
        f"<p class=\"muted\">Loaded {len(lemma49_items)} BCGMMW Lemma 4.9 exemplar snippets "
        "from <span class=\"word\">bcgmmw_lemma49_exemplars_0714.json</span>. "
        "These snippets are available for boundary-window matching; branch signs are still used in pairing values.</p>"
        f"<p class=\"muted\">Loaded {len(sl4_lemma49_items)} paired SL4 analogue zero rules "
        "from <span class=\"word\">sl4_lemma49_zero_patterns/</span>. "
        "When both local windows match, the terminal action is <span class=\"word\">discharge_pair</span> with pairing value 0.</p>"
    )

    figure43_table = ""
    if w_matches or x_matches:
        figure43_table = f"""
          <table class="step-table">
            <thead>
              <tr><th>web</th><th>rule</th><th>vertices top/right/bottom/left</th><th>side types</th><th>tag-sensitive</th><th>relation note</th></tr>
            </thead>
            <tbody>{rows('W', w_matches)}{rows('X', x_matches)}</tbody>
          </table>
        """

    return f"""
    <section class="step">
      <div class="step-head">
        <div><strong>GPPSS / BCGMMW Relation Rules</strong></div>
        <div class="muted">Figure 43 red tags are ignored completely; branch signs are still used in pairing values.</div>
      </div>
      {lemma_summary}
      {figure43_table}
    </section>
    """


def render_coloring_section(
    x_graph,
    w_graph,
    x_bounds,
    w_bounds,
    final_x,
    final_w,
    final_xh,
    final_wh,
    proof,
) -> str:
    evaluations = list(proof.get("linear_combination_terms", []))
    if not evaluations:
        evaluations = [
            item
            for item in proof.get("coloring_evaluations", [])
            if item.get("status") == "computed"
        ]
    if not evaluations:
        fallback = proof.get("w_expansion_fallback", {})
        if proof.get("status") == "proved_zero" and proof.get("active_term_count") == 0:
            reason = (
                "No coloring pictures are needed: every branch was killed by the fork lemma, "
                "so the pairing is proved zero before the coloring stage."
            )
        else:
            reason = fallback.get("reason") or "No surviving branch has reached the coloring stage."
        if proof.get("coloring_evaluations"):
            reason = "; ".join(
                str(ev.get("reason", ev.get("status", "not computed")))
                for ev in proof.get("coloring_evaluations", [])
            )
        return f'<section class="step"><h2>Final Coloring Pictures</h2><p>{html.escape(reason)}</p></section>'

    def as_adj(raw: Any, fallback: wrench.Adjacency) -> wrench.Adjacency:
        if not isinstance(raw, dict):
            return fallback
        out: wrench.Adjacency = {}
        for key, value in raw.items():
            try:
                node = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                converted = {}
                for k, v in value.items():
                    try:
                        port = int(k)
                    except (TypeError, ValueError):
                        port = str(k)
                    converted[port] = None if v is None else int(v)
                out[node] = converted
            else:
                out[node] = [int(v) for v in value]
        return out

    def as_hourglasses(raw: Any) -> List[wrench.Hourglass]:
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if isinstance(item, dict) and "white" in item and "black" in item:
                out.append({"white": int(item["white"]), "black": int(item["black"])})
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                out.append({"white": int(item[0]), "black": int(item[1])})
        return out

    def color_maps(ev: Dict[str, Any]) -> Tuple[Dict[Tuple[int, int], str], Dict[Tuple[int, int], Tuple[str, str]]]:
        edge_colors: Dict[Tuple[int, int], str] = {}
        hourglass_colors: Dict[Tuple[int, int], Tuple[str, str]] = {}
        for item in ev.get("sample_edge_colors", []):
            edge = item.get("edge", [])
            if len(edge) != 2:
                continue
            color = COLORS.get(int(item.get("color", 0)), "#111")
            edge_colors[tuple(sorted((int(edge[0]), int(edge[1]))))] = color
        for item in ev.get("sample_hourglass_colors", []):
            edge = item.get("edge", [])
            colors = item.get("colors", [])
            if len(edge) != 2 or len(colors) != 2:
                continue
            hourglass_colors[tuple(sorted((int(edge[0]), int(edge[1]))))] = (
                COLORS.get(int(colors[0]), "#111"),
                COLORS.get(int(colors[1]), "#111"),
            )
        return edge_colors, hourglass_colors

    def boundary_rings(graph: Dict[str, Any], condition: Dict[int, int]) -> Dict[int, str]:
        _, _, _, label_to_node = node_maps(graph)
        rings: Dict[int, str] = {}
        for label, color in condition.items():
            if label in label_to_node:
                rings[label_to_node[label]] = COLORS.get(int(color), "#111")
        return rings

    computed = [ev for ev in evaluations if ev.get("term_value") is not None]
    if computed:
        pieces = [
            f"({int(ev.get('coeff', 0))})*({int(ev.get('source_orientation_sign', 1))})*{int(ev.get('coloring_count', 0))}"
            for ev in computed
        ]
        linear_combo = " + ".join(pieces).replace("+ (-", "- (")
        linear_combo = f"{linear_combo} = {sum(int(ev.get('term_value', 0)) for ev in computed)}"
    else:
        linear_combo = "No computed surviving coloring terms."

    cards = []
    for idx, ev in enumerate(evaluations, start=1):
        status = str(ev.get("status", ""))
        if ev.get("term_value") is None:
            cards.append(
                f"""
                <div class="factor-box">
                  <h3>Surviving branch {idx}</h3>
                  <p><strong>Status:</strong> {html.escape(status)}</p>
                  <p>{html.escape(str(ev.get("reason", "not computed")))}</p>
                </div>
                """
            )
            continue

        condition = {int(k): int(v) for k, v in ev.get("boundary_color_by_label", {}).items()}
        edge_colors, hg_colors = color_maps(ev)
        source = str(ev.get("source_side", "X_components"))
        colored_side = str(ev.get("colored_side", "W"))
        x_adj = as_adj(ev.get("source_adj"), final_x) if source in {"X", "X_components"} else final_x
        x_hgs = [] if source in {"X", "X_components"} else final_xh
        w_adj = as_adj(ev.get("colored_adj"), final_w) if colored_side == "W" else final_w
        w_hgs = as_hourglasses(ev.get("colored_hourglasses")) if colored_side == "W" else final_wh
        x_rings = boundary_rings(x_graph, condition) if source in {"X", "X_components"} else {}
        w_rings = boundary_rings(w_graph, condition) if source == "W" else {}
        w_edge_colors = edge_colors if colored_side == "W" else {}
        x_edge_colors = edge_colors if colored_side == "X" else {}
        w_hg_colors = hg_colors if colored_side == "W" else {}
        x_hg_colors = hg_colors if colored_side == "X" else {}
        history = list(ev.get("history", []))
        x_curves = wrench.edge_curves_from_history(history, "X", x_adj)
        w_curves = wrench.edge_curves_from_history(history, "W", w_adj)
        cards.append(
            f"""
            <div class="factor-box">
              <h3>Surviving branch {idx}</h3>
              <p><strong>Coefficient:</strong> {html.escape(str(ev.get('coeff')))}</p>
              <p><strong>Tagged source-orientation sign:</strong> {html.escape(str(ev.get('source_orientation_sign', 1)))}</p>
              <p><strong>Coloring count:</strong> {html.escape(str(ev.get('coloring_count')))}</p>
              <p><strong>Contribution:</strong> {html.escape(str(ev.get('term_value')))}</p>
              <p class="muted">Hourglass strands use unordered distinct color pairs; swapping the two hourglass strand colors is not counted again.</p>
              <div class="grid two">
                {draw_web_svg('W: compatible edge coloring', w_graph, w_adj, w_hgs, edge_colors=w_edge_colors, hourglass_colors=w_hg_colors, node_ring_colors=w_rings, edge_curves=w_curves, subtitle='edge-colored from X boundary components')}
                {draw_web_svg('X: boundary component colors', x_graph, x_adj, x_hgs, edge_colors=x_edge_colors, hourglass_colors=x_hg_colors, node_ring_colors=x_rings, edge_curves=x_curves, subtitle='only boundary vertices are colored')}
              </div>
            </div>
            """
        )

    return f"""
    <section class="step coloring">
      <div class="step-head">
        <div><strong>Final Coloring Pictures</strong></div>
        <div class="muted">Every surviving computed branch is shown; W is always left and X is always right.</div>
      </div>
      <div class="factor-box">
        <h3>Linear Combination</h3>
        <p><span class="word">{html.escape(linear_combo)}</span></p>
        <p><strong>Final pairing value:</strong> {html.escape(str(proof.get('final_pairing_value')))}</p>
      </div>
      {''.join(cards)}
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
    allow_w = ""
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
    button.tiny {{ height:auto; padding:6px 9px; border-radius:6px; font-size:12px; }}
    .tiny-link, .branch-link {{ display:inline-block; padding:6px 9px; border-radius:6px; background:var(--ink); color:#fff; text-decoration:none; font-size:12px; }}
    .branch-link {{ font-weight:bold; }}
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
    .relation-warning {{ margin-top:6px; padding:8px 10px; border:1px solid #d99a22; border-radius:6px; background:#fff4d6; color:#704600; font-size:12px; font-weight:normal; max-width:280px; }}
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
    .branch-ledger-table td:last-child {{ min-width:260px; }}
    .branch-detail {{ border:1px solid var(--line); border-radius:7px; padding:8px 10px; background:#fff; }}
    .branch-detail summary {{ color:var(--ink); font-weight:bold; }}
    .branch-detail-body {{ margin-top:10px; }}
    .branch-moves {{ margin:10px 0 12px; font-size:13px; }}
    .branch-terminal-pair {{ grid-template-columns: repeat(2, minmax(220px, 1fr)); }}
    .branch-process-pictures {{ margin-top:14px; }}
    .branch-lazy-output {{ margin-top:12px; }}
    .branch-move-picture {{ border-top:1px solid var(--line); padding-top:12px; margin-top:12px; }}
    .branch-move-picture h4 {{ margin:0 0 8px; font-size:14px; }}
    @media (max-width: 1300px) {{ form, .summary, .grid.four, .grid.two {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Wrench Pairing Explorer</h1>
    <p class="muted">Enter W and X directly. They do not need to be transposes of each other.</p>
    <p class="muted"><a href="/image-explorer">Open image survivor explorer</a></p>
    <form method="get" action="/run">
      <label>W web index, word, or JSON file<input id="w-input" name="w" type="text" value="{w}" placeholder="0447_1231423121323444.json"></label>
      <label>X web index, word, or JSON file<input id="x-input" name="x" type="text" value="{x}" placeholder="0447_1112122334344234.json"></label>
      <label>Step cap, optional<input name="max_steps" type="number" value="{max_steps}" min="0" placeholder="auto"></label>
      <label>Beam width<input name="beam_width" type="number" value="{beam}" min="1"></label>
      <label class="check muted"><input type="checkbox" disabled> W is passive; apply relations only to X</label>
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

    document.addEventListener('click', async (event) => {{
      const button = event.target.closest('.load-branch-view');
      if (!button) {{
        return;
      }}
      const detail = button.closest('.branch-detail');
      const output = detail ? detail.querySelector('.branch-lazy-output') : null;
      if (!output) {{
        return;
      }}
      const params = new URLSearchParams(window.location.search);
      params.set('branch_id', button.dataset.branch || '');
      params.set('move', button.dataset.move || 'terminal');
      output.innerHTML = '<p class="muted">Loading pictures for this branch step...</p>';
      button.disabled = true;
      try {{
        const response = await fetch('/branch-view?' + params.toString(), {{cache: 'no-store'}});
        output.innerHTML = await response.text();
      }} catch (error) {{
        output.innerHTML = '<p class="muted">Could not load this branch picture.</p>';
      }} finally {{
        button.disabled = false;
      }}
    }});
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

    def send_file(self, path: Path) -> None:
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def serve_rep_image(self, parsed_path: str) -> bool:
        prefix = "/" + REP_IMAGE_FOLDER_NAME + "/"
        if not parsed_path.startswith(prefix):
            return False
        rel = urllib.parse.unquote(parsed_path[len(prefix) :])
        if "/" in rel or rel.startswith("."):
            return False
        image_path = (REP_IMAGE_DIR / rel).resolve()
        try:
            image_path.relative_to(REP_IMAGE_DIR.resolve())
        except ValueError:
            return False
        if not image_path.exists() or image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            return False
        self.send_file(image_path)
        return True

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if self.serve_rep_image(parsed.path):
            return
        if parsed.path == "/":
            self.send_html(page_shell(params))
            return
        if parsed.path in {"/image-explorer", "/images", "/web-explorer"}:
            self.send_html(image_explorer_page())
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
        if parsed.path == "/branch-view":
            try:
                self.send_html(render_branch_view(params))
            except Exception as exc:  # noqa: BLE001 - show branch-specific error inline.
                self.send_html(f"<p class='muted'>Could not load branch pictures: {html.escape(str(exc))}</p>", status=500)
            return
        if parsed.path == "/branch":
            try:
                self.send_html(render_branch_page(params))
            except Exception as exc:  # noqa: BLE001 - show branch-specific error in page.
                body = (
                    '<section class="summary"><div><h2>Could not open this branch</h2>'
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
