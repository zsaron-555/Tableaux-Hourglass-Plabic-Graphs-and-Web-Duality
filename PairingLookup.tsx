"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type Adj = Record<string, number[] | { top: number; bot: number }>;
type Hourglass = {
  white: number;
  black: number;
  left: number;
  right: number;
  leftTop: number;
  leftBot: number;
  rightTop: number;
  rightBot: number;
  localCase: string;
};
type Graph = {
  index: number;
  word: string;
  nodes: Map<number, { x: number; y: number; color: number }>;
  boundary: Record<string, number>;
  labelToNode: Record<string, number>;
  adj: Adj;
  hourglasses: Hourglass[];
};
type SurvivorRow = {
  wIndex: number;
  wWord: string;
  nPairs: number;
  nOrbits: number;
  forks: number[];
  words: string[];
};
type CoreData = {
  graphs: unknown[];
  survivors: unknown[];
  orbits: [number, string[]][];
  transposeByRep: Record<string, string>;
  meta: { graphCount: number; survivorRows: number };
};
type CoreIndex = {
  graphByWord: Map<string, Graph>;
  graphByIndex: Map<string, Graph>;
  survivorByRep: Map<string, SurvivorRow>;
  survivorByIndex: Map<string, SurvivorRow>;
  orbitByIndex: Map<number, string[]>;
  repByWord: Map<string, { index: number; pos: number }>;
  transposeByRep: Record<string, string>;
  meta: { graphCount: number; survivorRows: number };
};
type Term = {
  xAdj: Adj;
  xRemaining: Hourglass[];
  wAdj: Adj;
  wRemaining: Hourglass[];
  coeff: number;
  history: Move[];
};
type Move = {
  side: "X" | "W";
  hourglass: [number, number];
  smoothing: "crossing" | "parallel";
  coefficientMultiplier: number;
  localCase: string;
};
type State = {
  active: Term[];
  discharged: { coeff: number; commonForks: number[][]; history: Move[]; reason: string }[];
  score: number[];
  expandedSide?: "X" | "W";
  expandedHourglass?: [number, number];
  createdForks?: number[][];
  activeBranchCount?: number;
  dischargedBranchCount?: number;
};
type Evaluation = {
  status: string;
  reason?: string;
  sourceSide?: string;
  boundaryColorByLabel?: Record<string, number>;
  coloringCount?: number;
  wExpansionStatus?: string;
  wExpandedLeaves?: number;
  wForkKilledLeaves?: number;
  wDirectColoredLeaves?: number;
  coeff?: number;
  termValue?: number | null;
  history?: Move[];
};
type Proof = {
  status: string;
  steps: Record<string, unknown>[];
  dischargedTerms: State["discharged"];
  activeTerms: ReturnType<typeof pairActiveTermSummary>[];
  activeTermCount: number;
  dischargedTermCount: number;
  coloringEvaluations: Evaluation[];
  finalPairingValue: number | null;
};

const DEFAULT_W = "0447_1231423121323444.json";
const DEFAULT_X = "0447_1112122334344234.json";
const DEFAULT_REP = "447";

function decodeGraph(row: any[]): Graph {
  const nodes = new Map<number, { x: number; y: number; color: number }>();
  for (const node of row[2]) nodes.set(node[0], { x: node[1], y: node[2], color: node[3] });
  const boundary: Record<string, number> = {};
  const labelToNode: Record<string, number> = {};
  for (const [node, label] of row[3]) {
    boundary[String(node)] = label;
    labelToNode[String(label)] = node;
  }
  const adj: Adj = {};
  for (const entry of row[4]) {
    if (entry[1] === "h") adj[String(entry[0])] = { top: entry[2], bot: entry[3] };
    else adj[String(entry[0])] = entry.slice(1);
  }
  return {
    index: row[0],
    word: row[1],
    nodes,
    boundary,
    labelToNode,
    adj,
    hourglasses: row[5].map((hg: any[]) => ({
      white: hg[0],
      black: hg[1],
      left: hg[2],
      right: hg[3],
      leftTop: hg[4],
      leftBot: hg[5],
      rightTop: hg[6],
      rightBot: hg[7],
      localCase: hg[9] || "",
    })),
  };
}

function buildCoreIndex(data: CoreData): CoreIndex {
  const graphByWord = new Map<string, Graph>();
  const graphByIndex = new Map<string, Graph>();
  for (const row of data.graphs as any[]) {
    const graph = decodeGraph(row);
    graphByWord.set(graph.word, graph);
    graphByIndex.set(String(graph.index), graph);
  }
  const survivorByRep = new Map<string, SurvivorRow>();
  const survivorByIndex = new Map<string, SurvivorRow>();
  for (const row of data.survivors as any[]) {
    const survivor = {
      wIndex: row[0],
      wWord: row[1],
      nPairs: row[2],
      nOrbits: row[3],
      forks: row[4],
      words: row[5],
    };
    survivorByRep.set(survivor.wWord, survivor);
    survivorByIndex.set(String(survivor.wIndex), survivor);
  }
  const orbitByIndex = new Map<number, string[]>();
  const repByWord = new Map<string, { index: number; pos: number }>();
  for (const [index, words] of data.orbits) {
    orbitByIndex.set(index, words);
    words.forEach((word, pos) => repByWord.set(word, { index, pos }));
  }
  return {
    graphByWord,
    graphByIndex,
    survivorByRep,
    survivorByIndex,
    orbitByIndex,
    repByWord,
    transposeByRep: data.transposeByRep,
    meta: data.meta,
  };
}

function cleanInput(value: string) {
  return value.trim();
}

function wordFromInput(value: string) {
  const input = cleanInput(value);
  if (input.endsWith(".json") && input.includes("_")) return input.replace(/\.json$/, "").split("_").slice(1).join("_");
  if (input.includes("_")) return input.split("_").slice(1).join("_").replace(/\.json$/, "");
  return input;
}

function resolveGraph(index: CoreIndex, value: string, fallback: string): Graph {
  const input = cleanInput(value) || fallback;
  if (/^\d+$/.test(input) && index.graphByIndex.has(String(Number(input)))) {
    return index.graphByIndex.get(String(Number(input)))!;
  }
  const word = wordFromInput(input);
  const graph = index.graphByWord.get(word);
  if (!graph) throw new Error(`Could not find graph for input: ${input}`);
  return graph;
}

function cloneAdj(adj: Adj): Adj {
  const out: Adj = {};
  for (const [node, neighbors] of Object.entries(adj)) {
    out[node] = Array.isArray(neighbors) ? [...neighbors] : { ...neighbors };
  }
  return out;
}

function neighborList(neighbors: number[] | { top: number; bot: number } | undefined) {
  if (!neighbors) return [];
  return Array.isArray(neighbors) ? neighbors : [neighbors.top, neighbors.bot].filter((x) => x != null);
}

function hourglassKey(hg: Hourglass): [number, number] {
  return hg.white < hg.black ? [hg.white, hg.black] : [hg.black, hg.white];
}

function remainingAfterMove(hourglasses: Hourglass[], moved: Hourglass) {
  const key = hourglassKey(moved).join(",");
  return hourglasses.filter((hg) => hourglassKey(hg).join(",") !== key);
}

function edgeTuple(adj: Adj) {
  const edges: string[] = [];
  for (const [uText, neighbors] of Object.entries(adj)) {
    const u = Number(uText);
    for (const v of neighborList(neighbors)) {
      if (u <= v) edges.push(`${u},${v}`);
    }
  }
  return edges.sort();
}

function edgeKey(u: number, v: number) {
  return u < v ? `${u},${v}` : `${v},${u}`;
}

function replaceNeighbor(adj: Adj, node: number, oldNeighbor: number, newNeighbor: number) {
  const key = String(node);
  const neighbors = adj[key];
  if (!neighbors) throw new Error(`Node ${node} is missing.`);
  if (Array.isArray(neighbors)) {
    let replaced = false;
    adj[key] = neighbors.map((n) => {
      if (n === oldNeighbor) {
        replaced = true;
        return newNeighbor;
      }
      return n;
    });
    if (replaced) return;
  } else {
    if (neighbors.top === oldNeighbor) {
      neighbors.top = newNeighbor;
      return;
    }
    if (neighbors.bot === oldNeighbor) {
      neighbors.bot = newNeighbor;
      return;
    }
  }
  throw new Error(`Node ${node} is not adjacent to ${oldNeighbor}.`);
}

