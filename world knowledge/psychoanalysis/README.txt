Obsidian Psychology Knowledge Graph Builder
==========================================

This vault currently contains exactly one researched Markdown article:
Psychology/Schools/Psychoanalysis.md. It covers the emergence of psychoanalysis
in the 1890s, distinguishes later revisions, and gives linked references with
source-access limitations. No person, successor-school or concept articles are
automatically created. Documentation is in this .txt file to respect the
one-Markdown-file-per-execution requirement.

Requirements and tests
----------------------
Python 3.10+ on Linux/macOS (fcntl is used for writer locking), and PyYAML 6.x.
The environment provides python3; the unqualified python executable is absent.

    python3 -m pip install -r requirements.txt
    bash test.sh

Tests create isolated temporary vaults and clean them up. Obsidian is not needed.
The suite checks registration, YAML and JSON, ownership, stable identity,
missing links, cycles, multiple inheritance, idempotent imports, person links,
node types, traversal, export filters and deterministic layouts, dry runs,
backups and preservation of Markdown and manually edited maps. The tests validate
Excalidraw structure; they do not drive an Excalidraw or Obsidian GUI.

Architecture and one-node workflow
----------------------------------
Markdown is authored source material. _Graph/graph.json stores the parsed node
index, content hashes and owner-specific relationship claims. It is the
transaction source of truth. _Graph/relationships.yaml is its readable typed
edge projection, with IDs, direction, dates, descriptions, confidence and evidence.
_Graph/research_queue.yaml tracks missing declared entities and the next school.
_Graph/schema.yaml holds node types, colors, traditions and the ontology.

Initialize metadata only (does not create Markdown):

    python3 tools/graph_builder.py init --root psy-school-psychoanalysis

For a new vault/domain, choose its root ID on init before registering any nodes.
Add, validate, or update exactly one existing authored file:

    python3 tools/graph_builder.py add --file 'Psychology/Schools/Psychoanalysis.md'
    python3 tools/graph_builder.py validate --file 'Psychology/Schools/Psychoanalysis.md'
    python3 tools/graph_builder.py update --file 'Psychology/Schools/Psychoanalysis.md'
    python3 tools/graph_builder.py update --file 'Psychology/Schools/Psychoanalysis.md' --dry-run

Use --vault /absolute/vault BEFORE the command to select another vault.
Every add/update parses only the requested Markdown file. The rest of the graph
is read from the index. Metadata projections and BFS distances are recalculated
from indexed claims (O(V+E)); unrelated Markdown is never rewritten or reparsed.
A selected note owns its claims, including incoming claims authored in that note.
Replacing its claims removes its stale edges, retaining independently authored
claims from every other owner. Parallel claims may appear separately because
their ownership and evidence are independent. Edges are not duplicated by reruns.

Ordinary add/update never rewrites the requested article either: paragraphs,
formatting and frontmatter remain authored content. Depth in graph.json is the
authoritative computed distance; the frontmatter depth is an author-provided
snapshot/hint and may become stale after changes elsewhere. It is deliberately
not propagated to other Markdown files. School frontmatter depth may be null.
Use query/export for current distances, and native graph colors by type/tradition
rather than relying on cached depth values.

Writes replace individual files atomically, with a previous-version .bak next to
each overwritten file. Writers serialize through _Graph/.lock. The three metadata
files are not a single filesystem transaction: after interruption, graph.json is
authoritative and `sync` regenerates the YAML projections. Backups of Markdown
are made only by commands that explicitly write Markdown (import and link-people).
Dry-run does not create locks, directories or backups.

Schema and naming
-----------------
Use human-readable filenames, stable immutable IDs, and aliases. No numeric
prefixes. A renamed note may reuse its ID once the former path no longer exists;
its former title/path are preserved as index aliases. Keep a stub's registered
canonical path when writing its article, or explicitly resolve its identity first.

