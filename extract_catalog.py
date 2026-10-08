"""Extrait le catalogue des identifiants (assetID) depuis les fichiers du jeu.

Les sauvegardes ne référencent les objets, recettes, missions, etc. que par
un entier (assetID). Ce script retrouve le nom et la catégorie de chaque ID
en lisant les fichiers Unity du jeu, pour pouvoir comparer démo et jeu complet.

Usage :
    .venv/Scripts/python extract_catalog.py <dossier *_Data du jeu> <sortie.csv>

Nécessite UnityPy (pip install UnityPy).

Deux sortes d'objets portent un assetID :
- les ScriptableObject (Recipe, Mission, TargetAudience...) : l'assetID est
  le premier champ après m_Name ;
- les composants WorldObject des prefabs : l'assetID est le dernier champ,
  le nom vient du GameObject parent.
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
    catalog = {}  # id -> (catégorie, nom, source)
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
            # Les prefabs (resources.assets) priment sur les instances de scène.
            if aid not in catalog or catalog[aid][2].startswith("level"):
                catalog[aid] = entry
    return catalog


def main():
    data_dir, out = sys.argv[1], sys.argv[2]
    catalog = extract(data_dir)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["assetID", "categorie", "nom", "fichier"])
        for aid, (cat, name, src) in sorted(catalog.items(), key=lambda x: (x[1][0], x[1][1])):
            w.writerow([aid, cat, name, src])
    print(f"{len(catalog)} identifiants -> {out}")


if __name__ == "__main__":
    main()
