"""Lecteur / écrivain du format binaire d'Odin Serializer.

Référence : https://github.com/TeamSirenix/odin-serializer
(BinaryDataReader.cs, BinaryDataWriter.cs, BinaryEntryType.cs)

Le fichier est converti en un arbre d'entrées JSON sans perte :
encoder(decoder(fichier)) redonne exactement les mêmes octets.

Forme d'une entrée :
    {"t": <type>, "n": <nom ou absent>, ...}
    - nœuds :   "t": "ref" | "struct", "type": nom de type C# ou null,
                "id": identifiant (ref seulement), "c": [entrées enfants]
    - tableaux: "t": "array", "len": longueur annoncée, "c": [entrées]
    - tableau primitif : "t": "parray", "count", "size", "hex"
    - valeurs : "t": "int", "float", "string", ... avec "v"
"""

import struct

# Codes des entrées (BinaryEntryType.cs). Les valeurs vont par paires :
# code nommé, puis code non nommé = code nommé + 1.
NAMED_REF, UNNAMED_REF = 0x01, 0x02
NAMED_STRUCT, UNNAMED_STRUCT = 0x03, 0x04
END_OF_NODE = 0x05
START_OF_ARRAY = 0x06
END_OF_ARRAY = 0x07
PRIMITIVE_ARRAY = 0x08
TYPE_NAME = 0x2F
TYPE_ID = 0x30
END_OF_STREAM = 0x31

# Valeurs simples : code nommé -> (nom, format struct ou traitement spécial)
SCALARS = {
    0x09: ("intref", "<i"),
    0x0B: ("extindex", "<i"),
    0x0D: ("extguid", "guid"),
    0x0F: ("sbyte", "<b"),
    0x11: ("byte", "<B"),
    0x13: ("short", "<h"),
    0x15: ("ushort", "<H"),
    0x17: ("int", "<i"),
    0x19: ("uint", "<I"),
    0x1B: ("long", "<q"),
    0x1D: ("ulong", "<Q"),
    0x1F: ("float", "<f"),
    0x21: ("double", "<d"),
    0x23: ("decimal", "raw16"),
    0x25: ("char", "<H"),
    0x27: ("string", "string"),
    0x29: ("guid", "guid"),
    0x2B: ("bool", "bool"),
    0x2D: ("null", None),
    0x32: ("extstring", "string"),
}
SCALAR_CODE = {name: code for code, (name, _) in SCALARS.items()}


class OdinFormatError(Exception):
    pass


class Reader:
    def __init__(self, data: bytes):
        self.b = data
        self.p = 0
        self.types = {}  # id -> nom de type, comme le cache d'Odin

    def take(self, n):
        if self.p + n > len(self.b):
            raise OdinFormatError(f"fin de fichier inattendue à 0x{self.p:X}")
        chunk = self.b[self.p:self.p + n]
        self.p += n
        return chunk

    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self):
        wide = self.unpack("<B")
        length = self.unpack("<i")
        if wide == 0:
            return self.take(length).decode("latin-1")
        if wide == 1:
            return self.take(length * 2).decode("utf-16-le")
        raise OdinFormatError(f"drapeau de chaîne inconnu {wide} à 0x{self.p - 5:X}")

    def type_entry(self):
        code = self.unpack("<B")
        if code == TYPE_NAME:
            tid = self.unpack("<i")
            name = self.string()
            self.types[tid] = name
            return name
        if code == TYPE_ID:
            tid = self.unpack("<i")
            if tid not in self.types:
                raise OdinFormatError(f"id de type inconnu {tid} à 0x{self.p:X}")
            return self.types[tid]
        if code == 0x2E:  # UnnamedNull : pas de type écrit
            return None
        raise OdinFormatError(f"entrée de type inattendue 0x{code:02X} à 0x{self.p - 1:X}")

    def scalar(self, kind):
        if kind is None:
            return None
        if kind == "string":
            return self.string()
        if kind == "guid":
            return self.take(16).hex()
        if kind == "raw16":
            return self.take(16).hex()
        if kind == "bool":
            return self.unpack("<B") != 0
        return self.unpack(kind)

    def entries(self, until):
        """Lit des entrées jusqu'au code de fin `until` (consommé).

        Au niveau racine (`until` = END_OF_STREAM), la fin du fichier suffit :
        le jeu n'écrit pas de marqueur de fin de flux.
        """
        out = []
        while True:
            start = self.p
            if until == END_OF_STREAM and self.p == len(self.b):
                self.saw_eos = False
                return out
            code = self.unpack("<B")
            if code == until:
                self.saw_eos = True
                return out
            if code in (END_OF_NODE, END_OF_ARRAY, END_OF_STREAM):
                raise OdinFormatError(f"fin 0x{code:02X} inattendue à 0x{start:X}")
            out.append(self.entry(code, start))

    def entry(self, code, start):
        if code in (NAMED_REF, UNNAMED_REF, NAMED_STRUCT, UNNAMED_STRUCT):
            e = {"t": "ref" if code <= UNNAMED_REF else "struct"}
            if code in (NAMED_REF, NAMED_STRUCT):
                e["n"] = self.string()
            e["type"] = self.type_entry()
            if e["t"] == "ref":
                e["id"] = self.unpack("<i")
            e["c"] = self.entries(END_OF_NODE)
            return e
        if code == START_OF_ARRAY:
            e = {"t": "array", "len": self.unpack("<q")}
            e["c"] = self.entries(END_OF_ARRAY)
            return e
        if code == PRIMITIVE_ARRAY:
            count = self.unpack("<i")
            size = self.unpack("<i")
            return {"t": "parray", "count": count, "size": size,
                    "hex": self.take(count * size).hex()}
        named = code if code % 2 == 1 else code - 1
        if named in SCALARS:
            name, kind = SCALARS[named]
            e = {"t": name}
            if code == named:
                e["n"] = self.string()
            if kind is not None:
                e["v"] = self.scalar(kind)
            return e
        raise OdinFormatError(f"code d'entrée inconnu 0x{code:02X} à 0x{start:X}")


