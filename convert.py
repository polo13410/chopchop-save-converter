"""Transfère la progression d'une sauvegarde de la démo dans une sauvegarde du jeu complet.

Version 1 : progression seulement, le monde de la sauvegarde de base est gardé.

Ce qui est transféré :
- recettes débloquées et articles de la boutique (union démo + base) ;
- valeurs des audiences (TargetAudience) ;
- contenu des inventaires spéciaux : argent, sac du joueur, etc. ;
- tableau des missions et missions actives, avec l'état de leurs conditions.

Ce qui n'est pas transféré pour l'instant :
- les objets du monde (arbres coupés, constructions, téléporteurs réparés) ;
- la position et les statistiques du joueur.

Usage :
    python convert.py <demo.sav> <base_complet.sav> <sortie.sav> [--catalog-demo catalog/demo.csv]
"""

import argparse
import copy
import csv
import sys

import odin_binary
import odin_tree as T

MISSION_COMPONENT = 17


def load(path):
    with open(path, "rb") as f:
        return odin_binary.decode(f.read())


def load_catalog(path):
    with open(path, encoding="utf-8") as f:
        return {int(r["assetID"]): r["nom"] for r in csv.DictReader(f)}


def int_set(node):
    return [e["v"] for e in T.array_of(node)["c"]]


def set_ints(node, values, kind="int"):
    T.set_array(T.array_of(node), [{"t": kind, "v": v} for v in values])


def union_ordered(base, extra):
    seen = set(base)
    return base + [v for v in extra if v not in seen and not seen.add(v)]


class Report:
    def __init__(self):
        self.lines = []

    def __call__(self, msg):
        self.lines.append(msg)
        print(msg)


# --- services à identifiants stables -------------------------------------

def merge_hashset(demo, base, service_prefix, field_name, log):
    d = int_set(T.field(T.service(demo, service_prefix), field_name))
    node = T.field(T.service(base, service_prefix), field_name)
    b = int_set(node)
    merged = union_ordered(b, d)
    set_ints(node, merged)
    log(f"{service_prefix}.{field_name} : {len(b)} dans la base, {len(d)} dans la démo, {len(merged)} au total")


def copy_audiences(demo, base, log):
    src = {k: v for k, v, _ in T.dict_pairs(T.field(T.service(demo, "Service.TargetAudience.ServiceData"), "targetAudiences"))}
    n = 0
    for key, value, _ in T.dict_pairs(T.field(T.service(base, "Service.TargetAudience.ServiceData"), "targetAudiences")):
        if key in src:
            for name in ("value", "clampedValue"):
                T.field(value, name)["v"] = T.field(src[key], name)["v"]
            n += 1
    log(f"Audiences : {n} valeurs copiées")


def special_inventories(doc, refs):
    """{InventoryType: nœud Inventory} via le dictionnaire specialInventories."""
    inv_service = T.service(doc, "Service.Inventory.ServiceData")
    out = {}
    for key, value, _ in T.dict_pairs(T.field(inv_service, "specialInventories")):
        node = refs[value["v"]] if value["t"] == "intref" else value
        out[key] = node
    return out


def copy_inventories(demo, base, demo_refs, base_refs, catalog_full, log):
    src = special_inventories(demo, demo_refs)
    dst = special_inventories(base, base_refs)
    for inv_type in sorted(src):
        if inv_type not in dst:
            log(f"Inventaire spécial {inv_type} : absent du jeu complet, ignoré")
            continue
        items = [(k, T.field(v, "amount")["v"]) for k, v, _ in T.dict_pairs(T.field(src[inv_type], "content"))]
        unknown = [k for k, _ in items if k not in catalog_full]
        items = [(k, a) for k, a in items if k in catalog_full]
        content = T.field(dst[inv_type], "content")
        pairs = []
        for item, amount in items:
            pairs.append({"t": "struct", "type": None, "c": [
                {"t": "int", "n": "$k", "v": item},
                T.fresh_ref("Service.Inventory.Inventory+Content, Assembly-CSharp", [
                    {"t": "int", "n": "itemID", "v": item},
                    {"t": "int", "n": "amount", "v": amount},
                ], name="$v"),
            ]})
        T.set_array(T.array_of(content), pairs)
        try:
            T.field(dst[inv_type], "totalAmount")["v"] = sum(a for _, a in items)
        except KeyError:
            pass
        msg = f"Inventaire spécial {inv_type} : {len(items)} sortes d'objets copiées"
        if unknown:
            msg += f", {len(unknown)} inconnues du jeu complet ignorées"
        log(msg)


def clone_from_demo(node):
    """Copie un sous-arbre de la démo ; il ne doit pas renvoyer hors de lui-même."""
    out = T.clone(node)
    for e in T.walk([out]):
        if e["t"] == "intref" and e["v"] >= 0:
            raise ValueError("sous-arbre de la démo avec une référence externe, copie impossible")
    return out


# --- missions --------------------------------------------------------------

def world_dict(doc, suffix):
    return T.service(doc, f"[{suffix}, Assembly-CSharp]]")


