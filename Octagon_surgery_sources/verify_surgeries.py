"""Run from any directory: python3 verify_surgeries.py. Standard library only."""
import json, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'replay'))
from surgery_core import *
from halfedge_web_20260812 import load_halfedge_web

def source(word):return HERE/'jsons'/('original_'+word+'.json')
def load(word):
    g=json.loads(source(word).read_text())
    return g,({n['id']:(n['color'],n.get('boundary_label')) for n in g['nodes']},
              {tuple(sorted((e['src'],e['dst']))):2 if e['kind']=='hourglass' else 1 for e in g['edges']})

data=json.loads((HERE/'verification.json').read_text())
total_states=total_matches=0
for rec in data['representatives']:
    states=sq.enumerate_square_orbit_states(source(rec['W']))
    assert len(states)==rec['square_orbit_size']
    assert not any(sq.exact_benzene_cycles(s) for s in states.values())
    for match in rec['matches']:
        web=load_halfedge_web(source(rec['W']))
        for step in match['square_move_path']:
            move=next(m for m in sq.detect_exact_square_moves(web) if list(m.cycle)==step['cycle'] and list(m.side_physical_edges)==step['side_physical_edges'])
            web=sq.apply_exact_square_move(web,move)
        assert sq.canonical_untagged_web_key(web)==list(states)[match['state_index']]
        B,step=splice_bundle(model(web),match['surgery']['cycle'],1)
        C,contractions=contract(B)
        assert len(contractions)==4 and all(s['weights']==[2,2] for s in contractions)
        target_g,target=load(match['target']);mapping=iso(C[:2],target)
        assert mapping and ribbon_match(C,target_g,mapping)
        assert mapping=={int(k):v for k,v in match['isomorphism'].items()}
        total_matches+=1
    total_states+=len(states)
    print('Orbit',rec['orbit'],':',len(states),'square states, two correction matches, no benzene.')
chain=data['chain_unzip'];A=model(load_halfedge_web(source(chain['source'])))
B,step=unzip(A,chain['step']['removed_cycle']);g,target=load(chain['target']);mapping=iso(B[:2],target)
assert mapping and ribbon_match(B,g,mapping)
print('PASS:',total_states,'square states;',total_matches,'octagon matches; chain unzip matches Q.')
print('Scope: colored weighted hourglass ribbon graphs, not skein coefficients or theta membership.')
