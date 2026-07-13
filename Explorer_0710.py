#!/usr/bin/env python3
"""Second pass for rows that the fast wrench/fork proof left partial."""

from __future__ import annotations

import argparse
import csv
import copy
import html
import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Set, Tuple


FIELDNAMES = [
    "w_idx",
    "w_word",
    "x_word",
    "x_index",
    "old_status",
    "new_status",
    "active_term_count",
    "discharged_term_count",
    "final_pairing_value",
    "unit_value_ok",
    "coloring_status",
    "steps_used",
    "elapsed_sec",
    "error",
]

_APP = None
_WRENCH = None


def install_july10_smoothing(wrench: Any) -> None:
    """Restore the smoothing convention used by the saved July 10 table.

    The current ``Wrench_or_Skein.py`` has the corrected convention.  The
    checkpoint table ``rep_pairing_partial_resolution_hourglass.tsv`` was made
    before that relabeling: the branch called ``crossing`` used the across
    splice, and the branch called ``parallel`` used the crossed/diagonal splice.
    Keep this compatibility patch local to ``0710.py`` so the newer code is not
    changed.
    """

    def july10_smooth_one_hourglass(adj: Any, hg: Dict[str, Any], smoothing: str) -> Any:
        if smoothing not in {"crossing", "parallel"}:
            raise ValueError("smoothing must be 'crossing' or 'parallel'.")

        left = int(hg["left"])
        right = int(hg["right"])
        if left not in adj or right not in adj:
            raise ValueError(f"Hourglass endpoint already removed: {left}-{right}.")
        if not isinstance(adj[left], dict) or not isinstance(adj[right], dict):
            raise ValueError(f"Hourglass endpoints must carry current top/bot ports: {left}-{right}.")

        lt = int(adj[left]["top"])
        lb = int(adj[left]["bot"])
        rt = int(adj[right]["top"])
        rb = int(adj[right]["bot"])

        new_adj = copy.deepcopy(adj)
        if smoothing == "crossing":
            wrench.splice_pair(new_adj, left, lt, right, rt)
            wrench.splice_pair(new_adj, left, lb, right, rb)
        else:
            wrench.splice_pair(new_adj, left, lt, right, rb)
            wrench.splice_pair(new_adj, left, lb, right, rt)

        del new_adj[left]
        del new_adj[right]
        new_adj = wrench.drop_nonreciprocal_references(new_adj)
        wrench.validate_adjacency(new_adj)
        return new_adj

    wrench.smooth_one_hourglass = july10_smooth_one_hourglass


def init_worker(project_root: str) -> None:
    global _APP, _WRENCH
    import wrench_web_app as app

    app.configure_project_root(project_root)
    _APP = app
    _WRENCH = app.wrench
    install_july10_smoothing(_WRENCH)


