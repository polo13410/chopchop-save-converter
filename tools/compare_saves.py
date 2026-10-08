"""Side-by-side summary of Chop Chop Inc. saves, as a Markdown table.

Usage (from the repository root):
    python -m tools.compare_saves demo.sav base.sav converted.sav [--names Demo Base Converted]
"""

import argparse
import csv
import os
import struct
import sys
from collections import Counter

from chopchop import data_dir, odin_binary
from chopchop import odin_tree as T
from chopchop.world import SaveView, asset_pos


def load_names():
    names = {}
    for f in ("catalog-demo.csv", "catalog-full.csv"):
        with open(os.path.join(data_dir(), f), encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                names[int(r["assetID"])] = r["name"]
    return names


def summarize(path, names):
    with open(path, "rb") as f:
        doc = odin_binary.decode(f.read())
    V = SaveView(doc)
    objs = V.objects()
    refs = T.index_refs(doc)

    inv_service = T.service(doc, "Service.Inventory.ServiceData")
    special = {}
    for inv_type, value, _ in T.dict_pairs(T.field(inv_service, "specialInventories")):
        node = refs[value["v"]] if value["t"] == "intref" else value
        special[inv_type] = {k: T.field(v, "amount")["v"] for k, v, _ in T.dict_pairs(T.field(node, "content"))}
    money = sum(a for k, a in special.get(0, {}).items() if names.get(k) == "Item_Money")
    backpack = special.get(1, {})

    def ints(svc, field):
        return [e["v"] for e in T.array_of(T.field(T.service(doc, svc), field))["c"]]

    stats_node = T.dict_pairs(V.dicts["Player.PlayerStats+SaveData"])[0][1]
    arr = T.field(stats_node, "permanentValue")["c"][0]
    stats = struct.unpack(f"<{arr['count']}f", bytes.fromhex(arr["hex"]))
    _, player_pos = asset_pos(objs[V.player_id()])

    kinds = Counter(names.get(asset_pos(o)[0], "?") for o in objs.values())
    trees = sum(c for n, c in kinds.items() if n.startswith("p_Tree_"))
    mission_ids = V.mission_ids()
    return {
        "Money": money,
        "Backpack (kinds of items / total)": f"{len(backpack)} / {sum(backpack.values())}",
        "Unlocked recipes": len(ints("Service.Recipe.ServiceData", "unlockedRecipes")),
        "Unlocked shop items": len(ints("Service.Shop.ServiceData", "unlockedItems")),
        "Unlocked board missions": len(ints("Service.MissionBoard.ServiceData", "unlockedMissionIDs")),
        "Running board missions": len(ints("Service.MissionBoard.ServiceData", "runningMissions")),
        "Active missions (incl. hidden)": len(mission_ids),
        "Strength / stamina / move speed": f"{stats[1]:.2f} / {stats[2]:.0f} / {stats[3]:.2f}",
        "World objects": len(objs),
        "Trees standing": trees,
        "Player position": "(" + ", ".join(f"{c:.0f}" for c in player_pos) + ")",
        "Tutorial finished marker": "yes" if kinds.get("p_tutorialPlayed") else "no",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("saves", nargs="+")
    p.add_argument("--names", nargs="+", help="column titles")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    names = load_names()
    titles = args.names or [os.path.basename(s) for s in args.saves]
    rows = [summarize(s, names) for s in args.saves]
    print("| | " + " | ".join(titles) + " |")
    print("|---|" + "---|" * len(titles))
    for key in rows[0]:
        print(f"| {key} | " + " | ".join(str(r[key]) for r in rows) + " |")


if __name__ == "__main__":
    main()
