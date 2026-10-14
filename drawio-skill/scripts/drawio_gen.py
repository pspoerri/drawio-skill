#!/usr/bin/env python3
"""Generate, inspect and validate draw.io (.drawio) files. Python 3.9+, standard library only.

  drawio_gen.py build    SPEC.json  -o out.drawio [--template T.drawio]
  drawio_gen.py mermaid  IN.mmd|.md -o out.drawio [--template T.drawio]
  drawio_gen.py shapes   QUERY...                 search draw.io's shape libraries and icons
  drawio_gen.py inspect  FILE.drawio
  drawio_gen.py validate FILE.drawio [--repair]
  drawio_gen.py export   FILE.drawio -f png|svg|pdf   (needs draw.io desktop)
  drawio_gen.py cli                                print the draw.io desktop executable, if installed
  drawio_gen.py update   [--shapes]                refresh the vendored upstream references / shape index

SPEC/IN may be '-' to read stdin.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import os  # noqa: E402
import tempfile  # noqa: E402

from dio import mermaid, shapes, upstream  # noqa: E402
from dio.cli import CliError, find_cli, run_cli  # noqa: E402
from dio.render import build_document, write_mxfile  # noqa: E402
from dio.spec import SpecError, normalize  # noqa: E402
from dio.template import DrawioFileError, Template, describe  # noqa: E402
from dio.validate import repair_text, validate  # noqa: E402


def read_input(path):
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"error: cannot read {path}: {exc.strerror or exc}")


def report(path):
    errors, warnings, stats = validate(path)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    status = "INVALID" if errors else "ok"
    print(f"{path}: {status} - {stats['pages']} page(s), {stats['vertices']} shapes, {stats['edges']} connectors")
    return 1 if errors else 0


def generate(spec, args):
    warnings = []
    pages = normalize(spec, warnings)
    if args.direction:
        for page in pages:
            if page["type"] == "graph":
                page["direction"] = args.direction
    template = Template(args.template, args.template_page) if args.template else None
    values = {}
    for item in args.set or []:
        if "=" not in item:
            raise SystemExit(f"error: --set expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        values[key.strip()] = value
    at = None
    if args.at:
        try:
            at = tuple(float(v) for v in args.at.split(","))
            assert len(at) == 2
        except (ValueError, AssertionError):
            raise SystemExit(f"error: --at expects X,Y, got {args.at!r}")
    mxfile = build_document(pages, template, args.template_mode, values, at, warnings)
    write_mxfile(mxfile, args.output)
    for w in dict.fromkeys(warnings):
        print(f"warning: {w}", file=sys.stderr)
    return 0 if args.output == "-" else report(args.output)


def cmd_build(args):
    text = read_input(args.spec)
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {args.spec} is not valid JSON: {exc}")
    return generate(spec, args)


def mermaid_via_cli(source, args):
    """Let draw.io's own Mermaid parser convert and lay out the diagram."""
    if not args.output or args.output == "-":
        raise SystemExit("error: the draw.io engine needs -o OUT.drawio")
    with tempfile.TemporaryDirectory() as tmp:
        mmd = os.path.join(tmp, "diagram.mmd")
        with open(mmd, "w", encoding="utf-8") as fh:
            fh.write(source)
        run_cli(["-x", "-f", "xml", "-o", args.output, mmd], expect=args.output)
    print("converted by the draw.io desktop CLI", file=sys.stderr)
    return report(args.output)


def cmd_mermaid(args):
    blocks = mermaid.extract_blocks(read_input(args.input))
    if args.engine == "drawio":
        if len(blocks) != 1 or args.template:
            raise SystemExit("error: --engine drawio converts one diagram and cannot apply a template; "
                             "use the built-in engine for templates and multi-diagram Markdown")
        return mermaid_via_cli(blocks[0], args)
    try:
        specs = [mermaid.parse(block) for block in blocks]
    except mermaid.UnsupportedMermaid as exc:
        # draw.io itself understands every Mermaid type; use it when it is installed and nothing else is asked.
        if args.engine == "auto" and len(blocks) == 1 and not args.template and not args.spec_out and find_cli():
            print(f"note: {exc}", file=sys.stderr)
            return mermaid_via_cli(blocks[0], args)
        raise
    spec = specs[0] if len(specs) == 1 else {"pages": specs}
    if args.title and len(specs) == 1:
        spec["title"] = args.title
    if args.spec_out:
        text = json.dumps(spec, indent=2, ensure_ascii=False)
        if args.spec_out == "-":
            print(text)
            return 0
        Path(args.spec_out).write_text(text + "\n", encoding="utf-8")
        print(f"spec written to {args.spec_out}", file=sys.stderr)
    if not args.output:
        raise SystemExit("error: give -o OUT.drawio (or --spec-out to only produce the intermediate spec)")
    return generate(spec, args)


