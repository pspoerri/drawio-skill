"""Mermaid -> diagram spec. Covers flowchart/graph, sequenceDiagram, classDiagram, erDiagram, stateDiagram.

Anything else raises UnsupportedMermaid; the caller is expected to translate
such diagrams into a spec by hand (see references/spec.md).
"""

import html
import re

from .styles import css_color


class UnsupportedMermaid(ValueError):
    pass


FENCE = re.compile(r"```+\s*mermaid[^\n]*\n(.*?)```", re.S | re.I)


def extract_blocks(text):
    """Mermaid sources found in `text`: fenced ```mermaid blocks, or the text itself."""
    blocks = [m.group(1) for m in FENCE.finditer(text)]
    return blocks or [text]


def _clean_lines(source):
    source = re.sub(r"\A\s*---\n.*?\n---\s*\n", "", source, flags=re.S)  # front matter
    source = re.sub(r"%%\{.*?\}%%", "", source, flags=re.S)             # init directives
    lines = []
    for line in source.splitlines():
        line = re.sub(r"(^|\s)%%.*$", "", line).strip()
        if line:
            lines.append(line)
    return lines


def clean_label(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    if len(text) >= 2 and text[0] == text[-1] == "`":
        text = text[1:-1]
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"\\n", "\n", text)
    text = re.sub(r"</?(b|i|u|em|strong|span|small|sub|sup|code)(\s[^>]*)?>", "", text, flags=re.I)
    text = re.sub(r"\bfa[bsrl]?:fa-[\w-]+\s*", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"#(\w+);", lambda m: html.unescape(f"&{'#' if m.group(1).isdigit() else ''}{m.group(1)};"), text)
    return "\n".join(part.strip() for part in html.unescape(text).split("\n")).strip()


def css_to_style(css):
    """'fill:#f9f,stroke:#333,stroke-width:2px' -> draw.io style fragment."""
    out = []
    for part in re.split(r"[,;]", css):
        if ":" not in part:
            continue
        key, value = (s.strip() for s in part.split(":", 1))
        if key == "fill":
            out.append(f"fillColor={css_color(value)}")
        elif key == "stroke":
            out.append(f"strokeColor={css_color(value)}")
        elif key == "color":
            out.append(f"fontColor={css_color(value)}")
        elif key == "stroke-width":
            width = re.match(r"[\d.]+", value)
            if width:
                out.append(f"strokeWidth={width.group(0)}")
        elif key == "stroke-dasharray":
            out.append("dashed=1")
        elif key == "font-weight" and value in ("bold", "700"):
            out.append("fontStyle=1")
    return ";".join(out) + ";" if out else ""


def parse(source):
    """Parse one Mermaid diagram into a spec dict."""
    lines = _clean_lines(source)
    if not lines:
        raise UnsupportedMermaid("empty Mermaid source")
    title = None
    if lines[0].lower().startswith("title:"):
        title = lines.pop(0).split(":", 1)[1].strip()
    head = lines[0]
    word = head.split()[0]
    lower = word.lower()
    if lower in ("graph", "flowchart", "flowchart-elk"):
        spec = _flowchart(lines)
    elif lower == "sequencediagram":
        spec = _sequence(lines[1:])
    elif lower in ("classdiagram", "classdiagram-v2"):
        spec = _class(lines[1:])
    elif lower == "erdiagram":
        spec = _er(lines[1:])
    elif lower in ("statediagram", "statediagram-v2"):
        spec = _state(lines[1:])
    else:
        raise UnsupportedMermaid(
            f"Mermaid diagram type {word!r} has no automatic converter (supported: flowchart/graph, sequenceDiagram, "
            f"classDiagram, erDiagram, stateDiagram). Translate it into a JSON spec by hand, or convert it with the "
            f"draw.io desktop CLI (--engine drawio), which understands every Mermaid type.")
    if title and not spec.get("title"):
        spec["title"] = title
    return spec


# ------------------------------------------------------------------ flowchart