function smoothOneHourglass(adj: Adj, hg: Hourglass, smoothing: "crossing" | "parallel") {
  const left = hg.left;
  const right = hg.right;
  const leftAdj = adj[String(left)] as { top: number; bot: number };
  const rightAdj = adj[String(right)] as { top: number; bot: number };
  const lt = leftAdj.top;
  const lb = leftAdj.bot;
  const rt = rightAdj.top;
  const rb = rightAdj.bot;
  const next = cloneAdj(adj);
  if (smoothing === "crossing") {
    replaceNeighbor(next, lt, left, rt);
    replaceNeighbor(next, rt, right, lt);
    replaceNeighbor(next, lb, left, rb);
    replaceNeighbor(next, rb, right, lb);
  } else {
    replaceNeighbor(next, lt, left, rb);
    replaceNeighbor(next, rb, right, lt);
    replaceNeighbor(next, lb, left, rt);
    replaceNeighbor(next, rt, right, lb);
  }
  delete next[String(left)];
  delete next[String(right)];
  return next;
}

function forkKey(pair: number[]) {
  return [...pair].sort((a, b) => a - b).join(",");
}

function getForks(adj: Adj, boundary: Record<string, number>) {
  const forks = new Set<string>();
  for (const [node, neighbors] of Object.entries(adj)) {
    if (boundary[node] != null) continue;
    if (!Array.isArray(neighbors)) continue;
    const labels = neighborList(neighbors)
      .filter((n) => boundary[String(n)] != null)
      .map((n) => boundary[String(n)]);
    for (let i = 0; i < labels.length; i += 1) {
      for (let j = i + 1; j < labels.length; j += 1) forks.add(forkKey([labels[i], labels[j]]));
    }
  }
  return forks;
}

function commonPairForks(xAdj: Adj, xBoundary: Record<string, number>, wAdj: Adj, wBoundary: Record<string, number>) {
  const xForks = getForks(xAdj, xBoundary);
  const wForks = getForks(wAdj, wBoundary);
  return [...xForks].filter((fork) => wForks.has(fork));
}

function dischargePairTerms(terms: Term[], xBoundary: Record<string, number>, wBoundary: Record<string, number>) {
  const active: Term[] = [];
  const discharged: State["discharged"] = [];
  for (const term of terms) {
    const common = commonPairForks(term.xAdj, xBoundary, term.wAdj, wBoundary);
    if (common.length) {
      discharged.push({
        coeff: term.coeff,
        commonForks: common.map((key) => key.split(",").map(Number)),
        history: term.history,
        reason: "fork_lemma",
      });
    } else active.push(term);
  }
  return { active, discharged };
}

function pairTermKey(term: Term) {
  return JSON.stringify([
    edgeTuple(term.xAdj),
    term.xRemaining.map(hourglassKey).sort(),
    edgeTuple(term.wAdj),
    term.wRemaining.map(hourglassKey).sort(),
  ]);
}

function consolidatePairTerms(terms: Term[]) {
  const map = new Map<string, Term>();
  for (const term of terms) {
    const key = pairTermKey(term);
    const old = map.get(key);
    if (old) old.coeff += term.coeff;
    else map.set(key, { ...term, history: [...term.history] });
  }
  return [...map.values()].filter((term) => term.coeff !== 0);
}

function expandPairTerm(term: Term, side: "X" | "W", hg: Hourglass) {
  return (["crossing", "parallel"] as const).map((smoothing) => {
    const mult = smoothing === "crossing" ? 1 : -1;
    const move = {
      side,
      hourglass: hourglassKey(hg),
      smoothing,
      coefficientMultiplier: mult,
      localCase: hg.localCase,
    };
    if (side === "X") {
      return {
        xAdj: smoothOneHourglass(term.xAdj, hg, smoothing),
        xRemaining: remainingAfterMove(term.xRemaining, hg),
        wAdj: term.wAdj,
        wRemaining: term.wRemaining,
        coeff: term.coeff * mult,
        history: [...term.history, move],
      };
    }
    return {
      xAdj: term.xAdj,
      xRemaining: term.xRemaining,
      wAdj: smoothOneHourglass(term.wAdj, hg, smoothing),
      wRemaining: remainingAfterMove(term.wRemaining, hg),
      coeff: term.coeff * mult,
      history: [...term.history, move],
    };
  });
}

function scorePairState(active: Term[], discharged: State["discharged"], xBoundary: Record<string, number>, wBoundary: Record<string, number>) {
  const remaining = active.reduce((sum, term) => sum + term.xRemaining.length + term.wRemaining.length, 0);
  const totalForks = active.length
    ? Math.max(...active.map((term) => getForks(term.xAdj, xBoundary).size + getForks(term.wAdj, wBoundary).size))
    : 0;
  return [discharged.length, -active.length, totalForks, -remaining];
}

function choosePairSuccessors(state: State, xBoundary: Record<string, number>, wBoundary: Record<string, number>, allowW: boolean) {
  const successors: State[] = [];
  state.active.forEach((term, termIndex) => {
    const choices: ["X" | "W", Hourglass][] = term.xRemaining.map((hg) => ["X", hg]);
    if (allowW) choices.push(...term.wRemaining.map((hg) => ["W" as const, hg] as ["W", Hourglass]));
    for (const [side, hg] of choices) {
      let children: Term[];
      try {
        children = expandPairTerm(term, side, hg);
      } catch {
        continue;
      }
      const nextTerms = consolidatePairTerms([...state.active.slice(0, termIndex), ...state.active.slice(termIndex + 1), ...children]);
      const { active, discharged } = dischargePairTerms(nextTerms, xBoundary, wBoundary);
      const nextDischarged = [...state.discharged, ...discharged];
      successors.push({
        active,
        discharged: nextDischarged,
        expandedSide: side,
        expandedHourglass: hourglassKey(hg),
        createdForks: discharged.flatMap((term) => term.commonForks),
        activeBranchCount: active.length,
        dischargedBranchCount: nextDischarged.length,
        score: scorePairState(active, nextDischarged, xBoundary, wBoundary),
      });
    }
  });
  return successors;
}

function graphComponents(adj: Adj) {
  const seen = new Set<string>();
  const comps: string[][] = [];
  for (const start of Object.keys(adj)) {
    if (seen.has(start)) continue;
    const stack = [start];
    const comp: string[] = [];
    seen.add(start);
    while (stack.length) {
      const node = stack.pop()!;
      comp.push(node);
      for (const neighbor of neighborList(adj[node])) {
        const key = String(neighbor);
        if (!seen.has(key) && adj[key]) {
          seen.add(key);
          stack.push(key);
        }
      }
    }
    comps.push(comp);
  }
  return comps;
}

function componentBoundaryConditionFromX(adj: Adj, boundary: Record<string, number>, r = 4) {
  const components: [number, number[]][] = [];
  for (const comp of graphComponents(adj)) {
    const labels = comp.filter((node) => boundary[node] != null).map((node) => boundary[node]).sort((a, b) => a - b);
    if (labels.length) components.push([labels[0], labels]);
  }
  if (components.length !== r) return null;
  components.sort((a, b) => a[0] - b[0]);
  const condition: Record<string, number> = {};
  components.forEach(([, labels], colorIndex) => labels.forEach((label) => (condition[String(label)] = colorIndex + 1)));
  return Object.keys(condition).length === r * r ? condition : null;
}

type ColoringStats = {
  count: number;
  edgeColors: Record<string, number>;
  hourglassColors: Record<string, number[]>;
};

