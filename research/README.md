# Preserved psychology research graph

Run from the repository root (Python 3.10+ and PyYAML):

```sh
python tools/graph_builder.py research --root psychoanalysis --recursive --max-depth 5 --max-nodes 3 --dry-run
python tools/graph_builder.py research --root psychoanalysis --recursive --max-depth 5 --max-nodes 3
```

The vault-local `tools/graph_builder.py research ...` entry point also works.
Use `--vault PATH` for another vault with a registered root and `--packets FILE`
for another reviewed packet collection. Limits are nonnegative. `--max-nodes`
counts newly created school notes per invocation. Zero creates none.

The initial pass is bounded to three schools. It preserves the original long
Psychoanalysis note, which is exempt from the new-note word/section constraints.
No existing Markdown is reformatted, including notes whose frontmatter differs
from the generated format. Existing incompatible notes require review rather
than replacement.

## Research and scope

This implementation is a deterministic scheduler of evidence-reviewed research
packets, not an unattended web-search agent. The initial packets were researched
using the linked university, historical collection, scholarly publisher, and
professional society sources on 20 October 2026. A reference URL and a `verified`
flag alone cannot establish historical truth: the packet author must inspect the
sources and review each claim. The runner validates structure, source membership,
and evidence attribution; it does not independently authenticate that review or
re-fetch pages. Full books were not accessed where references identify summaries.

To extend research, add a packet in the `packets.json` format, with school
metadata, seven sections, 3–5 reference URLs, declared pending entities, and
explained, sourced relationships. People use canonical path wikilinks. Concepts
and people enter the optional queue but are never expanded by this command.
Schools without reviewed packets become `needs_review`; no article is fabricated.
The checked-in corpus is deliberately limited, not a claim to exhaust psychology.

BFS processes children before parents at the same distance, with known emergence
years as tie-breakers. Genealogical distance is the shortest number of school
lineage edges, allowing multiple parents and cycles. Chronological proximity does
not create a lineage. Influential rivals and other cross-tradition connections
are considered after reachable genealogy; their genealogical depth is null and
the node cap bounds them separately. `--max-depth 0` excludes them. Nonrecursive
mode processes only direct genealogical neighbors. Weak thematic connections
must not be added as lineage. The root's existing relationships initialize the
traversal; a new unregistered root is not silently created.

## Persistence and safety

`research_backups/` contains the initial vault archive and repository-wide
Markdown SHA-256 baseline. The runner additionally backs up each vault before
its first real pass and records its vault-wide baseline in
`_Research/preservation.json`. Every node checks preservation before and after
publication. Existing registered note hashes are checked on resume.

Notes are validated in memory, staged to temporary files, fsynced, and published
with an exclusive hard link. No existing destination is replaced. A file lock
serializes real research passes. Dry runs do not lock or write anything.
Graph JSON is authoritative; YAML registries can be regenerated after an
interruption. An interrupted publication is registered on resume without
rewriting its note. This assumes a single host/POSIX filesystem.

`_Research/state.json` tracks pending, researching, completed, and needs_review
entities. `_Graph/research_queue.yaml` is the existing registry's pending-entity
projection; the runner computes BFS from relationships rather than using that
projection's chronological ordering. `_Research/completed.json` records complete
nodes, and `_Research/report.json` records the last pass. The existing root is
completed/existing, not counted as newly researched.

Each successful node produces a new `_Research/maps/<timestamp>/` directory:

- `genealogy.json`: school-only lineage edges.
- `network.json`: optional full graph with people and concepts.
- `schools-timeline.generated.excalidraw`: chronological school map.
- `schools-radial.generated.excalidraw`: school graph centered on Psychoanalysis.
- `all-radial.generated.excalidraw`: graph including optional entities.

`_Research/latest_maps.json` points to the latest directory. Old drawings are
never updated. Dashed nodes are pending; uncertain dates are ordering conventions,
not precise founding events. Cross-tradition influence is distinct from lineage.
Relationship totals count sourced registry claims, including separate owners'
accounts of the same historical connection. Review totals count flagged or
low-confidence relationship claims, not an exhaustive audit of every sentence.

## Validation

```sh
python3 -m unittest discover -s tests -v
bash 'world knowledge/psychoanalysis/test.sh'
TEST_BUILD_ROOT=/tmp/letssee-research-tests bash test.sh --unit
TEST_BUILD_ROOT=/tmp/letssee-research-tests bash test.sh --all
```

The repository test runner includes both graph suites before the existing ROS
checks. Full model integration additionally requires its pre-existing PyTorch,
transformers, and downloaded-model prerequisites.
