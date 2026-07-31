#!/usr/bin/env python3
"""Bounded A/B benchmark for the monotone SL4 square preprocessor."""

from __future__ import annotations

import argparse
import importlib
import signal
import time
from pathlib import Path
from typing import Any, Dict


class BenchmarkTimeout(RuntimeError):
    pass


def _timeout(_signum: int, _frame: Any) -> None:
    raise BenchmarkTimeout


def run(
    engine_name: str,
    graph_dir: Path,
    w_word: str,
    x_word: str,
    square_enabled: bool,
    timeout_seconds: int,
) -> Dict[str, Any]:
    engine = importlib.import_module(engine_name)
    w_path = next(graph_dir.glob(f"*_{w_word}.json"))
    x_path = next(graph_dir.glob(f"*_{x_word}.json"))
    w_adj, w_boundary, w_hgs = engine.parse_web(w_path)
    x_adj, x_boundary, x_hgs = engine.parse_web(x_path)
    w_colors, w_xy = engine.parse_web_metadata(w_path)
    x_colors, x_xy = engine.parse_web_metadata(x_path)

    original_detector = engine.detect_hourglass_reducing_square_moves
    counters = {"detector_calls": 0, "square_matches": 0}

    def detector(*args: Any, **kwargs: Any) -> Any:
        counters["detector_calls"] += 1
        matches = original_detector(*args, **kwargs) if square_enabled else []
        counters["square_matches"] += len(matches)
        return matches

    engine.detect_hourglass_reducing_square_moves = detector
    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(timeout_seconds)
    started = time.perf_counter()
    try:
        result = engine.prove_pair_value_complete_pipeline(
            x_adj,
            x_boundary,
            x_hgs,
            w_adj,
            w_boundary,
            w_hgs,
            allow_w_wrench=False,
            x_node_colors=x_colors,
            x_node_xy=x_xy,
            w_node_colors=w_colors,
            w_node_xy=w_xy,
            use_lemma49=True,
            use_lemma48=False,
            allow_three_strand=True,
        )
        status = str(result.get("status"))
        value = result.get("final_pairing_value")
    except BenchmarkTimeout:
        status = "timeout"
        value = None
    finally:
        signal.alarm(0)
        engine.detect_hourglass_reducing_square_moves = original_detector

    return {
        "engine": engine_name,
        "square_enabled": square_enabled,
        "w_word": w_word,
        "x_word": x_word,
        "seconds": round(time.perf_counter() - started, 6),
        "status": status,
        "value": value,
        **counters,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="Wrench_or_Skein_0714")
    parser.add_argument("--graph-dir", type=Path, default=Path("4x4_All_graph_data"))
    parser.add_argument("--w", required=True)
    parser.add_argument("--x", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--mode", choices=("disabled", "enabled", "both"), default="both")
    args = parser.parse_args()
    modes = {
        "disabled": (False,),
        "enabled": (True,),
        "both": (False, True),
    }
    for enabled in modes[args.mode]:
        print(
            run(
                args.engine,
                args.graph_dir,
                args.w,
                args.x,
                enabled,
                args.timeout,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
