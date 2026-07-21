"""
apply_lemma49_patterns.py

Applies the SL4 Lemma 4.9 zero-pair boundary patterns (cases a, b, e, f, g, h, i,
plus extra_outer_pair_four_fan) to the 1,522 promotion-orbit representative webs.

For each (W, X) pair that survived Lemma 4.6 (fork check), checks whether both
W and X contain the local boundary subgraph specified by any Lemma 4.9 pattern.
If so, the pairing is discharged to zero.

Outputs:
  lemma49_survivors.tsv  -- pairs surviving both Lemma 4.6 and Lemma 4.9
  lemma49_eliminated.tsv -- pairs eliminated by Lemma 4.9

Usage:
  python3 apply_lemma49_patterns.py \\
      --graphs  hourglass_disk_4x4_promotion_reps_graph_data/ \\
      --patterns path/to/patterns/   \\
      --forks   lemma46_survivors_v2.csv
"""

import json, csv, glob, os, sys, argparse
from collections import defaultdict

# ── CLI ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--graphs',   required=True, help='Folder of graph JSONs')
parser.add_argument('--patterns', required=True, help='Folder of Lemma 4.9 JSONs')
parser.add_argument('--forks',    required=True, help='lemma46_survivors_v2.csv')
parser.add_argument('--out-survivors',  default='lemma49_survivors.tsv')
parser.add_argument('--out-eliminated', default='lemma49_eliminated.tsv')
args = parser.parse_args()

# ── Load Lemma 4.9 patterns ───────────────────────────────────────────────────
PATTERN_NAMES = ['a','b','e','f','g','h','i','extra_outer_pair_four_fan']

def load_patterns(pattern_dir):
    patterns = []
    for name in PATTERN_NAMES:
        path = os.path.join(pattern_dir, f'{name}.json')
        if os.path.exists(path):
            with open(path) as f:
                patterns.append(json.load(f))
    print(f'Loaded {len(patterns)} Lemma 4.9 patterns')
    return patterns

# ── Load and index graph JSONs ────────────────────────────────────────────────
def load_all_graphs(graph_dir):
    """Returns dict: word -> parsed graph data."""
    graphs = {}
    for path in glob.glob(os.path.join(graph_dir, '*.json')):
        fname = os.path.basename(path)
        parts = fname.split('_', 1)
        if len(parts) < 2:
            continue
        word = parts[1].replace('.json', '')
        with open(path) as f:
            graphs[word] = json.load(f)
    print(f'Loaded {len(graphs)} graph JSONs')
    return graphs

# ── Build adjacency structure for matching ────────────────────────────────────
def build_adj(graph_data):
    """
    Returns:
      nodes:        {node_id: {color, is_boundary}}
      adj:          {node_id: [(neighbor_id, kind, multiplicity)]}
      boundary_seq: [node_id ...] in order boundary_label 1..n
    """
    nodes = {}
    for n in graph_data['nodes']:
        nodes[n['id']] = {
            'color':       n['color'],
            'is_boundary': n.get('boundary_label') is not None,
            'bl':          n.get('boundary_label'),
        }

    adj = defaultdict(list)

    # ordinary edges
    for e in graph_data.get('edges', []):
        s, d = e['src'], e['dst']
        adj[s].append((d, 'ordinary', 1))
        adj[d].append((s, 'ordinary', 1))

    # hourglass edges
    for h in graph_data.get('hourglasses', []):
        w, b = h['white'], h['black']
        adj[w].append((b, 'hourglass', 2))
        adj[b].append((w, 'hourglass', 2))

    boundary_seq = sorted(
        [nid for nid, nd in nodes.items() if nd['is_boundary']],
        key=lambda nid: nodes[nid]['bl']
    )
    return nodes, dict(adj), boundary_seq