def transfer_missions(demo, base, catalog_demo, log):
    d_world = world_dict(demo, "WorldObjects.WorldObject+SaveData")
    b_world = world_dict(base, "WorldObjects.WorldObject+SaveData")
    d_missions = world_dict(demo, "Service.Mission.Mission+SaveData")
    b_missions = world_dict(base, "Service.Mission.Mission+SaveData")

    d_obj = {k: v for k, v, _ in T.dict_pairs(d_world)}
    b_obj = {k: v for k, v, _ in T.dict_pairs(b_world)}

    def asset(obj):
        return T.field(obj, "assetID")["v"]

    # 1. Retirer de la base les missions que la démo connaît : son état fait foi.
    removed = set()
    keep = []
    base_checks = {}  # assetID -> nœud Mission+SaveData de la base
    for key, value, pair in T.dict_pairs(b_missions):
        base_checks[asset(b_obj[key])] = value
        if asset(b_obj[key]) in catalog_demo:
            removed.add(key)
        else:
            keep.append(pair)
    T.set_array(T.array_of(b_missions), keep)
    T.set_array(T.array_of(b_world), [p for k, _, p in T.dict_pairs(b_world) if k not in removed])
    log(f"Missions : {len(removed)} retirées de la base, {len(keep)} propres au jeu complet gardées")

    # 2. Ajouter les missions de la démo avec de nouveaux worldObjectID.
    wo_service = T.service(base, "Service.WorldObject.ServiceData")
    current = T.field(wo_service, "currentID")
    remap = {}
    reset = 0
    world_pairs = T.array_of(b_world)["c"]
    mission_pairs = T.array_of(b_missions)["c"]
    for key, value, pair in T.dict_pairs(d_missions):
        obj = d_obj[key]
        new_id = current["v"]
        current["v"] += 1
        remap[key] = new_id

        obj_pair = clone_from_demo(next(p for k, _, p in T.dict_pairs(d_world) if k == key))
        obj_pair["c"][0]["v"] = new_id
        new_obj = obj_pair["c"][1]
        T.field(new_obj, "worldObjectID")["v"] = new_id
        comps = T.field(new_obj, "serializedComponents")["c"][0]
        comps["count"], comps["hex"] = 1, MISSION_COMPONENT.to_bytes(4, "little").hex()
        world_pairs.append(obj_pair)

        m_pair = clone_from_demo(pair)
        m_pair["c"][0]["v"] = new_id
        # Si les conditions ont changé entre les versions, on repart de celles du jeu complet.
        template = base_checks.get(asset(obj))
        if template is not None and check_ids(template) != check_ids(value):
            fresh = T.clone(template)
            fresh["n"] = "$v"
            m_pair["c"][1] = fresh
            reset += 1
        mission_pairs.append(m_pair)
    T.array_of(b_world)["len"] = len(world_pairs)
    T.array_of(b_missions)["len"] = len(mission_pairs)
    log(f"Missions : {len(remap)} missions de la démo ajoutées, "
        f"dont {reset} avec les conditions du jeu complet (remises à zéro)")

    # 3. Tableau des missions.
    d_board = T.service(demo, "Service.MissionBoard.ServiceData")
    b_board = T.service(base, "Service.MissionBoard.ServiceData")
    for name in ("unlockedMissionIDs", "availableMissionIDs"):
        set_ints(T.field(b_board, name), int_set(T.field(d_board, name)))
    running = [remap[k] for k in int_set(T.field(d_board, "runningMissions")) if k in remap]
    set_ints(T.field(b_board, "runningMissions"), running, kind="uint")
    log(f"Tableau des missions : {len(int_set(T.field(d_board, 'unlockedMissionIDs')))} débloquées, "
        f"{len(running)} en cours")
    return remap


def check_ids(mission_value):
    return [T.field(c, "_id")["v"] for c in T.array_of(T.field(mission_value, "checksSavedata"))["c"]]


def check_mission_compat(demo, base_original, log, catalog_full):
    """Signale les missions dont les conditions diffèrent entre la démo et la base."""
    def checks(doc):
        world = {k: T.field(v, "assetID")["v"] for k, v, _ in T.dict_pairs(world_dict(doc, "WorldObjects.WorldObject+SaveData"))}
        out = {}
        for k, v, _ in T.dict_pairs(world_dict(doc, "Service.Mission.Mission+SaveData")):
            ids = [T.field(c, "_id")["v"] for c in T.array_of(T.field(v, "checksSavedata"))["c"]]
            out[world[k]] = ids
        return out
    d, b = checks(demo), checks(base_original)
    diff = [a for a in d if a in b and d[a] != b[a]]
    unseen = [a for a in d if a not in b]
    for a in diff:
        log(f"  Attention : conditions différentes pour {catalog_full.get(a, a)}")
    if unseen:
        log(f"  {len(unseen)} missions de la démo absentes de la base, conditions non vérifiables")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("demo")
    p.add_argument("base")
    p.add_argument("output")
    p.add_argument("--catalog-demo", default="catalog/demo.csv")
    p.add_argument("--catalog-full", default="catalog/complet.csv")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    log = Report()
    demo, base = load(args.demo), load(args.base)
    base_original = copy.deepcopy(base)
    catalog_demo = load_catalog(args.catalog_demo)
    catalog_full = load_catalog(args.catalog_full)
    demo_refs = T.index_refs(demo)
    base_refs = T.index_refs(base)
    originals = copy.deepcopy(base_refs)

    merge_hashset(demo, base, "Service.Recipe.ServiceData", "unlockedRecipes", log)
    merge_hashset(demo, base, "Service.Shop.ServiceData", "unlockedItems", log)
    copy_audiences(demo, base, log)
    copy_inventories(demo, base, demo_refs, base_refs, catalog_full, log)
    check_mission_compat(demo, base_original, log, catalog_full)
    transfer_missions(demo, base, catalog_demo, log)

    T.renumber(base, originals)
    data = odin_binary.encode(base)
    # Vérification : le fichier produit doit se relire.
    odin_binary.decode(data)
    with open(args.output, "wb") as f:
        f.write(data)
    log(f"Écrit : {args.output} ({len(data)} octets)")


if __name__ == "__main__":
    main()
