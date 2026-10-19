"""Preservation-first BFS: Codex researches one school live, then commits one note."""
import argparse
import copy
from collections import deque
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import uuid
from codex_research import LiveResearchUnavailable, research as live_research, prompt as research_prompt

REPO = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = REPO / 'world knowledge/psychoanalysis'
spec = importlib.util.spec_from_file_location('vault_graph', DEFAULT_VAULT/'tools/graph_builder.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
HEADINGS = ['Who','When','What','Why','How','What Changed','Developments','References']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exclusive(path, content):
    """Stage fully, fsync, then publish atomically without replacing any destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as f:
            name = f.name
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.link(name, path)
    finally:
        if name:
            Path(name).unlink(missing_ok=True)


def preserve(vault, dry=False):
    manifest_path = vault/'_Research/preservation.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {str(p.relative_to(vault)): sha(p) for p in vault.rglob('*.md')}
        if not dry:
            backup = vault.parent / (vault.name + '-research-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.tar.gz')
            with tarfile.open(backup, 'x:gz') as archive:
                archive.add(vault, arcname=vault.name)
            exclusive(manifest_path, json.dumps(manifest, indent=2)+'\n')
            exclusive(vault/'_Research/backup.json', json.dumps({'path':str(backup)}))
    for name, expected in manifest.items():
        path = g.within(vault, name)
        if not path.is_file() or sha(path) != expected:
            raise ValueError('STOP: pre-existing Markdown changed: ' + name)
    return manifest


def check_preserved(vault, manifest):
    if vault == DEFAULT_VAULT.resolve():
        baseline = sorted((REPO/'research_backups').glob('*/markdown-sha256.json'))
        for saved in baseline:
            for name, expected in json.loads(saved.read_text()).items():
                path = REPO/name
                if not path.is_file() or sha(path) != expected:
                    raise ValueError('STOP: pre-existing repository Markdown changed: '+name)
    for name, expected in manifest.items():
        path = g.within(vault, name)
        if not path.is_file() or sha(path) != expected:
            raise ValueError('STOP: pre-existing Markdown changed: '+name)


def validate_result(result, graph, schema):
    m = result['metadata']
    for i,n in graph['nodes'].items():
        if i != m['id'] and (n['path'] == result['path'] or n['title'].casefold() == m['title'].casefold()):
            raise ValueError('Duplicate school identity or path')
    body = result['body']
    if result.get('review', {}).get('status') != 'verified':
        raise ValueError('Research result needs live evidence review')
    if m.get('type') != 'school':
        raise ValueError('Only school articles may be created')
    if m.get('status') != 'completed':
        raise ValueError('New school status must be completed')
    expected_path = 'Psychology/Schools/'+m['title']+'.md'
    if result['path'] != expected_path:
        raise ValueError('School article must use its canonical school path')
    if re.findall(r'^## (.+)$', body, re.M) != HEADINGS:
        raise ValueError('Required section headings missing or out of order')
    main, refs = body.split('## References\n', 1)
    prose = g.LINK.sub(lambda x: x[1].split('|')[-1], main)
    if len(prose.split()) > 250:
        raise ValueError('Main content exceeds 250 words')
    for heading in HEADINGS[:-1]:
        section = re.search(r'^## '+re.escape(heading)+r'\n(.*?)(?=^## |\Z)', main, re.M|re.S)
        if not section or not re.search(r'\[R[1-5]\]',section[1]):
            raise ValueError('Each main section needs a source marker: '+heading)
    urls = re.findall(r'https://[^\s)]+', refs)
    if not 3 <= len(urls) <= 5 or len(set(urls)) != len(urls):
        raise ValueError('Require 3–5 distinct reference URLs')
    reviewed = result['review'].get('sources', [])
    numbers=re.findall(r'^- \[R([1-5])\]',refs,re.M)
    if numbers != [str(i) for i in range(1,len(urls)+1)]:
        raise ValueError('References must use consecutive numbered markers')
    if not set(re.findall(r'\[R([0-9]+)\]',main)).issubset(set(numbers)):
        raise ValueError('Main content cites an undefined reference')
    if not set(urls).issubset(set(reviewed)):
        raise ValueError('Unreviewed reference URL')
    content = '---\n'+g.yaml.safe_dump(m, sort_keys=False, allow_unicode=True)+'---\n'+body
    g.parse_content(content, schema)
    nodes = copy.deepcopy(graph['nodes'])
    nodes[m['id']] = {**m, 'path':result['path'], 'pending':False}
    for entity in m.get('pending_entities', []):
        if entity['id'] not in nodes:
            folder={'school':'Schools','person':'People','concept':'Concepts'}.get(entity['type'])
            if not folder or entity['path'] != 'Psychology/'+folder+'/'+entity['title']+'.md':
                raise ValueError('New optional entities need canonical paths')
        nodes.setdefault(entity['id'], {**entity, 'pending':True})
    g.validate_entities(nodes)
    identities={}
    for i,n in nodes.items():
        for name in [n['title'], *n.get('aliases',[])]:
            key=(n['type'],name.casefold())
            if key in identities and identities[key] != i:
                raise ValueError('Duplicate entity title or alias: '+name)
            identities[key]=i
    g.person_check(body, nodes)
    for link in g.LINK.findall(body):
        if not g.resolve('[['+link+']]', nodes):
            raise ValueError('Unregistered wikilink: '+link)
    linked={g.resolve('[['+l+']]',nodes) for l in g.LINK.findall(body)}
    if not any(i in graph['nodes'] and not graph['nodes'][i].get('pending') and graph['nodes'][i]['type']=='school' for i in linked):
        raise ValueError('New school must link to an existing school in the graph')
    claims = g.extract(m, nodes, schema)
    for claim in claims:
        if claim['target'] and nodes[claim['target']]['type']=='school' and claim['target'] not in linked:
            raise ValueError('School relationship target must have a body wikilink')
        if not claim['description'] or not claim['evidence']:
            raise ValueError('Relationship needs explanation and evidence')
        if any(e['source'] not in reviewed for e in claim['evidence']):
            raise ValueError('Relationship evidence not reviewed')
        if any(not e.get('locator') or not e.get('finding') for e in claim['evidence']):
            raise ValueError('Relationship evidence needs a locator and a finding')
    return content


def traversal(graph, root):
    """School genealogy is undirected for distance; descendant neighbors enter first.

    Rival/influence links discover schools but never masquerade as genealogical depth.
    """
    children, parents, network = {}, {}, {}
    for e in graph.get('edges', []):
        s,t,r = e['source'],e['target'],e['relation']
        if not t or any(graph['nodes'][i]['type'] != 'school' for i in [s,t]):
            continue
        if r == 'developed_from': s,t = t,s
        if r in ['developed_from','branched_into']:
            children.setdefault(s,set()).add(t)
            parents.setdefault(t,set()).add(s)
        elif r in ['influenced','influenced_by','reacted_against','integrates','revises','contradicts','extends']:
            network.setdefault(s,set()).add(t)
            network.setdefault(t,set()).add(s)
    distance = {root:0}; queue = deque([root]); order = []
    while queue:
        i = queue.popleft(); order.append(i)
        for neighbors in [children.get(i, set()), parents.get(i, set())]:
            for j in sorted(neighbors, key=lambda x:(graph['nodes'][x].get('sort_year',9999), x)):
                if j not in distance:
                    distance[j] = distance[i]+1; queue.append(j)
    connections = sorted({j for i in order for j in network.get(i,set()) if j not in distance})
    return order, distance, connections



def checkpoint(vault, graph, schema, state):
    """Graph is authoritative; auxiliary projections are repaired on every resume."""
    g.persist(vault,graph,schema,False)
    for i,n in graph['nodes'].items():
        entry=state['entities'].setdefault(i,{'path':n['path'],'status':'pending'})
        if not n.get('pending'):
            entry['status']='completed'
    completed=sorted(i for i,n in graph['nodes'].items() if not n.get('pending'))
    state['completed']=completed
    g.atomic(vault/'_Research/state.json',json.dumps(state,indent=2,ensure_ascii=False)+'\n')
    g.atomic(vault/'_Research/completed.json',json.dumps(completed,indent=2)+'\n')
    # Unlike the legacy projection, this is an explicit BFS/status queue.
    root=state.get('run',{}).get('root',graph['root'])
    order,depths,connections=traversal(graph,root)
    queue=[{'id':i,'type':graph['nodes'][i]['type'],'status':state['entities'][i]['status'],
            'genealogical_depth':depths.get(i),'path':graph['nodes'][i]['path']}
           for i in order+connections if graph['nodes'][i].get('pending')]
    queue += [{'id':i,'type':n['type'],'status':state['entities'][i]['status'],
               'genealogical_depth':None,'path':n['path'],'optional':n['type']!='school'}
              for i,n in sorted(graph['nodes'].items()) if n.get('pending') and i not in order+connections]
    g.atomic(vault/'_Research/queue.json',json.dumps(queue,indent=2,ensure_ascii=False)+'\n')


def resolve_root(graph,name):
    root=g.resolve('[['+name+']]',graph['nodes'])
    if not root:
        root=next((i for i,n in graph['nodes'].items() if re.sub(r'[^a-z0-9]+','-',n['title'].lower()).strip('-')==name),None)
    if not root or graph['nodes'][root]['type']!='school': raise ValueError('Unknown school root: '+name)
    return root


def eligible(graph, state, run):
    order,depths,connections=traversal(graph,run['root'])
    limit=run['max_depth'] if run['recursive'] else min(1,run['max_depth'])
    candidates=[i for i in order if i!=run['root'] and depths[i]<=limit]
    # A cross-tradition connection has no genealogical distance. Its ANCHOR must
    # be inside the limit; max_nodes still bounds all research calls.
    if run['recursive'] and limit>0:
        within={i for i in order if depths[i]<=limit}
        anchored={e['target'] for e in graph['edges'] if e['source'] in within}
        anchored|={e['source'] for e in graph['edges'] if e['target'] in within}
        candidates += [i for i in connections if i in anchored]
    return [i for i in candidates if graph['nodes'][i].get('pending')
            and state['entities'].get(i,{}).get('status')!='needs_review'],depths


def load_context(vault,dry=False):
    manifest=preserve(vault,dry)
    schema=g.read(vault/'_Graph/schema.yaml',g.schema_default())
    graph=g.load(vault,check_projection=False)
    check_preserved(vault,manifest)
    g.verify_sources(vault,graph)
    state=g.read(vault/'_Research/state.json',{'entities':{},'completed':[]})
    # Persisted publication journals make a crash between note creation and
    # registration recoverable without another research call or any overwrite.
    current=state.get('current')
    if current:
        journal=vault/'_Research/jobs'/current['request_id']/'commit.json'
        if journal.exists():
            data=json.loads(journal.read_text()); path=g.within(vault,data['path'])
            if path.exists():
                if sha(path)!=data['sha256']: raise ValueError('STOP: interrupted publication changed: '+data['path'])
                if graph['nodes'][data['id']].get('pending'):
                    g._register(vault,path,schema,graph,dry=True,validate=True)
                run=state['run']
                if data['id'] not in run['completed']: run['completed'].append(data['id'])
                state['current']=None
    for i,n in graph['nodes'].items():
        entry=state['entities'].setdefault(i,{'path':n['path'],'status':'pending'})
        if not n.get('pending'): entry.update(status='completed')
        # Migrate the old offline-packet dead end without losing its history.
        elif 'packet' in entry.get('reason','').lower():
            entry.update(status='pending',previous_reason=entry.pop('reason'))
    return manifest,schema,graph,state


def start_run(state,root,args):
    old=state.get('run')
    configuration={'root':root,'recursive':args.recursive,'max_depth':args.max_depth,'max_nodes':args.max_nodes}
    if old and old['status']=='active':
        if any(old[k]!=v for k,v in configuration.items()):
            raise ValueError('An interrupted run has different limits. Resume with its original configuration.')
        return old
    state['run']={**configuration,'id':uuid.uuid4().hex,'status':'active','completed':[]}
    state['current']=None
    return state['run']


def request_for(vault,graph,schema,state,node_id,depth):
    node=graph['nodes'][node_id]
    template={k:node.get(k) for k in ['id','title','aliases','type']}
    template.update(domain='psychology',tradition='psychodynamic',period='20th-century',
        emergence_year=None,depth=depth,status='completed',
        tags=['domain/psychology','type/school','tradition/psychodynamic','period/20th-century'],
        pending_entities=[],relationships=[])
    known=[{k:n[k] for k in ['id','title','type','path','aliases'] if k in n}
           for n in graph['nodes'].values()]
    return {'request_id':uuid.uuid4().hex,'run_id':state['run']['id'],
        'graph_sha256':sha(vault/'_Graph/graph.json'),'node':{**node,'depth':depth},
        'metadata_template':template,'known_entities':known,
        'known_school_relationships':[e for e in graph['edges'] if e['target'] and
            graph['nodes'][e['source']]['type']=='school' and graph['nodes'][e['target']]['type']=='school'],
        'allowed_relations':list(schema['relations']),'traditions':schema['traditions'],
        'root':state['run']['root'],'main_word_limit':250,'required_headings':HEADINGS}


def prepare(vault,graph,schema,state,manifest):
    run=state['run']
    if state.get('current'): return state['current']
    if len(run['completed'])>=run['max_nodes']:
        run.update(status='stopped',stop_reason='max_nodes');checkpoint(vault,graph,schema,state);return None
    candidates,depths=eligible(graph,state,run)
    for i in candidates:
        path=g.within(vault,graph['nodes'][i]['path'])
        if path.exists():
            # Existing content is read and registered if compatible, never regenerated.
            try: g._register(vault,path,schema,graph,dry=True,validate=True)
            except ValueError as error:
                state['entities'][i].update(status='needs_review',existing=True,reason=str(error))
            else: state['entities'][i].update(status='completed',existing=True)
            checkpoint(vault,graph,schema,state)
            continue
        checkpoint(vault,graph,schema,state)
        request=request_for(vault,graph,schema,state,i,depths.get(i))
        job=vault/'_Research/jobs'/request['request_id']
        exclusive(job/'request.json',json.dumps(request,indent=2,ensure_ascii=False)+'\n')
        state['current']=request
        state['entities'][i].update(status='researching',depth=depths.get(i),path=graph['nodes'][i]['path'])
        check_preserved(vault,manifest)
        checkpoint(vault,graph,schema,state)
        return request
    run.update(status='stopped',stop_reason='eligible_queue_exhausted')
    checkpoint(vault,graph,schema,state)
    return None


def normalize_result(result,request):
    if not isinstance(result,dict) or type(result.get('available')) is not bool:
        raise ValueError('Live research must return an object with boolean availability')
    if not result.get('available'):
        raise LiveResearchUnavailable('Live research unavailable or insufficient: '+result.get('reason','unspecified'))
    if not isinstance(result.get('metadata_yaml'),str) or not isinstance(result.get('body'),str):
        raise ValueError('Live research must return YAML and Markdown strings')
    sources=result.get('sources',[])
    if not isinstance(sources,list) or any(not isinstance(source,dict) for source in sources):
        raise ValueError('Sources must be a list of source records')
    if not 3<=len(sources)<=5 or any(not all(s.get(k) for k in ['url','title','locator','finding']) for s in sources):
        raise ValueError('Live research needs 3–5 inspected sources with locators and findings')
    if len({s['url'] for s in sources})!=len(sources): raise ValueError('Duplicate source URLs')
    try: metadata=g.yaml.safe_load(result['metadata_yaml'])
    except g.yaml.YAMLError as error: raise ValueError('Invalid research frontmatter YAML') from error
    if not isinstance(metadata,dict): raise ValueError('Research frontmatter must be a mapping')
    for key in ['id','title','type']:
        if metadata.get(key)!=request['node'][key]: raise ValueError('Research changed canonical identity: '+key)
    return {'path':request['node']['path'],'metadata':metadata,'body':result['body'],
        'review':{'status':'verified','sources':[s['url'] for s in sources],
                  'checked_on':datetime.now(timezone.utc).isoformat(),'source_findings':sources}}


def commit_result(vault,graph,schema,state,manifest,request,result,provenance):
    if not state.get('current') or request['request_id']!=state['current']['request_id']:
        raise ValueError('Stale or already completed research request')
    if request['graph_sha256']!=sha(vault/'_Graph/graph.json'):
        raise ValueError('Graph changed while researching; resume and reconcile before publication')
    if not provenance.get('web_search_observed'):
        raise LiveResearchUnavailable('No live web-search evidence; refusing to publish from memory or archived packets.')
    draft=normalize_result(result,request)
    try: content=validate_result(draft,graph,schema)
    except (KeyError,TypeError,AttributeError,g.yaml.YAMLError) as error:
        raise ValueError('Invalid research structure: '+type(error).__name__) from error
    path=g.within(vault,draft['path'])
    staged=copy.deepcopy(graph)
    g._register(vault,path,schema,staged,dry=True,validate=True,content_override=content)
    check_preserved(vault,manifest)
    job=vault/'_Research/jobs'/request['request_id']
    # Keep the first accepted live result as a recovery artifact, never an input corpus.
    for name,data in [('result.json',result),('provenance.json',provenance)]:
        destination=job/name
        serialized=json.dumps(data,indent=2,ensure_ascii=False)+'\n'
        if destination.exists() and destination.read_text()!=serialized:
            raise ValueError('A different result is already staged for this request')
        if not destination.exists(): exclusive(destination,serialized)
    journal={'id':draft['metadata']['id'],'path':draft['path'],'sha256':hashlib.sha256(content.encode()).hexdigest()}
    if not (job/'commit.json').exists(): exclusive(job/'commit.json',json.dumps(journal,indent=2)+'\n')
    exclusive(path,content)
    # No Markdown writes beyond the exclusive publication above.
    graph.clear();graph.update(staged)
    i=draft['metadata']['id']
    state['entities'][i].update(status='completed',research_review=draft['review'])
    if i not in state['run']['completed']: state['run']['completed'].append(i)
    state['current']=None
    check_preserved(vault,manifest)
    checkpoint(vault,graph,schema,state)
    g.verify_sources(vault,graph)


def report(graph,state,dry=False,planned=None):
    run=state.get('run',{})
    return {'dry_run':dry,'schools_researched':len(run.get('completed',[])),
        'created_this_run':run.get('completed',[]),'planned':planned or [],
        'unresolved_entities':sum(bool(n.get('pending')) for n in graph['nodes'].values()),
        'pending_schools':sum(n['type']=='school' and bool(n.get('pending')) for n in graph['nodes'].values()),
        'relationships':len(graph['edges']),
        'claims_requiring_review':sum(bool(e.get('review_required')) or e.get('confidence') in ['low','uncertain'] for e in graph['edges']),
        'stop_reason':run.get('stop_reason','awaiting_live_research'),
        'run_id':run.get('id'),'request_id':state.get('current',{}).get('request_id') if state.get('current') else None}


def run(args):
    vault=Path(args.vault).resolve()
    if args.max_depth<0 or args.max_nodes<0: raise ValueError('Limits must be nonnegative')
    with g.lock(vault,args.dry_run):
        manifest,schema,graph,state=load_context(vault,args.dry_run)
        root=resolve_root(graph,args.root)
        if args.dry_run:
            run_config={'root':root,'recursive':args.recursive,'max_depth':args.max_depth,'max_nodes':args.max_nodes}
            candidates,depths=eligible(graph,state,run_config)
            plan=[{'id':i,'path':graph['nodes'][i]['path'],'genealogical_depth':depths.get(i),
                   'action':'register_existing' if g.within(vault,graph['nodes'][i]['path']).exists() else 'research_live'}
                  for i in candidates[:args.max_nodes]]
            value=report(graph,{},True,plan)
            value.update(stop_reason='dry_run',discovery='Further schools are discovered during live research; no invented preview.')
            return value
        start_run(state,root,args)
        checkpoint(vault,graph,schema,state)
        request=prepare(vault,graph,schema,state,manifest)
        if args.mode=='session':
            value=report(graph,state)
            if request:
                value.update(request_file=str(vault/'_Research/jobs'/request['request_id']/'request.json'),
                             research_prompt=research_prompt(request))
            return value
        while request:
            try:
                print('Researching '+request['node']['title']+' with live Codex web tools.',file=sys.stderr,flush=True)
                result,provenance=live_research(request,executable=args.codex,timeout=args.timeout)
                commit_result(vault,graph,schema,state,manifest,request,result,provenance)
            except (LiveResearchUnavailable,ValueError,OSError) as error:
                i=request['node']['id'];state['entities'][i].update(status='needs_review',reason=str(error))
                # Keep current lease and active run so a retry uses the same node/budget.
                checkpoint(vault,graph,schema,state)
                value=report(graph,state);value.update(stop_reason='research_failed',error=str(error))
                g.atomic(vault/'_Research/report.json',json.dumps(value,indent=2)+'\n')
                raise
            request=prepare(vault,graph,schema,state,manifest)
        value=report(graph,state)
        g.atomic(vault/'_Research/report.json',json.dumps(value,indent=2)+'\n')
        return value


def complete(args):
    """Commit a response researched by the current Codex session's web tools."""
    vault=Path(args.vault).resolve()
    with g.lock(vault,False):
        manifest,schema,graph,state=load_context(vault)
        supplied=json.loads(Path(args.request).read_text())
        if not state.get('current'):
            # A committed journal may have been recovered during load_context.
            if supplied['node']['id'] in state.get('run',{}).get('completed',[]):
                if state['run']['status']!='active': return report(graph,state)
                request=prepare(vault,graph,schema,state,manifest)
                value=report(graph,state)
                if request: value['request_file']=str(vault/'_Research/jobs'/request['request_id']/'request.json')
                return value
            raise ValueError('No active research request')
        if supplied!=state['current']: raise ValueError('Stale research request')
        result=json.loads(Path(args.result).read_text())
        evidence=json.loads(Path(args.web_evidence).read_text())
        # Session mode cannot observe another process's tools. Require an explicit
        # audit of actual web calls rather than silently trusting an archived draft.
        calls=evidence.get('calls',[])
        if evidence.get('provider')!='codex-session' or not any(c.get('tool') in ['web.run','web__run'] and c.get('action')=='search' for c in calls):
            raise LiveResearchUnavailable('Session completion requires a live web-search audit')
        inspected={c.get('url') for c in calls if c.get('action')=='open'}
        if not {s['url'] for s in result.get('sources',[])}.issubset(inspected):
            raise ValueError('Every cited source must have an inspected-page audit entry')
        commit_result(vault,graph,schema,state,manifest,supplied,result,
                      {**evidence,'web_search_observed':True})
        request=prepare(vault,graph,schema,state,manifest)
        value=report(graph,state)
        if request: value['request_file']=str(vault/'_Research/jobs'/request['request_id']/'request.json')
        g.atomic(vault/'_Research/report.json',json.dumps(value,indent=2)+'\n')
        return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ['research','next']:
        p=sub.add_parser(command)
        p.add_argument('--vault',default=str(DEFAULT_VAULT));p.add_argument('--root',default='psychoanalysis')
        p.add_argument('--recursive',action='store_true');p.add_argument('--max-depth',type=int,default=5)
        p.add_argument('--max-nodes',type=int,default=3);p.add_argument('--dry-run',action='store_true')
        p.add_argument('--mode',choices=['codex','session'],default='session' if command=='next' else 'codex')
        p.add_argument('--codex',default='codex',help='Codex executable, with an authenticated account and live search')
        p.add_argument('--timeout',type=int,default=900,help='Maximum seconds for one live research request')
    p=sub.add_parser('complete');p.add_argument('--vault',default=str(DEFAULT_VAULT))
    p.add_argument('--request',required=True);p.add_argument('--result',required=True);p.add_argument('--web-evidence',required=True)
    args=parser.parse_args()
    try:
        if getattr(args,'timeout',1)<=0: raise ValueError('timeout must be positive')
        print(json.dumps(complete(args) if args.command=='complete' else run(args),indent=2,ensure_ascii=False))
    except (ValueError,OSError,LiveResearchUnavailable) as error: parser.exit(1,str(error)+'\n')