# ── Local pattern matching ────────────────────────────────────────────────────
def match_side(pat_side, g_nodes, g_adj, boundary_seq, start_idx, allow_reflection=False):
    """
    Try to match pat_side starting at boundary position start_idx.
    Returns a mapping {pat_node_id -> global_node_id} or None.
    """
    pat_boundary = pat_side['boundary_order']
    nb = len(pat_boundary)
    n  = len(boundary_seq)

    # Build pattern adjacency
    pat_nodes = {nd['id']: nd for nd in pat_side['nodes']}
    pat_adj   = defaultdict(list)
    for e in pat_side['edges']:
        pat_adj[e['u']].append((e['v'], e['kind'], e['multiplicity']))
        pat_adj[e['v']].append((e['u'], e['kind'], e['multiplicity']))

    def try_match(boundary_indices):
        """boundary_indices: list of global boundary node ids to map to pat_boundary."""
        mapping   = {}
        used      = set()

        # Map boundary nodes
        for k, pb in enumerate(pat_boundary):
            gb = boundary_indices[k]
            mapping[pb] = gb
            used.add(gb)

        # BFS inward from boundary
        queue   = list(pat_boundary)
        visited = set(pat_boundary)

        while queue:
            pn = queue.pop(0)
            gn = mapping.get(pn)
            if gn is None:
                continue  # port node, no global counterpart

            for (pnbr, ekind, emult) in pat_adj[pn]:
                pnbr_role  = pat_nodes[pnbr]['role']
                pnbr_color = pat_nodes[pnbr]['color']

                if pnbr in mapping:
                    # Already assigned — verify edge exists
                    gnbr = mapping[pnbr]
                    if gnbr is None:
                        continue  # port, ok
                    edge_ok = any(
                        gnbr2 == gnbr and gk == ekind and gm == emult
                        for gnbr2, gk, gm in g_adj.get(gn, [])
                    )
                    if not edge_ok:
                        return None
                else:
                    if pnbr_role == 'window_port':
                        mapping[pnbr] = None
                        if pnbr not in visited:
                            visited.add(pnbr)
                            queue.append(pnbr)
                        continue

                    # Find a global neighbor with the right color and edge type
                    candidates = [
                        gnbr for gnbr, gk, gm in g_adj.get(gn, [])
                        if gk == ekind and gm == emult
                        and g_nodes.get(gnbr, {}).get('color') == pnbr_color
                        and gnbr not in used
                    ]

                    if not candidates:
                        return None
                    # Take first candidate (patterns are typically unambiguous)
                    chosen = candidates[0]
                    mapping[pnbr] = chosen
                    used.add(chosen)

                    if pnbr not in visited:
                        visited.add(pnbr)
                        queue.append(pnbr)

        return mapping

    # Try all cyclic starting positions
    for start in range(n):
        indices = [boundary_seq[(start + k) % n] for k in range(nb)]
        result  = try_match(indices)
        if result is not None:
            return result

    # Try reflection (reverse boundary order)
    if allow_reflection:
        for start in range(n):
            indices = [boundary_seq[(start - k) % n] for k in range(nb)]
            result  = try_match(indices)
            if result is not None:
                return result

    return None

def pair_eliminated_by_pattern(pat, w_adj_data, x_adj_data, allow_reflection=True):
    """
    Returns True if this (W, X) pair is discharged to 0 by this pattern.
    Checks both orientations and pair-swap per the manifest.
    """
    wn, wa, wb = w_adj_data
    xn, xa, xb = x_adj_data

    # Normal: W matches pat['W'], X matches pat['X']
    if (match_side(pat['W'], wn, wa, wb, 0, allow_reflection) is not None and
        match_side(pat['X'], xn, xa, xb, 0, allow_reflection) is not None):
        return True

    # Pair-swap: W matches pat['X'], X matches pat['W']
    if (match_side(pat['X'], wn, wa, wb, 0, allow_reflection) is not None and
        match_side(pat['W'], xn, xa, xb, 0, allow_reflection) is not None):
        return True

    return False

def pair_eliminated_by_any(patterns, w_adj_data, x_adj_data):
    for pat in patterns:
        if pair_eliminated_by_pattern(pat, w_adj_data, x_adj_data):
            return True, pat['id']
    return False, None

# ── Load Lemma 4.6 survivors ──────────────────────────────────────────────────
def load_fork_survivors(csv_path):
    """
    Reads lemma46_survivors_v2.csv.
    Returns list of (w_word, x_word, rotation_k).
    """
    pairs = []
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            import ast
            survivor_words = ast.literal_eval(row['survivor_words'])
            w_word = row['w_word']
            for x_word in survivor_words:
                pairs.append((w_word, x_word))
    print(f'Loaded {len(pairs)} Lemma 4.6 surviving pairs')
    return pairs

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    patterns = load_patterns(args.patterns)
    graphs   = load_all_graphs(args.graphs)
    pairs    = load_fork_survivors(args.forks)

    # Pre-build adjacency for all graphs we need
    print('Building adjacency structures...')
    adj_cache = {}
    all_words = set()
    for w, x in pairs:
        all_words.add(w)
        all_words.add(x)
    for word in all_words:
        if word in graphs:
            adj_cache[word] = build_adj(graphs[word])
    print(f'Built adjacency for {len(adj_cache)} distinct webs')

    # Run pattern matching
    survivors  = []
    eliminated = []
    missing    = []

    print(f'Checking {len(pairs)} pairs against {len(patterns)} patterns...')
    for i, (w_word, x_word) in enumerate(pairs):
        if i % 10000 == 0:
            print(f'  {i}/{len(pairs)}...')

        if w_word not in adj_cache or x_word not in adj_cache:
            missing.append((w_word, x_word))
            continue

        elim, pat_id = pair_eliminated_by_any(
            patterns, adj_cache[w_word], adj_cache[x_word]
        )

        if elim:
            eliminated.append((w_word, x_word, pat_id))
        else:
            survivors.append((w_word, x_word))

    print(f'\nResults:')
    print(f'  Eliminated by Lemma 4.9: {len(eliminated)}')
    print(f'  Surviving:               {len(survivors)}')
    print(f'  Missing graph data:      {len(missing)}')

    # Write survivors TSV
    with open(args.out_survivors, 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['w_word', 'x_word'])
        w.writerows(survivors)
    print(f'Wrote {args.out_survivors}')

    # Write eliminated TSV
    with open(args.out_eliminated, 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['w_word', 'x_word', 'pattern_id'])
        w.writerows(eliminated)
    print(f'Wrote {args.out_eliminated}')

    # Summary by pattern
    from collections import Counter
    pat_counts = Counter(pat_id for _, _, pat_id in eliminated)
    print('\nEliminations by pattern:')
    for pat_id, count in pat_counts.most_common():
        print(f'  {pat_id}: {count}')

if __name__ == '__main__':
    main()
