"""Command line tool to inspect Chop Chop Inc. saves.

Run from the repository root:
    python -m tools.savetool decode save0.sav save0.json
    python -m tools.savetool encode save0.json save0.sav
    python -m tools.savetool check save0.sav
    python -m tools.savetool summary save0.sav --depth 3
    python -m tools.savetool services demo.sav full.sav
    python -m tools.savetool schema --a demo.sav --b full1.sav full2.sav
"""

import argparse
import json
import sys
from collections import Counter

from chopchop import odin_binary


def load_tree(path):
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    with open(path, "rb") as f:
        return odin_binary.decode(f.read())


def cmd_decode(args):
    tree = load_tree(args.input)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=1)
    print(f"Decoded: {args.output}")


def cmd_encode(args):
    with open(args.input, encoding="utf-8") as f:
        tree = json.load(f)
    with open(args.output, "wb") as f:
        f.write(odin_binary.encode(tree))
    print(f"Encoded: {args.output}")


def cmd_check(args):
    with open(args.input, "rb") as f:
        data = f.read()
    again = odin_binary.encode(odin_binary.decode(data))
    if again == data:
        print(f"OK: identical round trip ({len(data)} bytes)")
        return 0
    diff = next((i for i, (a, b) in enumerate(zip(data, again)) if a != b),
                min(len(data), len(again)))
    print(f"FAILED: first different byte at 0x{diff:X} "
          f"(original {len(data)} bytes, re-encoded {len(again)})")
    return 1


def walk(entries, depth=0):
    for e in entries:
        yield depth, e
        if "c" in e:
            yield from walk(e["c"], depth + 1)


def cmd_summary(args):
    tree = load_tree(args.input)
    kinds = Counter(e["t"] for _, e in walk(tree["root"]))
    print("Entries by kind:", dict(kinds.most_common()))
    print(f"\nStructure (max depth {args.depth}):")
    for depth, e in walk(tree["root"]):
        if depth > args.depth:
            continue
        label = e.get("n", "")
        if e["t"] in ("ref", "struct"):
            print(f"{'  ' * depth}{label} [{e['type'] or ''}] ({len(e['c'])} children)")
        elif e["t"] == "array":
            print(f"{'  ' * depth}{label} [array of {e['len']}]")
        elif e["t"] == "parray":
            print(f"{'  ' * depth}{label} [primitive array {e['count']}x{e['size']}B]")
        else:
            print(f"{'  ' * depth}{label} = {e.get('v')!r} ({e['t']})")


def short(type_name):
    """Shorten a C# type name for display."""
    t = type_name.replace(", Assembly-CSharp", "").replace(", mscorlib", "")
    if t.startswith("System.Collections.Generic.Dictionary`2[[System.UInt32]"):
        t = "objects: " + t.split("],[", 1)[1].rstrip("]")
    return t.replace("Service.", "").replace("WorldObjects.", "")


def services(path):
    """{service name: number of entries} for a save."""
    doc = load_tree(path)
    table = doc["root"][0]["c"][1]["c"][1]  # data -> array of key/value pairs
    out = {}
    for pair in table["c"]:
        key, value = pair["c"][0], pair["c"][1]
        out[short(key["c"][0]["v"])] = sum(1 for _ in walk([value]))
    return out


def schema(paths):
    """For each C# type, the set of (field name, kind) written in the saves."""
    out = {}
    for path in paths:
        for _, e in walk(load_tree(path)["root"]):
            if e["t"] in ("ref", "struct") and e.get("type"):
                fields = out.setdefault(short(e["type"]), set())
                for c in e["c"]:
                    if "n" in c:
                        kind = c["t"] if c["t"] not in ("ref", "struct") else short(c.get("type") or "null")
                        fields.add((c["n"], kind))
    return out


def cmd_schema(args):
    a = schema(args.a)
    b = schema(args.b)
    for t in sorted(set(a) | set(b)):
        if t not in b:
            print(f"- {t}: only in A")
        elif t not in a:
            print(f"+ {t}: only in B")
        elif a[t] != b[t]:
            print(f"~ {t}")
            for n, k in sorted(a[t] - b[t]):
                print(f"    - {n} ({k})")
            for n, k in sorted(b[t] - a[t]):
                print(f"    + {n} ({k})")
        elif args.all:
            print(f"= {t}")


def cmd_services(args):
    a = services(args.a)
    b = services(args.b) if args.b else {}
    width = max(len(k) for k in list(a) + list(b))
    print(f"{'service':<{width}}  {'A':>7}  {'B':>7}")
    for name in sorted(set(a) | set(b)):
        va = a.get(name, "-")
        vb = b.get(name, "-") if args.b else ""
        print(f"{name:<{width}}  {va:>7}  {vb:>7}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode", help=".sav save -> JSON")
    d.add_argument("input")
    d.add_argument("output")
    e = sub.add_parser("encode", help="JSON -> .sav save")
    e.add_argument("input")
    e.add_argument("output")
    c = sub.add_parser("check", help="check that decoding then re-encoding loses nothing")
    c.add_argument("input")
    s = sub.add_parser("summary", help="show the structure of a save")
    s.add_argument("input")
    s.add_argument("--depth", type=int, default=3)
    v = sub.add_parser("services", help="list the services of one or two saves")
    v.add_argument("a")
    v.add_argument("b", nargs="?")
    m = sub.add_parser("schema", help="compare the fields written per type between two groups of saves")
    m.add_argument("--a", nargs="+", required=True, help="saves of group A (e.g. demo)")
    m.add_argument("--b", nargs="+", required=True, help="saves of group B (e.g. full game)")
    m.add_argument("--all", action="store_true", help="also show identical types")
    args = p.parse_args()
    handler = {"decode": cmd_decode, "encode": cmd_encode, "check": cmd_check,
               "summary": cmd_summary, "services": cmd_services, "schema": cmd_schema}[args.cmd]
    sys.exit(handler(args) or 0)


if __name__ == "__main__":
    main()