Required fields for every node: id, title, aliases (list), type, domain, tags.
Types: school, person, concept, theory, method, period. Schools additionally
require tradition, period, emergence_year (integer or null), depth (integer or
null), status. All school tags are exactly these four matching dimensions:

    domain/psychology
    type/school
    tradition/depth-psychology
    period/1890s

People support birth_year, death_year, associated_schools and influenced_by;
their minimal tags are domain/psychology and type/person. The two-tag person
schema follows the newer entity requirements. Other types also permit the two
mandatory dimensions, with optional matching tradition/period dimensions.
Extend traditions in schema.yaml deliberately. Other domains can use their own
domain tags, ID prefixes, note folders and root. Psychology person paths currently
have a specific Psychology/People/ rule for declared pending entities; adapt that
rule before using the person workflow in a different domain.

The researched article demonstrates the full school schema, provenance,
approximate dates and all narrative sections. Its pending_entities list declares
canonical IDs/titles/paths/types and aliases without creating files. Schools in
that list can carry sort_year, founding_period and research_priority. Those
records let the queue order overlapping successor periods without inventing
intellectual influence from chronology. Typed pending nodes are machine metadata,
not researched articles; exports draw their boxes with dashed outlines.

Relationship syntax
-------------------
Use a `relationships` list in frontmatter for fully evidenced claims:

    relationships:
      - source: '[[psy-person-sigmund-freud]]'
        relation: founded
        target: '[[psy-school-psychoanalysis]]'
        date: 1896
        description: Naming landmark during a longer emergence in the 1890s.
        confidence: high
        evidence:
          - source: https://www.loc.gov/collections/sigmund-freud-papers/articles-and-essays/timeline/

The owner must be one endpoint. Source defaults to the current note. Targets
must be wikilinks. A missing target is reported, never turned into a Markdown
placeholder. Declare pending_entities when its canonical ID/type/path are known;
otherwise the unresolved edge is retained with a null target and target_link.
Later registration resolves it without reparsing the referring note. Unresolved
untyped prose links are reported but cannot be safely classified or queued
automatically: the researcher must declare their identities.

Simple property lists also work, for example:

    developed_from:
      - '[[Psychoanalysis]]'

List items can instead be mappings with target/date/description/confidence/evidence.
Unsupported evidence is marked missing/uncertain rather than invented. Use a
single representation per claim; precise research should use explicit edge data.

Controlled vocabulary:
- Genealogy: developed_from, branched_into.
- Other historical: influenced, influenced_by, reacted_against, contemporary_of,
  associated_with_period, founded, founded_by.
- Conceptual: extends, revises, contradicts, integrates, shares_assumption_with.
- Knowledge/entity: studies, introduces_concept, applies_to, related_to, developed,
  criticized, contributed_to, collaborated_with, uses_method, used_by.
- Aliases: branched_from -> developed_from; introduced -> introduces_concept.

Only developed_from/branched_into count toward genealogical distance. Similarity,
influence, disagreement and personal association never shorten that depth.
Schema.yaml declares explicit inverses and symmetric predicates. No reverse edge
is written merely because an edge exists. Genealogy follows parent to descendant;
network traversal follows directed edges plus explicitly declared inverse or
symmetric traversal. Thus influenced can be traversed backward as influenced_by,
whereas reacted_against alone does not authorize reverse traversal.

Entity recognition and person linking
------------------------------------
First identify and disambiguate people using research, then search the index and
aliases for existing identities. Declare each missing person's canonical ID,
full name, aliases and Psychology/People/<Full Name>.md path in pending_entities.
Use full canonical display names on first body mention, aliases thereafter:

    [[Psychology/People/Sigmund Freud|Sigmund Freud]]
    [[Psychology/People/Sigmund Freud|Freud]]

