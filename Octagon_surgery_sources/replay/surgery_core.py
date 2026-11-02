import json, math, collections
import square_move_orbit_exact_20260815 as sq
from halfedge_web_20260812 import vertex_cycle_ccw, VertexColor


def iso(A,B):
 na,ea=A;nb,eb=B
 if len(na)!=len(nb) or sorted(ea.values())!=sorted(eb.values()):return None
 adj=[]
 for ns,es in [A,B]:
  d={v:{} for v in ns}
  for (v,w),m in es.items():d[v][w]=m;d[w][v]=m
  adj.append(d)
 colors=[{v:str(t) for v,t in ns.items()} for ns in [na,nb]]
 for _ in range(len(na)):
  sig=[{v:(colors[k][v],tuple(sorted((m,colors[k][w]) for w,m in adj[k][v].items()))) for v in ns} for k,ns in enumerate([na,nb])];keys=sorted(set(sig[0].values())|set(sig[1].values()),key=str);ids={x:i for i,x in enumerate(keys)};new=[{v:ids[sig[k][v]] for v in ns} for k,ns in enumerate([na,nb])]
  if collections.Counter(new[0].values())!=collections.Counter(new[1].values()):return None
  if all(len(set(new[k].values()))==len(set(colors[k].values())) for k in range(2)):colors=new;break
  colors=new
 groups=collections.defaultdict(list)
 for v,c in colors[1].items():groups[c].append(v)
 mapping={};used=set()
 def bt():
  if len(mapping)==len(na):return dict(mapping)
  v=min((v for v in na if v not in mapping),key=lambda v:(sum(w not in used for w in groups[colors[0][v]]),-sum(u in mapping for u in adj[0][v])))
  for w in groups[colors[0][v]]:
   if w in used:continue
   if any(adj[0][v].get(vv,0)!=adj[1][w].get(ww,0) for vv,ww in mapping.items()):continue
   mapping[v]=w;used.add(w);r=bt()
   if r is not None:return r
   used.remove(w);del mapping[v]
  return None
 return bt()

def model(web):
 ns={v:('black' if c in [VertexColor.BLACK,VertexColor.BOUNDARY] else 'white',web.boundary_label.get(v)) for v,c in web.color.items()};es={tuple(sorted(e.endpoints)):2 if e.kind=='H' else 1 for e in sq._abstract_edges(web)}
 rot={}
 for v in ns:
  arr=[web.vertex_of[web.mate[d]] for d in vertex_cycle_ccw(web,v)];uni=[]
  for x in arr:
   if not uni or uni[-1]!=x:uni.append(x)
  if len(uni)>1 and uni[0]==uni[-1]:uni.pop()
  rot[v]=uni
 return ns,es,rot

def facial(A):
 ns,es,rot=A;seen=set();out=[]
 for v in ns:
  for w in rot[v]:
   if (v,w) in seen:continue
   cyc=[];a,b=v,w
   while (a,b) not in seen:
    seen.add((a,b));cyc.append(a);arr=rot[b];a,b=b,arr[(arr.index(a)-1)%len(arr)]
   if len(set(cyc))!=len(cyc) or any(ns[x][1] is not None for x in cyc):continue
   out.append(cyc)
 return out

def splice_bundle(A,cyc,side):
 ns,es,rot=A;S=set(cyc);ext={}
 for v in cyc:
  xs=[(w,es[tuple(sorted((v,w)))]) for w in rot[v] if w not in S]
  if len(xs)!=1 or xs[0][1]!=1:return None
  ext[v]=xs[0][0]
 ns={v:t for v,t in ns.items() if v not in S};ed={e:m for e,m in es.items() if not set(e)&S};replace={};added=[]
 for i,v in enumerate(cyc):
  w=cyc[(i+1)%len(cyc)]
  if es[tuple(sorted((v,w)))]!=side:continue
  a,b=ext[v],ext[w];key=tuple(sorted((a,b)));ed[key]=ed.get(key,0)+1;replace[a,v]=b;replace[b,w]=a;added.append([a,b])
 rr={v:[replace[v,w] if w in S else w for w in ws] for v,ws in rot.items() if v not in S}
 # Adjacent parallel ports become one bundle in the compressed rotation.
 for v,arr in rr.items():
  uni=[]
  for x in arr:
   if not uni or uni[-1]!=x:uni.append(x)
  if len(uni)>1 and uni[0]==uni[-1]:uni.pop()
  if len(uni)!=len(set(uni)):return None
  rr[v]=uni
 return (ns,ed,rr),{'operation':'ordinary-side splice' if side==1 else 'hourglass-side splice','cycle':list(cyc),'external':ext,'added_edges':added}

