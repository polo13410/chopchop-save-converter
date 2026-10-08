"""Transfert des objets du monde de la démo vers une sauvegarde du jeu complet.

Les numéros d'objets (worldObjectID) diffèrent entre les versions. Dans une
même version, les objets placés dans les scènes ont un numéro fixe : le jeu les
retrouve par ce numéro au chargement, il ne faut donc jamais les renuméroter.
On reconnaît les objets d'une version à l'autre par leur type et leur position,
en s'appuyant sur l'état initial des cartes extrait des scènes
(extract_scene.py) pour les deux versions.

Règles, pour chaque objet (hors missions et joueur, traités à part) :

Objets de la base (jeu complet) :
- présent sur la carte du jeu complet ET sur celle de la démo : garde son
  numéro et prend l'état de la démo, ou est retiré s'il a été détruit dans la
  démo (arbre coupé...) ;
- présent seulement sur la carte du jeu complet : gardé (nouveau contenu) ;
- apparu en jeu (sur aucune carte) : retiré si la démo connaît son type,
  gardé sinon.

Objets de la démo :
- présent sur la carte de la démo et sur celle du jeu complet : fusionné dans
  l'objet correspondant de la base (voir ci-dessus) ;
- présent sur la carte de la démo mais plus sur celle du jeu complet : ignoré,
  le jeu complet a changé cet endroit ;
- apparu en jeu (construction, objet lâché, animal) : ajouté, sauf doublon
  avec un objet gardé de la base au même endroit.
"""

import csv
import math
import struct
from collections import defaultdict

import odin_tree as T

TOLERANCE = 0.5  # mètres
MOVED_TOLERANCE = 3.0  # objets déplacés par les développeurs entre les versions

SKIP_TYPES = ("Drone.DeliveryDrone+SaveData", "Truck.Truck+SaveData")
PLAYER_TYPES = ("Player.Player+SaveData", "Player.PlayerStats+SaveData",
                "Player.CurrentItem+SaveData", "Player.FPSCamera+SaveData",
                "Player.PlayerRespawn+SaveData")


def load_scene(path):
    with open(path, encoding="utf-8") as f:
        return [(int(r["assetID"]), (float(r["x"]), float(r["y"]), float(r["z"])))
                for r in csv.DictReader(f) if r["flag"] == "1"]


