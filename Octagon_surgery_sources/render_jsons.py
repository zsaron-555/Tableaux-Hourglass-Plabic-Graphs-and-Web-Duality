import json, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, PathPatch
from matplotlib.path import Path as PlotPath
INK="#183043";PURPLE="#8749ba"
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
HERE=Path(__file__).resolve().parent
for path in sorted((HERE/'jsons').glob('orbit_*.json')):
 g=json.loads(path.read_text());fig,ax=plt.subplots(figsize=(5,5));draw(ax,g,g['name'])
 fig.savefig(HERE/'figures'/(path.stem+'_standalone.pdf'));plt.close(fig)
print('Rendered all generated JSONs.')
