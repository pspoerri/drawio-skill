"""Turn normalised page specs into draw.io XML (optionally inside a template page)."""

import datetime
import html
import math
import re
import textwrap
from collections import defaultdict
from xml.etree import ElementTree as ET

from . import styles as S
from .layout import layout_graph
from .template import prepare_page

CHAR_W = 7.0
LINE_H = 18
PORT_KEYS = {"exitX", "exitY", "exitDx", "exitDy", "exitPerimeter", "entryX", "entryY", "entryDx", "entryDy", "entryPerimeter"}
MODEL_ATTRS = {
    "dx": "1200", "dy": "800", "grid": "1", "gridSize": "10", "guides": "1", "tooltips": "1", "connect": "1",
    "arrows": "1", "fold": "1", "page": "1", "pageScale": "1", "pageWidth": "827", "pageHeight": "1169",
    "math": "0", "shadow": "0", "adaptiveColors": "auto",
}


def html_label(text):
    return html.escape(text, quote=False).replace("\n", "<br>")


def wrap_lines(text, width=24):
    lines = []
    for line in text.split("\n"):
        lines.extend(textwrap.wrap(line, width, break_long_words=False) or [""])
    return lines


def text_size(text, width=24, scale=1.0):
    lines = wrap_lines(text, width)
    return max(len(line) for line in lines) * CHAR_W * scale, len(lines) * LINE_H * scale


def up(value, step=20):
    return int(math.ceil(value / step) * step)


def r10(value):
    return int(math.floor(value / 10 + 0.5) * 10)


class IdGen:
    def __init__(self, used=()):
        self.used = set(used) | {"0", "1"}

    def make(self, base):
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", str(base)).strip("_") or "cell"
        candidate, n = base, 2
        while candidate in self.used:
            candidate, n = f"{base}_{n}", n + 1
        self.used.add(candidate)
        return candidate


class StyleContext:
    """Resolves the style of every cell from: template samples, spec styles, palette names, raw strings."""

    def __init__(self, template, page_styles, warnings):
        self.template, self.styles, self.warnings = template, page_styles, warnings
        self._warned = set()

    def kind(self, kind):
        t = self.template
        if t and kind in t.kinds:
            return t.kinds[kind]
        if t and kind == "rect" and "rounded" in t.kinds:  # a template with only rounded boxes means boxes are rounded
            return t.kinds["rounded"]
        if t and kind == "circle" and "ellipse" in t.kinds:
            return S.merge_style(t.kinds["ellipse"], "aspect=fixed;")
        if t and kind == "ellipse" and "circle" in t.kinds:
            return S.format_style([p for p in S.parse_style(t.kinds["circle"]) if p[0] != "aspect"])
        base = S.SHAPES[kind] + S.SHAPE_DEFAULT_COLORS.get(kind, S.DEFAULT_NODE_COLORS)
        if t and t.dominant and kind not in ("text", "actor", "initial", "final", "note"):
            base = S.merge_style(base, t.dominant)
        return base

    def _tokens(self, base, tokens, edge, kind=None, explicit=False):
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if "=" in token:
                # A fragment that names its own shape (e.g. pasted from `shapes` search) is a complete
                # style, not a tweak: blending it with the default box would add stray fills and borders.
                whole = not edge and (S.style_get(token, "shape") or S.style_get(token, "image"))
                base = S.merge_style(token, "") if whole else S.merge_style(base, token)
                continue
            name = token.lower()
            named = self.template.named.get(name) if self.template else None
            if name in self.styles:
                base = S.merge_style(base, self.styles[name])
            elif named and named[2] == edge:
                sample_kind, sample, _ = named
                if edge or not explicit or sample_kind == kind:
                    base = self._strip_ports(sample) if edge else sample
                else:
                    base = S.merge_style(base, S.pick_keys(sample, S.APPEARANCE_KEYS))
            elif edge and name in S.EDGE_PRESETS:
                base = S.merge_style(base, S.EDGE_PRESETS[name])
            elif S.palette_style(name, edge):
                base = S.merge_style(base, S.palette_style(name, edge))
            elif name not in self._warned:
                self._warned.add(name)
                self.warnings.append(f"unknown style name {token!r} ignored (use a palette colour, a name from "
                                     f"'styles', a template label, or a raw 'key=value;' draw.io style)")
        return base

    @staticmethod
    def _strip_ports(style):
        return S.format_style([p for p in S.parse_style(style) if p[0] not in PORT_KEYS])

    def node(self, node):
        style = self._tokens(self.kind(node["shape"]), node["style"], False, node["shape"], node["shape_explicit"])
        return S.merge_style(style, "html=1;")

    def group(self, group):
        if self.template and "group" in self.template.kinds:
            base = S.merge_style(self.template.kinds["group"], "container=1;collapsible=0;")
        else:
            base = S.GROUP_STYLE
        return S.merge_style(self._tokens(base, group["style"], False, "group", True), "html=1;")

    def table_row(self):
        if self.template and "table_row" in self.template.kinds:
            return self.template.kinds["table_row"]
        return S.TABLE_ROW_STYLE

    def edge(self, edge):
        if self.template and "edge" in self.template.kinds:
            base = self._strip_ports(self.template.kinds["edge"])
        else:
            base = S.EDGE_STYLE
        arrow = edge.get("arrow")
        if arrow:
            if arrow in S.ARROWS:
                base = S.merge_style(base, S.ARROWS[arrow])
            else:
                self.warnings.append(f"unknown arrow {arrow!r} ignored (use one of: {', '.join(S.ARROWS)})")
        return S.merge_style(self._tokens(base, edge["style"], True), "html=1;")

    def look(self, kind, keys):
        """Appearance keys of a template kind, to tint built-in sequence-diagram parts."""
        if self.template and kind in self.template.kinds:
            return S.pick_keys(self.template.kinds[kind], keys)
        return ""


