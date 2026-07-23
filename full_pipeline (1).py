"""
full_pipeline.py

Filtering pipeline:
  1. Load all 48,056 web JSONs
  2. For each (W, X) pair from Lemma 4.6 survivors, apply Lemma 4.9 patterns
  3. Output surviving pairs

NOTE: The (1,16) cyclic fork check has been removed pending clarification
from Gregg on the exact condition. Lemma 4.6 already eliminates pairs where
both W and X have fork at position 16 (the cyclic wrap). If additional
elimination is needed, the rotation-corrected check needs to be implemented
correctly.

Usage (one line on Windows from Downloads folder):
  python3 full_pipeline.py --graphs 4x4_All_graph_data\4x4_All_graph_data --patterns Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality\sl4_lemma49_zero_patterns --forks lemma46_survivors.csv
"""

import json, csv, glob, os, argparse, ast
from collections import defaultdict, Counter

parser = argparse.ArgumentParser()
parser.add_argument('--graphs',      required=True)
parser.add_argument('--patterns',    required=True)
parser.add_argument('--forks',       required=True)
parser.add_argument('--out',         default='final_survivors.tsv')
parser.add_argument('--out-summary', default='final_summary.txt')
args = parser.parse_args()

# ── Load Lemma 4.9 patterns ───────────────────────────────────────────────────
PATTERN_NAMES = ['a','b','e','f','g','h','i','extra_outer_pair_four_fan']

def load_patterns(d):
    pats = []
    for name in PATTERN_NAMES:
        p = os.path.join(d, f'{name}.json')
        if os.path.exists(p):
            with open(p) as f: pats.append(json.load(f))
        else:
            print(f'  WARNING: {name}.json not found')
    print(f'Loaded {len(pats)} patterns')
    return pats

# ── Index all 48,056 web JSONs ────────────────────────────────────────────────
def load_graph_index(d):
    index = {}
    for path in glob.glob(os.path.join(d, '*.json')):
        fname = os.path.basename(path)
        parts = fname.split('_', 1)
        if len(parts) == 2:
            word = parts[1].replace('.json','')
            index[word] = path
    print(f'Indexed {len(index):,} web JSONs')
    return index

def load_graph(path):
    with open(path) as f: return json.load(f)

# ── Build adjacency ───────────────────────────────────────────────────────────
def build_adj(data):
    nodes = {}
    for n in data['nodes']:
        nodes[n['id']] = {
            'color':       n['color'],
            'is_boundary': n.get('boundary_label') is not None,
            'bl':          n.get('boundary_label'),
        }
    adj  = defaultdict(list)
    seen = set()
    for e in data['edges']:
        s, d  = e['src'], e['dst']
        kind  = e.get('kind', 'ordinary')
        mult  = 2 if kind == 'hourglass' else 1
        key   = (min(s,d), max(s,d), kind)
        if key not in seen:
            seen.add(key)
            adj[s].append((d, kind, mult))
            adj[d].append((s, kind, mult))
    bseq = sorted(
        [nid for nid,nd in nodes.items() if nd['is_boundary']],
        key=lambda nid: nodes[nid]['bl']
    )
    return nodes, dict(adj), bseq

# ── Lemma 4.9 pattern matching ────────────────────────────────────────────────
def match_side(pat_side, g_nodes, g_adj, bseq, allow_reflection=False):
    pat_boundary = pat_side['boundary_order']
    nb = len(pat_boundary)
    n  = len(bseq)
    if nb > n: return False

    pat_nodes = {nd['id']: nd for nd in pat_side['nodes']}
    pat_adj   = defaultdict(list)
    for e in pat_side['edges']:
        pat_adj[e['u']].append((e['v'], e['kind'], e['multiplicity']))
        pat_adj[e['v']].append((e['u'], e['kind'], e['multiplicity']))

    def try_match(boundary_indices):
        mapping = {}
        used    = set()
        for k, pb in enumerate(pat_boundary):
            mapping[pb] = boundary_indices[k]
            used.add(boundary_indices[k])
        queue   = list(pat_boundary)
        visited = set(pat_boundary)
        while queue:
            pn = queue.pop(0)
            gn = mapping.get(pn)
            if gn is None: continue
            for (pnbr, ekind, emult) in pat_adj[pn]:
                if pnbr in mapping:
                    gnbr = mapping[pnbr]
                    if gnbr is None: continue
                    if not any(nb2==gnbr and k2==ekind and m2==emult
                               for nb2,k2,m2 in g_adj.get(gn,[])):
                        return None
                else:
                    pdata = pat_nodes[pnbr]
                    if pdata['role'] == 'window_port':
                        mapping[pnbr] = None
                        if pnbr not in visited:
                            visited.add(pnbr); queue.append(pnbr)
                        continue
                    cands = [
                        gnbr for gnbr,gk,gm in g_adj.get(gn,[])
                        if gk==ekind and gm==emult
                        and g_nodes.get(gnbr,{}).get('color')==pdata['color']
                        and gnbr not in used
                    ]
                    if not cands: return None
                    mapping[pnbr] = cands[0]
                    used.add(cands[0])
                    if pnbr not in visited:
                        visited.add(pnbr); queue.append(pnbr)
        return mapping

    for start in range(n):
        if try_match([bseq[(start+k)%n] for k in range(nb)]) is not None:
            return True
    if allow_reflection:
        for start in range(n):
            if try_match([bseq[(start-k)%n] for k in range(nb)]) is not None:
                return True
    return False

