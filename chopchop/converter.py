"""Carry the progress of a Chop Chop Inc. demo save over to a full-game save.

What is transferred:
- unlocked recipes and shop items (demo + base, merged);
- target audience values;
- special inventories: money, player backpack...;
- the mission board and the active missions, with the state of their checks;
- missions, recipes and rewards the full game added to missions the demo ran,
  and to zone triggers the demo already fired (e.g. the lab door battery holders);
- player stats: strength, stamina, move speed;
- world objects: cut trees, buildings, machines and their contents;
- player position and view direction.

Not transferred: the item in hand, drones and trucks mid-delivery, achievements.

Command line (from the repository root):
    python -m chopchop.converter <demo.sav> <output.sav> [--base base.sav] [--progress-only]
"""

import argparse
import copy
import csv
import os
import sys

from . import data_dir
from . import missions
from . import odin_binary
from . import odin_tree as T
from . import progress
from . import world

# Content the developers moved between the demo and the full game: follow the full game.
# The Area 2 teleporter now leads to the mountains, from another spot; it has to be
# rebuilt, and the doors of the old spot are not transferred.
KEEP_BASE_MISSIONS = frozenset({"Mission_Area2_TP_CheckIfBuild"})
SKIP_DEMO_MISSIONS = frozenset({"Mission_Area2_CheckForDoorbellDestroy", "Mission_Area2_StayCloseTP"})
SKIP_DEMO_OBJECTS = frozenset({"Teleporter_Closed", "p_teleporter_Area2_DoorbellCollider"})

# Objects the full game rebuilds through a quest, at a new spot. When the converter starts
# that quest, the demo object is removed so it does not stay behind at the old spot.
# The full-game cooking tutorial (walk to Chester, collect the pot, build the station)
# builds the cooking station next to the campfire; in the demo it was built by the cabin.
REBUILT_BY_QUEST = {"Mission_Tutorial_12A_WalkToChester": ("p_CookingStation_Crafter",)}


class ConversionError(Exception):
    pass


def _path(name, folder=None):
    return os.path.join(folder or data_dir(), name)


def load_catalog(path):
    with open(path, encoding="utf-8") as f:
        return {int(r["assetID"]): r["name"] for r in csv.DictReader(f)}


def load_prefabs(path):
    """AssetIDs of world objects that exist as prefabs (the game can recreate them)."""
    with open(path, encoding="utf-8") as f:
        return {int(r["assetID"]) for r in csv.DictReader(f)
                if r["category"] == "WorldObject" and r["file"] == "resources.assets"}


def convert(demo_bytes, base_bytes=None, with_world=True, log=print, data=None):
    """Return the bytes of a full-game save holding the progress of `demo_bytes`."""
    if base_bytes is None:
        with open(_path("base-full-game.sav", data), "rb") as f:
            base_bytes = f.read()
    try:
        demo = odin_binary.decode(demo_bytes)
        base = odin_binary.decode(base_bytes)
        world.SaveView(demo)
    except Exception as e:
        raise ConversionError(f"this file does not look like a Chop Chop Inc. save ({e})") from e

    catalog_demo = load_catalog(_path("catalog-demo.csv", data))
    catalog_full = load_catalog(_path("catalog-full.csv", data))
    demo_refs = T.index_refs(demo)
    base_refs = T.index_refs(base)
    originals = copy.deepcopy(base_refs)

    progress.merge_hashset(demo, base, "Service.Recipe.ServiceData", "unlockedRecipes", "Recipes", log)
    progress.merge_hashset(demo, base, "Service.Shop.ServiceData", "unlockedItems", "Shop items", log)
    progress.copy_audiences(demo, base, log)
    progress.copy_special_inventories(demo, base, demo_refs, base_refs, catalog_full, log)
    missions.report_check_differences(demo, base, catalog_full, log)
    progress.transfer_player_stats(demo, base, log)
    mission_children = missions.transfer_missions(
        demo, base, catalog_demo, catalog_full, log,
        keep_base=KEEP_BASE_MISSIONS, skip_demo=SKIP_DEMO_MISSIONS)
    if with_world:
        world.transfer_world(
            demo, base, demo_refs, base_refs, catalog_demo, catalog_full,
            world.load_scene(_path("scene-demo.csv", data)), world.load_scene(_path("scene-full.csv", data)),
            log, mission_children,
            prefab_assets=load_prefabs(_path("catalog-full.csv", data)), skip_names=SKIP_DEMO_OBJECTS)

    missions_demo = missions.load_definitions(_path("missions-demo.json", data))
    missions_full = missions.load_definitions(_path("missions-full.json", data))
    started, completed = missions.demo_progress(demo, catalog_demo, missions_demo)
    adds = missions.Additions(base, catalog_demo, catalog_full, missions_full, completed,
                              skip_missions=KEEP_BASE_MISSIONS)
    missions.apply_full_additions(adds, catalog_demo, catalog_full, missions_demo, missions_full,
                                  started, completed, log)
    if with_world:
        missions.apply_trigger_additions(adds, demo, missions.load_definitions(_path("triggers-demo.json", data)),
                                         missions.load_definitions(_path("triggers-full.json", data)), log)
    for quest, objects in REBUILT_BY_QUEST.items():
        if quest in adds.started:
            for name in objects:
                adds.remove_all(name)
    adds.finish(log)
    missions.ensure_tutorial_marker(base, catalog_full, started, log)

    T.renumber(base, originals)
    out = odin_binary.encode(base)
    odin_binary.decode(out)  # the result must read back
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("demo", help="demo save (.sav)")
    p.add_argument("output", help="converted save to write (.sav)")
    p.add_argument("--base", help="fresh full-game save to start from (default: the bundled one)")
    p.add_argument("--data", help="folder with the catalogs (default: the bundled data folder)")
    p.add_argument("--progress-only", action="store_true", help="do not transfer world objects")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with open(args.demo, "rb") as f:
        demo = f.read()
    base = None
    if args.base:
        with open(args.base, "rb") as f:
            base = f.read()
    out = convert(demo, base, with_world=not args.progress_only, data=args.data)
    with open(args.output, "wb") as f:
        f.write(out)
    print(f"Written: {args.output} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