def add_vertex(root, cell_id, value, style, parent, x, y, w, h, extra=None, connectable=True):
    """`extra`: attributes for an <object> wrapper (link, tooltip, tags, metadata)."""
    attrs = {"style": style, "vertex": "1", "parent": parent}
    if not connectable:
        attrs["connectable"] = "0"
    if extra:
        wrapper = ET.SubElement(root, "object", {"label": value, **extra, "id": cell_id})
        cell = ET.SubElement(wrapper, "mxCell", attrs)
    else:
        cell = ET.SubElement(root, "mxCell", {"id": cell_id, "value": value, **attrs})
    ET.SubElement(cell, "mxGeometry", {"x": f"{x:g}", "y": f"{y:g}", "width": f"{w:g}", "height": f"{h:g}", "as": "geometry"})
    return cell


def add_edge(root, cell_id, value, style, parent, source=None, target=None, points=(), ends=None):
    attrs = {"id": cell_id, "value": value, "style": style, "edge": "1", "parent": parent}
    if source:
        attrs["source"] = source
    if target:
        attrs["target"] = target
    cell = ET.SubElement(root, "mxCell", attrs)
    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
    if ends:
        for (x, y), name in zip(ends, ("sourcePoint", "targetPoint")):
            ET.SubElement(geo, "mxPoint", {"x": f"{x:g}", "y": f"{y:g}", "as": name})
    if points:
        array = ET.SubElement(geo, "Array", {"as": "points"})
        for x, y in points:
            ET.SubElement(array, "mxPoint", {"x": f"{x:g}", "y": f"{y:g}"})
    return cell


def add_edge_label(root, cell_id, value, edge_id, position):
    cell = ET.SubElement(root, "mxCell", {
        "id": cell_id, "value": value, "vertex": "1", "connectable": "0", "parent": edge_id,
        "style": "edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];labelBackgroundColor=default;",
    })
    geo = ET.SubElement(cell, "mxGeometry", {"x": f"{position:g}", "y": "-12", "relative": "1", "as": "geometry"})
    ET.SubElement(geo, "mxPoint", {"as": "offset"})


# ---------------------------------------------------------------- graph pages

def table_head(node):
    lines = node["label"].count("\n") + 1
    return 26 if lines == 1 else 10 + 16 * lines


