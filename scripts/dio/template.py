"""Reading .drawio files and using one as a template (styles, frame, placeholders)."""

import base64
import copy
import html
import re
import zlib
from collections import Counter, defaultdict
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from .styles import APPEARANCE_KEYS, parse_style, pick_keys, style_get, style_has_token

PLACEHOLDER = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")
_TAG = re.compile(r"<[^>]+>")


class DrawioFileError(ValueError):
    pass


def load_mxfile(path):
    """Parse a .drawio/.xml/.drawio.svg file into an <mxfile> element with plain (uncompressed) pages."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise DrawioFileError(f"{path}: not well-formed XML ({exc})") from exc
    except OSError as exc:
        raise DrawioFileError(f"{path}: {exc.strerror or exc}") from exc
    if root.tag.endswith("svg"):
        content = root.get("content")
        if not content:
            raise DrawioFileError(f"{path}: SVG has no embedded draw.io diagram (no 'content' attribute)")
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise DrawioFileError(f"{path}: embedded diagram is not well-formed XML ({exc})") from exc
    if root.tag == "mxGraphModel":
        mxfile = ET.Element("mxfile")
        ET.SubElement(mxfile, "diagram", {"id": "page-1", "name": "Page-1"}).append(root)
        return mxfile
    if root.tag != "mxfile":
        raise DrawioFileError(f"{path}: root element is <{root.tag}>, expected <mxfile>")
    for diagram in root.findall("diagram"):
        if diagram.find("mxGraphModel") is None:
            text = (diagram.text or "").strip()
            if not text:
                raise DrawioFileError(f"{path}: page {diagram.get('name')!r} is empty")
            try:
                xml = unquote(zlib.decompress(base64.b64decode(text), -15).decode("utf-8"))
                diagram.append(ET.fromstring(xml))
            except Exception as exc:
                raise DrawioFileError(f"{path}: cannot decode compressed page {diagram.get('name')!r} ({exc})") from exc
            diagram.text = None
    if not root.findall("diagram"):
        raise DrawioFileError(f"{path}: no <diagram> pages found")
    return root


def plain_text(label):
    text = re.sub(r"<br\s*/?>", " ", label or "", flags=re.I)
    return " ".join(html.unescape(_TAG.sub("", text)).split())


class Cell:
    """One entry under <root>: an <mxCell>, possibly wrapped in <object>/<UserObject>."""

    def __init__(self, element):
        self.element = element
        self.cell = element if element.tag == "mxCell" else element.find("mxCell")
        if self.cell is None:
            self.cell = ET.Element("mxCell")
        self.id = element.get("id")
        self.label_attr = "value" if element.tag == "mxCell" else "label"
        self.label = element.get(self.label_attr) or ""
        self.style = self.cell.get("style") or ""
        self.parent = self.cell.get("parent")
        self.vertex = self.cell.get("vertex") == "1"
        self.edge = self.cell.get("edge") == "1"
        self.source, self.target = self.cell.get("source"), self.cell.get("target")
        self.geometry = self.cell.find("mxGeometry")

    def rect(self):
        g = self.geometry
        if g is None:
            return None
        try:
            return tuple(float(g.get(k) or 0) for k in ("x", "y", "width", "height"))
        except ValueError:
            return None


def page_cells(diagram):
    root = diagram.find("mxGraphModel/root")
    if root is None:
        return None, []
    return root, [Cell(el) for el in root if el.tag in ("mxCell", "object", "UserObject")]


def kind_of(style, has_children=False):
    """Map a draw.io vertex style to one of our shape kinds (or None if it isn't one)."""
    shape = (style_get(style, "shape") or "").lower()
    if shape == "image" or style_has_token(style, "image"):
        return None
    if shape == "umllifeline":
        return "lifeline"
    if shape == "umlframe":
        return "frame"
    if style_has_token(style, "swimlane") or shape == "swimlane":
        return "table" if style_get(style, "childLayout") == "stackLayout" else "group"
    if has_children or style_get(style, "container") == "1":
        return "group"
    if style_has_token(style, "rhombus") or shape == "rhombus":
        return "diamond"
    if shape.startswith("cylinder") or shape == "datastore":
        return "cylinder"
    for name, kind in (("hexagon", "hexagon"), ("parallelogram", "parallelogram"), ("trapezoid", "trapezoid"),
                       ("document", "document"), ("process", "subroutine"), ("cloud", "cloud"),
                       ("umlactor", "actor"), ("note", "note"), ("endstate", "final")):
        if shape == name:
            return kind
    if style_has_token(style, "text"):
        return "text"
    if style_has_token(style, "line") or shape == "line":
        return None
    if style_has_token(style, "ellipse") or shape == "ellipse":
        return "circle" if style_get(style, "aspect") == "fixed" else "ellipse"
    if shape:
        return None
    if style_get(style, "rounded") == "1":
        try:
            if float(style_get(style, "arcSize", "0")) >= 40 and style_get(style, "absoluteArcSize") != "1":
                return "terminator"
        except ValueError:
            pass
        return "rounded"
    return "rect"


class Template:
    """A .drawio file used as a style source and/or as a frame around the generated diagram."""

    def __init__(self, path, page=None):
        self.path = str(path)
        self.mxfile = load_mxfile(path)
        diagrams = self.mxfile.findall("diagram")
        self.diagram = self._pick(diagrams, page)
        self.kinds = {}     # kind -> style string
        self.named = {}     # lower-case label -> (kind, style, is_edge)
        self.dominant = ""  # appearance keys of the most common box style
        self.samples = defaultdict(Counter)
        for diagram in diagrams:
            self._harvest(diagram)
        for kind, counter in self.samples.items():
            self.kinds[kind] = counter.most_common(1)[0][0]
        boxes = Counter()
        for kind in ("rect", "rounded", "terminator", "ellipse", "diamond", "cylinder", "hexagon"):
            boxes.update(self.samples.get(kind, {}))
        if boxes:
            self.dominant = pick_keys(boxes.most_common(1)[0][0], APPEARANCE_KEYS)

    def _pick(self, diagrams, page):
        if page is None:
            return diagrams[0]
        for d in diagrams:
            if d.get("name") == str(page):
                return d
        try:
            return diagrams[int(page) - 1]
        except (ValueError, IndexError):
            names = ", ".join(repr(d.get("name")) for d in diagrams)
            raise DrawioFileError(f"{self.path}: no page {page!r} (pages: {names}; or use a 1-based index)") from None

    def _harvest(self, diagram):
        _, cells = page_cells(diagram)
        by_id = {c.id: c for c in cells}
        has_children = {c.parent for c in cells if c.vertex}

        def locked(cell):
            while cell is not None and cell.parent != "0":
                cell = by_id.get(cell.parent)
            return cell is not None and style_get(cell.style, "locked") == "1"

        for c in cells:
            if not c.style or not (c.vertex or c.edge):
                continue
            text = plain_text(c.label)
            # Frames, rules and logos are unlabelled or locked; only labelled shapes are style samples.
            if PLACEHOLDER.search(text) or locked(c) or (c.vertex and not text):
                continue
            if c.edge:
                kind = "edge"
            else:
                parent = by_id.get(c.parent)
                if parent is not None and parent.vertex and kind_of(parent.style, True) == "table":
                    kind = "table_row" if style_has_token(c.style, "text") else None
                else:
                    kind = kind_of(c.style, c.id in has_children)
            if not kind:
                continue
            self.samples[kind][c.style] += 1
            if text and kind != "table_row":
                self.named.setdefault(text.lower(), (kind, c.style, c.edge))

    def fresh_page(self):
        return copy.deepcopy(self.diagram)


def _abs_origin(cell, by_id):
    x = y = 0.0
    cur = cell
    while cur is not None and cur.vertex:
        rect = cur.rect() or (0, 0, 0, 0)
        x, y = x + rect[0], y + rect[1]
        cur = by_id.get(cur.parent)
    return x, y


def prepare_page(diagram, mode, values, warnings):
    """Strip/keep template content and work out where the generated diagram goes.

    Returns dict(model, root, layer, origin, region, ids, mode).
    """
    model = diagram.find("mxGraphModel")
    root, cells = page_cells(diagram)
    if root is None:
        raise DrawioFileError("template page has no <mxGraphModel><root>")
    by_id = {c.id: c for c in cells}
    kids = defaultdict(list)
    for c in cells:
        kids[c.parent].append(c)

    def descendants(cell):
        out, stack = [], list(kids[cell.id])
        while stack:
            cur = stack.pop()
            out.append(cur)
            stack.extend(kids[cur.id])
        return out

    layers = [c for c in cells if c.parent == "0"]
    locked = [c for c in layers if style_get(c.style, "locked") == "1"]
    slot = next((c for c in cells if c.vertex and re.fullmatch(r"\{\{\s*diagram\s*\}\}", plain_text(c.label), re.I)), None)
    if mode == "auto":
        mode = "frame" if slot is not None else "style"

    origin, region = None, None
    remove = set()
    if slot is not None:
        rect = slot.rect() or (0, 0, 0, 0)
        px, py = _abs_origin(by_id.get(slot.parent), by_id)
        origin, region = (px + rect[0], py + rect[1]), (rect[2], rect[3])
        remove.update([slot.id] + [d.id for d in descendants(slot)])

    if mode == "style":
        keep = {c.id for c in cells if c.parent is None or c.parent == "0"}
        for layer in locked:
            keep.update(d.id for d in descendants(layer))
        for c in cells:
            if c.id not in remove and PLACEHOLDER.search(plain_text(c.label)):
                keep.add(c.id)
                keep.update(d.id for d in descendants(c))
                cur = by_id.get(c.parent)
                while cur is not None:
                    keep.add(cur.id)
                    cur = by_id.get(cur.parent)
        remove.update(c.id for c in cells if c.id not in keep)

    # Edges must not dangle once their endpoints are gone.
    for c in cells:
        if c.edge and (c.source in remove or c.target in remove):
            remove.add(c.id)
    for c in cells:
        if c.id in remove:
            root.remove(c.element)
    cells = [c for c in cells if c.id not in remove]

    for c in cells:
        def fill(match):
            key = match.group(1)
            if key.lower() in values:
                return html.escape(values[key.lower()], quote=False)
            warnings.append(f"template placeholder {{{{{key}}}}} left as is (pass --set {key}=VALUE or add it to spec 'meta')")
            return match.group(0)
        if "{{" in c.label:
            c.element.set(c.label_attr, PLACEHOLDER.sub(fill, c.label))

    ids = {c.id for c in cells}
    layer = next((c.id for c in layers if c not in locked), None)
    if layer is None:
        layer = "layer-diagram"
        n = 2
        while layer in ids:
            layer, n = f"layer-diagram-{n}", n + 1
        ET.SubElement(root, "mxCell", {"id": layer, "value": "Diagram", "parent": "0"})
        ids.add(layer)

    if origin is None:
        locked_ids = {l.id for l in locked}
        rects = [c.rect() for c in cells if c.vertex and c.parent not in locked_ids and by_id.get(c.parent) in layers and c.rect()]
        if rects:
            origin = (min(r[0] for r in rects), max(r[1] + r[3] for r in rects) + 40)
            if mode == "frame":
                warnings.append("template has no {{diagram}} placeholder cell: the diagram was placed below the existing "
                                "content. Add a rectangle labelled {{diagram}} to the template, or pass --at X,Y.")
        else:
            origin = (40.0, 40.0)
    return {"model": model, "root": root, "layer": layer, "origin": origin, "region": region, "ids": ids, "mode": mode}


def describe(path):
    """Human-readable summary of a .drawio file, for choosing how to use it as a template."""
    mxfile = load_mxfile(path)
    lines = [f"{path}: {len(mxfile.findall('diagram'))} page(s)"]
    for index, diagram in enumerate(mxfile.findall("diagram"), 1):
        model = diagram.find("mxGraphModel")
        root, cells = page_cells(diagram)
        by_id = {c.id: c for c in cells}
        has_children = {c.parent for c in cells if c.vertex}
        attrs = " ".join(f"{k}={model.get(k)}" for k in ("pageWidth", "pageHeight", "background", "grid") if model is not None and model.get(k))
        lines.append(f"\nPage {index}: {diagram.get('name')!r}  {attrs}")
        layers = [c for c in cells if c.parent == "0"]
        for layer in layers:
            count = sum(1 for c in cells if c.parent == layer.id)
            flag = " [locked: always kept]" if style_get(layer.style, "locked") == "1" else ""
            lines.append(f"  layer {layer.id!r} {plain_text(layer.label) or '(default)'}: {count} top-level cells{flag}")
        placeholders = []
        lines.append("  cells:")
        for c in cells:
            if not (c.vertex or c.edge):
                continue
            text = plain_text(c.label)
            placeholders += PLACEHOLDER.findall(text)
            if c.edge:
                what = f"edge {c.source or '?'} -> {c.target or '?'}"
            else:
                parent = by_id.get(c.parent)
                in_table = parent is not None and parent.vertex and kind_of(parent.style, True) == "table"
                kind = "row" if in_table else "edge-label" if parent is not None and parent.edge else (
                    kind_of(c.style, c.id in has_children) or "other")
                rect = c.rect()
                geo = "" if rect is None else " @{:g},{:g} {:g}x{:g}".format(*rect)
                what = f"{kind}{geo}"
            label = f" {text[:40]!r}" if text else ""
            style = c.style if len(c.style) <= 90 else c.style[:87] + "..."
            lines.append(f"    [{c.id}] {what}{label} parent={c.parent}\n        {style}")
        if placeholders:
            lines.append(f"  placeholders: {', '.join('{{' + p + '}}' for p in dict.fromkeys(placeholders))}")
    template = Template(path)
    lines.append("\nStyles the generator will pick up from this file:")
    if not template.kinds:
        lines.append("  (none - the file has no styled cells; built-in styles will be used)")
    for kind, style in sorted(template.kinds.items()):
        lines.append(f"  shape {kind!r}: {style}")
    if template.named:
        lines.append("Named styles (use as \"style\": \"<name>\" on a node or edge):")
        for name, (kind, _, is_edge) in sorted(template.named.items()):
            lines.append(f"  {name!r} ({'edge' if is_edge else kind})")
    has_slot = any(p.lower() == "diagram" for d in mxfile.findall("diagram") for c in page_cells(d)[1]
                   for p in PLACEHOLDER.findall(plain_text(c.label)))
    lines.append("\nDefault template mode: " + (
        "frame ({{diagram}} placeholder found: all content is kept, the diagram replaces the placeholder)" if has_slot else
        "style (no {{diagram}} placeholder: styles are copied, sample cells are dropped; locked layers and "
        "cells with {{placeholders}} are kept). Use --template-mode frame to keep everything."))
    return "\n".join(lines)
