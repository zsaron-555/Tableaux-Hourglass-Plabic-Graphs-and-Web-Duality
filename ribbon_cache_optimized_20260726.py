#!/usr/bin/env python3
"""Canonical colored-ribbon keys and bounded caches for the optimized engine.

The canonical key fixes boundary labels and preserves vertex colors, ordinary
edge multiplicities, hourglass strands, and the tagged cyclic half-edge order.
Temporary internal vertex numbers are ignored whenever exact individualization
finishes within the configured search budget.  On budget exhaustion the key
falls back to an ID-sensitive serialization, which is slower but never causes
an unsafe merge.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple


Key = Tuple[Any, ...]


@dataclass
class OptimizationStats:
    canonical_calls: int = 0
    fingerprint_calls: int = 0
    fingerprint_cache_hits: int = 0
    canonical_cache_hits: int = 0
    canonical_exact: int = 0
    canonical_fallbacks: int = 0
    canonical_search_nodes: int = 0
    term_merges: int = 0
    beam_candidates_raw: int = 0
    beam_candidates_unique: int = 0
    expansion_cache_hits: int = 0
    expansion_cache_misses: int = 0
    lemma49_cache_hits: int = 0
    lemma49_cache_misses: int = 0
    lemma49_compiled_w_cache_hits: int = 0
    lemma49_compiled_w_cache_misses: int = 0
    rotation_untwist_checks: int = 0
    rotation_untwists: int = 0
    geometry_rotation_disagreements: int = 0

    def snapshot(self) -> Dict[str, int]:
        return dict(self.__dict__)


STATS = OptimizationStats()


class BoundedCache:
    """Small explicit LRU cache with values controlled by the caller."""

    def __init__(self, maxsize: int) -> None:
        self.maxsize = max(1, int(maxsize))
        self._items: OrderedDict[Key, Any] = OrderedDict()

    def get(self, key: Key, default: Any = None) -> Any:
        try:
            value = self._items.pop(key)
        except KeyError:
            return default
        self._items[key] = value
        return value

    def put(self, key: Key, value: Any) -> None:
        if key in self._items:
            self._items.pop(key)
        self._items[key] = value
        while len(self._items) > self.maxsize:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


CANONICAL_CACHE = BoundedCache(200_000)
FINGERPRINT_CACHE = BoundedCache(300_000)
EXPANSION_CACHE = BoundedCache(100_000)
LEMMA49_CACHE = BoundedCache(200_000)
LEMMA49_COMPILED_W_CACHE = BoundedCache(5_000)


def reset_stats(*, clear_caches: bool = False) -> None:
    global STATS
    STATS = OptimizationStats()
    if clear_caches:
        CANONICAL_CACHE.clear()
        FINGERPRINT_CACHE.clear()
        EXPANSION_CACHE.clear()
        LEMMA49_CACHE.clear()
        LEMMA49_COMPILED_W_CACHE.clear()


def _hourglass_pairs(hourglasses: Iterable[Mapping[str, Any]]) -> Tuple[Tuple[int, int], ...]:
    pairs = []
    for hg in hourglasses:
        white = int(hg["white"])
        black = int(hg["black"])
        pairs.append(tuple(sorted((white, black))))
    return tuple(sorted(pairs))


def raw_ribbon_key(
    adj: Mapping[int, Any],
    hourglasses: Iterable[Mapping[str, Any]],
    boundary_labels: Mapping[int, int],
    node_colors: Optional[Mapping[int, str]],
) -> Key:
    """ID-sensitive key used for memo lookup and conservative fallback."""
    hg_pairs = _hourglass_pairs(hourglasses)
    hg_partner: Dict[int, int] = {}
    for first, second in hg_pairs:
        hg_partner[first] = second
        hg_partner[second] = first

    rows = []
    for node in sorted(int(item) for item in adj):
        value = adj[node]
        if isinstance(value, MutableMapping):
            slot_pattern = tuple(str(item) for item in getattr(value, "slot_pattern", ()))
            if slot_pattern:
                incident = []
                strand = 0
                for slot in slot_pattern:
                    if slot in {"top", "bot"}:
                        neighbor = value.get(slot)
                        incident.append(("o", None if neighbor is None else int(neighbor)))
                    elif slot.startswith("strand"):
                        incident.append((f"h{strand}", hg_partner.get(node)))
                        strand += 1
                    else:
                        incident.append((slot, None))
            else:
                incident = [
                    ("o", None if value.get(slot) is None else int(value[slot]))
                    for slot in ("top", "bot")
                ]
        else:
            incident = [("o", int(neighbor)) for neighbor in value if neighbor is not None]
        rows.append(
            (
                node,
                boundary_labels.get(node),
                str((node_colors or {}).get(node, "")),
                tuple(incident),
            )
        )
    return ("raw-ribbon-v1", tuple(rows), hg_pairs)


def _incident_sequences(
    adj: Mapping[int, Any],
    hourglasses: Iterable[Mapping[str, Any]],
) -> Dict[int, Tuple[Tuple[str, int], ...]]:
    hg_partner: Dict[int, int] = {}
    for first, second in _hourglass_pairs(hourglasses):
        hg_partner[first] = second
        hg_partner[second] = first

    result: Dict[int, Tuple[Tuple[str, int], ...]] = {}
    for node_raw, value in adj.items():
        node = int(node_raw)
        incident: List[Tuple[str, int]] = []
        if isinstance(value, MutableMapping):
            slot_pattern = tuple(str(item) for item in getattr(value, "slot_pattern", ()))
            if slot_pattern:
                strand = 0
                for slot in slot_pattern:
                    if slot in {"top", "bot"}:
                        neighbor = value.get(slot)
                        if neighbor is not None:
                            incident.append(("ordinary", int(neighbor)))
                    elif slot.startswith("strand"):
                        partner = hg_partner.get(node)
                        if partner is not None:
                            incident.append((f"hourglass:{strand}", partner))
                        strand += 1
            else:
                for slot in ("top", "bot"):
                    neighbor = value.get(slot)
                    if neighbor is not None:
                        incident.append(("ordinary", int(neighbor)))
                partner = hg_partner.get(node)
                if partner is not None:
                    incident.extend((("hourglass:0", partner), ("hourglass:1", partner)))
        else:
            incident.extend(
                ("ordinary", int(neighbor))
                for neighbor in value
                if neighbor is not None and int(neighbor) in adj
            )
        result[node] = tuple(incident)
    return result


def _compress(descriptors: Mapping[int, Key]) -> Dict[int, int]:
    ordered = {descriptor: index for index, descriptor in enumerate(sorted(set(descriptors.values())))}
    return {node: ordered[descriptor] for node, descriptor in descriptors.items()}


def refinement_ribbon_fingerprint(
    adj: Mapping[int, Any],
    hourglasses: Iterable[Mapping[str, Any]],
    boundary_labels: Mapping[int, int],
    node_colors: Optional[Mapping[int, str]],
) -> Key:
    """Fast ID-invariant colored-ribbon refinement fingerprint.

    Equality is only a necessary condition for isomorphism.  Callers must run
    ``canonical_ribbon_key`` before merging two states in the same bucket.
    """
    STATS.fingerprint_calls += 1
    raw = raw_ribbon_key(adj, hourglasses, boundary_labels, node_colors)
    cached = FINGERPRINT_CACHE.get(raw)
    if cached is not None:
        STATS.fingerprint_cache_hits += 1
        return cached

    nodes = tuple(sorted(int(node) for node in adj))
    incident = _incident_sequences(adj, hourglasses)
    base: Dict[int, Key] = {}
    for node in nodes:
        value = adj[node]
        base[node] = (
            ("boundary", int(boundary_labels[node]))
            if node in boundary_labels
            else ("internal",)
        ) + (
            str((node_colors or {}).get(node, "")),
            "ports" if isinstance(value, MutableMapping) else "ordinary",
            len(incident[node]),
            tuple(kind for kind, _neighbor in incident[node]),
        )
    colors = _compress(base)
    while True:
        descriptors = {
            node: (
                base[node],
                colors[node],
                tuple((kind, colors[neighbor]) for kind, neighbor in incident[node]),
            )
            for node in nodes
        }
        updated = _compress(descriptors)
        if updated == colors:
            break
        colors = updated
    result = (
        "refined-ribbon-v1",
        tuple(
            sorted(
                (
                    base[node],
                    colors[node],
                    tuple((kind, colors[neighbor]) for kind, neighbor in incident[node]),
                )
                for node in nodes
            )
        ),
    )
    FINGERPRINT_CACHE.put(raw, result)
    return result


def canonical_ribbon_key(
    adj: Mapping[int, Any],
    hourglasses: Iterable[Mapping[str, Any]],
    boundary_labels: Mapping[int, int],
    node_colors: Optional[Mapping[int, str]],
    *,
    search_budget: int = 4096,
) -> Key:
    """Return an exact boundary-fixed colored-ribbon key when feasible."""
    STATS.canonical_calls += 1
    raw = raw_ribbon_key(adj, hourglasses, boundary_labels, node_colors)
    cached = CANONICAL_CACHE.get(raw)
    if cached is not None:
        STATS.canonical_cache_hits += 1
        return cached

    nodes = tuple(sorted(int(node) for node in adj))
    incident = _incident_sequences(adj, hourglasses)
    base: Dict[int, Key] = {}
    for node in nodes:
        value = adj[node]
        base[node] = (
            ("boundary", int(boundary_labels[node]))
            if node in boundary_labels
            else ("internal",)
        ) + (
            str((node_colors or {}).get(node, "")),
            "ports" if isinstance(value, MutableMapping) else "ordinary",
            len(incident[node]),
            tuple(kind for kind, _neighbor in incident[node]),
        )

    budget = [max(1, int(search_budget))]

    def refine(individualized: Tuple[int, ...]) -> Dict[int, int]:
        marks = {node: index for index, node in enumerate(individualized)}
        colors = _compress(
            {
                node: (base[node], ("mark", marks[node]) if node in marks else ("unmarked",))
                for node in nodes
            }
        )
        while True:
            descriptors = {
                node: (
                    base[node],
                    colors[node],
                    tuple((kind, colors[neighbor]) for kind, neighbor in incident[node]),
                )
                for node in nodes
            }
            updated = _compress(descriptors)
            if updated == colors:
                return colors
            colors = updated

    def serialize(colors: Mapping[int, int]) -> Key:
        ordered_nodes = sorted(nodes, key=lambda node: colors[node])
        canonical_id = {node: index for index, node in enumerate(ordered_nodes)}
        rows = tuple(
            (
                base[node],
                tuple((kind, canonical_id[neighbor]) for kind, neighbor in incident[node]),
            )
            for node in ordered_nodes
        )
        return ("canonical-ribbon-v1", rows)

    def search(individualized: Tuple[int, ...]) -> Optional[Key]:
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        STATS.canonical_search_nodes += 1
        colors = refine(individualized)
        counts = Counter(colors.values())
        tied_colors = [color for color, count in counts.items() if count > 1]
        if not tied_colors:
            return serialize(colors)
        selected_color = min(
            tied_colors,
            key=lambda color: (
                counts[color],
                min(base[node] for node in nodes if colors[node] == color),
                color,
            ),
        )
        cell = [node for node in nodes if colors[node] == selected_color]
        best: Optional[Key] = None
        for node in cell:
            candidate = search(individualized + (node,))
            if candidate is None:
                continue
            if best is None or candidate < best:
                best = candidate
        return best

    canonical = search(())
    if canonical is None:
        STATS.canonical_fallbacks += 1
        result = ("id-sensitive-fallback", raw)
    else:
        STATS.canonical_exact += 1
        result = canonical
    CANONICAL_CACHE.put(raw, result)
    return result