def contract(A):
 ns,es,rot=[dict(x) for x in A];steps=[]
 while True:
  ns0=list(ns)
  v=next((v for v in ns0 if ns[v][1] is None and len(rot[v])==2 and all(ns[a][1] is None for a in rot[v])),None)
  if v is None:break
  a,b=rot[v];assert ns[a][0]==ns[b][0]
  ma,mb=es[tuple(sorted((v,a)))],es[tuple(sorted((v,b)))];assert ma+mb==4
  def rest(x):
   arr=rot[x];i=arr.index(v);return arr[i+1:]+arr[:i]
  ra,rb=rest(a),rest(b);newrot=ra+rb
  ne={}
  for (x,y),m in es.items():
   if v in (x,y):continue
   x=a if x==b else x;y=a if y==b else y;key=tuple(sorted((x,y)));ne[key]=ne.get(key,0)+m
  nr={x:[a if y==b else y for y in ys] for x,ys in rot.items() if x not in [v,b]};nr[a]=newrot
  for x,arr in nr.items():
   uni=[]
   for y in arr:
    if not uni or uni[-1]!=y:uni.append(y)
   if len(uni)>1 and uni[0]==uni[-1]:uni.pop()
   nr[x]=uni
  steps.append({'bivalent_vertex':v,'neighbors':[a,b],'weights':[ma,mb],'merge_to':a});del ns[v];del ns[b];es=ne;rot=nr
 return (ns,es,rot),steps

def target_rotation(g):
 rr={}
 for n in g['nodes']:
  arr=[p['neighbor'] for p in sorted(g['effective_rotation_system'][str(n['id'])],key=lambda p:p['ccw_slot'])];out=[]
  for a in arr:
   if not out or out[-1]!=a:out.append(a)
  if len(out)>1 and out[0]==out[-1]:out.pop()
  rr[n['id']]=out
 return rr

def ribbon_match(A,g,mat):
 rr=target_rotation(g)
 for v,arr in A[2].items():
  aa=[mat[x] for x in arr];bb=rr[mat[v]]
  if len(aa)!=len(bb) or not any(aa==bb[i:]+bb[:i] for i in range(len(bb))):return False
 return True

def unzip(A,cyc):
 ns,es,rot=A;S=set(cyc);outer={};attachments={};replacement={}
 for i,v in enumerate(cyc):
  prev,nxt=cyc[i-1],cyc[(i+1)%len(cyc)];out=[x for x in rot[v] if x not in S]
  if len(out)==1 and es[tuple(sorted((v,out[0])))]==2:outer[v]=out[0]
  elif len(out)==2 and all(es[tuple(sorted((v,x)))]==1 for x in out):
   rr=rot[v];j=rr.index(prev);ordered=rr[j+1:]+rr[:j]
   assert ordered[-1]==nxt,(v,ordered,nxt)
   attachments[v,prev]=ordered[0];attachments[v,nxt]=ordered[1]
  else:raise ValueError('wrong alternating corner')
 assert len(outer)==len(cyc)//2
 en={k:m for k,m in es.items() if not set(k)&S};nn={v:t for v,t in ns.items() if v not in S};newedges=[]
 for i,v in enumerate(cyc):
  if v not in outer:continue
  prev,nxt=cyc[i-1],cyc[(i+1)%len(cyc)];a=attachments[prev,v];b=attachments[nxt,v];x=outer[v]
  replacement[x,v]=[b,a]
  for u in [a,b]:
   en[tuple(sorted((x,u)))]=1;newedges.append([x,u])
  replacement[a,prev]=[x];replacement[b,nxt]=[x]
 rr={}
 for v,arr in rot.items():
  if v in S:continue
  rr[v]=[x for y in arr for x in (replacement[v,y] if y in S else [y])]
 return (nn,en,rr),{'operation':'ordinary-octagon unzip','removed_cycle':list(cyc),'outer_hourglass_vertices':outer,'new_edges':newedges}