The validator checks every occurrence of declared names/aliases outside links,
full display names on first mention, canonical target paths, conflicting person
names/aliases and person labels linked to the wrong entity. Bibliography-only
names after `## References` are exempt. It is a deterministic check against
registered/declared entities, not a general named-entity recognition model;
a researcher must identify new people. Unlisted strangers cannot be detected
reliably. Disambiguate identical names explicitly in canonical labels and paths.

To automatically link declared names in exactly one article:

    python3 tools/graph_builder.py link-people --file 'Psychology/Schools/Psychoanalysis.md' --dry-run
    python3 tools/graph_builder.py link-people --file 'Psychology/Schools/Psychoanalysis.md'

This command replaces name occurrences, preserves existing wikilinks and the
bibliography, makes a backup, validates, and updates the registry. It does not
research or create biographies. Avoid short ambiguous aliases such as common
first names. Person discovery and historical evidence checking remain research
work, distinct from syntactic validation.

Queries, queue and narrative
----------------------------

    python3 tools/graph_builder.py query --root psy-school-psychoanalysis --depth 3
    python3 tools/graph_builder.py query --mode network --view all --depth 3
    python3 tools/graph_builder.py query --mode network --view people --relations founded founded_by influenced --depth 3
    python3 tools/graph_builder.py queue
    python3 tools/graph_builder.py narrative --root psy-school-psychoanalysis --depth 3
    python3 tools/graph_builder.py narrative --output Psychology/Maps/history.generated.txt

Unreachable nodes have null cached depth. BFS handles cycles and multiple parents.
Query output omits unreachable nodes; exports place them on an outer ring. View
filters affect display, not the genealogy metric. Missing pending school nodes
may already have a documented genealogical distance. Narrative is a deterministic
assembly of authored sections and edge descriptions with missing information
marked. It performs no new research and fabricates no explanation or reference.
Generated narrative files use .generated.txt to avoid creating another Markdown
article in a research pass. Ordering is developmental distance then known date;
it is not a total chronological ordering of all psychological movements.

Obsidian native graph
---------------------
Use Graph View's filter box:

    path:Psychology -path:_Graph -path:tools -path:tests