def read_rows(path: Path) -> list[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


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


def coloring_statuses(evaluations: list[Dict[str, Any]]) -> str:
    parts = []
    for evaluation in evaluations:
        status = str(evaluation.get("status", ""))
        reason = str(evaluation.get("reason", ""))
        if reason:
            parts.append(f"{status}:{reason}")
        elif status:
            parts.append(status)
    return ";".join(parts)


def unit_value_ok(raw_value: Any) -> str:
    if raw_value is None or raw_value == "":
        return ""
    try:
        return "yes" if int(raw_value) in {-1, 0, 1} else "no"
    except (TypeError, ValueError):
        return "no"


def resolve_one(task: Tuple[Dict[str, str], int, int]) -> Dict[str, Any]:
    if _APP is None or _WRENCH is None:
        raise RuntimeError("worker was not initialized")
    app = _APP
    wrench = _WRENCH
    row, beam_width, max_steps = task
    start = time.time()
    try:
        x_path = app.resolve_graph(row["x_word"], "X")
        w_path = app.resolve_graph(row["w_word"], "W")
        x_adj, x_bounds, x_hgs = wrench.parse_web(x_path)
        w_adj, w_bounds, w_hgs = wrench.parse_web(w_path)
        x_hgs = wrench.sort_hourglasses_by_boundary_distance(x_adj, x_bounds, x_hgs)
        w_hgs = wrench.sort_hourglasses_by_boundary_distance(w_adj, w_bounds, w_hgs)
        proof = wrench.prove_pair_value_by_wrench_forks_complete(
            x_adj,
            x_bounds,
            x_hgs,
            w_adj,
            w_bounds,
            w_hgs,
            allow_w_wrench=True,
            beam_width=beam_width,
            max_steps=max_steps,
        )
        value = proof.get("final_pairing_value")
        return {
            "w_idx": row["w_idx"],
            "w_word": row["w_word"],
            "x_word": row["x_word"],
            "x_index": row["x_index"],
            "old_status": row.get("status", ""),
            "new_status": proof.get("status", ""),
            "active_term_count": proof.get("active_term_count", ""),
            "discharged_term_count": proof.get("discharged_term_count", ""),
            "final_pairing_value": "" if value is None else value,
            "unit_value_ok": unit_value_ok(value),
            "coloring_status": coloring_statuses(proof.get("coloring_evaluations", [])),
            "steps_used": len(proof.get("steps", [])),
            "elapsed_sec": f"{time.time() - start:.3f}",
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - checkpoint errors and continue.
        return {
            "w_idx": row.get("w_idx", ""),
            "w_word": row.get("w_word", ""),
            "x_word": row.get("x_word", ""),
            "x_index": row.get("x_index", ""),
            "old_status": row.get("status", ""),
            "new_status": "error",
            "active_term_count": "",
            "discharged_term_count": "",
            "final_pairing_value": "",
            "unit_value_ok": "",
            "coloring_status": "",
            "steps_used": "",
            "elapsed_sec": f"{time.time() - start:.3f}",
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_parallel(
    rows: Sequence[Dict[str, str]],
    out_path: Path,
    log_path: Path,
    project_root: str,
    workers: int,
    beam_width: int,
    max_steps: int,
) -> None:
    start = time.time()
    last_log = start
    submitted = 0
    completed = 0
    max_pending = max(workers * 2, 1)
    tasks = [(row, beam_width, max_steps) for row in rows]
    with ProcessPoolExecutor(max_workers=workers, initializer=init_worker, initargs=(project_root,)) as executor:
        pending = {}
        while submitted < len(tasks) and len(pending) < max_pending:
            future = executor.submit(resolve_one, tasks[submitted])
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
                    future = executor.submit(resolve_one, tasks[submitted])
                    pending[future] = tasks[submitted]
                    submitted += 1

            now = time.time()
            if completed == len(tasks) or completed % 10 == 0 or now - last_log >= 60:
                rate = completed / max(now - start, 0.001)
                eta = (len(tasks) - completed) / max(rate, 0.001)
                log_line(
                    log_path,
                    f"done {completed}/{len(tasks)} submitted={submitted} "
                    f"rate={rate:.2f}/s eta={eta/3600:.2f}h",
                )
                last_log = now


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", action="store_true", help="Launch the local website with the July 10 smoothing convention.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for --web mode.")
    parser.add_argument("--port", type=int, default=8765, help="Port for --web mode.")
    parser.add_argument("--project-root", default=os.environ.get("PROBLEM3_ROOT", str(Path(__file__).resolve().parent)))
    parser.add_argument("--input", default="rep_pairing_partial_rows.tsv")
    parser.add_argument("--out", default="rep_pairing_partial_resolution.tsv")
    parser.add_argument("--log", default="rep_pairing_partial_resolution.log")
    parser.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--beam-width", type=int, default=200)
    parser.add_argument("--max-steps", type=int, default=80)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args(argv)


def run_web(args: argparse.Namespace) -> int:
    import wrench_web_app as app

    app.configure_project_root(args.project_root)
    install_july10_smoothing(app.wrench)

    def july10_complete_proof_for_web(
        x_adj: Any,
        x_bounds: Any,
        x_hgs: Any,
        w_adj: Any,
        w_bounds: Any,
        w_hgs: Any,
        *,
        allow_w_wrench: bool = True,
        guided_beam_width: int = 120,
        guided_steps: Optional[int] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        return app.wrench.prove_pair_value_by_wrench_forks_complete(
            x_adj,
            x_bounds,
            x_hgs,
            w_adj,
            w_bounds,
            w_hgs,
            allow_w_wrench=allow_w_wrench,
            beam_width=guided_beam_width,
            max_steps=guided_steps or 80,
        )

    app.wrench.prove_pair_value_by_x_component_coloring = july10_complete_proof_for_web

    original_run_pair = app.run_pair
    july10_table_cache: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None

    def load_july10_table() -> Dict[Tuple[str, str], Dict[str, str]]:
        nonlocal july10_table_cache
        if july10_table_cache is not None:
            return july10_table_cache
        table: Dict[Tuple[str, str], Dict[str, str]] = {}
        table_path = Path(args.project_root) / "rep_pairing_partial_resolution_hourglass.tsv"
        if table_path.exists():
            with table_path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    w_word = (row.get("w_word") or "").strip()
                    x_word = (row.get("x_word") or "").strip()
                    if w_word and x_word:
                        table[(w_word, x_word)] = row
        july10_table_cache = table
        return table

    def fast_july10_run_pair(params: Dict[str, str]) -> str:
        if params.get("show_steps") == "1":
            return original_run_pair(params)

        x_path, w_path, pair_mode = app.resolve_pair(params)
        x_word = app.graph_word(x_path)
        w_word = app.graph_word(w_path)
        x_index = app.graph_index(x_path)
        w_index = app.graph_index(w_path)

        saved = load_july10_table().get((w_word, x_word))
        if saved is not None:
            status = saved.get("new_status", "")
            value = saved.get("final_pairing_value", "")
            active = saved.get("active_term_count", "")
            discharged = saved.get("discharged_term_count", "")
            source_note = "Loaded from rep_pairing_partial_resolution_hourglass.tsv."
        else:
            max_steps_raw = params.get("max_steps", "").strip()
            max_steps = None if max_steps_raw in {"", "auto", "8"} else int(max_steps_raw)
            beam_width = int(params.get("beam_width", "120") or "120")
            allow_w = params.get("allow_w", "1") == "1"
            x_adj, x_bounds, x_hgs = app.wrench.parse_web(x_path)
            w_adj, w_bounds, w_hgs = app.wrench.parse_web(w_path)
            x_hgs = app.wrench.sort_hourglasses_by_boundary_distance(x_adj, x_bounds, x_hgs)
            w_hgs = app.wrench.sort_hourglasses_by_boundary_distance(w_adj, w_bounds, w_hgs)
            proof = app.wrench.prove_pair_value_by_wrench_forks_complete(
                x_adj,
                x_bounds,
                x_hgs,
                w_adj,
                w_bounds,
                w_hgs,
                allow_w_wrench=allow_w,
                beam_width=beam_width,
                max_steps=max_steps or 80,
            )
            status = str(proof.get("status", ""))
            value = str(proof.get("final_pairing_value", ""))
            active = str(proof.get("active_term_count", ""))
            discharged = str(proof.get("discharged_term_count", ""))
            source_note = "Computed with July 10 recovered proof route; step pictures were skipped."

        return app.page_shell(
            params,
            f"""
            <section class="summary">
              <div>
                <h2>Pairing Result</h2>
                <p><strong>Mode:</strong> {html.escape(pair_mode)} / July 10 fast mode</p>
                <p><strong>W:</strong> <span class="muted">{w_index:04d}</span> <span class="word">{html.escape(w_word)}</span></p>
                <p><strong>X:</strong> <span class="muted">{x_index:04d}</span> <span class="word">{html.escape(x_word)}</span></p>
                <p class="muted">{html.escape(source_note)}</p>
              </div>
              <div class="result-pill">{html.escape(status)}</div>
              <div class="metric"><span>Fork-killed branches</span><strong>{html.escape(discharged)}</strong></div>
              <div class="metric"><span>Active branches left</span><strong>{html.escape(active)}</strong></div>
              <div class="metric"><span>Final pairing value</span><strong>{html.escape(value)}</strong></div>
            </section>
            <section class="toc">
              <h2>Fast July 10 Mode</h2>
              <p>This page skips the heavy step-by-step SVG reconstruction. Turn on full step pictures only when you need the visual proof tree.</p>
            </section>
            """,
        )

    app.run_pair = fast_july10_run_pair
    app.warm_lookup_caches()
    server = app.ThreadingHTTPServer((args.host, args.port), app.AppHandler)
    print(f"July 10 Wrench Pairing Explorer running at http://{args.host}:{args.port}/")
    print(f"Using graph data from {app.PROJECT_ROOT}")
    server.serve_forever()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.web:
        return run_web(args)

    input_path = Path(args.input).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    log_path = Path(args.log).expanduser().resolve()
    rows = read_rows(input_path)
    if args.limit is not None:
        rows = rows[: args.limit]
    done = completed_pairs(out_path)
    todo = [row for row in rows if (row["w_word"], row["x_word"]) not in done]
    log_line(
        log_path,
        f"pid={os.getpid()} input={input_path} remaining={len(todo)} "
        f"workers={args.workers} beam={args.beam_width} max_steps={args.max_steps}",
    )
    print(f"remaining partial rows: {len(todo)}")
    print(f"output: {out_path}")
    print(f"log: {log_path}")
    if not todo:
        return 0
    if args.workers <= 1:
        init_worker(args.project_root)
        for index, row in enumerate(todo, start=1):
            append_row(out_path, resolve_one((row, args.beam_width, args.max_steps)))
            if index % 10 == 0 or index == len(todo):
                log_line(log_path, f"done {index}/{len(todo)}")
    else:
        run_parallel(todo, out_path, log_path, args.project_root, args.workers, args.beam_width, args.max_steps)
    log_line(log_path, "finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
