"""Progress that only uses stable identifiers (assetIDs), copied directly.

Recipes, shop items, target audiences, the contents of the special inventories
(money, player backpack...) and the player stats. AssetIDs are hashes that are
identical in the demo and the full game, so these need no translation.
"""

import struct

from . import odin_tree as T
from . import world as W

# PlayerStat enum of the game: 0 None, 1 Strength, 2 Stamina, 3 MoveSpeedFactor, 4 unused.
STAT_NAMES = {1: "strength", 2: "stamina", 3: "move speed"}


def _ints(node):
    return [e["v"] for e in T.array_of(node)["c"]]


def merge_hashset(demo, base, service_prefix, field_name, label, log):
    """Union of a HashSet<int> of the demo into the base save (recipes, shop items)."""
    d = _ints(T.field(T.service(demo, service_prefix), field_name))
    node = T.field(T.service(base, service_prefix), field_name)
    b = _ints(node)
    seen = set(b)
    merged = b + [v for v in d if v not in seen and not seen.add(v)]
    T.set_array(T.array_of(node), [{"t": "int", "v": v} for v in merged])
    log(f"{label}: {len(b)} in the base save, {len(d)} in the demo, {len(merged)} in total")


def copy_audiences(demo, base, log):
    svc = "Service.TargetAudience.ServiceData"
    src = {k: v for k, v, _ in T.dict_pairs(T.field(T.service(demo, svc), "targetAudiences"))}
    n = 0
    for key, value, _ in T.dict_pairs(T.field(T.service(base, svc), "targetAudiences")):
        if key in src:
            for name in ("value", "clampedValue"):
                T.field(value, name)["v"] = T.field(src[key], name)["v"]
            n += 1
    log(f"Target audiences: {n} values copied")


def special_inventories(doc, refs):
    """{InventoryType: Inventory node}, through the specialInventories dictionary."""
    inv_service = T.service(doc, "Service.Inventory.ServiceData")
    out = {}
    for key, value, _ in T.dict_pairs(T.field(inv_service, "specialInventories")):
        out[key] = refs[value["v"]] if value["t"] == "intref" else value
    return out


def copy_special_inventories(demo, base, demo_refs, base_refs, catalog_full, log):
    src = special_inventories(demo, demo_refs)
    dst = special_inventories(base, base_refs)
    for inv_type in sorted(src):
        if inv_type not in dst:
            log(f"Special inventory {inv_type}: not in the full game, skipped")
            continue
        items = [(k, T.field(v, "amount")["v"]) for k, v, _ in T.dict_pairs(T.field(src[inv_type], "content"))]
        unknown = [k for k, _ in items if k not in catalog_full]
        items = [(k, a) for k, a in items if k in catalog_full]
        pairs = []
        for item, amount in items:
            pairs.append({"t": "struct", "type": None, "c": [
                {"t": "int", "n": "$k", "v": item},
                T.fresh_ref("Service.Inventory.Inventory+Content, Assembly-CSharp", [
                    {"t": "int", "n": "itemID", "v": item},
                    {"t": "int", "n": "amount", "v": amount},
                ], name="$v"),
            ]})
        T.set_array(T.array_of(T.field(dst[inv_type], "content")), pairs)
        try:
            T.field(dst[inv_type], "totalAmount")["v"] = sum(a for _, a in items)
        except KeyError:
            pass
        if items or unknown:
            msg = f"Special inventory {inv_type}: {len(items)} kinds of items copied"
            if unknown:
                msg += f", {len(unknown)} unknown to the full game skipped"
            log(msg)


def transfer_player_stats(demo, base, log):
    def stats(doc):
        return T.dict_pairs(W.SaveView(doc).dicts["Player.PlayerStats+SaveData"])[0][1]

    def floats(node):
        arr = node["c"][0]
        return list(struct.unpack(f"<{arr['count']}f", bytes.fromhex(arr["hex"])))

    def set_floats(node, values):
        arr = node["c"][0]
        arr["count"] = len(values)
        arr["hex"] = struct.pack(f"<{len(values)}f", *values).hex()

    d, b = stats(demo), stats(base)
    limits = [tuple(c["v"] for c in vec["c"]) for vec in T.array_of(T.field(b, "permanentMinMaxValue"))["c"]]
    d_perm = floats(T.field(d, "permanentValue"))
    perm = floats(T.field(b, "permanentValue"))
    for i, name in STAT_NAMES.items():
        lo, hi = limits[i]
        value = min(max(d_perm[i], lo), hi)
        log(f"Player: {name} {perm[i]:.2f} -> {value:.2f} (full-game limits {lo:g} to {hi:g})")
        perm[i] = value
    set_floats(T.field(b, "permanentValue"), perm)
    # Current value = permanent + temporary; start again without temporary bonuses.
    set_floats(T.field(b, "currentValue"), perm)
    set_floats(T.field(b, "temporaryValue"), [0.0] * len(perm))
