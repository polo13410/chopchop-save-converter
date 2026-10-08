"""Extrait la définition des missions du jeu : conditions et actions.

Chaque mission est un prefab "Mission_..." avec des enfants StartActions,
Checks, SuccessActions et FailActions. Pour chaque mission, on écrit :
- ses conditions (classe et _id, dans l'ordre où le jeu les sauvegarde) ;
- ses actions (groupe, classe et cible : mission démarrée, objet créé...).

Usage :
    .venv/Scripts/python extract_missions.py <dossier *_Data du jeu> <sortie.json>
"""

import json
import os
import struct
import sys

import UnityPy

from extract_scene import world_transform

HEADER = 28  # m_GameObject (12) + m_Enabled (4) + m_Script (12)


def first_pptr_target(raw, objects, cache):
    """Nom de la première cible référencée par une action (mission ou prefab)."""
    off = HEADER + 4  # m_Name vide
    while off + 12 <= len(raw):
        file_id, path_id = struct.unpack_from("<iq", raw, off)
        if file_id == 0 and path_id > 0 and path_id in objects:
            return describe(objects[path_id], cache)
        off += 4
    return None


def spawn_position(raw, objects):
    """Position (relative à la mission, placée à l'origine) du point d'apparition d'une action SpawnObject."""
    pptrs = []
    off = HEADER + 4
    while off + 12 <= len(raw) and len(pptrs) < 2:
        file_id, path_id = struct.unpack_from("<iq", raw, off)
        if file_id == 0 and path_id > 0 and path_id in objects:
            pptrs.append(objects[path_id])
            off += 12
        else:
            off += 4
    if len(pptrs) < 2 or pptrs[1].type.name != "Transform":
        return None
    (x, y, z), _, _ = world_transform(pptrs[1].read(), {})
    return [round(x, 4), round(y, 4), round(z, 4)]


def describe(obj, cache):
    if obj.path_id in cache:
        return cache[obj.path_id]
    name = None
    try:
        if obj.type.name == "GameObject":
            name = obj.read().m_Name
        elif obj.type.name == "MonoBehaviour":
            mb = obj.read(check_read=False)
            if mb.m_GameObject.path_id:
                name = mb.m_GameObject.read().m_Name
            else:
                name = getattr(mb, "m_Name", None)
    except Exception:
        pass
    cache[obj.path_id] = name
    return name


def main():
    data_dir, out = sys.argv[1], sys.argv[2]
    env = UnityPy.load(os.path.join(data_dir, "resources.assets"))
    objects = {o.path_id: o for o in env.objects}
    cache = {}
    missions = {}
    for obj in env.objects:
        if obj.type.name != "GameObject":
            continue
        go = obj.read()
        if go.m_Transform is None:
            continue
        tr = go.m_Transform.read()
        if tr.m_Father and tr.m_Father.path_id:
            continue
        is_mission = False
        for comp in go.m_Component:
            r = (comp.component if hasattr(comp, "component") else comp).deref()
            if r.type.name == "MonoBehaviour":
                if r.read(check_read=False).m_Script.read().m_ClassName == "Mission":
                    is_mission = True
        if not is_mission:
            continue
        entry = {"checks": [], "actions": []}
        for child in tr.m_Children:
            cgo = child.read().m_GameObject.read()
            for comp in cgo.m_Component:
                r = (comp.component if hasattr(comp, "component") else comp).deref()
                if r.type.name != "MonoBehaviour":
                    continue
                cls = r.read(check_read=False).m_Script.read().m_ClassName
                raw = r.get_raw_data()
                if cls.startswith("MissionCheck_"):
                    check_id = struct.unpack_from("<Q", raw, HEADER + 24)[0]
                    entry["checks"].append([cls, check_id])
                elif cls.startswith("MissionAction_"):
                    target = first_pptr_target(raw, objects, cache)
                    entry["actions"].append([cgo.m_Name, cls, target])
                    if cls == "MissionAction_SpawnObject":
                        index = str(len(entry["actions"]) - 1)
                        entry.setdefault("spawn_positions", {})[index] = spawn_position(raw, objects)
        missions[go.m_Name] = entry
    with open(out, "w", encoding="utf-8") as f:
        json.dump(missions, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"{len(missions)} missions -> {out}")


if __name__ == "__main__":
    main()
