#!/usr/bin/env python3
"""Name SL4 benzene presentations as top, middle, or bottom.

The convention is the one recorded in the revised double-benzene notes:

* top: clockwise around the active benzene face, every hourglass goes black
  to white;
* bottom: the clockwise hourglasses go white to black;
* middle: the chain-reaction state has the adjacent top and bottom faces.

The graph JSON remains the source of topology.  Benzene faces are detected
combinatorially, their incidence is checked against the stored ribbon system,
and coordinates are used only to choose which of the two boundary directions
is clockwise.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from audit_benzene_conjecture_20260803 import (
    Cycle,
    cycle_edges,
    induced_internal_six_cycles,
    is_benzene,
)


REPRESENTATION_ORDER = {"top": 0, "middle": 1, "bottom": 2, "none": 3}


@dataclass(frozen=True)
class BenzeneFaceOrientation:
    cycle: tuple[int, ...]
    orientation: str
    clockwise_cycle: tuple[int, ...]
    clockwise_hourglass_directions: tuple[str, ...]


@dataclass(frozen=True)
class BenzeneRepresentation:
    name: str
    faces: tuple[BenzeneFaceOrientation, ...]

    @property
    def benzene_count(self) -> int:
        return len(self.faces)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "benzene_count": self.benzene_count,
            "faces": [asdict(face) for face in self.faces],
        }


def _load_data(source: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def _model_from_data(data: Mapping[str, Any]):
    """Build the existing graph model without making a temporary file."""
    from collections import defaultdict
    from audit_benzene_conjecture_20260803 import GraphModel, component_count

    boundary_nodes = frozenset(int(item["node"]) for item in data.get("boundary", []))
    adjacency_sets: dict[int, set[int]] = defaultdict(set)
    edge_kind: dict[frozenset[int], str] = {}
    for edge in data.get("edges", []):
        source, target = int(edge["src"]), int(edge["dst"])
        adjacency_sets[source].add(target)
        adjacency_sets[target].add(source)
        edge_kind[frozenset((source, target))] = (
            "hourglass"
            if edge.get("kind") == "hourglass" or bool(edge.get("double"))
            else "ordinary"
        )
    all_nodes = {int(node["id"]) for node in data.get("nodes", [])}
    all_nodes.update(adjacency_sets)
    adjacency = {
        node: frozenset(adjacency_sets.get(node, set())) for node in sorted(all_nodes)
    }
    colors = {
        int(node["id"]): str(node.get("color", "")).lower()
        for node in data.get("nodes", [])
    }
    return GraphModel(
        word=str(data.get("word", "")),
        boundary_nodes=boundary_nodes,
        adjacency=adjacency,
        edge_kind=edge_kind,
        node_color=colors,
        hourglass_count=sum(kind == "hourglass" for kind in edge_kind.values()),
        internal_vertex_count=len(all_nodes - set(boundary_nodes)),
        cycle_rank=len(edge_kind) - len(all_nodes) + component_count(adjacency),
    )


def _signed_area(cycle: Sequence[int], xy: Mapping[int, tuple[float, float]]) -> float:
    return 0.5 * sum(
        xy[cycle[index]][0] * xy[cycle[(index + 1) % len(cycle)]][1]
        - xy[cycle[(index + 1) % len(cycle)]][0] * xy[cycle[index]][1]
        for index in range(len(cycle))
    )


def _distinct_neighbor_order(entries: Sequence[Mapping[str, Any]]) -> tuple[int, ...]:
    ordered = sorted(entries, key=lambda item: int(item["ccw_slot"]))
    result: list[int] = []
    for entry in ordered:
        neighbor = int(entry["neighbor"])
        if not result or result[-1] != neighbor:
            result.append(neighbor)
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    if len(result) != len(set(result)):
        raise ValueError(f"A neighbor occupies multiple ribbon blocks: {entries!r}")
    return tuple(result)


def _validate_cycle_against_ribbon(data: Mapping[str, Any], cycle: Cycle) -> None:
    rotations = data.get("tagged_rotation_system") or data.get("effective_rotation_system")
    if not rotations:
        raise ValueError("Graph JSON has no ribbon rotation system.")
    for index, vertex in enumerate(cycle):
        before = int(cycle[index - 1])
        after = int(cycle[(index + 1) % len(cycle)])
        order = _distinct_neighbor_order(rotations[str(vertex)])
        if before not in order or after not in order:
            raise ValueError(
                f"Benzene cycle is absent from the ribbon order at vertex {vertex}."
            )


def classify_benzene_representation(
    source: Mapping[str, Any] | str | Path,
) -> BenzeneRepresentation:
    """Classify one exact graph presentation by the revised naming convention."""
    data = _load_data(source)
    model = _model_from_data(data)
    xy = {
        int(node["id"]): (float(node["x"]), float(node["y"]))
        for node in data.get("nodes", [])
        if "x" in node and "y" in node
    }
    faces: list[BenzeneFaceOrientation] = []
    for cycle in induced_internal_six_cycles(model):
        if not is_benzene(cycle, model.edge_kind):
            continue
        _validate_cycle_against_ribbon(data, cycle)
        if any(vertex not in xy for vertex in cycle):
            raise ValueError("Clockwise benzene naming requires node coordinates.")
        area = _signed_area(cycle, xy)
        if abs(area) < 1e-12:
            raise ValueError(f"Benzene face {cycle} has degenerate displayed geometry.")
        clockwise = tuple(cycle if area < 0 else reversed(cycle))
        directions: list[str] = []
        for index, edge in enumerate(cycle_edges(clockwise)):
            if model.edge_kind[edge] != "hourglass":
                continue
            source_color = model.node_color[clockwise[index]]
            target_color = model.node_color[clockwise[(index + 1) % len(clockwise)]]
            directions.append(f"{source_color}->{target_color}")
        if directions and set(directions) == {"black->white"}:
            orientation = "top"
        elif directions and set(directions) == {"white->black"}:
            orientation = "bottom"
        else:
            raise ValueError(
                f"Benzene face {cycle} has inconsistent hourglass orientations: {directions}."
            )
        faces.append(
            BenzeneFaceOrientation(
                cycle=tuple(int(vertex) for vertex in cycle),
                orientation=orientation,
                clockwise_cycle=tuple(int(vertex) for vertex in clockwise),
                clockwise_hourglass_directions=tuple(directions),
            )
        )

    orientations = {face.orientation for face in faces}
    if not faces:
        name = "none"
    elif orientations == {"top"} and len(faces) == 1:
        name = "top"
    elif orientations == {"bottom"} and len(faces) == 1:
        name = "bottom"
    elif orientations == {"top", "bottom"} and len(faces) == 2:
        name = "middle"
    else:
        raise ValueError(
            "Presentation does not match a supported G(4,16) benzene state: "
            f"{[(face.cycle, face.orientation) for face in faces]}."
        )
    return BenzeneRepresentation(name=name, faces=tuple(faces))


def presentation_paths_for_word(
    graph_dir: str | Path,
    word: str,
) -> list[dict[str, Any]]:
    """Return every exact selectable presentation with a structural name."""
    graph_dir = Path(graph_dir)
    catalogue = sorted(graph_dir.glob(f"*_{word}.json"))
    if len(catalogue) != 1:
        raise FileNotFoundError(
            f"Expected one catalogue graph for {word}, found {len(catalogue)}."
        )
    records: list[dict[str, Any]] = []

    def add(path: Path, *, presentation: int, move_count: int, origin: str) -> None:
        representation = classify_benzene_representation(path)
        records.append(
            {
                "path": path,
                "value": word if origin == "catalogue" else path.relative_to(graph_dir).as_posix(),
                "word": word,
                "representation": representation.name,
                "benzene_count": representation.benzene_count,
                "presentation": int(presentation),
                "move_count": int(move_count),
                "origin": origin,
            }
        )

    add(catalogue[0], presentation=0, move_count=0, origin="catalogue")
    manifest_path = graph_dir / "benzene_move_presentations" / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest.get("files", []):
            if entry.get("word") != word:
                continue
            path = graph_dir / str(entry["json"])
            add(
                path,
                presentation=int(entry.get("presentation", 0)),
                move_count=int(entry.get("move_count", 0)),
                origin="generated",
            )
    # The promoted catalogue web can be a square-move variant of one generated
    # state.  Keep one selectable exact JSON per structural name, preferring
    # the catalogue file when it already realizes that state.
    records.sort(
        key=lambda item: (
            REPRESENTATION_ORDER[item["representation"]],
            item["origin"] != "catalogue",
            item["presentation"],
        )
    )
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        unique.setdefault(str(record["representation"]), record)
    return sorted(
        unique.values(),
        key=lambda item: REPRESENTATION_ORDER[str(item["representation"])],
    )
