"""Extract the catalog of identifiers (assetIDs) from the game files.

Saves only refer to items, recipes, missions, etc. by an integer (assetID).
This script finds the name and category of each id by reading the Unity files
of the game, so the demo and the full game can be compared.

Usage (requires UnityPy):
    python -m tools.extract_catalog <game *_Data folder> <output.csv>

Two kinds of objects carry an assetID:
- ScriptableObjects (Recipe, Mission, TargetAudience...): the assetID is the
  first field after m_Name;
- WorldObject components of prefabs: the assetID is the last field, and the
  name comes from the parent GameObject.
"""

import csv
import glob
import os
import struct
import sys

import UnityPy

HEADER = 28  # m_GameObject (12) + m_Enabled (4) + m_Script (12)


def first_field_after_name(raw):
    length = struct.unpack_from("<i", raw, HEADER)[0]
    if not 0 <= length < 512:
        return None
    off = HEADER + 4 + length
    off += (-off) % 4
    if off + 4 > len(raw):
        return None
    return struct.unpack_from("<i", raw, off)[0]


def script_name(mb):
    try:
        return mb.m_Script.read().m_ClassName
    except Exception:
        return None


def extract(data_dir):
    files = sorted(glob.glob(os.path.join(data_dir, "*.assets")))
    files += sorted(f for f in glob.glob(os.path.join(data_dir, "level*")) if "." not in os.path.basename(f))
    catalog = {}  # id -> (category, name, source file)
    for path in files:
        env = UnityPy.load(path)
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                mb = obj.read(check_read=False)
            except Exception:
                continue
            cls = script_name(mb)
            if not cls:
                continue
            raw = obj.get_raw_data()
            if cls == "WorldObject" and len(raw) >= 44:
                aid = struct.unpack_from("<i", raw, len(raw) - 4)[0]
                try:
                    name = mb.m_GameObject.read().m_Name
                except Exception:
                    name = "?"
                entry = ("WorldObject", name, os.path.basename(path))
            elif mb.m_GameObject.path_id == 0 and getattr(mb, "m_Name", ""):
                aid = first_field_after_name(raw)
                if aid is None or aid == 0:
                    continue
                entry = (cls, mb.m_Name, os.path.basename(path))
            else:
                continue
            # Prefabs (resources.assets) win over scene instances.
            if aid not in catalog or catalog[aid][2].startswith("level"):
                catalog[aid] = entry
    return catalog


def write(catalog, out):
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["assetID", "category", "name", "file"])
        for aid, (cat, name, src) in sorted(catalog.items(), key=lambda x: (x[1][0], x[1][1])):
            w.writerow([aid, cat, name, src])


def main():
    data_dir, out = sys.argv[1], sys.argv[2]
    catalog = extract(data_dir)
    write(catalog, out)
    print(f"{len(catalog)} identifiers -> {out}")


if __name__ == "__main__":
    main()
