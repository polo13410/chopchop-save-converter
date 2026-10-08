"""Outils pour manipuler l'arbre brut d'une sauvegarde (format de odin_binary).

Règle importante : les nœuds "ref" portent un identifiant, et des entrées
"intref" peuvent y renvoyer. Le jeu écrit ces identifiants dans l'ordre du
fichier (0, 1, 2...). Après toute modification, appeler `renumber()` qui
renumérote dans l'ordre et répare les références.
"""

import copy
import itertools

_temp_ids = itertools.count(-1, -1)


def walk(entries):
    for e in entries:
        yield e
        if "c" in e:
            yield from walk(e["c"])


def field(node, name):
    for c in node["c"]:
        if c.get("n") == name:
            return c
    raise KeyError(name)


def array_of(node):
    """Le tableau d'éléments d'une collection (HashSet, List, Stack, Dictionary)."""
    for c in node["c"]:
        if c["t"] == "array":
            return c
    raise KeyError("array")


def set_array(arr, items):
    arr["c"] = items
    arr["len"] = len(items)


def dict_pairs(node):
    """Paires (clé, nœud valeur, nœud paire) d'un Dictionary Odin."""
    return [(p["c"][0]["v"], p["c"][1], p) for p in array_of(node)["c"]]


def services(doc):
    """{nom de type du service: (nœud paire, nœud valeur)} pour la racine SessionData."""
    table = array_of(field(doc["root"][0], "data"))
    out = {}
    for pair in table["c"]:
        key, value = pair["c"][0], pair["c"][1]
        out[key["c"][0]["v"]] = value
    return out


def service(doc, prefix):
    matches = [v for k, v in services(doc).items() if k.startswith(prefix) or prefix in k]
    if len(matches) != 1:
        raise KeyError(f"{prefix}: {len(matches)} services trouvés")
    return matches[0]


def clone(node):
    """Copie profonde avec de nouveaux identifiants temporaires.

    Les intref internes au sous-arbre suivent leur cible. Celles qui pointent
    hors du sous-arbre sont gardées telles quelles et réparées par renumber().
    """
    node = copy.deepcopy(node)
    mapping = {}
    for e in walk([node]):
        if e["t"] == "ref":
            new = next(_temp_ids)
            mapping[e["id"]] = new
            e["id"] = new
    for e in walk([node]):
        if e["t"] == "intref" and e["v"] in mapping:
            e["v"] = mapping[e["v"]]
    return node


def fresh_ref(type_name, children, name=None):
    e = {"t": "ref"}
    if name is not None:
        e["n"] = name
    e["type"] = type_name
    e["id"] = next(_temp_ids)
    e["c"] = children
    return e


def renumber(doc, originals):
    """Renumérote les ref dans l'ordre du fichier et répare les intref.

    `originals` : {ancien id: nœud} pour toutes les sources utilisées. Si une
    intref vise un nœud supprimé ou situé plus loin, on la remplace par une
    copie complète de ce nœud, comme le ferait Odin à la première occurrence.
    """
    seen = {}
    counter = itertools.count()

    def visit(entries):
        for i, e in enumerate(entries):
            if e["t"] == "intref":
                if e["v"] in seen:
                    e["v"] = seen[e["v"]]
                    continue
                target = originals.get(e["v"])
                if target is None:
                    raise ValueError(f"référence interne {e['v']} introuvable")
                old = e["v"]
                full = clone(target)
                if "n" in e:
                    full["n"] = e["n"]
                else:
                    full.pop("n", None)
                entries[i] = full
                visit_node(full)
                seen[old] = full["id"]
                continue
            visit_node(e)

    def visit_node(e):
        if e["t"] == "ref":
            old = e["id"]
            e["id"] = next(counter)
            seen.setdefault(old, e["id"])
        if "c" in e:
            visit(e["c"])

    visit(doc["root"])


def index_refs(doc):
    return {e["id"]: e for e in walk(doc["root"]) if e["t"] == "ref"}
