"""Applique à la sauvegarde convertie ce que le jeu complet a ajouté aux missions.

S'appuie sur mission_graph.py pour savoir quelles missions la démo a exécutées,
puis compare leurs actions entre la démo et le jeu complet (par assetID, car
certaines missions ont seulement été renommées). Les actions ajoutées par le
jeu complet sont appliquées : missions à démarrer, recettes à débloquer.
"""

import struct

import mission_graph as G
import odin_tree as T
import world as W

CHECK_EXTRA_FIELDS = {
    "MissionCheck_Collect": [("currentCount", "int", 0)],
    "MissionCheck_DespawnedWorldObject": [("currentCount", "int", 0)],
    "MissionCheck_SpawnedWorldObject": [("currentCount", "int", 0)],
    "MissionCheck_Input": [("buttonOnce", "bool", False), ("axisOnce", "bool", False)],
    "MissionCheck_InventoryAmount": [("wasSolvedLastFrame", "bool", False)],
    "MissionCheck_InventoryAmountRange": [("wasSolvedLastFrame", "bool", False)],
    "MissionCheck_InventoryTotalAmount": [("wasSolvedLastFrame", "bool", False)],
    "MissionCheck_InventoryTotalWorth": [("wasSolvedLastFrame", "bool", False)],
    "MissionCheck_ShopItemUnlocked": [("wasSolvedLastFrame", "bool", False)],
    "MissionCheck_TargetAudiencePercentage": [("wasSolvedLastFrame", "bool", False)],
    "MissionCheck_TargetAudienceValue": [("wasSolvedLastFrame", "bool", False)],
    "MissionCheck_ShopOrder": [("currentOrderAmount", "int", 0)],
    "MissionCheck_Timer": [("currentTimer", "float", 0.0)],
}
WO_TYPE = "WorldObjects.WorldObject+SaveData, Assembly-CSharp"
VEC3 = "UnityEngine.Vector3, UnityEngine.CoreModule"
QUAT = "UnityEngine.Quaternion, UnityEngine.CoreModule"
MISSION_COMPONENT = 17


def _vec(name, type_name, values):
    return {"t": "struct", "n": name, "type": type_name, "c": [{"t": "float", "v": v} for v in values]}


def new_world_object(world_id, asset_id, components=(), position=(0.0, 0.0, 0.0)):
    """Paire de dictionnaire pour un nouvel objet du monde."""
    comps = list(components)
    return {"t": "struct", "type": None, "c": [
        {"t": "uint", "n": "$k", "v": world_id},
        T.fresh_ref(WO_TYPE, [
            {"t": "int", "n": "assetID", "v": asset_id},
            {"t": "uint", "n": "worldObjectID", "v": world_id},
            _vec("position", VEC3, position),
            _vec("rotation", QUAT, (0.0, 0.0, 0.0, 1.0)),
            _vec("scale", VEC3, (1.0, 1.0, 1.0)),
            _vec("linearVelocity", VEC3, (0.0, 0.0, 0.0)),
            _vec("angularVelocity", VEC3, (0.0, 0.0, 0.0)),
            T.fresh_ref("System.Int32[], mscorlib", [{"t": "parray", "count": len(comps), "size": 4,
                                                      "hex": struct.pack(f"<{len(comps)}i", *comps).hex()}],
                        name="serializedComponents"),
            T.fresh_ref("System.UInt32[], mscorlib", [{"t": "parray", "count": 0, "size": 4, "hex": ""}],
                        name="childWorldObjects"),
        ], name="$v"),
    ]}


def new_mission_data(world_id, checks):
    items = []
    for cls, check_id in checks:
        fields = [{"t": "ulong", "n": "_id", "v": check_id}, {"t": "bool", "n": "_isSolved", "v": False}]
        fields += [{"t": kind, "n": n, "v": v} for n, kind, v in CHECK_EXTRA_FIELDS.get(cls, [])]
        items.append(T.fresh_ref(f"Service.Mission.MissionChecks.{cls}+SaveData, Assembly-CSharp", fields))
    return {"t": "struct", "type": None, "c": [
        {"t": "uint", "n": "$k", "v": world_id},
        T.fresh_ref("Service.Mission.Mission+SaveData, Assembly-CSharp", [
            T.fresh_ref("Service.Mission.MissionChecks.IMissionCheckSaveData[], Assembly-CSharp",
                        [{"t": "array", "len": len(items), "c": items}], name="checksSavedata"),
        ], name="$v"),
    ]}


def _reverse(catalog):
    out = {}
    for asset, name in catalog.items():
        out.setdefault(name, asset)
    return out


def demo_progress(demo, catalog_demo, missions_demo):
    D = W.SaveView(demo)
    d_objs = D.objects()
    active = {catalog_demo.get(T.field(d_objs[k], "assetID")["v"]) for k in D.mission_ids()}

    def names(svc, field):
        return {catalog_demo.get(e["v"]) for e in T.array_of(T.field(T.service(demo, svc), field))["c"]}
    return G.infer_progress(
        missions_demo, active,
        names("Service.Recipe.ServiceData", "unlockedRecipes"),
        names("Service.MissionBoard.ServiceData", "unlockedMissionIDs"),
        names("Service.Shop.ServiceData", "unlockedItems"),
        {catalog_demo.get(T.field(o, "assetID")["v"]) for o in d_objs.values()})