def measure_node(node, style):
    try:
        scale = max(0.6, float(S.style_get(style, "fontSize", "12")) / 12)
    except ValueError:
        scale = 1.0
    shape = node["shape"]
    tw, th = text_size(node["label"], 24, scale)
    if shape == "table":
        rows = node["rows"]
        widest = max([len(line) * 1.1 for line in node["label"].split("\n")] + [len(r) for r in rows if r != "---"])
        w = max(160, widest * CHAR_W * scale + 24)
        h = table_head(node) + sum(8 if r == "---" else 26 for r in rows)
    elif shape == "diamond":
        w, h = max(120, tw * 1.6 + 30), max(80, th * 2 + 36)
    elif shape == "ellipse":
        w, h = max(120, tw * 1.3 + 30), max(60, th * 1.5 + 24)
    elif shape == "circle":
        w = h = max(80, tw + 30, th + 30)
    elif shape == "cylinder":
        w, h = max(100, tw + 30), max(80, th + 50)
    elif shape in ("hexagon", "parallelogram", "trapezoid"):
        w, h = max(120, tw + 60), max(60, th + 24)
    elif shape == "document":
        w, h = max(120, tw + 30), max(80, th + 44)
    elif shape == "cloud":
        w, h = max(140, tw * 1.4 + 40), max(80, th * 1.6 + 40)
    elif shape == "actor":
        w, h = 40, 60
    elif shape in ("initial", "final"):
        w = h = 30
    elif shape == "text":
        w, h = max(40, tw + 10), max(20, th + 6)
    elif shape == "note":
        w, h = max(120, tw + 34), max(60, th + 30)
    else:
        w, h = max(120, tw + 30), max(60, th + 24)
    if S.style_get(style, "verticalLabelPosition") == "bottom" and shape != "actor":
        w = h = 60  # an icon with its label underneath: the text does not size the shape
    if shape not in ("actor", "initial", "final"):
        w, h = up(w), up(h)
    return (up(node["width"]) if node["width"] else w, up(node["height"]) if node["height"] else h)


def _sides(a, b, horizontal):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b

    def vertical():
        if by >= ay + ah - 1:
            return "S", "N"
        if by + bh <= ay + 1:
            return "N", "S"

    def sideways():
        if bx >= ax + aw - 1:
            return "E", "W"
        if bx + bw <= ax + 1:
            return "W", "E"

    for test in ((sideways, vertical) if horizontal else (vertical, sideways)):
        found = test()
        if found:
            return found
    return None


def _port(side, t):
    return {"N": (t, 0), "S": (t, 1), "W": (0, t), "E": (1, t)}[side]


