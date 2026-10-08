"""Missions: transfer from the demo, progress inference, and full-game additions.

In Chop Chop Inc. an active mission is an invisible world object (at the
origin, carrying only the mission component) plus an entry holding the state of
its checks. A finished mission simply disappears. The mission board keeps
unlocked / available missions by assetID and running missions by worldObjectID.

Three steps:

1. transfer_missions: the active demo missions replace the base ones the demo
   knows about. Missions only the full game knows are kept.

2. infer_progress: which demo missions were started / completed. Completed
   missions leave no trace of their own, so this is a fixed point over their
   visible effects in the save: active missions, unlocked recipes, unlocked
   board missions, unlocked shop items, spawned objects, missions started next.
   An effect only counts if a single mission can produce it, and a mission
   without checks completes as soon as it starts.

3. apply_full_additions: the full game added actions to missions that already
   existed in the demo. For example Mission_Board_InitialSetup starts 16
   missions instead of 7. If the demo ran such a mission, the added actions
   would never happen, so they are applied: missions to start (with their own
   start actions, which the game does not run for a mission loaded from a
   save), recipes to unlock, reward objects at their spawn point.

4. apply_trigger_additions: the same for zone triggers (objects that act when
   the player walks into them, then destroy themselves) the demo already fired.
"""

import json
import math
import struct
from collections import defaultdict

from . import odin_tree as T
from . import world as W

START, SUCCESS = "StartActions", "SuccessActions"
MISSION_COMPONENT = 17

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


