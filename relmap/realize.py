"""Graph -> story text, and the reverse parse used to verify every story."""

import re

from .schema import CONNECTIVES, DOMAINS

NAME = r"[A-Z][a-z]+"


def new_style(rng, domain, n_edges, avoid=None):
    """Pick surface choices for one story. `avoid` forces a different wording."""
    n_forms = 3
    forms = []
    for i in range(n_edges):
        opts = [k for k in range(n_forms) if not avoid or k != avoid["forms"][i]]
        forms.append(rng.choice(opts))
    order = list(range(n_edges))
    for _ in range(20):
        rng.shuffle(order)
        if not avoid or n_edges < 2 or order != avoid["order"]:
            break
    intros = range(len(DOMAINS[domain]["intros"]))
    intro = rng.choice([k for k in intros if not avoid or k != avoid["intro"]])
    conns = [rng.randrange(len(CONNECTIVES)) for _ in range(n_edges - 1)]
    return {"forms": forms, "order": order, "intro": intro, "conns": conns}


def render(domain, names, edges, style):
    """Return (text, triples) with triples as [head, REL, tail] in sentence order."""
    d = DOMAINS[domain]
    sentences, triples = [], []
    for pos, i in enumerate(style["order"]):
        u, r, v = edges[i]
        clause = d["lex"][r][style["forms"][i]].format(x=names[u], y=names[v])
        prefix = d["intros"][style["intro"]] + " " if pos == 0 else CONNECTIVES[style["conns"][pos - 1]]
        sentences.append(prefix + clause + ".")
        triples.append([names[u], r, names[v]])
    return " ".join(sentences), triples


def _patterns(domain):
    out = []
    for rel, forms in DOMAINS[domain]["lex"].items():
        for t in forms:
            rx = re.escape(t).replace(r"\{x\}", f"(?P<x>{NAME})").replace(r"\{y\}", f"(?P<y>{NAME})")
            out.append((rel, re.compile(rx)))
    return out


def parse(domain, text):
    """Recover triples from a template story. Raises ValueError if any sentence
    matches zero or more than one template (i.e. the text is ambiguous)."""
    d = DOMAINS[domain]
    for intro in d["intros"]:
        if text.startswith(intro + " "):
            text = text[len(intro) + 1:]
            break
    else:
        raise ValueError(f"no known intro: {text!r}")
    triples = []
    for sent in text.rstrip(".").split(". "):
        for c in sorted(set(CONNECTIVES), key=len, reverse=True):
            if c and sent.startswith(c):
                sent = sent[len(c):]
                break
        hits = [(rel, m) for rel, rx in _patterns(domain) if (m := rx.fullmatch(sent))]
        if len(hits) != 1:
            raise ValueError(f"{len(hits)} template matches for {sent!r} in {domain}")
        rel, m = hits[0]
        triples.append([m["x"], rel, m["y"]])
    return triples