def decode(data: bytes) -> dict:
    """Renvoie {"eos": bool, "root": [entrées]}."""
    r = Reader(data)
    root = r.entries(END_OF_STREAM)
    if r.p != len(data):
        raise OdinFormatError(f"{len(data) - r.p} octets en trop après la fin du flux")
    return {"eos": r.saw_eos, "root": root}


class Writer:
    def __init__(self):
        self.out = bytearray()
        self.types = {}  # nom de type -> id, attribué dans l'ordre d'apparition

    def pack(self, fmt, v):
        self.out += struct.pack(fmt, v)

    def string(self, s):
        # Le jeu écrit toutes ses chaînes en UTF-16 (drapeau 1).
        raw = s.encode("utf-16-le")
        self.pack("<B", 1)
        self.pack("<i", len(raw) // 2)
        self.out += raw

    def type_entry(self, name):
        if name is None:
            self.pack("<B", 0x2E)
        elif name in self.types:
            self.pack("<B", TYPE_ID)
            self.pack("<i", self.types[name])
        else:
            tid = len(self.types)
            self.types[name] = tid
            self.pack("<B", TYPE_NAME)
            self.pack("<i", tid)
            self.string(name)

    def entries(self, items, end):
        for e in items:
            self.entry(e)
        if end is not None:
            self.pack("<B", end)

    def entry(self, e):
        t = e["t"]
        named = "n" in e
        if t in ("ref", "struct"):
            code = NAMED_REF if t == "ref" else NAMED_STRUCT
            self.pack("<B", code if named else code + 1)
            if named:
                self.string(e["n"])
            self.type_entry(e["type"])
            if t == "ref":
                self.pack("<i", e["id"])
            self.entries(e["c"], END_OF_NODE)
        elif t == "array":
            self.pack("<B", START_OF_ARRAY)
            self.pack("<q", e["len"])
            self.entries(e["c"], END_OF_ARRAY)
        elif t == "parray":
            raw = bytes.fromhex(e["hex"])
            self.pack("<B", PRIMITIVE_ARRAY)
            self.pack("<i", e["count"])
            self.pack("<i", e["size"])
            self.out += raw
        else:
            code = SCALAR_CODE[t]
            kind = SCALARS[code][1]
            self.pack("<B", code if named else code + 1)
            if named:
                self.string(e["n"])
            v = e.get("v")
            if kind is None:
                pass
            elif kind == "string":
                self.string(v)
            elif kind in ("guid", "raw16"):
                self.out += bytes.fromhex(v)
            elif kind == "bool":
                self.pack("<B", 1 if v else 0)
            else:
                self.pack(kind, v)


def encode(doc: dict) -> bytes:
    w = Writer()
    w.entries(doc["root"], END_OF_STREAM if doc.get("eos") else None)
    return bytes(w.out)