class GraphBuilder:
    def __init__(self, page, ctx):
        self.page, self.ctx = page, ctx
        nodes, groups = page["nodes"], page["groups"]
        self.node_style = {nid: ctx.node(n) for nid, n in nodes.items()}
        for nid, n in nodes.items():
            if n["shape"] == "table":
                self.node_style[nid] = S.merge_style(self.node_style[nid], f"startSize={table_head(n)};")
        self.group_style = {gid: ctx.group(g) for gid, g in groups.items()}
        sizes = {nid: measure_node(n, self.node_style[nid]) for nid, n in nodes.items()}
        tops, min_w = {}, {}
        for gid, group in groups.items():
            style = self.group_style[gid]
            if S.style_has_token(style, "swimlane"):
                try:
                    tops[gid] = float(S.style_get(style, "startSize", "23")) + 12
                except ValueError:
                    tops[gid] = 35
            else:
                tops[gid] = 40
            min_w[gid] = up(len(group["label"]) * 7.5 + 40)
        self.layout = layout_graph(page, sizes, tops, min_w)
        self.size = self.layout.size

    def emit(self, root, layer, ox, oy, ids):
        page, lay = self.page, self.layout
        nodes, groups, edges = page["nodes"], page["groups"], page["edges"]
        horizontal = page["direction"] in ("LR", "RL")

        # Snap absolute positions to the grid, then derive container-relative ones.
        snapped = {}
        for key, (x, y, w, h) in lay.abs.items():
            sx, sy = r10(x), r10(y)
            if key in groups:
                w, h = up(x + w - sx, 10), up(y + h - sy, 10)
            snapped[key] = (sx, sy, w, h)
        parent_of = {nid: n["group"] for nid, n in nodes.items()}
        parent_of.update({gid: g["parent"] for gid, g in groups.items()})
        cell_id = {}

        def origin(container):
            return (snapped[container][0], snapped[container][1]) if container is not None else (-ox, -oy)

        def place(key):
            x, y, w, h = snapped[key]
            px, py = origin(parent_of[key])
            return x - px, y - py, w, h

        def depth(gid):
            d = 0
            while groups[gid]["parent"] is not None:
                gid, d = groups[gid]["parent"], d + 1
            return d

        for gid in sorted(groups, key=depth):
            group = groups[gid]
            cell_id[gid] = ids.make("g_" + gid)
            parent = cell_id[group["parent"]] if group["parent"] is not None else layer
            add_vertex(root, cell_id[gid], html_label(group["label"]), self.group_style[gid], parent, *place(gid))

        row_style = self.ctx.table_row()
        for nid, node in nodes.items():
            cell_id[nid] = ids.make("n_" + nid)
            parent = cell_id[node["group"]] if node["group"] is not None else layer
            x, y, w, h = place(nid)
            extra = {k: str(node[k]) for k in ("link", "tooltip") if node[k]}
            if node["tags"]:
                extra["tags"] = " ".join(node["tags"])
            if node["data"]:
                extra.update(node["data"], placeholders="1")
            label = node["label"] if node["html"] else html_label(node["label"])
            add_vertex(root, cell_id[nid], label, self.node_style[nid], parent, x, y, w, h, extra)
            if node["shape"] == "table":
                ry = table_head(node)
                for i, row in enumerate(node["rows"]):
                    rid = ids.make(f"{cell_id[nid]}_r{i + 1}")
                    if row == "---":
                        add_vertex(root, rid, "", S.TABLE_DIVIDER_STYLE, cell_id[nid], 0, ry, w, 8, connectable=False)
                        ry += 8
                    else:
                        add_vertex(root, rid, html_label(row), row_style, cell_id[nid], 0, ry, w, 26, connectable=False)
                        ry += 26

        # Edges between the same two cells are fanned out so they do not overlap.
        bundles = defaultdict(list)
        for i, edge in enumerate(edges):
            bundles[frozenset((edge["from"], edge["to"]))].append(i)
        fraction = {}
        for members in bundles.values():
            for k, i in enumerate(members):
                fraction[i] = (k + 1) / (len(members) + 1)

        def ancestors(key):
            out = set()
            while parent_of[key] is not None:
                key = parent_of[key]
                out.add(key)
            return out

        for i, edge in enumerate(edges):
            src, dst = edge["from"], edge["to"]
            style = self.ctx.edge(edge)
            nested = src == dst or src in ancestors(dst) or dst in ancestors(src)
            # Fixed ports and waypoints only suit right-angle connectors; other edge styles
            # (straight UML lines, entity-relation stubs) pick their own attachment points.
            router = S.style_get(style, "edgeStyle")
            sides = None if nested or router != "orthogonalEdgeStyle" else _sides(snapped[src], snapped[dst], horizontal)
            if sides:
                (ex, ey), (nx, ny) = _port(sides[0], fraction[i]), _port(sides[1], fraction[i])
                style = S.merge_style(style, f"exitX={ex:g};exitY={ey:g};exitDx=0;exitDy=0;"
                                             f"entryX={nx:g};entryY={ny:g};entryDx=0;entryDy=0;")
            owner = lay.edge_parent[i]
            rx, ry = (lay.abs[owner][0], lay.abs[owner][1]) if owner is not None else (0, 0)
            px, py = origin(owner)
            route = [] if router == "entityRelationEdgeStyle" else lay.routes.get(i, [])
            points = [(r10(x + rx) - px, r10(y + ry) - py) for x, y in route]
            eid = ids.make(f"e_{i + 1}")
            add_edge(root, eid, html_label(edge["label"]), style, cell_id[owner] if owner is not None else layer,
                     cell_id[src], cell_id[dst], points)
            if edge["startLabel"]:
                add_edge_label(root, ids.make(eid + "_start"), html_label(edge["startLabel"]), eid, -0.8)
            if edge["endLabel"]:
                add_edge_label(root, ids.make(eid + "_end"), html_label(edge["endLabel"]), eid, 0.8)


