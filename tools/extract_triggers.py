"""Extract the zone triggers placed in the game scenes, with their actions.

Some world objects fire when the player walks into them (OnTrigger_SpawnObject,
OnTrigger_StartMission...) and then destroy themselves. For each such object
found in the level* files, this writes its assetID, its position and its
actions: target name, target assetID (for spawned prefabs) and the world
position of spawn points.

Usage (requires UnityPy):
    python -m tools.extract_triggers <game *_Data folder> <output.json>
"""

import glob
import json
import os
import struct
import sys

import UnityPy

from tools.extract_scene import world_transform

HEADER = 28  # m_GameObject (12) + m_Enabled (4) + m_Script (12)


def pptrs(raw):
    """Every plausible (fileID, pathID) reference in a MonoBehaviour body."""
    out = []
    off = HEADER + 4
    while off + 12 <= len(raw):
        file_id, path_id = struct.unpack_from("<iq", raw, off)
        if 0 <= file_id < 64 and 0 < path_id < 1 << 40:
            out.append((file_id, path_id))
            off += 12
        else:
            off += 4
    return out


def resolve(obj_file, file_id, path_id, files):
    """Object behind a reference, following the file's external list."""
    if file_id == 0:
        target_file = obj_file
    else:
        externals = obj_file.externals
        if file_id - 1 >= len(externals):
            return None
        name = os.path.basename(externals[file_id - 1].path)
        target_file = files.get(name)
        if target_file is None:
            return None
    return target_file.objects.get(path_id)


def asset_of(obj):
    """AssetID of the WorldObject component of a GameObject, if any."""
    try:
        go = obj.read()
        for comp in go.m_Component:
            r = (comp.component if hasattr(comp, "component") else comp).deref()
            if r is not None and r.type.name == "MonoBehaviour":
                if r.read(check_read=False).m_Script.read().m_ClassName == "WorldObject":
                    raw = r.get_raw_data()
                    return struct.unpack_from("<i", raw, len(raw) - 4)[0]
    except Exception:
        return None
    return None


def name_of(obj):
    try:
        if obj.type.name == "GameObject":
            return obj.read().m_Name
        if obj.type.name == "MonoBehaviour":
            mb = obj.read(check_read=False)
            if mb.m_GameObject.path_id:
                return mb.m_GameObject.read().m_Name
            return getattr(mb, "m_Name", None)
    except Exception:
        return None
    return None


def extract(data_dir):
    levels = sorted((f for f in glob.glob(os.path.join(data_dir, "level*")) if "." not in os.path.basename(f)),
                    key=lambda f: int(os.path.basename(f)[5:]))
    env = UnityPy.load(os.path.join(data_dir, "resources.assets"), *levels)
    files = {os.path.basename(name): f for name, f in env.files.items()}
    triggers = []
    for level in levels:
        level_file = files[os.path.basename(level)]
        cache = {}
        for obj in level_file.objects.values():
            if obj.type.name != "GameObject":
                continue
            go = obj.read()
            asset_id = None
            actions = []
            for comp in go.m_Component:
                r = (comp.component if hasattr(comp, "component") else comp).deref()
                if r is None or r.type.name != "MonoBehaviour":
                    continue
                try:
                    mb = r.read(check_read=False)
                    cls = mb.m_Script.read().m_ClassName
                except Exception:
                    continue
                raw = r.get_raw_data()
                if cls == "WorldObject":
                    asset_id = struct.unpack_from("<i", raw, len(raw) - 4)[0]
                elif cls.startswith("OnTrigger_"):
                    target, spawn, target_asset = None, None, None
                    for file_id, path_id in pptrs(raw):
                        ref = resolve(r.assets_file, file_id, path_id, files)
                        if ref is None:
                            continue
                        if ref.type.name == "Transform" and spawn is None:
                            (x, y, z), _, _ = world_transform(ref.read(), cache)
                            spawn = [round(x, 3), round(y, 3), round(z, 3)]
                        elif ref.type.name in ("GameObject", "MonoBehaviour") and target is None:
                            n = name_of(ref)
                            if n != go.m_Name:  # skip the reference to its own Trigger component
                                target = n
                                if ref.type.name == "GameObject":
                                    target_asset = asset_of(ref)
                    actions.append([cls, target, spawn, target_asset])
            if asset_id is None or not actions:
                continue
            (x, y, z), _, _ = world_transform(go.m_Transform.read(), cache)
            triggers.append({"scene": os.path.basename(level), "assetID": asset_id, "name": go.m_Name,
                             "position": [round(x, 3), round(y, 3), round(z, 3)], "actions": actions})
    return triggers


def write(triggers, out):
    with open(out, "w", encoding="utf-8") as f:
        json.dump(triggers, f, ensure_ascii=False, indent=1)


def main():
    triggers = extract(sys.argv[1])
    write(triggers, sys.argv[2])
    print(f"{len(triggers)} triggers -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