class Matcher:
    """Apparie des objets (assetID, position) à une liste de référence, sans réutilisation."""

    def __init__(self, reference, tolerance=TOLERANCE):
        self.tolerance = tolerance
        self.by_asset = defaultdict(list)
        for i, (asset, pos) in enumerate(reference):
            self.by_asset[asset].append((i, pos))

    def match_all(self, items):
        """items : {clé: (assetID, position)} -> {clé: index de référence}.

        Les paires les plus proches sont attribuées en premier.
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
    """Accès pratique aux dictionnaires d'objets d'une sauvegarde."""

    def __init__(self, doc):
        self.doc = doc
        self.dicts = {}  # nom court du type -> nœud Dictionary
        self.pairs = {}  # nom court du type -> paire de la table des services
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
    """{inventoryID: InventoryType} pour les inventaires spéciaux."""
    inv_service = T.service(doc, "Service.Inventory.ServiceData")
    out = {}
    for inv_type, value, _ in T.dict_pairs(T.field(inv_service, "specialInventories")):
        node = refs[value["v"]] if value["t"] == "intref" else value
        out[T.field(node, "inventoryID")["v"]] = inv_type
    return out


def clone_demo(node, demo_refs):
    """Copie un sous-arbre de la démo en remplaçant ses références externes par des copies."""
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


# Prefabs du jeu complet qui portent le composant AutomatedCrafter (absent de la démo).
# Sans données sauvegardées, ce composant plante au chargement (son lien vers le
# Crafter n'est pas encore initialisé) : on leur donne une file de fabrication vide.
AUTOMATED_CRAFTER_PREFABS = ("p_AutoFurnace", "p_BoberCarvingCrafter01", "p_FurnitureCrafter03",
                             "p_automaticElectroPress", "p_automaticSawhorse01")
AUTOMATED_TYPE = "WorldObjects.AutomatedCrafter+SaveData, Assembly-CSharp"
AUTOMATED_DICT = ("System.Collections.Generic.Dictionary`2[[System.UInt32, mscorlib],"
                  f"[{AUTOMATED_TYPE}]], mscorlib")
AUTOMATED_LIST = ("System.Collections.Generic.List`1[[WorldObjects.AutomatedCrafter+RecipeQueueEntry, "
                  "Assembly-CSharp]], mscorlib")


def ensure_automated_crafters(base, catalog_names, log):
    B = SaveView(base)
    ids = {a for a, n in catalog_names.items() if n in AUTOMATED_CRAFTER_PREFABS}
    objs = [k for k, o in B.objects().items() if T.field(o, "assetID")["v"] in ids]
    node = B.dicts.get("AutomatedCrafter+SaveData")
    have = set() if node is None else {k for k, _, _ in T.dict_pairs(node)}
    missing = [k for k in objs if k not in have]
    if not missing:
        return
    if node is None:
        # Nouveau dictionnaire, construit sur le modèle d'un dictionnaire existant de la base.
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
    log(f"Monde : file de fabrication vide créée pour {len(missing)} machine(s) automatisée(s)")


def transfer_world(demo, base, demo_refs, base_refs, catalog_demo, catalog_full,
                   scene_demo, scene_full, log, mission_children=None, catalog_names=None,
                   prefab_assets=frozenset(), skip_names=frozenset()):
    D, B = SaveView(demo), SaveView(base)
    d_objs, b_objs = D.objects(), B.objects()
    d_player, b_player = D.player_id(), B.player_id()
    d_skip = D.mission_ids() | {d_player}
    for short in SKIP_TYPES:
        d_skip |= D.keys_of(short)
    b_protect = B.mission_ids() | {b_player}

    # Appariements avec les cartes initiales.
    sd_to_sf = Matcher(scene_full).match_all({i: s for i, s in enumerate(scene_demo)})
    # Second passage, plus large, pour les objets déplacés entre les versions.
    taken = set(sd_to_sf.values())
    rest_sf = [(i, s) for i, s in enumerate(scene_full) if i not in taken]
    moved_raw = Matcher([s for _, s in rest_sf], MOVED_TOLERANCE).match_all(
        {i: s for i, s in enumerate(scene_demo) if i not in sd_to_sf})
    moved = {sd: rest_sf[j][0] for sd, j in moved_raw.items()}  # index démo -> index complet
    sf_to_sd = {sf: sd for sd, sf in sd_to_sf.items()}
    b_to_sf = Matcher(scene_full).match_all({k: asset_pos(o) for k, o in b_objs.items() if k not in b_protect})
    d_to_sd = Matcher(scene_demo).match_all({k: asset_pos(o) for k, o in d_objs.items() if k not in d_skip})
    sd_to_d = {sd: k for k, sd in d_to_sd.items()}

    # Objets déplacés : on garde la version du jeu complet, sauf si le joueur l'a détruite dans la démo.
    sf_destroyed_moved = {sf for sd, sf in moved.items() if sd not in sd_to_d}

    # 1. Objets de la base : mis à jour sur place, retirés, ou gardés.
    # Les objets des scènes ont un worldObjectID fixe dans chaque version : le jeu les
    # retrouve par ce numéro. On garde donc le numéro de la base et on y met l'état de la démo.
    inplace = {}  # id base -> id démo
    drop = set()
    for k, o in b_objs.items():
        if k in b_protect:
            continue
        sf = b_to_sf.get(k)
        if sf is not None:
            if sf in sf_to_sd:
                dk = sd_to_d.get(sf_to_sd[sf])
                if dk is None:
                    drop.add(k)  # détruit dans la démo
                else:
                    inplace[k] = dk
            elif sf in sf_destroyed_moved:
                drop.add(k)
        elif T.field(o, "assetID")["v"] in catalog_demo:
            drop.add(k)  # apparu en jeu dans la base : la démo fait foi
    kept = {k: asset_pos(o) for k, o in b_objs.items()
            if k not in drop and k not in b_protect and k not in inplace}

    # 2. Objets apparus en jeu dans la démo : ajoutés avec un nouveau numéro.
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
            # Objet de scène inactif au début du jeu complet (ex. cabane, établi) : la base ne le
            # sauvegarde pas encore. Le jeu le recrée depuis son prefab, comme un objet apparu en jeu.
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

    log(f"Monde : {len(b_objs)} objets dans la base : {len(inplace)} mis à l'état de la démo, "
        f"{len(drop)} retirés (détruits dans la démo), {len(kept)} gardés tels quels")
    log(f"Monde : {len(moved)} objets déplacés entre les versions, dont {len(sf_destroyed_moved)} "
        f"détruits dans la démo ; {kept_moved} gardés à leur nouvelle place")
    log(f"Monde : {len(add)} objets ajoutés (apparus pendant la démo, ou inactifs au début du jeu complet : "
        f"{absent_added}), {dedup} doublons évités ; ignorés : {ignored_changed} retirés du jeu complet, "
        f"{ignored_absent} sans prefab, {ignored_unknown} inconnus ou exclus")

    # 3. Table de correspondance des numéros démo -> final.
    wo_service = T.service(base, "Service.WorldObject.ServiceData")
    current = T.field(wo_service, "currentID")
    idmap = {d_player: b_player}
    for bk, dk in inplace.items():
        idmap[dk] = bk
    for k in add:
        idmap[k] = current["v"]
        current["v"] += 1

    # 4. Inventaires.
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
        """Inventaire final pour l'inventaire démo `old` de l'objet final `base_obj`."""
        nonlocal inv_count
        if old in d_special and d_special[old] in b_special_by_type:
            return b_special_by_type[d_special[old]]
        inv_count += 1
        target = b_obj_inv.get(base_obj)
        if target is not None and target not in b_special and target in b_inventories:
            # Même numéro d'inventaire que la base, contenu de la démo.
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

    # 5. Retirer les objets détruits, leurs données et leurs inventaires non spéciaux.
    dropped_inventories = {b_obj_inv[k] for k in drop if k in b_obj_inv and b_obj_inv[k] not in b_special}
    for node in B.dicts.values():
        T.set_array(T.array_of(node), [p for k, _, p in T.dict_pairs(node) if k not in drop])
    T.set_array(T.array_of(inv_dict), [p for k, _, p in T.dict_pairs(inv_dict) if k not in dropped_inventories])

    # 6. Copier les données de la démo : objets mis à jour sur place et objets ajoutés.
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
            # Type absent de la base : on reprend le dictionnaire de la démo, vidé.
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
                # Objet de scène : on garde l'entrée de la base, avec la position et les composants de la démo.
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

    # 7. Liens des objets de la base vers des objets retirés.
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

    # Objets enfants des missions de la démo.
    if mission_children:
        objs_now = {k: v for k, v, _ in T.dict_pairs(B.world)}
        for mission_id, old in mission_children.items():
            mapped = [idmap[c] for c in old if c in idmap]
            lost_refs += len(old) - len(mapped)
            set_parray(T.field(objs_now[mission_id], "childWorldObjects"), mapped)

    if lost_refs:
        log(f"Monde : {lost_refs} liens vers des objets non transférés retirés ou redirigés")
    log(f"Monde : {inv_count} inventaires d'objets transférés")

    # 8. Joueur : position et regard de la démo, le reste vient du jeu complet.
    b_obj = b_objs[b_player]
    d_obj = d_objs[d_player]
    for name in ("position", "rotation"):
        for dst, src in zip(T.field(b_obj, name)["c"], T.field(d_obj, name)["c"]):
            dst["v"] = src["v"]
    d_cam = {k: v for k, v, _ in T.dict_pairs(D.dicts["Player.FPSCamera+SaveData"])}[d_player]
    b_cam = {k: v for k, v, _ in T.dict_pairs(B.dicts["Player.FPSCamera+SaveData"])}[b_player]
    for name in ("upDownAngle", "leftRightAngle"):
        T.field(b_cam, name)["v"] = T.field(d_cam, name)["v"]
    log("Joueur : position et orientation de la démo")
    ensure_automated_crafters(base, catalog_names, log)
    return idmap
