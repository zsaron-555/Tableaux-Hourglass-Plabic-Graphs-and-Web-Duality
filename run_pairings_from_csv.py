#!/usr/bin/env python3
"""Run SL4 pairing computations from a collaborator-supplied CSV or TSV file.

This is a portable front end for compute_pairing_values_optimized_20260726.py.
It normalizes flexible input columns to the task format used by the cached
pairing engine, supports disjoint shards, and resumes from an existing output.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
RUNNER_NAME = "compute_pairing_values_optimized_20260726.py"
APP_NAME = "wrench_web_app_0714.py"
ENGINE_NAME = "Wrench_or_Skein_optimized_20260726.py"
GRAPH_DIR_NAMES = ("hourglass_disk_4x4_all_graph_data", "4x4_All_graph_data")

W_ALIASES = {
    "w",
    "wword",
    "wordw",
    "webw",
    "firstword",
    "representativeword",
    "representative",
}
X_ALIASES = {
    "x",
    "xword",
    "wordx",
    "webx",
    "secondword",
    "survivorword",
    "partnerword",
}
INDEX_ALIASES = {
    "widx",
    "windex",
    "representativeindex",
    "repindex",
    "index",
}


def normalized_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def detect_delimiter(path: Path) -> str:
    if path.suffix.lower() in {".tsv", ".tab"}:
        return "\t"
    sample = path.read_text(encoding="utf-8-sig", errors="replace")[:65536]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except csv.Error:
        return ","


def select_column(fieldnames: Iterable[str], aliases: set[str]) -> Optional[str]:
    for field in fieldnames:
        if normalized_header(field) in aliases:
            return field
    return None


def is_sl4_yamanouchi(word: str) -> bool:
    if len(word) != 16 or any(letter not in "1234" for letter in word):
        return False
    counts = [0, 0, 0, 0]
    for letter in word:
        counts[int(letter) - 1] += 1
        if not (counts[0] >= counts[1] >= counts[2] >= counts[3]):
            return False
    return counts == [4, 4, 4, 4]


def locate_code_dir(explicit: Optional[str]) -> Path:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_dir = os.environ.get("PROBLEM3_APP_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.extend([SCRIPT_DIR, Path.cwd(), SCRIPT_DIR.parent, Path.cwd().parent])

    checked: List[str] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        checked.append(str(resolved))
        if all((resolved / name).is_file() for name in (RUNNER_NAME, APP_NAME, ENGINE_NAME)):
            return resolved
    raise FileNotFoundError(
        "Could not locate the pairing code folder. Expected these files together:\n"
        f"  {RUNNER_NAME}\n  {APP_NAME}\n  {ENGINE_NAME}\n"
        "Checked:\n  " + "\n  ".join(checked)
    )


def contains_graph_data(path: Path) -> bool:
    return any((path / name).is_dir() for name in GRAPH_DIR_NAMES)


def locate_project_root(code_dir: Path, explicit: Optional[str]) -> Path:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_root = os.environ.get("PROBLEM3_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend([code_dir, Path.cwd(), code_dir.parent, Path.cwd().parent])

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if contains_graph_data(resolved):
            return resolved

    # The app has a broader bounded search over Desktop/Documents/Downloads.
    # Passing the code directory lets it perform that discovery portably.
    return code_dir


def graph_index_by_word(code_dir: Path, project_root: Path) -> Dict[str, int]:
    sys.path.insert(0, str(code_dir))
    try:
        import wrench_web_app_0714 as app  # type: ignore

        app.configure_project_root(project_root)
        index = app.graph_dir_index(app.ALL_DIR)
        return {
            str(word): int(app.graph_index(path))
            for word, path in index["by_word"].items()
        }
    finally:
        try:
            sys.path.remove(str(code_dir))
        except ValueError:
            pass


def read_tasks(
    input_path: Path,
    *,
    code_dir: Path,
    project_root: Path,
    shard_index: int,
    shard_count: int,
) -> List[Tuple[int, str, str]]:
    delimiter = detect_delimiter(input_path)
    with input_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        fieldnames = reader.fieldnames or []
        w_column = select_column(fieldnames, W_ALIASES)
        x_column = select_column(fieldnames, X_ALIASES)
        index_column = select_column(fieldnames, INDEX_ALIASES)
        if not w_column or not x_column:
            raise ValueError(
                "Input must have W and X columns. Accepted examples include "
                "'w_word,x_word', 'W,X', or 'representative_word,survivor_word'. "
                f"Found columns: {fieldnames}"
            )

        raw_rows = list(reader)

    try:
        known_indices = graph_index_by_word(code_dir, project_root)
    except Exception as exc:  # noqa: BLE001 - computation will validate graph lookup.
        print(f"Warning: could not pre-index graph words ({exc}).", file=sys.stderr)
        known_indices = {}

    tasks: List[Tuple[int, str, str]] = []
    seen: set[Tuple[str, str]] = set()
    invalid: List[str] = []
    for source_row, row in enumerate(raw_rows, start=2):
        w_word = re.sub(r"\s+", "", str(row.get(w_column, "")))
        x_word = re.sub(r"\s+", "", str(row.get(x_column, "")))
        if not w_word and not x_word:
            continue
        if not is_sl4_yamanouchi(w_word) or not is_sl4_yamanouchi(x_word):
            invalid.append(f"row {source_row}: W={w_word!r}, X={x_word!r}")
            continue
        pair = (w_word, x_word)
        if pair in seen:
            continue
        seen.add(pair)

        supplied_index = 0
        if index_column:
            raw_index = str(row.get(index_column, "") or "").strip()
            if raw_index.isdigit():
                supplied_index = int(raw_index)
        w_idx = known_indices.get(w_word, supplied_index or source_row - 1)
        tasks.append((w_idx, w_word, x_word))

    if invalid:
        preview = "\n  ".join(invalid[:10])
        suffix = f"\n  ... and {len(invalid) - 10} more" if len(invalid) > 10 else ""
        raise ValueError(f"Invalid 4x4 SL4 Yamanouchi words:\n  {preview}{suffix}")
    if not tasks:
        raise ValueError("No valid W,X task rows were found.")

    if shard_count < 1 or not 1 <= shard_index <= shard_count:
        raise ValueError("--shard-index must lie between 1 and --shard-count.")
    return [
        task
        for offset, task in enumerate(tasks)
        if offset % shard_count == shard_index - 1
    ]


def write_normalized_tasks(path: Path, tasks: Sequence[Tuple[int, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["w_idx", "w_word", "x_word"])
        writer.writerows(tasks)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="CSV or TSV containing W and X word columns.")
    parser.add_argument("--code-dir", default=None, help="Folder containing the pairing Python files.")
    parser.add_argument("--project-root", default=None, help="Folder containing 4x4_All_graph_data.")
    parser.add_argument("--output", default=None, help="Result TSV; defaults next to the input file.")
    parser.add_argument("--log", default=None, help="Progress log; defaults next to the result TSV.")
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(4, (os.cpu_count() or 2) - 1)),
        help="Parallel worker count (default: up to 4).",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=float,
        default=60.0,
        help="Per-pair timeout in minutes; use 0 for no timeout (default: 60).",
    )
    parser.add_argument("--shard-index", type=int, default=1, help="This computer's 1-based shard number.")
    parser.add_argument("--shard-count", type=int, default=1, help="Total number of disjoint shards.")
    parser.add_argument(
        "--keep-awake",
        action="store_true",
        help="On macOS, run the computation under caffeinate.",
    )
    parser.add_argument(
        "--record-reversed-as-original",
        action="store_true",
        help="Compute entered tasks as <X,W> but store them under the entered <W,X> order.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Normalize and report tasks without computing.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input_file).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    code_dir = locate_code_dir(args.code_dir)
    project_root = locate_project_root(code_dir, args.project_root)
    stem = input_path.stem
    shard_suffix = (
        f"_shard{args.shard_index}of{args.shard_count}"
        if args.shard_count > 1
        else ""
    )
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else input_path.with_name(f"{stem}{shard_suffix}_pairing_values.tsv")
    )
    log_path = (
        Path(args.log).expanduser().resolve()
        if args.log
        else output_path.with_suffix(".log")
    )
    normalized_path = output_path.with_name(f"{output_path.stem}_tasks.tsv")

    tasks = read_tasks(
        input_path,
        code_dir=code_dir,
        project_root=project_root,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
    )
    write_normalized_tasks(normalized_path, tasks)

    print(f"code folder: {code_dir}")
    print(f"project root: {project_root}")
    print(f"input rows assigned to this computer: {len(tasks)}")
    print(f"normalized tasks: {normalized_path}")
    print(f"result TSV: {output_path}")
    print(f"progress log: {log_path}")
    if args.dry_run:
        return 0

    command = [
        sys.executable,
        str(code_dir / RUNNER_NAME),
        "--project-root",
        str(project_root),
        "--task-file",
        str(normalized_path),
        "--out",
        str(output_path),
        "--log",
        str(log_path),
        "--workers",
        str(max(1, args.workers)),
        "--task-order",
        "by-x-cache",
    ]
    if args.timeout_minutes > 0:
        command.extend(["--task-timeout", str(args.timeout_minutes * 60.0)])
    if args.record_reversed_as_original:
        command.append("--record-reversed-as-original")

    env = os.environ.copy()
    env["PROBLEM3_APP_DIR"] = str(code_dir)
    env["PROBLEM3_ENGINE_DIR"] = str(code_dir)
    env["PROBLEM3_ROOT"] = str(project_root)

    if args.keep_awake and sys.platform == "darwin":
        caffeinate = shutil.which("caffeinate")
        if caffeinate:
            command = [caffeinate, "-dims", "--", *command]
        else:
            print("Warning: caffeinate was not found; continuing normally.", file=sys.stderr)

    print("\nStarting computation. Re-running this command safely resumes the output.")
    print("Command:", " ".join(command))
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
