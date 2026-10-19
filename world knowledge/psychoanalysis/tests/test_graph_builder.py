import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

TOOL=Path(__file__).resolve().parents[1]/'tools/graph_builder.py'
spec=importlib.util.spec_from_file_location('builder',TOOL)
b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)

class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.v=Path(self.temp.name); self.schema=b.schema_default()
        self.g={'version':1,'root':b.ROOT,'nodes':{},'claims':{}}
        b.atomic(self.v/'_Graph/schema.yaml',yaml.safe_dump(self.schema))
        self.root=self.note('Psychoanalysis',b.ROOT,year=1896)
        self.add(self.root)

    def note(self,title,id=None,parents=(),year=1912,extra=None):
        id=id or 'psy-school-'+title.lower().replace(' ','-')
        m=dict(id=id,title=title,aliases=[],type='school',domain='psychology',tradition='depth-psychology',period='1910s',emergence_year=year,depth=None,status='fixture',tags=['domain/psychology','type/school','tradition/depth-psychology','period/1910s'])
        if parents: m['developed_from']=['[['+p+']]' for p in parents]
        m.update(extra or {})
        path=self.v/'Psychology/Schools'/f'{title}.md'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('---\n'+yaml.safe_dump(m,sort_keys=False)+'---\n# '+title+'\n\nManual paragraph: preserve exactly.\n')
        return path

    def add(self,path,**kw):
        return b.register(self.v,path,self.schema,self.g,**kw)

    def modify(self,path,**changes):
        m,body,_=b.parse(path,self.schema); m.update(changes)
        path.write_text('---\n'+yaml.safe_dump(m,sort_keys=False)+'---\n'+body)

    def snapshot(self):
        return {str(p.relative_to(self.v)):p.read_bytes() for p in self.v.rglob('*') if p.is_file()}

    def fixture(self):
        a=self.note('Analytical Psychology',parents=['Psychoanalysis']); self.add(a)
        o=self.note('Object Relations',parents=['Psychoanalysis']); self.add(o)
        r=self.note('Relational Psychoanalysis',parents=['Object Relations']); self.add(r)
        return a,o,r

    def test_depth_and_cross_links(self):
        a,o,r=self.fixture()
        self.modify(self.root,influenced=['[[Relational Psychoanalysis]]']); self.add(self.root)
        depths=b.distances(self.g,b.ROOT)
        self.assertEqual(depths[b.ROOT],0)
        self.assertEqual(depths['psy-school-analytical-psychology'],1)
        self.assertEqual(depths['psy-school-relational-psychoanalysis'],2)
        self.assertEqual(b.distances(self.g,b.ROOT,'network')['psy-school-relational-psychoanalysis'],1)

    def test_idempotency_and_preservation(self):
        a,_,_=self.fixture(); before=self.snapshot(); self.add(a)
        self.assertEqual(before,self.snapshot())
        self.assertEqual(len(self.g['claims']['psy-school-analytical-psychology']),1)

    def test_stale_owned_edges_and_other_owner(self):
        a,_,_=self.fixture()
        self.modify(self.root,branched_into=['[[Analytical Psychology]]']); self.add(self.root)
        self.modify(a,developed_from=[]); body=b.parse(a,self.schema)[1]; self.add(a)
        self.assertEqual(self.g['claims']['psy-school-analytical-psychology'],[])
        self.assertTrue(any(e['owner']==b.ROOT and e['target']=='psy-school-analytical-psychology' for e in self.g['edges']))
        self.assertEqual(b.parse(a,self.schema)[1],body)

    def test_missing_and_later_resolution(self):
        a=self.note('Analytical Psychology',parents=['Missing School']); result=self.add(a)
        self.assertIsNone(self.g['edges'][0]['target']); self.assertTrue(self.g['edges'][0]['pending'])
        self.assertFalse((self.v/'Psychology/Schools/Missing School.md').exists())
        self.add(self.note('Missing School',parents=['Psychoanalysis']))
        self.assertEqual(b.distances(self.g,b.ROOT)['psy-school-analytical-psychology'],2)

    def test_cycles_multiple_inheritance_disconnected(self):
        a,o,r=self.fixture()
        self.modify(o,developed_from=['[[Psychoanalysis]]','[[Relational Psychoanalysis]]']); self.add(o)
        self.modify(r,developed_from=['[[Object Relations]]','[[Analytical Psychology]]']); self.add(r)
        self.add(self.note('Disconnected'))
        self.assertEqual(b.distances(self.g,b.ROOT)['psy-school-relational-psychoanalysis'],2)
        self.assertIsNone(self.g['nodes']['psy-school-disconnected']['depth'])

    def test_dry_run_validate(self):
        a=self.note('Analytical Psychology',parents=['Psychoanalysis']); before=self.snapshot()
        self.add(a,dry=True); self.assertEqual(before,self.snapshot())
        self.add(a,validate=True); self.assertEqual(before,self.snapshot())

    def test_immutable_id_conflict_and_rename(self):
        self.modify(self.root,id='other-id')
        with self.assertRaisesRegex(ValueError,'immutable'): self.add(self.root)
        self.modify(self.root,id=b.ROOT)
        other=self.note('Duplicate',id=b.ROOT)
        with self.assertRaisesRegex(ValueError,'Duplicate stable'): self.add(other)
        renamed=self.root.with_name('Renamed.md'); self.root.rename(renamed); self.add(renamed)
        self.assertEqual(self.g['nodes'][b.ROOT]['path'],'Psychology/Schools/Renamed.md')

    def person_fixture(self):
        person=dict(id='psy-person-sigmund-freud',title='Sigmund Freud',aliases=['Freud'],type='person',path='Psychology/People/Sigmund Freud.md')
        relation=dict(source='[[psy-person-sigmund-freud]]',relation='founded',target='[[Psychoanalysis]]',date=1896,description='Fixture',confidence='high',evidence=[{'source':'https://example.org/fixture'}])
        self.modify(self.root,pending_entities=[person],relationships=[relation])
        text=self.root.read_text(); self.root.write_text(text+'\n[[Psychology/People/Sigmund Freud|Sigmund Freud]] and [[Psychology/People/Sigmund Freud|Freud]].\n')
        self.add(self.root)
        return person

    def test_person_canonical_links_and_direction(self):
        self.person_fixture(); edge=self.g['edges'][0]
        self.assertEqual((edge['source'],edge['relation'],edge['target']),('psy-person-sigmund-freud','founded',b.ROOT))
        self.assertEqual(b.resolve('[[Freud]]',self.g['nodes']),'psy-person-sigmund-freud')
        self.assertFalse((self.v/'Psychology/People/Sigmund Freud.md').exists())
        self.assertEqual(len(b.selected_nodes(self.g,'schools')),1)
        self.assertEqual(len(b.selected_nodes(self.g,'people')),2)
        self.assertEqual(b.distances(self.g,b.ROOT),{b.ROOT:0})
        self.root.write_text(self.root.read_text()+'Freud wrote this.\n')
        with self.assertRaisesRegex(ValueError,'Unlinked person'): self.add(self.root)

    def test_person_duplicate_and_reference_exemption(self):
        person=self.person_fixture(); other={**person,'id':'psy-person-duplicate','path':'Psychology/People/Duplicate.md'}
        self.modify(self.root,pending_entities=[person,other])
        with self.assertRaisesRegex(ValueError,'Duplicate person'): self.add(self.root)
        self.g=b.load(self.v)
        self.modify(self.root,pending_entities=[person]); self.root.write_text(self.root.read_text()+'\n## References\nFreud, Sigmund. A fixture.\n')
        self.add(self.root)

    def test_person_schema_minimal(self):
        self.person_fixture()
        p=self.v/'Psychology/People/Sigmund Freud.md'; p.parent.mkdir(parents=True)
        m=dict(id='psy-person-sigmund-freud',title='Sigmund Freud',aliases=['Freud'],type='person',domain='psychology',birth_year=1856,death_year=1939,tags=['domain/psychology','type/person'])
        p.write_text('---\n'+yaml.safe_dump(m)+'---\nA biography fixture.\n'); self.add(p)
        self.assertFalse(self.g['nodes'][m['id']]['pending'])

    def test_visualization_generation_is_disabled(self):
        from types import SimpleNamespace
        before=self.snapshot()
        for view in ['schools','people','concepts','all']:
            args=SimpleNamespace(view=view,root=b.ROOT,layout='radial',output=None,dry_run=False)
            with self.assertRaisesRegex(ValueError,'native Graph View'):
                b.export(self.v,self.g,self.schema,args)
        self.assertEqual(before,self.snapshot())

    def test_yaml_projection_and_backups(self):
        self.fixture(); self.assertEqual(b.read(self.v/'_Graph/relationships.yaml')['relationships'],self.g['edges'])
        self.assertTrue((self.v/'_Graph/graph.json.bak').exists())
        self.root.write_text('---\ntitle: [broken\n---\n')
        before=(self.v/'_Graph/graph.json').read_bytes()
        with self.assertRaises(yaml.YAMLError): self.add(self.root)
        self.assertEqual(before,(self.v/'_Graph/graph.json').read_bytes())

    def test_import_idempotency_and_cli(self):
        a=self.note('Seed School',parents=['Psychoanalysis'])
        m,body,_=b.parse(a,self.schema); a.unlink(); m['body']=body
        manifest=self.v/'seed.yaml'; manifest.write_text(yaml.safe_dump({'nodes':[m]}))
        def run(*args):
            return subprocess.run([sys.executable,str(TOOL),'--vault',str(self.v),*args],text=True,capture_output=True,check=True).stdout
        listing=run('import-list','--source',str(manifest)); self.assertIn(m['id'],listing)
        args=['import-node','--source',str(manifest),'--id',m['id'],'--file',str(a.relative_to(self.v))]
        run(*args); before=self.snapshot(); run(*args); self.assertEqual(before,self.snapshot())
        self.assertEqual(run('import-list','--source',str(manifest)).strip(),'')
        self.assertIn('psy-school-seed-school',run('query','--depth','2'))
        run('validate','--file',str(a.relative_to(self.v)))
        self.assertIn('Missing information',run('narrative'))

    def test_relation_aliases_and_symmetry(self):
        a=self.note('Analytical Psychology',extra={'relationships':[{'relation':'branched_from','target':'[[Psychoanalysis]]'}]}); self.add(a)
        self.assertEqual(self.g['edges'][0]['relation'],'developed_from')
        self.modify(a,relationships=[{'relation':'related_to','target':'[[Psychoanalysis]]'}]); self.add(a)
        self.assertEqual(b.distances(self.g,b.ROOT,'network')['psy-school-analytical-psychology'],1)
        self.assertNotIn('psy-school-analytical-psychology',b.distances(self.g,b.ROOT))

    def test_validation_failure_preserves_registry(self):
        a=self.note('Bad Tags',extra={'tags':['type/school']}); before=self.snapshot()
        with self.assertRaises(ValueError): self.add(a)
        self.assertEqual(before,self.snapshot())

    def test_automatic_person_linking(self):
        person=dict(id='psy-person-sigmund-freud',title='Sigmund Freud',aliases=['Freud'],type='person',path='Psychology/People/Sigmund Freud.md')
        self.modify(self.root,pending_entities=[person])
        self.root.write_text(self.root.read_text()+'\nFreud proposed it. Freud revised it.\n\n## References\nFreud, Sigmund. Bibliography only.\n')
        before=self.snapshot()
        result=b.link_people(self.v,self.root,self.schema,self.g,True)
        self.assertEqual(result['linked'],2); self.assertEqual(before,self.snapshot())
        b.link_people(self.v,self.root,self.schema,self.g,False)
        text=self.root.read_text()
        self.assertIn('[[Psychology/People/Sigmund Freud|Sigmund Freud]] proposed',text)
        self.assertIn('[[Psychology/People/Sigmund Freud|Freud]] revised',text)
        self.assertIn('## References\nFreud, Sigmund.',text)
        before=self.snapshot(); b.link_people(self.v,self.root,self.schema,self.g,False)
        self.assertEqual(before,self.snapshot())

    def test_person_wrong_target_and_first_mention(self):
        self.person_fixture()
        text=self.root.read_text()
        self.root.write_text(text.replace('[[Psychology/People/Sigmund Freud|Sigmund Freud]]','[[Psychology/Schools/Psychoanalysis|Sigmund Freud]]'))
        with self.assertRaisesRegex(ValueError,'wrong entity'): self.add(self.root)
        self.root.write_text(text.replace('|Sigmund Freud]]','|Freud]]'))
        with self.assertRaisesRegex(ValueError,'First person mention'): self.add(self.root)

    def test_queue_chronological_order(self):
        entities=[dict(id='psy-school-later',title='Later',type='school',path='Psychology/Schools/Later.md',sort_year=1913),
                  dict(id='psy-school-earlier',title='Earlier',type='school',path='Psychology/Schools/Earlier.md',sort_year=1911)]
        self.modify(self.root,pending_entities=entities); self.add(self.root)
        queue=b.read(self.v/'_Graph/research_queue.yaml')
        self.assertEqual(queue['next_proposed_target'],'psy-school-earlier')
        self.assertEqual(queue['pending'][0]['sort_year'],1911)

    def test_unresolved_edge_identity_survives_registration(self):
        a=self.note('Child',parents=['Missing Parent']); self.add(a)
        edge_id=self.g['claims']['psy-school-child'][0]['id']
        self.add(self.note('Missing Parent',parents=['Psychoanalysis']))
        self.add(a)
        self.assertEqual(self.g['claims']['psy-school-child'][0]['id'],edge_id)

    def test_registry_drift_recovery(self):
        projection=self.v/'_Graph/relationships.yaml'; projection.write_text('relationships: [manual]\n')
        with self.assertRaisesRegex(ValueError,'projection differs'): b.load(self.v)
        recovered=b.load(self.v,check_projection=False)
        b.persist(self.v,recovered,self.schema,False)
        self.assertEqual(b.load(self.v)['edges'],[])

if __name__=='__main__': unittest.main()