_ID = re.compile(r"[\w]+(?:[-.](?=\w)[\w]+)*")
_SHAPES = [  # (opener, [(closer, shape)])
    ("(((", [(")))", "circle")]),
    ("((", [("))", "circle")]),
    ("([", [("])", "terminator")]),
    ("[[", [("]]", "subroutine")]),
    ("[(", [(")]", "cylinder")]),
    ("[/", [("/]", "parallelogram"), ("\\]", "trapezoid")]),
    ("[\\", [("\\]", "parallelogram"), ("/]", "trapezoid")]),
    ("{{", [("}}", "hexagon")]),
    ("(", [(")", "rounded")]),
    ("[", [("]", "rect")]),
    ("{", [("}", "diamond")]),
    (">", [("]", "rect")]),
]
_AT_SHAPES = {
    "rect": "rect", "rounded": "rounded", "stadium": "terminator", "pill": "terminator", "terminal": "terminator",
    "diam": "diamond", "diamond": "diamond", "decision": "diamond", "question": "diamond", "circle": "circle",
    "circ": "circle", "cyl": "cylinder", "cylinder": "cylinder", "db": "cylinder", "database": "cylinder",
    "hex": "hexagon", "hexagon": "hexagon", "doc": "document", "document": "document", "subproc": "subroutine",
    "subprocess": "subroutine", "lean-r": "parallelogram", "lean-l": "parallelogram", "in-out": "parallelogram",
    "trap-b": "trapezoid", "trap-t": "trapezoid", "cloud": "cloud", "text": "text", "note": "note",
    "event": "rounded", "process": "rect", "proc": "rect", "start": "circle", "stop": "circle",
}
_LINK = re.compile(r"(?P<start>[<ox])?(?P<body>-\.+-|-{2,}|={2,}|~{3,}|-\.+)(?P<end>[>ox])?")
_CLOSERS = {"-": re.compile(r"-{2,}([>ox])?"), "=": re.compile(r"={2,}([>ox])?"), ".": re.compile(r"\.+-([>ox])?")}


class _Flow:
    def __init__(self):
        self.nodes, self.order = {}, []
        self.edges, self.groups = [], {}
        self.stack = []
        self.classdefs, self.node_classes, self.node_css = {}, {}, {}
        self.direction = "TB"

    def node(self, nid, label=None, shape=None):
        node = self.nodes.get(nid)
        if node is None:
            node = self.nodes[nid] = {"id": nid, "label": None, "shape": None, "group": None}
            self.order.append(nid)
        if label is not None and node["label"] is None:
            node["label"] = label
        if shape is not None and node["shape"] is None:
            node["shape"] = shape
        if self.stack and node["group"] is None:
            node["group"] = self.stack[-1]
        return node


def _statements(lines):
    for line in lines:
        buf, quote, depth = "", False, 0
        for ch in line:
            if ch == '"':
                quote = not quote
            elif not quote and ch in "[({":
                depth += 1
            elif not quote and ch in "])}":
                depth = max(0, depth - 1)
            if ch == ";" and not quote and not depth:
                if buf.strip():
                    yield buf.strip()
                buf = ""
            else:
                buf += ch
        if buf.strip():
            yield buf.strip()