# ------------------------------------------------------------- sequence pages

LIFELINE = ("shape=umlLifeline;perimeter=lifelinePerimeter;whiteSpace=wrap;html=1;container=1;dropTarget=0;"
            "collapsible=0;recursiveResize=0;outlineConnect=0;portConstraint=eastwest;size=40;")
MESSAGE = "html=1;verticalAlign=bottom;edgeStyle=none;rounded=0;labelBackgroundColor=none;endSize=6;startSize=6;"
MESSAGE_KIND = {
    "sync": "endArrow=block;endFill=1;",
    "async": "endArrow=open;",
    "reply": "endArrow=open;dashed=1;",
    "lost": "endArrow=cross;",
}
FRAME = "shape=umlFrame;whiteSpace=wrap;html=1;pointerEvents=0;width=50;height=22;fillColor=#f5f5f5;strokeColor=#666666;fontColor=#333333;"
HEAD_H = 40


class SequenceBuilder:
    def __init__(self, page, ctx):
        self.page, self.ctx = page, ctx
        parts = list(page["participants"].values())
        self.index = {p["id"]: i for i, p in enumerate(parts)}
        self.widths = [up(max(100, len(p["label"]) * CHAR_W + 30)) for p in parts]
        gaps = [max(160, (self.widths[i] + self.widths[i + 1]) / 2 + 40) for i in range(len(parts) - 1)]

        self.messages, self.notes, self.frames = [], [], []
        counter = [0]

        def walk(items, depth):
            """Assign y positions; return the (lo, hi) x-extent in participant-index space."""
            lo, hi = None, None

            def extend(a, b):
                nonlocal lo, hi
                lo = a if lo is None else min(lo, a)
                hi = b if hi is None else max(hi, b)

            for item in items:
                if item["kind"] == "message":
                    a, b = self.index[item["from"]], self.index[item["to"]]
                    label = item["label"]
                    if page["autonumber"]:
                        counter[0] += 1
                        label = f"{counter[0]}. {label}"
                    lines = wrap_lines(label, 60)
                    self.y += (len(lines) - 1) * 16
                    need = max(len(line) for line in lines) * 6.5 + 40
                    if a == b:
                        if a < len(gaps):
                            gaps[a] = max(gaps[a], need + 60)
                        self.messages.append((item, label, self.y))
                        self.y += 50
                        extend(a, a + 0.4)
                    else:
                        i, j = min(a, b), max(a, b)
                        short = need - sum(gaps[i:j])
                        if short > 0:
                            for k in range(i, j):
                                gaps[k] += short / (j - i)
                        self.messages.append((item, label, self.y))
                        self.y += 40
                        extend(i, j)
                elif item["kind"] == "note":
                    tw, th = text_size(item["text"], 30)
                    h = up(th + 14, 10)
                    idx = sorted(self.index[p] for p in item["over"])
                    self.notes.append((item, self.y - 15, max(100, up(tw + 24)), h))
                    self.y += h + 20
                    extend(idx[0], idx[-1])
                else:
                    frame = {"item": item, "top": self.y - 20, "depth": depth, "dividers": []}
                    self.frames.append(frame)
                    self.y += 30
                    span = (None, None)
                    for k, section in enumerate(item["sections"]):
                        if k:
                            frame["dividers"].append((self.y - 15, section["label"]))
                            self.y += 30
                        a, b = walk(section["items"], depth + 1)
                        if a is not None:
                            span = (a if span[0] is None else min(span[0], a), b if span[1] is None else max(span[1], b))
                    frame["bottom"] = self.y - 15
                    self.y += 15
                    if span[0] is None:
                        span = (0, len(parts) - 1)
                    frame["span"] = span
                    extend(*span)
            return lo, hi

        self.y = HEAD_H + 50
        walk(page["items"], 0)
        self.height = up(self.y + 10)
        self.centers = [self.widths[0] / 2 + 20]
        for gap in gaps:
            self.centers.append(self.centers[-1] + up(gap, 10))
        depth_max = max((f["depth"] for f in self.frames), default=0)
        self.inset = lambda depth: 20 + 10 * (depth_max - depth)
        right = self.centers[-1] + self.widths[-1] / 2 + 20
        for frame in self.frames:
            right = max(right, self._x(frame["span"][1]) + 70 + self.inset(frame["depth"]))
        for item, _, _ in self.messages:
            if item["from"] == item["to"]:
                right = max(right, self.centers[self.index[item["from"]]] + 160)
        self.size = (right, self.height)

    def _x(self, pos):
        """x of a (possibly fractional) participant index."""
        base = int(math.floor(pos))
        return self.centers[base] + (pos - base) * 150

    def emit(self, root, layer, ox, oy, ids):
        ctx, page = self.ctx, self.page
        line_look = ctx.look("edge", {"strokeColor", "strokeWidth", "fontColor", "fontFamily", "fontSize"})
        for frame in self.frames:
            lo, hi = frame["span"]
            x0 = self._x(lo) - 60 - self.inset(frame["depth"])
            x1 = self._x(hi) + 60 + self.inset(frame["depth"])
            x0 = max(x0, 0)
            item = frame["item"]
            fid = ids.make("frame")
            add_vertex(root, fid, html_label(item["block"]), S.merge_style(FRAME, ctx.look("frame", S.APPEARANCE_KEYS)),
                       layer, r10(x0) + ox, frame["top"] + oy, r10(x1 - x0), frame["bottom"] - frame["top"])
            label = item["sections"][0]["label"]
            text = "text;html=1;align=left;verticalAlign=middle;fontStyle=2;fontColor=#333333;"
            if label:
                add_vertex(root, ids.make("frame_label"), html_label(f"[{label}]"), text, layer,
                           r10(x0) + 58 + ox, frame["top"] + 1 + oy, len(label) * CHAR_W + 20, 20, connectable=False)
            for y, label in frame["dividers"]:
                add_edge(root, ids.make("frame_else"), "", "endArrow=none;dashed=1;html=1;strokeColor=#666666;", layer,
                         ends=[(r10(x0) + ox, y + oy), (r10(x0) + r10(x1 - x0) + ox, y + oy)])
                if label:
                    add_vertex(root, ids.make("frame_label"), html_label(f"[{label}]"), text, layer,
                               r10(x0) + 8 + ox, y + 1 + oy, len(label) * CHAR_W + 20, 20, connectable=False)

        cell_id = {}
        for pid, part in page["participants"].items():
            i = self.index[pid]
            style = ctx.kind("lifeline") if ctx.template and "lifeline" in ctx.template.kinds else LIFELINE + S.DEFAULT_NODE_COLORS
            style = S.merge_style(style, f"size={HEAD_H};")
            if part["actor"]:  # people are told apart from systems by colour; the head stays a labelled box
                style = S.merge_style(style, S.palette_style("green"))
            style = ctx._tokens(style, part["style"], False, "lifeline", True)
            cell_id[pid] = ids.make("p_" + pid)
            w = self.widths[i]
            add_vertex(root, cell_id[pid], html_label(part["label"]), style, layer,
                       r10(self.centers[i] - w / 2) + ox, oy, w, self.height)

        for n, (item, label, y) in enumerate(self.messages, 1):
            src, dst = item["from"], item["to"]
            style = S.merge_style(MESSAGE + MESSAGE_KIND[item["msg"]], line_look)
            f0 = y / self.height
            if src == dst:
                f1 = (y + 20) / self.height
                cx = r10(self.centers[self.index[src]]) + ox
                style = S.merge_style(style, "align=left;verticalAlign=middle;spacingLeft=4;"
                                             f"exitX=0.5;exitY={f0:.5f};exitDx=0;exitDy=0;exitPerimeter=0;"
                                             f"entryX=0.5;entryY={f1:.5f};entryDx=0;entryDy=0;entryPerimeter=0;")
                points = [(cx + 40, y + oy), (cx + 40, y + 20 + oy)]
            else:
                style = S.merge_style(style, f"exitX=0.5;exitY={f0:.5f};exitDx=0;exitDy=0;exitPerimeter=0;"
                                             f"entryX=0.5;entryY={f0:.5f};entryDx=0;entryDy=0;entryPerimeter=0;")
                points = []
            add_edge(root, ids.make(f"m_{n}"), html_label(label), style, layer, cell_id[src], cell_id[dst], points)

        note_style = S.merge_style(S.SHAPES["note"] + S.SHAPE_DEFAULT_COLORS["note"], ctx.look("note", S.APPEARANCE_KEYS))
        for item, y, w, h in self.notes:
            xs = sorted(self.centers[self.index[p]] for p in item["over"])
            if item["side"] == "right":
                x = xs[-1] + 20
            elif item["side"] == "left":
                x = xs[0] - 20 - w
            elif len(xs) > 1:
                x, w = xs[0] - 30, max(w, xs[-1] - xs[0] + 60)
            else:
                x = xs[0] - w / 2
            add_vertex(root, ids.make("note"), html_label(item["text"]), note_style, layer, r10(x) + ox, y + oy, w, h)


