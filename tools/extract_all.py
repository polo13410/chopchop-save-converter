"""Regenerate every file of the data folder from the installed games.

Needed after a game update. Both the demo and the full game must be installed.

Usage (requires UnityPy):
    python -m tools.extract_all ["C:/Program Files (x86)/Steam/steamapps/common"]
"""

import os
import sys

from tools import extract_catalog, extract_missions, extract_scene

DEFAULT_STEAM = r"C:\Program Files (x86)\Steam\steamapps\common"
GAMES = {
    "demo": os.path.join("ChopChopIncDemo", "ChopChopIncDemo_Data"),
    "full": os.path.join("ChopChopInc", "ChopChopInc_Data"),
}


def main():
    steam = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STEAM
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    for version, folder in GAMES.items():
        game = os.path.join(steam, folder)
        if not os.path.isdir(game):
            sys.exit(f"Game folder not found: {game}")
        print(f"{version}: reading {game}")
        catalog = extract_catalog.extract(game)
        extract_catalog.write(catalog, os.path.join(out, f"catalog-{version}.csv"))
        print(f"  {len(catalog)} identifiers")
        rows = extract_scene.extract(game)
        extract_scene.write(rows, os.path.join(out, f"scene-{version}.csv"))
        print(f"  {len(rows)} scene objects")
        missions = extract_missions.extract(game)
        extract_missions.write(missions, os.path.join(out, f"missions-{version}.json"))
        print(f"  {len(missions)} missions")


if __name__ == "__main__":
    main()
