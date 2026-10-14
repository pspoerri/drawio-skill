"""Structural checks that tell whether draw.io will open a file and show a connected diagram."""

import re
import shutil
import subprocess

from .template import DrawioFileError, load_mxfile, page_cells
from .upstream import XSD

_BARE_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);)")


def repair_text(xml):
    """Fix the mechanical slips that make draw.io reject a hand-written file (after upstream's repair-xml.js):
    text around the diagram, `<` or a bare `&` inside attribute values, a layer that is its own parent."""
    found = re.search(r"<mxfile[\s\S]*</mxfile>|<mxGraphModel[\s\S]*</mxGraphModel>", xml)
    if found:
        xml = found.group(0)
    xml = re.sub(r"<!--[\s\S]*?-->", "", xml)
    xml = re.sub(r'="([^"]*)"', lambda m: '="' + _BARE_AMP.sub("&amp;", m.group(1).replace("<", "&lt;")) + '"', xml)
    return re.sub(r'<mxCell id="([^"]+)" parent="\1"\s*/>', r'<mxCell id="\1" parent="0"/>', xml)


def schema_problems(path):
    """Messages from validating against the official mxfile.xsd; [] if xmllint or the schema is unavailable."""
    xmllint = shutil.which("xmllint")
    if not xmllint or not XSD.is_file():
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
            if "<mxGraphModel" not in text or "<mxfile" not in text:
                return []  # compressed pages, an SVG wrapper or a bare model: not what the schema describes
        proc = subprocess.run([xmllint, "--noout", "--schema", str(XSD), str(path)],
                              capture_output=True, text=True, timeout=60)
    except (OSError, UnicodeDecodeError, subprocess.TimeoutExpired):
        return []
    if proc.returncode == 0:
        return []
    lines = [re.sub(r"^.*?:(\d+): ", r"line \1: ", line) for line in proc.stderr.splitlines() if "error" in line.lower()]
    return [f"schema (mxfile.xsd): {line}" for line in lines[:5]]


def _num(element, key):
    try:
        return float(element.get(key) or 0)
    except ValueError:
        return None


def validate(path):
    """Returns (errors, warnings, stats). Errors mean the file is broken; warnings are worth a look."""
    errors, warnings = [], []
    stats = {"pages": 0, "vertices": 0, "edges": 0}
    try:
        mxfile = load_mxfile(path)
    except DrawioFileError as exc:
        return [str(exc)], warnings, stats

    for number, diagram in enumerate(mxfile.findall("diagram"), 1):
        where = f"page {number} ({diagram.get('name')!r})"
        stats["pages"] += 1
        root, cells = page_cells(diagram)
        if root is None:
            errors.append(f"{where}: missing <mxGraphModel><root>")
            continue
        ids = {}
        for c in cells:
            if not c.id:
                errors.append(f"{where}: a cell has no id")
            elif c.id in ids:
                errors.append(f"{where}: duplicate cell id {c.id!r}")
            else:
                ids[c.id] = c
        roots = [c for c in cells if c.parent is None]
        if len(roots) != 1:
            errors.append(f"{where}: expected exactly one root cell without a parent (id=\"0\"), found {len(roots)}")
        elif not any(c.parent == roots[0].id for c in cells):
            errors.append(f"{where}: no layer cell (e.g. <mxCell id=\"1\" parent=\"0\"/>)")

        for c in cells:
            if c.parent is not None and c.parent not in ids:
                errors.append(f"{where}: cell {c.id!r} has unknown parent {c.parent!r}")
            seen, cur = set(), c
            while cur is not None and cur.parent is not None:
                if cur.id in seen:
                    errors.append(f"{where}: cell {c.id!r} is in a parent cycle")
                    break
                seen.add(cur.id)
                cur = ids.get(cur.parent)
            if c.vertex and c.edge:
                errors.append(f"{where}: cell {c.id!r} is marked as both vertex and edge")
            if c.vertex:
                stats["vertices"] += 1
                g = c.geometry
                if g is None:
                    errors.append(f"{where}: vertex {c.id!r} has no <mxGeometry>")
                elif g.get("as") != "geometry":
                    errors.append(f"{where}: vertex {c.id!r}: <mxGeometry> needs as=\"geometry\"")
                elif any(_num(g, k) is None for k in ("x", "y", "width", "height")):
                    errors.append(f"{where}: vertex {c.id!r} has non-numeric geometry")
                elif g.get("relative") != "1" and (not _num(g, "width") or not _num(g, "height")):
                    warnings.append(f"{where}: vertex {c.id!r} has zero width or height")
            if c.edge:
                stats["edges"] += 1
                g = c.geometry
                if g is None or g.get("as") != "geometry":
                    errors.append(f"{where}: edge {c.id!r} needs <mxGeometry relative=\"1\" as=\"geometry\"/>")
                    continue
                fixed = {p.get("as") for p in g.findall("mxPoint")}
                for end, ref in (("source", c.source), ("target", c.target)):
                    if ref is None:
                        if end + "Point" not in fixed:
                            warnings.append(f"{where}: edge {c.id!r} has no {end} (dangling end)")
                    elif ref not in ids:
                        errors.append(f"{where}: edge {c.id!r} has unknown {end} {ref!r}")
                    elif not ids[ref].vertex:
                        warnings.append(f"{where}: edge {c.id!r} {end} {ref!r} is not a vertex")

        if not any(c.vertex or c.edge for c in cells):
            warnings.append(f"{where}: the page is empty")
        warnings.extend(_overlaps(where, cells, ids))
    warnings.extend(schema_problems(path))
    return errors, warnings, stats


def _overlaps(where, cells, ids):
    """Sibling shapes on top of each other usually mean a layout mistake."""
    if any("umlLifeline" in c.style for c in cells):
        return []  # sequence diagrams stack frames and notes over lifelines on purpose
    parents = {c.parent for c in cells}
    by_parent = {}
    for c in cells:
        g = c.geometry
        if not c.vertex or g is None or g.get("relative") == "1" or c.id in parents:
            continue
        if not c.label.strip() or c.style.startswith("text;"):
            continue  # frames, rules and captions are allowed to sit on top of other things
        parent = ids.get(c.parent)
        if parent is not None and parent.edge:
            continue
        rect = c.rect()
        if rect and rect[2] > 0 and rect[3] > 0:
            by_parent.setdefault(c.parent, []).append((c.id, rect))
    out = []
    for group in by_parent.values():
        if len(group) > 400:
            continue
        for i, (a, (ax, ay, aw, ah)) in enumerate(group):
            for b, (bx, by, bw, bh) in group[i + 1:]:
                if ax < bx + bw - 1 and bx < ax + aw - 1 and ay < by + bh - 1 and by < ay + ah - 1:
                    out.append(f"{where}: shapes {a!r} and {b!r} overlap")
                    if len(out) >= 10:
                        return out + [f"{where}: ...more overlaps not listed"]
    return out
