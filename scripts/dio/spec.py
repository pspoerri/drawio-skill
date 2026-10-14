"""Validation and normalisation of the JSON diagram spec (see references/spec.md)."""

import re

from .styles import SHAPES, SHAPE_ALIASES

RESERVED_DATA_KEYS = {"id", "label", "tags", "placeholders", "link", "tooltip"}

DIRECTIONS = {"TB": "TB", "TD": "TB", "BT": "BT", "LR": "LR", "RL": "RL"}
MESSAGE_KINDS = {"sync", "async", "reply", "lost"}


class SpecError(ValueError):
    pass


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _str(value, what):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise SpecError(f"{what} must be a string, got {value!r}")
    return str(value)


def normalize(spec, warnings):
    """Return a list of normalised page specs. `warnings` collects non-fatal notes."""
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    if "pages" in spec:
        pages = spec["pages"]
        if not isinstance(pages, list) or not pages:
            raise SpecError("'pages' must be a non-empty list of page specs")
        inherited = {k: v for k, v in spec.items() if k in ("styles", "meta", "direction")}
        return [_normalize_page({**inherited, **p}, warnings) for p in pages]
    return [_normalize_page(spec, warnings)]


def _normalize_page(spec, warnings):
    kind = spec.get("type", "graph")
    if kind in ("graph", "flowchart", "er", "class", "state"):
        page = _normalize_graph(spec, warnings)
    elif kind == "sequence":
        page = _normalize_sequence(spec, warnings)
    else:
        raise SpecError(f"unknown diagram type {kind!r} (use 'graph' or 'sequence')")
    page["title"] = str(spec.get("title") or "")
    page["meta"] = {str(k): str(v) for k, v in (spec.get("meta") or {}).items()}
    styles = spec.get("styles") or {}
    if not isinstance(styles, dict):
        raise SpecError("'styles' must map a style name to a draw.io style string")
    page["styles"] = {str(k).lower(): str(v) for k, v in styles.items()}
    return page


def _normalize_graph(spec, warnings):
    direction = DIRECTIONS.get(str(spec.get("direction", "TB")).upper())
    if not direction:
        raise SpecError(f"unknown direction {spec.get('direction')!r} (use TB, BT, LR or RL)")

    groups, order = {}, []
    members = {}
    for raw in _as_list(spec.get("groups")):
        if not isinstance(raw, dict) or "id" not in raw:
            raise SpecError(f"each group needs an 'id': {raw!r}")
        gid = _str(raw["id"], "group id")
        if gid in groups:
            raise SpecError(f"duplicate group id {gid!r}")
        groups[gid] = {
            "id": gid,
            "label": str(raw.get("label", gid)),
            "parent": None if raw.get("parent") is None else _str(raw["parent"], "group parent"),
            "style": [str(s) for s in _as_list(raw.get("style"))],
        }
        for member in _as_list(raw.get("nodes")):
            members[_str(member, "group member")] = gid
        order.append(gid)
    for gid, group in groups.items():
        if group["parent"] is not None and group["parent"] not in groups:
            raise SpecError(f"group {gid!r} has unknown parent {group['parent']!r}")
        seen, cur = {gid}, group["parent"]
        while cur is not None:
            if cur in seen:
                raise SpecError(f"group {gid!r} is nested inside itself")
            seen.add(cur)
            cur = groups[cur]["parent"]

    nodes = {}
    raw_nodes = spec.get("nodes") or []
    if isinstance(raw_nodes, dict):
        raw_nodes = [{"id": k, **(v if isinstance(v, dict) else {"label": v})} for k, v in raw_nodes.items()]
    for raw in raw_nodes:
        if isinstance(raw, str):
            raw = {"id": raw}
        if not isinstance(raw, dict) or "id" not in raw:
            raise SpecError(f"each node needs an 'id': {raw!r}")
        nid = _str(raw["id"], "node id")
        if nid in nodes or nid in groups:
            raise SpecError(f"duplicate id {nid!r} (node and group ids share one namespace)")
        nodes[nid] = _node(nid, raw, groups, members)

    edges = []
    for i, raw in enumerate(_as_list(spec.get("edges"))):
        if isinstance(raw, (list, tuple)) and len(raw) in (2, 3):
            raw = {"from": raw[0], "to": raw[1], "label": raw[2] if len(raw) == 3 else ""}
        if not isinstance(raw, dict):
            raise SpecError(f"edge #{i + 1} must be an object or [from, to, label]: {raw!r}")
        src = raw.get("from", raw.get("source"))
        dst = raw.get("to", raw.get("target"))
        if src is None or dst is None:
            raise SpecError(f"edge #{i + 1} needs 'from' and 'to': {raw!r}")
        src, dst = _str(src, "edge 'from'"), _str(dst, "edge 'to'")
        for end in (src, dst):
            if end not in nodes and end not in groups:
                warnings.append(f"edge #{i + 1} references undeclared node {end!r}; created it as a plain box")
                nodes[end] = _node(end, {"id": end}, groups, members)
        edges.append({
            "from": src, "to": dst,
            "label": str(raw.get("label") or ""),
            "startLabel": str(raw.get("startLabel") or ""),
            "endLabel": str(raw.get("endLabel") or ""),
            "arrow": None if raw.get("arrow") is None else str(raw["arrow"]).lower(),
            "style": [str(s) for s in _as_list(raw.get("style"))],
        })

    if not nodes and not groups:
        raise SpecError("the spec has no nodes")
    return {"type": "graph", "direction": direction, "nodes": nodes, "edges": edges, "groups": groups}


