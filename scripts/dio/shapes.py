"""Search draw.io's shape libraries (AWS, Azure, GCP, Cisco, Kubernetes, BPMN, P&ID, ...).

A Python port of shared/shape-search.js and shared/icon-search.js from
https://github.com/jgraph/drawio-mcp: Soundex phonetic matching, compound-token
splitting and scored AND/OR ranking over the official shape index, supplemented
by the draw.io icon service for logos and everyday icons.
"""

import json
import os
import re
import urllib.parse

from .upstream import UpstreamError, fetch

IMAGE_BASE_URL = "https://app.diagrams.net/"
DEFAULT_ICON_SERVICE_URL = "https://icons.diagrams.net/api/icons"
ICON_STYLE_PREFIX = ("shape=image;html=1;verticalAlign=top;verticalLabelPosition=bottom;"
                     "labelBackgroundColor=default;imageAspect=0;aspect=fixed;image=")
_SOUNDEX = "01230120022455012603010202"


def soundex(name):
    if not name:
        return ""
    out = [name[0].upper()]
    for ch in name[1:]:
        c = ord(ch.upper()) - 65
        if 0 <= c <= 25 and _SOUNDEX[c] != "0":
            if _SOUNDEX[c] != out[-1]:
                out.append(_SOUNDEX[c])
            if len(out) > 3:
                break
    return "".join(out + ["0"] * (4 - len(out)))


def _stem(token):
    return re.sub(r"\.*\d*$", "", token)


def build_tag_map(index):
    tag_map = {}
    for i, shape in enumerate(index):
        tags = shape.get("tags")
        if not tags:
            continue
        seen = set()
        for token in re.sub(r"[/,()]", " ", tags.lower()).split(" "):
            if len(token) < 2 or token in seen:
                continue
            seen.add(token)
            tag_map.setdefault(token, set()).add(i)
            sx = soundex(_stem(token))
            if sx and sx != token and sx not in seen:
                seen.add(sx)
                tag_map.setdefault(sx, set()).add(i)
    return tag_map


def _split_compound(token):
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", token)
    parts = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", parts)
    parts = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", parts)
    return [p for p in parts.lower().split() if len(p) >= 2]


def _absolute_image(style):
    return re.sub(r"(^|;)image=(?!https?:|data:)/?", r"\1image=" + IMAGE_BASE_URL, style)


def search_local(index, tag_map, query, limit):
    """Returns (results, strong). `strong` = the best hit matched every query term exactly."""
    terms = []
    for raw in query.split():
        subs = _split_compound(raw) or ([raw.lower()] if len(raw) >= 2 else [])
        for sub in subs:
            if sub not in terms:
                terms.append(sub)
    if not terms:
        return [], False

    matches = []
    for term in terms:
        exact = set(tag_map.get(term, ()))
        sx = soundex(_stem(term))
        phonetic = set(tag_map.get(sx, ())) - exact if sx and sx != term else set()
        matches.append((exact, phonetic))

    both = None
    for exact, phonetic in matches:
        both = (exact | phonetic) if both is None else both & (exact | phonetic)
        if not both:
            break

    scores = {}
    for exact, phonetic in matches:
        for idx in exact:
            if not both or idx in both:
                scores[idx] = scores.get(idx, 0) + 1.0
        for idx in phonetic:
            if not both or idx in both:
                scores[idx] = scores.get(idx, 0) + 0.5
    ranked = sorted(scores, key=lambda idx: (-scores[idx], (index[idx].get("title") or "").lower()))
    results = [{"title": index[i].get("title"), "style": _absolute_image(index[i]["style"]),
                "w": index[i].get("w"), "h": index[i].get("h")} for i in ranked[:limit]]
    return results, bool(ranked) and scores[ranked[0]] >= len(terms)


def icon_service_url():
    value = os.environ.get("DRAWIO_ICON_SERVICE_URL", "")
    if value.lower() in ("off", "none", "0", "false"):
        return None
    return value or DEFAULT_ICON_SERVICE_URL


def search_icons(query, limit, service_url):
    """Logos and concept icons from the draw.io icon service; [] on any failure."""
    if not service_url or limit <= 0:
        return []
    url = f"{service_url}/search?q={urllib.parse.quote(query)}&p=0&c={int(limit)}"
    try:
        images = json.loads(fetch(url, timeout=4)).get("images")
    except (UpstreamError, ValueError, AttributeError):
        return []
    results = []
    for img in images if isinstance(images, list) else []:
        link = img.get("url") if isinstance(img, dict) else None
        if not isinstance(link, str) or not link.startswith("https://") or re.search(r"[;&\"'<>\s]", link[8:]):
            continue
        title = " ".join(re.sub(r"[_-]+", " ", img.get("title") or "").split())
        set_name = (img.get("set") or {}).get("name") if isinstance(img.get("set"), dict) else None
        if set_name:
            title = f"{title} ({set_name})".strip()
        w, h = img.get("width"), img.get("height")
        results.append({"title": title, "style": ICON_STYLE_PREFIX + link,
                        "w": w if isinstance(w, (int, float)) and w > 0 else 48,
                        "h": h if isinstance(h, (int, float)) and h > 0 else 48})
        if len(results) >= limit:
            break
    return results


def search(index, query, limit=10, icons=True):
    """Local stencils first; the icon service fills in when local matches are weak or few."""
    results, strong = search_local(index, build_tag_map(index), query, limit)
    service = icon_service_url() if icons else None
    if not service:
        return results
    if not strong:
        keep = min(len(results), limit // 2)
        found = search_icons(query, limit - keep, service)
        return results[:limit - len(found)] + found
    if len(results) < limit:
        results += search_icons(query, limit - len(results), service)
    return results