def load_definitions(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _world_dict(doc, suffix):
    return T.service(doc, f"[{suffix}, Assembly-CSharp]]")


def _asset(obj):
    return T.field(obj, "assetID")["v"]


def _ints(node):
    return [e["v"] for e in T.array_of(node)["c"]]


def _set_ints(node, values, kind="int"):
    T.set_array(T.array_of(node), [{"t": kind, "v": v} for v in values])


def check_ids(mission_value):
    return [T.field(c, "_id")["v"] for c in T.array_of(T.field(mission_value, "checksSavedata"))["c"]]


def _clone_self_contained(node):
    """Copy a demo subtree that must not reference anything outside itself."""
    out = T.clone(node)
    for e in T.walk([out]):
        if e["t"] == "intref" and e["v"] >= 0:
            raise ValueError("demo subtree references something outside itself, cannot copy it")
    return out


# --- 1. transfer -----------------------------------------------------------------

def report_check_differences(demo, base, catalog_full, log):
    """Log the missions whose checks differ between the demo and the base save."""
    def checks(doc):
        objs = {k: _asset(v) for k, v, _ in T.dict_pairs(_world_dict(doc, "WorldObjects.WorldObject+SaveData"))}
        return {objs[k]: check_ids(v) for k, v, _ in T.dict_pairs(_world_dict(doc, "Service.Mission.Mission+SaveData"))}
    d, b = checks(demo), checks(base)
    for a in d:
        if a in b and d[a] != b[a]:
            log(f"  Note: checks changed for {catalog_full.get(a, a)}")
    unseen = [a for a in d if a not in b]
    if unseen:
        log(f"  {len(unseen)} demo missions are not in the base save, their checks cannot be compared")


def transfer_missions(demo, base, catalog_demo, catalog_full, log,
                      keep_base=frozenset(), skip_demo=frozenset()):
    """Replace the base missions known to the demo with the active demo missions.

    Returns {new mission id: [demo child object ids]}: missions can own objects
    (a beehive...), renumbered later by world.transfer_world.
    """
    d_world = _world_dict(demo, "WorldObjects.WorldObject+SaveData")
    b_world = _world_dict(base, "WorldObjects.WorldObject+SaveData")
    d_missions = _world_dict(demo, "Service.Mission.Mission+SaveData")
    b_missions = _world_dict(base, "Service.Mission.Mission+SaveData")
    d_obj = {k: v for k, v, _ in T.dict_pairs(d_world)}
    b_obj = {k: v for k, v, _ in T.dict_pairs(b_world)}

    # Remove the base missions the demo knows about: the demo state wins.
    removed, keep, base_checks = set(), [], {}
    for key, value, pair in T.dict_pairs(b_missions):
        asset = _asset(b_obj[key])
        base_checks[asset] = value
        if asset in catalog_demo and catalog_full.get(asset) not in keep_base:
            removed.add(key)
        else:
            keep.append(pair)
    T.set_array(T.array_of(b_missions), keep)
    T.set_array(T.array_of(b_world), [p for k, _, p in T.dict_pairs(b_world) if k not in removed])
    log(f"Missions: {len(removed)} removed from the base save, {len(keep)} full-game-only missions kept")

    # Add the demo missions with new worldObjectIDs.
    current = T.field(T.service(base, "Service.WorldObject.ServiceData"), "currentID")
    remap, mission_children = {}, {}
    reset = skipped = 0
    world_pairs = T.array_of(b_world)["c"]
    mission_pairs = T.array_of(b_missions)["c"]
    d_world_pairs = {k: p for k, _, p in T.dict_pairs(d_world)}
    for key, value, pair in T.dict_pairs(d_missions):
        obj = d_obj[key]
        name = catalog_full.get(_asset(obj))
        if name is None or name in skip_demo or name in keep_base:
            skipped += 1  # end-of-demo sign, relocated content...
            continue
        new_id = current["v"]
        current["v"] += 1
        remap[key] = new_id

        obj_pair = _clone_self_contained(d_world_pairs[key])
        obj_pair["c"][0]["v"] = new_id
        new_obj = obj_pair["c"][1]
        T.field(new_obj, "worldObjectID")["v"] = new_id
        # Child objects are renumbered by world.py; until then the list is emptied
        # so it never points at the wrong objects.
        children = T.field(new_obj, "childWorldObjects")
        mission_children[new_id] = W.parray_values(children)
        W.set_parray(children, [])
        W.set_parray(T.field(new_obj, "serializedComponents"), [MISSION_COMPONENT], "i")
        world_pairs.append(obj_pair)

        m_pair = _clone_self_contained(pair)
        m_pair["c"][0]["v"] = new_id
        # If the checks changed between versions, start over from the full-game ones.
        template = base_checks.get(_asset(obj))
        if template is not None and check_ids(template) != check_ids(value):
            fresh = T.clone(template)
            fresh["n"] = "$v"
            m_pair["c"][1] = fresh
            reset += 1
        mission_pairs.append(m_pair)
    T.array_of(b_world)["len"] = len(world_pairs)
    T.array_of(b_missions)["len"] = len(mission_pairs)
    log(f"Missions: {len(remap)} demo missions added, {reset} of them reset to the full-game checks, "
        f"{skipped} demo-only or relocated missions skipped")

    # Mission board.
    d_board = T.service(demo, "Service.MissionBoard.ServiceData")
    b_board = T.service(base, "Service.MissionBoard.ServiceData")
    for name in ("unlockedMissionIDs", "availableMissionIDs"):
        _set_ints(T.field(b_board, name), _ints(T.field(d_board, name)))
    running = [remap[k] for k in _ints(T.field(d_board, "runningMissions")) if k in remap]
    _set_ints(T.field(b_board, "runningMissions"), running, kind="uint")
    log(f"Mission board: {len(_ints(T.field(d_board, 'unlockedMissionIDs')))} unlocked, {len(running)} running")
    return mission_children


# --- 2. progress inference ----------------------------------------------------------

def infer_progress(missions_demo, active, recipes, board, shop, world_objects=frozenset()):
    """Return (started, completed): sets of demo mission names."""
    started, completed = set(active), set()
    parents = defaultdict(list)  # target -> [(source, group)]
    for name, m in missions_demo.items():
        for group, cls, target in m["actions"]:
            if cls == "MissionAction_StartMission" and target:
                parents[target].append((name, group))

    # An effect only proves a mission ran if that mission is the only one able to produce it.
    producers = defaultdict(set)
    for name, m in missions_demo.items():
        if "Cheat" in name:
            continue
        for group, cls, target in m["actions"]:
            producers[(cls, target)].add(name)

    def effect_seen(cls, target):
        if len(producers[(cls, target)]) != 1:
            return False
        if cls == "MissionAction_UnLockRecipe":
            return target in recipes
        if cls == "MissionAction_UnLockMissionBoardMission":
            return target in board
        if cls == "MissionAction_UnLockShopItem":
            return target in shop
        if cls == "MissionAction_SpawnObject":
            return target in world_objects
        if cls == "MissionAction_StartMission":
            return target in started
        return False

    changed = True
    while changed:
        changed = False
        for name, m in missions_demo.items():
            if "Cheat" in name:
                continue
            groups = defaultdict(list)
            for group, cls, target in m["actions"]:
                groups[group].append((cls, target))
            if name not in started and any(effect_seen(c, t) for c, t in groups[START]):
                started.add(name)
                changed = True
            if name not in completed and name not in active and any(effect_seen(c, t) for c, t in groups[SUCCESS]):
                completed.add(name)
                started.add(name)
                changed = True
            if name in started and name not in active and name not in completed and not m["checks"]:
                completed.add(name)  # no checks: completes as soon as it starts
                changed = True
        # A started mission was started by a parent: started (StartActions) or completed (SuccessActions).
        for child in list(started):
            # Only walk up when there is a single possible parent.
            candidates = [(p, g) for p, g in parents.get(child, ()) if "Cheat" not in p]
            if len(candidates) != 1:
                continue
            parent, group = candidates[0]
            if group == START and parent not in started:
                started.add(parent)
                changed = True
            if group == SUCCESS and parent not in completed and parent not in active:
                completed.add(parent)
                started.add(parent)
                changed = True
    return started, completed


def demo_progress(demo, catalog_demo, missions_demo):
    D = W.SaveView(demo)
    d_objs = D.objects()
    active = {catalog_demo.get(_asset(d_objs[k])) for k in D.mission_ids()}

    def names(svc, field):
        return {catalog_demo.get(e["v"]) for e in T.array_of(T.field(T.service(demo, svc), field))["c"]}
    return infer_progress(
        missions_demo, active,
        names("Service.Recipe.ServiceData", "unlockedRecipes"),
        names("Service.MissionBoard.ServiceData", "unlockedMissionIDs"),
        names("Service.Shop.ServiceData", "unlockedItems"),
        {catalog_demo.get(_asset(o)) for o in d_objs.values()})


# --- 3. full-game additions ---------------------------------------------------------

def _vec(name, type_name, values):
    return {"t": "struct", "n": name, "type": type_name, "c": [{"t": "float", "v": v} for v in values]}


def new_world_object(world_id, asset_id, components=(), position=(0.0, 0.0, 0.0)):
    """Dictionary pair for a new world object."""
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
    """Dictionary pair for the check state of a freshly started mission."""
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


class Additions:
    """Applies full-game actions to the converted save: start missions, spawn objects, unlock recipes."""

    def __init__(self, base, catalog_demo, catalog_full, missions_full, completed, skip_missions=frozenset()):
        self.base = base
        self.ids_full, self.ids_demo = _reverse(catalog_full), _reverse(catalog_demo)
        self.missions_full = missions_full
        self.skip_missions = skip_missions
        self.view = W.SaveView(base)
        objs = self.view.objects()
        self.present = {_asset(objs[k]) for k in self.view.mission_ids()}
        self.known_done = {self.ids_demo.get(n) for n in completed}
        self.present_assets = {_asset(o) for o in objs.values()}
        self.current = T.field(T.service(base, "Service.WorldObject.ServiceData"), "currentID")
        self.world_arr = T.array_of(self.view.world)
        self.mission_arr = T.array_of(self.view.dicts["Mission.Mission+SaveData"])
        self.started, self.recipes, self.spawned, self.skipped_spawn, self.removed = [], [], [], [], []

    def _new_id(self):
        wid = self.current["v"]
        self.current["v"] += 1
        return wid

    def spawn(self, target, position, near_only=False, asset=None):
        """Create an object at a spawn point, unless one already exists (anywhere, or nearby)."""
        asset = asset if asset is not None else self.ids_full.get(target)
        if asset is None or position is None:
            self.skipped_spawn.append(target)
            return
        if near_only:
            for pair in self.world_arr["c"]:
                a, pos = W.asset_pos(pair["c"][1])
                if a == asset and math.dist(pos, position) < 1.0:
                    return
        elif asset in self.present_assets:
            return
        self.world_arr["c"].append(new_world_object(self._new_id(), asset, position=tuple(position)))
        self.present_assets.add(asset)
        self.spawned.append(target)

    def remove_near(self, target, position, radius=1.0, asset=None):
        """Remove the objects of one kind near a spot, with all their data."""
        asset = asset if asset is not None else self.ids_full.get(target)
        if asset is None or position is None:
            return
        doomed = {pair["c"][0]["v"] for pair in self.world_arr["c"]
                  if W.asset_pos(pair["c"][1])[0] == asset
                  and math.dist(W.asset_pos(pair["c"][1])[1], position) < radius}
        if not doomed:
            return
        for node in self.view.dicts.values():
            arr = T.array_of(node)
            arr["c"] = [p for p in arr["c"] if p["c"][0]["v"] not in doomed]
        self.removed.extend([target] * len(doomed))

    def start(self, target):
        """Insert a started mission and run its start actions, which the game
        does not run for a mission loaded from a save."""
        asset = self.ids_full.get(target)
        if (asset is None or target in self.skip_missions or asset in self.present
                or asset in self.known_done or target not in self.missions_full):
            return
        wid = self._new_id()
        self.world_arr["c"].append(new_world_object(wid, asset, [MISSION_COMPONENT]))
        self.mission_arr["c"].append(new_mission_data(wid, self.missions_full[target]["checks"]))
        self.present.add(asset)
        self.started.append(target)
        positions = self.missions_full[target].get("spawn_positions", {})
        for i, (group, cls, child) in enumerate(self.missions_full[target]["actions"]):
            if group == START:
                self.apply_mission_action(cls, child, positions.get(str(i)))

    def apply_mission_action(self, cls, target, position):
        if cls == "MissionAction_StartMission":
            self.start(target)
        elif cls == "MissionAction_UnLockRecipe":
            asset = self.ids_full.get(target)
            if asset is not None:
                self.recipes.append(asset)
        elif cls == "MissionAction_SpawnObject":
            self.spawn(target, position)

    def finish(self, log):
        for node in self.view.dicts.values():
            arr = T.array_of(node)
            arr["len"] = len(arr["c"])
        if self.recipes:
            node = T.array_of(T.field(T.service(self.base, "Service.Recipe.ServiceData"), "unlockedRecipes"))
            have = {e["v"] for e in node["c"]}
            for r in self.recipes:
                if r not in have:
                    node["c"].append({"t": "int", "v": r})
                    have.add(r)
            node["len"] = len(node["c"])
        log(f"Full-game additions: {len(self.started)} missions started")
        for m in self.started:
            log(f"  + {m}")
        if self.recipes:
            log(f"Recipes added by the full game: {len(self.recipes)}")
        if self.spawned:
            log("Objects added by the full game: " + ", ".join(self.spawned))
        if self.removed:
            log("Demo objects replaced by their full-game version: " + ", ".join(self.removed))
        if self.skipped_spawn:
            log("Full-game objects not created (unknown position): " + ", ".join(sorted(set(self.skipped_spawn))))


def apply_full_additions(adds, catalog_demo, catalog_full, missions_demo, missions_full, started, completed, log):
    """Missions the demo ran: apply the actions the full game added to them."""
    ids_full, ids_demo = _reverse(catalog_full), _reverse(catalog_demo)

    # Actions are compared by assetID: some missions were only renamed.
    def key(group, cls, target, ids):
        return group, cls, (ids.get(target, target) if target else None)

    count = 0
    for name in sorted(started):
        if name not in missions_full or name not in missions_demo:
            continue
        groups = [START] + ([SUCCESS] if name in completed else [])
        demo_keys = {key(*a, ids_demo) for a in missions_demo[name]["actions"]}
        positions = missions_full[name].get("spawn_positions", {})
        for i, (group, cls, target) in enumerate(missions_full[name]["actions"]):
            if group not in groups or key(group, cls, target, ids_full) in demo_keys:
                continue
            # Objects spawned when a mission (long finished in the demo) started are usually
            # temporary (sounds, triggers): only end-of-mission rewards are kept.
            if cls == "MissionAction_SpawnObject" and group != SUCCESS:
                continue
            adds.apply_mission_action(cls, target, positions.get(str(i)))
            count += 1
    log(f"Missions: {len(started)} missions ran in the demo, {count} full-game additions to them")


def apply_trigger_additions(adds, demo, triggers_demo, triggers_full, log):
    """Zone triggers the demo fired: apply the actions the full game added to them.

    A trigger is a world object that does something when the player walks into
    it, then destroys itself. The lab discovery trigger, for example, spawns the
    door battery holders and starts the lab missions in the full game only. If
    the demo already fired it, those would never happen.
    """
    ids_full, ids_demo = adds.ids_full, adds.ids_demo
    demo_objs = W.SaveView(demo).objects()
    conv_objs = {pair["c"][0]["v"]: pair["c"][1] for pair in adds.world_arr["c"]}

    def present(objs, t):
        ref = W.Matcher([(t["assetID"], tuple(t["position"]))])
        return bool(ref.match_all({k: W.asset_pos(o) for k, o in objs.items()}))

    def key(action, ids):
        cls, target = action[0], action[1]
        # Spawning a mission object and starting that mission are the same thing.
        if cls == "OnTrigger_SpawnObject" and target and target.startswith("Mission"):
            cls = "OnTrigger_StartMission"
        return cls, (action[3] if action[3] is not None else ids.get(target, target) if target else None)

    full_index = W.Matcher([(t["assetID"], tuple(t["position"])) for t in triggers_full]).match_all(
        {i: (t["assetID"], tuple(t["position"])) for i, t in enumerate(triggers_demo)})
    fired = 0
    for i, td in enumerate(triggers_demo):
        if i not in full_index or present(demo_objs, td):
            continue  # not in the full game, or not fired in the demo
        tf = triggers_full[full_index[i]]
        if present(conv_objs, tf):
            continue  # still in the converted save: the game will fire it
        demo_keys = {key(a, ids_demo) for a in td["actions"]}
        full_keys = {key(a, ids_full) for a in tf["actions"]}
        removed = [a for a in td["actions"] if key(a, ids_demo) not in full_keys]
        added = [a for a in tf["actions"] if key(a, ids_full) not in demo_keys]
        if added:
            fired += 1
        for action in added:
            kind, _ = key(action, ids_full)
            target, position, asset = action[1], action[2], action[3]
            if kind == "OnTrigger_StartMission":
                adds.start(target)
            elif kind == "OnTrigger_SpawnObject":
                # A demo object spawned at the same spot is the old version of this one.
                for old in removed:
                    if old[0] == "OnTrigger_SpawnObject" and old[2] and math.dist(old[2], position) < 0.5:
                        adds.remove_near(old[1], old[2], asset=old[3])
                adds.spawn(target, position, near_only=True, asset=asset)
    log(f"Triggers: {fired} triggers fired in the demo do more in the full game")


def ensure_tutorial_marker(base, catalog_full, started, log):
    """The full game spawns p_tutorialPlayed at the end of its tutorial; some missions wait for it."""
    if "Mission_Board_InitialSetup" not in started:
        return
    ids = {n: a for a, n in catalog_full.items() if n in ("p_tutorialPlayed", "p_tutorialSkipped")}
    B = W.SaveView(base)
    if any(_asset(o) in ids.values() for o in B.objects().values()):
        return
    current = T.field(T.service(base, "Service.WorldObject.ServiceData"), "currentID")
    arr = T.array_of(B.world)
    arr["c"].append(new_world_object(current["v"], ids["p_tutorialPlayed"]))
    arr["len"] = len(arr["c"])
    current["v"] += 1
    log("Tutorial: end-of-tutorial marker added (the demo finished it)")
