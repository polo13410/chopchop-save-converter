"""Transfer of world objects from the demo save into a full-game save.

World object numbers (worldObjectID) differ between the two versions. Within
one version, objects placed in the scenes get a fixed number: the game finds
them again by that number when loading, so they must never be renumbered.
Objects are matched from one version to the other by type (assetID) and
position, using the initial state of both maps, extracted from the game scenes
(tools/extract_scene.py).

Rules, for every object (missions and the player are handled separately):

Objects of the base save (full game):
- on the full-game map AND on the demo map: keeps its number and takes the
  demo state, or is removed if it was destroyed in the demo (a cut tree...);
- only on the full-game map: kept (new content);
- spawned during play (on neither map): removed if the demo knows its type,
  kept otherwise.

Objects of the demo save:
- on the demo map and on the full-game map: merged into the matching base
  object (see above);
- on the demo map but no longer on the full-game map: ignored, the full game
  changed that spot;
- on both maps but inactive at the start of the full game (cabin, workbench):
  recreated from its prefab, like an object spawned during play;
- spawned during play (buildings, dropped items, animals): added, unless it
  duplicates a kept base object at the same spot.
"""

import csv
import math
import struct
from collections import defaultdict

from . import odin_tree as T

TOLERANCE = 0.5  # meters
MOVED_TOLERANCE = 3.0  # objects moved by the developers between versions

SKIP_TYPES = ("Drone.DeliveryDrone+SaveData", "Truck.Truck+SaveData")
PLAYER_TYPES = ("Player.Player+SaveData", "Player.PlayerStats+SaveData",
                "Player.CurrentItem+SaveData", "Player.FPSCamera+SaveData",
                "Player.PlayerRespawn+SaveData")


def load_scene(path):
    with open(path, encoding="utf-8") as f:
        return [(int(r["assetID"]), (float(r["x"]), float(r["y"]), float(r["z"])))
                for r in csv.DictReader(f) if r["flag"] == "1"]


class Matcher:
    """Matches (assetID, position) items to a reference list, each reference used once."""

    def __init__(self, reference, tolerance=TOLERANCE):
        self.tolerance = tolerance
        self.by_asset = defaultdict(list)
        for i, (asset, pos) in enumerate(reference):
            self.by_asset[asset].append((i, pos))

    def match_all(self, items):
        """items: {key: (assetID, position)} -> {key: reference index}.

        The closest pairs are assigned first.
        """
        candidates = []
        for key, (asset, pos) in items.items():
            for i, ref in self.by_asset.get(asset, ()):
                d = math.dist(pos, ref)
                if d < self.tolerance:
                    candidates.append((d, key, i))
        candidates.sort(key=lambda c: c[0])
        out, used = {}, set()
        for d, key, i in candidates:
            if key in out or i in used:
                continue
            out[key] = i
            used.add(i)
        return out


def parray_values(node, fmt="I"):
    arr = node["c"][0]
    return list(struct.unpack(f"<{arr['count']}{fmt}", bytes.fromhex(arr["hex"])))


def set_parray(node, values, fmt="I"):
    arr = node["c"][0]
    arr["count"] = len(values)
    arr["hex"] = struct.pack(f"<{len(values)}{fmt}", *values).hex()


class SaveView:
    """Convenient access to the per-object dictionaries of a save."""

    def __init__(self, doc):
        self.doc = doc
        self.dicts = {}  # short type name -> Dictionary node
        self.pairs = {}  # short type name -> pair in the service table
        table = T.array_of(T.field(doc["root"][0], "data"))
        for pair in table["c"]:
            type_name = pair["c"][0]["c"][0]["v"]
            if type_name.startswith("System.Collections.Generic.Dictionary`2[[System.UInt32"):
                short = type_name.split("],[", 1)[1].split(",", 1)[0]
                short = short.replace("WorldObjects.", "").replace("Service.", "")
                self.dicts[short] = pair["c"][1]
                self.pairs[short] = pair
        self.world = self.dicts["WorldObject+SaveData"]

    def objects(self):
        return {k: v for k, v, _ in T.dict_pairs(self.world)}

    def keys_of(self, short):
        node = self.dicts.get(short)
        return set() if node is None else {k for k, _, _ in T.dict_pairs(node)}

    def player_id(self):
        return next(iter(self.keys_of("Player.Player+SaveData")))

    def mission_ids(self):
        return self.keys_of("Mission.Mission+SaveData")


