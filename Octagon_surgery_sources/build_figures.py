"""Exact graph surgery certificates and figures, rendered from JSON records."""
import sys, json, math, collections, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT/'web_surgery_probe'), str(ROOT/'fll_pair_90min')]
from unzip_probe import *
from halfedge_web_20260812 import load_halfedge_web
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, PathPatch
from matplotlib.path import Path as PlotPath

WORDS=['1111222233334444','1111222233343444','1111222323343444','1112122233343444','1112122323343444','1121223133424344']
INK='#183043'; PURPLE='#8749ba'; TEAL='#008c83'

def write(name, data):
    (OUT/name).write_text(json.dumps(data,indent=2))

def export(A, name, cycle=None, coords=None, metadata=None):
    ns,es,rot=A
    fixed={v:(math.cos(math.pi/2-t[1]*math.pi/8), math.sin(math.pi/2-t[1]*math.pi/8)) for v,t in ns.items() if t[1] is not None}
    if coords is None:
        internal=[v for v in ns if v not in fixed]; ix={v:i for i,v in enumerate(internal)}
        L=np.zeros((len(ix),len(ix)));rhs=np.zeros((len(ix),2))
        for v in internal:
            i=ix[v];L[i,i]=len(rot[v])
            for w in rot[v]:
                if w in ix:L[i,ix[w]]-=1
                else:rhs[i]+=fixed[w]
        sol=np.linalg.solve(L,rhs)
        coords={**fixed,**{v:sol[ix[v]].tolist() for v in internal}}
    data={'schema':'sl4-surgery-ribbon-graph-v1','name':name,
          'nodes':[{'id':v,'color':t[0],'boundary_label':t[1],'x':float(coords[v][0]),'y':float(coords[v][1])} for v,t in ns.items()],
          'edges':[{'id':i,'src':v,'dst':w,'multiplicity':m,'kind':'hourglass' if m==2 else 'ordinary'} for i,((v,w),m) in enumerate(es.items())],
          'rotation_ccw':{str(v):r for v,r in rot.items()},'highlight_cycle':cycle or [],'metadata':metadata or {}}
    write('jsons/'+name+'.json',data)
    return data

def original(word,name,cycle=None):
    g=json.load(open(ROOT/'revised_basis_drawings'/M[word]['path']))
    web=load_halfedge_web(ROOT/'revised_basis_drawings'/M[word]['path'])
    A=model(web);coords={n['id']:(n['x'],n['y']) for n in g['nodes']}
    shutil.copy2(ROOT/'revised_basis_drawings'/M[word]['path'], OUT/'jsons'/('original_'+word+'.json'))
    return export(A,name,cycle,coords,{'tableau_word':word})

def draw(ax,g,title):
    ns={n['id']:n for n in g['nodes']}; pos={v:np.array([n['x'],n['y']]) for v,n in ns.items()}
    cyc=g['highlight_cycle']
    if cyc:ax.add_patch(Polygon([pos[v] for v in cyc],closed=True,fc=PURPLE,alpha=.13,ec='none',zorder=0))
    cycle_edges={frozenset((cyc[i],cyc[(i+1)%len(cyc)])) for i in range(len(cyc))}
    ax.add_patch(Circle((0,0),1,ec='#b8c5ce',lw=.65,fc='none'))
    for e in g['edges']:
        a,b=pos[e['src']],pos[e['dst']];d=b-a;l=np.linalg.norm(d);normal=np.array([-d[1],d[0]])/(l or 1)
        color=PURPLE if frozenset((e['src'],e['dst'])) in cycle_edges else INK
        if e['multiplicity']==2:
            bend=min(.055,l*.28)
            for s in [-1,1]:
                pts=[a,a+.28*d+s*bend*normal,a+.72*d-s*bend*normal,b]
                ax.add_patch(PathPatch(PlotPath(pts,[1,4,4,4]),ec=color,lw=1.05,fc='none',zorder=2))
        else:ax.plot([a[0],b[0]],[a[1],b[1]],c=color,lw=.95,zorder=2)
    for v,n in ns.items():
        x,y=pos[v];ax.add_patch(Circle((x,y),.015,ec=INK,lw=.7,fc=INK if n['color']=='black' else 'white',zorder=3))
        if n['boundary_label'] is not None:ax.text(x*1.105,y*1.105,str(n['boundary_label']),fontsize=6,ha='center',va='center',color=INK)
    ax.set(xlim=(-1.2,1.2),ylim=(-1.2,1.2),aspect='equal');ax.axis('off');ax.set_title(title,fontsize=10,color=INK,pad=5)

