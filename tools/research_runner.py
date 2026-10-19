"""BFS scheduler consuming evidence-reviewed research packets; never fabricates research."""
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
import tarfile
import tempfile
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = REPO / 'world knowledge/psychoanalysis'
spec = importlib.util.spec_from_file_location('vault_graph', DEFAULT_VAULT/'tools/graph_builder.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
HEADINGS = ['Who / When', 'What', 'Why', 'How', 'What changed', 'Developments', 'References']


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
        if baseline:
            for name, expected in json.loads(baseline[0].read_text()).items():
                path = REPO/name
                if not path.is_file() or sha(path) != expected:
                    raise ValueError('STOP: pre-existing repository Markdown changed: '+name)
    for name, expected in manifest.items():
        path = g.within(vault, name)
        if not path.is_file() or sha(path) != expected:
            raise ValueError('STOP: pre-existing Markdown changed: '+name)


def validate_packet(packet, graph, schema):
    m = packet['metadata']
    for i,n in graph['nodes'].items():
        if i != m['id'] and (n['path'] == packet['path'] or n['title'].casefold() == m['title'].casefold()):
            raise ValueError('Duplicate school identity or path')
    body = packet['body']
    if packet.get('review', {}).get('status') != 'verified':
        raise ValueError('Research packet needs evidence review')
    if re.findall(r'^## (.+)$', body, re.M) != HEADINGS:
        raise ValueError('Required section headings missing or out of order')
    main, refs = body.split('## References\n', 1)
    prose = g.LINK.sub(lambda x: x[1].split('|')[-1], main)
    if len(prose.split()) > 250:
        raise ValueError('Main content exceeds 250 words')
    urls = re.findall(r'https://[^\s)]+', refs)
    if not 3 <= len(urls) <= 5 or len(set(urls)) != len(urls):
        raise ValueError('Require 3–5 distinct reference URLs')
    reviewed = packet['review'].get('sources', [])
    if not set(urls).issubset(set(reviewed)):
        raise ValueError('Unreviewed reference URL')
    content = '---\n'+g.yaml.safe_dump(m, sort_keys=False, allow_unicode=True)+'---\n'+body
    g.parse_content(content, schema)
    nodes = copy.deepcopy(graph['nodes'])
    nodes[m['id']] = {**m, 'path':packet['path'], 'pending':False}
    for entity in m.get('pending_entities', []):
        nodes.setdefault(entity['id'], {**entity, 'pending':True})
    g.validate_entities(nodes)
    g.person_check(body, nodes)
    for link in g.LINK.findall(body):
        if not g.resolve('[['+link+']]', nodes):
            raise ValueError('Unregistered wikilink: '+link)
    claims = g.extract(m, nodes, schema)
    for claim in claims:
        if not claim['description'] or not claim['evidence']:
            raise ValueError('Relationship needs explanation and evidence')
        if any(e['source'] not in reviewed for e in claim['evidence']):
            raise ValueError('Relationship evidence not reviewed')
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


def snapshots(vault, graph, schema):
    # Every pass gets fresh names, preserving ALL old drawings, including generated ones.
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = '_Research/maps/'+stamp
    (vault/folder).mkdir(parents=True,exist_ok=False)
    for view,layout in [('schools','radial'),('schools','timeline'),('all','radial')]:
        g.export(vault, graph, schema, SimpleNamespace(view=view, layout=layout,
            root=graph['root'], output=f'{folder}/{view}-{layout}.generated.excalidraw',dry_run=False))
    genealogy = [e for e in graph['edges'] if e['relation'] in ['developed_from','branched_into']
                 and e['target'] and all(graph['nodes'][i]['type']=='school' for i in [e['source'],e['target']])]
    exclusive(vault/f'{folder}/genealogy.json', json.dumps(genealogy, indent=2)+'\n')
    exclusive(vault/f'{folder}/network.json', json.dumps({'nodes':graph['nodes'],'edges':graph['edges']},indent=2)+'\n')
    g.atomic(vault/'_Research/latest_maps.json', json.dumps({'directory':folder},indent=2)+'\n')


def run(args):
    vault = Path(args.vault).resolve()
    if args.max_depth < 0 or args.max_nodes < 0:
        raise ValueError('Limits must be nonnegative')
    with g.lock(vault, args.dry_run):
        manifest = preserve(vault, args.dry_run)
        schema = g.read(vault/'_Graph/schema.yaml', g.schema_default())
        graph = g.load(vault, check_projection=False)
        g.verify_sources(vault,graph)
        check_preserved(vault,manifest)
        # Refresh root relationships by reading, never rewriting, the original note.
        root = g.resolve('[['+args.root+']]', graph['nodes'])
        if not root:
            root = next((i for i,n in graph['nodes'].items() if re.sub(r'[^a-z0-9]+','-',n['title'].lower()).strip('-') == args.root), None)
        if not root: raise ValueError('Unknown root: '+args.root)
        g.register(vault, g.within(vault,graph['nodes'][root]['path']),schema,graph,dry=True,validate=True)
        packets = json.loads(Path(args.packets).read_text())['packets']
        packet_index = {}
        for packet in packets:
            i = packet['metadata']['id']
            if i in packet_index: raise ValueError('Duplicate packet ID: '+i)
            packet_index[i] = packet
        state_path = vault/'_Research/state.json'
        state = g.read(state_path, {'entities':{},'completed':[]})
        for i,n in graph['nodes'].items():
            entry = state['entities'].setdefault(i, {'path':n['path'],'status':'pending'})
            if not n.get('pending'):
                entry.update(status='completed',existing=i not in state['completed'])
            elif entry['status']=='researching':
                entry['status']='pending'
        count = 0; planned = []; attempted = set(); maps_needed = False
        while count < args.max_nodes:
            g.rebuild(graph,schema)
            order, depths, connections = traversal(graph,root)
            candidates = [i for i in order if i != root and graph['nodes'][i].get('pending')
                and depths[i] <= (args.max_depth if args.recursive else min(1,args.max_depth)) and i not in attempted]
            if not candidates and args.recursive and args.max_depth > 0:
                candidates = [i for i in connections if graph['nodes'][i].get('pending') and i not in attempted]
            if not candidates: break
            i = candidates[0]; attempted.add(i); node = graph['nodes'][i]
            path = g.within(vault,node['path'])
            state['entities'][i] = {'status':'researching','depth':depths.get(i),'path':node['path']}
            if not args.dry_run: g.atomic(state_path,json.dumps(state,indent=2)+'\n')
            try:
                if path.exists():
                    g.register(vault,path,schema,graph,dry=args.dry_run)
                    state['entities'][i].update(status='completed',existing=True)
                    if args.dry_run: graph['nodes'][i]['pending'] = False
                    maps_needed = True
                    continue
                packet = packet_index.get(i)
                if not packet:
                    state['entities'][i].update(status='needs_review',reason='No evidence-reviewed research packet available')
                    continue
                if packet['path'] != node['path']: raise ValueError('Packet path differs from registry')
                content = validate_packet(packet, graph, schema)
                g.register(vault,path,schema,graph,dry=True,validate=True,content_override=content)
                planned.append({'id':i,'path':node['path'],'genealogical_depth':depths.get(i)})
                if args.dry_run:
                    staged = copy.deepcopy(graph)
                    g._register(vault,path,schema,staged,dry=True,validate=True,content_override=content)
                    graph = staged
                else:
                    check_preserved(vault,manifest)
                    exclusive(path,content)
                    g.register(vault,path,schema,graph)
                    check_preserved(vault,manifest)
                    snapshots(vault,graph,schema)
                count += 1
                state['entities'][i].update(status='completed',packet_review=packet['review'])
                if i not in state['completed']: state['completed'].append(i)
                if not args.dry_run:
                    g.atomic(vault/'_Research/completed.json',json.dumps(sorted(j for j,n in graph['nodes'].items() if not n.get('pending')),indent=2)+'\n')
            except Exception as error:
                state['entities'][i].update(status='needs_review',reason=str(error))
                if not args.dry_run: g.atomic(state_path,json.dumps(state,indent=2)+'\n')
                raise
            finally:
                if not args.dry_run:
                    check_preserved(vault,manifest)
                    g.atomic(state_path,json.dumps(state,indent=2)+'\n')
        order, depths, connections = traversal(graph,root)
        for i,n in graph['nodes'].items():
            state['entities'].setdefault(i,{'status':'pending' if n.get('pending') else 'completed','path':n['path']})
        # Connections without a lineage are retained, but cannot consume genealogy depth.
        for i in connections:
            state['entities'][i]['genealogical_depth'] = None
        report = {'dry_run':args.dry_run,'schools_researched':count,'planned_or_created':planned,
            'unresolved_entities':sum(n.get('pending',False) for n in graph['nodes'].values()),
            'pending_schools':sum(n['type']=='school' and n.get('pending',False) for n in graph['nodes'].values()),
            'relationships':len(graph.get('edges',[])),
            'claims_requiring_review':sum(bool(e.get('review_required')) or e.get('confidence') in ['low','uncertain'] for e in graph.get('edges',[])),
            'stop_reason':'max_nodes' if count == args.max_nodes else 'eligible_queue_exhausted',
            'max_depth':args.max_depth,'max_nodes':args.max_nodes}
        if not args.dry_run:
            g.persist(vault,graph,schema,False)
            g.atomic(state_path,json.dumps(state,indent=2)+'\n')
            g.atomic(vault/'_Research/completed.json',json.dumps(sorted(i for i,n in graph['nodes'].items() if not n.get('pending')),indent=2)+'\n')
            g.atomic(vault/'_Research/report.json',json.dumps(report,indent=2)+'\n')
            if maps_needed or not (vault/'_Research/latest_maps.json').exists(): snapshots(vault,graph,schema)
            check_preserved(vault,manifest)
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('research')
    p.add_argument('--vault',default=str(DEFAULT_VAULT))
    p.add_argument('--root',default='psychoanalysis')
    p.add_argument('--recursive',action='store_true')
    p.add_argument('--max-depth',type=int,default=5)
    p.add_argument('--max-nodes',type=int,default=3)
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--packets',default=str(REPO/'research/packets.json'))
    args=parser.parse_args()
    try: print(json.dumps(run(args),indent=2))
    except (ValueError,OSError) as error: parser.exit(1,str(error)+'\n')
