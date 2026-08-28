#!/usr/bin/env python3
from __future__ import annotations

import ast
import csv
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("PROBLEM3_ROOT", str(PROJECT.parent))).expanduser()
WRENCH_ROOT = Path(os.environ.get("PROBLEM3_WRENCH_ROOT", str(ROOT))).expanduser()
ZIP_PATH = ROOT / "4x4_All_graph_data.zip"
OUT_DIR = PROJECT / "public" / "problem3-core"
CHUNK_SIZE = 3_500_000

sys.path.insert(0, str(WRENCH_ROOT))
import Wrench_or_Skein as wrench  # noqa: E402


def graph_word_from_name(name: str) -> str:
    return Path(name).stem.split("_", 1)[1]


def graph_index_from_name(name: str) -> int:
    return int(Path(name).stem.split("_", 1)[0])


def graph_members_from_zip(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        names = [
            info.filename
            for info in archive.infolist()
            if info.filename.startswith("4x4_All_graph_data/")
            and info.filename.endswith(".json")
            and "/._" not in info.filename
            and not info.filename.startswith("__MACOSX/")
        ]
    return sorted(names, key=graph_index_from_name)


def parse_web_data(data: dict[str, Any]) -> tuple[wrench.Adjacency, wrench.BoundaryLabels, list[wrench.Hourglass]]:
    nodes = wrench._as_int_key_map(data["nodes"])
    rot_sys = data.get("effective_rotation_system", {})
    boundary_labels = {int(b["node"]): int(b["label"]) for b in data["boundary"]}
    adj: wrench.Adjacency = {int(n["id"]): [] for n in data["nodes"]}

    hourglasses: list[wrench.Hourglass] = []
    for h in data.get("hourglasses", []):
        white = int(h["white"])
        black = int(h["black"])
        local_case = str(nodes[white].get("local_case") or nodes[black].get("local_case") or "")
        hg = wrench.orient_hourglass_ports(white, black, nodes, rot_sys, "black", local_case)
        hourglasses.append(hg)
        adj[white] = {"top": None, "bot": None}
        adj[black] = {"top": None, "bot": None}

    for edge in data["edges"]:
        if edge.get("double", False):
            continue
        u, v = int(edge["src"]), int(edge["dst"])
        if isinstance(adj[u], list):
            adj[u].append(v)
        if isinstance(adj[v], list):
            adj[v].append(u)

    for hg in hourglasses:
        left = int(hg["left"])
        right = int(hg["right"])
        adj[left]["top"] = int(hg["left_top"])
        adj[left]["bot"] = int(hg["left_bot"])
        adj[right]["top"] = int(hg["right_top"])
        adj[right]["bot"] = int(hg["right_bot"])

    wrench.validate_adjacency(adj)
    return adj, boundary_labels, hourglasses


def compact_graph(name: str, data: dict[str, Any]):
    adj, boundary, hgs = parse_web_data(data)
    hgs = wrench.sort_hourglasses_by_boundary_distance(adj, boundary, hgs)
    nodes = []
    for node in data["nodes"]:
      node_id = int(node["id"])
      nodes.append(
          [
              node_id,
              round(float(node["x"]), 6),
              round(float(node["y"]), 6),
              1 if node.get("color") == "black" else 0,
          ]
      )
    adj_rows = []
    for node_id in sorted(adj):
        neighbors = adj[node_id]
        if isinstance(neighbors, dict):
            adj_rows.append([node_id, "h", int(neighbors["top"]), int(neighbors["bot"])])
        else:
            adj_rows.append([node_id, *[int(n) for n in neighbors]])
    return [
        graph_index_from_name(name),
        graph_word_from_name(name),
        nodes,
        [[int(node), int(label)] for node, label in sorted(boundary.items())],
        adj_rows,
        [
            [
                int(hg["white"]),
                int(hg["black"]),
                int(hg["left"]),
                int(hg["right"]),
                int(hg["left_top"]),
                int(hg["left_bot"]),
                int(hg["right_top"]),
                int(hg["right_bot"]),
                str(hg.get("left_endpoint", "black")),
                str(hg.get("local_case", "")),
            ]
            for hg in hgs
        ],
    ]


def load_graphs_from_zip(zip_path: Path):
    names = graph_members_from_zip(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        return [compact_graph(name, json.loads(archive.read(name))) for name in names]


def load_survivors():
    out = []
    with (ROOT / "lemma46_survivors.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            words = ast.literal_eval(row["survivor_words"]) if row.get("survivor_words") else []
            forks = ast.literal_eval(row["forks_W"]) if row.get("forks_W") else []
            out.append(
                [
                    int(row["w_idx"]),
                    row["w_word"],
                    int(row["n_survivor_pairs"]),
                    int(row["n_survivor_orbits"]),
                    forks,
                    words,
                ]
            )
    return out


def load_orbits():
    path = ROOT / "hourglass_disk_4x4_promotion_reps" / "promotion_orbits_4x4.tsv"
    out = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            idx = int(row.get("orbit_index") or row.get("index"))
            words = [word.strip() for word in row["orbit_words"].split(",") if word.strip()]
            out.append([idx, words])
    return out


def transpose_words():
    result = {}
    for path in (ROOT / "hourglass_disk_4x4_transpose_words_graph_data").glob("*.json"):
        result[str(graph_index_from_name(path.name))] = graph_word_from_name(path.name)
    return result


def write_chunked_bundle(bundle: dict[str, Any]) -> None:
    text = json.dumps(bundle, separators=(",", ":"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.json"):
        old.unlink()
    parts = []
    for idx in range(0, len(text), CHUNK_SIZE):
        part_name = f"part-{len(parts):03d}.json"
        (OUT_DIR / part_name).write_text(text[idx : idx + CHUNK_SIZE], encoding="utf-8")
        parts.append(part_name)
    (OUT_DIR / "manifest.json").write_text(
        json.dumps({"parts": parts, "bytes": len(text)}, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> int:
    if not ZIP_PATH.exists():
        raise FileNotFoundError(f"Missing graph data archive: {ZIP_PATH}")
    graphs = load_graphs_from_zip(ZIP_PATH)
    bundle = {
        "meta": {
            "graphCount": len(graphs),
            "survivorRows": 1522,
            "source": "Problem 3 compact bundle",
            "graphArchive": str(ZIP_PATH),
            "wrenchSource": str(WRENCH_ROOT / "Wrench_or_Skein.py"),
        },
        "graphs": graphs,
        "survivors": load_survivors(),
        "orbits": load_orbits(),
        "transposeByRep": transpose_words(),
    }
    write_chunked_bundle(bundle)
    print(f"Wrote {OUT_DIR} from {ZIP_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