def panel(filename,graphs,titles,figsize):
    fig,axes=plt.subplots(1,len(graphs),figsize=figsize)
    for ax,g,title in zip(np.atleast_1d(axes),graphs,titles):draw(ax,g,title)
    fig.subplots_adjust(left=.015,right=.985,bottom=.02,top=.88,wspace=.06)
    fig.savefig(OUT/'figures'/(filename+'.pdf'))
    fig.savefig(OUT/'figures'/(filename+'.png'),dpi=190)
    plt.close(fig)

def main():
    rows=json.load(open(ROOT/'web_surgery_probe/ordinary_octagon_matches.json')); results=[];views={}
    for i,w in enumerate(WORDS,1):
        initial=load_halfedge_web(ROOT/'revised_basis_drawings'/M[w]['path']);key=sq.canonical_untagged_web_key(initial)
        states={key:initial};paths={key:[]};queue=collections.deque([key]);trip=sq._trip_signature(initial)
        while queue:
            k=queue.popleft();web=states[k]
            for move in sq.detect_exact_square_moves(web):
                child=sq.apply_exact_square_move(web,move);assert sq._trip_signature(child)==trip
                ck=sq.canonical_untagged_web_key(child)
                if ck in states:continue
                states[ck]=child;paths[ck]=paths[k]+[{'cycle':list(move.cycle),'facial_turn':move.facial_turn,'corner_kinds':list(move.corner_kinds),'side_physical_edges':list(move.side_physical_edges)}];queue.append(ck)
        matched=[]
        for r in [r for r in rows if r['web']==w]:
            k=list(states)[r['state_index']];A=model(states[k]);B,step=splice_bundle(A,r['surgery']['cycle'],1);C,steps=contract(B)
            target_g,target=load(r['target']);mat=iso(C[:2],target)
            assert mat and ribbon_match(C,target_g,mat)
            matched.append({**r,'square_move_path':paths[k],'ribbon_match':True})
        r=matched[0];A=model(list(states.values())[r['state_index']])
        orig=original(w,f'orbit_{i}_W')
        exposed=export(A,f'orbit_{i}_exposed',r['surgery']['cycle'],metadata={'square_move_path':r['square_move_path']})
        B,step=splice_bundle(A,r['surgery']['cycle'],1)
        export(B,f'orbit_{i}_spliced',metadata=step)
        C,steps=contract(B);export(C,f'orbit_{i}_contracted',metadata={'contractions':steps,'target':r['target']})
        residual_cycle=None
        if i==1:
            RA=model(load_halfedge_web(ROOT/'revised_basis_drawings'/M[r['target']]['path']));residual_cycle=next(f for f in facial(RA) if len(f)==8)
        target=original(r['target'],f'orbit_{i}_R',residual_cycle)
        panel(f'orbit_{i}',[orig,exposed,target],['Original $W_T$','$\\widetilde W_T$: exposed octagon',f'Correction web $R_{i}$'],(9,3.2))
        views[i]=(orig,exposed,target)
        benzene_count=sum(bool(sq.exact_benzene_cycles(s)) for s in states.values())
        assert benzene_count==0
        results.append({'orbit':i,'W':w,'R':r['target'],'coefficient_in_C':1 if i in [2,5] else -1,'square_orbit_size':len(states),'benzene_presentations':benzene_count,'exposing_path_length':len(r['square_move_path']), 'matches':matched})
        print('orbit',i,'states',len(states),'path',len(r['square_move_path']),'matches',len(matched),flush=True)
    R=WORDS[0];rword=results[0]['R'];RA=model(load_halfedge_web(ROOT/'revised_basis_drawings'/M[rword]['path']));face=next(f for f in facial(RA) if len(f)==8)
    Q,step=unzip(RA,face);qword='1212341234123434';qg,qt=load(qword);mat=iso(Q[:2],qt);assert mat and ribbon_match(Q,qg,mat)
    export(Q,'orbit_1_unzipped',metadata={'step':step,'isomorphism':mat,'target':qword})
    q=original(qword,'orbit_1_Q')
    panel('chain',[views[1][1],views[1][2],q],['$\\widetilde W_1$: alternating octagon','$R_1$: ordinary octagon','$Q$: four stars'],(9,3.2))
    fig,axes=plt.subplots(2,3,figsize=(12,8))
    for ax,g,t in zip(axes.flat,[*views[6],views[1][1],views[1][2],q],['Orbit 6: original W','Expose alternating octagon','Ordinary-side surgery gives R6','Orbit 1: exposed W','First surgery gives R1','Unzip gives Q']):draw(ax,g,t)
    fig.tight_layout(pad=1.1);fig.savefig(OUT/'Surgery_preview.png',dpi=170);plt.close(fig)
    write('verification.json',{'representatives':results,'chain_unzip':{'source':rword,'target':qword,'step':step,'isomorphism':mat,'ribbon_match':True},'scope':'Boundary-fixed colored weighted ribbon-graph matching. Not a skein identity or pairing proof.'})

    # A port diagram states the local rule independently of vertex numbering.
    ang=np.pi/2-np.arange(8)*np.pi/4;inner=np.array([np.cos(ang),np.sin(ang)]).T*.55;outer=inner/.55
    fig,axes=plt.subplots(1,2,figsize=(7,3.1))
    for ax in axes:
        ax.set_aspect('equal');ax.set_xlim(-1.3,1.3);ax.set_ylim(-1.3,1.3);ax.axis('off')
        for j,p in enumerate(outer):ax.text(*(p*1.15),f'$a_{j+1}$',fontsize=11,ha='center',va='center')
    ax=axes[0];ax.add_patch(Polygon(inner,fc=PURPLE,alpha=.11,ec='none'))
    for j,p in enumerate(inner):
        q=inner[(j+1)%8];d=q-p;l=np.linalg.norm(d);n=np.array([-d[1],d[0]])/l
        if j%2==0:
            for side in [-1,1]:ax.add_patch(PathPatch(PlotPath([p,p+.28*d+side*.06*n,p+.72*d-side*.06*n,q],[1,4,4,4]),ec=PURPLE,fc='none',lw=1.5))
        else:ax.plot([p[0],q[0]],[p[1],q[1]],c=PURPLE,lw=1.5)
        ax.plot([p[0],outer[j,0]],[p[1],outer[j,1]],c=INK,lw=1.2)
        ax.add_patch(Circle(p,.025,fc=INK if j%2==0 else 'white',ec=INK,zorder=4))
        ax.text(*(p*.76),f'$v_{j+1}$',ha='center',va='center',fontsize=9)
    axes[0].set_title('Alternating H / O octagon',fontsize=11,color=INK)
    for j in [1,3,5,7]:
        p,q=outer[j],outer[(j+1)%8];axes[1].plot([p[0],q[0]],[p[1],q[1]],c=TEAL,lw=2)
    axes[1].set_title('Remove corners; join across O sides',fontsize=11,color=INK)
    fig.tight_layout();fig.savefig(OUT/'figures/local_rule.pdf');fig.savefig(OUT/'figures/local_rule.png',dpi=190);plt.close(fig)

if __name__=='__main__':main()
