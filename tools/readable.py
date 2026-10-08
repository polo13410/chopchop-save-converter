"""Readable (lossy) view of a decoded save, for analysis only."""


def readable(e):
    t = e["t"]
    if t in ("ref", "struct"):
        kids = e["c"]
        # Odin Dictionary: a comparer, then an array of $k/$v pairs
        if (e.get("type") or "").startswith("System.Collections.Generic.Dictionary"):
            arr = next((k for k in kids if k["t"] == "array"), None)
            if arr is not None:
                out = {}
                for pair in arr["c"]:
                    k, v = pair["c"][0], pair["c"][1]
                    out[str(readable(k))] = readable(v)
                return out
        if e.get("type") == "System.RuntimeType, mscorlib":
            return "type:" + kids[0]["v"]
        if kids and all("n" not in k for k in kids):
            vals = [readable(k) for k in kids]
            return vals[0] if len(vals) == 1 else vals
        return {k.get("n", f"#{i}"): readable(k) for i, k in enumerate(kids)}
    if t == "array":
        return [readable(k) for k in e["c"]]
    if t == "parray":
        return f"<{e['count']}x{e['size']}B>"
    if t == "intref":
        return f"->ref{e['v']}"
    return e.get("v")


def services(doc):
    root = readable(doc["root"][0])
    return {k.replace("type:", "").replace(", Assembly-CSharp", ""): v
            for k, v in root["data"].items()}
