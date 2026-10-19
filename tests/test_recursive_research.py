import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'tools'))
import research_runner as r
import codex_research as backend


def response(request,discover=None,parent='Psychoanalysis'):
    """Synthetic live-provider output for deterministic offline tests only."""
    m=copy.deepcopy(request['metadata_template'])
    m['emergence_year']=1950
    urls=['https://example.org/source-'+str(i) for i in range(1,4)]
    evidence=[{'source':urls[0],'locator':'History','finding':'Synthetic test evidence.'}]
    m['relationships']=[{'relation':'developed_from','target':'[[Psychology/Schools/'+parent+']]','description':'Test lineage.','confidence':'high','evidence':evidence}]
    body='\n\n'.join('## '+h+'\n'+('An institutional movement. [R1]' if h!='Developments' else
        'A development within [[Psychology/Schools/'+parent+']]. No separate rival is asserted. [R1]') for h in r.HEADINGS[:-1])
    if discover:
        m['pending_entities'].append({'id':'psy-school-'+discover.lower().replace(' ','-'),
            'title':discover,'type':'school','aliases':[],'path':'Psychology/Schools/'+discover+'.md'})
        m['relationships'].append({'relation':'branched_into','target':'[[Psychology/Schools/'+discover+']]','description':'Test descendant.','confidence':'high','evidence':evidence})
        body+='\nSuccessor: [[Psychology/Schools/'+discover+']]. [R1]'
    body+='\n\n## References\n'+'\n'.join('- [R'+str(i)+'] [Test source]('+url+')' for i,url in enumerate(urls,1))+'\n'
    return {'available':True,'reason':'','metadata_yaml':r.g.yaml.safe_dump(m,sort_keys=False),'body':body,
            'sources':[{'url':url,'title':'Synthetic test source','locator':'History','finding':'Test fixture, not historical evidence.'} for url in urls]}


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.vault=Path(self.tmp.name)/'vault';shutil.copytree(r.DEFAULT_VAULT,self.vault)
        shutil.rmtree(self.vault/'_Research',ignore_errors=True)
        for note in (self.vault/'Psychology/Schools').glob('*.md'):
            if note.name!='Psychoanalysis.md': note.unlink()
        graph={'version':1,'root':r.g.ROOT,'nodes':{},'claims':{}}
        schema=r.g.read(self.vault/'_Graph/schema.yaml')
        r.g.register(self.vault,self.vault/'Psychology/Schools/Psychoanalysis.md',schema,graph)
        self.before={str(p.relative_to(self.vault)):p.read_bytes() for p in self.vault.rglob('*') if p.is_file() and p.suffix in ['.md','.excalidraw','.png','.svg']}
        self.calls=[]
        def fake(request,**kw):
            self.calls.append(request['node']['id'])
            return response(request),{'provider':'test-double','web_search_observed':True}
        self.fake=fake

    def args(self,**kw):
        data=dict(vault=str(self.vault),root='psychoanalysis',recursive=True,max_depth=5,
                  max_nodes=3,dry_run=False,mode='codex',codex='codex',timeout=60)
        data.update(kw);return SimpleNamespace(**data)

    def files(self):
        return {str(p.relative_to(self.vault)):p.read_bytes() for p in self.vault.rglob('*') if p.is_file()}

    def test_dry_run_has_no_side_effects_or_research(self):
        before=self.files()
        with patch.object(r,'live_research',side_effect=AssertionError('must not research')):
            report=r.run(self.args(dry_run=True))
        self.assertEqual(before,self.files())
        self.assertEqual(len(report['planned']),3)
        self.assertEqual(report['schools_researched'],0)

    def test_live_default_one_note_at_a_time_preserves_all_files_and_no_visuals(self):
        def sequential(request,**kw):
            # Every prior result is committed before the next research call.
            if self.calls:
                graph=r.g.load(self.vault)
                self.assertFalse(graph['nodes'][self.calls[-1]]['pending'])
            return self.fake(request)
        before_visuals={p for p in self.vault.rglob('*') if p.suffix in ['.excalidraw','.png','.svg']}
        with patch.object(r,'live_research',side_effect=sequential), patch.object(r.g,'export',side_effect=AssertionError('no visualizations')):
            report=r.run(self.args())
        self.assertEqual(report['schools_researched'],3)
        self.assertEqual(len(set(self.calls)),3)
        for name,content in self.before.items(): self.assertEqual((self.vault/name).read_bytes(),content)
        self.assertEqual(before_visuals,{p for p in self.vault.rglob('*') if p.suffix in ['.excalidraw','.png','.svg']})
        self.assertFalse((self.vault/'_Research/maps').exists())
        self.assertEqual(len(list((self.vault/'Psychology/Schools').glob('*.md'))),4)

    def test_recursive_discovery_and_depth(self):
        def discover(request,**kw):
            self.calls.append(request['node']['id'])
            child='Discovery School' if request['node']['title']=='Individual Psychology' else None
            parent='Individual Psychology' if request['node']['title']=='Discovery School' else 'Psychoanalysis'
            return response(request,child,parent),{'web_search_observed':True}
        with patch.object(r,'live_research',side_effect=discover):
            report=r.run(self.args(max_depth=1,max_nodes=10))
        self.assertEqual(report['schools_researched'],3)
        self.assertNotIn('psy-school-discovery-school',self.calls)
        self.calls=[]
        with patch.object(r,'live_research',side_effect=discover):
            report=r.run(self.args(max_depth=2,max_nodes=1))
        self.assertEqual(report['schools_researched'],1)
        self.assertEqual(self.calls,['psy-school-discovery-school'])

    def test_failure_resume_keeps_budget_and_does_not_duplicate(self):
        def fail_second(request,**kw):
            if self.calls: raise backend.LiveResearchUnavailable('network unavailable')
            return self.fake(request)
        with patch.object(r,'live_research',side_effect=fail_second):
            with self.assertRaisesRegex(backend.LiveResearchUnavailable,'network'): r.run(self.args(max_nodes=2))
        with patch.object(r,'live_research',side_effect=self.fake):
            result=r.run(self.args(max_nodes=2))
        self.assertEqual(result['schools_researched'],2)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(len(set(self.calls)),2)
        self.assertEqual(len(list((self.vault/'Psychology/Schools').glob('*.md'))),3)

    def test_interruption_after_exclusive_publication_resumes_without_research(self):
        original=r.checkpoint
        def interrupt(vault,graph,schema,state):
            if state['run']['completed']: raise RuntimeError('simulated crash')
            return original(vault,graph,schema,state)
        with patch.object(r,'live_research',side_effect=self.fake),patch.object(r,'checkpoint',side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError,'crash'):r.run(self.args(max_nodes=1))
        self.assertEqual(len(self.calls),1)
        with patch.object(r,'live_research',side_effect=AssertionError('must recover existing note')):
            report=r.run(self.args(max_nodes=1))
        self.assertEqual(report['schools_researched'],1)

    def test_depth_zero_no_research(self):
        with patch.object(r,'live_research',side_effect=AssertionError('no calls')):
            self.assertEqual(r.run(self.args(max_depth=0))['schools_researched'],0)

    def test_exclusive_existing_note(self):
        path=self.vault/'manual.md';path.write_text('manual')
        with self.assertRaises(FileExistsError): r.exclusive(path,'new')
        self.assertEqual(path.read_text(),'manual')

    def test_tampering_stops_before_research(self):
        r.run(self.args(max_nodes=0))
        path=self.vault/'Psychology/Schools/Psychoanalysis.md';path.write_text(path.read_text()+'changed')
        with patch.object(r,'live_research',side_effect=AssertionError('no calls')):
            with self.assertRaisesRegex(ValueError,'STOP'):r.run(self.args())

    def test_unavailable_live_tools_explicit_no_packet_fallback(self):
        with patch.object(r,'live_research',side_effect=backend.LiveResearchUnavailable('live web unavailable')):
            with self.assertRaisesRegex(backend.LiveResearchUnavailable,'web unavailable'):r.run(self.args())
        self.assertEqual(len(list((self.vault/'Psychology/Schools').glob('*.md'))),1)
        state=json.loads((self.vault/'_Research/state.json').read_text())
        self.assertEqual(state['entities']['psy-school-individual-psychology']['status'],'needs_review')
        self.assertTrue(state['current'])

    def test_missing_web_evidence_rejected(self):
        with patch.object(r,'live_research',side_effect=lambda req,**kw:(response(req),{})):
            with self.assertRaisesRegex(backend.LiveResearchUnavailable,'No live web'):r.run(self.args())

    def test_invalid_result_and_duplicate_identity_rejected(self):
        info=r.run(self.args(mode='session',max_nodes=1))
        req=json.loads(Path(info['request_file']).read_text())
        manifest,schema,graph,state=r.load_context(self.vault)
        data=response(req);data['body']=data['body'].replace('## What\n','## Missing\n')
        normalized=r.normalize_result(data,req)
        with self.assertRaisesRegex(ValueError,'headings'):r.validate_result(normalized,graph,schema)
        data=response(req);m=r.g.yaml.safe_load(data['metadata_yaml']);m['pending_entities']=[{
            'id':'duplicate-root','title':'Psychoanalysis','type':'school','aliases':[],
            'path':'Psychology/Schools/Psychoanalysis.md'}];data['metadata_yaml']=r.g.yaml.safe_dump(m)
        with self.assertRaises(ValueError):r.validate_result(r.normalize_result(data,req),graph,schema)

    def test_session_handoff_requires_inspected_sources_and_resumes_idempotently(self):
        first=r.run(self.args(mode='session',max_nodes=1))
        resumed=r.run(self.args(mode='session',max_nodes=1))
        self.assertEqual(first['request_file'],resumed['request_file'])
        req=json.loads(Path(first['request_file']).read_text());result=response(req)
        output=Path(self.tmp.name)/'result.json';output.write_text(json.dumps(result))
        audit=Path(self.tmp.name)/'audit.json';audit.write_text(json.dumps({'provider':'codex-session','calls':[
            {'tool':'web.run','action':'search','query':'history'},
            *[{'tool':'web.run','action':'open','url':s['url']} for s in result['sources']]]}))
        args=SimpleNamespace(vault=str(self.vault),request=first['request_file'],result=str(output),web_evidence=str(audit))
        self.assertEqual(r.complete(args)['schools_researched'],1)
        before=self.files()
        self.assertEqual(r.complete(args)['schools_researched'],1)
        self.assertEqual(before,self.files())

    def test_bfs_multiple_parents_cycles_rivals(self):
        graph={'nodes':{i:{'type':'school'} for i in ['root','child','grandchild','parent','rival']},
            'edges':[{'source':s,'target':t,'relation':rel} for s,t,rel in [
                ('root','child','branched_into'),('child','grandchild','branched_into'),
                ('parent','root','branched_into'),('grandchild','root','branched_into'),('root','rival','influenced')]]}
        order,depth,connections=r.traversal(graph,'root')
        self.assertEqual(len(order),len(set(order)));self.assertEqual(depth['child'],1)
        self.assertEqual(depth['parent'],1);self.assertIn('rival',connections);self.assertNotIn('rival',depth)


