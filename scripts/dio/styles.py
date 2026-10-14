"""draw.io style strings: parsing, merging and the built-in shape/colour vocabulary."""

import re


def parse_style(style):
    """'ellipse;fillColor=#fff;' -> [('ellipse', None), ('fillColor', '#fff')]"""
    out = []
    for part in (style or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
            out.append((key.strip(), value.strip()))
        else:
            out.append((part, None))
    return out


def format_style(pairs):
    return "".join(k + ";" if v is None else f"{k}={v};" for k, v in pairs)


def merge_style(base, *overrides):
    """Overlay style fragments on a base style; later keys win, order is kept."""
    pairs = parse_style(base)
    for override in overrides:
        for key, value in parse_style(override):
            for i, (k, v) in enumerate(pairs):
                if k == key and (v is None) == (value is None):
                    pairs[i] = (key, value)
                    break
            else:
                if value is None:
                    pairs.insert(0, (key, None))
                else:
                    pairs.append((key, value))
    return format_style(pairs)


def style_get(style, key, default=None):
    for k, v in parse_style(style):
        if k == key and v is not None:
            return v
    return default


def style_has_token(style, token):
    return any(k == token and v is None for k, v in parse_style(style))


def pick_keys(style, keys):
    return format_style([(k, v) for k, v in parse_style(style) if v is not None and k in keys])


# Keys that carry the "look" of a cell without changing what shape it is.
APPEARANCE_KEYS = {
    "fillColor", "strokeColor", "fontColor", "fontFamily", "fontSize", "fontStyle",
    "strokeWidth", "shadow", "sketch", "glass", "gradientColor", "gradientDirection",
    "opacity", "fontSource", "swimlaneFillColor",
}
EDGE_APPEARANCE_KEYS = {
    "strokeColor", "strokeWidth", "fontColor", "fontFamily", "fontSize", "fontStyle",
    "sketch", "shadow", "fontSource", "labelBackgroundColor",
}

SHAPES = {
    "rect": "rounded=0;whiteSpace=wrap;html=1;",
    "rounded": "rounded=1;whiteSpace=wrap;html=1;",
    "terminator": "rounded=1;whiteSpace=wrap;html=1;arcSize=50;",
    "diamond": "rhombus;whiteSpace=wrap;html=1;",
    "ellipse": "ellipse;whiteSpace=wrap;html=1;",
    "circle": "ellipse;whiteSpace=wrap;html=1;aspect=fixed;",
    "cylinder": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;",
    "hexagon": "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;fixedSize=1;",
    "parallelogram": "shape=parallelogram;perimeter=parallelogramPerimeter;whiteSpace=wrap;html=1;fixedSize=1;",
    "trapezoid": "shape=trapezoid;perimeter=trapezoidPerimeter;whiteSpace=wrap;html=1;fixedSize=1;",
    "document": "shape=document;whiteSpace=wrap;html=1;boundedLbl=1;",
    "subroutine": "shape=process;whiteSpace=wrap;html=1;backgroundOutline=1;",
    "cloud": "ellipse;shape=cloud;whiteSpace=wrap;html=1;",
    "actor": "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;outlineConnect=0;",
    "note": "shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;size=14;",
    "text": "text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;",
    "initial": "ellipse;html=1;aspect=fixed;",
    "final": "ellipse;html=1;shape=endState;aspect=fixed;",
    "table": "swimlane;fontStyle=1;align=center;verticalAlign=middle;childLayout=stackLayout;horizontal=1;"
             "startSize=26;horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;"
             "collapsible=0;marginBottom=0;whiteSpace=wrap;html=1;",
}

SHAPE_ALIASES = {
    "rectangle": "rect", "box": "rect", "process": "rect", "square": "rect",
    "round": "rounded", "rounded-rect": "rounded",
    "stadium": "terminator", "pill": "terminator", "start": "terminator", "end": "terminator",
    "decision": "diamond", "rhombus": "diamond", "choice": "diamond",
    "oval": "ellipse",
    "database": "cylinder", "db": "cylinder", "datastore": "cylinder", "storage": "cylinder",
    "io": "parallelogram", "input": "parallelogram", "output": "parallelogram",
    "subprocess": "subroutine", "predefined": "subroutine",
    "person": "actor", "user": "actor",
    "comment": "note",
    "label": "text",
    "class": "table", "entity": "table",
}

# name -> (fillColor, strokeColor); the standard draw.io pastel palette.
PALETTE = {
    "blue": ("#dae8fc", "#6c8ebf"),
    "green": ("#d5e8d4", "#82b366"),
    "orange": ("#ffe6cc", "#d79b00"),
    "yellow": ("#fff2cc", "#d6b656"),
    "red": ("#f8cecc", "#b85450"),
    "purple": ("#e1d5e7", "#9673a6"),
    "gray": ("#f5f5f5", "#666666"),
    "white": ("#ffffff", "#000000"),
}
PALETTE_ALIASES = {
    "primary": "blue", "info": "blue", "success": "green", "warning": "yellow",
    "danger": "red", "error": "red", "neutral": "gray", "grey": "gray", "accent": "purple",
}

DEFAULT_NODE_COLORS = "fillColor=#dae8fc;strokeColor=#6c8ebf;"
SHAPE_DEFAULT_COLORS = {
    "note": "fillColor=#fff2cc;strokeColor=#d6b656;",
    "text": "",
    "actor": "",
    "initial": "fillColor=#000000;strokeColor=#000000;",
    "final": "fillColor=#000000;strokeColor=#000000;",
    "table": "fillColor=#dae8fc;strokeColor=#6c8ebf;swimlaneFillColor=#ffffff;",
}

# Titled container, as the upstream XML reference prescribes for groups that can also be edge endpoints.
GROUP_STYLE = (
    "swimlane;startSize=28;whiteSpace=wrap;html=1;collapsible=0;rounded=1;arcSize=8;"
    "fillColor=#f5f5f5;strokeColor=#999999;fontColor=#333333;"
)
TABLE_ROW_STYLE = (
    "text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;spacingLeft=6;spacingRight=6;"
    "overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];portConstraint=eastwest;whiteSpace=wrap;html=1;"
)
TABLE_DIVIDER_STYLE = (
    "line;strokeWidth=1;fillColor=none;align=left;verticalAlign=middle;spacingTop=-1;spacingLeft=3;"
    "spacingRight=3;rotatable=0;labelPosition=right;points=[];portConstraint=eastwest;strokeColor=inherit;"
)

EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;labelBackgroundColor=default;"

EDGE_PRESETS = {
    "dashed": "dashed=1;",
    "dotted": "dashed=1;dashPattern=1 4;",
    "thick": "strokeWidth=3;",
    "curved": "edgeStyle=none;curved=1;",
    "straight": "edgeStyle=none;rounded=0;",
}

# `arrow` shorthand on an edge -> style fragment.
ARROWS = {
    "normal": "endArrow=classic;",
    "none": "endArrow=none;",
    "both": "startArrow=classic;endArrow=classic;",
    "open": "endArrow=open;",
    "circle": "endArrow=oval;endFill=1;",
    "cross": "endArrow=cross;",
    "inherit": "endArrow=block;endFill=0;endSize=12;",
    "realize": "endArrow=block;endFill=0;endSize=12;dashed=1;",
    "depend": "endArrow=open;dashed=1;",
    "compose": "startArrow=diamondThin;startFill=1;startSize=14;endArrow=none;",
    "aggregate": "startArrow=diamondThin;startFill=0;startSize=14;endArrow=none;",
}


def palette_style(name, edge=False):
    name = PALETTE_ALIASES.get(name, name)
    if name not in PALETTE:
        return None
    fill, stroke = PALETTE[name]
    if edge:
        return f"strokeColor={stroke};"
    extra = "fontColor=#333333;" if name == "gray" else ""
    return f"fillColor={fill};strokeColor={stroke};{extra}"


_HEX3 = re.compile(r"^#([0-9a-fA-F])([0-9a-fA-F])([0-9a-fA-F])$")


def css_color(value):
    """Normalise a CSS colour for draw.io (#abc -> #aabbcc)."""
    value = value.strip()
    m = _HEX3.match(value)
    if m:
        return "#" + "".join(c * 2 for c in m.groups())
    return value