def _flowchart(lines):
    flow = _Flow()
    head = lines[0].split()
    if len(head) > 1:
        flow.direction = {"TD": "TB"}.get(head[1].upper(), head[1].upper())
        if flow.direction not in ("TB", "BT", "LR", "RL"):
            flow.direction = "TB"
    for stmt in _statements(lines[1:]):
        first = stmt.split(None, 1)
        keyword, rest = first[0], (first[1] if len(first) > 1 else "")
        if keyword == "subgraph":
            m = re.match(r'^([\w.-]+)\s*\[(.*)\]\s*$', rest)
            if m:
                gid, label = m.group(1), clean_label(m.group(2))
            else:
                label = clean_label(rest) or f"group{len(flow.groups) + 1}"
                gid = rest.strip() if re.fullmatch(r"[\w.-]+", rest.strip()) else f"subgraph_{len(flow.groups) + 1}"
            while gid in flow.groups:
                gid += "_"
            flow.groups[gid] = {"id": gid, "label": label, "parent": flow.stack[-1] if flow.stack else None}
            flow.stack.append(gid)
        elif stmt == "end":
            if flow.stack:
                flow.stack.pop()
        elif keyword == "direction":
            if not flow.stack and rest.strip().upper() in ("TB", "TD", "BT", "LR", "RL"):
                flow.direction = {"TD": "TB"}.get(rest.strip().upper(), rest.strip().upper())
        elif keyword == "classDef":
            names, _, css = rest.partition(" ")
            for name in names.split(","):
                flow.classdefs[name.strip().lower()] = css_to_style(css)
        elif keyword == "class":
            ids, _, name = rest.rpartition(" ")
            for nid in ids.split(","):
                flow.node_classes.setdefault(nid.strip(), []).append(name.strip().lower())
        elif keyword == "style":
            nid, _, css = rest.partition(" ")
            flow.node_css[nid.strip()] = css_to_style(css)
        elif keyword in ("linkStyle", "click", "accTitle:", "accDescr:", "accTitle", "accDescr"):
            continue
        else:
            _flow_chain(flow, stmt)

    # A subgraph used as an edge endpoint is a group, not a node.
    for gid in flow.groups:
        if gid in flow.nodes:
            del flow.nodes[gid]
            flow.order.remove(gid)
    nodes = []
    for nid in flow.order:
        n = flow.nodes[nid]
        node = {"id": nid, "label": n["label"] if n["label"] is not None else nid}
        if n["shape"] and n["shape"] != "rect":
            node["shape"] = n["shape"]
        if n["group"]:
            node["group"] = n["group"]
        style = [c for c in flow.node_classes.get(nid, []) if flow.classdefs.get(c)]
        if flow.node_css.get(nid):
            style.append(flow.node_css[nid])
        if style:
            node["style"] = style
        nodes.append(node)
    groups = []
    for gid, g in flow.groups.items():
        group = dict(g)
        style = [c for c in flow.node_classes.get(gid, []) if flow.classdefs.get(c)]
        if flow.node_css.get(gid):
            style.append(flow.node_css[gid])
        if style:
            group["style"] = style
        groups.append(group)
    spec = {"type": "graph", "direction": flow.direction, "nodes": nodes, "edges": flow.edges}
    if groups:
        spec["groups"] = groups
    styles = {k: v for k, v in flow.classdefs.items() if v}
    if styles:
        spec["styles"] = styles
    return spec


def _flow_node(flow, text, pos):
    m = _ID.match(text, pos)
    if not m:
        raise UnsupportedMermaid(f"cannot parse flowchart statement near: {text[pos:pos + 40]!r} (in {text!r})")
    nid, pos = m.group(0), m.end()
    label = shape = None
    if text.startswith("@{", pos):
        end = text.find("}", pos)
        if end < 0:
            raise UnsupportedMermaid(f"unterminated '@{{' in {text!r}")
        body = text[pos + 2:end]
        sm = re.search(r"shape\s*:\s*([\w-]+)", body)
        lm = re.search(r'label\s*:\s*("([^"]*)"|[^,}]+)', body)
        if sm:
            shape = _AT_SHAPES.get(sm.group(1).lower(), "rect")
        if lm:
            label = clean_label(lm.group(1))
        pos = end + 1
    else:
        for opener, closers in _SHAPES:
            if not text.startswith(opener, pos):
                continue
            start = pos + len(opener)
            stripped = text[start:].lstrip()
            if stripped.startswith('"'):
                q0 = start + (len(text) - start - len(stripped))
                q1 = text.find('"', q0 + 1)
                if q1 < 0:
                    raise UnsupportedMermaid(f"unterminated quote in {text!r}")
                after = q1 + 1
                while after < len(text) and text[after] == " ":
                    after += 1
                match = next(((c, s) for c, s in closers if text.startswith(c, after)), None)
                if match:
                    label, shape, pos = clean_label(text[q0:q1 + 1]), match[1], after + len(match[0])
                    break
            found = [(text.find(c, start), c, s) for c, s in closers]
            found = [f for f in found if f[0] >= 0]
            if found:
                idx, closer, shape = min(found)
                label, pos = clean_label(text[start:idx]), idx + len(closer)
                break
    m = re.compile(r":::\s*([\w-]+)").match(text, pos)
    if m:
        flow.node_classes.setdefault(nid, []).append(m.group(1).lower())
        pos = m.end()
    flow.node(nid, label, shape)
    return nid, pos


