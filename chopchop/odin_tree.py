"""Helpers to edit the raw tree of a save (the format produced by odin_binary).

Important rule: "ref" nodes carry an id, and "intref" entries can point back
to them. The game writes these ids in file order (0, 1, 2...). After any edit,
call `renumber()`, which renumbers them in order and repairs the references.
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
    """The element array of a collection (HashSet, List, Stack, Dictionary)."""
    for c in node["c"]:
        if c["t"] == "array":
            return c
    raise KeyError("array")


def set_array(arr, items):
    arr["c"] = items
    arr["len"] = len(items)


def dict_pairs(node):
    """(key, value node, pair node) triples of an Odin Dictionary."""
    return [(p["c"][0]["v"], p["c"][1], p) for p in array_of(node)["c"]]


def services(doc):
    """{service type name: value node} for the SessionData root."""
    table = array_of(field(doc["root"][0], "data"))
    out = {}
    for pair in table["c"]:
        key, value = pair["c"][0], pair["c"][1]
        out[key["c"][0]["v"]] = value
    return out


def service(doc, prefix):
    matches = [v for k, v in services(doc).items() if k.startswith(prefix) or prefix in k]
    if len(matches) != 1:
        raise KeyError(f"{prefix}: {len(matches)} services found")
    return matches[0]


def clone(node):
    """Deep copy with fresh temporary ids.

    Intrefs inside the subtree follow their target. Those pointing outside
    the subtree are kept as they are and repaired by renumber().
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
    """Renumber refs in file order and repair intrefs.

    `originals`: {old id: node} for every source used. If an intref targets a
    node that was removed or now comes later in the file, it is replaced by a
    full copy of that node, which is what Odin writes on first occurrence.
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
                    raise ValueError(f"internal reference {e['v']} not found")
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
