---
name: drawio
description: Create working draw.io / diagrams.net files (.drawio) from a text description or from Mermaid, optionally styled by or embedded in an existing .drawio template, with real shapes from draw.io's libraries (AWS, Azure, GCP, Kubernetes, Cisco, BPMN, ...). Use this whenever the user wants a diagram they can open and edit in draw.io - flowcharts, architecture and cloud diagrams, sequence, ER, class and state diagrams, process maps, org charts - or mentions drawio, draw.io, diagrams.net, .drawio files, "convert this Mermaid", "diagram in our template / corporate style", or asks to fix, validate or export a .drawio file. Prefer this over writing mxGraph XML from memory - the bundled generator does layout, styling and validation against the official draw.io schema, so the file opens with connected, non-overlapping shapes.
---

# draw.io diagrams

A `.drawio` file is only useful if it opens, the shapes do not overlap and the arrows
are attached. Getting that right by writing XML from memory is unreliable, so this skill
gives you two things:

- `scripts/drawio_gen.py` - turns a small JSON description or Mermaid into a laid-out,
  validated `.drawio` file, can apply a template, and searches draw.io's shape libraries.
  Python 3.9+, standard library only.
- `references/upstream/` - the official draw.io references from
  [jgraph/drawio-mcp](https://github.com/jgraph/drawio-mcp) (`shared/`), vendored
  unmodified. They are the authority on the XML format and styles.

Paths are relative to this skill's directory.

```
python3 scripts/drawio_gen.py build    SPEC.json   -o OUT.drawio [--template T.drawio]
python3 scripts/drawio_gen.py mermaid  IN.mmd|.md  -o OUT.drawio [--template T.drawio]
python3 scripts/drawio_gen.py shapes   aws lambda          # find library shapes and icons
python3 scripts/drawio_gen.py inspect  FILE.drawio         # what is in a file / template
python3 scripts/drawio_gen.py validate FILE.drawio [--repair]
python3 scripts/drawio_gen.py export   FILE.drawio -f png  # needs draw.io desktop
```

`build` and `mermaid` validate their own output and end with a line like
`out.drawio: ok - 1 page(s), 12 shapes, 14 connectors`. Read the `warning:` lines above
it; they are specific and usually worth acting on.

## Choosing the route

| The user gives you | Do this |
| --- | --- |
| Mermaid (a file, a fenced block, pasted text) | `mermaid` subcommand. |
| A description, a list of steps, code or docs to visualise | Write a JSON spec, then `build`. |
| Either of the above plus a `.drawio` file to match | Same, plus `--template`; run `inspect` on it first. |
| An existing `.drawio` to change, or a layout the generator cannot express | Edit the XML by hand, following `references/upstream/xml-reference.md`, then `validate --repair`. |

Write spec and intermediate files next to the output or in a scratch directory, not in
the skill folder. Match the language of the labels to the user's language.

## From text: write a spec

A spec lists what exists and what connects to what. No coordinates: layout is automatic.

```json
{
  "title": "Order handling",
  "direction": "TB",
  "nodes": [
    {"id": "start", "label": "Order received", "shape": "terminator", "style": "green"},
    {"id": "check", "label": "In stock?", "shape": "decision"},
    {"id": "ship",  "label": "Ship order", "group": "wh"},
    {"id": "db",    "label": "Orders DB", "shape": "database", "group": "wh"},
    {"id": "back",  "label": "Back-order", "style": "orange"}
  ],
  "groups": [{"id": "wh", "label": "Warehouse"}],
  "edges": [
    ["start", "check"],
    ["check", "ship", "yes"],
    ["check", "back", "no"],
    {"from": "ship", "to": "db", "style": "dashed"}
  ]
}
```

What makes the result good rather than merely valid (these follow the upstream
reference's general principles):

- **Semantically right shapes.** `terminator` for start/end, `decision`, `database`,
  `actor`, `document`, `cloud`, `note`; plain boxes for the rest. For cloud, network and
  other domain diagrams use real library shapes - see "Library shapes" below.
- **Group what belongs together.** Groups are containers (systems, zones, teams,
  phases); they nest via `parent`. Keep external actors outside implementation groups.
  When many edges converge, route them through one hub node (gateway, bus, broker).
- **Short labels.** Two to four words per node, one to three per edge; `\n` breaks a
  line. Put secondary detail in node text or a `note`, not on extra edges.
- **Consistent visual meaning.** One colour per kind of thing, one meaning for dashed
  lines. Palette names: `blue green orange yellow red purple gray`, or `primary success
  warning danger neutral`. Add a small legend (a `note`) when you mix several.
- **Direction.** `TB` for processes and hierarchies, `LR` for pipelines and layered
  architecture. Long edge labels make `LR` wide - switch if warned that it does not fit.
- **Main path first.** Edges are laid out in the order given; list the happy path first
  so it runs straight.
- Sequence diagrams use `"type": "sequence"` with `participants` and `messages`.
  ER entities and UML classes are nodes with `rows`.

`references/spec.md` documents every field, the sequence format, tables, metadata and
tags, multi-page files and recipes. Read it before writing anything beyond a plain flowchart.

## From Mermaid

```
python3 scripts/drawio_gen.py mermaid diagram.mmd -o diagram.drawio
```

- The built-in engine converts `flowchart`/`graph`, `sequenceDiagram`, `classDiagram`,
  `erDiagram` and `stateDiagram`, works offline and with templates. Markdown containing
  several ```mermaid blocks becomes one page per block.
- Other types (gantt, pie, mindmap, journey, C4, ...) are handed to the draw.io desktop
  CLI automatically when it is installed, because draw.io's own Mermaid parser handles
  every type. `--engine drawio` forces that route; `--engine builtin` forbids it.
- If neither can convert it (no desktop app, or a template is required), translate the
  Mermaid into a spec yourself and use `build`. Say so when something like gantt bars has
  no sensible node-and-edge equivalent.

To adjust a converted diagram (colours, shapes, grouping), add `--spec-out spec.json`,
edit that spec and run `build` on it. When you write Mermaid yourself, follow
`references/upstream/mermaid-reference.md`.

## Library shapes (AWS, Azure, Kubernetes, Cisco, BPMN, logos ...)

Skip this for flowcharts, UML, ER, org charts and anything that is boxes, diamonds and
cylinders. Use it when the user expects standard symbols: cloud architecture, network
topology, Kubernetes, P&ID, electrical, BPMN task types, or brand logos and everyday icons.

```
python3 scripts/drawio_gen.py shapes aws lambda
{"title": "Lambda", "style": "sketch=0;...shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;", "w": 78, "h": 78}
```

Put the returned `style` on the node unchanged and copy `w`/`h`:

```json
{"id": "fn", "label": "Resize images", "style": "<style from the search>", "width": 78, "height": 78}
```

A style that names its own `shape=` or `image=` replaces the default box entirely. The
search uses the official draw.io shape index (10,000+ shapes, downloaded and cached on
first use; `--refresh` updates it) and falls back to the online draw.io icon service for
logos (`--no-icons` to stay offline). Search with two or three plain words; several
libraries often have the same shape, so pick one family (e.g. `aws4`) and stay in it.

## With a template

A template is any `.drawio` file. It can contribute:

1. **Styles** - every labelled shape is a sample. The most common style per shape kind
   becomes the default for that kind, and a shape's label is usable as a style name
   (`"style": "highlight"` picks the template shape labelled "Highlight").
2. **A frame** - title block, border, logo, legend around the diagram.
3. **Placeholders** - `{{title}}`, `{{date}}` and any `{{key}}` in template labels are
   filled from the spec's `title`, today's date, the spec's `meta`, or `--set key=value`.

Always look first: `python3 scripts/drawio_gen.py inspect template.drawio` lists pages,
layers, cells, the styles and style names that will be picked up, the placeholders, and
the mode that applies by default.

- `--template-mode style` copies the look and drops the template's own shapes (locked
  layers and cells containing `{{placeholders}}` stay). For "make it look like this one".
- `--template-mode frame` keeps everything and puts the diagram into the cell labelled
  `{{diagram}}`, or below the existing content if there is none (`--at X,Y` to choose).
  For title-block templates.
- `auto` (default): `frame` if a `{{diagram}}` cell exists, otherwise `style`.

Use the style names `inspect` reports rather than palette colours, so the result stays
within the template's visual language. Details and how to build a template are in
`references/templates.md`; `assets/template-example.drawio` is a working frame-plus-styles
template to start from, or to offer when the user wants one and has none.

## Editing XML by hand

For changes to an existing file, or structures the spec cannot express (flat swimlanes
across the full width, cross-functional tables, layers), edit the XML directly.

- Read `references/upstream/xml-essentials.md` first (ten lines: skeleton, vertex and
  edge templates, containers, the placement grid).
- Read `references/upstream/xml-reference.md` for containers, swimlanes, cross-functional
  tables, layers, tags, metadata and dark mode; `references/upstream/style-reference.md`
  for every shape, style key, arrow marker and colour.
- Those documents were written for the draw.io MCP servers: where they say
  `search_shapes`, use the `shapes` subcommand; where they say `postLayout: "elk"` or
  `routing: "libavoid"`, use the desktop CLI's `--layout` (below).
- Afterwards run `validate --repair FILE`: it escapes stray `<` and `&` in labels, strips
  comments and text around the XML, then checks ids, parents, edge endpoints, geometry,
  overlaps and (when `xmllint` is present) the official `mxfile.xsd`.

## draw.io desktop CLI (optional)

When the desktop app is installed it adds image export, draw.io's own Mermaid parser and
ELK layouts. `python3 scripts/drawio_gen.py cli` prints the executable (macOS:
`/Applications/draw.io.app/Contents/MacOS/draw.io`; Linux: `drawio`; Windows:
`draw.io.exe`; override with `DRAWIO_CMD`).

```
python3 scripts/drawio_gen.py export out.drawio -f png      # also svg, pdf; diagram stays embedded and editable
"$DRAWIO" -x -f xml --layout verticalFlow -o out.drawio out.drawio   # re-layout hand-written XML
"$DRAWIO" -x -f xml --layout libavoid     -o out.drawio out.drawio   # only re-route edges around shapes
```

Layout presets: `verticalFlow`, `horizontalFlow`, `verticalTree`, `horizontalTree`,
`radialTree`, `organic`. Files from `build` are already laid out; `--layout` is for
hand-written XML. A sandboxed shell usually cannot start the app - if the CLI fails with
a sandbox or GPU error, say so and continue without it; nothing else depends on it.

## Before you hand it over

- The last output line says `ok`. Fix every `error:`; treat each `warning:` as a question
  to answer (unknown style name, diagram larger than the template area, undeclared node
  that was auto-created, unfilled placeholder, schema complaint).
- Check the spec against the request: every thing the user named is a node, every
  relationship an edge, arrow directions are right.
- If the desktop CLI works, export a PNG and look at it. If not, say plainly that the
  file is validated but was not rendered.
- Tell the user where the file is and that it opens in draw.io desktop, at
  app.diagrams.net (File > Open from > Device) or in the VS Code draw.io extension. The
  layout is a starting point: connectors stay attached when shapes are moved.

## Reference files

- `references/spec.md` - the spec format: graph and sequence diagrams, shapes, styles, tables, metadata, pages.
- `references/templates.md` - how templates are read, the modes, placeholders, building one.
- `references/upstream/xml-essentials.md`, `xml-reference.md`, `style-reference.md`,
  `mermaid-reference.md`, `mxfile.xsd` - official draw.io references (Apache-2.0, see
  `SOURCE.md` there). Refresh with `python3 scripts/drawio_gen.py update`.
