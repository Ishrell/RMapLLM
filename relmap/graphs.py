"""Small directed, labeled graphs: matching, canonical forms, perturbations.

A graph is a list of edges (head, relation, tail) over node ids 0..n-1.
Graphs here have at most ~6 nodes, so brute force over permutations is fine.
"""

import hashlib
from itertools import permutations


def n_nodes(edges):
    return max(max(u, v) for u, _, v in edges) + 1


def is_valid(edges, n):
    """No self loops, no duplicate triples, every node 0..n-1 used, connected."""
    if len(set(edges)) != len(edges) or any(u == v for u, _, v in edges):
        return False
    used = {u for u, _, _ in edges} | {v for _, _, v in edges}
    if used != set(range(n)):
        return False
    seen, stack = {0}, [0]
    while stack:
        a = stack.pop()
        for u, _, v in edges:
            for b in ((v,) if u == a else (u,) if v == a else ()):
                if b not in seen:
                    seen.add(b)
                    stack.append(b)
    return len(seen) == n


def isomorphisms(a, b):
    """All node maps p (tuple: a-node -> b-node) that turn graph a into graph b."""
    if len(a) != len(b) or n_nodes(a) != n_nodes(b):
        return []
    target = set(b)
    return [p for p in permutations(range(n_nodes(b)))
            if {(p[u], r, p[v]) for u, r, v in a} == target]


def matches(a, b):
    return bool(isomorphisms(a, b))


def canonical(edges, labeled=True):
    n = n_nodes(edges)
    forms = (tuple(sorted((p[u], r if labeled else "", p[v]) for u, r, v in edges))
             for p in permutations(range(n)))
    return min(forms)


def _hash(obj):
    return hashlib.md5(repr(obj).encode()).hexdigest()[:8]


def structure_id(edges):
    """Id of the labeled structure (shape + relation types)."""
    return _hash(canonical(edges))


def shape_id(edges):
    """Id of the unlabeled shape, e.g. 'e3n4-1a2b3c4d'."""
    return f"e{len(edges)}n{n_nodes(edges)}-{_hash(canonical(edges, labeled=False))}"


def random_graph(rng, n_edges, relations, uniform_prob=0.3):
    """Random connected graph with n_edges edges, built as a tree plus extras."""
    lo = 2
    while lo * (lo - 1) < n_edges:
        lo += 1
    # Prefer tree-like graphs (more entities, easier to read as a story).
    options = list(range(lo, n_edges + 2))
    n = rng.choices(options, weights=[1 + 2 * (k == n_edges + 1) for k in options])[0]
    uniform = rng.random() < uniform_prob
    rel0 = rng.choice(relations)

    def rel():
        return rel0 if uniform else rng.choice(relations)

    while True:
        order = list(range(n))
        rng.shuffle(order)
        pairs = set()
        for i in range(1, n):
            a, b = order[i], rng.choice(order[:i])
            pairs.add((a, b) if rng.random() < 0.5 else (b, a))
        while len(pairs) < n_edges:
            a, b = rng.sample(range(n), 2)
            pairs.add((a, b))
        edges = [(u, rel(), v) for u, v in sorted(pairs)]
        if len(pairs) == n_edges and is_valid(edges, n):
            if uniform or n_edges == 1 or len({r for _, r, _ in edges}) > 1:
                return edges


def perturbations(edges, kind, relations):
    """All single-edit variants of `edges` that do NOT match the original.

    kind: 'reverse' (flip one edge), 'relabel' (change one relation type),
          'rewire' (move one endpoint of an edge to another node).
    The node set never changes, so a perturbed story has the same entities.
    """
    n = n_nodes(edges)
    out = []
    for i, (u, r, v) in enumerate(edges):
        if kind == "reverse":
            new = [(v, r, u)]
        elif kind == "relabel":
            new = [(u, r2, v) for r2 in relations if r2 != r]
        elif kind == "rewire":
            new = [(w, r, v) for w in range(n) if w not in (u, v)] + \
                  [(u, r, w) for w in range(n) if w not in (u, v)]
        else:
            raise ValueError(kind)
        for e in new:
            g = edges[:i] + [e] + edges[i + 1:]
            if is_valid(g, n) and not matches(edges, g):
                out.append(g)
    return out
