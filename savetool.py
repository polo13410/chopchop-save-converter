"""Outil en ligne de commande pour les sauvegardes de Chop Chop Inc.

Exemples :
    python savetool.py decode save0.sav save0.json
    python savetool.py encode save0.json save0.sav
    python savetool.py check save0.sav
    python savetool.py summary save0.sav
    python savetool.py services demo.sav complet.sav
"""

import argparse
import json
import sys
from collections import Counter

import odin_binary


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
    print(f"Décodé : {args.output}")


def cmd_encode(args):
    with open(args.input, encoding="utf-8") as f:
        tree = json.load(f)
    with open(args.output, "wb") as f:
        f.write(odin_binary.encode(tree))
    print(f"Encodé : {args.output}")


def cmd_check(args):
    with open(args.input, "rb") as f:
        data = f.read()
    again = odin_binary.encode(odin_binary.decode(data))
    if again == data:
        print(f"OK : aller-retour identique ({len(data)} octets)")
        return 0
    diff = next((i for i, (a, b) in enumerate(zip(data, again)) if a != b),
                min(len(data), len(again)))
    print(f"ÉCHEC : premier octet différent à 0x{diff:X} "
          f"(original {len(data)} octets, réencodé {len(again)})")
    return 1


def walk(entries, depth=0):
    for e in entries:
        yield depth, e
        if "c" in e:
            yield from walk(e["c"], depth + 1)


def cmd_summary(args):
    tree = load_tree(args.input)
    kinds = Counter(e["t"] for _, e in walk(tree["root"]))
    print("Entrées par sorte :", dict(kinds.most_common()))
    print("\nStructure (profondeur max", args.depth, ") :")
    for depth, e in walk(tree["root"]):
        if depth > args.depth:
            continue
        label = e.get("n", "")
        if e["t"] in ("ref", "struct"):
            info = e["type"] or ""
            print(f"{'  ' * depth}{label} [{info}] ({len(e['c'])} enfants)")
        elif e["t"] == "array":
            print(f"{'  ' * depth}{label} [tableau de {e['len']}]")
        elif e["t"] == "parray":
            print(f"{'  ' * depth}{label} [tableau primitif {e['count']}x{e['size']}o]")
        else:
            print(f"{'  ' * depth}{label} = {e.get('v')!r} ({e['t']})")


def short(type_name):
    """Raccourcit un nom de type C# pour l'affichage."""
    t = type_name.replace(", Assembly-CSharp", "").replace(", mscorlib", "")
    if t.startswith("System.Collections.Generic.Dictionary`2[[System.UInt32]"):
        t = "objets: " + t.split("],[", 1)[1].rstrip("]")
    return t.replace("Service.", "").replace("WorldObjects.", "")


def services(path):
    """Renvoie {nom du service: nombre d'entrées} pour une sauvegarde."""
    doc = load_tree(path)
    table = doc["root"][0]["c"][1]["c"][1]  # data -> tableau des paires clé/valeur
    out = {}
    for pair in table["c"]:
        key, value = pair["c"][0], pair["c"][1]
        out[short(key["c"][0]["v"])] = sum(1 for _ in walk([value]))
    return out


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
    sys.stdout.reconfigure(encoding="utf-8")  # accents corrects dans la console Windows
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode", help="sauvegarde .sav -> JSON")
    d.add_argument("input"); d.add_argument("output")
    e = sub.add_parser("encode", help="JSON -> sauvegarde .sav")
    e.add_argument("input"); e.add_argument("output")
    c = sub.add_parser("check", help="vérifie que décoder puis réencoder ne perd rien")
    c.add_argument("input")
    s = sub.add_parser("summary", help="affiche la structure d'une sauvegarde")
    s.add_argument("input")
    s.add_argument("--depth", type=int, default=3)
    v = sub.add_parser("services", help="liste les services d'une ou deux sauvegardes")
    v.add_argument("a"); v.add_argument("b", nargs="?")
    args = p.parse_args()
    handler = {"decode": cmd_decode, "encode": cmd_encode,
               "check": cmd_check, "summary": cmd_summary,
               "services": cmd_services}[args.cmd]
    sys.exit(handler(args) or 0)


if __name__ == "__main__":
    main()
