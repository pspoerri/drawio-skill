"""Layered (Sugiyama-style) auto-layout with nested groups. Pure stdlib.

Each group is laid out on its own, then treated as one big node in its parent's
layout. Edges that cross group boundaries are lifted to the level where their
endpoints diverge, so they still drive ranking there.
"""

from bisect import bisect_right, insort
from collections import defaultdict

NODE_GAP = 40
RANK_GAP = 60
GROUP_PAD = 20
EMPTY_GROUP = (160, 80)


def _isotonic(targets, weights):
    """Weighted least-squares fit of a non-decreasing sequence (pool adjacent violators)."""
    blocks = []
    for t, w in zip(targets, weights):
        blocks.append([w, w * t, 1])
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][0] > blocks[-1][1] / blocks[-1][0]:
            w2, wt2, n2 = blocks.pop()
            blocks[-1][0] += w2
            blocks[-1][1] += wt2
            blocks[-1][2] += n2
    out = []
    for w, wt, n in blocks:
        out.extend([wt / w] * n)
    return out


def _grid(items, size, node_gap):
    """No edges at this level: a row for a few items, a grid for many."""
    cols = len(items) if len(items) <= 4 else int(len(items) ** 0.5 + 0.999)
    pos, y, width = {}, 0, 0
    for start in range(0, len(items), cols):
        row = items[start:start + cols]
        row_h = max(size[v][1] for v in row)
        x = 0
        for v in row:
            pos[v] = (x, y + (row_h - size[v][1]) / 2)
            x += size[v][0] + node_gap
        width = max(width, x - node_gap)
        y += row_h + node_gap
    return pos, {}, (width, y - node_gap)