def eliminated_by_lemma49(patterns, w_adj, x_adj):
    wn,wa,wb = w_adj
    xn,xa,xb = x_adj
    for pat in patterns:
        if (match_side(pat['W'],wn,wa,wb,True) and
            match_side(pat['X'],xn,xa,xb,True)):
            return True, pat['id']
        if (match_side(pat['X'],wn,wa,wb,True) and
            match_side(pat['W'],xn,xa,xb,True)):
            return True, pat['id']
    return False, None

# ── Load Lemma 4.6 pairs ──────────────────────────────────────────────────────
def load_fork_survivors(path):
    pairs = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        # handle both CSV formats
        fieldnames = reader.fieldnames
        for row in reader:
            w = row['w_word']
            if 'survivor_words' in row:
                for x in ast.literal_eval(row['survivor_words']):
                    pairs.append((w, x))
            elif 'x_word' in row:
                pairs.append((w, row['x_word']))
    print(f'Loaded {len(pairs):,} Lemma 4.6 pairs')
    return pairs

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    patterns    = load_patterns(args.patterns)
    graph_index = load_graph_index(args.graphs)
    pairs       = load_fork_survivors(args.forks)

    print('Building adjacency structures...')
    needed = set(w for w,x in pairs) | set(x for w,x in pairs)
    adj_cache = {}
    missing   = []
    for word in needed:
        if word in graph_index:
            adj_cache[word] = build_adj(load_graph(graph_index[word]))
        else:
            missing.append(word)
    print(f'  Built for {len(adj_cache):,} webs, missing: {len(missing)}')

    print(f'\nProcessing {len(pairs):,} pairs...')
    survivors           = []
    elim_lemma49        = 0
    elim_lemma49_counts = Counter()
    skipped             = 0

    for i, (w_word, x_word) in enumerate(pairs):
        if i % 10000 == 0:
            print(f'  {i:,} / {len(pairs):,}...')

        if w_word not in adj_cache or x_word not in adj_cache:
            skipped += 1
            continue

        elim, pat_id = eliminated_by_lemma49(
            patterns, adj_cache[w_word], adj_cache[x_word]
        )
        if elim:
            elim_lemma49 += 1
            elim_lemma49_counts[pat_id] += 1
            continue

        survivors.append((w_word, x_word))

    # count distinct w and x words
    distinct_w = len(set(w for w,x in survivors))
    distinct_x = len(set(x for w,x in survivors))

    with open(args.out, 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['w_word','x_word'])
        w.writerows(survivors)

    lines = [
        'Full pipeline summary (Lemma 4.9 only)',
        '=======================================',
        f'Input (Lemma 4.6 survivors):      {len(pairs):,}',
        f'Eliminated by Lemma 4.9:          {elim_lemma49:,}',
        f'Surviving pairs:                  {len(survivors):,}',
        f'Distinct W words:                 {distinct_w:,}',
        f'Distinct X words:                 {distinct_x:,}',
        f'Skipped (no graph data):          {skipped:,}',
        '',
        'Lemma 4.9 breakdown:',
    ] + [f'  {pid}: {cnt}' for pid,cnt in elim_lemma49_counts.most_common()]

    with open(args.out_summary, 'w') as f:
        f.write('\n'.join(lines))

    print('\n' + '\n'.join(lines))
    print(f'\nWrote {args.out} and {args.out_summary}')

if __name__ == '__main__':
    main()