def _node(nid, raw, groups, members):
    shape_raw = raw.get("shape")
    shape = str(shape_raw).lower() if shape_raw else "rect"
    shape = SHAPE_ALIASES.get(shape, shape)
    rows = raw.get("rows")
    if rows is not None and not shape_raw:
        shape = "table"
    if shape not in SHAPES:
        raise SpecError(
            f"node {nid!r}: unknown shape {shape_raw!r}. Valid shapes: {', '.join(sorted(SHAPES))} "
            f"(aliases: {', '.join(sorted(SHAPE_ALIASES))}). Put raw draw.io style strings in 'style' instead."
        )
    group = raw.get("group", members.get(nid))
    if group is not None:
        group = _str(group, "node group")
        if group not in groups:
            raise SpecError(f"node {nid!r} is in unknown group {group!r}")
    node = {
        "id": nid,
        "label": str(raw.get("label", nid)),
        "shape": shape,
        "shape_explicit": bool(shape_raw) or rows is not None,
        "style": [str(s) for s in _as_list(raw.get("style"))],
        "group": group,
        "rows": [str(r) for r in _as_list(rows)],
        "width": raw.get("width"),
        "height": raw.get("height"),
        "link": raw.get("link"),
        "tooltip": raw.get("tooltip"),
        "tags": [str(t) for t in (raw["tags"].split() if isinstance(raw.get("tags"), str) else _as_list(raw.get("tags")))],
        "data": {},
        "html": bool(raw.get("html")),
    }
    data = raw.get("data") or {}
    if not isinstance(data, dict):
        raise SpecError(f"node {nid!r}: 'data' must be an object of metadata values")
    for key, value in data.items():
        if not re.fullmatch(r"[A-Za-z_][\w.-]*", str(key)) or str(key) in RESERVED_DATA_KEYS:
            raise SpecError(f"node {nid!r}: {key!r} cannot be used as a metadata key")
        node["data"][str(key)] = str(value)
    for dim in ("width", "height"):
        if node[dim] is not None and (isinstance(node[dim], bool) or not isinstance(node[dim], (int, float)) or node[dim] <= 0):
            raise SpecError(f"node {nid!r}: {dim} must be a positive number")
    return node


def _normalize_sequence(spec, warnings):
    participants = {}
    for raw in _as_list(spec.get("participants")):
        if isinstance(raw, str):
            raw = {"id": raw}
        if not isinstance(raw, dict) or "id" not in raw:
            raise SpecError(f"each participant needs an 'id': {raw!r}")
        pid = _str(raw["id"], "participant id")
        if pid in participants:
            raise SpecError(f"duplicate participant id {pid!r}")
        participants[pid] = {
            "id": pid,
            "label": str(raw.get("label", pid)),
            "actor": str(raw.get("shape", "")).lower() in ("actor", "person", "user"),
            "style": [str(s) for s in _as_list(raw.get("style"))],
        }

    def ensure(pid):
        pid = _str(pid, "participant reference")
        if pid not in participants:
            participants[pid] = {"id": pid, "label": pid, "actor": False, "style": []}
        return pid

    def items(raw_items, where):
        out = []
        for raw in _as_list(raw_items):
            if not isinstance(raw, dict):
                raise SpecError(f"{where}: each item must be an object, got {raw!r}")
            if "note" in raw:
                over = [ensure(p) for p in _as_list(raw.get("over") or raw.get("of"))]
                if not over:
                    raise SpecError(f"{where}: a note needs 'over' (one or two participant ids): {raw!r}")
                side = str(raw.get("side", "over")).lower()
                if side not in ("over", "left", "right"):
                    raise SpecError(f"{where}: note side must be over, left or right")
                out.append({"kind": "note", "text": str(raw["note"]), "over": over[:2], "side": side})
            elif "block" in raw:
                sections = [{"label": str(raw.get("label") or ""), "items": items(raw.get("items"), where)}]
                for alt in _as_list(raw.get("else")):
                    if not isinstance(alt, dict):
                        raise SpecError(f"{where}: 'else' entries must be objects with 'label' and 'items'")
                    sections.append({"label": str(alt.get("label") or ""), "items": items(alt.get("items"), where)})
                out.append({"kind": "block", "block": str(raw["block"]), "sections": sections})
            elif "from" in raw and "to" in raw:
                kind = str(raw.get("kind", "sync")).lower()
                if kind not in MESSAGE_KINDS:
                    raise SpecError(f"{where}: message kind must be one of {sorted(MESSAGE_KINDS)}, got {kind!r}")
                out.append({"kind": "message", "from": ensure(raw["from"]), "to": ensure(raw["to"]),
                            "label": str(raw.get("label") or ""), "msg": kind})
            else:
                raise SpecError(f"{where}: item must be a message (from/to), a note or a block: {raw!r}")
        return out

    body = items(spec.get("messages", spec.get("items")), "messages")
    if not participants:
        raise SpecError("a sequence diagram needs participants or messages")
    return {"type": "sequence", "participants": participants, "items": body,
            "autonumber": bool(spec.get("autonumber"))}
