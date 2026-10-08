"""Déduit l'avancement des missions de la démo et ce que le jeu complet aurait fait en plus.

Le jeu complet a enrichi des missions qui existaient déjà dans la démo : par
exemple Mission_Board_InitialSetup démarre 16 missions au lieu de 7. Si la
démo a exécuté cette mission, les missions ajoutées par le jeu complet ne
seront jamais démarrées dans la sauvegarde convertie. Ce module les trouve.

1. Missions démarrées / terminées dans la démo, par point fixe sur leurs effets
   visibles dans la sauvegarde : mission active, recette débloquée, mission du
   tableau débloquée, article de boutique débloqué, mission démarrée ensuite.
   Une mission sans condition se termine dès qu'elle démarre.
2. Pour chaque mission exécutée, on compare ses actions dans la démo et dans
   le jeu complet. Les actions ajoutées par le jeu complet sont à appliquer.
"""

import json
from collections import defaultdict

START, SUCCESS = "StartActions", "SuccessActions"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def infer_progress(missions_demo, active, recipes, board, shop, world_objects=frozenset()):
    """Renvoie (démarrées, terminées) : ensembles de noms de missions de la démo."""
    started, completed = set(active), set()
    parents = defaultdict(list)  # cible -> [(source, groupe)]
    for name, m in missions_demo.items():
        for group, cls, target in m["actions"]:
            if cls == "MissionAction_StartMission" and target:
                parents[target].append((name, group))

    # Un effet ne prouve qu'une mission a agi que si elle seule peut le produire.
    producers = defaultdict(set)
    for name, m in missions_demo.items():
        if "Cheat" in name:
            continue
        for group, cls, target in m["actions"]:
            producers[(cls, target)].add(name)

    def effect_seen(cls, target, group=SUCCESS):
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
            groups = defaultdict(list)
            for group, cls, target in m["actions"]:
                groups[group].append((cls, target))
            if "Cheat" in name:
                continue
            if name not in started and any(effect_seen(c, t, START) for c, t in groups[START]):
                started.add(name)
                changed = True
            if name not in completed and name not in active and any(effect_seen(c, t) for c, t in groups[SUCCESS]):
                completed.add(name)
                started.add(name)
                changed = True
            if name in started and name not in active and name not in completed and not m["checks"]:
                completed.add(name)  # sans condition : terminée aussitôt démarrée
                changed = True
        # Une mission démarrée l'a été par un parent : démarré (StartActions) ou terminé (SuccessActions).
        for child in list(started):
            # On ne remonte au parent que s'il est le seul possible.
            candidates = [(p, g) for p, g in parents.get(child, ()) if "Cheat" not in p]
            if len(candidates) != 1:
                continue
            for parent, group in candidates:
                if group == START and parent not in started:
                    started.add(parent)
                    changed = True
                if group == SUCCESS and parent not in completed and parent not in active:
                    completed.add(parent)
                    started.add(parent)
                    changed = True
    return started, completed


def added_actions(missions_demo, missions_full, started, completed):
    """Actions présentes dans le jeu complet mais pas dans la démo, pour les missions exécutées."""
    out = []
    for name in sorted(started):
        if name not in missions_full or name not in missions_demo:
            continue
        groups = [START] + ([SUCCESS] if name in completed else [])
        demo_actions = {tuple(a) for a in missions_demo[name]["actions"]}
        for action in missions_full[name]["actions"]:
            if action[0] in groups and tuple(action) not in demo_actions:
                out.append((name, *action))
    return out
