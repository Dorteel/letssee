import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'tools'))
import research_runner as r


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault=Path(self.tmp.name)/'vault'
        shutil.copytree(r.DEFAULT_VAULT,self.vault)
        shutil.rmtree(self.vault/'_Research',ignore_errors=True)
        for note in (self.vault/'Psychology/Schools').glob('*.md'):
            if note.name != 'Psychoanalysis.md': note.unlink()
        graph={'version':1,'root':r.g.ROOT,'nodes':{},'claims':{}}
        schema=r.g.read(self.vault/'_Graph/schema.yaml')
        r.g.register(self.vault,self.vault/'Psychology/Schools/Psychoanalysis.md',schema,graph)
        self.before={str(p.relative_to(self.vault)):p.read_bytes() for p in self.vault.rglob('*.md')}

    def args(self,**kw):
        return SimpleNamespace(vault=str(self.vault),root='psychoanalysis',recursive=True,
            max_depth=kw.get('max_depth',5),max_nodes=kw.get('max_nodes',3),
            dry_run=kw.get('dry_run',False),packets=str(REPO/'research/packets.json'))

    def test_dry_run_has_no_side_effects(self):
        before={str(p.relative_to(self.vault)):p.read_bytes() for p in self.vault.rglob('*') if p.is_file()}
        report=r.run(self.args(dry_run=True))
        after={str(p.relative_to(self.vault)):p.read_bytes() for p in self.vault.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        self.assertEqual(report['schools_researched'],3)

    def test_resume_and_preservation(self):
        first=r.run(self.args(max_nodes=1))
        self.assertEqual(first['schools_researched'],1)
        second=r.run(self.args())
        self.assertEqual(second['schools_researched'],2)
        self.assertEqual(r.run(self.args())['schools_researched'],0)
        for name,content in self.before.items():
            self.assertEqual((self.vault/name).read_bytes(),content)
        schools=list((self.vault/'Psychology/Schools').glob('*.md'))
        self.assertEqual(len(schools),4)
        # All old Excalidraw files survive byte for byte.
        for original in r.DEFAULT_VAULT.rglob('*.excalidraw'):
            if '_Research' not in original.parts:
                self.assertEqual(original.read_bytes(),(self.vault/original.relative_to(r.DEFAULT_VAULT)).read_bytes())

    def test_depth_zero(self):
        self.assertEqual(r.run(self.args(max_depth=0))['schools_researched'],0)

    def test_existing_file_exclusive(self):
        path=self.vault/'untouched.md'; path.write_text('manual')
        with self.assertRaises(FileExistsError): r.exclusive(path,'replacement')
        self.assertEqual(path.read_text(),'manual')

    def test_tamper_stops(self):
        r.run(self.args(max_nodes=0))
        root=self.vault/'Psychology/Schools/Psychoanalysis.md'
        root.write_text(root.read_text()+'\nchanged')
        with self.assertRaisesRegex(ValueError,'STOP'): r.run(self.args())
        self.assertFalse((self.vault/'Psychology/Schools/Individual Psychology.md').exists())

    def test_invalid_packet_rejected(self):
        graph=r.g.load(self.vault)
        schema=r.g.read(self.vault/'_Graph/schema.yaml')
        packet=json.loads((REPO/'research/packets.json').read_text())['packets'][0]
        packet['body']=packet['body'].replace('## What\n','## Missing\n')
        with self.assertRaises(ValueError): r.validate_packet(packet,graph,schema)

    def test_recursive_discovery_and_depth(self):
        data=json.loads((REPO/'research/packets.json').read_text())
        first=data['packets'][0]
        child=copy.deepcopy(first)
        child['path']='Psychology/Schools/Example Child.md'
        child['metadata'].update(id='psy-school-example-child',title='Example Child')
        child['metadata']['relationships']=[copy.deepcopy(first['metadata']['relationships'][0])]
        child['metadata']['relationships'][0]['target']='[[Psychology/Schools/Individual Psychology]]'
        first['metadata']['pending_entities'].append({'id':'psy-school-example-child','title':'Example Child',
            'type':'school','path':child['path']})
        edge=copy.deepcopy(first['metadata']['relationships'][0])
        edge.update(relation='branched_into',target='[[Psychology/Schools/Example Child]]')
        first['metadata']['relationships'].append(edge)
        data['packets'].append(child)
        path=Path(self.tmp.name)/'packets.json';path.write_text(json.dumps(data))
        args=self.args(dry_run=True,max_nodes=10,max_depth=1); args.packets=str(path)
        self.assertEqual(r.run(args)['schools_researched'],3)
        args.max_depth=2
        result=r.run(args)
        self.assertEqual(result['schools_researched'],4)
        self.assertEqual(result['planned_or_created'][-1]['genealogical_depth'],2)

    def test_resume_after_note_publish_before_state(self):
        from unittest.mock import patch
        with patch.object(r,'snapshots',side_effect=RuntimeError('simulated interruption')):
            with self.assertRaises(RuntimeError): r.run(self.args(max_nodes=1))
        result=r.run(self.args())
        self.assertEqual(result['schools_researched'],2)
        self.assertEqual(len(list((self.vault/'Psychology/Schools').glob('*.md'))),4)

    def test_bfs_multiple_parents_cycles_and_rivals(self):
        nodes={i:{'type':'school'} for i in ['root','child','grandchild','parent','rival']}
        edges=[{'source':s,'target':t,'relation':rel} for s,t,rel in [
            ('root','child','branched_into'),('child','grandchild','branched_into'),
            ('parent','root','branched_into'),('grandchild','root','branched_into'),
            ('root','rival','influenced')]]
        order,depth,connections=r.traversal({'nodes':nodes,'edges':edges},'root')
        self.assertEqual(len(order),len(set(order)))
        self.assertEqual(depth['child'],1)
        self.assertEqual(depth['parent'],1)
        self.assertIn('rival',connections)
        self.assertNotIn('rival',depth)

if __name__=='__main__': unittest.main()
