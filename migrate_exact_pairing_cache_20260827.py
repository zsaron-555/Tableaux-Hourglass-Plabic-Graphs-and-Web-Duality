#!/usr/bin/env python3
"""Relocate authenticated exact-pairing caches into a repartitioned task queue.

The mathematical cache key is independent of shard assignment.  This utility
finds completed records from every old shard, verifies their checkpoint bytes,
and makes them available in the shard that now owns the same exact task.  Each
current checkpoint is materialized as an independent file.  This is necessary
because replacing a hard-linked stale checkpoint changes the shared inode's
ctime and correctly trips the manifest runner's immutable-input audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import run_exact_pairing_manifest_contraction_20260825 as adapter


SCHEMA = "problem3.exact_pairing_cache_migration_audit.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _materialize_copy(path: Path) -> None:
    """Replace ``path`` with an independent byte-identical regular file."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    shutil.copyfile(path, temporary)
    os.replace(temporary, path)


def _current_module_manifest_sha256() -> str:
    base = adapter._base
    snapshots = base.SnapshotStore()
    hashes = base._local_dependency_closure(
        [Path(adapter.__file__).resolve(), base.ROOT / "exact_pairing_scheduler_20260819.py"],
        snapshots,
    )
    base._validate_core_pins(hashes)
    return base._semantic_sha256(hashes)


def _task_cache_key(
    task: Mapping[str, Any],
    manifest_settings: Mapping[str, Any],
    module_manifest_sha256: str,
) -> str:
    base = adapter._base
    settings = base._normalized_settings(
        {**dict(manifest_settings), **dict(task.get("settings", {}))},
        context=f"task {task.get('task_id')}.settings",
    )
    payload = {
        "schema": "problem3.exact_pairing_manifest_cache_key.v1",
        "w_exact_digest": task["w"]["expected_exact_digest"],
        "x_exact_digest": task["x"]["expected_exact_digest"],
        "x_boundary_word": task["x_boundary_word"],
        "source_web_sign": task["source_web_sign"],
        "settings": settings,
        "local_dependency_hash_manifest_sha256": module_manifest_sha256,
    }
    return base._semantic_sha256(payload)


def _checkpoint_for_record(record_path: Path, record: Mapping[str, Any]) -> Path:
    declared = Path(str(record.get("checkpoint_path", "")))
    if not declared.is_absolute():
        declared = (record_path.parent / declared).resolve()
    return declared


