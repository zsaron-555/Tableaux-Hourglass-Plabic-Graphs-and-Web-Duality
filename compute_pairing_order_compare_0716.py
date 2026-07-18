#!/usr/bin/env python3
"""Compare <W,X> against <X,W> for sign/speed diagnostics.

This does not replace the full batch table.  It is a spot-check tool for
finding examples where the two orders differ in value, parity, or runtime.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


GITHUB_APP_DIR = Path(
    "/Users/zhuzhetian/Documents/GitHub/Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality"
)

FIELDNAMES = [
    "example_id",
    "w_word",
    "x_word",
    "wx_status",
    "wx_value",
    "wx_active",
    "wx_discharged",
    "wx_elapsed_sec",
    "xw_status",
    "xw_value",
    "xw_active",
    "xw_discharged",
    "xw_elapsed_sec",
    "same_value",
    "same_mod2",
    "faster_order",
    "speed_ratio",
    "wx_error",
    "xw_error",
]


def import_0714_app():
    local_dir = Path(__file__).resolve().parent
    if str(local_dir) not in sys.path:
        sys.path.insert(0, str(local_dir))
    if not (local_dir / "wrench_web_app_0714.py").exists() and str(GITHUB_APP_DIR) not in sys.path:
        sys.path.insert(1, str(GITHUB_APP_DIR))
    import wrench_web_app_0714 as app  # type: ignore

    return app


def int_or_none(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_graph(app: Any, word: str, side: str) -> Tuple[Any, Any, Any, Any, Any]:
    path = app.resolve_graph(word, side)
    adj, bounds, hgs = app.wrench.parse_web(path)
    node_colors, node_xy = app.wrench.parse_web_metadata(path)
    hgs = app.wrench.sort_hourglasses_by_boundary_distance(adj, bounds, hgs)
    return adj, bounds, hgs, node_colors, node_xy


class TimeoutExpired(RuntimeError):
    pass


def _timeout_handler(_signum: int, _frame: Any) -> None:
    raise TimeoutExpired("order comparison timed out")


def compute_order(app: Any, w_word: str, x_word: str, timeout_sec: Optional[int] = None) -> Dict[str, str]:
    start = time.time()
    old_handler = None
    try:
        if timeout_sec:
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_sec)
        w_adj, w_bounds, w_hgs, w_colors, w_xy = parse_graph(app, w_word, "W")
        x_adj, x_bounds, x_hgs, x_colors, x_xy = parse_graph(app, x_word, "X")
        proof = app.wrench.prove_pair_value_by_x_component_coloring(
            x_adj,
            x_bounds,
            x_hgs,
            w_adj,
            w_bounds,
            w_hgs,
            allow_w_wrench=False,
            guided_beam_width=120,
            x_beam_width=500,
            guided_steps=None,
            x_resolution_steps=None,
            x_node_colors=x_colors,
            x_node_xy=x_xy,
            w_node_colors=w_colors,
            w_node_xy=w_xy,
        )
        return {
            "status": str(proof.get("status", "")),
            "value": str(proof.get("final_pairing_value", "")),
            "active": str(proof.get("active_term_count", "")),
            "discharged": str(proof.get("discharged_term_count", "")),
            "elapsed_sec": f"{time.time() - start:.3f}",
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic should keep going.
        return {
            "status": "error",
            "value": "",
            "active": "",
            "discharged": "",
            "elapsed_sec": f"{time.time() - start:.3f}",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if timeout_sec:
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)


def survivor_pairs(app: Any) -> List[Tuple[str, str]]:
    index = app.load_survivor_index()
    pairs: List[Tuple[str, str]] = []
    for w_idx in sorted(index["by_idx"]):
        entry = index["by_idx"][w_idx]
        w_word = entry["w_word"]
        survivor_info = app.actual_survivor_words(entry, w_word)
        for x_word in survivor_info["words"]:
            if w_word != x_word:
                pairs.append((w_word, x_word))
    return pairs


def explicit_pairs(items: Iterable[str]) -> List[Tuple[str, str]]:
    pairs = []
    for item in items:
        if not item.strip():
            continue
        if "," in item:
            left, right = item.split(",", 1)
        else:
            parts = item.split()
            if len(parts) != 2:
                raise ValueError(f"Expected 'WORD1,WORD2' or 'WORD1 WORD2', got {item!r}")
            left, right = parts
        pairs.append((left.strip(), right.strip()))
    return pairs


def load_pair_file(path: Path) -> List[Tuple[str, str]]:
    pairs = []
    with path.open(newline="", encoding="utf-8") as f:
        sample = f.read(2048)
        f.seek(0)
        delimiter = "\t" if "\t" in sample else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        fields = set(reader.fieldnames or [])
        if {"w_word", "x_word"} <= fields:
            for row in reader:
                pairs.append((row["w_word"].strip(), row["x_word"].strip()))
        elif {"W", "X"} <= fields:
            for row in reader:
                pairs.append((row["W"].strip(), row["X"].strip()))
        else:
            for row in reader:
                vals = [v.strip() for v in row.values() if v and v.strip()]
                if len(vals) >= 2:
                    pairs.append((vals[0], vals[1]))
    return pairs


def compare_pair(app: Any, example_id: int, w_word: str, x_word: str, timeout_sec: Optional[int]) -> Dict[str, str]:
    wx = compute_order(app, w_word, x_word, timeout_sec=timeout_sec)
    xw = compute_order(app, x_word, w_word, timeout_sec=timeout_sec)
    wx_val = int_or_none(wx["value"])
    xw_val = int_or_none(xw["value"])
    same_value = wx_val is not None and xw_val is not None and wx_val == xw_val
    same_mod2 = wx_val is not None and xw_val is not None and (wx_val - xw_val) % 2 == 0
    wx_t = float(wx["elapsed_sec"])
    xw_t = float(xw["elapsed_sec"])
    faster = "WX" if wx_t < xw_t else "XW" if xw_t < wx_t else "tie"
    ratio = max(wx_t, xw_t) / max(min(wx_t, xw_t), 1e-9)
    return {
        "example_id": str(example_id),
        "w_word": w_word,
        "x_word": x_word,
        "wx_status": wx["status"],
        "wx_value": wx["value"],
        "wx_active": wx["active"],
        "wx_discharged": wx["discharged"],
        "wx_elapsed_sec": wx["elapsed_sec"],
        "xw_status": xw["status"],
        "xw_value": xw["value"],
        "xw_active": xw["active"],
        "xw_discharged": xw["discharged"],
        "xw_elapsed_sec": xw["elapsed_sec"],
        "same_value": str(same_value),
        "same_mod2": str(same_mod2),
        "faster_order": faster,
        "speed_ratio": f"{ratio:.3f}",
        "wx_error": wx["error"],
        "xw_error": xw["error"],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        default=os.environ.get("PROBLEM3_ROOT", str(Path(__file__).resolve().parent)),
    )
    parser.add_argument("--out", default="pairing_order_compare_0716.tsv")
    parser.add_argument("--pair", action="append", default=[], help="Pair as WORD1,WORD2. Can be repeated.")
    parser.add_argument("--pair-file", default=None, help="CSV/TSV containing w_word and x_word columns.")
    parser.add_argument("--sample", type=int, default=20, help="Random survivor-pair sample size if no pairs are given.")
    parser.add_argument("--seed", type=int, default=71416)
    parser.add_argument("--timeout-sec", type=int, default=120, help="Maximum seconds for each ordered pairing.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    app = import_0714_app()
    app.configure_project_root(args.project_root)
    pairs = explicit_pairs(args.pair)
    if args.pair_file:
        pairs.extend(load_pair_file(Path(args.pair_file).expanduser()))
    if not pairs:
        all_pairs = survivor_pairs(app)
        rng = random.Random(args.seed)
        pairs = rng.sample(all_pairs, min(args.sample, len(all_pairs)))
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        writer.writeheader()
        for idx, (w_word, x_word) in enumerate(pairs, start=1):
            row = compare_pair(app, idx, w_word, x_word, args.timeout_sec)
            writer.writerow(row)
            f.flush()
            print(
                idx,
                w_word,
                x_word,
                row["wx_value"],
                row["xw_value"],
                row["same_value"],
                row["same_mod2"],
                row["speed_ratio"],
            )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