def asset_pos(obj):
    pos = T.field(obj, "position")["c"]
    return T.field(obj, "assetID")["v"], tuple(c["v"] for c in pos)


def inventory_id_to_type(doc, refs):
    """{inventoryID: InventoryType} for the special inventories."""
    inv_service = T.service(doc, "Service.Inventory.ServiceData")
    out = {}
    for inv_type, value, _ in T.dict_pairs(T.field(inv_service, "specialInventories")):
        node = refs[value["v"]] if value["t"] == "intref" else value
        out[T.field(node, "inventoryID")["v"]] = inv_type
    return out


def clone_demo(node, demo_refs):
    """Copy a demo subtree, replacing references to the outside with full copies."""
    out = T.clone(node)
    for parent in T.walk([out]):
        for i, c in enumerate(parent.get("c", [])):
            if c["t"] == "intref" and c["v"] >= 0:
                full = T.clone(demo_refs[c["v"]])
                if "n" in c:
                    full["n"] = c["n"]
                else:
                    full.pop("n", None)
                parent["c"][i] = full
    return out


# Full-game prefabs carrying the AutomatedCrafter component (not in the demo).
# Without saved data this component crashes the game while loading (its link to
# the Crafter is set in Awake, which has not run yet), so they get an empty queue.
AUTOMATED_CRAFTER_PREFABS = ("p_AutoFurnace", "p_BoberCarvingCrafter01", "p_FurnitureCrafter03",
                             "p_automaticElectroPress", "p_automaticSawhorse01")
AUTOMATED_TYPE = "WorldObjects.AutomatedCrafter+SaveData, Assembly-CSharp"
AUTOMATED_DICT = ("System.Collections.Generic.Dictionary`2[[System.UInt32, mscorlib],"
                  f"[{AUTOMATED_TYPE}]], mscorlib")
AUTOMATED_LIST = ("System.Collections.Generic.List`1[[WorldObjects.AutomatedCrafter+RecipeQueueEntry, "
                  "Assembly-CSharp]], mscorlib")


def ensure_automated_crafters(base, catalog_full, log):
    B = SaveView(base)
    ids = {a for a, n in catalog_full.items() if n in AUTOMATED_CRAFTER_PREFABS}
    objs = [k for k, o in B.objects().items() if T.field(o, "assetID")["v"] in ids]
    node = B.dicts.get("AutomatedCrafter+SaveData")
    have = set() if node is None else {k for k, _, _ in T.dict_pairs(node)}
    missing = [k for k in objs if k not in have]
    if not missing:
        return
    if node is None:
        # New dictionary, built from an existing dictionary of the base save.
        template = B.pairs["Spawner+SaveData"]
        pair = T.clone(template)
        pair["c"][0]["c"][0]["v"] = AUTOMATED_DICT
        pair["c"][1]["type"] = AUTOMATED_DICT
        T.set_array(T.array_of(pair["c"][1]), [])
        table = T.array_of(T.field(base["root"][0], "data"))
        table["c"].append(pair)
        table["len"] = len(table["c"])
        node = pair["c"][1]
    arr = T.array_of(node)
    for k in missing:
        arr["c"].append({"t": "struct", "type": None, "c": [
            {"t": "uint", "n": "$k", "v": k},
            T.fresh_ref(AUTOMATED_TYPE, [
                T.fresh_ref(AUTOMATED_LIST, [{"t": "array", "len": 0, "c": []}], name="recipeQueue"),
                {"t": "int", "n": "currentRecipeQueueIndex", "v": -1},
            ], name="$v"),
        ]})
    arr["len"] = len(arr["c"])
    log(f"World: empty crafting queue created for {len(missing)} automated machine(s)")


