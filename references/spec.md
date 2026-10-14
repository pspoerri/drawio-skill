# Diagram spec reference

A spec is one JSON object. `drawio_gen.py build SPEC.json -o OUT.drawio` turns it into a
draw.io file. Unknown shapes and malformed entries are rejected with a message that says
what to change; softer problems come back as warnings.

The generated XML follows `upstream/xml-reference.md`: `html=1` on every cell, containers
as swimlanes with children in relative coordinates, each edge filed in the innermost
container that holds both of its ends, adaptive (dark-mode) colours enabled.

Contents: [Common fields](#common-fields) · [Graph diagrams](#graph-diagrams) ·
[Shapes](#shapes) · [Styles](#styles) · [Edges](#edges) ·
[Tables](#tables-er-entities-uml-classes) · [Metadata, tags, links](#metadata-tags-links) ·
[Sequence diagrams](#sequence-diagrams) · [Several pages](#several-pages) · [Recipes](#recipes)

## Common fields

| Field | Meaning |
| --- | --- |
| `title` | Page name; fills `{{title}}` in a template. |
| `type` | `"graph"` (default) or `"sequence"`. |
| `meta` | Extra values for template placeholders, e.g. `{"author": "Ana"}` fills `{{author}}`. |
| `styles` | Your own style names: `{"legacy": "fillColor=#eeeeee;dashed=1;"}`. Usable in any `style` field. |

## Graph diagrams

Everything that is boxes and arrows: flowcharts, architecture, ER, class, state, org charts.

```json
{
  "direction": "TB",
  "nodes":  [{"id": "a", "label": "A"}],
  "edges":  [{"from": "a", "to": "b", "label": "calls"}],
  "groups": [{"id": "g", "label": "Backend", "parent": null}]
}
```

`direction`: `TB` (top to bottom, default), `LR`, `BT`, `RL`. `--direction` on the command
line overrides it.

### Nodes

| Field | Meaning |
| --- | --- |
| `id` | Required, unique among nodes and groups. Only used for wiring. |
| `label` | Text shown. Defaults to the id. `\n` for a line break. Plain text: `<` and `&` are escaped for you. |
| `html` | `true` to pass the label through as HTML (`<b>Title</b><br>detail`). You are then responsible for valid HTML. |
| `shape` | See [Shapes](#shapes). Default `rect`. |
| `style` | A style name, a raw draw.io style string, or a list of both. See [Styles](#styles). |
| `group` | Id of the group that contains the node. |
| `rows` | List of strings: makes the node a table. See [Tables](#tables-er-entities-uml-classes). |
| `width`, `height` | Override the automatic size (pixels). Needed for library shapes. |
| `link`, `tooltip`, `tags`, `data` | See [Metadata, tags, links](#metadata-tags-links). |

`"nodes"` may also be an object mapping id to label: `{"a": "Start", "b": "End"}`.

### Groups

Titled containers (draw.io swimlanes) drawn around their members. A node joins a group
with `"group": "id"`, or the group lists its members:
`{"id": "g", "label": "Backend", "nodes": ["a", "b"]}`. Groups nest with `parent` and
accept `style` like nodes (a palette name colours the title bar).

Each group is laid out on its own and then placed as one block, so members always stay
together. A group is not a full-width lane; for true swimlanes or an actor-by-phase grid,
see "Swimlanes" and "Cross-functional flowcharts" in `upstream/xml-reference.md` and write
that structure by hand.

## Shapes

| Shape | Aliases | Typical use |
| --- | --- | --- |
| `rect` | `box`, `process`, `rectangle` | Default step / component |
| `rounded` | `round` | Softer box, states |
| `terminator` | `stadium`, `pill`, `start`, `end` | Start and end of a flow |
| `diamond` | `decision`, `choice`, `rhombus` | Branch |
| `ellipse`, `circle` | `oval` | Events, connectors |
| `cylinder` | `database`, `db`, `datastore`, `storage` | Data stores |
| `parallelogram` | `io`, `input`, `output` | Input / output |
| `trapezoid`, `hexagon` | | Manual step, preparation |
| `document` | | Documents, reports |
| `subroutine` | `subprocess`, `predefined` | Predefined process |
| `cloud` | | Internet, external network |
| `actor` | `person`, `user` | People (stick figure, label below) |
| `note` | `comment` | Annotation (yellow) |
| `text` | `label` | Bare text without a box |
| `table` | `class`, `entity` | ER entity / UML class (use with `rows`) |
| `initial`, `final` | | State-machine start and end dots |

**Anything else** - any of draw.io's 10,000+ library shapes - goes in `style`: run
`drawio_gen.py shapes <words>`, paste the returned style, and set `width`/`height` to the
returned `w`/`h`. A style fragment containing `shape=` or `image=` replaces the default box
completely instead of being blended with it. `upstream/style-reference.md` sections 3 and
4 list every shape name and style key if you want to compose one yourself.

## Styles

A `style` value is resolved in this order:

1. A name defined in the spec's own `styles` object.
2. With a template: the label of a template shape (see `templates.md`).
3. A palette name - `blue`, `green`, `orange`, `yellow`, `red`, `purple`, `gray`, `white` -
   or an alias: `primary`/`info` (blue), `success` (green), `warning` (yellow),
   `danger`/`error` (red), `neutral` (gray), `accent` (purple). These are draw.io's
   standard fill/stroke pairs.
4. Anything containing `=` is a raw draw.io style fragment, overlaid on what came before:
   `"fillColor=#1f3a5f;fontColor=#ffffff;fontStyle=1;"`.

Use a list to combine: `"style": ["green", "dashed=1;strokeWidth=2;"]`. An unknown name
produces a warning and is ignored.

Useful raw keys: `fillColor`, `strokeColor`, `fontColor`, `fontSize`, `fontStyle`
(1 bold, 2 italic, 4 underline; add them up), `strokeWidth`, `dashed=1`, `opacity`,
`shadow=1`, `rounded=1`, `align`, `verticalAlign`. Colours adapt to dark mode
automatically; `light-dark(#light,#dark)` sets both explicitly.

## Edges

Full form: `{"from": "a", "to": "b", "label": "text", "style": ..., "arrow": ...}`.
Short form: `["a", "b"]` or `["a", "b", "label"]`.

- Endpoints may be node ids or group ids. An endpoint that was never declared is created
  as a plain box (with a warning) rather than failing.
- `style`: palette names colour the line; `dashed`, `dotted`, `thick`, `curved`,
  `straight`; raw fragments such as `"endArrow=block;endFill=0;"`.
- `arrow`: `normal` (default), `none`, `both`, `open`, `circle`, `cross`, and the UML set
  `inherit`, `realize`, `depend`, `compose`, `aggregate`.
- `startLabel`, `endLabel`: small labels near each end (multiplicities, roles).
- Two edges between the same pair (either direction) are drawn side by side. Cycles and
  self-loops are fine.

Edges default to rounded orthogonal connectors with attachment sides and waypoints
chosen by the layout, so long edges do not run through boxes. If you switch an edge to
another routing (`straight`, `curved`, or `edgeStyle=entityRelationEdgeStyle;` for ER),
draw.io picks the attachment points itself. Keep one edge style per diagram: orthogonal
for flowcharts and architecture, straight for UML class diagrams, entity-relation for ER.

## Tables (ER entities, UML classes)

A node with `rows` is drawn as a header plus stacked rows. `"---"` inserts a divider line.

```json
{"id": "order", "label": "Order", "rows": ["id : int  [PK]", "customer_id : int  [FK]", "---", "total() : Money"]}
```

Relationship markers go in the edge style. ER crow's-feet (use `"direction": "LR"`):
`"edgeStyle=entityRelationEdgeStyle;startArrow=ERmandOne;endArrow=ERzeroToMany;startFill=0;endFill=0;startSize=12;endSize=12;"`
(markers: `ERone`, `ERmandOne`, `ERzeroToOne`, `ERmany`, `ERoneToMany`, `ERzeroToMany`).

UML: put the parent/whole first so it is laid out on top, with the marker at the start:
`"style": ["straight", "startArrow=block;startFill=0;startSize=14;endArrow=none;"]` for
inheritance, `startArrow=diamondThin;startFill=1` for composition (`startFill=0` for
aggregation). For a stereotype, use the first label line: `"label": "«interface»\nRepository"`.

The quickest way to see a correct table spec is to convert a small Mermaid `erDiagram` or
`classDiagram` with `--spec-out -`.

## Metadata, tags, links

```json
{"id": "auth", "label": "Auth service", "tags": ["critical", "v2"],
 "data": {"owner": "Team Backend", "status": "active"},
 "tooltip": "Owner: %owner%", "link": "https://wiki.example.com/auth"}
```

- `tags`: categories the viewer can filter by in draw.io (Edit > Tags).
- `data`: custom properties stored on the shape. `%key%` in the label or tooltip shows a
  value (`"label": "Auth\n%status%"`); draw.io's built-ins such as `%date%` and `%page%`
  work too. Use `%%` for a literal percent sign in such labels.
- `link`: makes the shape clickable. `tooltip`: hover text.

## Sequence diagrams

```json
{
  "type": "sequence",
  "title": "Login",
  "autonumber": true,
  "participants": [
    {"id": "u", "label": "User", "shape": "actor"},
    {"id": "web", "label": "Web app"},
    {"id": "auth", "label": "Auth service"}
  ],
  "messages": [
    {"from": "u", "to": "web", "label": "submit credentials"},
    {"from": "web", "to": "auth", "label": "POST /token"},
    {"block": "alt", "label": "valid", "items": [
        {"from": "auth", "to": "web", "label": "200 + JWT", "kind": "reply"}
      ],
      "else": [{"label": "invalid", "items": [
        {"from": "auth", "to": "web", "label": "401", "kind": "reply"}
      ]}]
    },
    {"note": "Token lives 15 min", "over": ["web", "auth"]},
    {"from": "web", "to": "web", "label": "store session"}
  ]
}
```

- `participants`: left-to-right order. `"shape": "actor"` marks a person (green head).
  Participants that only appear in messages are added in order of appearance.
- Message `kind`: `sync` (default, solid filled arrow), `reply` (dashed), `async` (open
  arrow), `lost` (ends in a cross). `from` equal to `to` draws a self-call.
- Note: `{"note": "text", "over": ["a"]}`, or two ids to span; `"side": "left"` or
  `"right"` puts it beside a single participant.
- Block: `{"block": "loop" | "alt" | "opt" | "par" | any word, "label": "condition",
  "items": [...]}`; further sections go in `"else": [{"label": ..., "items": [...]}]`.
  Blocks nest.
- `autonumber`: prefix messages with 1., 2., ...

Participants are UML lifelines; messages are attached to them and move along when the
user drags a lifeline sideways.

## Several pages

```json
{"styles": {}, "pages": [ {"title": "Overview", "nodes": [], "edges": []},
                          {"title": "Login flow", "type": "sequence", "messages": []} ]}
```

Top-level `styles`, `meta` and `direction` are inherited by every page. With a template,
every page is built on a fresh copy of the template page.

## Recipes

**Org chart / tree**: `TB`, one edge per reporting line from manager to report, `"arrow": "none"`.

**Cloud / network architecture**: `LR`; one group per account, VPC, zone or tier, nested as
in reality; library shapes from `shapes` for services; `actor` or `cloud` for the outside
world; edge labels for protocols. Route fan-in through a gateway or bus node.

**Process with roles**: one group per role, steps inside, `LR`.

**Decision flow**: the happy path is the first edge out of each decision so it runs
straight; label every branch.

**Big diagrams** (40+ nodes): split into pages - an overview of groups, then one page per
group - instead of one unreadable sheet.