function coloringStatsWithHourglasses(adj: Adj, boundary: Record<string, number>, condition: Record<string, number>, hourglasses: Hourglass[], r = 4): ColoringStats {
  const edges: { u: number; v: number; kind: "ordinary" | "hourglass"; key: string }[] = [];
  for (const [uText, neighbors] of Object.entries(adj)) {
    const u = Number(uText);
    for (const v of neighborList(neighbors)) if (u <= v) edges.push({ u, v, kind: "ordinary", key: edgeKey(u, v) });
  }
  for (const hg of hourglasses) {
    if (adj[String(hg.white)] && adj[String(hg.black)]) {
      const key = edgeKey(hg.white, hg.black);
      edges.push({ u: hg.white, v: hg.black, kind: "hourglass", key }, { u: hg.white, v: hg.black, kind: "hourglass", key });
    }
  }
  const incident: Record<string, number[]> = {};
  Object.keys(adj).forEach((node) => (incident[node] = []));
  const fixed = new Map<number, number>();
  edges.forEach(({ u, v }, idx) => {
    incident[String(u)].push(idx);
    incident[String(v)].push(idx);
    const uBoundary = boundary[String(u)];
    const vBoundary = boundary[String(v)];
    if (uBoundary != null || vBoundary != null) {
      const label = uBoundary ?? vBoundary;
      const color = condition[String(label)];
      if (!color) fixed.set(idx, -1);
      else fixed.set(idx, color);
    }
  });
  if ([...fixed.values()].includes(-1)) return { count: 0, edgeColors: {}, hourglassColors: {} };
  const colors = new Array(edges.length).fill(0);
  fixed.forEach((color, idx) => (colors[idx] = color));
  const internal = Object.keys(adj).filter((node) => boundary[node] == null);
  if (internal.some((node) => incident[node].length !== r)) return { count: 0, edgeColors: {}, hourglassColors: {} };
  const remaining = colors.map((_, idx) => idx).filter((idx) => !fixed.has(idx));
  remaining.sort((a, b) => {
    const ca = [edges[a].u, edges[a].v].filter((n) => boundary[String(n)] == null).length;
    const cb = [edges[b].u, edges[b].v].filter((n) => boundary[String(n)] == null).length;
    return cb - ca;
  });
  function possible(vertex: string) {
    const seen = new Set<number>();
    let unknown = 0;
    for (const idx of incident[vertex]) {
      const color = colors[idx];
      if (!color) unknown += 1;
      else if (seen.has(color)) return false;
      else seen.add(color);
    }
    return seen.size + unknown === r;
  }
  function complete(vertex: string) {
    return new Set(incident[vertex].map((idx) => colors[idx])).size === r && incident[vertex].every((idx) => colors[idx] >= 1 && colors[idx] <= r);
  }
  if (internal.some((vertex) => !possible(vertex))) return { count: 0, edgeColors: {}, hourglassColors: {} };
  let total = 0;
  let firstSolution: number[] | null = null;
  function backtrack(pos: number) {
    if (pos === remaining.length) {
      if (internal.every(complete)) {
        total += 1;
        if (!firstSolution) firstSolution = [...colors];
      }
      return;
    }
    const edgeIdx = remaining[pos];
    const endpoints = [edges[edgeIdx].u, edges[edgeIdx].v].map(String).filter((node) => boundary[node] == null);
    for (let color = 1; color <= r; color += 1) {
      colors[edgeIdx] = color;
      if (endpoints.every(possible)) backtrack(pos + 1);
      colors[edgeIdx] = 0;
    }
  }
  backtrack(0);
  const edgeColors: Record<string, number> = {};
  const hourglassColors: Record<string, number[]> = {};
  if (firstSolution) {
    edges.forEach((edge, idx) => {
      const color = firstSolution![idx];
      if (edge.kind === "ordinary") edgeColors[edge.key] = color;
      else {
        if (!hourglassColors[edge.key]) hourglassColors[edge.key] = [];
        hourglassColors[edge.key].push(color);
      }
    });
  }
  return { count: total, edgeColors, hourglassColors };
}

function countConsistentColorings(adj: Adj, boundary: Record<string, number>, condition: Record<string, number>, hourglasses: Hourglass[], r = 4) {
  return coloringStatsWithHourglasses(adj, boundary, condition, hourglasses, r).count;
}

function boundaryIncidentEdgeColors(adj: Adj, boundary: Record<string, number>, condition: Record<string, number>) {
  const edgeColors: Record<string, number> = {};
  for (const [uText, neighbors] of Object.entries(adj)) {
    const u = Number(uText);
    const uBoundary = boundary[uText];
    for (const v of neighborList(neighbors)) {
      if (u > v) continue;
      const vBoundary = boundary[String(v)];
      const label = uBoundary ?? vBoundary;
      if (label == null) continue;
      const color = condition[String(label)];
      if (color) edgeColors[edgeKey(u, v)] = color;
    }
  }
  return edgeColors;
}

function evaluatePairByXComponentColoring(term: Term, xBoundary: Record<string, number>, wBoundary: Record<string, number>) {
  if (term.xRemaining.length) return { status: "not_computed", reason: `X still has ${term.xRemaining.length} hourglass(es)` };
  const condition = componentBoundaryConditionFromX(term.xAdj, xBoundary);
  if (!condition) return { status: "not_computed", reason: "X does not have exactly four boundary-bearing connected components" };
  const count = countConsistentColorings(term.wAdj, wBoundary, condition, term.wRemaining);
  return { status: "computed", sourceSide: "X_components", boundaryColorByLabel: condition, coloringCount: count };
}

function evaluateStateByXComponentColoring(state: State, xBoundary: Record<string, number>, wBoundary: Record<string, number>) {
  let total = 0;
  const evaluations: Evaluation[] = [];
  for (const term of state.active) {
    const evaluation = evaluatePairByXComponentColoring(term, xBoundary, wBoundary) as Evaluation;
    evaluation.coeff = term.coeff;
    evaluation.history = term.history;
    if (evaluation.status !== "computed") {
      evaluation.termValue = null;
      return null;
    }
    evaluation.termValue = term.coeff * Number(evaluation.coloringCount);
    total += evaluation.termValue;
    evaluations.push(evaluation);
  }
  return { value: total, evaluations };
}

function evaluateTermByWExpansionThenColor(
  term: Term,
  xBoundary: Record<string, number>,
  wBoundary: Record<string, number>,
  maxWExpansionsPerBranch = 6,
) {
  if (term.xRemaining.length) {
    return { status: "not_computed", reason: `X still has ${term.xRemaining.length} hourglass(es)` } as Evaluation;
  }
  const condition = componentBoundaryConditionFromX(term.xAdj, xBoundary);
  if (!condition) {
    return { status: "not_computed", reason: "X does not have exactly four boundary-bearing connected components" } as Evaluation;
  }

  type WStackTerm = {
    wAdj: Adj;
    wRemaining: Hourglass[];
    coeff: number;
    history: Move[];
    expansions: number;
  };
  const stack: WStackTerm[] = [{ wAdj: term.wAdj, wRemaining: term.wRemaining, coeff: term.coeff, history: term.history, expansions: 0 }];
  let value = 0;
  let expandedLeaves = 0;
  let forkKilledLeaves = 0;
  let directColoredLeaves = 0;
  let firstComputed: Evaluation | null = null;

  while (stack.length) {
    const current = stack.pop()!;
    const common = commonPairForks(term.xAdj, xBoundary, current.wAdj, wBoundary);
    if (common.length) {
      forkKilledLeaves += 1;
      continue;
    }

    if (current.wRemaining.length && current.expansions < maxWExpansionsPerBranch) {
      const hg = current.wRemaining[0];
      for (const smoothing of ["crossing", "parallel"] as const) {
        try {
          const mult = smoothing === "crossing" ? 1 : -1;
          const move: Move = {
            side: "W",
            hourglass: hourglassKey(hg),
            smoothing,
            coefficientMultiplier: mult,
            localCase: hg.localCase,
          };
          stack.push({
            wAdj: smoothOneHourglass(current.wAdj, hg, smoothing),
            wRemaining: remainingAfterMove(current.wRemaining, hg),
            coeff: current.coeff * mult,
            history: [...current.history, move],
            expansions: current.expansions + 1,
          });
        } catch {
          // Skip invalid local smoothings; the other branch may still be valid.
        }
      }
      continue;
    }

    const stats = coloringStatsWithHourglasses(current.wAdj, wBoundary, condition, current.wRemaining);
    const termValue = current.coeff * stats.count;
    value += termValue;
    if (current.wRemaining.length) directColoredLeaves += 1;
    else expandedLeaves += 1;
    if (!firstComputed) {
      firstComputed = {
        status: "computed",
        sourceSide: "X_components",
        boundaryColorByLabel: condition,
        coloringCount: stats.count,
        coeff: current.coeff,
        termValue,
        history: current.history,
        wExpansionStatus: current.wRemaining.length ? "direct_w_coloring_with_hourglasses" : "expanded_w_then_colored",
        wExpandedLeaves: expandedLeaves,
        wForkKilledLeaves: forkKilledLeaves,
        wDirectColoredLeaves: directColoredLeaves,
      };
    }
  }

  return {
    status: "computed",
    sourceSide: "X_components",
    boundaryColorByLabel: condition,
    coloringCount: value / Math.max(1, term.coeff),
    coeff: term.coeff,
    termValue: value,
    history: firstComputed?.history ?? term.history,
    wExpansionStatus: directColoredLeaves ? "computed_after_w_expansion_with_direct_w_fallback" : "computed_after_w_expansion",
    wExpandedLeaves: expandedLeaves,
    wForkKilledLeaves: forkKilledLeaves,
    wDirectColoredLeaves: directColoredLeaves,
  } as Evaluation;
}

function evaluateStateByWExpansionThenColor(state: State, xBoundary: Record<string, number>, wBoundary: Record<string, number>) {
  let total = 0;
  const evaluations: Evaluation[] = [];
  for (const term of state.active) {
    const evaluation = evaluateTermByWExpansionThenColor(term, xBoundary, wBoundary);
    if (evaluation.status !== "computed") {
      evaluation.termValue = null;
      return null;
    }
    total += Number(evaluation.termValue ?? 0);
    evaluations.push(evaluation);
  }
  return { value: total, evaluations };
}

function hasXHourglasses(state: State) {
  return state.active.some((term) => term.xRemaining.length > 0);
}

