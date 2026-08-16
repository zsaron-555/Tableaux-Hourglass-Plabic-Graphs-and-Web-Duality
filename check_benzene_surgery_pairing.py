#!/usr/bin/env python3
"""Check the benzene-surgery transpose pairing conjecture for one SL4 web.

For every benzene face in the supplied web W, this script:

1. removes the six vertices of the alternating ordinary/hourglass hexagon;
2. joins the two external half-edges across each hourglass side of the hexagon;
3. identifies the resulting boundary-labelled ribbon graph W' in the catalogue;
4. computes the Yamanouchi word of (W')^T; and
5. checks whether <W, (W')^T> is recorded as +1 or -1.

By default, the final check uses the consolidated pairing table.  With
``--compute-missing``, a pair not covered by that table is evaluated with the
current 0714 pairing engine.

The graph identification preserves boundary labels, vertex colors, edge kinds,
and the cyclic half-edge order.  It ignores only temporary internal vertex IDs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from audit_benzene_conjecture_20260803 import (
    Cycle,
    cycle_edges,
    graph_model,
    induced_internal_six_cycles,
    is_benzene,
)


EdgeKey = frozenset[int]
Port = Tuple[int, str]


@dataclass(frozen=True)
class RibbonWeb:
    word: str
    colors: Mapping[int, str]
    boundary_labels: Mapping[int, int]
    edges: Mapping[EdgeKey, str]
    rotations: Mapping[int, Tuple[Port, ...]]


@dataclass(frozen=True)
class SurgeryResult:
    cycle: Cycle
    external_by_cycle_vertex: Mapping[int, int]
    added_edges: Tuple[Tuple[int, int], ...]
    web: RibbonWeb


@dataclass(frozen=True)
class BenzeneSurgeryChannel:
    """One surgery face together with the presentation in which it is active."""

    channel_type: str
    cycle: Cycle
    benzene_move_path: Tuple[Cycle, ...]
    presentation: RibbonWeb
    surgery: SurgeryResult


@dataclass(frozen=True)
class SquareReductionResult:
    """A monotone reduction of an alternating square with two hourglasses."""

    cycle: Tuple[int, int, int, int]
    external_by_cycle_vertex: Mapping[int, int]
    added_edges: Tuple[Tuple[int, int], ...]
    web: RibbonWeb


@dataclass(frozen=True)
class CatalogueIdentification:
    """A catalogue match, possibly after monotone two-hourglass reductions."""

    matches: Tuple[Tuple[str, Path], ...]
    mode: str
    square_path: Tuple[Tuple[int, int, int, int], ...]
    normalized_web: RibbonWeb


def transpose_word(word: str) -> str:
    """Convert a rectangular Yamanouchi word to the transpose-tableau word."""
    counts: Counter[str] = Counter()
    result: List[str] = []
    for letter in word:
        counts[letter] += 1
        result.append(str(counts[letter]))
    return "".join(result)


def _edge_kind(edge: Mapping[str, object]) -> str:
    return "H" if edge.get("kind") == "hourglass" or edge.get("double") else "O"


def load_ribbon_web(path: Path) -> RibbonWeb:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    colors = {
        int(node["id"]): str(node.get("color", ""))
        for node in data.get("nodes", [])
    }
    boundary_labels = {
        int(item["node"]): int(item["label"])
        for item in data.get("boundary", [])
    }
    edges: Dict[EdgeKey, str] = {}
    for edge in data.get("edges", []):
        source, target = int(edge["src"]), int(edge["dst"])
        key = frozenset((source, target))
        kind = _edge_kind(edge)
        previous = edges.get(key)
        if previous is not None and previous != kind:
            raise ValueError(f"Conflicting edge kinds at {sorted(key)} in {path}.")
        edges[key] = kind

    rotations: Dict[int, Tuple[Port, ...]] = {}
    raw_rotation = data.get("effective_rotation_system", {})
    if not raw_rotation:
        raise ValueError(f"{path} has no effective_rotation_system.")
    for node_text, entries in raw_rotation.items():
        node = int(node_text)
        ordered = sorted(entries, key=lambda item: int(item["ccw_slot"]))
        rotations[node] = tuple(
            (
                int(item["neighbor"]),
                "H" if str(item.get("kind", "")).startswith("hourglass") else "O",
            )
            for item in ordered
        )

    return RibbonWeb(
        word=str(data.get("word") or path.stem.split("_", 1)[-1]),
        colors=colors,
        boundary_labels=boundary_labels,
        edges=edges,
        rotations=rotations,
    )


def _neighbors(web: RibbonWeb) -> Mapping[int, frozenset[int]]:
    result: Dict[int, set[int]] = {node: set() for node in web.colors}
    for key in web.edges:
        source, target = tuple(key)
        result[source].add(target)
        result[target].add(source)
    return {node: frozenset(values) for node, values in result.items()}


def perform_benzene_surgery(
    web: RibbonWeb,
    cycle: Cycle,
    *,
    splice_side_kind: str = "H",
) -> SurgeryResult:
    """Remove one benzene and splice stubs across one alternating side class.

    The surgery convention in the project slides pairs the external stubs at
    the endpoints of each hourglass side.  ``splice_side_kind="O"`` is kept as
    an explicit diagnostic mode for comparing the other possible pairing.
    """
    if splice_side_kind not in {"H", "O"}:
        raise ValueError("splice_side_kind must be 'H' or 'O'.")
    cycle_set = set(cycle)
    neighbors = _neighbors(web)
    external_by_vertex: Dict[int, int] = {}
    for vertex in cycle:
        external = sorted(neighbors[vertex] - cycle_set)
        if len(external) != 1:
            raise ValueError(
                f"Benzene vertex {vertex} has {len(external)} external neighbors: {external}."
            )
        external_by_vertex[vertex] = external[0]

    splice_sides: List[Tuple[int, int]] = []
    for key in cycle_edges(cycle):
        if web.edges.get(key) == splice_side_kind:
            splice_sides.append(tuple(sorted(key)))
    if len(splice_sides) != 3:
        raise ValueError(
            f"Expected three {splice_side_kind} benzene sides, found {splice_sides}."
        )

    added_edges = tuple(
        sorted(
            tuple(sorted((external_by_vertex[left], external_by_vertex[right])))
            for left, right in splice_sides
        )
    )
    if len({frozenset(edge) for edge in added_edges}) != 3:
        raise ValueError(f"Surgery produced repeated splice edges: {added_edges}.")

    colors = {node: color for node, color in web.colors.items() if node not in cycle_set}
    boundary_labels = {
        node: label for node, label in web.boundary_labels.items() if node not in cycle_set
    }
    edges = {
        key: kind
        for key, kind in web.edges.items()
        if key.isdisjoint(cycle_set)
    }
    for source, target in added_edges:
        key = frozenset((source, target))
        if key in edges:
            raise ValueError(
                f"Surgery would create a second abstract edge between {source} and {target}."
            )
        if web.colors[source] == web.colors[target]:
            raise ValueError(
                f"Surgery splice {source}-{target} violates bipartiteness "
                f"({web.colors[source]}-{web.colors[target]})."
            )
        edges[key] = "O"

    replacement: Dict[Tuple[int, int], int] = {}
    for left, right in splice_sides:
        left_external = external_by_vertex[left]
        right_external = external_by_vertex[right]
        replacement[(left_external, left)] = right_external
        replacement[(right_external, right)] = left_external

    rotations: Dict[int, Tuple[Port, ...]] = {}
    for node, ports in web.rotations.items():
        if node in cycle_set:
            continue
        changed: List[Port] = []
        for neighbor, kind in ports:
            if neighbor not in cycle_set:
                changed.append((neighbor, kind))
                continue
            key = (node, neighbor)
            if key not in replacement:
                raise ValueError(
                    f"Removed half-edge {node}-{neighbor} is not part of a surgery splice."
                )
            changed.append((replacement[key], "O"))
        rotations[node] = tuple(changed)

    result = RibbonWeb(
        word="",
        colors=colors,
        boundary_labels=boundary_labels,
        edges=edges,
        rotations=rotations,
    )
    validate_ribbon_web(result)
    return SurgeryResult(
        cycle=cycle,
        external_by_cycle_vertex=external_by_vertex,
        added_edges=added_edges,
        web=result,
    )


def validate_ribbon_web(web: RibbonWeb) -> None:
    neighbors = _neighbors(web)
    if set(web.rotations) != set(web.colors):
        raise ValueError("Rotation-system vertices and graph vertices disagree.")
    for node, ports in web.rotations.items():
        port_neighbors = {neighbor for neighbor, _kind in ports}
        if port_neighbors != set(neighbors[node]):
            raise ValueError(
                f"Rotation and adjacency disagree at {node}: "
                f"rotation={sorted(port_neighbors)}, graph={sorted(neighbors[node])}."
            )
        for neighbor, kind in ports:
            expected = web.edges[frozenset((node, neighbor))]
            if kind != expected:
                raise ValueError(f"Rotation edge kind mismatch at {node}-{neighbor}.")
        expected_slots = sum(2 if kind == "H" else 1 for kind in (
            web.edges[frozenset((node, neighbor))] for neighbor in neighbors[node]
        ))
        if len(ports) != expected_slots:
            raise ValueError(
                f"Rotation at {node} has {len(ports)} slots; expected {expected_slots}."
            )


def _canonical_cycle(nodes: Sequence[int]) -> Tuple[int, ...]:
    """Choose a deterministic orientation and starting point for a short cycle."""
    values = tuple(nodes)
    candidates = []
    for oriented in (values, tuple(reversed(values))):
        for offset in range(len(oriented)):
            candidates.append(oriented[offset:] + oriented[:offset])
    return min(candidates)


def alternating_two_hourglass_squares(
    web: RibbonWeb,
) -> List[Tuple[int, int, int, int]]:
    """Find induced internal 4-cycles with opposite H and opposite O sides.

    Every square vertex must have exactly one neighbor outside the square.  This
    is the local configuration produced by the chain-reaction surgery before it
    is returned to the 24,024-web catalogue.
    """
    neighbors = _neighbors(web)
    internal = sorted(set(web.colors) - set(web.boundary_labels))
    found: set[Tuple[int, int, int, int]] = set()
    for chosen in combinations(internal, 4):
        chosen_set = set(chosen)
        internal_degrees = {
            node: len(neighbors[node] & chosen_set) for node in chosen
        }
        if any(degree != 2 for degree in internal_degrees.values()):
            continue
        if any(len(neighbors[node] - chosen_set) != 1 for node in chosen):
            continue

        start = min(chosen)
        first_options = sorted(neighbors[start] & chosen_set)
        if len(first_options) != 2:
            continue
        ordered = [start, first_options[0]]
        while len(ordered) < 4:
            previous, current = ordered[-2], ordered[-1]
            next_options = sorted((neighbors[current] & chosen_set) - {previous})
            next_options = [node for node in next_options if node not in ordered]
            if len(next_options) != 1:
                break
            ordered.append(next_options[0])
        if len(ordered) != 4 or start not in neighbors[ordered[-1]]:
            continue

        cycle = _canonical_cycle(ordered)
        kinds = [
            web.edges[frozenset((cycle[index], cycle[(index + 1) % 4]))]
            for index in range(4)
        ]
        if kinds not in (["H", "O", "H", "O"], ["O", "H", "O", "H"]):
            continue
        if any(web.colors[cycle[index]] == web.colors[cycle[(index + 1) % 4]]
               for index in range(4)):
            continue
        found.add(cycle)
    return sorted(found)


def reduce_alternating_two_hourglass_square(
    web: RibbonWeb,
    cycle: Sequence[int],
) -> SquareReductionResult:
    """Remove a two-hourglass square and join stubs across ordinary sides.

    The operation strictly decreases both the internal-vertex count and the
    hourglass count, so using it for catalogue normalization cannot cycle.
    """
    canonical = _canonical_cycle(cycle)
    if canonical not in alternating_two_hourglass_squares(web):
        raise ValueError(f"Not a reducible two-hourglass square: {canonical}.")

    cycle_set = set(canonical)
    neighbors = _neighbors(web)
    external_by_vertex = {
        vertex: next(iter(neighbors[vertex] - cycle_set)) for vertex in canonical
    }
    ordinary_sides = [
        (canonical[index], canonical[(index + 1) % 4])
        for index in range(4)
        if web.edges[frozenset((canonical[index], canonical[(index + 1) % 4]))] == "O"
    ]
    if len(ordinary_sides) != 2:
        raise ValueError(f"Expected two ordinary square sides, found {ordinary_sides}.")

    added_edges = tuple(
        sorted(
            tuple(sorted((external_by_vertex[left], external_by_vertex[right])))
            for left, right in ordinary_sides
        )
    )
    if len({frozenset(edge) for edge in added_edges}) != 2:
        raise ValueError(f"Square reduction produced repeated edges: {added_edges}.")

    colors = {node: color for node, color in web.colors.items() if node not in cycle_set}
    boundary_labels = dict(web.boundary_labels)
    edges = {
        key: kind for key, kind in web.edges.items() if key.isdisjoint(cycle_set)
    }
    replacement: Dict[Tuple[int, int], int] = {}
    for left, right in ordinary_sides:
        left_external = external_by_vertex[left]
        right_external = external_by_vertex[right]
        key = frozenset((left_external, right_external))
        if key in edges:
            raise ValueError(
                f"Square reduction would duplicate edge {left_external}-{right_external}."
            )
        if colors[left_external] == colors[right_external]:
            raise ValueError(
                f"Square splice {left_external}-{right_external} violates bipartiteness."
            )
        edges[key] = "O"
        replacement[(left_external, left)] = right_external
        replacement[(right_external, right)] = left_external

    rotations: Dict[int, Tuple[Port, ...]] = {}
    for node, ports in web.rotations.items():
        if node in cycle_set:
            continue
        changed: List[Port] = []
        for neighbor, kind in ports:
            if neighbor not in cycle_set:
                changed.append((neighbor, kind))
                continue
            replacement_key = (node, neighbor)
            if replacement_key not in replacement:
                raise ValueError(
                    f"Removed square half-edge {node}-{neighbor} has no ordinary-side splice."
                )
            changed.append((replacement[replacement_key], "O"))
        rotations[node] = tuple(changed)

    result = RibbonWeb(
        word="",
        colors=colors,
        boundary_labels=boundary_labels,
        edges=edges,
        rotations=rotations,
    )
    validate_ribbon_web(result)
    return SquareReductionResult(
        cycle=canonical,
        external_by_cycle_vertex=external_by_vertex,
        added_edges=added_edges,
        web=result,
    )


def _distinct_neighbor_order(ports: Sequence[Port]) -> Tuple[int, ...]:
    """Collapse the two adjacent slots of each hourglass half-edge."""
    neighbors: List[int] = []
    for neighbor, _kind in ports:
        if not neighbors or neighbor != neighbors[-1]:
            neighbors.append(neighbor)
    if len(neighbors) > 1 and neighbors[0] == neighbors[-1]:
        neighbors.pop()
    if len(neighbors) != len(set(neighbors)):
        raise ValueError(f"A neighbor occurs in multiple cyclic blocks: {ports}.")
    return tuple(neighbors)


def web_with_edge_kinds(
    web: RibbonWeb,
    edge_kinds: Mapping[EdgeKey, str],
) -> RibbonWeb:
    """Change ordinary/hourglass kinds while preserving the ribbon embedding."""
    if set(edge_kinds) != set(web.edges):
        raise ValueError("Replacement edge-kind map does not match the web edges.")
    if set(edge_kinds.values()) - {"H", "O"}:
        raise ValueError("Replacement edge kinds must be H or O.")

    rotations: Dict[int, Tuple[Port, ...]] = {}
    for node, ports in web.rotations.items():
        rebuilt: List[Port] = []
        for neighbor in _distinct_neighbor_order(ports):
            kind = edge_kinds[frozenset((node, neighbor))]
            rebuilt.extend([(neighbor, kind)] * (2 if kind == "H" else 1))
        rotations[node] = tuple(rebuilt)

    result = RibbonWeb(
        word=web.word,
        colors=dict(web.colors),
        boundary_labels=dict(web.boundary_labels),
        edges=dict(edge_kinds),
        rotations=rotations,
    )
    validate_ribbon_web(result)
    return result


def benzene_move_presentations(
    web: RibbonWeb,
    all_cycles: Sequence[Cycle],
) -> List[Tuple[RibbonWeb, Tuple[Cycle, ...]]]:
    """Enumerate the benzene-move orbit with a shortest path to each state."""
    ordered_edges = tuple(sorted(web.edges, key=lambda edge: tuple(sorted(edge))))
    initial = tuple(web.edges[edge] for edge in ordered_edges)
    queue = deque([(initial, tuple())])
    seen = {initial}
    presentations: List[Tuple[RibbonWeb, Tuple[Cycle, ...]]] = []

    while queue:
        state, path = queue.popleft()
        kinds = dict(zip(ordered_edges, state))
        presentation = web_with_edge_kinds(web, kinds)
        presentations.append((presentation, path))
        active = [cycle for cycle in all_cycles if is_benzene(cycle, kinds)]
        for cycle in active:
            toggled = dict(kinds)
            for edge in cycle_edges(cycle):
                toggled[edge] = "O" if toggled[edge] == "H" else "H"
            child = tuple(toggled[edge] for edge in ordered_edges)
            if child in seen:
                continue
            seen.add(child)
            queue.append((child, path + (cycle,)))
    return presentations


def enumerate_benzene_surgery_channels(
    web: RibbonWeb,
    all_cycles: Sequence[Cycle],
    *,
    include_chain_reactions: bool = True,
    splice_side_kind: str = "H",
) -> List[BenzeneSurgeryChannel]:
    """Return direct surgeries and surgeries activated by a benzene chain reaction.

    A face contributes once, using the shortest benzene-move path that makes it
    active.  Faces already active in the stored presentation are direct
    channels; a newly active face is a chain-reaction channel.
    """
    initial_faces = {
        cycle for cycle in all_cycles if is_benzene(cycle, web.edges)
    }
    presentations = (
        benzene_move_presentations(web, all_cycles)
        if include_chain_reactions
        else [(web, tuple())]
    )
    selected_faces: set[Cycle] = set()
    channels: List[BenzeneSurgeryChannel] = []
    for presentation, path in presentations:
        active = [
            cycle for cycle in all_cycles if is_benzene(cycle, presentation.edges)
        ]
        for cycle in active:
            if cycle in selected_faces:
                continue
            if path and cycle in initial_faces:
                continue
            selected_faces.add(cycle)
            surgery = perform_benzene_surgery(
                presentation,
                cycle,
                splice_side_kind=splice_side_kind,
            )
            channels.append(
                BenzeneSurgeryChannel(
                    channel_type=(
                        "direct" if cycle in initial_faces else "chain_reaction"
                    ),
                    cycle=cycle,
                    benzene_move_path=path,
                    presentation=presentation,
                    surgery=surgery,
                )
            )
    return channels


def _cyclic_minimum(values: Sequence[Tuple[str, str]]) -> Tuple[Tuple[str, str], ...]:
    if not values:
        return tuple()
    tuples = tuple(values)
    return min(tuples[offset:] + tuples[:offset] for offset in range(len(tuples)))


def _node_base(web: RibbonWeb, node: int) -> str:
    boundary = web.boundary_labels.get(node)
    kinds = Counter(kind for _neighbor, kind in web.rotations[node])
    return json.dumps(
        (
            "B" if boundary is not None else "I",
            boundary,
            web.colors[node],
            kinds["O"],
            kinds["H"],
        ),
        separators=(",", ":"),
    )


def refined_labels(web: RibbonWeb) -> Mapping[int, str]:
    labels = {
        node: hashlib.sha256(_node_base(web, node).encode()).hexdigest()
        for node in web.colors
    }
    previous_class_count = len(set(labels.values()))
    for _ in range(max(1, len(web.colors))):
        updated: Dict[int, str] = {}
        for node in web.colors:
            cyclic = _cyclic_minimum(
                [(kind, labels[neighbor]) for neighbor, kind in web.rotations[node]]
            )
            payload = (_node_base(web, node), cyclic)
            updated[node] = hashlib.sha256(
                repr(payload).encode("utf-8")
            ).hexdigest()
        # The old label is part of every new payload, so this refinement can
        # split color classes but cannot merge them.  Once no class splits,
        # the partition is stable even though the cryptographic label strings
        # themselves would continue to change on every round.
        class_count = len(set(updated.values()))
        if class_count == previous_class_count:
            labels = updated
            break
        labels = updated
        previous_class_count = class_count
    return labels


def refined_fingerprint(web: RibbonWeb) -> Tuple[object, ...]:
    """A boundary-fixed ribbon fingerprint used before exact isomorphism."""
    labels = refined_labels(web)
    boundary_profile = tuple(sorted(
        (boundary_label, labels[node])
        for node, boundary_label in web.boundary_labels.items()
    ))
    internal_profile = tuple(sorted(
        labels[node] for node in web.colors if node not in web.boundary_labels
    ))
    return coarse_fingerprint(web), boundary_profile, internal_profile


def coarse_fingerprint(web: RibbonWeb) -> Tuple[object, ...]:
    profiles = []
    for node in web.colors:
        kinds = Counter(kind for _neighbor, kind in web.rotations[node])
        profiles.append(
            (
                node in web.boundary_labels,
                web.colors[node],
                kinds["O"],
                kinds["H"],
            )
        )
    return (
        len(web.colors),
        len(web.boundary_labels),
        sum(kind == "O" for kind in web.edges.values()),
        sum(kind == "H" for kind in web.edges.values()),
        tuple(sorted(profiles)),
    )


def _cyclic_equal(left: Sequence[Port], right: Sequence[Port]) -> bool:
    if len(left) != len(right):
        return False
    if not left:
        return True
    left_tuple, right_tuple = tuple(left), tuple(right)
    return any(
        left_tuple == right_tuple[offset:] + right_tuple[:offset]
        for offset in range(len(right_tuple))
    )


def ribbon_isomorphism(source: RibbonWeb, target: RibbonWeb) -> Optional[Mapping[int, int]]:
    """Return an orientation-preserving boundary-fixed ribbon isomorphism."""
    if coarse_fingerprint(source) != coarse_fingerprint(target):
        return None
    source_labels = refined_labels(source)
    target_labels = refined_labels(target)
    by_target_label: Dict[str, List[int]] = defaultdict(list)
    for node, label in target_labels.items():
        by_target_label[label].append(node)

    domains: Dict[int, Tuple[int, ...]] = {}
    target_boundary_by_label = {
        label: node for node, label in target.boundary_labels.items()
    }
    for node, label in source_labels.items():
        boundary_label = source.boundary_labels.get(node)
        if boundary_label is not None:
            candidate = target_boundary_by_label.get(boundary_label)
            if candidate is None or target_labels.get(candidate) != label:
                return None
            domains[node] = (candidate,)
        else:
            domains[node] = tuple(
                candidate
                for candidate in by_target_label.get(label, [])
                if candidate not in target.boundary_labels
            )
            if not domains[node]:
                return None

    source_neighbors = _neighbors(source)
    target_neighbors = _neighbors(target)
    mapping: Dict[int, int] = {}
    used: set[int] = set()

    def compatible(node: int, candidate: int) -> bool:
        for mapped_node, mapped_candidate in mapping.items():
            source_kind = source.edges.get(frozenset((node, mapped_node)))
            target_kind = target.edges.get(frozenset((candidate, mapped_candidate)))
            if source_kind != target_kind:
                return False
        return len(source_neighbors[node]) == len(target_neighbors[candidate])

    def finish_check() -> bool:
        for node, ports in source.rotations.items():
            transformed = tuple((mapping[neighbor], kind) for neighbor, kind in ports)
            if not _cyclic_equal(transformed, target.rotations[mapping[node]]):
                return False
        return True

    ordered_nodes = sorted(source.colors, key=lambda node: (len(domains[node]), node))

    def search(index: int) -> bool:
        if index == len(ordered_nodes):
            return finish_check()
        node = ordered_nodes[index]
        for candidate in domains[node]:
            if candidate in used or not compatible(node, candidate):
                continue
            mapping[node] = candidate
            used.add(candidate)
            if search(index + 1):
                return True
            used.remove(candidate)
            del mapping[node]
        return False

    return dict(mapping) if search(0) else None


def catalogue_index(graph_dir: Path) -> Mapping[Tuple[object, ...], List[Tuple[str, Path, RibbonWeb]]]:
    result: Dict[Tuple[object, ...], List[Tuple[str, Path, RibbonWeb]]] = defaultdict(list)
    for path in sorted(graph_dir.glob("*.json")):
        word = path.stem.split("_", 1)[-1]
        if len(word) != 16 or set(word) - set("1234"):
            continue
        web = load_ribbon_web(path)
        result[refined_fingerprint(web)].append((word, path, web))
    return result


def identify_catalogue_web(
    web: RibbonWeb,
    index: Mapping[Tuple[object, ...], List[Tuple[str, Path, RibbonWeb]]],
) -> List[Tuple[str, Path]]:
    matches: List[Tuple[str, Path]] = []
    for word, path, candidate in index.get(refined_fingerprint(web), []):
        if ribbon_isomorphism(web, candidate) is not None:
            matches.append((word, path))
    return matches


def _labelled_state_key(web: RibbonWeb) -> Tuple[object, ...]:
    """Deduplicate monotone reductions while retaining fixed boundary labels."""
    return (
        tuple(sorted(web.colors.items())),
        tuple(sorted(web.boundary_labels.items())),
        tuple(sorted((tuple(sorted(edge)), kind) for edge, kind in web.edges.items())),
        tuple(sorted((node, ports) for node, ports in web.rotations.items())),
    )


def identify_after_square_normalization(
    web: RibbonWeb,
    index: Mapping[Tuple[object, ...], List[Tuple[str, Path, RibbonWeb]]],
) -> CatalogueIdentification:
    """Identify a web exactly or after monotone two-hourglass square reductions."""
    direct = tuple(identify_catalogue_web(web, index))
    if direct:
        return CatalogueIdentification(direct, "exact", tuple(), web)

    queue = deque([(web, tuple())])
    seen = {_labelled_state_key(web)}
    while queue:
        current, path = queue.popleft()
        for cycle in alternating_two_hourglass_squares(current):
            reduction = reduce_alternating_two_hourglass_square(current, cycle)
            child = reduction.web
            child_path = path + (reduction.cycle,)
            key = _labelled_state_key(child)
            if key in seen:
                continue
            seen.add(key)
            matches = tuple(identify_catalogue_web(child, index))
            if matches:
                return CatalogueIdentification(
                    matches,
                    "after_two_hourglass_square_move",
                    child_path,
                    child,
                )
            queue.append((child, child_path))
    return CatalogueIdentification(tuple(), "unidentified", tuple(), web)


def pairing_rows(path: Path) -> Mapping[Tuple[str, str], List[Mapping[str, str]]]:
    result: Dict[Tuple[str, str], List[Mapping[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            result[(row.get("w_word", ""), row.get("x_word", ""))].append(row)
    return result


def representative_words(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            row["w_word"]
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("w_word")
        }


def pairing_check(
    w_word: str,
    x_word: str,
    rows: Mapping[Tuple[str, str], List[Mapping[str, str]]],
    representatives: set[str],
) -> Mapping[str, object]:
    matched = rows.get((w_word, x_word), [])
    if matched:
        numeric = []
        for row in matched:
            try:
                numeric.append(int(row.get("final_pairing_value", "")))
            except ValueError:
                pass
        unique = sorted(set(numeric))
        value: object = unique[0] if len(unique) == 1 else unique or None
        return {
            "coverage": "recorded_row",
            "status": matched[-1].get("status", ""),
            "value": value,
            "is_plus_or_minus_one": value in (-1, 1),
            "used_three_strand_relation": matched[-1].get(
                "used_three_strand_relation", ""
            ),
            "row_count": len(matched),
        }
    if w_word in representatives:
        return {
            "coverage": "absent_from_survivor_pairing_table",
            "status": "certified_zero_by_table_absence",
            "value": 0,
            "is_plus_or_minus_one": False,
            "used_three_strand_relation": "",
            "row_count": 0,
        }
    return {
        "coverage": "not_covered_for_this_W",
        "status": "not_checked",
        "value": None,
        "is_plus_or_minus_one": None,
        "used_three_strand_relation": "",
        "row_count": 0,
    }


def compute_pairing_live(w_path: Path, x_path: Path) -> Mapping[str, object]:
    """Evaluate one ordered pair with the current production pairing engine."""
    import Wrench_or_Skein_0714 as wrench

    w_adj, w_bounds, w_hgs = wrench.parse_web(w_path)
    x_adj, x_bounds, x_hgs = wrench.parse_web(x_path)
    w_colors, w_xy = wrench.parse_web_metadata(w_path)
    x_colors, x_xy = wrench.parse_web_metadata(x_path)
    proof = wrench.prove_pair_value_complete_pipeline(
        x_adj,
        x_bounds,
        wrench.sort_hourglasses_by_boundary_distance(x_adj, x_bounds, x_hgs),
        w_adj,
        w_bounds,
        wrench.sort_hourglasses_by_boundary_distance(w_adj, w_bounds, w_hgs),
        allow_w_wrench=False,
        guided_beam_width=120,
        x_beam_width=500,
        x_node_colors=x_colors,
        x_node_xy=x_xy,
        w_node_colors=w_colors,
        w_node_xy=w_xy,
        use_lemma48=False,
    )
    value = proof.get("final_pairing_value")
    return {
        "coverage": "computed_live",
        "status": proof.get("status", ""),
        "value": value,
        "is_plus_or_minus_one": value in (-1, 1),
        "used_three_strand_relation": "yes"
        if proof.get("used_three_strand_relation")
        else "no",
        "active_term_count": proof.get("active_term_count"),
        "discharged_term_count": proof.get("discharged_term_count"),
    }


def indexed_graph_paths(graph_dir: Path) -> Mapping[str, Path]:
    result: Dict[str, Path] = {}
    for path in graph_dir.glob("*.json"):
        word = path.stem.split("_", 1)[-1]
        if len(word) == 16 and not set(word) - set("1234"):
            result[word] = path
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Perform benzene surgery and check <W, Surgery(W)^T>."
    )
    parser.add_argument("word", help="16-letter SL4 Yamanouchi word W")
    parser.add_argument(
        "--graph-dir", type=Path, default=Path("4x4_All_graph_data")
    )
    parser.add_argument(
        "--compute-missing",
        action="store_true",
        help=(
            "Run the current 0714 pairing engine when the consolidated table "
            "does not cover W. This may be slow and has no built-in timeout."
        ),
    )
    parser.add_argument(
        "--pairings",
        type=Path,
        default=Path("all_pairings_0802/All_Pairings_0802.tsv"),
    )
    parser.add_argument(
        "--representatives", type=Path, default=Path("transpose_1522_tasks_latest.tsv")
    )
    parser.add_argument(
        "--splice-across",
        choices=("hourglass", "ordinary"),
        default="hourglass",
        help=(
            "Pair external stubs across hourglass sides (the project surgery "
            "convention) or ordinary sides (diagnostic alternative)."
        ),
    )
    parser.add_argument(
        "--stored-presentation-only",
        action="store_true",
        help=(
            "Only perform surgery on benzenes visible in the stored graph. "
            "By default, also move a benzene along every chain reaction and "
            "output surgery on each newly activated face."
        ),
    )
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = indexed_graph_paths(args.graph_dir)
    if args.word not in paths:
        raise SystemExit(f"No graph JSON found for {args.word} in {args.graph_dir}.")

    source_path = paths[args.word]
    source_web = load_ribbon_web(source_path)
    model = graph_model(source_path)
    all_cycles = induced_internal_six_cycles(model)
    benzenes = [
        cycle
        for cycle in all_cycles
        if is_benzene(cycle, model.edge_kind)
    ]
    if not benzenes:
        raise SystemExit(f"{args.word} has no benzene in its stored presentation.")

    print(f"Indexing {len(paths):,} catalogue graphs...", flush=True)
    index = catalogue_index(args.graph_dir)
    rows = pairing_rows(args.pairings)
    representatives = representative_words(args.representatives)

    splice_kind = "H" if args.splice_across == "hourglass" else "O"
    surgery_channels = enumerate_benzene_surgery_channels(
        source_web,
        all_cycles,
        include_chain_reactions=not args.stored_presentation_only,
        splice_side_kind=splice_kind,
    )
    channels: List[Dict[str, object]] = []
    for position, surgery_channel in enumerate(surgery_channels, start=1):
        cycle = surgery_channel.cycle
        surgery = surgery_channel.surgery
        identification = identify_after_square_normalization(surgery.web, index)
        matches = list(identification.matches)
        channel: Dict[str, object] = {
            "surgery_channel_index": position,
            "surgery_channel_type": surgery_channel.channel_type,
            "benzene_move_count": len(surgery_channel.benzene_move_path),
            "benzene_move_path": [
                list(moved_cycle)
                for moved_cycle in surgery_channel.benzene_move_path
            ],
            "cycle_vertices": list(cycle),
            "external_stubs": {
                str(vertex): external
                for vertex, external in sorted(surgery.external_by_cycle_vertex.items())
            },
            "surgery_edges": [list(edge) for edge in surgery.added_edges],
            "catalogue_identification_mode": identification.mode,
            "square_normalization_count": len(identification.square_path),
            "square_normalization_path": [
                list(square) for square in identification.square_path
            ],
            "catalogue_match_count": len(matches),
            "catalogue_matches": [word for word, _path in matches],
        }
        if len(matches) == 1:
            w_prime, match_path = matches[0]
            transposed = transpose_word(w_prime)
            pairing = dict(pairing_check(args.word, transposed, rows, representatives))
            if args.compute_missing and pairing["coverage"] == "not_covered_for_this_W":
                pairing = dict(compute_pairing_live(source_path, paths[transposed]))
            channel.update(
                {
                    "w_prime": w_prime,
                    "w_prime_file": str(match_path.resolve()),
                    "transpose_of_w_prime": transposed,
                    "pairing": pairing,
                }
            )
        elif not matches:
            channel["identification_error"] = (
                "No ribbon-graph catalogue match before or after monotone "
                "two-hourglass square normalization."
            )
        else:
            channel["identification_error"] = "Ambiguous exact ribbon-graph catalogue match."
        channels.append(channel)

    report = {
        "w_word": args.word,
        "w_file": str(source_path.resolve()),
        "stored_presentation_benzene_count": len(benzenes),
        "benzene_move_orbit_state_count": len(
            benzene_move_presentations(source_web, all_cycles)
        ),
        "surgery_channel_count": len(channels),
        "includes_chain_reaction_channels": not args.stored_presentation_only,
        "surgery_convention": (
            "Remove the alternating six-cycle and splice external half-edges "
            f"across its three {args.splice_across} sides."
        ),
        "channels": channels,
        "all_identified_channels_are_plus_or_minus_one": bool(channels)
        and all(
            channel.get("pairing", {}).get("is_plus_or_minus_one") is True
            for channel in channels
        ),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