def _skip(text, pos):
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _flow_group(flow, text, pos):
    ids = []
    while True:
        nid, pos = _flow_node(flow, text, _skip(text, pos))
        ids.append(nid)
        pos = _skip(text, pos)
        if pos < len(text) and text[pos] == "&":
            pos += 1
            continue
        return ids, pos


def _flow_link(text, pos):
    m = _LINK.match(text, pos)
    if not m:
        return None
    start, body, end = m.group("start"), m.group("body"), m.group("end")
    pos, label = m.end(), ""
    if end is None and body in ("--", "==", "-."):
        closer = _CLOSERS[body[-1] if body != "--" else "-"].search(text, pos)
        if not closer:
            return None
        label, end, pos = clean_label(text[pos:closer.start()]), closer.group(1), closer.end()
    pos = _skip(text, pos)
    if pos < len(text) and text[pos] == "|":
        close = text.find("|", pos + 1)
        if close > 0:
            label, pos = clean_label(text[pos + 1:close]), close + 1
    edge = {"label": label}
    style = []
    if "." in body:
        style.append("dashed")
    if "=" in body:
        style.append("thick")
    marks = {">": "classic", "<": "classic", "o": "oval", "x": "cross", None: "none"}
    if start or end != ">":
        style.append(f"startArrow={marks[start]};endArrow={marks[end]};" + ("startFill=1;" if start else ""))
    if style:
        edge["style"] = style
    edge["hidden"] = "~" in body
    return edge, pos


def _flow_chain(flow, text):
    sources, pos = _flow_group(flow, text, 0)
    while True:
        pos = _skip(text, pos)
        if pos >= len(text):
            return
        link = _flow_link(text, pos)
        if not link:
            raise UnsupportedMermaid(f"cannot parse flowchart link near: {text[pos:pos + 40]!r} (in {text!r})")
        edge, pos = link
        targets, pos = _flow_group(flow, text, pos)
        if not edge.pop("hidden"):
            for s in sources:
                for t in targets:
                    flow.edges.append({"from": s, "to": t, **{k: v for k, v in edge.items() if v}})
        sources = targets


# ------------------------------------------------------------------- sequence

_MSG = re.compile(r"^(.+?)\s*(<<-->>|<<->>|-->>|->>|--x|-x|--\)|-\)|-->|->)\s*[+-]?\s*(.+?)\s*:\s*(.*)$")
_MSG_KIND = {"->>": "sync", "-->>": "reply", "->": "sync", "-->": "reply", "-x": "lost", "--x": "lost",
             "-)": "async", "--)": "async", "<<->>": "sync", "<<-->>": "reply"}
_BLOCKS = ("loop", "alt", "opt", "par", "critical", "break", "rect")


def _sequence(lines):
    participants, alias = [], {}
    spec = {"type": "sequence", "participants": participants, "messages": []}

    def declare(name, label=None, actor=False):
        name = name.strip()
        if name not in alias:
            alias[name] = name
            entry = {"id": name, "label": clean_label(label) if label else name}
            if actor:
                entry["shape"] = "actor"
            participants.append(entry)
        return name

    stack = [spec["messages"]]
    opened = []  # the block dict (or None for `box`) of each open `end`-terminated construct
    for line in lines:
        word = line.split(None, 1)[0]
        low = word.lower()
        rest = line[len(word):].strip()
        if low in ("participant", "actor") or (low == "create" and rest.split(None, 1)[0] in ("participant", "actor")):
            if low == "create":
                low, rest = rest.split(None, 1)[0], rest.split(None, 1)[1] if " " in rest else ""
            m = re.match(r"^(.+?)\s+as\s+(.+)$", rest)
            declare(m.group(1) if m else rest, m.group(2) if m else None, low == "actor")
        elif low == "autonumber":
            spec["autonumber"] = True
        elif low == "title" or low == "title:":
            spec["title"] = rest.lstrip(":").strip()
        elif low in ("activate", "deactivate", "destroy", "links", "link", "properties", "details"):
            continue
        elif low == "note":
            m = re.match(r"^(right of|left of|over)\s+(.+?)\s*:\s*(.*)$", rest, re.I)
            if not m:
                continue
            where = m.group(1).lower()
            over = [declare(p) for p in m.group(2).split(",")]
            stack[-1].append({"note": clean_label(m.group(3)), "over": over,
                              "side": {"right of": "right", "left of": "left"}.get(where, "over")})
        elif low == "box":
            opened.append(None)
        elif low in _BLOCKS:
            label = "" if low == "rect" else clean_label(rest)
            block = {"block": "group" if low == "rect" else low, "label": label, "items": []}
            stack[-1].append(block)
            stack.append(block["items"])
            opened.append(block)
        elif low in ("else", "and", "option"):
            block = next((b for b in reversed(opened) if b is not None), None)
            if block is None:
                continue
            section = {"label": clean_label(rest), "items": []}
            block.setdefault("else", []).append(section)
            stack[-1] = section["items"]
        elif low == "end":
            if opened and opened.pop() is not None:
                stack.pop()
        else:
            m = _MSG.match(line)
            if not m:
                raise UnsupportedMermaid(f"cannot parse sequence diagram line: {line!r}")
            src, arrow, dst, text = m.groups()
            stack[-1].append({"from": declare(src), "to": declare(dst), "label": clean_label(text),
                              "kind": _MSG_KIND[arrow]})
    return spec