function chooseXResolutionSuccessors(state: State, xBoundary: Record<string, number>, wBoundary: Record<string, number>) {
  const successors: State[] = [];
  state.active.forEach((term, termIndex) => {
    for (const hg of term.xRemaining) {
      let children: Term[];
      try {
        children = expandPairTerm(term, "X", hg);
      } catch {
        continue;
      }
      const nextTerms = consolidatePairTerms([...state.active.slice(0, termIndex), ...state.active.slice(termIndex + 1), ...children]);
      const { active, discharged } = dischargePairTerms(nextTerms, xBoundary, wBoundary);
      const nextDischarged = [...state.discharged, ...discharged];
      successors.push({
        active,
        discharged: nextDischarged,
        expandedSide: "X",
        expandedHourglass: hourglassKey(hg),
        createdForks: discharged.flatMap((term) => term.commonForks),
        activeBranchCount: active.length,
        dischargedBranchCount: nextDischarged.length,
        score: scorePairState(active, nextDischarged, xBoundary, wBoundary),
      });
    }
  });
  return successors;
}

function pairActiveTermSummary(term: Term, xBoundary: Record<string, number>, wBoundary: Record<string, number>) {
  return {
    coeff: term.coeff,
    commonForks: commonPairForks(term.xAdj, xBoundary, term.wAdj, wBoundary).map((key) => key.split(",").map(Number)),
    xRemainingHourglasses: term.xRemaining.length,
    wRemainingHourglasses: term.wRemaining.length,
    history: term.history,
  };
}

function provePairValueByXComponentColoring(x: Graph, w: Graph, allowW: boolean, beamWidth: number, guidedStepsInput: number | null): Proof {
  const initialRemaining = x.hourglasses.length + (allowW ? w.hourglasses.length : 0);
  const guidedSteps = guidedStepsInput ?? Math.max(80, 8 * Math.max(1, initialRemaining));
  const xResolutionSteps = Math.max(80, 10 * Math.max(1, x.hourglasses.length));
  const initialTerms: Term[] = [{ xAdj: cloneAdj(x.adj), xRemaining: x.hourglasses, wAdj: cloneAdj(w.adj), wRemaining: w.hourglasses, coeff: 1, history: [] }];
  const dischargedInitial = dischargePairTerms(initialTerms, x.boundary, w.boundary);
  let beam: State[] = [{ active: dischargedInitial.active, discharged: dischargedInitial.discharged, score: scorePairState(dischargedInitial.active, dischargedInitial.discharged, x.boundary, w.boundary) }];
  let bestState = beam[0];
  const steps: Record<string, unknown>[] = [];

  for (let step = 0; step < guidedSteps; step += 1) {
    const zeroState = beam.find((state) => state.active.length === 0);
    if (zeroState) {
      bestState = zeroState;
      return proofFromState(bestState, x, w, steps, "proved_zero", 0, []);
    }
    const candidates = beam.flatMap((state) => choosePairSuccessors(state, x.boundary, w.boundary, allowW));
    if (!candidates.length) break;
    candidates.sort((a, b) => compareScore(b.score, a.score));
    beam = candidates.slice(0, beamWidth);
    bestState = beam[0];
    steps.push({
      phase: "guided",
      step: step + 1,
      activeTerms: bestState.active.length,
      dischargedTerms: bestState.discharged.length,
      expandedSide: bestState.expandedSide,
      expandedHourglass: bestState.expandedHourglass,
      createdForks: bestState.createdForks ?? [],
      activeBranchesKept: bestState.activeBranchCount ?? bestState.active.length,
      branchesForkKilled: bestState.dischargedBranchCount ?? bestState.discharged.length,
    });
  }

  for (let step = 0; step <= xResolutionSteps; step += 1) {
    for (const state of beam) {
      if (!state.active.length) return proofFromState(state, x, w, steps, "proved_zero", 0, []);
      if (!hasXHourglasses(state)) {
        const evaluated = evaluateStateByXComponentColoring(state, x.boundary, w.boundary) ?? evaluateStateByWExpansionThenColor(state, x.boundary, w.boundary);
        if (evaluated) {
          const usedWExpansion = evaluated.evaluations.some((evaluation) => evaluation.wExpansionStatus);
          return proofFromState(state, x, w, steps, usedWExpansion ? "evaluated_after_w_expansion_coloring" : "evaluated_by_x_component_coloring", evaluated.value, evaluated.evaluations);
        }
      }
    }
    if (step === xResolutionSteps) break;
    const candidates = beam.flatMap((state) => chooseXResolutionSuccessors(state, x.boundary, w.boundary));
    if (!candidates.length) break;
    candidates.sort((a, b) => compareScore(xResolutionScore(b), xResolutionScore(a)));
    beam = candidates.slice(0, beamWidth);
    bestState = beam[0];
    steps.push({
      phase: "resolve_x",
      step: step + 1,
      activeTerms: bestState.active.length,
      dischargedTerms: bestState.discharged.length,
      expandedSide: bestState.expandedSide,
      expandedHourglass: bestState.expandedHourglass,
      createdForks: bestState.createdForks ?? [],
      activeBranchesKept: bestState.activeBranchCount ?? bestState.active.length,
      branchesForkKilled: bestState.dischargedBranchCount ?? bestState.discharged.length,
      xRemainingHourglasses: bestState.active.reduce((sum, term) => sum + term.xRemaining.length, 0),
      wRemainingHourglasses: bestState.active.reduce((sum, term) => sum + term.wRemaining.length, 0),
    });
  }

  return proofFromState(bestState, x, w, steps, "partial", null, []);
}

function proofFromState(state: State, x: Graph, w: Graph, steps: Record<string, unknown>[], status: string, value: number | null, evaluations: Evaluation[]): Proof {
  return {
    status,
    steps,
    dischargedTerms: state.discharged,
    activeTerms: state.active.map((term) => pairActiveTermSummary(term, x.boundary, w.boundary)),
    activeTermCount: state.active.length,
    dischargedTermCount: state.discharged.length,
    coloringEvaluations: evaluations,
    finalPairingValue: value,
  };
}

function compareScore(a: number[], b: number[]) {
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const diff = (a[i] ?? 0) - (b[i] ?? 0);
    if (diff) return diff;
  }
  return 0;
}

function xResolutionScore(state: State) {
  const xRemaining = state.active.reduce((sum, term) => sum + term.xRemaining.length, 0);
  const wRemaining = state.active.reduce((sum, term) => sum + term.wRemaining.length, 0);
  return [xRemaining === 0 ? 1 : 0, -xRemaining, state.discharged.length, -state.active.length, -wRemaining];
}

function shiftedSurvivorWords(index: CoreIndex, row: SurvivorRow, enteredW: Graph) {
  const rep = index.repByWord.get(enteredW.word);
  const shift = rep?.index === row.wIndex ? rep.pos : 0;
  if (!shift) return row.words;
  return row.words.map((word) => {
    const info = index.repByWord.get(word);
    const orbit = info ? index.orbitByIndex.get(info.index) : null;
    return orbit ? orbit[(info!.pos + shift) % orbit.length] : word;
  });
}

function survivorWordsForW(index: CoreIndex, wInput: string) {
  const wGraph = resolveGraph(index, wInput, DEFAULT_W);
  const rep = index.repByWord.get(wGraph.word);
  const row = rep ? index.survivorByIndex.get(String(rep.index)) : index.survivorByRep.get(wGraph.word);
  if (!row) return { wGraph, row: null, words: [] as string[], removed: 0, forks: [] as number[][] };
  const wForks = getForks(wGraph.adj, wGraph.boundary);
  const shifted = shiftedSurvivorWords(index, row, wGraph);
  const words: string[] = [];
  let removed = 0;
  for (const word of shifted) {
    const graph = index.graphByWord.get(word);
    if (!graph) continue;
    const xForks = getForks(graph.adj, graph.boundary);
    const common = [...xForks].some((fork) => wForks.has(fork));
    if (common) removed += 1;
    else words.push(word);
  }
  const forks = [...wForks].map((fork) => fork.split(",").map(Number));
  return { wGraph, row, words, removed, forks };
}

function resolveShortcut(index: CoreIndex, repInput: string) {
  const repGraph = resolveGraph(index, repInput, DEFAULT_X);
  const rep = index.repByWord.get(repGraph.word);
  const repIndex = rep?.index ?? repGraph.index;
  const orbit = index.orbitByIndex.get(repIndex);
  const xWord = orbit?.[0] ?? repGraph.word;
  const wWord = index.transposeByRep[String(repIndex)];
  if (!wWord) throw new Error(`No transpose word found for representative ${repIndex}.`);
  return { xWord, wWord };
}

