#!/usr/bin/env python3
"""Streaming, memoized X-only evaluator for SL4 web pairings.

This module is an experiment.  It keeps the geometry-based untwist oracle from
``Wrench_or_Skein_optimized_20260726`` but changes the algebraic search:

* active terms live in a coefficient-aggregating worklist;
* only newly-created children are tested for zero rules;
* relation detection and complete local expansions are memoized;
* a boundary-labelled colored-ribbon key merges states that differ only by
  temporary internal vertex IDs;
* an optional versioned SQLite cache persists exact-ID expansion templates.

The persistent cache is deliberately conservative.  It stores only exact raw
states.  Canonical merging happens in memory and is guarded by the exact
colored-ribbon canonicalizer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import copy
import hashlib
import json
from pathlib import Path
import pickle
import sqlite3
import time
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Tuple

import ribbon_cache_optimized_20260726 as ribbon_cache


Key = Tuple[Any, ...]
_MISS = object()


@dataclass
class StreamingStats:
    moves: int = 0
    children_generated: int = 0
    terms_inserted: int = 0
    terms_merged: int = 0
    terms_cancelled: int = 0
    terms_discharged: int = 0
    terms_colored: int = 0
    unresolved_terms: int = 0
    max_active_terms: int = 0
    move_cache_hits: int = 0
    move_cache_misses: int = 0
    expansion_cache_hits: int = 0
    expansion_cache_misses: int = 0
    discharge_cache_hits: int = 0
    discharge_cache_misses: int = 0
    canonical_key_seconds: float = 0.0
    move_detection_seconds: float = 0.0
    expansion_seconds: float = 0.0
    discharge_seconds: float = 0.0
    coloring_seconds: float = 0.0
    coloring_cache_hits: int = 0
    coloring_cache_misses: int = 0
    sqlite_hits: int = 0
    sqlite_misses: int = 0
    sqlite_writes: int = 0
    normalization_copy_skips: int = 0
    normalization_copies: int = 0
    state_key_cache_hits: int = 0
    state_key_cache_misses: int = 0


class PersistentExpansionCache:
    """Versioned exact-state cache for local expansion templates."""

    def __init__(self, path: Optional[Path], namespace: str) -> None:
        self.path = path
        self.namespace = namespace
        self.connection: Optional[sqlite3.Connection] = None
        self.pending_writes = 0
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path)
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=NORMAL")
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS expansion_cache (
                    namespace TEXT NOT NULL,
                    cache_key BLOB NOT NULL,
                    payload BLOB NOT NULL,
                    PRIMARY KEY(namespace, cache_key)
                )
                """
            )
            self.connection.commit()

    @staticmethod
    def _key_blob(key: Key) -> bytes:
        return hashlib.sha256(pickle.dumps(key, protocol=5)).digest()

    def get(self, key: Key) -> Any:
        if self.connection is None:
            return _MISS
        row = self.connection.execute(
            "SELECT payload FROM expansion_cache WHERE namespace=? AND cache_key=?",
            (self.namespace, self._key_blob(key)),
        ).fetchone()
        if row is None:
            return _MISS
        return pickle.loads(row[0])

    def put(self, key: Key, value: Any) -> None:
        if self.connection is None:
            return
        self.connection.execute(
            """
            INSERT OR REPLACE INTO expansion_cache(namespace, cache_key, payload)
            VALUES (?, ?, ?)
            """,
            (
                self.namespace,
                self._key_blob(key),
                sqlite3.Binary(pickle.dumps(value, protocol=5)),
            ),
        )
        self.pending_writes += 1
        if self.pending_writes >= 256:
            self.connection.commit()
            self.pending_writes = 0

    def close(self) -> None:
        if self.connection is not None:
            if self.pending_writes:
                self.connection.commit()
            self.connection.close()
            self.connection = None


