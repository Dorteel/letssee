#!/usr/bin/env python3
"""Incremental, owner-aware Obsidian graph. Requires Python 3.10+ and PyYAML."""
import argparse
from collections import defaultdict, deque
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import yaml

ROOT = 'psy-school-psychoanalysis'
SOURCE = 'obsidian-psychology-graph-builder'
LINK = re.compile(r'\[\[([^\[\]\n]+)\]\]')
PRIMARY = ('domain', 'type', 'tradition', 'period')
TYPES = {'school':'#2563eb', 'person':'#d97706', 'concept':'#9333ea',
         'theory':'#16a34a', 'method':'#0d9488', 'period':'#6b7280'}
RELATIONS = {
    'developed_from': ('branched_into', False, True),
    'branched_into': ('developed_from', False, True),
    'influenced': ('influenced_by', False, False),
    'influenced_by': ('influenced', False, False),
    'reacted_against': (None, False, False), 'extends': (None, False, False),
    'revises': (None, False, False), 'contradicts': ('contradicts', True, False),
    'integrates': (None, False, False),
    'shares_assumption_with': ('shares_assumption_with', True, False),
    'contemporary_of': ('contemporary_of', True, False),
    'associated_with_period': (None, False, False),
    'founded_by': ('founded', False, False), 'founded': ('founded_by', False, False),
    'studies': (None, False, False), 'introduces_concept': (None, False, False),
    'applies_to': (None, False, False), 'related_to': ('related_to', True, False),
    'developed': (None, False, False), 'criticized': (None, False, False),
    'uses_method': ('used_by', False, False), 'used_by': ('uses_method', False, False),
    'contributed_to': (None, False, False), 'collaborated_with': ('collaborated_with', True, False)}
ALIASES = {'branched_from':'developed_from', 'introduced':'introduces_concept'}
FIELDS = {r:r for r in RELATIONS} | ALIASES | {
    'associated_people':'related_to', 'related_concepts':'studies',
    'associated_schools':'contributed_to'}


def schema_default():
    return {'version':1, 'node_types':{k:{'color':v} for k,v in TYPES.items()},
        'traditions':['depth-psychology','psychodynamic','behavioral','cognitive',
        'humanistic','developmental','biological','social','integrative'],
        'primary_tag_dimensions':list(PRIMARY),
        'tag_policy':'Schools require four dimensions; people require domain and type.',
        'relations':{k:{'inverse':v[0], 'symmetric':v[1], 'genealogical':v[2]}
                     for k,v in RELATIONS.items()}, 'relation_aliases':ALIASES}


def read(path, default=None):
    if not path.exists(): return copy.deepcopy(default)
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data.encode()).hexdigest()


def atomic(path, data, dry=False):
    if path.exists() and path.read_text(encoding='utf-8') == data: return
    if dry: return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): shutil.copy2(path, path.with_name(path.name+'.bak'))
    name=None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as f:
            name=f.name; f.write(data); f.flush()
        Path(name).replace(path)
    finally:
        if name and Path(name).exists(): Path(name).unlink()


def within(vault, value):
    path=(vault/value).resolve()
    path.relative_to(vault)
    return path