type WebDrawOptions = {
  edgeColors?: Record<string, number>;
  hourglassColors?: Record<string, number[]>;
  boundaryColorByLabel?: Record<string, number>;
  nodeColorById?: Record<string, number>;
  highlightHourglass?: [number, number];
  highlightForks?: number[][];
  subtitle?: string;
};

type BranchDisplayStep = {
  side: "X" | "W";
  selected: [number, number];
  continueMove: Move;
  killedMove: Move;
  killedForks: number[][];
  killedCoeff: number | string;
  siblingStatus: "fork-killed" | "kept-active";
  currentX: Adj;
  currentW: Adj;
  currentXRemaining: Hourglass[];
  currentWRemaining: Hourglass[];
  killedX: Adj;
  killedW: Adj;
  killedXRemaining: Hourglass[];
  killedWRemaining: Hourglass[];
  killedNewX: Set<string>;
  killedNewW: Set<string>;
  continueX: Adj;
  continueW: Adj;
  continueXRemaining: Hourglass[];
  continueWRemaining: Hourglass[];
  continueNewX: Set<string>;
  continueNewW: Set<string>;
};

type ReplaySnapshot = {
  move: Move;
  step: number;
  beforeX: Adj;
  beforeXRemaining: Hourglass[];
  beforeW: Adj;
  beforeWRemaining: Hourglass[];
  afterX: Adj;
  afterXRemaining: Hourglass[];
  afterW: Adj;
  afterWRemaining: Hourglass[];
  commonForksAfter: number[][];
};

function toSvgPoint(point: { x: number; y: number }) {
  const scale = 330 * 0.39;
  return { x: 165 + scale * point.x, y: 165 - scale * point.y };
}

function hourglassPaths(a: { x: number; y: number }, b: { x: number; y: number }) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy);
  if (!length) return [];
  const ux = dx / length;
  const uy = dy / length;
  const px = -uy;
  const py = ux;
  const amp = Math.min(12.8, length * 0.42);
  const inset = 0.27 * length;
  return [
    `M ${a.x} ${a.y} C ${a.x + ux * inset + px * amp} ${a.y + uy * inset + py * amp}, ${b.x - ux * inset - px * amp} ${b.y - uy * inset - py * amp}, ${b.x} ${b.y}`,
    `M ${a.x} ${a.y} C ${a.x + ux * inset - px * amp} ${a.y + uy * inset - py * amp}, ${b.x - ux * inset + px * amp} ${b.y - uy * inset + py * amp}, ${b.x} ${b.y}`,
  ];
}

function findHourglass(remaining: Hourglass[], target: [number, number]) {
  const targetKey = target.join(",");
  return remaining.find((hg) => hourglassKey(hg).join(",") === targetKey);
}

function forkHighlightsFor(adj: Adj, boundary: Record<string, number>, forks: number[][]) {
  const highlights: { labels: number[]; center: number; boundaryNodes: number[] }[] = [];
  const seen = new Set<string>();
  for (const fork of forks) {
    if (fork.length !== 2) continue;
    const labels = [...fork].sort((a, b) => a - b);
    for (const [nodeText, neighbors] of Object.entries(adj)) {
      if (boundary[nodeText] != null || !Array.isArray(neighbors)) continue;
      const center = Number(nodeText);
      const labelToNode = new Map<number, number>();
      for (const neighbor of neighbors) {
        const label = boundary[String(neighbor)];
        if (label != null && !labelToNode.has(label)) labelToNode.set(label, neighbor);
      }
      const first = labelToNode.get(labels[0]);
      const second = labelToNode.get(labels[1]);
      if (first == null || second == null) continue;
      const key = `${center}|${labels.join(",")}`;
      if (seen.has(key)) continue;
      seen.add(key);
      highlights.push({ labels, center, boundaryNodes: [first, second] });
    }
  }
  return highlights;
}

function replayMoveSnapshots(xGraph: Graph, wGraph: Graph, history: Move[]) {
  let xAdj = cloneAdj(xGraph.adj);
  let wAdj = cloneAdj(wGraph.adj);
  let xRemaining = [...xGraph.hourglasses];
  let wRemaining = [...wGraph.hourglasses];
  const snapshots: ReplaySnapshot[] = [];
  history.forEach((move, idx) => {
    const beforeX = cloneAdj(xAdj);
    const beforeW = cloneAdj(wAdj);
    const beforeXRemaining = [...xRemaining];
    const beforeWRemaining = [...wRemaining];
    const remaining = move.side === "X" ? xRemaining : wRemaining;
    const hg = findHourglass(remaining, move.hourglass);
    if (hg) {
      if (move.side === "X") {
        xAdj = smoothOneHourglass(xAdj, hg, move.smoothing);
        xRemaining = remainingAfterMove(xRemaining, hg);
      } else {
        wAdj = smoothOneHourglass(wAdj, hg, move.smoothing);
        wRemaining = remainingAfterMove(wRemaining, hg);
      }
    }
    snapshots.push({
      move,
      step: idx + 1,
      beforeX,
      beforeXRemaining,
      beforeW,
      beforeWRemaining,
      afterX: cloneAdj(xAdj),
      afterXRemaining: [...xRemaining],
      afterW: cloneAdj(wAdj),
      afterWRemaining: [...wRemaining],
      commonForksAfter: commonPairForks(xAdj, xGraph.boundary, wAdj, wGraph.boundary).map((key) => key.split(",").map(Number)),
    });
  });
  return snapshots;
}

function replayFinalState(xGraph: Graph, wGraph: Graph, history: Move[]) {
  const snapshots = replayMoveSnapshots(xGraph, wGraph, history);
  const last = snapshots.at(-1);
  return {
    xAdj: last?.afterX ?? cloneAdj(xGraph.adj),
    xRemaining: last?.afterXRemaining ?? [...xGraph.hourglasses],
    wAdj: last?.afterW ?? cloneAdj(wGraph.adj),
    wRemaining: last?.afterWRemaining ?? [...wGraph.hourglasses],
  };
}

function nodeColorsFromBoundaryCondition(adj: Adj, boundary: Record<string, number>, condition: Record<string, number>) {
  const nodeColors: Record<string, number> = {};
  for (const comp of graphComponents(adj)) {
    const color = comp.map((node) => boundary[node]).find((label) => label != null && condition[String(label)]);
    if (color != null) {
      comp.forEach((node) => {
        if (boundary[node] != null) nodeColors[node] = condition[String(color)];
      });
    }
  }
  return nodeColors;
}

function edgeKeySet(adj: Adj) {
  return new Set(edgeTuple(adj).map((edge) => edge));
}

function blueEdgeColors(edges: Set<string>) {
  const out: Record<string, number> = {};
  edges.forEach((edge) => (out[edge] = 2));
  return out;
}

function moveKey(move: Move) {
  return `${move.side}|${edgeKey(move.hourglass[0], move.hourglass[1])}|${move.smoothing}`;
}

function sameHistoryPrefix(history: Move[], prefix: Move[]) {
  if (history.length < prefix.length) return false;
  return prefix.every((move, idx) => moveKey(history[idx]) === moveKey(move));
}

function sameHourglassMove(a: Move, b: Move) {
  return a.side === b.side && edgeKey(a.hourglass[0], a.hourglass[1]) === edgeKey(b.hourglass[0], b.hourglass[1]);
}

function oppositeSmoothing(smoothing: Move["smoothing"]): Move["smoothing"] {
  return smoothing === "crossing" ? "parallel" : "crossing";
}