def apply_full_additions(base, catalog_demo, catalog_full, missions_demo, missions_full,
                         started, completed, log, skip_missions=()):
    ids_full, ids_demo = _reverse(catalog_full), _reverse(catalog_demo)

    def key(group, cls, target, ids):
        return group, cls, (ids.get(target, target) if target else None)

    added = []
    for name in sorted(started):
        if name not in missions_full or name not in missions_demo:
            continue
        groups = ["StartActions"] + (["SuccessActions"] if name in completed else [])
        demo_keys = {key(*a, ids_demo) for a in missions_demo[name]["actions"]}
        positions = missions_full[name].get("spawn_positions", {})
        for i, (group, cls, target) in enumerate(missions_full[name]["actions"]):
            if group in groups and key(group, cls, target, ids_full) not in demo_keys:
                added.append((name, group, cls, target, positions.get(str(i))))

    B = W.SaveView(base)
    b_objs = B.objects()
    present = {T.field(b_objs[k], "assetID")["v"] for k in B.mission_ids()}
    known_done = {ids_demo.get(n) for n in completed}
    current = T.field(T.service(base, "Service.WorldObject.ServiceData"), "currentID")
    world_arr = T.array_of(B.world)
    mission_arr = T.array_of(B.dicts["Mission.Mission+SaveData"])

    present_assets = {T.field(o, "assetID")["v"] for o in b_objs.values()}
    started_new, recipes_new, skipped_spawn, spawned = [], [], [], []

    def spawn(target, position):
        asset = ids_full.get(target)
        if asset is None or position is None:
            skipped_spawn.append(target)
            return
        if asset in present_assets:
            return
        wid = current["v"]
        current["v"] += 1
        world_arr["c"].append(new_world_object(wid, asset, position=tuple(position)))
        present_assets.add(asset)
        spawned.append(target)

    def start(target):
        """Insère une mission démarrée et applique ses actions de démarrage, que le jeu
        n'exécute pas pour une mission chargée depuis une sauvegarde."""
        asset = ids_full.get(target)
        if (asset is None or target in skip_missions or asset in present or asset in known_done
                or target not in missions_full):
            return
        wid = current["v"]
        current["v"] += 1
        world_arr["c"].append(new_world_object(wid, asset, [MISSION_COMPONENT]))
        mission_arr["c"].append(new_mission_data(wid, missions_full[target]["checks"]))
        present.add(asset)
        started_new.append(target)
        positions = missions_full[target].get("spawn_positions", {})
        for i, (group, cls, child) in enumerate(missions_full[target]["actions"]):
            if group == "StartActions":
                apply(cls, child, positions.get(str(i)))

    def apply(cls, target, position):
        if cls == "MissionAction_StartMission":
            start(target)
        elif cls == "MissionAction_UnLockRecipe":
            asset = ids_full.get(target)
            if asset is not None:
                recipes_new.append(asset)
        elif cls == "MissionAction_SpawnObject":
            spawn(target, position)

    for source, group, cls, target, position in added:
        # Les objets créés au démarrage d'une mission déjà finie dans la démo sont souvent
        # temporaires (sons, déclencheurs) : on ne garde que les récompenses de fin de mission.
        if cls == "MissionAction_SpawnObject" and group != "SuccessActions":
            continue
        apply(cls, target, position)
    world_arr["len"] = len(world_arr["c"])
    mission_arr["len"] = len(mission_arr["c"])

    if recipes_new:
        node = T.array_of(T.field(T.service(base, "Service.Recipe.ServiceData"), "unlockedRecipes"))
        have = {e["v"] for e in node["c"]}
        for r in recipes_new:
            if r not in have:
                node["c"].append({"t": "int", "v": r})
                have.add(r)
        node["len"] = len(node["c"])

    log(f"Missions du jeu complet : {len(started)} missions exécutées dans la démo, "
        f"{len(started_new)} missions ajoutées par le jeu complet démarrées")
    for m in started_new:
        log(f"  + {m}")
    if recipes_new:
        log(f"Recettes ajoutées par le jeu complet : {len(recipes_new)}")
    if spawned:
        log("Objets de récompense ajoutés par le jeu complet : " + ", ".join(spawned))
    if skipped_spawn:
        log("Objets de récompense du jeu complet non créés (position inconnue) : "
            + ", ".join(sorted(set(skipped_spawn))))


def ensure_tutorial_marker(base, catalog_full, started, log):
    """Le jeu complet crée p_tutorialPlayed à la fin du tutoriel ; certaines missions l'attendent."""
    if "Mission_Board_InitialSetup" not in started:
        return
    ids = {n: a for a, n in catalog_full.items() if n in ("p_tutorialPlayed", "p_tutorialSkipped")}
    B = W.SaveView(base)
    if any(T.field(o, "assetID")["v"] in ids.values() for o in B.objects().values()):
        return
    current = T.field(T.service(base, "Service.WorldObject.ServiceData"), "currentID")
    arr = T.array_of(B.world)
    arr["c"].append(new_world_object(current["v"], ids["p_tutorialPlayed"]))
    arr["len"] = len(arr["c"])
    current["v"] += 1
    log("Tutoriel : marqueur de fin de tutoriel ajouté (la démo l'a terminé)")