# ------------------------------------------------------------------ documents

def build_document(pages, template=None, mode="auto", values=None, at=None, warnings=None):
    """pages: normalised page specs. Returns the <mxfile> element."""
    warnings = warnings if warnings is not None else []
    if template is not None:
        mxfile = ET.Element("mxfile", dict(template.mxfile.attrib))
    else:
        mxfile = ET.Element("mxfile", {"host": "drawio-skill"})
    for number, page in enumerate(pages, 1):
        ctx = StyleContext(template, page["styles"], warnings)
        builder = (SequenceBuilder if page["type"] == "sequence" else GraphBuilder)(page, ctx)
        width, height = builder.size
        if template is not None:
            diagram = template.fresh_page()
            fill = {"title": page["title"], "date": datetime.date.today().isoformat()}
            fill.update({k.lower(): v for k, v in page["meta"].items()})
            fill.update({k.lower(): v for k, v in (values or {}).items()})
            prep = prepare_page(diagram, mode, fill, warnings)
            root, layer, ids = prep["root"], prep["layer"], IdGen(prep["ids"])
            ox, oy = prep["origin"]
            if prep["region"]:
                rw, rh = prep["region"]
                if width > rw or height > rh:
                    warnings.append(f"page {number}: the diagram ({width:.0f}x{height:.0f}) is larger than the template's "
                                    f"{{{{diagram}}}} area ({rw:.0f}x{rh:.0f}); it overflows to the right/bottom")
                ox, oy = ox + max(0, (rw - width) / 2), oy + max(0, (rh - height) / 2)
            if at:
                ox, oy = at
            if page["title"] or len(pages) > 1:
                diagram.set("name", page["title"] or f"Page-{number}")
        else:
            diagram = ET.Element("diagram", {"name": page["title"] or f"Page-{number}"})
            attrs = dict(MODEL_ATTRS)
            if width > height * 1.2:
                attrs["pageWidth"], attrs["pageHeight"] = "1169", "827"
            model = ET.SubElement(diagram, "mxGraphModel", attrs)
            root = ET.SubElement(model, "root")
            ET.SubElement(root, "mxCell", {"id": "0"})
            ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
            layer, ids = "1", IdGen()
            ox, oy = at or (40, 40)
        diagram.set("id", f"page-{number}")
        builder.emit(root, layer, r10(ox), r10(oy), ids)
        mxfile.append(diagram)
    return mxfile


def write_mxfile(mxfile, path):
    ET.indent(mxfile, space="  ")
    data = ET.tostring(mxfile, encoding="unicode")
    if path == "-":
        print(data)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data + "\n")
