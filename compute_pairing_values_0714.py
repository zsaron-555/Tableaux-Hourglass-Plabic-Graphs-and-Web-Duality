#!/usr/bin/env python3
"""Compute only pairing values using the current 0714 relation code.

This is the batch runner to use when proof pictures / branch pages are not
needed.  It imports the current 0714 app and wrench code, but writes only the
pairing value summary for each survivor pair.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import os
import signal
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


GITHUB_APP_DIR = Path(
    os.environ.get("PROBLEM3_APP_DIR", str(Path(__file__).resolve().parent))
).expanduser().resolve()
ENGINE_DIR = Path(
    os.environ.get("PROBLEM3_ENGINE_DIR", str(GITHUB_APP_DIR))
).expanduser().resolve()

FIELDNAMES = [
    "w_idx",
    "w_word",
    "x_word",
    "x_index",
    "status",
    "final_pairing_value",
    "used_three_strand_relation",
    "pairing_value_warning",
    "active_term_count",
    "discharged_term_count",
    "elapsed_sec",
    "error",
]

_APP = None
_WRENCH = None
_PARSED_GRAPH_CACHE: Dict[Path, Tuple[Any, Any, Any, Any, Any, int]] = {}
USE_FAST_FIXED_ORDER = os.environ.get("HG_FAST_FIXED_ORDER", "") == "1"


class TaskTimeoutError(TimeoutError):
    """Raised when one pairing exceeds the configured serial-task limit."""


def task_timeout_handler(_signum: int, _frame: Any) -> None:
    raise TaskTimeoutError("pairing exceeded the per-task time limit")


def import_0714_app():
    if str(GITHUB_APP_DIR) not in sys.path:
        sys.path.insert(0, str(GITHUB_APP_DIR))
    import wrench_web_app_0714 as app  # type: ignore

    return app


def init_worker(project_root: str) -> None:
    global _APP, _WRENCH, _PARSED_GRAPH_CACHE
    app = import_0714_app()
    app.configure_project_root(project_root)
    engine_path = str(ENGINE_DIR)
    if engine_path in sys.path:
        sys.path.remove(engine_path)
    sys.path.insert(0, engine_path)
    if ENGINE_DIR != GITHUB_APP_DIR:
        sys.modules.pop("Wrench_or_Skein_0714", None)
    current_wrench = importlib.import_module("Wrench_or_Skein_0714")

    _APP = app
    _WRENCH = current_wrench
    _PARSED_GRAPH_CACHE = {}


def completed_pairs(path: Path) -> Set[Tuple[str, str]]:
    if not path.exists():
        return set()
    done: Set[Tuple[str, str]] = set()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            w_word = (row.get("w_word") or "").strip()
            x_word = (row.get("x_word") or "").strip()
            if w_word and x_word:
                done.add((w_word, x_word))
    return done


def append_row(path: Path, row: Dict[str, Any]) -> None:
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in FIELDNAMES})
        f.flush()


def log_line(path: Path, message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")
        f.flush()


def build_tasks(
    project_root: str,
    start_index: int,
    end_index: Optional[int],
    limit: Optional[int],
) -> List[Tuple[int, str, str]]:
    app = import_0714_app()
    app.configure_project_root(project_root)
    survivor_index = app.load_survivor_index()
    tasks: List[Tuple[int, str, str]] = []
    for w_idx in sorted(survivor_index["by_idx"]):
        if w_idx < start_index:
            continue
        if end_index is not None and w_idx > end_index:
            continue
        entry = survivor_index["by_idx"][w_idx]
        w_word = entry["w_word"]
        survivor_info = app.actual_survivor_words(entry, w_word)
        for x_word in survivor_info["words"]:
            tasks.append((w_idx, w_word, x_word))
            if limit is not None and len(tasks) >= limit:
                return tasks
    return tasks


def load_task_file(path: Path, limit: Optional[int]) -> List[Tuple[int, str, str]]:
    tasks: List[Tuple[int, str, str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            w_idx = int((row.get("w_idx") or "0").strip())
            w_word = (row.get("w_word") or "").strip()
            x_word = (row.get("x_word") or "").strip()
            if not w_idx or not w_word or not x_word:
                continue
            tasks.append((w_idx, w_word, x_word))
            if limit is not None and len(tasks) >= limit:
                return tasks
    return tasks


def round_robin_by_w(tasks: Sequence[Tuple[int, str, str]]) -> List[Tuple[int, str, str]]:
    grouped: Dict[int, List[Tuple[int, str, str]]] = {}
    for task in tasks:
        grouped.setdefault(task[0], []).append(task)
    ordered: List[Tuple[int, str, str]] = []
    keys = sorted(grouped)
    max_len = max((len(grouped[key]) for key in keys), default=0)
    for offset in range(max_len):
        for key in keys:
            items = grouped[key]
            if offset < len(items):
                ordered.append(items[offset])
    return ordered


def compute_one(task: Tuple[int, str, str]) -> Dict[str, Any]:
    if _APP is None or _WRENCH is None:
        raise RuntimeError("worker was not initialized")

    app = _APP
    wrench = _WRENCH
    w_idx, w_word, x_word = task
    start = time.time()
    try:
        w_path = app.resolve_graph(w_word, "W")
        x_path = app.resolve_graph(x_word, "X")
        x_adj, x_bounds, x_hgs, x_node_colors, x_node_xy, x_index = parse_graph_cached(x_path)
        w_adj, w_bounds, w_hgs, w_node_colors, w_node_xy, _w_index = parse_graph_cached(w_path)
        proof = {"final_pairing_value": ""}
        if USE_FAST_FIXED_ORDER:
            proof = prove_value_fixed_x_order(
                wrench,
                x_adj,
                x_bounds,
                x_hgs,
                w_adj,
                w_bounds,
                w_hgs,
                x_node_colors=x_node_colors,
                x_node_xy=x_node_xy,
                source_web_sign=wrench.word_inversion_sign(x_word),
            )
        if proof.get("final_pairing_value", "") == "":
            proof = wrench.prove_pair_value_by_x_component_coloring(
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
                x_node_colors=x_node_colors,
                x_node_xy=x_node_xy,
                w_node_colors=w_node_colors,
                w_node_xy=w_node_xy,
                source_web_sign=wrench.word_inversion_sign(x_word),
                use_lemma48=False,
            )
            proof["status"] = "fallback_" + str(proof.get("status", ""))
        used_three_strand = bool(proof.get("used_three_strand_relation", False))
        if not used_three_strand and hasattr(app, "proof_used_three_strand_relation"):
            used_three_strand = bool(app.proof_used_three_strand_relation(proof))
        warning = "WARNING: 3-strand relation used" if used_three_strand else ""
        return {
            "w_idx": w_idx,
            "w_word": w_word,
            "x_word": x_word,
            "x_index": x_index,
            "status": proof.get("status", ""),
            "final_pairing_value": proof.get("final_pairing_value", ""),
            "used_three_strand_relation": "yes" if used_three_strand else "no",
            "pairing_value_warning": warning,
            "active_term_count": proof.get("active_term_count", ""),
            "discharged_term_count": proof.get("discharged_term_count", ""),
            "elapsed_sec": f"{time.time() - start:.3f}",
            "error": "",
        }

    except Exception as exc:  # noqa: BLE001 - keep the batch checkpointing.
        timed_out = isinstance(exc, TaskTimeoutError)
        return {
            "w_idx": w_idx,
            "w_word": w_word,
            "x_word": x_word,
            "x_index": "",
            "status": "timeout" if timed_out else "error",
            "final_pairing_value": "",
            "used_three_strand_relation": "",
            "pairing_value_warning": "",
            "active_term_count": "",
            "discharged_term_count": "",
            "elapsed_sec": f"{time.time() - start:.3f}",
            "error": f"{type(exc).__name__}: {exc}",
        }


def compute_one_with_timeout(task: Tuple[int, str, str], task_timeout: Optional[float]) -> Dict[str, Any]:
    if not task_timeout:
        return compute_one(task)
    signal.signal(signal.SIGALRM, task_timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, task_timeout)
    try:
        return compute_one(task)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def has_internal_black_vertices(wrench: Any, term: Dict[str, Any], x_bounds: Any, x_node_colors: Any) -> bool:
    if not x_node_colors:
        return False
    normalized = wrench.normalize_pair_term(term)
    return any(
        int(node) not in x_bounds and x_node_colors.get(int(node)) == "black"
        for node in normalized["x_adj"]
    )


def fixed_order_children(wrench: Any, term: Dict[str, Any], x_bounds: Any, x_node_colors: Any, x_node_xy: Any):
    term = wrench.normalize_pair_term(term)
    for match in wrench.detect_figure43_moves(term["x_adj"], term["x_remaining"], x_node_colors, x_node_xy):
        try:
            return wrench.expand_pair_term_by_figure43(term, "X", match), "figure43"
        except ValueError:
            continue
    if term["x_remaining"]:
        for hg in term["x_remaining"]:
            try:
                return wrench.expand_pair_term(term, "X", hg, node_xy=x_node_xy), "wrench"
            except ValueError:
                continue
    if has_internal_black_vertices(wrench, term, x_bounds, x_node_colors):
        for match in wrench.detect_antisymmetrizer_moves(term["x_adj"], x_node_colors, x_node_xy):
            try:
                return wrench.expand_pair_term_by_antisymmetrizer(term, match), "antisymmetrizer"
            except ValueError:
                continue
    return None, ""


def fixed_x_ready(wrench: Any, active: List[Dict[str, Any]], x_bounds: Any, x_node_colors: Any) -> bool:
    for term in active:
        term = wrench.normalize_pair_term(term)
        if term["x_remaining"] or has_internal_black_vertices(wrench, term, x_bounds, x_node_colors):
            return False
    return True


def prove_value_fixed_x_order(
    wrench: Any,
    x_adj: Any,
    x_bounds: Any,
    x_hgs: Any,
    w_adj: Any,
    w_bounds: Any,
    w_hgs: Any,
    *,
    x_node_colors: Any = None,
    x_node_xy: Any = None,
    max_moves: int = 500,
    source_web_sign: int = 1,
) -> Dict[str, Any]:
    used_three_strand_relation = False
    active = [
        {
            "x_adj": x_adj,
            "x_remaining": x_hgs,
            "w_adj": w_adj,
            "w_remaining": w_hgs,
            "coeff": 1,
            "history": [],
        }
    ]
    active, discharged = wrench.discharge_pair_terms_by_common_fork(active, x_bounds, w_bounds)

    moves = 0
    while moves <= max_moves:
        if not active:
            return {
                "status": "proved_zero",
                "final_pairing_value": 0,
                "used_three_strand_relation": used_three_strand_relation,
                "active_term_count": 0,
                "discharged_term_count": len(discharged),
            }
        if fixed_x_ready(wrench, active, x_bounds, x_node_colors):
            evaluated = wrench.evaluate_pair_state_by_x_component_coloring(
                {"active": active, "discharged": discharged},
                x_bounds,
                w_bounds,
                r=4,
                source_web_sign=source_web_sign,
            )
            if evaluated is not None:
                value, _evaluations = evaluated
                return {
                    "status": "evaluated_by_fixed_x_order",
                    "final_pairing_value": value,
                    "used_three_strand_relation": used_three_strand_relation,
                    "active_term_count": len(active),
                    "discharged_term_count": len(discharged),
                }

        expanded = False
        for term_idx, term in enumerate(active):
            children, relation = fixed_order_children(wrench, term, x_bounds, x_node_colors, x_node_xy)
            if not children:
                continue
            if relation == "antisymmetrizer":
                used_three_strand_relation = True
            next_terms = active[:term_idx] + active[term_idx + 1 :] + children
            next_terms = wrench.consolidate_pair_terms(next_terms)
            active, newly_discharged = wrench.discharge_pair_terms_by_common_fork(next_terms, x_bounds, w_bounds)
            discharged = discharged + newly_discharged
            moves += 1
            expanded = True
            break
        if not expanded:
            break

    return {
        "status": "partial_fixed_x_order",
        "final_pairing_value": "",
        "used_three_strand_relation": used_three_strand_relation,
        "active_term_count": len(active),
        "discharged_term_count": len(discharged),
    }

def parse_graph_cached(path: Path) -> Tuple[Any, Any, Any, Any, Any, int]:
    if _WRENCH is None or _APP is None:
        raise RuntimeError("worker was not initialized")
    path = path.resolve()
    cached = _PARSED_GRAPH_CACHE.get(path)
    if cached is not None:
        return cached
    adj, bounds, hgs = _WRENCH.parse_web(path)
    node_colors, node_xy = _WRENCH.parse_web_metadata(path)
    hgs = _WRENCH.sort_hourglasses_by_boundary_distance(adj, bounds, hgs)
    graph_index = _APP.graph_index(path)
    parsed = (adj, bounds, hgs, node_colors, node_xy, graph_index)
    _PARSED_GRAPH_CACHE[path] = parsed
    return parsed


def run_parallel(
    tasks: Sequence[Tuple[int, str, str]],
    out_path: Path,
    log_path: Path,
    project_root: str,
    workers: int,
    task_timeout: Optional[float] = None,
) -> None:
    start = time.time()
    last_log = start
    submitted = 0
    completed = 0
    max_pending = max(workers * 2, 1)
    with ProcessPoolExecutor(max_workers=workers, initializer=init_worker, initargs=(project_root,)) as executor:
        pending = {}
        while submitted < len(tasks) and len(pending) < max_pending:
            future = executor.submit(compute_one_with_timeout, tasks[submitted], task_timeout)
            pending[future] = tasks[submitted]
            submitted += 1

        while pending:
            done_futures, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done_futures:
                pending.pop(future)
                row = future.result()
                append_row(out_path, row)
                completed += 1

                while submitted < len(tasks) and len(pending) < max_pending:
                    next_future = executor.submit(compute_one_with_timeout, tasks[submitted], task_timeout)
                    pending[next_future] = tasks[submitted]
                    submitted += 1

            now = time.time()
            if completed == len(tasks) or completed % 25 == 0 or now - last_log >= 60:
                rate = completed / max(now - start, 0.001)
                eta = (len(tasks) - completed) / max(rate, 0.001)
                log_line(
                    log_path,
                    f"done {completed}/{len(tasks)} submitted={submitted} "
                    f"rate={rate:.2f}/s eta={eta/3600:.2f}h",
                )
                last_log = now


def run_serial(
    tasks: Sequence[Tuple[int, str, str]],
    out_path: Path,
    log_path: Path,
    project_root: str,
    task_timeout: Optional[float] = None,
) -> None:
    init_worker(project_root)
    if task_timeout:
        signal.signal(signal.SIGALRM, task_timeout_handler)
    start = time.time()
    last_log = start
    for completed, task in enumerate(tasks, start=1):
        if task_timeout:
            signal.setitimer(signal.ITIMER_REAL, task_timeout)
        try:
            row = compute_one(task)
        finally:
            if task_timeout:
                signal.setitimer(signal.ITIMER_REAL, 0)
        append_row(out_path, row)
        now = time.time()
        if completed == len(tasks) or completed % 25 == 0 or now - last_log >= 60:
            rate = completed / max(now - start, 0.001)
            eta = (len(tasks) - completed) / max(rate, 0.001)
            log_line(log_path, f"done {completed}/{len(tasks)} rate={rate:.2f}/s eta={eta/3600:.2f}h")
            last_log = now


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        default=os.environ.get("PROBLEM3_ROOT", str(Path(__file__).resolve().parent)),
        help="Folder containing lemma46_survivors.csv and the graph-data folders.",
    )
    parser.add_argument("--out", default="All_Pairings_0714.tsv", help="Checkpoint TSV output path.")
    parser.add_argument("--log", default="All_Pairings_0714.log", help="Progress log path.")
    parser.add_argument("--workers", type=int, default=min(12, os.cpu_count() or 1), help="Parallel worker count.")
    parser.add_argument("--limit", type=int, default=None, help="Optional smoke-test task limit.")
    parser.add_argument("--start-index", type=int, default=1, help="First representative W index to include.")
    parser.add_argument("--end-index", type=int, default=None, help="Last representative W index to include.")
    parser.add_argument("--task-file", default=None, help="Optional TSV with explicit w_idx, w_word, x_word tasks.")
    parser.add_argument(
        "--task-timeout",
        type=float,
        default=None,
        help="Maximum seconds per task; timed-out tasks are checkpointed and skipped.",
    )
    parser.add_argument(
        "--task-order",
        choices=["round-robin", "by-index"],
        default="round-robin",
        help="Use round-robin to avoid all workers starting inside the same hard representative block.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    out_path = Path(args.out).expanduser().resolve()
    log_path = Path(args.log).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if args.task_file:
        tasks = load_task_file(Path(args.task_file).expanduser().resolve(), args.limit)
    else:
        tasks = build_tasks(args.project_root, args.start_index, args.end_index, args.limit)
    if args.task_order == "round-robin":
        tasks = round_robin_by_w(tasks)
    done_pairs = completed_pairs(out_path)
    todo = [task for task in tasks if (task[1], task[2]) not in done_pairs]

    log_line(
        log_path,
        f"pid={os.getpid()} project_root={Path(args.project_root).expanduser()} "
        f"tasks={len(tasks)} completed={len(done_pairs)} remaining={len(todo)} workers={args.workers} "
        f"app_dir={GITHUB_APP_DIR} engine_dir={ENGINE_DIR} mode=value_only",
    )
    print(f"remaining tasks: {len(todo)}", flush=True)
    print(f"output: {out_path}", flush=True)
    print(f"log: {log_path}", flush=True)
    if not todo:
        return 0

    if args.workers <= 1:
        run_serial(todo, out_path, log_path, args.project_root, args.task_timeout)
    else:
        run_parallel(todo, out_path, log_path, args.project_root, args.workers, args.task_timeout)

    log_line(log_path, "finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
