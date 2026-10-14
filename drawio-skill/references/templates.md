# Templates

`--template FILE.drawio` makes the generator read an existing draw.io file and reuse its
look, its surrounding frame, or both. Compressed `.drawio` files and `.drawio.svg` files
(SVG with an embedded diagram) work too. The template file itself is never modified.

Run `drawio_gen.py inspect FILE.drawio` first. Its output is the ground truth for
everything described here.

## What is read from a template

**Page setup.** Page size, grid, background colour and everything else on the template
page's `<mxGraphModel>` carry over. `--template-page NAME|N` picks the page that becomes
the output page (default: the first). Other pages are not copied to the output, but they
are still scanned for styles - so a template can keep its frame on page 1 and a style
sheet on page 2.

**Default styles per shape kind.** Every *labelled* shape that is not on a locked layer
is a sample. Samples are sorted into kinds (rect, rounded, terminator, diamond, ellipse,
circle, cylinder, hexagon, parallelogram, document, cloud, actor, note, text, group,
table, lifeline, edge, ...) and the most frequent style of each kind becomes the default
for that kind. Unlabelled shapes (borders, rules, logos) and anything on a locked layer
are decoration, not samples.

Kinds the template has no sample for fall back to the built-in shape, tinted with the
colours and font of the template's most common box - so a diagram stays coherent even if
the template only ever shows rectangles. A template that has rounded boxes but no square
ones gives plain nodes the rounded style.

**Named styles.** The label of a sample is a style name (case-insensitive). If the
template has a shape labelled "External system", then `"style": "external system"` on a
node applies that shape's complete style. If the node also asks for a different `shape`
than the sample has, only the sample's colours and font are applied, so the shape is
kept. Labelled edges work the same way for edges.

**Placeholders.** `{{key}}` inside any template label is replaced:

| Placeholder | Filled from |
| --- | --- |
| `{{title}}` | spec `title` (or `--title` for Mermaid input) |
| `{{date}}` | today's date, ISO format |
| `{{anything}}` | spec `meta.anything`, or `--set anything=value` (wins over `meta`) |
| `{{diagram}}` | not text: marks where the generated diagram goes (see below) |

Unfilled placeholders are left in place and reported as a warning - ask the user for the
value, or pass `--set key=` to blank it. (These `{{...}}` markers belong to this skill.
draw.io's own `%name%` placeholders are untouched and keep working - see "Metadata and
placeholders" in `upstream/xml-reference.md`.)

## Modes

**`style`** - take the look, drop the content. All template shapes are removed except
locked layers and cells that contain a `{{placeholder}}` (so a title text survives). The
diagram starts at the top-left, or below whatever was kept. Use this when the template is
an example diagram: "make it look like this one".

**`frame`** - keep every template cell and add the diagram:

- into the cell labelled `{{diagram}}` if there is one: the cell is removed and the
  diagram is centred in its rectangle. If the diagram is bigger than that rectangle you
  get a warning; change `direction`, shorten labels, split into pages, or accept it;
- otherwise below the existing content, with a warning. Pass `--at X,Y` to choose the
  position yourself after reading the coordinates from `inspect`.

**`auto`** (default) - `frame` if a `{{diagram}}` cell exists, else `style`.

New shapes go into the first unlocked layer. If every layer is locked, a new layer named
"Diagram" is added on top.

## Typical situations

*"Use our corporate template"* - `inspect` it. If it is a title block without a
`{{diagram}}` cell, use `--template-mode frame --at X,Y` with a position inside the free
area, and tell the user that adding a rectangle labelled `{{diagram}}` to the template
makes this automatic next time. Fill the title block via `--set`.

*"Match the style of this existing diagram"* - `--template-mode style` (the default when
there is no `{{diagram}}` cell). Check the "Named styles" list from `inspect`: in an
ordinary diagram the labels are content ("Kafka", "Billing"), not style names, so rely on
the per-kind defaults and add raw style overrides for emphasis.

*No template, but brand colours given* - skip the template and put the colours in the
spec's `styles` object, then reference those names on nodes.

*Mermaid plus template* - works with the built-in engine (`flowchart`, `sequenceDiagram`,
`classDiagram`, `erDiagram`, `stateDiagram`). Colours set in the Mermaid source
(`classDef`, `style`) still win over the template for those nodes.

## Building a template

`assets/template-example.drawio` is a complete example to copy and adapt:

- Page "Diagram": a locked layer "Frame" with a border, `{{title}}`, `{{author}} · {{date}}`
  and a rule; an unlocked layer with one dashed rectangle labelled `{{diagram}}`.
- Page "Styles": labelled samples - "Step" (default box), "Decision", "Store", "Highlight",
  "External", "Group", plus one edge. Their labels are the style names.

To make one in draw.io: draw the frame, put it on its own layer and lock the layer
(View > Layers); add a rectangle with the text `{{diagram}}` where diagrams should go; add
a second page with one sample per shape kind, labelled with the name you want to use.