function reconstructBranchDisplaySteps(xGraph: Graph, wGraph: Graph, proof: Proof): BranchDisplayStep[] {
  const displayHistory =
    proof.coloringEvaluations[0]?.history?.length
      ? proof.coloringEvaluations[0].history!
      : proof.activeTerms[0]?.history?.length
        ? proof.activeTerms[0].history
        : proof.dischargedTerms.reduce<Move[]>((longest, term) => (term.history.length > longest.length ? term.history : longest), []);
  let currentX = cloneAdj(xGraph.adj);
  let currentW = cloneAdj(wGraph.adj);
  let currentXRemaining = [...xGraph.hourglasses];
  let currentWRemaining = [...wGraph.hourglasses];
  const steps: BranchDisplayStep[] = [];

  displayHistory.forEach((continueMove, idx) => {
    const selected = [Math.min(...continueMove.hourglass), Math.max(...continueMove.hourglass)] as [number, number];
    const side = continueMove.side;
    const hgs = side === "X" ? currentXRemaining : currentWRemaining;
    const hg = findHourglass(hgs, selected);
    if (!hg) return;
    const prefix = displayHistory.slice(0, idx);
    const killed = proof.dischargedTerms.find((term) => {
      if (term.history.length !== prefix.length + 1) return false;
      if (!sameHistoryPrefix(term.history, prefix)) return false;
      const move = term.history.at(-1);
      return !!move && sameHourglassMove(move, continueMove) && move.smoothing !== continueMove.smoothing;
    });
    const killedMove =
      killed?.history.at(-1) ??
      ({
        ...continueMove,
        smoothing: oppositeSmoothing(continueMove.smoothing),
        coefficientMultiplier: -continueMove.coefficientMultiplier,
      } as Move);

    function branch(smoothing: Move["smoothing"]) {
      if (side === "X") {
        const nextX = smoothOneHourglass(currentX, hg, smoothing);
        const nextXRemaining = remainingAfterMove(currentXRemaining, hg);
        const before = edgeKeySet(currentX);
        const after = edgeKeySet(nextX);
        return {
          xAdj: nextX,
          wAdj: currentW,
          xRemaining: nextXRemaining,
          wRemaining: currentWRemaining,
          newX: new Set([...after].filter((edge) => !before.has(edge))),
          newW: new Set<string>(),
        };
      }
      const nextW = smoothOneHourglass(currentW, hg, smoothing);
      const nextWRemaining = remainingAfterMove(currentWRemaining, hg);
      const before = edgeKeySet(currentW);
      const after = edgeKeySet(nextW);
      return {
        xAdj: currentX,
        wAdj: nextW,
        xRemaining: currentXRemaining,
        wRemaining: nextWRemaining,
        newX: new Set<string>(),
        newW: new Set([...after].filter((edge) => !before.has(edge))),
      };
    }

    const killedBranch = branch(killedMove.smoothing);
    const continueBranch = branch(continueMove.smoothing);
    steps.push({
      side,
      selected,
      continueMove,
      killedMove,
      killedForks: killed?.commonForks ?? [],
      killedCoeff: killed?.coeff ?? "",
      siblingStatus: killed ? "fork-killed" : "kept-active",
      currentX,
      currentW,
      currentXRemaining,
      currentWRemaining,
      killedX: killedBranch.xAdj,
      killedW: killedBranch.wAdj,
      killedXRemaining: killedBranch.xRemaining,
      killedWRemaining: killedBranch.wRemaining,
      killedNewX: killedBranch.newX,
      killedNewW: killedBranch.newW,
      continueX: continueBranch.xAdj,
      continueW: continueBranch.wAdj,
      continueXRemaining: continueBranch.xRemaining,
      continueWRemaining: continueBranch.wRemaining,
      continueNewX: continueBranch.newX,
      continueNewW: continueBranch.newW,
    });
    currentX = continueBranch.xAdj;
    currentW = continueBranch.wAdj;
    currentXRemaining = continueBranch.xRemaining;
    currentWRemaining = continueBranch.wRemaining;
  });
  return steps;
}

function drawMiniSvg(graph: Graph, adj: Adj, remaining: Hourglass[], title: string, options: WebDrawOptions = {}) {
  const colors = ["", "#df454f", "#2586d8", "#23a267", "#9958be"];
  const wrenchColor = "#f000d8";
  const forkColor = "#f28e2b";
  const edges = edgeTuple(adj).map((edge) => edge.split(",").map(Number));
  const remainingKeys = new Set(remaining.map((hg) => hourglassKey(hg).join(",")));
  const highlightKey = options.highlightHourglass ? edgeKey(options.highlightHourglass[0], options.highlightHourglass[1]) : "";
  const forkHighlights = forkHighlightsFor(adj, graph.boundary, options.highlightForks ?? []);
  const forkLabelNodes = new Set(forkHighlights.flatMap((fork) => fork.boundaryNodes));
  const forkCenterNodes = new Set(forkHighlights.map((fork) => fork.center));
  const forkEdges = new Set(forkHighlights.flatMap((fork) => fork.boundaryNodes.map((node) => edgeKey(fork.center, node))));
  const selectedWrenchEdges = new Set<string>();
  const selectedWrenchNodes = new Set<number>();
  if (highlightKey) {
    const hg = findHourglass(remaining, options.highlightHourglass!);
    if (hg) {
      selectedWrenchNodes.add(hg.white);
      selectedWrenchNodes.add(hg.black);
      for (const endpoint of [hg.white, hg.black]) {
        for (const neighbor of neighborList(adj[String(endpoint)])) {
          selectedWrenchEdges.add(edgeKey(endpoint, neighbor));
          selectedWrenchNodes.add(neighbor);
        }
      }
    }
  }
  return (
    <div className="web-card">
      <div className="web-title">{title}</div>
      {options.subtitle ? <div className="web-subtitle">{options.subtitle}</div> : null}
      <svg viewBox="0 0 330 330" width="330" height="330">
        <circle cx="165" cy="165" r={330 * 0.39} fill="none" stroke="#111" strokeWidth="2" />
        {edges.map(([u, v]) => {
          const a = graph.nodes.get(u);
          const b = graph.nodes.get(v);
          if (!a || !b) return null;
          const pa = toSvgPoint(a);
          const pb = toSvgPoint(b);
          const key = edgeKey(u, v);
          const color = options.edgeColors?.[key];
          const selected = selectedWrenchEdges.has(key);
          return <line key={`${u}-${v}`} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke={selected ? wrenchColor : typeof color === "number" ? colors[color] : "#111"} strokeWidth={selected ? 5 : color ? 4 : 2} strokeLinecap="round" />;
        })}
        {edges.map(([u, v]) => {
          const key = edgeKey(u, v);
          if (!forkEdges.has(key)) return null;
          const a = graph.nodes.get(u);
          const b = graph.nodes.get(v);
          if (!a || !b) return null;
          const pa = toSvgPoint(a);
          const pb = toSvgPoint(b);
          return <line key={`fork-${u}-${v}`} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke={forkColor} strokeWidth="4" strokeLinecap="round" strokeDasharray="5 4" />;
        })}
        {remaining.map((hg) => {
          const a = graph.nodes.get(hg.white);
          const b = graph.nodes.get(hg.black);
          if (!a || !b || !adj[String(hg.white)] || !adj[String(hg.black)]) return null;
          const key = hourglassKey(hg).join(",");
          const strandColors = options.hourglassColors?.[key] ?? [];
          const paths = hourglassPaths(toSvgPoint(a), toSvgPoint(b));
          const highlighted = key === highlightKey;
          return (
            <g key={`${hg.white}-${hg.black}`}>
              {paths.map((d, idx) => (
                <path key={idx} d={d} fill="none" stroke={highlighted ? wrenchColor : colors[strandColors[idx]] ?? "#111"} strokeWidth={strandColors[idx] || highlighted ? 4 : 2.3} strokeLinecap="round" />
              ))}
            </g>
          );
        })}
        {[...graph.nodes.entries()].filter(([node]) => adj[String(node)] != null).map(([node, point]) => {
          const label = graph.boundary[String(node)];
          const nodeColor = options.nodeColorById?.[String(node)];
          const boundaryColor = label ? options.boundaryColorByLabel?.[String(label)] : undefined;
          const haloColor = colors[nodeColor ?? boundaryColor ?? 0];
          const p = toSvgPoint(point);
          return (
            <g key={node}>
              {haloColor ? <circle cx={p.x} cy={p.y} r={label ? 11 : 9} fill="none" stroke={haloColor} strokeWidth="3" /> : null}
              {selectedWrenchNodes.has(node) ? <circle cx={p.x} cy={p.y} r={label ? 13 : 12} fill="none" stroke={wrenchColor} strokeWidth="3" /> : null}
              {forkLabelNodes.has(node) ? <circle cx={p.x} cy={p.y} r="15" fill="none" stroke={forkColor} strokeWidth="3" strokeDasharray="4 3" /> : null}
              {forkCenterNodes.has(node) ? <circle cx={p.x} cy={p.y} r="12" fill="none" stroke={forkColor} strokeWidth="3" strokeDasharray="4 3" /> : null}
              <circle cx={p.x} cy={p.y} r={label ? 6.5 : 5.5} fill={nodeColor ? colors[nodeColor] : label || point.color ? "#000" : "#fff"} stroke="#000" strokeWidth="2" />
              {label ? <text x={165 + 145 * point.x} y={165 - 145 * point.y} textAnchor="middle" dominantBaseline="central" fontSize="12" fontWeight={forkLabelNodes.has(node) ? "700" : "400"}>{label}</text> : null}
            </g>
          );
        })}
      </svg>
      {remainingKeys.has(highlightKey) ? <div className="web-subtitle">highlighted wrench/hourglass: [{highlightKey}]</div> : null}
    </div>
  );
}