class CompiledColoringCounter:
    """Constraint-propagating coloring counter for one fixed W.

    The production routine branches edge by edge over all four colors.  This
    equivalent solver compiles W once, propagates the all-different constraint
    at each internal 4-valent vertex, branches on the smallest domain, and
    memoizes residual domain states across different terminal X partitions.
    """

    def __init__(
        self,
        engine: Any,
        adj: Mapping[int, Any],
        boundary_labels: Mapping[int, int],
        hourglasses: Iterable[Mapping[str, Any]],
        *,
        r: int = 4,
    ) -> None:
        self.engine = engine
        self.adj = adj
        self.boundary_labels = dict(boundary_labels)
        self.hourglasses = list(hourglasses)
        self.r = int(r)
        self.all_mask = (1 << self.r) - 1
        self.edges: List[Tuple[int, int]] = []
        self.incident: Dict[int, List[int]] = {int(node): [] for node in adj}
        self.boundary_edge_label: Dict[int, int] = {}
        self.hourglass_pairs: List[Tuple[int, int]] = []
        self.valid = True
        self.invalid_reason: Optional[str] = None
        self.memo: Dict[Tuple[int, ...], int] = {}

        covered = {
            int(endpoint)
            for hg in self.hourglasses
            for endpoint in (int(hg["white"]), int(hg["black"]))
            if int(endpoint) in adj
        }
        if any(
            isinstance(neighbors, dict) and int(node) not in covered
            for node, neighbors in adj.items()
        ):
            self.valid = False
            self.invalid_reason = "uncovered_hourglass_metadata"
            return

        for u, neighbors in adj.items():
            for v in engine.neighbor_list(neighbors):
                if int(u) <= int(v):
                    self._add_edge(int(u), int(v))
        for hg in self.hourglasses:
            white = int(hg["white"])
            black = int(hg["black"])
            if white not in adj or black not in adj:
                continue
            first = self._add_edge(white, black)
            second = self._add_edge(white, black)
            self.hourglass_pairs.append((first, second))

        for index, (u, v) in enumerate(self.edges):
            boundary_endpoints = [
                node for node in (u, v) if node in self.boundary_labels
            ]
            if len(boundary_endpoints) > 1:
                self.valid = False
                self.invalid_reason = "boundary_boundary_edge"
                return
            if boundary_endpoints:
                self.boundary_edge_label[index] = int(
                    self.boundary_labels[boundary_endpoints[0]]
                )
        for node, edge_indices in self.incident.items():
            if node not in self.boundary_labels and len(edge_indices) != self.r:
                self.valid = False
                self.invalid_reason = "non_r_valent_internal_vertex"
                return

    def _add_edge(self, u: int, v: int) -> int:
        index = len(self.edges)
        self.edges.append((u, v))
        self.incident[u].append(index)
        self.incident[v].append(index)
        return index

    @staticmethod
    def _singleton_color(mask: int) -> int:
        return mask.bit_length() if mask and mask & (mask - 1) == 0 else 0

    def _propagate(self, domains: List[int]) -> bool:
        changed = True
        internal = [
            node for node in self.adj if node not in self.boundary_labels
        ]
        while changed:
            changed = False
            for node in internal:
                edge_indices = self.incident[int(node)]
                used = 0
                unresolved: List[int] = []
                for edge_index in edge_indices:
                    domain = domains[edge_index]
                    if domain == 0:
                        return False
                    color = self._singleton_color(domain)
                    if color:
                        bit = 1 << (color - 1)
                        if used & bit:
                            return False
                        used |= bit
                    else:
                        unresolved.append(edge_index)
                missing = self.all_mask & ~used
                if missing.bit_count() != len(unresolved):
                    return False
                for edge_index in unresolved:
                    narrowed = domains[edge_index] & missing
                    if not narrowed:
                        return False
                    if narrowed != domains[edge_index]:
                        domains[edge_index] = narrowed
                        changed = True

                # Hall checks and hidden singletons are tiny here (at most four
                # incident edges), but remove a large part of the search tree.
                count = len(unresolved)
                for subset in range(1, 1 << count):
                    union = 0
                    members = 0
                    for offset, edge_index in enumerate(unresolved):
                        if subset & (1 << offset):
                            members += 1
                            union |= domains[edge_index]
                    if union.bit_count() < members:
                        return False
                for bit_index in range(self.r):
                    bit = 1 << bit_index
                    candidates = [
                        edge_index
                        for edge_index in unresolved
                        if domains[edge_index] & bit
                    ]
                    if len(candidates) == 1 and domains[candidates[0]] != bit:
                        domains[candidates[0]] = bit
                        changed = True

            for first, second in self.hourglass_pairs:
                left = domains[first]
                right = domains[second]
                allowed_left = 0
                allowed_right = 0
                for left_color in range(1, self.r + 1):
                    left_bit = 1 << (left_color - 1)
                    if not left & left_bit:
                        continue
                    for right_color in range(left_color + 1, self.r + 1):
                        right_bit = 1 << (right_color - 1)
                        if right & right_bit:
                            allowed_left |= left_bit
                            allowed_right |= right_bit
                if not allowed_left or not allowed_right:
                    return False
                if left != allowed_left:
                    domains[first] = allowed_left
                    changed = True
                if right != allowed_right:
                    domains[second] = allowed_right
                    changed = True
        return True

    def _count(self, domains_tuple: Tuple[int, ...]) -> int:
        cached = self.memo.get(domains_tuple)
        if cached is not None:
            return cached
        domains = list(domains_tuple)
        if not self._propagate(domains):
            self.memo[domains_tuple] = 0
            return 0
        reduced = tuple(domains)
        if reduced != domains_tuple:
            result = self._count(reduced)
            self.memo[domains_tuple] = result
            return result
        choices = [
            (domain.bit_count(), index, domain)
            for index, domain in enumerate(domains)
            if domain.bit_count() > 1
        ]
        if not choices:
            self.memo[domains_tuple] = 1
            return 1
        _size, edge_index, domain = min(choices)
        total = 0
        remaining = domain
        while remaining:
            bit = remaining & -remaining
            remaining -= bit
            child = list(domains)
            child[edge_index] = bit
            total += self._count(tuple(child))
        self.memo[domains_tuple] = total
        return total

    def count(self, boundary_color_by_label: Mapping[int, int]) -> int:
        if not self.valid:
            if self.invalid_reason == "uncovered_hourglass_metadata":
                raise ValueError(
                    "Coloring fallback saw hourglass-style vertices without "
                    "matching remaining hourglass metadata."
                )
            if self.invalid_reason == "boundary_boundary_edge":
                raise ValueError(
                    "Boundary-boundary edge is not supported by the coloring fallback."
                )
            return 0
        domains = [self.all_mask] * len(self.edges)
        for edge_index, label in self.boundary_edge_label.items():
            color = boundary_color_by_label.get(label)
            if color is None or not 1 <= int(color) <= self.r:
                return 0
            domains[edge_index] = 1 << (int(color) - 1)
        return self._count(tuple(domains))


