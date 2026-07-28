#!/usr/bin/env python3
"""Run and compare the optimized SL4 pairing engine on a full task cohort.

This is a shadow-only experiment.  It never edits the production engine or
the historical production TSV.  Results are keyed by (w_word, x_word), so the
comparison is independent of parallel completion order.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
import signal
import sys
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS = ROOT / "final_survivors_AFTER_MATCHING_FIX_tasks_20260723.tsv"
DEFAULT_PRODUCTION = (
    ROOT
    / "final_survivors_AFTER_MATCHING_FIX_pairing_values_GITHUB_REPO_20260723.tsv"
)
DEFAULT_SHADOW = ROOT / "full_dataset_shadow_optimized_20260726.tsv"
DEFAULT_LOG = ROOT / "full_dataset_shadow_optimized_20260726.log"
DEFAULT_COMPARISON = ROOT / "full_dataset_shadow_comparison_20260726.tsv"
DEFAULT_SUMMARY = ROOT / "full_dataset_shadow_summary_20260726.json"

OUTPUT_FIELDS = [
    "w_idx",
    "w_word",
    "x_word",
    "x_index",
    "status",
    "final_pairing_value",
    "used_three_strand_relation",
    "active_term_count",
    "discharged_term_count",
    "elapsed_sec",
    "moves",
    "children_generated",
    "terms_merged",
    "terms_cancelled",
    "move_cache_hits",
    "expansion_cache_hits",
    "lemma49_cache_hits",
    "engine_variant",
    "engine_fingerprint",
    "error",
]

COMPARISON_FIELDS = [
    "w_idx",
    "w_word",
    "x_word",
    "production_status",
    "production_value",
    "production_three_strand",
    "production_elapsed_sec",
    "shadow_status",
    "shadow_value",
    "shadow_three_strand",
    "shadow_elapsed_sec",
    "classification",
    "value_match",
    "three_strand_match",
    "shadow_error",
]

Task = Tuple[int, str, str]
_ENGINE: Any = None
_STREAMING: Any = None
_GRAPH_BY_WORD: Dict[str, Path] = {}
_PARSED: Dict[str, Tuple[Any, ...]] = {}
_ENGINE_FINGERPRINT = ""
_ENGINE_VARIANT = ""


class PairTimeout(TimeoutError):
    """Raised when one shadow pairing exceeds its wall-clock allowance."""


def _alarm_handler(_signum: int, _frame: Any) -> None:
    raise PairTimeout


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log_line(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{_stamp()}] {message}\n")
        handle.flush()


def load_tasks(path: Path, limit: Optional[int] = None) -> List[Task]:
    tasks: List[Task] = []
    seen = set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            w_word = (row.get("w_word") or "").strip()
            x_word = (row.get("x_word") or "").strip()
            if not w_word or not x_word:
                continue
            key = (w_word, x_word)
            if key in seen:
                raise ValueError(f"Duplicate task pair in {path}: {key}")
            seen.add(key)
            tasks.append((int((row.get("w_idx") or "0").strip()), w_word, x_word))
            if limit is not None and len(tasks) >= limit:
                break
    return tasks


def load_rows_by_pair(path: Path) -> Dict[Tuple[str, str], Dict[str, str]]:
    rows: Dict[Tuple[str, str], Dict[str, str]] = {}
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            key = (
                (row.get("w_word") or "").strip(),
                (row.get("x_word") or "").strip(),
            )
            if not all(key):
                continue
            if key in rows:
                raise ValueError(f"Duplicate pair in {path}: {key}")
            rows[key] = dict(row)
    return rows


def append_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})
        handle.flush()


def _find_graph_dir(project_root: Path) -> Path:
    candidates = [
        project_root / "4x4_All_graph_data",
        project_root / "hourglass_disk_4x4_all_graph_data",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"No 4x4 graph-data folder found under {project_root}"
    )


def _index_graphs(graph_dir: Path) -> Dict[str, Path]:
    result: Dict[str, Path] = {}
    for path in graph_dir.glob("*.json"):
        word = path.stem.rsplit("_", 1)[-1]
        if len(word) != 16 or set(word) - set("1234"):
            continue
        if word in result:
            raise ValueError(f"Duplicate graph JSON for {word}")
        result[word] = path
    if not result:
        raise FileNotFoundError(f"No graph JSON files found in {graph_dir}")
    return result


def _source_fingerprint(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:20]


def init_worker(project_root: str, engine_variant: str) -> None:
    global _ENGINE, _STREAMING, _GRAPH_BY_WORD, _PARSED
    global _ENGINE_FINGERPRINT, _ENGINE_VARIANT
    root = Path(project_root).expanduser().resolve()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    _ENGINE = importlib.import_module("Wrench_or_Skein_optimized_20260726")
    _ENGINE.set_optimized_embedding_mode("geometry")
    _STREAMING = importlib.import_module("streaming_x_evaluator_20260726")
    _ENGINE_VARIANT = str(engine_variant)
    _GRAPH_BY_WORD = _index_graphs(_find_graph_dir(root))
    _PARSED = {}
    sources = [
        ROOT / "Wrench_or_Skein_optimized_20260726.py",
        ROOT / "web_relation_rules_optimized_20260726.py",
        ROOT / "ribbon_cache_optimized_20260726.py",
        ROOT / "streaming_x_evaluator_20260726.py",
        Path(__file__).resolve(),
    ]
    _ENGINE_FINGERPRINT = _source_fingerprint(sources)


def parse_graph(word: str) -> Tuple[Any, Any, Any, Any, Any, int]:
    cached = _PARSED.get(word)
    if cached is not None:
        return cached
    path = _GRAPH_BY_WORD.get(word)
    if path is None:
        raise FileNotFoundError(f"No graph JSON indexed for {word}")
    adj, bounds, hourglasses = _ENGINE.parse_web(path)
    colors, xy = _ENGINE.parse_web_metadata(path)
    hourglasses = _ENGINE.sort_hourglasses_by_boundary_distance(
        adj, bounds, hourglasses
    )
    try:
        index = int(path.stem.split("_", 1)[0])
    except ValueError:
        index = 0
    result = (adj, bounds, hourglasses, colors, xy, index)
    _PARSED[word] = result
    return result


def _compute_one(
    task: Task,
    timeout_seconds: Optional[float],
    shared_x_caches: Optional[Dict[str, Dict[Any, Any]]] = None,
) -> Dict[str, Any]:
    if _ENGINE is None or _STREAMING is None:
        raise RuntimeError("worker not initialized")
    w_idx, w_word, x_word = task
    started = time.perf_counter()
    if timeout_seconds:
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
    try:
        w_adj, w_bounds, w_hgs, w_colors, w_xy, _ = parse_graph(w_word)
        x_adj, x_bounds, x_hgs, x_colors, x_xy, x_index = parse_graph(x_word)
        if _ENGINE_VARIANT == "cached_beam":
            proof = _ENGINE.prove_pair_value_by_x_component_coloring(
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
                source_web_sign=_ENGINE.word_inversion_sign(x_word),
                use_lemma48=False,
                use_lemma49=True,
                allow_three_strand=True,
            )
            stats = (
                _ENGINE.optimization_stats()
                if hasattr(_ENGINE, "optimization_stats")
                else {}
            )
            lemma_stats = {}
            proof_status = (
                "completed"
                if proof.get("final_pairing_value") is not None
                and not proof.get("active_term_count")
                else str(proof.get("status", "partial"))
            )
        elif _ENGINE_VARIANT == "streaming":
            evaluator = _STREAMING.StreamingXEvaluator(
                _ENGINE,
                x_boundary_labels=x_bounds,
                w_boundary_labels=w_bounds,
                x_node_colors=x_colors,
                w_node_colors=w_colors,
                x_node_xy=x_xy,
                source_web_sign=_ENGINE.word_inversion_sign(x_word),
                use_lemma49=True,
                compiled_lemma49=True,
                allow_three_strand=True,
                canonical_merge=True,
                lookahead=True,
                persistent_cache=None,
            )
            # These caches depend only on X and its embedding. W-sensitive fork,
            # Lemma 4.9, and coloring caches deliberately remain evaluator-local.
            if shared_x_caches is not None:
                evaluator.move_cache = shared_x_caches.setdefault("moves", {})
                evaluator.expansion_cache = shared_x_caches.setdefault(
                    "expansions", {}
                )
                evaluator.x_fork_cache = shared_x_caches.setdefault("x_forks", {})
            deadline = (
                time.perf_counter() + float(timeout_seconds)
                if timeout_seconds
                else None
            )
            proof = evaluator.evaluate(
                _STREAMING.make_initial_term(x_adj, x_hgs, w_adj, w_hgs),
                deadline=deadline,
            )
            stats = proof.get("stats") or {}
            lemma_stats = proof.get("lemma49_matcher_stats") or {}
            proof_status = str(proof.get("status", ""))
        else:
            raise ValueError(f"Unknown shadow engine variant: {_ENGINE_VARIANT}")
        return {
            "w_idx": w_idx,
            "w_word": w_word,
            "x_word": x_word,
            "x_index": x_index,
            "status": proof_status,
            "final_pairing_value": (
                ""
                if proof.get("final_pairing_value") is None
                else proof.get("final_pairing_value")
            ),
            "used_three_strand_relation": (
                "yes" if proof.get("used_three_strand_relation") else "no"
            ),
            "active_term_count": proof.get("active_term_count", ""),
            "discharged_term_count": proof.get("discharged_term_count", ""),
            "elapsed_sec": f"{time.perf_counter() - started:.6f}",
            "moves": stats.get("moves", ""),
            "children_generated": stats.get("children_generated", ""),
            "terms_merged": stats.get(
                "terms_merged", stats.get("term_merges", "")
            ),
            "terms_cancelled": stats.get("terms_cancelled", ""),
            "move_cache_hits": stats.get("move_cache_hits", ""),
            "expansion_cache_hits": stats.get("expansion_cache_hits", ""),
            "lemma49_cache_hits": lemma_stats.get(
                "state_cache_hits",
                stats.get("lemma49_cache_hits", ""),
            ),
            "engine_variant": _ENGINE_VARIANT,
            "engine_fingerprint": _ENGINE_FINGERPRINT,
            "error": "",
        }
    except PairTimeout:
        return {
            "w_idx": w_idx,
            "w_word": w_word,
            "x_word": x_word,
            "status": "timeout",
            "elapsed_sec": f"{time.perf_counter() - started:.6f}",
            "engine_variant": _ENGINE_VARIANT,
            "engine_fingerprint": _ENGINE_FINGERPRINT,
            "error": f"PairTimeout: exceeded {timeout_seconds}s",
        }
    except Exception as exc:  # Keep a complete, resumable audit trail.
        return {
            "w_idx": w_idx,
            "w_word": w_word,
            "x_word": x_word,
            "status": "error",
            "elapsed_sec": f"{time.perf_counter() - started:.6f}",
            "engine_variant": _ENGINE_VARIANT,
            "engine_fingerprint": _ENGINE_FINGERPRINT,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if timeout_seconds:
            signal.setitimer(signal.ITIMER_REAL, 0)


def compute_x_group(
    tasks: Sequence[Task], timeout_seconds: Optional[float]
) -> List[Dict[str, Any]]:
    shared: Dict[str, Dict[Any, Any]] = {}
    return [_compute_one(task, timeout_seconds, shared) for task in tasks]


def group_by_x(tasks: Sequence[Task], chunk_size: int) -> List[List[Task]]:
    grouped: Dict[str, List[Task]] = {}
    for task in tasks:
        grouped.setdefault(task[2], []).append(task)
    chunks: List[List[Task]] = []
    size = max(1, int(chunk_size))
    for x_word in sorted(grouped):
        items = sorted(grouped[x_word], key=lambda item: (item[0], item[1]))
        chunks.extend(
            items[offset : offset + size]
            for offset in range(0, len(items), size)
        )
    chunks.sort(key=lambda group: (-len(group), group[0][2], group[0][0]))
    return chunks


def run_shadow(args: argparse.Namespace) -> None:
    task_path = Path(args.tasks).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    log_path = Path(args.log).expanduser().resolve()
    tasks = load_tasks(task_path, args.limit)
    done = load_rows_by_pair(out_path)
    todo = [task for task in tasks if (task[1], task[2]) not in done]
    groups = group_by_x(todo, args.x_cache_chunk)
    log_line(
        log_path,
        f"start tasks={len(tasks)} already_done={len(done)} remaining={len(todo)} "
        f"groups={len(groups)} workers={args.workers} timeout={args.task_timeout}s "
        f"engine={args.engine} input={task_path} output={out_path}",
    )
    print(f"remaining tasks: {len(todo)}", flush=True)
    print(f"output: {out_path}", flush=True)
    print(f"log: {log_path}", flush=True)
    if not todo:
        log_line(log_path, "finished (nothing remaining)")
        return

    started = time.time()
    completed = 0
    submitted = 0
    last_log = started
    max_pending = max(1, int(args.workers) * 2)
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=init_worker,
        initargs=(args.project_root, args.engine),
    ) as executor:
        pending: Dict[Any, List[Task]] = {}
        while submitted < len(groups) and len(pending) < max_pending:
            group = groups[submitted]
            future = executor.submit(
                compute_x_group, group, args.task_timeout
            )
            pending[future] = group
            submitted += 1

        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                group = pending.pop(future)
                try:
                    rows = future.result()
                except Exception as exc:
                    rows = [
                        {
                            "w_idx": task[0],
                            "w_word": task[1],
                            "x_word": task[2],
                            "status": "worker_error",
                            "elapsed_sec": "",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                        for task in group
                    ]
                append_rows(out_path, rows)
                completed += len(rows)
                while submitted < len(groups) and len(pending) < max_pending:
                    next_group = groups[submitted]
                    next_future = executor.submit(
                        compute_x_group, next_group, args.task_timeout
                    )
                    pending[next_future] = next_group
                    submitted += 1

            now = time.time()
            if completed == len(todo) or now - last_log >= 60:
                rate = completed / max(now - started, 1e-9)
                eta = (len(todo) - completed) / max(rate, 1e-9)
                counts = Counter(
                    row.get("status", "")
                    for row in load_rows_by_pair(out_path).values()
                )
                log_line(
                    log_path,
                    f"done={completed}/{len(todo)} total_rows={len(done)+completed} "
                    f"rate={rate:.3f}/s eta={eta/3600:.2f}h statuses={dict(counts)}",
                )
                last_log = now
    log_line(log_path, "finished")


def _normalized_value(row: Mapping[str, str]) -> Optional[int]:
    value = (row.get("final_pairing_value") or "").strip()
    if value == "":
        return None
    return int(value)


def compare_results(args: argparse.Namespace) -> None:
    task_path = Path(args.tasks).expanduser().resolve()
    production_path = Path(args.production).expanduser().resolve()
    shadow_path = Path(args.shadow).expanduser().resolve()
    comparison_path = Path(args.comparison).expanduser().resolve()
    summary_path = Path(args.summary).expanduser().resolve()

    tasks = load_tasks(task_path)
    task_keys = {(w, x) for _, w, x in tasks}
    production = load_rows_by_pair(production_path)
    shadow = load_rows_by_pair(shadow_path)
    rows: List[Dict[str, Any]] = []
    classifications = Counter()
    value_mismatches = []
    three_strand_mismatches = []
    for w_idx, w_word, x_word in tasks:
        key = (w_word, x_word)
        prod = production.get(key)
        new = shadow.get(key)
        if prod is None:
            classification = "missing_production"
            prod_value = None
        else:
            prod_value = _normalized_value(prod)
            if new is None:
                classification = "missing_shadow"
            else:
                shadow_value = _normalized_value(new)
                if prod_value is not None and shadow_value is not None:
                    classification = (
                        "resolved_value_match"
                        if prod_value == shadow_value
                        else "resolved_value_mismatch"
                    )
                elif prod_value is None and shadow_value is not None:
                    classification = "shadow_resolved_production_unresolved"
                elif prod_value is not None and shadow_value is None:
                    classification = "shadow_unresolved_production_resolved"
                else:
                    classification = "both_unresolved"
        new = new or {}
        prod = prod or {}
        shadow_value = _normalized_value(new) if new else None
        value_match = (
            ""
            if prod_value is None or shadow_value is None
            else "yes" if prod_value == shadow_value else "no"
        )
        prod_three = (prod.get("used_three_strand_relation") or "").strip()
        new_three = (new.get("used_three_strand_relation") or "").strip()
        three_match = (
            ""
            if not prod_three or not new_three
            else "yes" if prod_three == new_three else "no"
        )
        row = {
            "w_idx": w_idx,
            "w_word": w_word,
            "x_word": x_word,
            "production_status": prod.get("status", ""),
            "production_value": "" if prod_value is None else prod_value,
            "production_three_strand": prod_three,
            "production_elapsed_sec": prod.get("elapsed_sec", ""),
            "shadow_status": new.get("status", ""),
            "shadow_value": "" if shadow_value is None else shadow_value,
            "shadow_three_strand": new_three,
            "shadow_elapsed_sec": new.get("elapsed_sec", ""),
            "classification": classification,
            "value_match": value_match,
            "three_strand_match": three_match,
            "shadow_error": new.get("error", ""),
        }
        rows.append(row)
        classifications[classification] += 1
        if classification == "resolved_value_mismatch":
            value_mismatches.append(row)
        if three_match == "no":
            three_strand_mismatches.append(row)

    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    with comparison_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=COMPARISON_FIELDS, delimiter="\t"
        )
        writer.writeheader()
        writer.writerows(rows)

    shadow_statuses = Counter(
        row.get("status", "") for key, row in shadow.items() if key in task_keys
    )
    summary = {
        "generated_at": _stamp(),
        "task_file": str(task_path),
        "production_file": str(production_path),
        "shadow_file": str(shadow_path),
        "task_count": len(tasks),
        "production_task_rows": len(task_keys & set(production)),
        "production_extra_rows": len(set(production) - task_keys),
        "shadow_task_rows": len(task_keys & set(shadow)),
        "shadow_extra_rows": len(set(shadow) - task_keys),
        "shadow_status_counts": dict(sorted(shadow_statuses.items())),
        "classification_counts": dict(sorted(classifications.items())),
        "resolved_value_mismatch_count": len(value_mismatches),
        "three_strand_mismatch_count": len(three_strand_mismatches),
        "comparison_file": str(comparison_path),
        "safe_to_replace_production": (
            len(shadow) >= len(tasks)
            and not value_mismatches
            and classifications.get("shadow_unresolved_production_resolved", 0)
            == 0
            and classifications.get("missing_shadow", 0) == 0
        ),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def select_preflight(args: argparse.Namespace) -> None:
    tasks = load_tasks(Path(args.tasks).expanduser().resolve())
    production = load_rows_by_pair(Path(args.production).expanduser().resolve())
    buckets: Dict[str, List[Task]] = {
        "minus_two": [],
        "minus_one": [],
        "zero": [],
        "plus_one": [],
        "partial": [],
        "timeout": [],
    }
    for task in tasks:
        row = production.get((task[1], task[2]), {})
        status = row.get("status", "")
        value = _normalized_value(row) if row else None
        if status == "timeout":
            bucket = "timeout"
        elif value is None:
            bucket = "partial"
        elif value == -2:
            bucket = "minus_two"
        elif value == -1:
            bucket = "minus_one"
        elif value == 1:
            bucket = "plus_one"
        else:
            bucket = "zero"
        buckets[bucket].append(task)

    quotas = {
        "minus_two": len(buckets["minus_two"]),
        "minus_one": args.nonzero_each,
        "plus_one": args.nonzero_each,
        "zero": args.zero,
        "partial": args.unresolved_each,
        "timeout": args.unresolved_each,
    }
    selected: List[Task] = []
    for bucket, items in buckets.items():
        # Stable pseudo-random ordering independent of Python hash seed.
        ranked = sorted(
            items,
            key=lambda task: hashlib.sha256(
                f"{args.seed}:{task[1]}:{task[2]}".encode()
            ).digest(),
        )
        selected.extend(ranked[: quotas[bucket]])
    selected.sort(key=lambda task: (task[0], task[1], task[2]))
    out_path = Path(args.out).expanduser().resolve()
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["w_idx", "w_word", "x_word"], delimiter="\t"
        )
        writer.writeheader()
        for w_idx, w_word, x_word in selected:
            writer.writerow(
                {"w_idx": w_idx, "w_word": w_word, "x_word": x_word}
            )
    print(
        json.dumps(
            {
                "output": str(out_path),
                "selected": len(selected),
                "bucket_sizes": {key: len(value) for key, value in buckets.items()},
                "quotas": quotas,
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample = subparsers.add_parser("sample", help="Create a stratified preflight task file.")
    sample.add_argument("--tasks", default=str(DEFAULT_TASKS))
    sample.add_argument("--production", default=str(DEFAULT_PRODUCTION))
    sample.add_argument(
        "--out", default=str(ROOT / "full_dataset_shadow_preflight_tasks_20260726.tsv")
    )
    sample.add_argument("--zero", type=int, default=120)
    sample.add_argument("--nonzero-each", type=int, default=30)
    sample.add_argument("--unresolved-each", type=int, default=30)
    sample.add_argument("--seed", default="shadow-preflight-v1")
    sample.set_defaults(func=select_preflight)

    run = subparsers.add_parser("run", help="Run or resume the optimized shadow evaluation.")
    run.add_argument("--tasks", default=str(DEFAULT_TASKS))
    run.add_argument("--out", default=str(DEFAULT_SHADOW))
    run.add_argument("--log", default=str(DEFAULT_LOG))
    run.add_argument("--project-root", default=str(ROOT))
    run.add_argument("--workers", type=int, default=min(12, os.cpu_count() or 1))
    run.add_argument("--task-timeout", type=float, default=600.0)
    run.add_argument("--x-cache-chunk", type=int, default=32)
    run.add_argument(
        "--engine",
        choices=["cached_beam", "streaming"],
        default="cached_beam",
        help=(
            "cached_beam preserves the production beam/search semantics; "
            "streaming is an experimental exhaustive worklist reducer"
        ),
    )
    run.add_argument("--limit", type=int, default=None)
    run.set_defaults(func=run_shadow)

    compare = subparsers.add_parser("compare", help="Compare shadow and production TSVs.")
    compare.add_argument("--tasks", default=str(DEFAULT_TASKS))
    compare.add_argument("--production", default=str(DEFAULT_PRODUCTION))
    compare.add_argument("--shadow", default=str(DEFAULT_SHADOW))
    compare.add_argument("--comparison", default=str(DEFAULT_COMPARISON))
    compare.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    compare.set_defaults(func=compare_results)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