# ---------------------------------------------------------------------- class

_REL = re.compile(
    r'^([\w.~-]+?)\s*(?:"([^"]*)")?\s*'
    r'(<\||\*|(?<=[\s"])o|<)?(--|\.\.)(\|>|\*|o(?=[\s"])|>)?'
    r'\s*(?:"([^"]*)")?\s*([\w.~-]+)\s*(?::\s*(.*))?$')
_MARK = {"<|": "block", "|>": "block", "*": "diamondThin", "o": "diamondThin", "<": "open", ">": "open", None: "none"}


def _class_name(name):
    return re.sub(r"~(.+?)~", r"<\1>", name)


def _class(lines):
    classes, order, edges, groups = {}, [], [], []
    direction = "TB"
    namespace = None

    def cls(name):
        name = name.strip()
        if name not in classes:
            classes[name] = {"label": _class_name(name), "attrs": [], "methods": [], "stereo": None, "group": namespace}
            order.append(name)
        return classes[name]

    def member(name, text):
        text = text.strip()
        m = re.match(r"^<<(.+)>>$", text)
        if m:
            cls(name)["stereo"] = m.group(1)
        elif text:
            cls(name)["methods" if "(" in text else "attrs"].append(_class_name(text))

    current = None
    for line in lines:
        if current is not None:
            if line == "}":
                current = None
            else:
                member(current, line)
            continue
        low = line.lower()
        if low.startswith("direction"):
            d = line.split()[-1].upper()
            direction = {"TD": "TB"}.get(d, d) if d in ("TB", "TD", "BT", "LR", "RL") else direction
            continue
        if low.startswith("note"):
            continue
        if low.startswith("namespace"):
            namespace = line.split()[1].rstrip("{").strip()
            groups.append({"id": "ns_" + namespace, "label": namespace})
            namespace = "ns_" + namespace
            continue
        if line == "}":
            namespace = None
            continue
        m = re.match(r"^<<(.+)>>\s+([\w.~-]+)$", line)
        if m:
            cls(m.group(2))["stereo"] = m.group(1)
            continue
        m = re.match(r'^class\s+([\w.~-]+)(?:\s*\["([^"]*)"\])?\s*(?:<<(.+?)>>)?\s*(:::\w+)?\s*(\{.*)?$', line)
        if m:
            c = cls(m.group(1))
            if m.group(2):
                c["label"] = m.group(2)
            if m.group(3):
                c["stereo"] = m.group(3)
            body = m.group(5)
            if body is not None:
                inner = body[1:].strip()
                if inner.endswith("}"):
                    for part in inner[:-1].split(";"):
                        member(m.group(1), part)
                else:
                    if inner:
                        member(m.group(1), inner)
                    current = m.group(1)
            continue
        m = _REL.match(line)
        if m:
            a, a_card, left, body, right, b_card, b, label = m.groups()
            cls(a)
            cls(b)
            if right in ("|>", "*", "o") and left is None:  # put the parent/whole on top
                a, b, left, right, a_card, b_card = b, a, {"|>": "<|"}.get(right, right), None, b_card, a_card
            style = f"edgeStyle=none;rounded=0;startArrow={_MARK[left]};endArrow={_MARK[right]};"
            style += "startFill=%d;endFill=%d;startSize=14;endSize=14;" % (left == "*", right == "*")
            if body == "..":
                style += "dashed=1;"
            edge = {"from": a, "to": b, "style": style}
            if label:
                edge["label"] = clean_label(label)
            if a_card:
                edge["startLabel"] = a_card
            if b_card:
                edge["endLabel"] = b_card
            edges.append(edge)
            continue
        m = re.match(r"^([\w.~-]+)\s*:\s*(.+)$", line)
        if m:
            member(m.group(1), m.group(2))
            continue
        if low.startswith(("click", "link", "callback", "style", "classdef", "cssclass")):
            continue
        raise UnsupportedMermaid(f"cannot parse class diagram line: {line!r}")

    nodes = []
    for name in order:
        c = classes[name]
        label = (f"«{c['stereo']}»\n" if c["stereo"] else "") + c["label"]
        rows = c["attrs"] + (["---"] if c["methods"] else []) + c["methods"]
        node = {"id": name, "label": label, "shape": "table", "rows": rows}
        if c["group"]:
            node["group"] = c["group"]
        nodes.append(node)
    spec = {"type": "graph", "direction": direction, "nodes": nodes, "edges": edges}
    if groups:
        spec["groups"] = groups
    return spec