def transfer_world(demo, base, demo_refs, base_refs, catalog_demo, catalog_full,
                   scene_demo, scene_full, log, mission_children=None,
                   prefab_assets=frozenset(), skip_names=frozenset()):
    D, B = SaveView(demo), SaveView(base)
    d_objs, b_objs = D.objects(), B.objects()
    d_player, b_player = D.player_id(), B.player_id()
    d_skip = D.mission_ids() | {d_player}
    for short in SKIP_TYPES:
        d_skip |= D.keys_of(short)
    b_protect = B.mission_ids() | {b_player}

    # Matching against the initial maps.
    sd_to_sf = Matcher(scene_full).match_all({i: s for i, s in enumerate(scene_demo)})
    # Second, looser pass for objects the developers moved between versions.
    taken = set(sd_to_sf.values())
    rest_sf = [(i, s) for i, s in enumerate(scene_full) if i not in taken]
    moved_raw = Matcher([s for _, s in rest_sf], MOVED_TOLERANCE).match_all(
        {i: s for i, s in enumerate(scene_demo) if i not in sd_to_sf})
    moved = {sd: rest_sf[j][0] for sd, j in moved_raw.items()}  # demo index -> full index
    sf_to_sd = {sf: sd for sd, sf in sd_to_sf.items()}
    b_to_sf = Matcher(scene_full).match_all({k: asset_pos(o) for k, o in b_objs.items() if k not in b_protect})
    d_to_sd = Matcher(scene_demo).match_all({k: asset_pos(o) for k, o in d_objs.items() if k not in d_skip})
    sd_to_d = {sd: k for k, sd in d_to_sd.items()}

    # Moved objects: keep the full-game version, unless the player destroyed it in the demo.
    sf_destroyed_moved = {sf for sd, sf in moved.items() if sd not in sd_to_d}

    # 1. Base objects: updated in place, removed, or kept.
    # Scene objects have a fixed worldObjectID in each version and the game finds
    # them by that number, so the base number is kept and the demo state copied in.
    inplace = {}  # base id -> demo id
    drop = set()
    for k, o in b_objs.items():
        if k in b_protect:
            continue
        sf = b_to_sf.get(k)
        if sf is not None:
            if sf in sf_to_sd:
                dk = sd_to_d.get(sf_to_sd[sf])
                if dk is None:
                    drop.add(k)  # destroyed in the demo
                else:
                    inplace[k] = dk
            elif sf in sf_destroyed_moved:
                drop.add(k)
        elif T.field(o, "assetID")["v"] in catalog_demo:
            drop.add(k)  # spawned during play in the base save: the demo wins
    kept = {k: asset_pos(o) for k, o in b_objs.items()
            if k not in drop and k not in b_protect and k not in inplace}

    # 2. Demo objects that need a new number.
    add, ignored_changed, ignored_unknown, ignored_absent, dedup, kept_moved = [], 0, 0, 0, 0, 0
    absent_added = 0
    kept_matcher = Matcher(list(kept.values()))
    seen_dynamic = set()
    inplace_demo = set(inplace.values())
    for k, o in d_objs.items():
        if k in d_skip or k in inplace_demo:
            continue
        asset, pos = asset_pos(o)
        if asset not in catalog_full or catalog_full.get(asset) in skip_names:
            ignored_unknown += 1
            continue
        if k in d_to_sd:
            sd = d_to_sd[k]
            if sd in moved:
                kept_moved += 1
                continue
            if sd not in sd_to_sf:
                ignored_changed += 1
                continue
            # Scene object inactive at the start of the full game (cabin, workbench): the
            # base save does not contain it yet. The game recreates it from its prefab.
            if asset not in prefab_assets:
                ignored_absent += 1
                continue
            absent_added += 1
        sig = (asset, tuple(round(c, 1) for c in pos))
        if kept_matcher.match_all({0: (asset, pos)}) or sig in seen_dynamic:
            dedup += 1
            continue
        seen_dynamic.add(sig)
        add.append(k)

    log(f"World: {len(b_objs)} objects in the base save: {len(inplace)} set to their demo state, "
        f"{len(drop)} removed (destroyed in the demo), {len(kept)} kept as they are")
    log(f"World: {len(moved)} objects moved between versions, {len(sf_destroyed_moved)} of them "
        f"destroyed in the demo; {kept_moved} kept at their new spot")
    log(f"World: {len(add)} objects added (spawned during the demo, or inactive at the start of the "
        f"full game: {absent_added}), {dedup} duplicates avoided; ignored: {ignored_changed} removed "
        f"from the full game, {ignored_absent} without prefab, {ignored_unknown} unknown or excluded")

    # 3. Demo number -> final number.
    wo_service = T.service(base, "Service.WorldObject.ServiceData")
    current = T.field(wo_service, "currentID")
    idmap = {d_player: b_player}
    for bk, dk in inplace.items():
        idmap[dk] = bk
    for k in add:
        idmap[k] = current["v"]
        current["v"] += 1

    # 4. Inventories.
    b_special = inventory_id_to_type(base, base_refs)
    d_special = inventory_id_to_type(demo, demo_refs)
    b_special_by_type = {t: i for i, t in b_special.items()}
    inv_service = T.service(base, "Service.Inventory.ServiceData")
    inv_dict = T.field(inv_service, "inventories")
    b_inventories = {k: v for k, v, _ in T.dict_pairs(inv_dict)}
    d_inventories = {k: p for k, _, p in T.dict_pairs(
        T.field(T.service(demo, "Service.Inventory.ServiceData"), "inventories"))}
    next_inv = T.field(inv_service, "currentInventoryID")
    b_obj_inv = {}
    if "Inventory+SaveData" in B.dicts:
        b_obj_inv = {k: T.field(v, "inventoryID")["v"] for k, v, _ in T.dict_pairs(B.dicts["Inventory+SaveData"])}
    inv_count = 0

    def set_content(inv, old):
        content = clone_demo(T.field(d_inventories[old]["c"][1], "content"), demo_refs)
        items = [p for item, _, p in T.dict_pairs(content) if item in catalog_full]
        T.set_array(T.array_of(content), items)
        content["n"] = "content"
        idx = next(i for i, c in enumerate(inv["c"]) if c.get("n") == "content")
        inv["c"][idx] = content
        total = sum(T.field(p["c"][1], "amount")["v"] for p in items)
        try:
            T.field(inv, "totalAmount")["v"] = total
        except KeyError:
            pos = next(i for i, c in enumerate(inv["c"]) if c.get("n") == "inventoryID") + 1
            inv["c"].insert(pos, {"t": "int", "n": "totalAmount", "v": total})

    def map_inventory(old, base_obj):
        """Final inventory for demo inventory `old` of final object `base_obj`."""
        nonlocal inv_count
        if old in d_special and d_special[old] in b_special_by_type:
            return b_special_by_type[d_special[old]]
        inv_count += 1
        target = b_obj_inv.get(base_obj)
        if target is not None and target not in b_special and target in b_inventories:
            # Same inventory number as the base save, demo content.
            set_content(b_inventories[target], old)
            return target
        new = next_inv["v"]
        next_inv["v"] += 1
        pair = clone_demo(d_inventories[old], demo_refs)
        pair["c"][0]["v"] = new
        inv = pair["c"][1]
        T.field(inv, "inventoryID")["v"] = new
        set_content(inv, old)
        arr = T.array_of(inv_dict)
        arr["c"].append(pair)
        arr["len"] = len(arr["c"])
        return new

    # 5. Remove destroyed objects, their data and their non-special inventories.
    dropped_inventories = {b_obj_inv[k] for k in drop if k in b_obj_inv and b_obj_inv[k] not in b_special}
    for node in B.dicts.values():
        T.set_array(T.array_of(node), [p for k, _, p in T.dict_pairs(node) if k not in drop])
    T.set_array(T.array_of(inv_dict), [p for k, _, p in T.dict_pairs(inv_dict) if k not in dropped_inventories])

    # 6. Copy the demo data: objects updated in place and added objects.
    lost_refs = 0
    targets = {dk: bk for bk, dk in inplace.items()}
    targets.update({k: idmap[k] for k in add})
    b_world_index = {k: v for k, v, _ in T.dict_pairs(B.world)}
    for short, d_node in D.dicts.items():
        if short == "Mission.Mission+SaveData" or short in PLAYER_TYPES or short in SKIP_TYPES:
            continue
        pairs = [(k, p) for k, _, p in T.dict_pairs(d_node) if k in targets]
        if not pairs:
            continue
        b_node = B.dicts.get(short)
        if b_node is None:
            # Type missing from the base save: reuse the demo dictionary, emptied.
            table = T.array_of(T.field(base["root"][0], "data"))
            new_pair = clone_demo(D.pairs[short], demo_refs)
            T.set_array(T.array_of(new_pair["c"][1]), [])
            table["c"].append(new_pair)
            table["len"] = len(table["c"])
            b_node = new_pair["c"][1]
            B.dicts[short] = b_node
        arr = T.array_of(b_node)
        position = {k: i for i, (k, _, _) in enumerate(T.dict_pairs(b_node))}
        for k, p in pairs:
            final = targets[k]
            if short == "WorldObject+SaveData" and k in inplace_demo:
                # Scene object: keep the base entry, with the demo position and components.
                b_value = b_world_index[final]
                d_value = p["c"][1]
                for name in ("position", "rotation"):
                    for dst, src in zip(T.field(b_value, name)["c"], T.field(d_value, name)["c"]):
                        dst["v"] = src["v"]
                comps = T.field(b_value, "serializedComponents")
                codes = parray_values(comps, "i")
                codes += [c for c in parray_values(T.field(d_value, "serializedComponents"), "i") if c not in codes]
                set_parray(comps, codes, "i")
                continue
            new = clone_demo(p, demo_refs)
            new["c"][0]["v"] = final
            value = new["c"][1]
            if short == "WorldObject+SaveData":
                T.field(value, "worldObjectID")["v"] = final
                children = T.field(value, "childWorldObjects")
                old_children = parray_values(children)
                mapped = [idmap[c] for c in old_children if c in idmap]
                lost_refs += len(old_children) - len(mapped)
                set_parray(children, mapped)
            elif short == "Inventory+SaveData":
                f = T.field(value, "inventoryID")
                f["v"] = map_inventory(f["v"], final)
            elif short in ("Useables.Crafter+SaveData", "Useables.AutoInventoryCrafter+SaveData"):
                f = T.field(value, "inventoryWorldObject")
                if f["v"] in idmap:
                    f["v"] = idmap[f["v"]]
                else:
                    lost_refs += 1
                    f["v"] = final
            if final in position:
                arr["c"][position[final]] = new
            else:
                arr["c"].append(new)
        arr["len"] = len(arr["c"])

    # 7. Links from base objects to removed objects.
    for short in ("Useables.Crafter+SaveData", "Useables.AutoInventoryCrafter+SaveData"):
        node = B.dicts.get(short)
        if node is None:
            continue
        for k, value, _ in T.dict_pairs(node):
            f = T.field(value, "inventoryWorldObject")
            if f["v"] in drop:
                f["v"] = k
                lost_refs += 1
    for k, value, _ in T.dict_pairs(B.world):
        children = T.field(value, "childWorldObjects")
        old = parray_values(children)
        if any(c in drop for c in old):
            new = [c for c in old if c not in drop]
            lost_refs += len(old) - len(new)
            set_parray(children, new)

    # Child objects of the demo missions.
    if mission_children:
        objs_now = {k: v for k, v, _ in T.dict_pairs(B.world)}
        for mission_id, old in mission_children.items():
            mapped = [idmap[c] for c in old if c in idmap]
            lost_refs += len(old) - len(mapped)
            set_parray(T.field(objs_now[mission_id], "childWorldObjects"), mapped)

    if lost_refs:
        log(f"World: {lost_refs} links to objects that were not transferred removed or redirected")
    log(f"World: {inv_count} object inventories transferred")

    # 8. Player: demo position and view direction, everything else from the full game.
    b_obj = b_objs[b_player]
    d_obj = d_objs[d_player]
    for name in ("position", "rotation"):
        for dst, src in zip(T.field(b_obj, name)["c"], T.field(d_obj, name)["c"]):
            dst["v"] = src["v"]
    d_cam = {k: v for k, v, _ in T.dict_pairs(D.dicts["Player.FPSCamera+SaveData"])}[d_player]
    b_cam = {k: v for k, v, _ in T.dict_pairs(B.dicts["Player.FPSCamera+SaveData"])}[b_player]
    for name in ("upDownAngle", "leftRightAngle"):
        T.field(b_cam, name)["v"] = T.field(d_cam, name)["v"]
    log("Player: demo position and view direction")
    ensure_automated_crafters(base, catalog_full, log)
    return idmap