class CodexTransportTests(unittest.TestCase):
    def test_codex_live_search_read_only_and_structured_output(self):
        request={'node':{'title':'Test School'}}
        result={'available':True,'reason':'','metadata_yaml':'','body':'','sources':[]}
        def execute(command,**kw):
            self.assertIn('--search',command);self.assertIn('read-only',command)
            self.assertIn('--output-schema',command);self.assertIn('exactly',kw['input'])
            Path(command[command.index('--output-last-message')+1]).write_text(json.dumps(result))
            return subprocess.CompletedProcess(command,0,json.dumps({'type':'item.completed','item':{'type':'web_search'}})+'\n','')
        with patch.object(backend.shutil,'which',return_value='/test/codex'),patch.object(backend.subprocess,'run',side_effect=execute):
            value,provenance=backend.research(request)
        self.assertEqual(value,result);self.assertTrue(provenance['web_search_observed'])

    def test_no_live_event_is_explicit_failure(self):
        with patch.object(backend.shutil,'which',return_value='/test/codex'),patch.object(backend.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')):
            with self.assertRaisesRegex(backend.LiveResearchUnavailable,'no completed web-search'):backend.research({})

    def test_missing_cli_explicit_failure(self):
        with patch.object(backend.shutil,'which',return_value=None):
            with self.assertRaisesRegex(backend.LiveResearchUnavailable,'not installed'):backend.research({})

if __name__=='__main__':unittest.main()