# ------------------------------------------------------------------------- er

_ER_REL = re.compile(r'^([\w-]+|"[^"]+")\s*(\|\||\|o|\}o|\}\|)(--|\.\.)(\|\||o\||o\{|\|\{)\s*([\w-]+|"[^"]+")\s*(?::\s*(.*))?$')
_ER_LEFT = {"||": "ERmandOne", "|o": "ERzeroToOne", "}o": "ERzeroToMany", "}|": "ERoneToMany"}
_ER_RIGHT = {"||": "ERmandOne", "o|": "ERzeroToOne", "o{": "ERzeroToMany", "|{": "ERoneToMany"}


def _er(lines):
    entities, order, edges = {}, [], []
    direction = "LR"  # entity-relation connectors leave and enter sideways

    def entity(name, label=None):
        name = name.strip().strip('"')
        if name not in entities:
            entities[name] = {"label": name, "rows": []}
            order.append(name)
        if label:
            entities[name]["label"] = label
        return name

    current = None
    for line in lines:
        if current is not None:
            if line == "}":
                current = None
                continue
            m = re.match(r'^(\S+)\s+(\S+)(?:\s+((?:PK|FK|UK)(?:\s*,\s*(?:PK|FK|UK))*))?(?:\s+"([^"]*)")?\s*$', line)
            if m:
                kind, name, keys, _comment = m.groups()
                entities[current]["rows"].append(f"{name} : {kind}" + (f"  [{keys}]" if keys else ""))
            else:
                entities[current]["rows"].append(line)
            continue
        if line.lower().startswith("direction"):
            d = line.split()[-1].upper()
            direction = {"TD": "TB"}.get(d, d) if d in ("TB", "TD", "BT", "LR", "RL") else direction
            continue
        m = _ER_REL.match(line)
        if m:
            a, left, body, right, b, label = m.groups()
            edge = {"from": entity(a), "to": entity(b),
                    "style": f"edgeStyle=entityRelationEdgeStyle;rounded=0;startArrow={_ER_LEFT[left]};"
                             f"endArrow={_ER_RIGHT[right]};startFill=0;endFill=0;"
                             f"startSize=12;endSize=12;" + ("dashed=1;" if body == ".." else "")}
            if label:
                edge["label"] = clean_label(label)
            edges.append(edge)
            continue
        m = re.match(r'^([\w-]+|"[^"]+")\s*(?:\[\s*"?([^"\]]*)"?\s*\])?\s*(\{)?\s*(\})?$', line)
        if m:
            name = entity(m.group(1), m.group(2))
            if m.group(3) and not m.group(4):
                current = name
            continue
        raise UnsupportedMermaid(f"cannot parse ER diagram line: {line!r}")

    nodes = []
    for name in order:
        e = entities[name]
        node = {"id": name, "label": e["label"], "shape": "table", "rows": e["rows"]}
        nodes.append(node)
    return {"type": "graph", "direction": direction, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------- state

def _state(lines):
    nodes, order, edges, groups = {}, [], [], []
    direction = "TB"
    stack = []
    markers = {}

    def scope():
        return stack[-1] if stack else None

    def state(name, label=None, shape=None):
        name = name.strip()
        if name == "[*]":
            raise ValueError("handled by endpoint()")
        if name not in nodes:
            nodes[name] = {"id": name, "label": name, "shape": "rounded", "group": scope()}
            order.append(name)
        if label:
            nodes[name]["label"] = label
        if shape:
            nodes[name]["shape"] = shape
        return name

    def endpoint(name, is_source):
        name = name.strip()
        if name != "[*]":
            return state(name)
        key = (scope(), is_source)
        if key not in markers:
            nid = f"__{'start' if is_source else 'end'}_{len(markers) + 1}"
            markers[key] = nid
            nodes[nid] = {"id": nid, "label": "", "shape": "initial" if is_source else "final", "group": scope()}
            order.append(nid)
        return markers[key]

    in_note = False
    for line in lines:
        low = line.lower()
        if in_note:
            in_note = low != "end note"
            continue
        if low.startswith("note"):
            in_note = ":" not in line
            continue
        if low.startswith("direction"):
            d = line.split()[-1].upper()
            if not stack and d in ("TB", "TD", "BT", "LR", "RL"):
                direction = {"TD": "TB"}.get(d, d)
            continue
        if line == "}":
            if stack:
                stack.pop()
            continue
        if line == "--" or low.startswith(("classdef", "class ", "hide", "scale")):
            continue
        m = re.match(r'^state\s+"([^"]*)"\s+as\s+([\w.-]+)\s*(\{)?$', line)
        if m:
            if m.group(3):
                groups.append({"id": m.group(2), "label": clean_label(m.group(1)), "parent": scope()})
                stack.append(m.group(2))
            else:
                state(m.group(2), clean_label(m.group(1)))
            continue
        m = re.match(r"^state\s+([\w.-]+)\s*(?:<<(\w+)>>)?\s*(\{)?$", line)
        if m:
            name, stereo, brace = m.groups()
            if brace:
                groups.append({"id": name, "label": name, "parent": scope()})
                stack.append(name)
            elif stereo:
                state(name, " ", "diamond" if stereo.lower() == "choice" else "rect")
                if stereo.lower() != "choice":
                    nodes[name].update(style="fillColor=#000000;strokeColor=#000000;", width=80, height=10, label="")
                else:
                    nodes[name].update(label="", width=40, height=40)
            else:
                state(name)
            continue
        m = re.match(r"^(\[\*\]|[\w.-]+)\s*-->\s*(\[\*\]|[\w.-]+)\s*(?::\s*(.*))?$", line)
        if m:
            a, b = endpoint(m.group(1), True), endpoint(m.group(2), False)
            edge = {"from": a, "to": b}
            if m.group(3):
                edge["label"] = clean_label(m.group(3))
            edges.append(edge)
            continue
        m = re.match(r"^([\w.-]+)\s*:\s*(.+)$", line)
        if m:
            state(m.group(1), clean_label(m.group(2)))
            continue
        if re.fullmatch(r"[\w.-]+", line):
            state(line)
            continue
        raise UnsupportedMermaid(f"cannot parse state diagram line: {line!r}")

    group_ids = {g["id"] for g in groups}
    out_nodes = []
    for nid in order:
        if nid in group_ids:
            continue
        node = {k: v for k, v in nodes[nid].items() if v is not None}
        if node.get("shape") == "rect":
            node.pop("shape")
        out_nodes.append(node)
    spec = {"type": "graph", "direction": direction, "nodes": out_nodes, "edges": edges}
    if groups:
        spec["groups"] = groups
    return spec