def layered(items, size, edges, node_gap=NODE_GAP, rank_gap=RANK_GAP):
    """Lay out `items` top-to-bottom.

    items: ordered ids; size: id -> (w, h); edges: [(u, v, key)].
    Returns (pos: id -> (x, y), routes: key -> [(x, y), ...], (width, height)).
    """
    if not items:
        return {}, {}, (0, 0)
    pairs = defaultdict(list)
    for u, v, key in edges:
        if u != v:
            pairs[(u, v)].append(key)
    if not pairs:
        return _grid(items, size, node_gap)

    out = defaultdict(list)
    indeg = defaultdict(int)
    for u, v in pairs:
        out[u].append(v)
        indeg[v] += 1

    # 1. Break cycles: edges that close a loop in DFS order get reversed.
    state, back = {}, set()
    for root in [v for v in items if not indeg[v]] + items:
        if state.get(root):
            continue
        state[root] = 1
        stack = [(root, iter(out[root]))]
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if not state.get(nxt):
                    state[nxt] = 1
                    stack.append((nxt, iter(out[nxt])))
                    break
                if state[nxt] == 1:
                    back.add((node, nxt))
            else:
                state[node] = 2
                stack.pop()

    dag = defaultdict(list)  # (a, b) -> [(key, reversed)]
    for (u, v), keys in pairs.items():
        a, b, rev = (v, u, True) if (u, v) in back else (u, v, False)
        dag[(a, b)].extend((k, rev) for k in keys)
    succ, pred = defaultdict(list), defaultdict(list)
    for a, b in dag:
        succ[a].append(b)
        pred[b].append(a)

    # 2. Rank by longest path, then pull sources down next to their first successor.
    remaining = {v: len(pred[v]) for v in items}
    queue = [v for v in items if not remaining[v]]
    topo, rank = [], {v: 0 for v in items}
    while queue:
        v = queue.pop(0)
        topo.append(v)
        for w in succ[v]:
            rank[w] = max(rank[w], rank[v] + 1)
            remaining[w] -= 1
            if not remaining[w]:
                queue.append(w)
    for v in reversed(topo):
        if not pred[v] and succ[v]:
            rank[v] = min(rank[w] for w in succ[v]) - 1

    # 3. Dummy nodes keep a lane free for edges that span several ranks.
    n_ranks = max(rank.values()) + 1
    layers = [[] for _ in range(n_ranks)]
    up, dn = defaultdict(list), defaultdict(list)
    dummies = {}  # (a, b) -> [dummy ids]
    is_dummy = set()
    sizes = dict(size)

    def link(a, b):
        dn[a].append(b)
        up[b].append(a)

    for (a, b) in dag:
        chain = []
        for r in range(rank[a] + 1, rank[b]):
            d = ("__dummy__", a, b, r)
            rank[d] = r
            sizes[d] = (10, 0)
            is_dummy.add(d)
            chain.append(d)
        dummies[(a, b)] = chain
        path = [a] + chain + [b]
        for x, y in zip(path, path[1:]):
            link(x, y)

    # Initial order: depth-first from the top so chains start out aligned.
    visited = set()

    def visit(v):
        stack = [v]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            layers[rank[cur]].append(cur)
            stack.extend(reversed(dn[cur]))

    for v in sorted(items, key=lambda v: rank[v]):
        visit(v)

    # 4. Reduce crossings with barycenter sweeps; keep the best ordering seen.
    def positions():
        return {v: i for layer in layers for i, v in enumerate(layer)}

    def crossings(pos):
        total = 0
        for layer in layers[:-1]:
            ends = sorted((pos[u], pos[v]) for u in layer for v in dn[u])
            seen = []
            for _, pv in ends:
                total += len(seen) - bisect_right(seen, pv)
                insort(seen, pv)
        return total

    pos = positions()
    best, best_cross = [list(layer) for layer in layers], crossings(pos)
    for sweep in range(24):
        if not best_cross:
            break
        down = sweep % 2 == 0
        neigh = up if down else dn
        for r in (range(1, n_ranks) if down else range(n_ranks - 2, -1, -1)):
            layer = layers[r]
            key = {v: (sum(pos[n] for n in neigh[v]) / len(neigh[v]) if neigh[v] else pos[v]) for v in layer}
            layer.sort(key=key.__getitem__)
            for i, v in enumerate(layer):
                pos[v] = i
        cross = crossings(pos)
        if cross < best_cross:
            best, best_cross = [list(layer) for layer in layers], cross
    layers = best

    # 5. Coordinates: pull every node towards its neighbours, never reordering or overlapping.
    center = {}
    offsets = []
    for layer in layers:
        offs, x = [], 0
        for i, v in enumerate(layer):
            if i:
                prev = layer[i - 1]
                gap = node_gap / 2 if (v in is_dummy and prev in is_dummy) else node_gap
                x += (sizes[prev][0] + sizes[v][0]) / 2 + gap
            offs.append(x)
            center[v] = x
        offsets.append(offs)
    widest = max(offs[-1] for offs in offsets)
    for layer, offs in zip(layers, offsets):
        shift = (widest - offs[-1]) / 2
        for v in layer:
            center[v] += shift

    def relax(r, neigh_of):
        layer, offs = layers[r], offsets[r]
        targets, weights = [], []
        for v, off in zip(layer, offs):
            ns = neigh_of(v)
            want = sum(center[n] for n in ns) / len(ns) if ns else center[v]
            targets.append(want - off)
            weights.append(3 if v in is_dummy else 1)
        for v, off, fit in zip(layer, offs, _isotonic(targets, weights)):
            center[v] = fit + off

    for _ in range(8):
        for r in range(1, n_ranks):
            relax(r, lambda v: up[v])
        for r in range(n_ranks - 2, -1, -1):
            relax(r, lambda v: dn[v])
    for r in range(n_ranks):
        relax(r, lambda v: up[v] + dn[v])

    # Straighten long edges: give all dummies of a chain one x if the lane is free on every rank.
    index = {v: i for layer in layers for i, v in enumerate(layer)}

    def lane_free(d, x):
        layer, i = layers[rank[d]], index[d]
        if i and center[layer[i - 1]] + sizes[layer[i - 1]][0] / 2 + node_gap / 2 > x - 5:
            return False
        return i + 1 == len(layer) or center[layer[i + 1]] - sizes[layer[i + 1]][0] / 2 - node_gap / 2 >= x + 5

    for (a, b), chain in dummies.items():
        if len(chain) < 2:
            continue
        xs = sorted(center[d] for d in chain)
        ends = (center[a] + center[b]) / 2
        for x in sorted({xs[len(xs) // 2], xs[0], xs[-1], center[a], center[b]}, key=lambda x: abs(x - ends)):
            if all(lane_free(d, x) for d in chain):
                for d in chain:
                    center[d] = x
                break

    left = min(center[v] - sizes[v][0] / 2 for layer in layers for v in layer)
    row_top, y = [], 0
    row_h = [max(sizes[v][1] for v in layer) for layer in layers]
    for h in row_h:
        row_top.append(y)
        y += h + rank_gap
    height = y - rank_gap

    result = {}
    for r, layer in enumerate(layers):
        for v in layer:
            if v not in is_dummy:
                w, h = sizes[v]
                result[v] = (center[v] - w / 2 - left, row_top[r] + (row_h[r] - h) / 2)
    width = max(center[v] + sizes[v][0] / 2 for layer in layers for v in layer) - left

    routes = {}
    for (a, b), keyed in dag.items():
        points = []
        for d in dummies[(a, b)]:
            x, r = center[d] - left, rank[d]
            for p in ((x, row_top[r]), (x, row_top[r] + row_h[r])):
                # Drop the middle point of a straight vertical run.
                if len(points) >= 2 and abs(points[-1][0] - x) < 1 and abs(points[-2][0] - x) < 1:
                    points[-1] = p
                else:
                    points.append(p)
        if points:
            for key, rev in keyed:
                routes[key] = points[::-1] if rev else list(points)
    return result, routes, (width, height)


class GraphLayout:
    """Result of laying out a graph spec.

    box[id]   = (x, y, w, h) relative to the parent container
    abs[id]   = (x, y, w, h) relative to the diagram origin
    routes[i] = waypoints of edge i, relative to edge_parent[i]
    edge_parent[i] = group id that should own edge i (None = the layer)
    """

    def __init__(self):
        self.box, self.abs, self.routes, self.edge_parent = {}, {}, {}, {}
        self.size = (0, 0)


def layout_graph(page, node_size, group_top, group_min_width):
    """page: normalised graph spec; node_size: id -> (w, h);
    group_top: id -> header height; group_min_width: id -> min width for the label."""
    nodes, groups, edges = page["nodes"], page["groups"], page["edges"]
    direction = page["direction"]
    horizontal = direction in ("LR", "RL")
    reverse = direction in ("BT", "RL")

    parent = {nid: n["group"] for nid, n in nodes.items()}
    parent.update({gid: g["parent"] for gid, g in groups.items()})

    def path(v):  # [top-level ancestor, ..., v]
        chain = []
        while v is not None:
            chain.append(v)
            v = parent[v]
        return chain[::-1]

    # Order children by where their first node appears in the spec.
    first_seen = {}
    for i, nid in enumerate(nodes):
        for anc in path(nid):
            first_seen.setdefault(anc, i)
    children = defaultdict(list)
    for v in sorted(parent, key=lambda v: first_seen.get(v, len(nodes))):
        children[parent[v]].append(v)

    level_edges = defaultdict(list)
    result = GraphLayout()
    for i, edge in enumerate(edges):
        pu, pv = path(edge["from"]), path(edge["to"])
        k = 0
        while k < len(pu) and k < len(pv) and pu[k] == pv[k]:
            k += 1
        lca = pu[k - 1] if k else None
        if lca in nodes:  # self-loop on a plain node
            lca = parent[lca]
        result.edge_parent[i] = lca
        if k < len(pu) and k < len(pv):
            level_edges[lca].append((pu[k], pv[k], i))

    has_labels = any(e["label"] for e in edges)
    if horizontal:
        longest = max((len(line) for e in edges for line in e["label"].split("\n")), default=0)
        rank_gap = max(RANK_GAP, min(240, longest * 7 + 50)) if has_labels else RANK_GAP
        node_gap = 30
    else:
        rank_gap = 80 if has_labels else RANK_GAP
        node_gap = NODE_GAP

    size = dict(node_size)

    def layout_level(container):
        kids = children[container]
        for kid in kids:
            if kid in groups:
                size[kid] = layout_level(kid)
        canon = {k: (size[k][1], size[k][0]) if horizontal else size[k] for k in kids}
        pos, routes, (w, h) = layered(kids, canon, level_edges[container], node_gap, rank_gap)

        def to_final(x, y, bw=0, bh=0):
            if reverse:
                y = h - y - bh
            return (y, x) if horizontal else (x, y)

        left = GROUP_PAD if container is not None else 0
        top = group_top[container] if container is not None else 0
        for kid in kids:
            cw, ch = canon[kid]
            fx, fy = to_final(*pos[kid], cw, ch)
            result.box[kid] = (fx + left, fy + top, size[kid][0], size[kid][1])
        for key, points in routes.items():
            result.routes[key] = [tuple(c + off for c, off in zip(to_final(x, y), (left, top))) for x, y in points]
        if container is None:
            return (h, w) if horizontal else (w, h)
        if not kids:
            return (max(EMPTY_GROUP[0], group_min_width[container]), EMPTY_GROUP[1])
        fw, fh = (h, w) if horizontal else (w, h)
        total_w = fw + 2 * GROUP_PAD
        min_w = group_min_width[container]
        if total_w < min_w:  # widen to fit the label, keeping the content centred
            shift = (min_w - total_w) / 2
            for kid in kids:
                x, y, bw, bh = result.box[kid]
                result.box[kid] = (x + shift, y, bw, bh)
            for key in routes:
                result.routes[key] = [(x + shift, y) for x, y in result.routes[key]]
            total_w = min_w
        return (total_w, fh + top + GROUP_PAD)

    result.size = layout_level(None)

    def absolute(v):
        if v not in result.abs:
            x, y, w, h = result.box[v]
            if parent[v] is not None:
                px, py, _, _ = absolute(parent[v])
                x, y = x + px, y + py
            result.abs[v] = (x, y, w, h)
        return result.abs[v]

    for v in parent:
        absolute(v)
    return result
