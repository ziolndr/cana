#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,math,os,time,urllib.request,urllib.error
from pathlib import Path
from datetime import datetime,timezone
import numpy as np

def post_json(url,payload,timeout=120):
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'content-type':'application/json','user-agent':'CANA-field-builder/1.0'},method='POST')
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())

def vectors_from(data):
    for key in ('vectors','embeddings','data'):
        v=data.get(key) if isinstance(data,dict) else None
        if isinstance(v,list) and v:
            if isinstance(v[0],dict): return [x.get('embedding') or x.get('vector') for x in v]
            return v
    for key in ('embedding','vector'):
        v=data.get(key) if isinstance(data,dict) else None
        if isinstance(v,list): return [v] if (not v or not isinstance(v[0],list)) else v
    raise ValueError('ARBITER response contained no vectors')

def record_text(r):
    n=r['name'];t=r['type']
    tokens=' '.join(x for x in n.replace('/',' ').replace('-',' ').split() if x)
    return f'Cannabis variety record. Registered name: {n}. Registered type: {t}. Name tokens: {tokens}. Source: OpenTHC Variety Database.'

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',default='data/strains.csv');ap.add_argument('--field',default='field')
    ap.add_argument('--embed-url',default=os.getenv('ARBITER_EMBED_URL','http://127.0.0.1:8000/v1/embed'))
    ap.add_argument('--batch',type=int,default=128);ap.add_argument('--limit',type=int,default=0)
    a=ap.parse_args();root=Path(__file__).resolve().parents[1];src=(root/a.input).resolve();out=(root/a.field).resolve();out.mkdir(parents=True,exist_ok=True)
    rows=[]
    with src.open(encoding='utf-8-sig',newline='') as f:
        for x in csv.DictReader(f):
            name=(x.get('Strain') or '').strip()
            if not name:continue
            typ=(x.get('Type') or '').strip()
            if typ in ('','-unknown-'):typ='Unclassified'
            rows.append({'id':x['ID'],'name':name,'type':typ})
    if a.limit:rows=rows[:a.limit]
    probe=vectors_from(post_json(a.embed_url,{'texts':['CANA ARBITER field verification'],'use_freq':True}))[0]
    dim=len(probe)
    if dim!=72:raise SystemExit(f'Expected 72D ARBITER vectors, received {dim}D')
    vec_path=out/'vectors.npy';state_path=out/'build_state.json';meta_path=out/'metadata.jsonl'
    start=0
    if state_path.exists() and vec_path.exists():
        st=json.loads(state_path.read_text());start=int(st.get('completed',0));arr=np.lib.format.open_memmap(vec_path,mode='r+',dtype='float32',shape=(len(rows),dim))
    else:
        arr=np.lib.format.open_memmap(vec_path,mode='w+',dtype='float32',shape=(len(rows),dim));start=0
        with meta_path.open('w',encoding='utf-8') as f:
            for r in rows:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    print(f'CANA FIELD · {len(rows):,} records · {dim}D · starting at {start:,}')
    for i in range(start,len(rows),a.batch):
        batch=rows[i:i+a.batch];texts=[record_text(r) for r in batch]
        err=None
        for attempt in range(5):
            try:
                vv=np.asarray(vectors_from(post_json(a.embed_url,{'texts':texts,'use_freq':True})),dtype=np.float32)
                if vv.shape!=(len(batch),dim):raise ValueError(f'bad vector shape {vv.shape}')
                norms=np.linalg.norm(vv,axis=1,keepdims=True);vv=vv/np.maximum(norms,1e-12);arr[i:i+len(batch)]=vv;arr.flush();err=None;break
            except Exception as e:
                err=e;time.sleep(min(20,2**attempt))
        if err:raise err
        done=i+len(batch);state_path.write_text(json.dumps({'completed':done,'count':len(rows),'dim':dim,'embed_url':a.embed_url},indent=2))
        print(f'embedded {done:,}/{len(rows):,}',flush=True)
    manifest={'count':len(rows),'dim':dim,'source':'OpenTHC Variety Database','source_url':'https://vdb.openthc.org/download/strains.csv','built_at':datetime.now(timezone.utc).isoformat(),'embed_url':a.embed_url}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2));print(f'FIELD READY · {len(rows):,} records · {dim}D')
if __name__=='__main__':main()