@contextmanager
def lock(vault, dry):
    if dry:
        yield; return
    (vault/'_Graph').mkdir(parents=True,exist_ok=True)
    with (vault/'_Graph/.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        yield


def load(vault,check_projection=True):
    graph=read(vault/'_Graph/graph.json', {'version':1,'root':ROOT,'nodes':{},'claims':{}})
    if check_projection and 'edges' in graph:
        projection=read(vault/'_Graph/relationships.yaml')
        if projection != {'relationships':graph['edges']}:
            raise ValueError('Registry projection differs from graph.json; preserve edits then run sync')
    return graph


def parse(path, schema):
    return parse_content(path.read_text(encoding='utf-8'),schema)


def parse_content(content, schema):
    match=re.match(r'\A---\s*\n(.*?)\n---(?:\n|$)',content,re.S)
    if not match: raise ValueError('Missing YAML frontmatter')
    m=yaml.safe_load(match[1]); body=content[match.end():]
    if not isinstance(m,dict): raise ValueError('Frontmatter must be a mapping')
    for field in ['id','title','aliases','type','domain','tags']:
        if field not in m: raise ValueError('Missing field: '+field)
    if not re.fullmatch(r'[a-z][a-z0-9-]+',str(m['id'])): raise ValueError('Invalid ID')
    if not isinstance(m['title'],str) or not m['title'].strip(): raise ValueError('Empty title')
    if m['type'] not in schema['node_types']: raise ValueError('Unknown node type')
    if not isinstance(m['aliases'],list) or any(not isinstance(a,str) for a in m['aliases']):
        raise ValueError('aliases must be a list of strings')
    dimensions=list(PRIMARY) if m['type']=='school' else ['domain','type']
    if m['type']=='school':
        for key in ['tradition','period','emergence_year','depth','status']:
            if key not in m: raise ValueError('Missing school field: '+key)
        if m['tradition'] not in schema['traditions']: raise ValueError('Unknown tradition')
        if m['emergence_year'] is not None and type(m['emergence_year']) is not int:
            raise ValueError('emergence_year must be integer or null')
        if m['depth'] is not None and (type(m['depth']) is not int or m['depth']<0):
            raise ValueError('depth must be nonnegative integer or null')
    for key in ['birth_year','death_year']:
        if m.get(key) is not None and type(m[key]) is not int:
            raise ValueError(key+' must be integer or null')
    if m.get('birth_year') is not None and m.get('death_year') is not None and m['birth_year']>m['death_year']:
        raise ValueError('death_year precedes birth_year')
    if m.get('tradition') and m['tradition'] not in schema['traditions']:
        raise ValueError('Unknown tradition')
    tags=m['tags']
    if not isinstance(tags,list) or len(tags)!=len(set(tags)): raise ValueError('Invalid or duplicate tags')
    required={f'{d}/{m[d]}' for d in dimensions}
    allowed={f'{d}/{m[d]}' for d in PRIMARY if d in m}
    if not required.issubset(set(tags)) or not set(tags).issubset(allowed):
        raise ValueError('Use only primary dimension tags with matching metadata')
    if m['type']=='school' and len(tags)!=4: raise ValueError('Schools require exactly four tags')
    for field in FIELDS:
        if field in m and not isinstance(m[field],list): raise ValueError(field+' must be a list')
    if body.count('[[')!=len(LINK.findall(body)) or body.count(']]')!=len(LINK.findall(body)):
        raise ValueError('Malformed body wikilink')
    return m,body,content


def link_name(link):
    match=LINK.fullmatch(link)
    if not match: raise ValueError('Expected a wikilink: '+str(link))
    return match[1].split('|')[0].split('#')[0].removesuffix('.md')


def resolve(link,nodes):
    name=link_name(link)
    exact=[i for i,n in nodes.items() if name in [i,n['path'].removesuffix('.md')]]
    if len(exact)==1: return exact[0]
    matches=[i for i,n in nodes.items() if name in [n['title'],Path(n['path']).stem,*n.get('aliases',[])]]
    if len(matches)>1: raise ValueError('Ambiguous link: '+link)
    return matches[0] if matches else None


def validate_entities(nodes):
    paths={}
    for i,n in nodes.items():
        if n['path'] in paths and paths[n['path']]!=i: raise ValueError('Conflicting IDs for path: '+n['path'])
        paths[n['path']]=i
    names={}
    for i,n in nodes.items():
        if n['type']!='person': continue
        for name in [n['title'],Path(n['path']).stem,*n.get('aliases',[])]:
            key=name.casefold()
            if key in names and names[key]!=i:
                raise ValueError('Duplicate person name/alias; disambiguate explicitly: '+name)
            names[key]=i


def person_check(body,nodes):
    # Bibliography-only authors are exempt. Known aliases are checked outside wikilinks/URLs.
    prose=re.split(r'^## References\s*$',body,flags=re.M)[0]
    first=set()
    for match in LINK.finditer(prose):
        target=resolve(match[0],nodes)
        display=match[1].split('|')[-1]
        if target and nodes[target]['type']=='person':
            canonical=nodes[target]
            if match[1].split('|')[0]!=canonical['path'].removesuffix('.md'):
                raise ValueError('Use canonical person path: '+canonical['path'])
            if target not in first and display!=canonical['title']:
                raise ValueError('First person mention must display full canonical name: '+canonical['title'])
            first.add(target)
        for i,n in nodes.items():
            if n['type']!='person': continue
            if display in [n['title'],*n.get('aliases',[])] and i!=target:
                raise ValueError('Person label points to wrong entity: '+display)
    plain=LINK.sub('',prose)
    plain=re.sub(r'https?://[^\s)]+','',plain)
    for n in nodes.values():
        if n['type']!='person': continue
        names=[n['title'],Path(n['path']).stem,*n.get('aliases',[])]
        for name in names:
            if re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',plain):
                raise ValueError('Unlinked person mention: '+name)


def link_people(vault,path,schema,graph,dry):
    """Link declared person names; new identities must be supplied by the researcher."""
    m,body,content=parse(path,schema)
    nodes=copy.deepcopy(graph['nodes'])
    for n in m.get('pending_entities',[]):
        nodes.setdefault(n['id'],n)
    validate_entities(nodes)
    people={i:n for i,n in nodes.items() if n['type']=='person'}
    names={name:i for i,n in people.items() for name in [n['title'],*n.get('aliases',[])]}
    if not names: return {'linked':0,'message':'Declare pending people or register them first.'}
    pattern=re.compile(r'(?<!\w)('+'|'.join(re.escape(n) for n in sorted(names,key=len,reverse=True))+r')(?!\w)')
    parts=re.split(r'(^## References\s*$)',body,maxsplit=1,flags=re.M)
    # Keep existing links, inline/fenced code and URLs intact.
    protected=re.compile(r'(\[\[[^\[\]\n]+\]\]|```[\s\S]*?```|`[^`\n]*`|https?://[^\s)]+)')
    seen=set(); count=0
    def replacement(match):
        nonlocal count
        i=names[match[0]]; n=people[i]
        label=match[0] if i in seen else n['title']
        seen.add(i); count+=1
        return '[['+n['path'].removesuffix('.md')+'|'+label+']]'
    chunks=protected.split(parts[0])
    for index,chunk in enumerate(chunks):
        if index%2:
            if LINK.fullmatch(chunk):
                target=resolve(chunk,nodes)
                if target in people: seen.add(target)
        else: chunks[index]=pattern.sub(replacement,chunk)
    new_body=''.join(chunks)+''.join(parts[1:])
    person_check(new_body,nodes)
    prefix=content[:len(content)-len(body)]
    register(vault,path,schema,graph,dry=True,validate=True,content_override=prefix+new_body)
    atomic(path,prefix+new_body,dry)
    if not dry: register(vault,path,schema,graph)
    return {'linked':count,'dry_run':dry}


def claim_id(owner,s,r,t):
    return 'edge-'+digest('|'.join([owner,s,r,t]))[:20]


def extract(m,nodes,schema):
    items=[]
    for field,relation in FIELDS.items():
        for value in m.get(field,[]):
            value={'target':value} if isinstance(value,str) else dict(value)
            value.update(relation=relation)
            items.append(value)
    items.extend(m.get('relationships',[]))
    claims={}
    for value in items:
        if not isinstance(value,dict): raise ValueError('Relationship must be a mapping')
        r=schema.get('relation_aliases',{}).get(value['relation'],value['relation'])
        if r not in schema['relations']: raise ValueError('Unknown predicate: '+r)
        s=resolve(value.get('source','[['+m['id']+']]'),nodes)
        target=value['target']; link_name(target)
        t=resolve(target,nodes)
        if not s: raise ValueError('Relationship source must be declared')
        if m['id'] not in [s,t]: raise ValueError('A note may own only relationships involving itself')
        confidence=value.get('confidence','uncertain')
        if confidence not in ['high','medium','low','uncertain']: raise ValueError('Invalid confidence')
        evidence=value.get('evidence',[])
        if not isinstance(evidence,list) or any(not isinstance(e,dict) or not isinstance(e.get('source'),str) for e in evidence):
            raise ValueError('Evidence must be a list of source mappings')
        if r in ['founded','founded_by']:
            person=s if r=='founded' else t; school=t if r=='founded' else s
            if person and nodes[person]['type']!='person': raise ValueError('Founder must be a person')
            if school and nodes[school]['type']!='school': raise ValueError('Founded entity must be a school')
        if schema['relations'][r]['genealogical'] and t:
            if nodes[s]['type'] not in ['school','theory'] or nodes[t]['type'] not in ['school','theory']:
                raise ValueError('Genealogy requires schools or theories')
        key=claim_id(m['id'],s,r,t or target)
        claims[key]={'id':key,'owner':m['id'],'source':s,'target':t,
            'target_link':target,'relation':r,'direction':'directed' if not schema['relations'][r]['symmetric'] else 'symmetric',
            'date':value.get('date'),'description':value.get('description','Missing description.'),
            'confidence':confidence,'evidence':evidence}
        for optional in ['review_required','date_precision']:
            if optional in value: claims[key][optional]=value[optional]
    return list(claims.values())


def edges_from(graph):
    result=[]
    for owner,claims in sorted(graph['claims'].items()):
        for claim in claims:
            e=dict(claim)
            e['target']=resolve(e['target_link'],graph['nodes'])
            e['pending']=not e['target'] or graph['nodes'][e['target']].get('pending',False) or graph['nodes'][e['source']].get('pending',False)
            result.append(e)
    return sorted(result,key=lambda e:e['id'])


def distances(graph,root,mode='genealogy',relations=None):
    if root not in graph['nodes']: raise ValueError('Unknown root ID: '+root)
    adj=defaultdict(set)
    for e in graph.get('edges',[]):
        s,t,r=e['source'],e['target'],e['relation']
        if t is None or relations and r not in relations: continue
        if mode=='genealogy':
            if r=='developed_from': adj[t].add(s)
            elif r=='branched_into': adj[s].add(t)
        else:
            adj[s].add(t)
            spec=graph.get('relation_schema',{}).get(r,{})
            if spec.get('symmetric') or spec.get('inverse'): adj[t].add(s)
    d={root:0}; q=deque([root])
    while q:
        s=q.popleft()
        for t in sorted(adj[s]):
            if t not in d: d[t]=d[s]+1; q.append(t)
    return d


def rebuild(graph,schema):
    graph['relation_schema']=schema['relations']; graph['edges']=edges_from(graph)
    for e in graph['edges']:
        s,t,r=e['source'],e['target'],e['relation']
        if r not in schema['relations']: raise ValueError('Unregistered predicate: '+r)
        if t and schema['relations'][r]['genealogical']:
            if graph['nodes'][s]['type'] not in ['school','theory'] or graph['nodes'][t]['type'] not in ['school','theory']:
                raise ValueError('Resolved genealogical target is not a school/theory: '+e['target_link'])
        if t and r in ['founded','founded_by']:
            person,school=(s,t) if r=='founded' else (t,s)
            if graph['nodes'][person]['type']!='person' or graph['nodes'][school]['type']!='school':
                raise ValueError('Resolved founded edge must connect person to school')
    d=distances(graph,graph['root']) if graph['root'] in graph['nodes'] else {}
    for i,n in graph['nodes'].items(): n['depth']=d.get(i) if n['type'] in ['school','theory'] else None
    return graph


def queue_from(graph,prior):
    queue=copy.deepcopy(prior or {'completed':[],'pending':[]})
    queue.setdefault('completed',[])
    existing={n['id']:n for n in queue.get('pending',[])}
    for i,n in graph['nodes'].items():
        if n.get('pending'):
            existing[i]={**existing.get(i,{}),**{k:n[k] for k in ['id','title','type','path','sort_year','emergence_year','founding_period','research_priority'] if k in n},'status':'pending','priority':'high' if n['type']=='school' else 'normal'}
        else:
            existing.pop(i,None)
            if i not in queue['completed']: queue['completed'].append(i)
    queue['pending']=sorted(existing.values(),key=lambda n:(0 if n['type']=='school' else 1,n.get('sort_year',9999),n['id']))
    schools=[n for n in queue['pending'] if n['type']=='school']
    queue['next_proposed_target']=schools[0]['id'] if schools else None
    return queue


def persist(vault,graph,schema,dry):
    rebuild(graph,schema)
    queue=queue_from(graph,read(vault/'_Graph/research_queue.yaml',{}))
    # graph.json is the source of truth; YAML is a deterministic projection recoverable with sync.
    atomic(vault/'_Graph/graph.json',json.dumps(graph,indent=2,ensure_ascii=False,sort_keys=True)+'\n',dry)
    atomic(vault/'_Graph/relationships.yaml',yaml.safe_dump({'relationships':graph['edges']},sort_keys=False,allow_unicode=True),dry)
    atomic(vault/'_Graph/research_queue.yaml',yaml.safe_dump(queue,sort_keys=False,allow_unicode=True),dry)


def register(vault,path,schema,graph,dry=False,validate=False,content_override=None):
    staged=copy.deepcopy(graph)
    result=_register(vault,path,schema,staged,dry,validate,content_override)
    if not dry and not validate:
        graph.clear(); graph.update(staged)
    return result


def _register(vault,path,schema,graph,dry=False,validate=False,content_override=None):
    m,body,content=parse_content(content_override,schema) if content_override is not None else parse(path,schema)
    relative=str(path.relative_to(vault))
    if m['type']=='person' and m['domain']=='psychology' and not relative.startswith('Psychology/People/'):
        raise ValueError('Psychology person articles belong in Psychology/People/')
    nodes=graph['nodes']; old=nodes.get(m['id'])
    for i,n in nodes.items():
        if n['path']==relative and i!=m['id']: raise ValueError('Stable ID is immutable for an existing path')
    if old and not old.get('pending') and old['path']!=relative and within(vault,old['path']).exists():
        raise ValueError('Duplicate stable ID: original note still exists')
    aliases=list(dict.fromkeys(m['aliases']+([old['title'],old['path'].removesuffix('.md')] if old and (old['title']!=m['title'] or old['path']!=relative) else [])))
    nodes[m['id']]={**m,'path':relative,'aliases':aliases,'pending':False,'body':body,'content_hash':digest(content)}
    for entity in m.get('pending_entities',[]):
        e=dict(entity)
        for key in ['id','title','type','path']: 
            if key not in e: raise ValueError('Pending entity missing '+key)
        if e['type'] not in schema['node_types']: raise ValueError('Unknown pending type')
        within(vault,e['path'])
        if e['type']=='person' and not e['path'].startswith('Psychology/People/'):
            raise ValueError('Person must use canonical Psychology/People path')
        existing=nodes.get(e['id'])
        if existing:
            if existing['type']!=e['type'] or existing['path']!=e['path']:
                raise ValueError('Conflicting pending entity; reuse registered path')
            continue
        if within(vault,e['path']).exists():
            raise ValueError('Existing unregistered target must be registered individually first: '+e['path'])
        nodes[e['id']]={**e,'aliases':e.get('aliases',[]),'pending':True}
    validate_entities(nodes); person_check(body,nodes)
    extracted=extract(m,nodes,schema)
    for claim in extracted:
        for previous in graph['claims'].get(m['id'],[]):
            same_target=(claim['target'] is not None and resolve(previous['target_link'],nodes)==claim['target']) or previous['target_link']==claim['target_link']
            if previous['source']==claim['source'] and previous['relation']==claim['relation'] and same_target:
                claim['id']=previous['id']; break
    graph['claims'][m['id']]=extracted
    # Resolve every prose link, including people; undeclared targets remain pending strings.
    missing=sorted({link_name('[['+l+']]') for l in LINK.findall(body)
                    if (i:=resolve('[['+l+']]',nodes)) is None or nodes[i].get('pending')})
    rebuild(graph,schema)
    if not validate: persist(vault,graph,schema,dry)
    return {'id':m['id'],'missing_links':missing,'edges_owned':len(graph['claims'][m['id']]),
            'depth':nodes[m['id']]['depth'],'dry_run':dry,'validated_only':validate}


def selected_nodes(graph,view):
    allowed={'schools':{'school','theory'},'people':{'person','school','theory'},
             'concepts':{'concept','method','theory','school'},'all':set(TYPES)}[view]
    return {i:n for i,n in graph['nodes'].items() if n['type'] in allowed}


def verify_sources(vault,graph):
    for n in graph['nodes'].values():
        if not n.get('pending'):
            path=within(vault,n['path'])
            if not path.exists() or digest(path.read_text())!=n['content_hash']:
                raise ValueError('Note changed; update this one file first: '+n['path'])


def export(vault,graph,schema,args):
    verify_sources(vault,graph)
    nodes=selected_nodes(graph,args.view)
    if args.root not in nodes: raise ValueError('Root excluded by selected view')
    d=distances(graph,args.root); groups=defaultdict(list)
    for i in sorted(nodes):
        if i!=args.root: groups[d.get(i,-1)].append(i)
    pos={args.root:(0.,0.)}
    outer=max(d.values(),default=0)+1
    for level,ids in sorted(groups.items()):
        radius=max(380*(level if level>=0 else outer),len(ids)*270/(2*math.pi))
        for j,i in enumerate(ids):
            angle=2*math.pi*j/len(ids)
            pos[i]=(radius*math.cos(angle),radius*math.sin(angle))
    if args.layout=='timeline':
        years=[n.get('emergence_year',n.get('birth_year')) for n in nodes.values()]
        origin=min([y for y in years if type(y) is int],default=1890)
        lanes=defaultdict(int)
        for i,n in sorted(nodes.items()):
            year=n.get('emergence_year',n.get('birth_year')); x=(year-origin)*18 if type(year) is int else -400
            lane=lanes[x]; lanes[x]+=1; pos[i]=(x,lane*160)
    elements=[]
    def element(kind,id,x,y,w,h,**kw):
        e={'id':id,'type':kind,'x':x,'y':y,'width':w,'height':h,'angle':0,
           'strokeColor':'#1e293b','backgroundColor':'transparent','fillStyle':'solid',
           'strokeWidth':2,'strokeStyle':'solid','roughness':0,'opacity':100,'groupIds':[],
           'frameId':None,'roundness':None,'seed':1,'version':1,'versionNonce':1,
           'isDeleted':False,'boundElements':None,'updated':1,'link':None,'locked':False}
        e.update(kw); elements.append(e)
    def label(id,x,y,text,color='#1e293b'):
        lines=text.splitlines() or ['']
        element('text',id,x,y,max(map(len,lines))*9.5,22*len(lines),text=text,originalText=text,
                fontSize=16,fontFamily=1,textAlign='left',verticalAlign='top',containerId=None,
                autoResize=True,lineHeight=1.375,strokeColor=color)
    for i,n in sorted(nodes.items()):
        x,y=pos[i]; year=n.get('emergence_year',n.get('birth_year'))
        color=schema['node_types'][n['type']]['color']
        element('rectangle',i,x-120,y-42,240,84,strokeColor=color,
                strokeStyle='dashed' if n.get('pending') else 'solid',
                customData={'nodeId':i,'nodeType':n['type'],'depth':d.get(i),'pending':n.get('pending',False)})
        title=n['title']; wrapped='\n'.join(title[k:k+25] for k in range(0,len(title),25))
        label(i+'-text',x-112,y-36,wrapped+'\n'+str(year if year is not None else 'date unknown'),color)
    for e in graph.get('edges',[]):
        s,t=e['source'],e['target']
        if s not in nodes or t not in nodes: continue
        x,y=pos[s]; tx,ty=pos[t]
        if s==t: tx=x+130; ty=y+100
        color='#2563eb' if schema['relations'][e['relation']]['genealogical'] else '#64748b'
        element('arrow',e['id'],x,y+42,abs(tx-x),abs(ty-y-84),
            points=[[0,0],[tx-x,ty-y-84]],startBinding={'elementId':s,'focus':0,'gap':0},endBinding={'elementId':t,'focus':0,'gap':0},
            startArrowhead=None,endArrowhead=None if e['direction']=='symmetric' else 'arrow',
            strokeColor=color,strokeStyle='solid' if schema['relations'][e['relation']]['genealogical'] else 'dashed',
            customData={'relation':e['relation'],'source':s,'target':t})
        label(e['id']+'-text',(x+tx)/2,(y+ty)/2,e['relation']+(' ~'+str(e['date']) if e['date'] else ''))
    bound=defaultdict(list)
    for e in graph.get('edges',[]):
        if e['source'] in nodes and e['target'] in nodes:
            bound[e['source']].append({'id':e['id'],'type':'arrow'})
            if e['source']!=e['target']: bound[e['target']].append({'id':e['id'],'type':'arrow'})
    for element_data in elements:
        if element_data['type']=='rectangle': element_data['boundElements']=bound.get(element_data['id'])
    label('legend',-450,-280,'Solid blue: genealogy; dashed gray: other relations\nDashed node: pending research; outer ring: no genealogical distance')
    scene={'type':'excalidraw','version':2,'source':SOURCE,'elements':elements,
           'appState':{'viewBackgroundColor':'#ffffff','gridSize':None},'files':{}}
    output=within(vault,args.output or f'Psychology/Maps/{args.view}-{args.layout}.generated.excalidraw')
    if not output.name.endswith('.generated.excalidraw'):
        raise ValueError('Use a separate *.generated.excalidraw output path')
    stamp=output.with_name(output.name+'.sha256')
    if output.exists():
        if not stamp.exists() or stamp.read_text().strip()!=digest(output.read_text()):
            raise ValueError('Map was manually edited or is unrecognized; choose a new output path')
    content=json.dumps(scene,indent=2,ensure_ascii=False)+'\n'
    atomic(output,content,args.dry_run); atomic(stamp,digest(content)+'\n',args.dry_run)
    return {'output':str(output.relative_to(vault)),'nodes':len(nodes),'elements':len(elements)}


def narrative(graph,args):
    d=distances(graph,args.root,args.mode,args.relations)
    chunks=['# Generated historical narrative']
    for i in sorted(d,key=lambda i:(d[i],graph['nodes'][i].get('emergence_year') or 9999,i)):
        if d[i]>args.depth: continue
        n=graph['nodes'][i]
        chunks.append('## '+n['title'])
        if n.get('pending'): chunks.append('Pending research. No historical account available.'); continue
        for question,heading in [('What was believed before?','What came before?'),
             ('What problem emerged?','The intellectual problem'),('Who proposed the approach?','Origins and founding thinkers'),
             ('What assumption changed?','What changed?'),('What followed?','Further developments')]:
            match=re.search(r'^## '+re.escape(heading)+r'\s*\n(.*?)(?=^## |\Z)',n['body'],re.M|re.S)
            chunks.append(question+'\n'+(match[1].strip() if match and match[1].strip() else 'Missing information.'))
        for e in graph['edges']:
            if i in [e['source'],e['target']]:
                chunks.append(e['relation']+': '+e['description']+'\nEvidence: '+json.dumps(e['evidence']))
        references=re.search(r'^## References\s*\n(.*)',n['body'],re.M|re.S)
        if references: chunks.append('### Source references\n'+references[1].strip())
    return '\n\n'.join(chunks)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vault',default='.'); p.add_argument('--dry-run',action='store_true')
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('init'); s.add_argument('--root',default=ROOT)
    for cmd in ['add','update','validate','link-people']:
        s=sub.add_parser(cmd); s.add_argument('--file',required=True)
        s.add_argument('--dry-run',action='store_true',default=argparse.SUPPRESS)
    for cmd in ['query','narrative','visualize']:
        s=sub.add_parser(cmd); s.add_argument('--root',default=ROOT)
        s.add_argument('--mode',choices=['genealogy','network'],default='genealogy')
        s.add_argument('--relations',nargs='+',choices=list(RELATIONS))
        s.add_argument('--depth',type=int,default=3); s.add_argument('--output')
        s.add_argument('--view',choices=['schools','people','concepts','all'],default='schools')
        s.add_argument('--layout',choices=['radial','timeline'],default='radial')
        s.add_argument('--dry-run',action='store_true',default=argparse.SUPPRESS)
    sub.add_parser('queue'); sub.add_parser('sync')
    s=sub.add_parser('import-list'); s.add_argument('--source',required=True)
    s=sub.add_parser('import-node'); s.add_argument('--source',required=True)
    s.add_argument('--id',required=True); s.add_argument('--file',required=True)
    s.add_argument('--dry-run',action='store_true',default=argparse.SUPPRESS)
    args=p.parse_args(); vault=Path(args.vault).resolve()
    readonly=args.command in ['validate','query','queue','import-list'] or args.dry_run
    with lock(vault,readonly):
        schema=read(vault/'_Graph/schema.yaml',schema_default())
        graph=load(vault,check_projection=args.command!='sync')
        if args.command=='init':
            if graph['nodes'] and graph['root']!=args.root: raise ValueError('Existing graph root differs')
            graph['root']=args.root
            atomic(vault/'_Graph/schema.yaml',yaml.safe_dump(schema,sort_keys=False),args.dry_run)
            persist(vault,graph,schema,args.dry_run); print('Initialized metadata; no Markdown created.')
        elif args.command=='link-people':
            print(json.dumps(link_people(vault,within(vault,args.file),schema,graph,args.dry_run)))
        elif args.command in ['add','update','validate']:
            path=within(vault,args.file)
            print(json.dumps(register(vault,path,schema,graph,args.dry_run,args.command=='validate'),indent=2))
        elif args.command=='sync': persist(vault,graph,schema,args.dry_run)
        elif args.command=='queue': print(yaml.safe_dump(read(vault/'_Graph/research_queue.yaml',{}),sort_keys=False))
        elif args.command in ['query','narrative','visualize']:
            rebuild(graph,schema)
            if args.command=='query':
                d=distances(graph,args.root,args.mode,args.relations)
                selected=selected_nodes(graph,args.view)
                print(json.dumps({i:v for i,v in d.items() if i in selected and v<=args.depth},indent=2))
            elif args.command=='visualize': print(json.dumps(export(vault,graph,schema,args)))
            else:
                content=narrative(graph,args)
                if args.output:
                    if not args.output.endswith('.generated.txt'): raise ValueError('Use *.generated.txt to preserve the one-Markdown-file workflow')
                    atomic(within(vault,args.output),content,args.dry_run)
                else: print(content)
        else:
            seed=read(Path(args.source)); entries=seed['nodes']
            if args.command=='import-list':
                print('\n'.join(n['id'] for n in entries if graph['nodes'].get(n['id'],{}).get('pending',True)))
            else:
                matches=[n for n in entries if n['id']==args.id]
                if len(matches)!=1: raise ValueError('Select exactly one seed ID')
                m=copy.deepcopy(matches[0]); body=m.pop('body','')
                content='---\n'+yaml.safe_dump(m,sort_keys=False,allow_unicode=True)+'---\n'+body
                path=within(vault,args.file)
                if path.exists() and path.read_text()!=content: raise ValueError('Import would overwrite authored content')
                register(vault,path,schema,graph,dry=True,validate=True,content_override=content)
                if args.dry_run: print(content)
                else:
                    existed=path.exists(); atomic(path,content)
                    try: print(json.dumps(register(vault,path,schema,graph)))
                    except Exception:
                        if not existed: path.unlink()
                        raise

if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,TypeError,OSError,yaml.YAMLError) as exc:
        print('Error: '+str(exc),file=sys.stderr); sys.exit(1)
