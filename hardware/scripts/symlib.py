"""Load symbols out of KiCad 10's split symbol libraries.

KiCad 10 stores each library as a ``<Nickname>.kicad_symdir`` directory holding
one ``.kicad_sym`` file per symbol.  Many symbols are *derived*: they carry an
``(extends "Parent")`` node and inherit the parent's pins and graphics.  A
schematic's ``lib_symbols`` cache must contain the flattened result, so this
module resolves ``extends`` the same way KiCad does.
"""

import math
import os

import kisexp
from kisexp import Atom, QStr


class SymbolLibrary:
    def __init__(self, symbol_root):
        self.root = symbol_root
        self._raw_cache = {}
        self._flat_cache = {}

    # ------------------------------------------------------------------ io
    def _raw(self, nickname, name):
        """The symbol node exactly as stored on disk, un-flattened."""
        key = (nickname, name)
        if key in self._raw_cache:
            return self._raw_cache[key]
        path = os.path.join(self.root, "%s.kicad_symdir" % nickname, "%s.kicad_sym" % name)
        if not os.path.exists(path):
            raise FileNotFoundError("no symbol %s:%s at %s" % (nickname, name, path))
        with open(path) as fh:
            lib = kisexp.parse_one(fh.read())
        for node in kisexp.find_all(lib, "symbol"):
            if str(node[1]) == name:
                self._raw_cache[key] = node
                return node
        raise KeyError("library file %s does not define %s" % (path, name))

    # ------------------------------------------------------------ flatten
    def flat(self, lib_id):
        """Flattened symbol node, renamed to ``lib_id`` (``"Lib:Name"``)."""
        if lib_id in self._flat_cache:
            return self._flat_cache[lib_id]
        nickname, name = lib_id.split(":", 1)
        node = self._resolve(nickname, name)
        node = [Atom("symbol"), QStr(lib_id)] + node[2:]
        self._flat_cache[lib_id] = node
        return node

    def _resolve(self, nickname, name):
        node = self._raw(nickname, name)
        extends = kisexp.find(node, "extends")
        if extends is None:
            return _deepcopy(node)

        parent_name = str(extends[1])
        parent = self._resolve(nickname, parent_name)

        merged = [Atom("symbol"), QStr(name)]
        child_props = {str(p[1]): p for p in kisexp.find_all(node, "property")}
        seen = set()

        for item in parent[2:]:
            if not isinstance(item, list):
                merged.append(item)
                continue
            tag = kisexp.head(item)
            if tag == "property":
                pname = str(item[1])
                seen.add(pname)
                # The child's own value wins where it defines one.
                merged.append(_deepcopy(child_props.get(pname, item)))
            elif tag == "symbol":
                # Sub-unit graphics/pins: rename PARENT_u_b -> CHILD_u_b.
                sub = _deepcopy(item)
                suffix = str(sub[1])[len(parent_name):]
                sub[1] = QStr(name + suffix)
                merged.append(sub)
            else:
                merged.append(_deepcopy(item))

        # Properties the child adds that the parent never had.
        tail = [p for pname, p in child_props.items() if pname not in seen]
        if tail:
            insert_at = len(merged)
            for i, item in enumerate(merged):
                if isinstance(item, list) and kisexp.head(item) == "symbol":
                    insert_at = i
                    break
            merged[insert_at:insert_at] = [_deepcopy(p) for p in tail]

        return merged

    # --------------------------------------------------------------- pins
    def pins(self, lib_id, unit=1):
        """pin number -> dict(x, y, angle, length, name, etype).

        Coordinates are symbol-space millimetres (Y up), as stored in the
        library.  Sub-units ``*_0_*`` hold shared graphics; ``*_<unit>_*`` hold
        that unit's pins.
        """
        node = self.flat(lib_id)
        bare = lib_id.split(":", 1)[1]
        out = {}
        for sub in kisexp.find_all(node, "symbol"):
            subname = str(sub[1])
            parts = subname[len(bare) + 1:].split("_") if subname.startswith(bare + "_") else []
            if len(parts) != 2:
                continue
            sub_unit = int(parts[0])
            if sub_unit not in (0, unit):
                continue
            for pin in kisexp.find_all(sub, "pin"):
                at = kisexp.find(pin, "at")
                number = kisexp.find(pin, "number")
                name = kisexp.find(pin, "name")
                out[str(number[1])] = {
                    "x": float(at[1]),
                    "y": float(at[2]),
                    "angle": float(at[3]) if len(at) > 3 else 0.0,
                    "length": float(kisexp.value(pin, "length", Atom("2.54"))),
                    "name": str(name[1]) if name else "",
                    "etype": str(pin[1]),
                }
        return out

    def unit_count(self, lib_id):
        node = self.flat(lib_id)
        bare = lib_id.split(":", 1)[1]
        units = set()
        for sub in kisexp.find_all(node, "symbol"):
            subname = str(sub[1])
            if subname.startswith(bare + "_"):
                parts = subname[len(bare) + 1:].split("_")
                if len(parts) == 2 and parts[0].isdigit():
                    units.add(int(parts[0]))
        units.discard(0)
        return max(units) if units else 1

    def is_power(self, lib_id):
        return kisexp.find(self.flat(lib_id), "power") is not None

    # ------------------------------------------------------------- extent
    def extent(self, lib_id):
        """(min_x, min_y, max_x, max_y) of the symbol's drawn body, symbol-space."""
        node = self.flat(lib_id)
        xs, ys = [], []

        def walk(n):
            tag = kisexp.head(n)
            if tag == "xy" and len(n) >= 3:
                xs.append(float(n[1]))
                ys.append(float(n[2]))
            elif tag in ("start", "end", "center", "mid") and len(n) >= 3:
                xs.append(float(n[1]))
                ys.append(float(n[2]))
            elif tag == "pin":
                at = kisexp.find(n, "at")
                if at:
                    xs.append(float(at[1]))
                    ys.append(float(at[2]))
            for c in n:
                if isinstance(c, list):
                    walk(c)

        walk(node)
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))


def pin_endpoint(pin, origin):
    """Schematic-space (x, y) of a pin's connection point.

    Symbol libraries use Y-up, schematics use Y-down, so the symbol Y is
    negated when a symbol is placed at ``origin`` with no rotation or mirror.
    """
    ox, oy = origin
    return (round(ox + pin["x"], 4), round(oy - pin["y"], 4))


def pin_outward(pin):
    """Unit vector, in schematic space, pointing away from the symbol body.

    A pin's ``(at x y angle)`` is its free end and ``angle`` points from there
    into the body, so a stub continues in the opposite direction.
    """
    rad = math.radians(pin["angle"])
    return (-round(math.cos(rad), 6), round(math.sin(rad), 6))


def _deepcopy(node):
    if isinstance(node, list):
        return [_deepcopy(c) for c in node]
    return node
