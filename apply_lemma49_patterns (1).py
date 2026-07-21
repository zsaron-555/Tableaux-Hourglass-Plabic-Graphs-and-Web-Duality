"""
apply_lemma49_patterns.py

Applies the SL4 Lemma 4.9 zero-pair boundary patterns to all (W, X) pairs
that survived Lemma 4.6, using the full set of 48,056 web JSON files.

Each JSON file has the format:
  nodes:      [{id, color, boundary_label, ...}]
  edges:      [{id, src, dst, kind ('ordinary'|'hourglass'), ...}]
  hourglasses:[{white, black, edge}]
  word:       "1234..."

Usage (Windows -- run as one line in Command Prompt):
  python3 apply_lemma49_patterns.py --graphs path\to\48056_jsons --patterns path\to\sl4_lemma49_zero_patterns --forks lemma46_survivors_v2.csv

Outputs:
  lemma49_survivors.tsv   -- pairs not eliminated by any pattern
  lemma49_eliminated.tsv  -- pairs eliminated, with which pattern
  lemma49_summary.txt     -- counts and breakdown by pattern
"""

import json, csv, glob, os, argparse, ast
from collections import defaultdict, Counter

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--graphs',         required=True)
parser.add_argument('--patterns',       required=True)
parser.add_argument('--forks',          required=True)
parser.add_argument('--out-survivors',  default='lemma49_survivors.tsv')
parser.add_argument('--out-eliminated', default='lemma49_eliminated.tsv')
parser.add_argument('--out-summary',    default='lemma49_summary.txt')
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
        else:
            print(f'  WARNING: {name}.json not found')
    print(f'Loaded {len(patterns)} Lemma 4.9 patterns')
    return patterns

# ── Index web JSONs ───────────────────────────────────────────────────────────
def load_graph_index(graph_dir):
    """Returns dict: word -> file path."""
    index = {}
    for path in glob.glob(os.path.join(graph_dir, '*.json')):
        fname = os.path.basename(path)
        parts = fname.split('_', 1)
        if len(parts) == 2:
            word = parts[1].replace('.json', '')
            index[word] = path
    print(f'Indexed {len(index):,} web JSON files')
    return index

def load_graph(path):
    with open(path) as f:
        return json.load(f)

# ── Build adjacency ───────────────────────────────────────────────────────────
def build_adj(data):
    nodes = {}
    for n in data['nodes']:
        nodes[n['id']] = {
            'color':       n['color'],
            'is_boundary': n.get('boundary_label') is not None,
            'bl':          n.get('boundary_label'),
        }

    adj = defaultdict(list)
    seen_edges = set()
    for e in data['edges']:
        s, d   = e['src'], e['dst']
        kind   = e.get('kind', 'ordinary')
        mult   = 2 if kind == 'hourglass' else 1
        key    = (min(s,d), max(s,d), kind)
        if key not in seen_edges:
            seen_edges.add(key)
            adj[s].append((d, kind, mult))
            adj[d].append((s, kind, mult))

    boundary_seq = sorted(
        [nid for nid, nd in nodes.items() if nd['is_boundary']],
        key=lambda nid: nodes[nid]['bl']
    )
    return nodes, dict(adj), boundary_seq

# ── Pattern matching ──────────────────────────────────────────────────────────
def match_side(pat_side, g_nodes, g_adj, boundary_seq, allow_reflection=False):
    pat_boundary = pat_side['boundary_order']
    nb = len(pat_boundary)
    n  = len(boundary_seq)
    if nb > n:
        return False

    pat_nodes = {nd['id']: nd for nd in pat_side['nodes']}
    pat_adj   = defaultdict(list)
    for e in pat_side['edges']:
        pat_adj[e['u']].append((e['v'], e['kind'], e['multiplicity']))
        pat_adj[e['v']].append((e['u'], e['kind'], e['multiplicity']))

    def try_match(boundary_indices):
        mapping = {}
        used    = set()
        for k, pb in enumerate(pat_boundary):
            gb = boundary_indices[k]
            mapping[pb] = gb
            used.add(gb)

        queue   = list(pat_boundary)
        visited = set(pat_boundary)

        while queue:
            pn = queue.pop(0)
            gn = mapping.get(pn)
            if gn is None:
                continue

            for (pnbr, ekind, emult) in pat_adj[pn]:
                if pnbr in mapping:
                    gnbr = mapping[pnbr]
                    if gnbr is None:
                        continue
                    if not any(nb2 == gnbr and k2 == ekind and m2 == emult
                               for nb2, k2, m2 in g_adj.get(gn, [])):
                        return None
                else:
                    pnbr_data  = pat_nodes[pnbr]
                    pnbr_role  = pnbr_data['role']
                    pnbr_color = pnbr_data['color']

                    if pnbr_role == 'window_port':
                        mapping[pnbr] = None
                        if pnbr not in visited:
                            visited.add(pnbr)
                            queue.append(pnbr)
                        continue

                    candidates = [
                        gnbr for gnbr, gk, gm in g_adj.get(gn, [])
                        if gk == ekind and gm == emult
                        and g_nodes.get(gnbr, {}).get('color') == pnbr_color
                        and gnbr not in used
                    ]
                    if not candidates:
                        return None

                    chosen = candidates[0]
                    mapping[pnbr] = chosen
                    used.add(chosen)
                    if pnbr not in visited:
                        visited.add(pnbr)
                        queue.append(pnbr)
        return mapping

    # Cyclic shifts
    for start in range(n):
        indices = [boundary_seq[(start + k) % n] for k in range(nb)]
        if try_match(indices) is not None:
            return True

    # Reflections
    if allow_reflection:
        for start in range(n):
            indices = [boundary_seq[(start - k) % n] for k in range(nb)]
            if try_match(indices) is not None:
                return True

    return False

