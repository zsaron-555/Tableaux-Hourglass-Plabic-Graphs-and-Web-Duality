#!/usr/bin/env python3
"""Build surgery results for every exact selectable benzene presentation.

The manifest is keyed by source JSON, not only by Yamanouchi word.  This keeps
benzene surgery consistent with the presentation selected in web_explorer_v4.
Both catalogue JSONs and generated benzene-move JSONs are used when certifying
the surgery output.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Tuple

from audit_benzene_conjecture_20260803 import graph_model, induced_internal_six_cycles
from check_benzene_surgery_pairing import (
    RibbonWeb,
    enumerate_benzene_surgery_channels,
    identify_after_square_normalization,
    load_ribbon_web,
    refined_fingerprint,
    transpose_word,
)


ROOT = Path(__file__).resolve().parent
GRAPH_DIR = ROOT / "4x4_All_graph_data"
PRESENTATION_MANIFEST = GRAPH_DIR / "benzene_move_presentations" / "manifest.json"
OUTPUT_DIR = GRAPH_DIR / "benzene_surgery_presentations"


def graph_word(path: Path) -> str:
    if path.parent.name == "benzene_move_presentations":
        with path.open(encoding="utf-8") as handle:
            return str(json.load(handle).get("word", ""))
    return path.stem.split("_", 1)[-1]


def relative_json(path: Path, graph_dir: Path) -> str:
    return path.resolve().relative_to(graph_dir.resolve()).as_posix()


def expanded_index(
    graph_dir: Path,
) -> Mapping[Tuple[object, ...], List[Tuple[str, Path, RibbonWeb]]]:
    result: Dict[Tuple[object, ...], List[Tuple[str, Path, RibbonWeb]]] = defaultdict(list)
    paths = sorted(graph_dir.glob("*.json"))
    paths.extend(sorted((graph_dir / "benzene_move_presentations").glob("*.json")))
    for number, path in enumerate(paths, start=1):
        if path.name == "manifest.json":
            continue
        word = graph_word(path)
        if len(word) != 16 or set(word) - set("1234"):
            continue
        web = load_ribbon_web(path)
        result[refined_fingerprint(web)].append((word, path, web))
        if number % 2000 == 0:
            print(f"indexed {number:,}/{len(paths):,} graph presentations", flush=True)
    return result


def source_paths(graph_dir: Path, presentation_manifest: Mapping[str, object]) -> List[Path]:
    paths = {
        graph_dir / f"{int(item['global_index']):05d}_{item['word']}.json"
        for item in presentation_manifest.get("files", [])
    }
    paths.update(
        graph_dir / str(item["json"])
        for item in presentation_manifest.get("files", [])
    )
    missing = sorted(path for path in paths if not path.is_file())
    if missing:
        raise FileNotFoundError(f"Missing {len(missing)} source JSONs; first: {missing[0]}")
    return sorted(paths)


def certified_match(identification, graph_dir: Path) -> Dict[str, object]:
    by_word: Dict[str, List[Path]] = defaultdict(list)
    for word, path in identification.matches:
        by_word[word].append(path)
    if len(by_word) != 1:
        return {
            "certified": False,
            "note": (
                "No unique expanded-catalogue word was certified."
                if not by_word
                else "The surgery graph matched more than one Yamanouchi word."
            ),
            "candidate_words": sorted(by_word),
        }
    word = next(iter(by_word))
    preferred = sorted(
        by_word[word],
        key=lambda path: (path.parent.name != "benzene_move_presentations", path.name),
    )[0]
    return {
        "certified": True,
        "word": word,
        "transpose": transpose_word(word),
        "json": relative_json(preferred, graph_dir),
        "identification_mode": identification.mode,
        "square_normalization_path": [list(cycle) for cycle in identification.square_path],
        "equivalent_json_matches": [
            relative_json(path, graph_dir) for path in sorted(by_word[word])
        ],
    }


def build(graph_dir: Path, presentation_manifest_path: Path, output_dir: Path) -> Dict[str, object]:
    presentation_manifest = json.loads(presentation_manifest_path.read_text(encoding="utf-8"))
    index = expanded_index(graph_dir)
    sources = source_paths(graph_dir, presentation_manifest)
    entries: List[Dict[str, object]] = []
    for number, source in enumerate(sources, start=1):
        model = graph_model(source)
        cycles = induced_internal_six_cycles(model)
        web = load_ribbon_web(source)
        channels = enumerate_benzene_surgery_channels(web, cycles, include_chain_reactions=True)
        channel_rows: List[Dict[str, object]] = []
        for channel_number, channel in enumerate(channels, start=1):
            identification = identify_after_square_normalization(channel.surgery.web, index)
            row: Dict[str, object] = {
                "channel": channel_number,
                "channel_type": channel.channel_type,
                "benzene_cycle": list(channel.cycle),
                "benzene_move_path": [list(cycle) for cycle in channel.benzene_move_path],
            }
            row.update(certified_match(identification, graph_dir))
            channel_rows.append(row)
        entries.append({
            "source_json": relative_json(source, graph_dir),
            "word": web.word,
            "channels": channel_rows,
        })
        if number % 50 == 0 or number == len(sources):
            print(f"processed {number:,}/{len(sources):,} exact source presentations", flush=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, object] = {
        "schema": "sl4-benzene-surgery-by-presentation-v1",
        "source_count": len(entries),
        "channel_count": sum(len(entry["channels"]) for entry in entries),
        "certified_channel_count": sum(
            bool(channel.get("certified"))
            for entry in entries for channel in entry["channels"]
        ),
        "entries": entries,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-dir", type=Path, default=GRAPH_DIR)
    parser.add_argument("--presentation-manifest", type=Path, default=PRESENTATION_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    payload = build(
        args.graph_dir.expanduser().resolve(),
        args.presentation_manifest.expanduser().resolve(),
        args.output_dir.expanduser().resolve(),
    )
    print(json.dumps({key: payload[key] for key in (
        "source_count", "channel_count", "certified_channel_count"
    )}, indent=2))


if __name__ == "__main__":
    main()