export function PairingLookup() {
  const [data, setData] = useState<CoreData | null>(null);
  const [loadError, setLoadError] = useState("");
  const [wInput, setWInput] = useState(DEFAULT_W);
  const [xInput, setXInput] = useState(DEFAULT_X);
  const [repInput, setRepInput] = useState(DEFAULT_REP);
  const [maxSteps, setMaxSteps] = useState("");
  const [beamWidth, setBeamWidth] = useState("500");
  const [allowW, setAllowW] = useState(true);
  const [showSteps, setShowSteps] = useState(true);
  const [useTranspose, setUseTranspose] = useState(false);
  const [selectedSurvivor, setSelectedSurvivor] = useState("");
  const [proof, setProof] = useState<Proof | null>(null);
  const [runError, setRunError] = useState("");
  const [running, setRunning] = useState(false);

  useEffect(() => {
    fetch("/problem3-core/manifest.json")
      .then((response) => response.json())
      .then((manifest: { parts: string[] }) =>
        Promise.all(
          manifest.parts.map((part) =>
            fetch(`/problem3-core/${part}`).then((response) => response.text()),
          ),
        ),
      )
      .then((parts) => setData(JSON.parse(parts.join(""))))
      .catch((error: Error) => setLoadError(error.message));
  }, []);

  const index = useMemo(() => (data ? buildCoreIndex(data) : null), [data]);
  const survivorInfo = useMemo(() => {
    if (!index || !wInput.trim()) return null;
    try {
      return survivorWordsForW(index, wInput);
    } catch {
      return null;
    }
  }, [index, wInput]);

  function chooseSurvivor(word: string) {
    setSelectedSurvivor(word);
    if (word) setXInput(word);
  }

  function applyShortcut() {
    if (!index) return;
    try {
      const pair = resolveShortcut(index, repInput);
      setWInput(pair.wWord);
      setXInput(pair.xWord);
      setSelectedSurvivor("");
    } catch (error) {
      setRunError(error instanceof Error ? error.message : String(error));
    }
  }

  function runProof(event: FormEvent) {
    event.preventDefault();
    if (!index) return;
    setRunning(true);
    setRunError("");
    setProof(null);
    window.setTimeout(() => {
      try {
        let wValue = wInput;
        let xValue = selectedSurvivor || xInput;
        if (useTranspose && !wInput.trim() && !xInput.trim()) {
          const pair = resolveShortcut(index, repInput);
          wValue = pair.wWord;
          xValue = pair.xWord;
          setWInput(wValue);
          setXInput(xValue);
        }
        const wGraph = resolveGraph(index, wValue, DEFAULT_W);
        const xGraph = resolveGraph(index, xValue, DEFAULT_X);
        const guidedSteps = maxSteps.trim() ? Number(maxSteps) : null;
        const result = provePairValueByXComponentColoring(xGraph, wGraph, allowW, Math.max(1, Number(beamWidth) || 500), guidedSteps);
        setProof(result);
      } catch (error) {
        setRunError(error instanceof Error ? error.message : String(error));
      } finally {
        setRunning(false);
      }
    }, 30);
  }

  const wGraph = index ? safeResolve(index, wInput, DEFAULT_W) : null;
  const xGraph = index ? safeResolve(index, selectedSurvivor || xInput, DEFAULT_X) : null;

  return (
    <>
      <header>
        <h1>Wrench Pairing Explorer</h1>
        <p className="muted">Enter W and X directly. They do not need to be transposes of each other.</p>
        <p className="muted">Hosted version: the graph data and Lemma 4.6 survivor list are bundled; the proof search and coloring run in this page.</p>
        <form onSubmit={runProof}>
          <label>W web index, word, or JSON file<input id="w-input" value={wInput} onChange={(e) => { setWInput(e.target.value); setSelectedSurvivor(""); }} placeholder="0447_1231423121323444.json" /></label>
          <label>X web index, word, or JSON file<input id="x-input" value={xInput} onChange={(e) => { setXInput(e.target.value); setSelectedSurvivor(""); }} placeholder="0447_1112122334344234.json" /></label>
          <label>Step cap, optional<input type="number" value={maxSteps} onChange={(e) => setMaxSteps(e.target.value)} min="0" placeholder="auto" /></label>
          <label>Beam width<input type="number" value={beamWidth} onChange={(e) => setBeamWidth(e.target.value)} min="1" /></label>
          <label className="check"><input type="checkbox" checked={allowW} onChange={(e) => setAllowW(e.target.checked)} /> allow wrench moves on W</label>
          <label className="check"><input type="checkbox" checked={showSteps} onChange={(e) => setShowSteps(e.target.checked)} /> show full step pictures</label>
          <button type="submit" disabled={!index || running}>{running ? "Running..." : "Run proof search"}</button>
          <div id="survivor-menu-slot">
            {survivorInfo?.row ? (
              <details className="survivor-panel" open>
                <summary>Lemma 4.6 survivors for W = {survivorInfo.row.wWord}</summary>
                <div className="survivor-grid">
                  <label>Survivor X word
                    <select value={selectedSurvivor} onChange={(e) => chooseSurvivor(e.target.value)}>
                      <option value="">Choose a survivor X word</option>
                      {survivorInfo.words.map((word, idx) => <option key={`${word}-${idx}`} value={word}>{String(idx + 1).padStart(4, "0")} {word}</option>)}
                    </select>
                  </label>
                  <div className="survivor-meta">
                    <p><strong>{survivorInfo.words.length}</strong> selectable survivors</p>
                    <p><strong>{survivorInfo.row.nPairs}</strong> CSV survivor pairs, <strong>{survivorInfo.row.nOrbits}</strong> CSV survivor orbits</p>
                    <p><strong>{survivorInfo.removed}</strong> CSV candidates removed by immediate common-fork check</p>
                    <p><strong>Forks of W:</strong> [{survivorInfo.forks.map((fork) => `[${fork.join(", ")}]`).join(", ")}]</p>
                    {selectedSurvivor ? <p className="muted">Selected survivor overrides the X field: <span className="word">{selectedSurvivor}</span></p> : <p className="muted">Choose one survivor, then run proof search. The selected survivor will be used as X.</p>}
                  </div>
                </div>
              </details>
            ) : wInput.trim() ? (
              <details className="survivor-panel" open><summary>No Lemma 4.6 survivor menu for this W</summary><p className="muted">No survivor row was found for this W or its promotion representative.</p></details>
            ) : null}
          </div>
          <details>
            <summary>Shortcut: use a representative and its transpose instead</summary>
            <div className="advanced-grid">
              <label>Representative index or word<input value={repInput} onChange={(e) => setRepInput(e.target.value)} placeholder="447 or 1112122334344234" /></label>
              <label className="check"><input type="checkbox" checked={useTranspose} onChange={(e) => setUseTranspose(e.target.checked)} /> use transpose pair when W/X are blank</label>
              <button type="button" onClick={applyShortcut} disabled={!index}>Fill shortcut pair</button>
            </div>
          </details>
        </form>
      </header>
      <main>
        {loadError ? <section className="summary"><h2>Data failed to load</h2><p>{loadError}</p></section> : null}
        {!data ? <section className="toc"><h2>Loading</h2><p>Loading the bundled 24,024-web graph data and survivor list...</p></section> : null}
        {runError ? <section className="summary"><h2>Error</h2><p>{runError}</p></section> : null}
        {!proof && data && !runError ? <section className="toc"><h2>Ready</h2><p>Enter a W web and an X web above, then run strategic wrench moves and coloring.</p><p className="muted">Bundled graphs: {index?.meta.graphCount.toLocaleString()}.</p></section> : null}
        {proof ? <ProofResult proof={proof} wGraph={wGraph} xGraph={xGraph} showSteps={showSteps} /> : null}
      </main>
    </>
  );
}

function safeResolve(index: CoreIndex, input: string, fallback: string) {
  try {
    return resolveGraph(index, input, fallback);
  } catch {
    return null;
  }
}

