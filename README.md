# drawio skill

An agent skill that creates working draw.io (`.drawio`) files from a text description or
from Mermaid, with or without a `.drawio` template. The diagrams it produces have automatic
layout, attached connectors, no overlapping shapes, and real library shapes (AWS, Azure,
Kubernetes, Cisco, BPMN, ...). Every file is validated against the official draw.io schema.

This repository *is* the skill: `SKILL.md` sits at the root together with its scripts and
references. It follows the open [Agent Skills](https://agentskills.io) format, so any
agent that supports skills can use it, not only Claude. Its only dependency is
Python 3.9+, standard library only.

## Install

Clone the repository into your agent's skills directory. **Name the folder `drawio`.**
The skill's `name` in `SKILL.md` is `drawio`, and several agents require the folder name
to match it.

### Claude Code

```bash
git clone <repo-url> ~/.claude/skills/drawio                     # all projects
# or, for one project only:
git clone <repo-url> /path/to/project/.claude/skills/drawio
```

Start a new session. `/drawio` should be listed, and Claude picks it up when you ask for
a draw.io diagram. Custom subagents (`.claude/agents/*.md`) can preload it with
`skills: [drawio]` in their frontmatter.

Update with `git -C ~/.claude/skills/drawio pull`. Remove by deleting the folder.

### Other agents

Clone into the matching directory instead. These are the locations the agents looked in
at the time of writing; check your agent's documentation if one does not work.

| Agent | Global (all projects) | Per project |
| --- | --- | --- |
| Shared location read by several agents | `~/.agents/skills/drawio` | `.agents/skills/drawio` |
| OpenAI Codex | `~/.codex/skills/drawio` | `.agents/skills/drawio` |
| Cursor | `~/.cursor/skills/drawio` | `.cursor/skills/drawio` |
| GitHub Copilot (VS Code, CLI) | `~/.copilot/skills/drawio` | `.github/skills/drawio` (also reads `.claude/skills/`) |
| Gemini CLI | `~/.gemini/skills/drawio` | `.gemini/skills/drawio` |

To use it with several agents, clone once and symlink the clone into the others, so that
one `git pull` updates them all:

```bash
git clone <repo-url> ~/.claude/skills/drawio
for dir in ~/.agents/skills ~/.codex/skills ~/.cursor/skills; do
  mkdir -p "$dir" && ln -sfn ~/.claude/skills/drawio "$dir/drawio"
done
```

### Agents without skill support

Clone it anywhere and point the agent at the instructions from its rules file
(`AGENTS.md`, `.cursorrules`, `CLAUDE.md`, ...):

```markdown
## draw.io diagrams
To create or edit .drawio files, read /absolute/path/to/drawio/SKILL.md and follow it.
The generator is /absolute/path/to/drawio/scripts/drawio_gen.py.
```

### claude.ai / Claude Desktop

Zip the skill without the repository extras and upload it under Settings > Capabilities >
Skills:

```bash
zip -r drawio.zip SKILL.md scripts references assets -x '*__pycache__*'
```

Shape search needs network access in that environment; everything else works offline.

## Use

Ask your agent, for example:

- "Create a draw.io diagram of our checkout flow: ..."
- "Convert `docs/architecture.md` (it has Mermaid blocks) to drawio."
- "AWS architecture with API Gateway, Lambda and DynamoDB, as a .drawio file."
- "Put this diagram into our `template.drawio`, title 'Payments', author Ana."

Or call the generator yourself, from the skill folder:

```bash
python3 scripts/drawio_gen.py build    spec.json   -o out.drawio [--template assets/template-example.drawio]
python3 scripts/drawio_gen.py mermaid  diagram.mmd -o out.drawio
python3 scripts/drawio_gen.py shapes   aws lambda           # search draw.io's shape libraries
python3 scripts/drawio_gen.py inspect  template.drawio      # what a file / template contains
python3 scripts/drawio_gen.py validate out.drawio [--repair]
python3 scripts/drawio_gen.py export   out.drawio -f png    # needs draw.io desktop
```

[`examples/`](examples/) has generated files to open in draw.io.

## What is inside

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Instructions the agent follows. |
| `scripts/drawio_gen.py` | Generator CLI: JSON spec or Mermaid to `.drawio`, layout, templates, shape search, validation, export. |
| `references/spec.md`, `templates.md` | The JSON spec format and how templates are interpreted. |
| `references/upstream/` | Official draw.io XML, style and Mermaid references plus `mxfile.xsd`, vendored from [jgraph/drawio-mcp](https://github.com/jgraph/drawio-mcp) (`shared/`, Apache-2.0). |
| `assets/template-example.drawio` | Example template: locked frame with `{{title}}`/`{{author}}`/`{{date}}`, a `{{diagram}}` slot, and a style-sample page. |
| `data/` (git-ignored) | Cache of the official shape index (about 5 MB), downloaded on the first `shapes` search. |
| `examples/` | Sample output. |

Mermaid support: the generator converts flowchart, sequence, class, ER and state diagrams
itself. Other Mermaid types are converted by the draw.io desktop app when it is installed.

Shape search is a Python port of `shared/shape-search.js` and `shared/icon-search.js` from
jgraph/drawio-mcp and uses its `search-index.json`, which upstream regenerates on every
draw.io release. To refresh the references and the index:

```bash
python3 scripts/drawio_gen.py update --shapes
```

## Optional: draw.io desktop

With the [desktop app](https://github.com/jgraph/drawio-desktop/releases) installed, the
skill can also do three more things:

- export PNG, SVG and PDF;
- convert the Mermaid types the built-in converter does not cover (gantt, mindmap, pie, ...);
- apply ELK layouts to hand-written XML.

If the app is not on the default path, set `DRAWIO_CMD` to its executable. Sandboxed
agents usually cannot start the app. The skill then says so and carries on without it.