def migrate(root: Path) -> dict[str, Any]:
    root = root.resolve()
    module_sha = _current_module_manifest_sha256()
    source_records: dict[str, tuple[Path, Path, dict[str, Any]]] = {}
    duplicate_keys: Counter[str] = Counter()
    ignored = Counter()

    record_paths = sorted(root.glob("run_shard*/cache_records/*.json"))
    for record_path in record_paths:
        record = _load(record_path)
        if not isinstance(record, Mapping):
            ignored["non_object"] += 1
            continue
        key = record.get("cache_key")
        if not isinstance(key, str) or record_path.stem != key:
            ignored["invalid_cache_key"] += 1
            continue
        if record.get("status") != "computed":
            ignored[f"status_{record.get('status')}"] += 1
            continue
        if record.get("local_dependency_hash_manifest_sha256") != module_sha:
            ignored["module_hash_mismatch"] += 1
            continue
        checkpoint_path = _checkpoint_for_record(record_path, record)
        if not checkpoint_path.is_file():
            ignored["missing_checkpoint"] += 1
            continue
        if _sha256(checkpoint_path) != record.get("checkpoint_sha256"):
            ignored["checkpoint_hash_mismatch"] += 1
            continue
        previous = source_records.get(key)
        if previous is not None:
            duplicate_keys[key] += 1
            if previous[2].get("checkpoint_sha256") != record.get("checkpoint_sha256"):
                raise RuntimeError(f"Conflicting checkpoints for cache key {key}")
            continue
        source_records[key] = (record_path, checkpoint_path, dict(record))

    manifests = sorted(root.glob("PAIRING_TASK_MANIFEST.shard*.json"))
    if not manifests:
        raise RuntimeError(f"No shard manifests found under {root}")

    counts = Counter()
    missing: list[dict[str, Any]] = []
    seen_tasks: set[str] = set()
    seen_keys: set[str] = set()
    per_shard: dict[str, dict[str, int]] = {}

    for manifest_path in manifests:
        manifest = _load(manifest_path)
        settings = manifest.get("settings", {})
        shard_name = manifest_path.stem.rsplit(".", 1)[-1]
        run_dir = root / f"run_{shard_name}"
        record_dir = run_dir / "cache_records"
        checkpoint_dir = run_dir / "scheduler_checkpoints"
        record_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        shard_counts = Counter()

        for task in manifest["tasks"]:
            task_id = str(task["task_id"])
            if task_id in seen_tasks:
                raise RuntimeError(f"Duplicate current task id {task_id}")
            seen_tasks.add(task_id)
            key = _task_cache_key(task, settings, module_sha)
            if key in seen_keys:
                counts["duplicate_current_cache_key"] += 1
            seen_keys.add(key)
            target_record = record_dir / f"{key}.json"
            target_checkpoint = checkpoint_dir / f"{key}.json"

            if target_record.is_file() and target_checkpoint.is_file():
                local = _load(target_record)
                if (
                    local.get("cache_key") == key
                    and local.get("status") != "computed"
                ):
                    counts["local_noncomputed"] += 1
                    shard_counts["local_noncomputed"] += 1
                    continue
                if (
                    local.get("cache_key") == key
                    and local.get("status") == "computed"
                    and local.get("local_dependency_hash_manifest_sha256") == module_sha
                    and local.get("checkpoint_path") == str(target_checkpoint.resolve())
                    and local.get("checkpoint_sha256") == _sha256(target_checkpoint)
                ):
                    if target_checkpoint.stat().st_nlink > 1:
                        _materialize_copy(target_checkpoint)
                        counts["materialized_existing_checkpoint"] += 1
                        shard_counts["materialized_existing_checkpoint"] += 1
                    counts["already_local"] += 1
                    shard_counts["already_local"] += 1
                    continue
                raise RuntimeError(f"Invalid existing target cache for {task_id}: {target_record}")

            source = source_records.get(key)
            if source is None:
                counts["not_cached"] += 1
                shard_counts["not_cached"] += 1
                missing.append({"task_id": task_id, "cache_key": key})
                continue

            source_record_path, source_checkpoint, source_record = source
            if target_checkpoint.exists():
                if _sha256(target_checkpoint) != source_record["checkpoint_sha256"]:
                    raise RuntimeError(f"Conflicting target checkpoint {target_checkpoint}")
                if target_checkpoint.stat().st_nlink > 1:
                    _materialize_copy(target_checkpoint)
                    counts["materialized_existing_checkpoint"] += 1
                    shard_counts["materialized_existing_checkpoint"] += 1
            else:
                temporary = target_checkpoint.with_name(
                    f".{target_checkpoint.name}.{os.getpid()}.tmp"
                )
                shutil.copyfile(source_checkpoint, temporary)
                counts["checkpoint_copies"] += 1
                os.replace(temporary, target_checkpoint)

            migrated_record = dict(source_record)
            migrated_record["checkpoint_path"] = str(target_checkpoint.resolve())
            _atomic_json(target_record, migrated_record)
            counts["migrated"] += 1
            shard_counts["migrated"] += 1
            if source_record_path.parent.parent == run_dir:
                counts["repaired_local_record"] += 1
            else:
                counts["moved_across_shards"] += 1

        per_shard[shard_name] = dict(sorted(shard_counts.items()))

    audit = {
        "schema": SCHEMA,
        "root": str(root),
        "local_dependency_hash_manifest_sha256": module_sha,
        "source_record_file_count": len(record_paths),
        "authenticated_computed_source_key_count": len(source_records),
        "duplicate_source_key_count": len(duplicate_keys),
        "ignored_source_records": dict(sorted(ignored.items())),
        "current_task_count": len(seen_tasks),
        "current_unique_cache_key_count": len(seen_keys),
        "counts": dict(sorted(counts.items())),
        "per_shard": per_shard,
        "not_cached": missing,
    }
    audit["semantic_sha256"] = adapter._base._semantic_sha256(audit)
    _atomic_json(root / "CACHE_MIGRATION_AUDIT.json", audit)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    audit = migrate(args.root)
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