function ProofResult({ proof, wGraph, xGraph, showSteps }: { proof: Proof; wGraph: Graph | null; xGraph: Graph | null; showSteps: boolean }) {
  const firstEval = proof.coloringEvaluations[0];
  return (
    <>
      <section className="summary">
        <div>
          <h2>Pairing Result</h2>
          <p><strong>Mode:</strong> manual / Lemma 4.6 survivor</p>
          <p><strong>W:</strong> {wGraph ? <><span className="muted">{String(wGraph.index).padStart(4, "0")}</span> <span className="word">{wGraph.word}</span></> : "unknown"}</p>
        <p><strong>X:</strong> {xGraph ? <><span className="muted">{String(xGraph.index).padStart(4, "0")}</span> <span className="word">{xGraph.word}</span></> : "unknown"}</p>
        </div>
        <div className="result-pill">{proof.status}</div>
        <div className="metric"><span>Fork-killed branches</span><strong>{proof.dischargedTermCount}</strong></div>
        <div className="metric"><span>Active branches left</span><strong>{proof.activeTermCount}</strong></div>
        <div className="metric"><span>Final pairing value</span><strong>{proof.finalPairingValue ?? "partial"}</strong></div>
      </section>
      <section className="toc">
        <h2>What the page is showing</h2>
        <p>Each wrench move replaces one active branch by crossing branch minus parallel branch. If neither branch has a common fork, both branches stay active and the search keeps applying wrench moves before coloring. Once X-hourglasses are gone, X boundary components set colors and the page counts compatible edge colorings of W.</p>
      </section>
      <section className="step">
        <div className="step-head">
          <div><strong>Wrench Move Summary</strong></div>
          <div className="muted">Turn on full step pictures only when needed.</div>
        </div>
        <table className="step-table">
          <thead><tr><th>#</th><th>phase</th><th>side</th><th>hourglass</th><th>fork-killed forks</th><th>active branches kept</th><th>fork-killed branches</th></tr></thead>
          <tbody>
            {proof.steps.map((step, idx) => <tr key={idx}><td>{idx + 1}</td><td>{String(step.phase ?? "guided")}</td><td>{String(step.expandedSide ?? "")}</td><td>{JSON.stringify(step.expandedHourglass ?? [])}</td><td>{JSON.stringify(step.createdForks ?? [])}</td><td>{String(step.activeBranchesKept ?? step.activeTerms ?? "")}</td><td>{String(step.branchesForkKilled ?? step.dischargedTerms ?? "")}</td></tr>)}
          </tbody>
        </table>
      </section>
      {wGraph && xGraph ? (
        <section className="step">
          <div className="step-head"><div><strong>Initial Webs</strong></div><div className="muted">Drawn with the original hourglass curve rule.</div></div>
          <div className="grid two">{drawMiniSvg(wGraph, wGraph.adj, wGraph.hourglasses, "Initial W")}{drawMiniSvg(xGraph, xGraph.adj, xGraph.hourglasses, "Initial X")}</div>
        </section>
      ) : null}
      {showSteps && wGraph && xGraph ? <WrenchTrace proof={proof} wGraph={wGraph} xGraph={xGraph} /> : null}
      {showSteps && wGraph && xGraph ? <ForkLemmaPictures proof={proof} wGraph={wGraph} xGraph={xGraph} /> : null}
      {firstEval && wGraph && xGraph ? <FinalColoringPictures evaluation={firstEval} wGraph={wGraph} xGraph={xGraph} /> : null}
    </>
  );
}

function WrenchTrace({ proof, wGraph, xGraph }: { proof: Proof; wGraph: Graph; xGraph: Graph }) {
  const steps = reconstructBranchDisplaySteps(xGraph, wGraph, proof);
  if (!steps.length) return null;
  return (
    <section className="step">
      <div className="step-head">
        <div><strong>Wrench Move Pictures</strong></div>
        <div className="muted">Highlighted wrench relation: current branch = crossing branch - parallel branch; surviving siblings remain active.</div>
      </div>
      <div className="move-list">
        {steps.map((step, idx) => {
          const fork = step.killedForks[0];
          return (
            <div className="move-row" key={`${idx}-${step.side}-${step.selected.join("-")}`}>
              <div className="move-caption">
                <strong>Step {idx + 1}</strong>: expand {step.side} hourglass [{step.selected.join(", ")}].
                <span> Displayed path: {step.continueMove.smoothing}; sibling branch: {step.killedMove.smoothing}.</span>
                {step.siblingStatus === "fork-killed" ? <span> Sibling is killed by fork lemma using {JSON.stringify(step.killedForks)}.</span> : <span> Sibling is not fork-killed here, so it stays active for later wrench moves/coloring.</span>}
              </div>
              <div className="grid four">
                {drawMiniSvg(wGraph, step.currentW, step.currentWRemaining, "Current W", { highlightHourglass: step.side === "W" ? step.selected : undefined })}
                {drawMiniSvg(xGraph, step.currentX, step.currentXRemaining, "Current X", { highlightHourglass: step.side === "X" ? step.selected : undefined })}
                <div className="pair-card">
                  <div className="pair-title">Sibling branch</div>
                  <div className="pair-note">{step.killedMove.smoothing}; {step.siblingStatus === "fork-killed" ? `fork-killed with coeff ${step.killedCoeff}; fork(s) ${JSON.stringify(step.killedForks)}` : "kept as an active branch"}</div>
                  <div className="mini-pair">
                    {drawMiniSvg(wGraph, step.killedW, step.killedWRemaining, "W", { highlightForks: fork ? [fork] : [], edgeColors: blueEdgeColors(step.killedNewW) })}
                    {drawMiniSvg(xGraph, step.killedX, step.killedXRemaining, "X", { highlightForks: fork ? [fork] : [], edgeColors: blueEdgeColors(step.killedNewX) })}
                  </div>
                </div>
                <div className="pair-card">
                  <div className="pair-title">Displayed path branch</div>
                  <div className="pair-note">{step.continueMove.smoothing}; this is one active branch path, not the whole sum</div>
                  <div className="mini-pair">
                    {drawMiniSvg(wGraph, step.continueW, step.continueWRemaining, "W", { edgeColors: blueEdgeColors(step.continueNewW) })}
                    {drawMiniSvg(xGraph, step.continueX, step.continueXRemaining, "X", { edgeColors: blueEdgeColors(step.continueNewX) })}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ForkLemmaPictures({ proof, wGraph, xGraph }: { proof: Proof; wGraph: Graph; xGraph: Graph }) {
  const branches = proof.dischargedTerms.slice(0, 8);
  if (!branches.length) return null;
  return (
    <section className="step">
      <div className="step-head">
        <div><strong>Fork Lemma Branches</strong></div>
        <div className="muted">Orange rings mark the common fork labels used to kill the branch.</div>
      </div>
      <div className="move-list">
        {branches.map((branch, idx) => {
          const finalState = replayFinalState(xGraph, wGraph, branch.history);
          return (
            <div className="move-row" key={`${idx}-${branch.history.length}-${branch.commonForks.map((f) => f.join("-")).join("_")}`}>
              <div className="move-caption">
                <strong>Killed branch {idx + 1}</strong>: coefficient {branch.coeff}; common fork(s) {JSON.stringify(branch.commonForks)}.
              </div>
              <div className="grid two">
                {drawMiniSvg(wGraph, finalState.wAdj, finalState.wRemaining, "W at fork lemma", { highlightForks: branch.commonForks })}
                {drawMiniSvg(xGraph, finalState.xAdj, finalState.xRemaining, "X at fork lemma", { highlightForks: branch.commonForks })}
              </div>
            </div>
          );
        })}
      </div>
      {proof.dischargedTerms.length > branches.length ? <p className="muted">Showing the first {branches.length} killed branches out of {proof.dischargedTerms.length}.</p> : null}
    </section>
  );
}

function FinalColoringPictures({ evaluation, wGraph, xGraph }: { evaluation: Evaluation; wGraph: Graph; xGraph: Graph }) {
  if (evaluation.status !== "computed" || !evaluation.boundaryColorByLabel) {
    return (
      <section className="step coloring">
        <div className="step-head"><div><strong>Final Coloring</strong></div><div className="muted">{evaluation.reason}</div></div>
      </section>
    );
  }
  const finalState = replayFinalState(xGraph, wGraph, evaluation.history ?? []);
  const condition = evaluation.boundaryColorByLabel;
  const xNodeColors = nodeColorsFromBoundaryCondition(finalState.xAdj, xGraph.boundary, condition);
  const wColoring = coloringStatsWithHourglasses(finalState.wAdj, wGraph.boundary, condition, finalState.wRemaining);
  const wBoundaryEdgeColors = boundaryIncidentEdgeColors(finalState.wAdj, wGraph.boundary, condition);
  const wEdgeColors = { ...wBoundaryEdgeColors, ...wColoring.edgeColors };
  return (
    <section className="step coloring">
      <div className="step-head">
        <div><strong>Final Coloring Pictures</strong></div>
        <div className="muted">X components set boundary colors; W is edge-colored from those boundary colors.</div>
      </div>
      <div className="factor-box">
        <p><strong>Source:</strong> {evaluation.sourceSide ?? "X components"}</p>
        <p><strong>Coloring count:</strong> {evaluation.coloringCount ?? wColoring.count}</p>
        <p><strong>Coefficient:</strong> {evaluation.coeff ?? ""}</p>
        <p><strong>Contribution:</strong> {evaluation.termValue ?? "not computed"}</p>
      </div>
      <div className="grid two">
        {drawMiniSvg(wGraph, finalState.wAdj, finalState.wRemaining, "Final W: edge colors from X boundary", { edgeColors: wEdgeColors, hourglassColors: wColoring.hourglassColors })}
        {drawMiniSvg(xGraph, finalState.xAdj, finalState.xRemaining, "Final X: colored boundary vertices", { boundaryColorByLabel: condition, nodeColorById: xNodeColors })}
      </div>
    </section>
  );
}
