"""Files taken from the official draw.io MCP repository (https://github.com/jgraph/drawio-mcp, Apache-2.0).

The reference documents are vendored under references/upstream/; the shape index
(about 5 MB, regenerated upstream on every draw.io release) is downloaded on
first use and cached.
"""

import datetime
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

REPO = "jgraph/drawio-mcp"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
SKILL_DIR = Path(__file__).resolve().parents[2]
REFERENCE_DIR = SKILL_DIR / "references" / "upstream"
REFERENCES = [
    "shared/xml-reference.md",
    "shared/xml-essentials.md",
    "shared/style-reference.md",
    "shared/mermaid-reference.md",
    "shared/mxfile.xsd",
]
INDEX_PATH = "shape-search/search-index.json"
XSD = REFERENCE_DIR / "mxfile.xsd"


class UpstreamError(RuntimeError):
    pass


def fetch(url, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": "drawio-skill"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise UpstreamError(f"cannot download {url}: {exc}") from exc


def index_candidates():
    return [SKILL_DIR / "data" / "search-index.json",
            Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "drawio-skill" / "search-index.json"]


def load_index(refresh=False):
    """The flat shape index: [{style, w, h, title, tags, type}, ...]."""
    if not refresh:
        for path in index_candidates():
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8")), path
    data = fetch(RAW + INDEX_PATH, timeout=120)
    index = json.loads(data)
    last = None
    for path in index_candidates():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return index, path
        except OSError as exc:
            last = exc
    raise UpstreamError(f"downloaded the shape index but could not cache it: {last}")


def update_references():
    """Refresh references/upstream/ from the main branch. Returns the list of files written."""
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for path in REFERENCES:
        target = REFERENCE_DIR / Path(path).name
        target.write_bytes(fetch(RAW + path))
        written.append(target)
    commit = "unknown"
    try:
        info = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits/main", timeout=20))
        commit = info["sha"]
    except (UpstreamError, KeyError, ValueError):
        pass
    (REFERENCE_DIR / "SOURCE.md").write_text(
        "# Upstream reference files\n\n"
        f"Copied unmodified from https://github.com/{REPO} (`shared/`), licensed Apache-2.0.\n\n"
        f"- Commit: `{commit}`\n- Fetched: {datetime.date.today().isoformat()}\n\n"
        "Refresh with `python3 scripts/drawio_gen.py update`. Do not edit these files by hand.\n\n"
        "These documents were written for the draw.io MCP servers. Where they mention the `search_shapes`\n"
        "tool, use `scripts/drawio_gen.py shapes QUERY`; where they mention `postLayout` / `routing`,\n"
        "use the draw.io desktop CLI's `--layout` option or this skill's own layout (`build`).\n",
        encoding="utf-8")
    return written