def cmd_shapes(args):
    index, _ = upstream.load_index(refresh=args.refresh)
    results = shapes.search(index, " ".join(args.query), args.limit, icons=not args.no_icons)
    if not results:
        print("no shapes found; try fewer or more general words", file=sys.stderr)
        return 1
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    return 0


def cmd_export(args):
    output = args.output or f"{args.file}.{args.format}"
    cli_args = ["-x", "-f", args.format, "-b", "10", "-o", output]
    if args.format != "jpg":
        cli_args.append("-e")  # embed the diagram so the image stays editable in draw.io
    if args.layout:
        cli_args += ["--layout", args.layout]
    run_cli(cli_args + [args.file], expect=output)
    print(output)
    return 0


def cmd_cli(args):
    exe = find_cli()
    if not exe:
        print("draw.io desktop not found (set DRAWIO_CMD to its executable if it is installed elsewhere)", file=sys.stderr)
        return 1
    print(exe)
    return 0


def cmd_update(args):
    for path in upstream.update_references():
        print(f"updated {path}")
    if args.shapes:
        index, path = upstream.load_index(refresh=True)
        print(f"updated {path} ({len(index)} shapes)")
    return 0


def cmd_inspect(args):
    print(describe(args.file))
    return 0


def cmd_validate(args):
    if args.repair:
        for path in args.files:
            text = Path(path).read_text(encoding="utf-8")
            fixed = repair_text(text)
            if fixed != text:
                Path(path).write_text(fixed, encoding="utf-8")
                print(f"{path}: repaired", file=sys.stderr)
    return max(report(path) for path in args.files)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("-o", "--output", help="output .drawio path ('-' for stdout)")
        p.add_argument("--template", help="a .drawio file to take styles / frame / placeholders from")
        p.add_argument("--template-mode", choices=("auto", "style", "frame"), default="auto",
                       help="style: copy styles, drop sample cells; frame: keep all template content; "
                            "auto (default): frame if the template has a {{diagram}} cell, else style")
        p.add_argument("--template-page", help="template page name or 1-based index (default: first)")
        p.add_argument("--set", action="append", metavar="KEY=VALUE", help="fill a {{KEY}} placeholder in the template")
        p.add_argument("--at", metavar="X,Y", help="top-left position of the generated diagram")
        p.add_argument("--direction", choices=("TB", "BT", "LR", "RL"), help="override the flow direction")

    p = sub.add_parser("build", help="JSON spec -> .drawio")
    p.add_argument("spec")
    common(p)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("mermaid", help="Mermaid (.mmd, or Markdown with ```mermaid blocks) -> .drawio")
    p.add_argument("input")
    common(p)
    p.add_argument("--title", help="page name")
    p.add_argument("--spec-out", metavar="PATH", help="also write the intermediate JSON spec ('-' prints it and stops)")
    p.add_argument("--engine", choices=("auto", "builtin", "drawio"), default="auto",
                   help="builtin: this script's converter and layout (works with templates); drawio: the draw.io "
                        "desktop CLI's own Mermaid parser (every diagram type); auto (default): builtin, falling "
                        "back to drawio for diagram types builtin cannot convert")
    p.set_defaults(func=cmd_mermaid)

    p = sub.add_parser("shapes", help="search draw.io's shape libraries (AWS, Azure, Cisco, BPMN, ...) and icons")
    p.add_argument("query", nargs="+")
    p.add_argument("-n", "--limit", type=int, default=10)
    p.add_argument("--no-icons", action="store_true", help="do not query the online icon service")
    p.add_argument("--refresh", action="store_true", help="download the shape index again")
    p.set_defaults(func=cmd_shapes)

    p = sub.add_parser("export", help="export to png/svg/pdf with the draw.io desktop CLI")
    p.add_argument("file")
    p.add_argument("-f", "--format", choices=("png", "svg", "pdf", "jpg"), default="png")
    p.add_argument("-o", "--output")
    p.add_argument("--layout", help="apply an ELK layout preset first (verticalFlow, horizontalFlow, ..., libavoid)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("cli", help="print the path of the draw.io desktop executable")
    p.set_defaults(func=cmd_cli)

    p = sub.add_parser("update", help="refresh references/upstream from github.com/jgraph/drawio-mcp")
    p.add_argument("--shapes", action="store_true", help="also re-download the shape index")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("inspect", help="summarise a .drawio file (pages, cells, styles, placeholders)")
    p.add_argument("file")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("validate", help="check that .drawio files are structurally sound")
    p.add_argument("files", nargs="+")
    p.add_argument("--repair", action="store_true",
                   help="first fix unescaped < and & in attribute values, stray text around the XML and comments")
    p.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    if args.command == "build" and not args.output:
        parser.error("build needs -o OUT.drawio")
    try:
        return args.func(args)
    except (SpecError, DrawioFileError, mermaid.UnsupportedMermaid, CliError, upstream.UpstreamError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