def source_namespace(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return "streaming-x-v2-" + digest.hexdigest()


class StreamingXEvaluator:
    """Evaluate a pairing using one deterministic, memoized X reduction."""

    def __init__(
        self,
        engine: Any,
        *,
        x_boundary_labels: Mapping[int, int],
        w_boundary_labels: Mapping[int, int],
        x_node_colors: Mapping[int, str],
        w_node_colors: Mapping[int, str],
        x_node_xy: Mapping[int, Tuple[float, float]],
        source_web_sign: int,
        use_lemma49: bool = True,
        compiled_lemma49: bool = True,
        allow_three_strand: bool = True,
        canonical_merge: bool = True,
        lookahead: bool = True,
        persistent_cache: Optional[PersistentExpansionCache] = None,
    ) -> None:
        self.engine = engine
        self.x_bounds = dict(x_boundary_labels)
        self.w_bounds = dict(w_boundary_labels)
        self.x_colors = dict(x_node_colors)
        self.w_colors = dict(w_node_colors)
        self.x_xy = dict(x_node_xy)
        self.geometry_scope = hashlib.sha256(
            pickle.dumps(
                tuple(
                    sorted(
                        (
                            int(node),
                            round(float(xy[0]), 12),
                            round(float(xy[1]), 12),
                        )
                        for node, xy in self.x_xy.items()
                    )
                ),
                protocol=5,
            )
        ).hexdigest()
        self.source_web_sign = int(source_web_sign)
        self.use_lemma49 = bool(use_lemma49)
        self.compiled_lemma49 = bool(compiled_lemma49)
        self.allow_three_strand = bool(allow_three_strand)
        self.canonical_merge = bool(canonical_merge)
        self.lookahead = bool(lookahead)
        self.persistent_cache = persistent_cache
        self.stats = StreamingStats()
        self.move_cache: Dict[Key, List[Dict[str, Any]]] = {}
        self.expansion_cache: Dict[Key, List[Dict[str, Any]]] = {}
        self.discharge_cache: Dict[Key, Optional[Dict[str, Any]]] = {}
        self.coloring_count_cache: Dict[Key, int] = {}
        self.compiled_coloring_counter: Optional[CompiledColoringCounter] = None
        self.compiled_lemma49_matcher: Optional[Any] = None
        self.w_forks: Optional[set[frozenset[int]]] = None
        self.x_fork_cache: Dict[Key, set[frozenset[int]]] = {}

        # The optimized engine uses this context for safe ribbon keys and its
        # own Lemma 4.9 cache.  W is fixed throughout this evaluator.
        engine._OPT_CONTEXT = {
            "x_boundary_labels": self.x_bounds,
            "w_boundary_labels": self.w_bounds,
            "x_node_colors": self.x_colors,
            "w_node_colors": self.w_colors,
        }

    def embedding_signature(self, term: Mapping[str, Any]) -> Key:
        cached = term.get("_stream_embedding_signature")
        if cached is not None:
            self.stats.state_key_cache_hits += 1
            return cached
        self.stats.state_key_cache_misses += 1
        curves = self.engine.edge_curves_from_history(
            term.get("history", []), "X", term["x_adj"]
        )
        result = tuple(
            (
                int(edge[0]),
                int(edge[1]),
                tuple(
                    (round(float(point[0]), 12), round(float(point[1]), 12))
                    for point in points
                ),
            )
            for edge, points in sorted(curves.items())
        )
        if isinstance(term, dict):
            term["_stream_embedding_signature"] = result
        return result

    def x_graph_key(self, term: Mapping[str, Any]) -> Key:
        cached = term.get("_stream_x_graph_key")
        if cached is not None:
            self.stats.state_key_cache_hits += 1
            return cached
        self.stats.state_key_cache_misses += 1
        result = ribbon_cache.raw_ribbon_key(
            term["x_adj"], term["x_remaining"], self.x_bounds, self.x_colors
        )
        if isinstance(term, dict):
            term["_stream_x_graph_key"] = result
        return result

    def raw_key(self, term: Mapping[str, Any]) -> Key:
        cached = term.get("_stream_raw_key")
        if cached is not None:
            self.stats.state_key_cache_hits += 1
            return cached
        self.stats.state_key_cache_misses += 1
        history = term.get("history", [])
        result = (
            self.x_graph_key(term),
            self.embedding_signature(term),
            self.engine.relation_history_orientation_sign(history, "X"),
            any(
                move.get("phase") == "antisymmetrizer"
                or "3strand" in str(move.get("rule", "")).lower()
                or "three_strand" in str(move.get("rule", "")).lower()
                for move in history
            ),
        )
        if isinstance(term, dict):
            term["_stream_raw_key"] = result
        return result

    def structural_key(self, term: Mapping[str, Any]) -> Key:
        if not self.canonical_merge:
            return self.raw_key(term)
        embedding = self.embedding_signature(term)
        # The geometry oracle can distinguish two curve embeddings of the same
        # abstract ribbon graph.  Until curve control points themselves have a
        # canonical relabeling, do not merge such states.
        if embedding:
            return self.raw_key(term)
        started = time.perf_counter()
        result = (
            ribbon_cache.canonical_ribbon_key(
                term["x_adj"], term["x_remaining"], self.x_bounds, self.x_colors
            ),
            self.engine.relation_history_orientation_sign(
                term.get("history", []), "X"
            ),
            any(
                move.get("phase") == "antisymmetrizer"
                or "3strand" in str(move.get("rule", "")).lower()
                or "three_strand" in str(move.get("rule", "")).lower()
                for move in term.get("history", [])
            ),
        )
        self.stats.canonical_key_seconds += time.perf_counter() - started
        return result

    @staticmethod
    def _adjacency_is_reciprocal(engine: Any, adj: Any) -> bool:
        """Return whether drop_nonreciprocal_references would be a no-op."""
        for node, neighbors in adj.items():
            if isinstance(neighbors, dict):
                values = neighbors.values()
            else:
                values = neighbors
            for neighbor in values:
                if neighbor is None:
                    continue
                neighbor = int(neighbor)
                if neighbor not in adj:
                    return False
                if int(node) not in engine.neighbor_list(adj[neighbor]):
                    return False
        return True

    def _normalize_active_term(self, term: Mapping[str, Any]) -> Dict[str, Any]:
        """Normalize the changing X side while reusing the fixed W side.

        The streaming evaluator never applies a relation to W. Production's
        generic normalize_pair_term() copies and cleans both graphs, which is
        necessary for the bidirectional search but redundant here.
        """
        if self._adjacency_is_reciprocal(self.engine, term["x_adj"]):
            x_adj = term["x_adj"]
            self.stats.normalization_copy_skips += 1
        else:
            x_adj = self.engine.drop_nonreciprocal_references(term["x_adj"])
            self.stats.normalization_copies += 1
        result = {
            key: value
            for key, value in term.items()
            if not str(key).startswith("_stream_")
        }
        result.update(
            {
                "x_adj": x_adj,
                "x_remaining": self.engine.clean_hourglasses_for_adj(
                    x_adj, term["x_remaining"]
                ),
                "w_adj": term["w_adj"],
                "w_remaining": term["w_remaining"],
            }
        )
        return result

    def _moves(self, term: Mapping[str, Any]) -> List[Dict[str, Any]]:
        raw = self.raw_key(term)
        cached = self.move_cache.get(raw)
        if cached is not None:
            self.stats.move_cache_hits += 1
            return cached
        self.stats.move_cache_misses += 1
        started = time.perf_counter()
        # Every active term crossed the normalization boundary in insert().
        # Repeating it here copied the X graph a second time before each move
        # scan and also copied the fixed W graph unnecessarily.
        normalized = term
        moves: List[Dict[str, Any]] = []
        for match in self.engine.detect_figure43_moves(
            normalized["x_adj"],
            normalized["x_remaining"],
            self.x_colors,
            self.x_xy,
        ):
            moves.append({"relation": "figure43", "match": copy.deepcopy(match)})
        for hg in normalized["x_remaining"]:
            moves.append({"relation": "wrench", "hourglass": copy.deepcopy(hg)})
        if (
            self.allow_three_strand
            and not normalized["x_remaining"]
            and self._has_internal_black(normalized)
        ):
            for match in self.engine.detect_antisymmetrizer_moves(
                normalized["x_adj"], self.x_colors, self.x_xy
            ):
                moves.append(
                    {"relation": "antisymmetrizer", "match": copy.deepcopy(match)}
                )
        self.stats.move_detection_seconds += time.perf_counter() - started
        self.move_cache[raw] = moves
        return moves

    def _has_internal_black(self, term: Mapping[str, Any]) -> bool:
        return any(
            int(node) not in self.x_bounds
            and self.x_colors.get(int(node)) == "black"
            for node in term["x_adj"]
        )

    def _ready(self, term: Mapping[str, Any]) -> bool:
        return not term["x_remaining"] and not self._has_internal_black(term)

    def _expansion_key(self, term: Mapping[str, Any], move: Mapping[str, Any]) -> Key:
        relation = str(move["relation"])
        if relation == "wrench":
            payload = tuple(
                sorted(
                    (
                        int(move["hourglass"]["white"]),
                        int(move["hourglass"]["black"]),
                    )
                )
            )
        elif relation == "figure43":
            match = move["match"]
            payload = (
                str(match.get("rule", "")),
                tuple(int(v) for v in match["vertices_top_right_bottom_left"]),
            )
        else:
            match = move["match"]
            payload = (
                str(match.get("rule", "")),
                int(match["white"]),
                int(match["black"]),
            )
        return (
            "local-expansion-v3",
            self.geometry_scope,
            self.raw_key(term),
            relation,
            payload,
        )

    @staticmethod
    def _template_term(term: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "x_adj": term["x_adj"],
            "x_remaining": term["x_remaining"],
            "w_adj": term["w_adj"],
            "w_remaining": term["w_remaining"],
            "coeff": 1,
            # Geometry-based smoothing reads prior replacement curves from
            # history, but expansion only appends a new immutable move record.
            # A shallow list copy therefore preserves isolation without
            # recursively copying every older curve record for each lookahead.
            "history": list(term.get("history", [])),
        }

    def _expand(
        self, term: Mapping[str, Any], move: Mapping[str, Any]
    ) -> List[Dict[str, Any]]:
        cache_key = self._expansion_key(term, move)
        cached = self.expansion_cache.get(cache_key)
        if cached is None and self.persistent_cache is not None:
            disk = self.persistent_cache.get(cache_key)
            if disk is not _MISS:
                self.stats.sqlite_hits += 1
                cached = disk
            else:
                self.stats.sqlite_misses += 1
        if cached is not None:
            self.stats.expansion_cache_hits += 1
            return self._materialize_children(term, cached)

        self.stats.expansion_cache_misses += 1
        started = time.perf_counter()
        template = self._template_term(term)
        relation = str(move["relation"])
        if relation == "figure43":
            children = self.engine.expand_pair_term_by_figure43(
                template, "X", move["match"]
            )
        elif relation == "wrench":
            children = self.engine.expand_pair_term(
                template,
                "X",
                move["hourglass"],
                node_xy=self.x_xy,
                boundary_labels=self.x_bounds,
            )
        elif relation == "antisymmetrizer":
            children = self.engine.expand_pair_term_by_antisymmetrizer(
                template, move["match"], node_xy=self.x_xy
            )
        else:
            raise ValueError(relation)
        self.stats.expansion_seconds += time.perf_counter() - started
        prefix_length = len(term.get("history", []))
        relative = [
            {
                "x_adj": child["x_adj"],
                "x_remaining": child["x_remaining"],
                "w_adj": child["w_adj"],
                "w_remaining": child["w_remaining"],
                "coeff": int(child["coeff"]),
                "history": child.get("history", [])[prefix_length:],
            }
            for child in children
        ]
        self.expansion_cache[cache_key] = relative
        if self.persistent_cache is not None:
            self.persistent_cache.put(cache_key, relative)
            self.stats.sqlite_writes += 1
        return self._materialize_children(term, relative)

    @staticmethod
    def _materialize_children(
        parent: Mapping[str, Any], relative: Iterable[Mapping[str, Any]]
    ) -> List[Dict[str, Any]]:
        prefix_history = list(parent.get("history", []))
        parent_coeff = int(parent["coeff"])
        result = []
        for child in relative:
            result.append(
                {
                    # insert() immediately normalizes every materialized child,
                    # and normalization builds a fresh adjacency.  The cached
                    # relative state is never mutated, so copying it here only
                    # duplicates work before that guaranteed copy boundary.
                    "x_adj": child["x_adj"],
                    "x_remaining": child["x_remaining"],
                    "w_adj": parent["w_adj"],
                    "w_remaining": parent["w_remaining"],
                    "coeff": parent_coeff * int(child["coeff"]),
                    "history": prefix_history + list(child.get("history", [])),
                }
            )
        return result

    def _discharge(self, term: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        key = self.x_graph_key(term)
        if key in self.discharge_cache:
            self.stats.discharge_cache_hits += 1
            cached = self.discharge_cache[key]
            return copy.deepcopy(cached)
        self.stats.discharge_cache_misses += 1
        started = time.perf_counter()
        if self.w_forks is None:
            self.w_forks = self.engine.get_forks(
                term["w_adj"], self.w_bounds
            )
        x_forks = self.x_fork_cache.get(key)
        if x_forks is None:
            x_forks = self.engine.get_forks(term["x_adj"], self.x_bounds)
            self.x_fork_cache[key] = x_forks
        common = self.w_forks & x_forks
        result: Optional[Dict[str, Any]]
        if common:
            result = {
                "coeff": int(term["coeff"]),
                "common_forks": sorted(
                    [self.engine.fork_to_list(fork) for fork in common]
                ),
                "history": term.get("history", []),
                "reason": "fork_lemma",
            }
        elif self.use_lemma49:
            if self.compiled_lemma49 and self.compiled_lemma49_matcher is None:
                self.compiled_lemma49_matcher = (
                    self.engine.compile_lemma49_matcher_for_term(
                        dict(term),
                        self.w_bounds,
                        self.w_colors,
                    )
                )
            match = self.engine.lemma49_pair_match_for_term(
                dict(term),
                self.x_bounds,
                self.w_bounds,
                self.x_colors,
                self.w_colors,
                compiled_matcher=(
                    self.compiled_lemma49_matcher
                    if self.compiled_lemma49
                    else None
                ),
                x_state_key=key,
            )
            if match:
                source = match.get("source", {})
                result = {
                    "coeff": int(term["coeff"]),
                    "common_forks": [],
                    "history": term.get("history", []),
                    "reason": "lemma49_zero",
                    "lemma49_match": match,
                    "lemma49_rule_id": match.get("rule_id"),
                    "lemma49_case": source.get("case")
                    or match.get("reason"),
                    "lemma49_boundary_labels": match.get(
                        "boundary_labels", []
                    ),
                }
            else:
                result = None
        else:
            result = None
        self.stats.discharge_seconds += time.perf_counter() - started
        self.discharge_cache[key] = copy.deepcopy(result)
        return result

    def _color(self, term: Mapping[str, Any]) -> Optional[int]:
        started = time.perf_counter()
        if term["x_remaining"]:
            return None
        condition = self.engine.component_boundary_condition_from_x(
            term["x_adj"], self.x_bounds, r=4
        )
        if condition is None:
            self.stats.coloring_seconds += time.perf_counter() - started
            return None
        terminal_orientation = self.engine.plucker_product_orientation_sign(
            term["x_adj"], self.x_bounds, r=4
        )
        if terminal_orientation is None:
            self.stats.coloring_seconds += time.perf_counter() - started
            return None
        condition_key = tuple(sorted((int(label), int(color)) for label, color in condition.items()))
        count = self.coloring_count_cache.get(condition_key)
        if count is None:
            self.stats.coloring_cache_misses += 1
            if self.compiled_coloring_counter is None:
                self.compiled_coloring_counter = CompiledColoringCounter(
                    self.engine,
                    term["w_adj"],
                    self.w_bounds,
                    term["w_remaining"],
                    r=4,
                )
            count = int(self.compiled_coloring_counter.count(condition))
            self.coloring_count_cache[condition_key] = count
        else:
            self.stats.coloring_cache_hits += 1
        self.stats.coloring_seconds += time.perf_counter() - started
        return (
            int(term["coeff"])
            * self.source_web_sign
            * int(terminal_orientation)
            * count
        )

    def _move_score(
        self, term: Mapping[str, Any], move: Mapping[str, Any]
    ) -> Tuple[int, int, int, int]:
        children = self._expand(term, move)
        killed = 0
        remaining = 0
        black = 0
        nodes = 0
        for child in children:
            if self._discharge(child) is not None:
                killed += 1
            remaining += len(child["x_remaining"])
            black += sum(
                1
                for node in child["x_adj"]
                if int(node) not in self.x_bounds
                and self.x_colors.get(int(node)) == "black"
            )
            nodes += len(child["x_adj"])
        relation_priority = {
            "figure43": 2,
            "wrench": 1,
            "antisymmetrizer": 0,
        }[str(move["relation"])]
        return (killed, -remaining - black, -nodes, relation_priority)

    def _choose_move(
        self, term: Mapping[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
        moves = self._moves(term)
        if not moves:
            return None, None
        if not self.lookahead or len(moves) == 1:
            for move in moves:
                try:
                    return move, self._expand(term, move)
                except ValueError:
                    # Production's fixed-order evaluator also skips a local
                    # move whose current ports no longer support the rewrite.
                    continue
            return None, None
        scored = []
        for index, move in enumerate(moves):
            try:
                score = self._move_score(term, move)
            except ValueError:
                continue
            scored.append((score, -index, move))
        if not scored:
            return None, None
        _score, _neg_index, best = max(scored, key=lambda item: (item[0], item[1]))
        return best, self._expand(term, best)

    def evaluate(
        self,
        initial_term: Mapping[str, Any],
        *,
        max_moves: int = 500_000,
        deadline: Optional[float] = None,
    ) -> Dict[str, Any]:
        active: Dict[Key, Dict[str, Any]] = {}
        queue: Deque[Key] = deque()
        total_value = 0
        discharged_value = 0
        used_three_strand = False
        unresolved_details: List[Dict[str, Any]] = []

        def insert(term: Dict[str, Any]) -> None:
            nonlocal used_three_strand
            # Match the production runner: every branch is normalized before
            # it is keyed or expanded.  Earlier rewrites can leave one-sided
            # references that are intentionally removed at this boundary.
            term = self._normalize_active_term(term)
            coeff = int(term["coeff"])
            if coeff == 0:
                return
            used_three_strand = used_three_strand or any(
                move.get("phase") == "antisymmetrizer"
                or "3strand" in str(move.get("rule", "")).lower()
                or "three_strand" in str(move.get("rule", "")).lower()
                for move in term.get("history", [])
            )
            key = self.structural_key(term)
            previous = active.get(key)
            if previous is None:
                active[key] = term
                queue.append(key)
                self.stats.terms_inserted += 1
            else:
                self.stats.terms_merged += 1
                new_coeff = int(previous["coeff"]) + coeff
                if new_coeff == 0:
                    active.pop(key, None)
                    self.stats.terms_cancelled += 1
                else:
                    previous["coeff"] = new_coeff
            self.stats.max_active_terms = max(
                self.stats.max_active_terms, len(active)
            )

        insert(dict(initial_term))
        started = time.perf_counter()

        while queue and self.stats.moves < max_moves:
            if deadline is not None and time.perf_counter() >= deadline:
                break
            key = queue.popleft()
            term = active.pop(key, None)
            if term is None:
                continue
            discharged = self._discharge(term)
            if discharged is not None:
                self.stats.terms_discharged += 1
                continue
            if self._ready(term):
                value = self._color(term)
                if value is not None:
                    total_value += value
                    self.stats.terms_colored += 1
                    continue
            move, children = self._choose_move(term)
            if move is None or children is None:
                active[key] = term
                self.stats.unresolved_terms += 1
                unresolved_details.append(
                    {
                        "coefficient": int(term["coeff"]),
                        "remaining_hourglasses": len(term["x_remaining"]),
                        "internal_black_vertices": sum(
                            1
                            for node in term["x_adj"]
                            if int(node) not in self.x_bounds
                            and self.x_colors.get(int(node)) == "black"
                        ),
                        "node_count": len(term["x_adj"]),
                        "history_length": len(term.get("history", [])),
                        "reason": "no_applicable_certified_relation",
                    }
                )
                continue
            self.stats.moves += 1
            self.stats.children_generated += len(children)
            for child in children:
                insert(child)

        status = "completed" if not active and not queue else "partial"
        lemma49_stats = None
        if self.compiled_lemma49_matcher is not None:
            lemma49_stats = asdict(self.compiled_lemma49_matcher.stats)
        return {
            "status": status,
            "final_pairing_value": total_value if status == "completed" else None,
            "used_three_strand_relation": used_three_strand,
            "active_term_count": len(active),
            "discharged_term_count": self.stats.terms_discharged,
            "unresolved_details": unresolved_details,
            "elapsed_sec": time.perf_counter() - started,
            "stats": asdict(self.stats),
            "lemma49_matcher_stats": lemma49_stats,
        }


def make_initial_term(
    x_adj: Any,
    x_hourglasses: Any,
    w_adj: Any,
    w_hourglasses: Any,
) -> Dict[str, Any]:
    return {
        "x_adj": x_adj,
        "x_remaining": x_hourglasses,
        "w_adj": w_adj,
        "w_remaining": w_hourglasses,
        "coeff": 1,
        "history": [],
    }
