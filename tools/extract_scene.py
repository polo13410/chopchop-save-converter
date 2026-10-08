"""Extract the world objects placed in the game scenes (initial state of the map).

For each WorldObject component found in the level* files, write its assetID
its position in the world (with the Transform hierarchy applied), and whether
it is active when the game starts (inactive objects are enabled later by
missions, and are not saved until then).
Comparing a save to this initial state tells what the player changed.

Usage (requires UnityPy):
    python -m tools.extract_scene <game *_Data folder> <output.csv>
"""

import csv
import glob
import os
import struct
import sys

import UnityPy


def qmul_vec(q, v):
    """Apply rotation q (x, y, z, w) to vector v."""
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v)
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def world_transform(tr, cache):
    key = tr.object_reader.path_id
    if key in cache:
        return cache[key]
    p = tr.m_LocalPosition
    r = tr.m_LocalRotation
    s = tr.m_LocalScale
    pos, rot, scl = (p.x, p.y, p.z), (r.x, r.y, r.z, r.w), (s.x, s.y, s.z)
    if tr.m_Father and tr.m_Father.path_id:
        ppos, prot, pscl = world_transform(tr.m_Father.read(), cache)
        scaled = (pos[0] * pscl[0], pos[1] * pscl[1], pos[2] * pscl[2])
        rx, ry, rz = qmul_vec(prot, scaled)
        pos = (ppos[0] + rx, ppos[1] + ry, ppos[2] + rz)
        rot = qmul(prot, rot)
        scl = (scl[0] * pscl[0], scl[1] * pscl[1], scl[2] * pscl[2])
    cache[key] = (pos, rot, scl)
    return cache[key]


def extract(data_dir):
    files = sorted((f for f in glob.glob(os.path.join(data_dir, "level*")) if "." not in os.path.basename(f)),
                   key=lambda f: int(os.path.basename(f)[5:]))
    rows = []
    for path in files:
        env = UnityPy.load(path)
        cache = {}
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                mb = obj.read(check_read=False)
                if mb.m_Script.read().m_ClassName != "WorldObject":
                    continue
            except Exception:
                continue
            raw = obj.get_raw_data()
            asset_id = struct.unpack_from("<i", raw, len(raw) - 4)[0]
            flag = struct.unpack_from("<i", raw, len(raw) - 8)[0]  # 1 = saved (serializeWorldObject)
            go = mb.m_GameObject.read()
            tr = go.m_Transform.read()
            (x, y, z), _, _ = world_transform(tr, cache)
            # Active at the start: the GameObject and all its parents are active.
            active = 1 if go.m_IsActive else 0
            node = tr
            while active and node.m_Father and node.m_Father.path_id:
                node = node.m_Father.read()
                if not node.m_GameObject.read().m_IsActive:
                    active = 0
            # A WorldObject under another WorldObject is a child (childWorldObjects).
            parent_wo = 0
            father = tr.m_Father
            while father and father.path_id:
                ftr = father.read()
                fgo = ftr.m_GameObject.read()
                for comp in fgo.m_Component:
                    c = comp.component if hasattr(comp, "component") else comp
                    try:
                        cm = c.read()
                        if c.type.name == "MonoBehaviour" and cm.m_Script.read().m_ClassName == "WorldObject":
                            parent_wo = 1
                    except Exception:
                        pass
                if parent_wo:
                    break
                father = ftr.m_Father
            rows.append((os.path.basename(path), asset_id, round(x, 3), round(y, 3), round(z, 3),
                         flag, parent_wo, active, go.m_Name))
    return rows


def write(rows, out):
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scene", "assetID", "x", "y", "z", "flag", "under_worldobject", "active", "name"])
        w.writerows(rows)


def main():
    rows = extract(sys.argv[1])
    write(rows, sys.argv[2])
    print(f"{len(rows)} objects -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