For History of Ideas, append:

    (tag:#type/school OR tag:#type/theory)

For History of People, append:

    (tag:#type/school OR tag:#type/theory OR tag:#type/person)

Set Groups to tag:#type/school (blue), tag:#type/person (amber),
tag:#type/concept (purple), tag:#type/theory (green), tag:#type/method (teal),
tag:#type/period (gray). Traditions may instead use tag:#tradition/depth-psychology.
Turn on Display > Arrows. Open the Psychoanalysis note and Open local graph;
raise Local Graph depth from 1 to 2 to 3 to explore more links. These native
link steps are not the ontology-aware genealogical distance. Enable Existing
files only / hide unresolved if queued nodes overwhelm the view. Without files,
pending nodes have no native type tags, so native tag filters cannot classify
them; use the exporter for typed pending-node views.

Suggested force starting points: moderate center force (~0.5), strong repulsion
(~10), link force (~1) and link distance (~250), adjusted to vault size. Exact
sliders/ranges vary. The root is a narrative entry point, not guaranteed to be
geometrically centered. Native graph supports group colors and arrows, but not
typed edge coloring, edge labels, or exact radial placement. _Graph contains no
Markdown; JSON/YAML are suppressed by attachment filtering and the path filter.
Existing .obsidian settings were left untouched. Official documentation:
https://obsidian.md/help/Plugins/Graph%2Bview

Layered editable Excalidraw exports
----------------------------------

    python3 tools/graph_builder.py visualize --root psy-school-psychoanalysis --view schools --layout radial
    python3 tools/graph_builder.py visualize --root psy-school-psychoanalysis --view people --layout radial
    python3 tools/graph_builder.py visualize --root psy-school-psychoanalysis --view concepts --layout radial
    python3 tools/graph_builder.py visualize --root psy-school-psychoanalysis --view all --layout radial
    python3 tools/graph_builder.py visualize --view all --layout timeline
    python3 tools/graph_builder.py visualize --view schools --layout radial --output Psychology/Maps/Psychoanalysis.generated.excalidraw

Default outputs: Psychology/Maps/<view>-<layout>.generated.excalidraw.
Schools includes schools/theories; people adds people; concepts adds concepts
and methods to schools/theories; all includes every type, including periods.

Exports read indexed Markdown content plus typed claims and verify source hashes.
If a registered Markdown file changed, update that one file before exporting.
Root is centered in radial layout. Concentric school rings use genealogical BFS
levels, while nodes without genealogical distance occupy an outer auxiliary ring.
Colors come from node type. Solid blue arrows indicate genealogy, dashed gray
arrows other predicates; edge labels show type and approximate date. Node labels
show emergence/birth year when available. Timeline positions use dates and stack
identical dates; unknown dates get a separate lane. Layouts are deterministic,
not a collision-avoiding graph engine: dense labels/edges may overlap and require
manual arrangement. Edge connectors are bound to editable node boxes.

Output is native Excalidraw v2 scene JSON. Import/open it in Excalidraw or the
Obsidian Excalidraw plugin; it is not an .excalidraw.md wrapper. No plugin is
required for the automated tests. Source format documentation:
https://docs.excalidraw.com/docs/codebase/json-schema/

A .sha256 sidecar protects each generated map. If the map changes by hand, the
exporter refuses to overwrite it even if the generator source field remains.
Choose a new output path or copy the edited map to an authored name. Only
*.generated.excalidraw output paths are accepted. Existing manually authored
Excalidraw files and Obsidian configuration are not modified.

Incremental seed import and limitations
--------------------------------------
No narrative Excalidraw map or accompanying psychology notes were supplied in
this workspace, so no historical map import has been claimed. The supplied
attachment describes requirements, not actual seed graph content.

Use a reviewed YAML/JSON manifest with `nodes`, each containing the same
frontmatter schema plus `body` (a string). Transcribe/map seed annotations into
this format with provenance, qualify uncertain genealogy and retain original
files. The importer deliberately does not infer schools or historical edge
semantics from arbitrary Excalidraw geometry, labels or proximity.

    python3 tools/graph_builder.py import-list --source /path/to/reviewed-seed.yaml
    python3 tools/graph_builder.py import-node --source /path/to/reviewed-seed.yaml --id psy-school-analytical-psychology --file 'Psychology/Schools/Analytical Psychology.md' --dry-run
    python3 tools/graph_builder.py import-node --source /path/to/reviewed-seed.yaml --id psy-school-analytical-psychology --file 'Psychology/Schools/Analytical Psychology.md'

One import creates at most one Markdown note. Repeating it is idempotent if the
same note remains unchanged. Different existing content is never overwritten.
Imported material still needs historical research; registration is not evidence
verification. For future research passes, choose exactly one school/person/concept,
verify references, write only its article and then update that one path.

Recovery
--------
Malformed YAML or conflicting IDs fail before registry writes. Repair the note
or restore its backup, preserve the stable ID, and validate again. Do not copy an
existing ID into another live note. To rename, move the original file then update
the new path. Two live files claiming the same ID are rejected. Registry identity
checks concern indexed notes; existing unregistered notes must first be registered
individually. No full-vault Markdown scan is required by add/update.

If relationships.yaml differs from graph.json, normal commands stop rather than
silently discard edits. Preserve any manual edits, put supported claims in the
owning note, then regenerate the projection:

    python3 tools/graph_builder.py sync
    python3 tools/graph_builder.py update --file 'Psychology/Schools/Psychoanalysis.md'

If graph.json itself is corrupt, restore graph.json.bak and sync, then update any
notes changed since that snapshot individually. Deletion of files does not delete
registry claims automatically; no destructive bulk-rebuild/delete command exists.