def eliminated_by_pattern(pat, w_adj, x_adj):
    wn, wa, wb = w_adj
    xn, xa, xb = x_adj

    if (match_side(pat['W'], wn, wa, wb, allow_reflection=True) and
        match_side(pat['X'], xn, xa, xb, allow_reflection=True)):
        return True

    # pair-swap
    if (match_side(pat['X'], wn, wa, wb, allow_reflection=True) and
        match_side(pat['W'], xn, xa, xb, allow_reflection=True)):
        return True

    return False

def eliminated_by_any(patterns, w_adj, x_adj):
    for pat in patterns:
        if eliminated_by_pattern(pat, w_adj, x_adj):
            return True, pat['id']
    return False, None

# ── Load Lemma 4.6 survivors ──────────────────────────────────────────────────
def load_fork_survivors(csv_path):
    pairs = []
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            w_word = row['w_word']
            survivor_words = ast.literal_eval(row['survivor_words'])
            for x_word in survivor_words:
                pairs.append((w_word, x_word))
    print(f'Loaded {len(pairs):,} Lemma 4.6 surviving pairs')
    return pairs

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print('Loading patterns...')
    patterns = load_patterns(args.patterns)

    print('Indexing web JSON files...')
    graph_index = load_graph_index(args.graphs)

    print('Loading Lemma 4.6 survivors...')
    pairs = load_fork_survivors(args.forks)

    print('Building adjacency structures...')
    needed = set(w for w,x in pairs) | set(x for w,x in pairs)
    adj_cache = {}
    missing   = []
    for word in needed:
        if word in graph_index:
            adj_cache[word] = build_adj(load_graph(graph_index[word]))
        else:
            missing.append(word)
    print(f'  Built adjacency for {len(adj_cache):,} webs')
    if missing:
        print(f'  WARNING: {len(missing):,} words have no JSON file')

    print(f'\nChecking {len(pairs):,} pairs against {len(patterns)} patterns...')
    survivors  = []
    eliminated = []
    skipped    = []

    for i, (w_word, x_word) in enumerate(pairs):
        if i % 5000 == 0:
            print(f'  {i:,} / {len(pairs):,}...')
        if w_word not in adj_cache or x_word not in adj_cache:
            skipped.append((w_word, x_word))
            continue
        elim, pat_id = eliminated_by_any(patterns, adj_cache[w_word], adj_cache[x_word])
        if elim:
            eliminated.append((w_word, x_word, pat_id))
        else:
            survivors.append((w_word, x_word))

    with open(args.out_survivors, 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['w_word', 'x_word'])
        w.writerows(survivors)

    with open(args.out_eliminated, 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['w_word', 'x_word', 'pattern_id'])
        w.writerows(eliminated)

    pat_counts = Counter(pat_id for _,_,pat_id in eliminated)
    lines = [
        'Lemma 4.9 pattern matching summary',
        '====================================',
        f'Input pairs (Lemma 4.6 survivors): {len(pairs):,}',
        f'Eliminated by Lemma 4.9:           {len(eliminated):,}',
        f'Surviving:                         {len(survivors):,}',
        f'Skipped (no graph file):           {len(skipped):,}',
        '',
        'Eliminations by pattern:',
    ] + [f'  {pid}: {cnt}' for pid, cnt in pat_counts.most_common()]

    with open(args.out_summary, 'w') as f:
        f.write('\n'.join(lines))

    print('\n' + '\n'.join(lines))
    print(f'\nWrote: {args.out_survivors}, {args.out_eliminated}, {args.out_summary}')

if __name__ == '__main__':
    main()
