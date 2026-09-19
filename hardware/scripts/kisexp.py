"""Minimal S-expression reader/writer for KiCad files.

Bare tokens and quoted strings are distinct in KiCad's format (``hide`` is a
keyword, ``"hide"`` is a string), so they are kept as distinct types here.
"""


class Atom(str):
    """A bare, unquoted token such as ``symbol``, ``yes`` or ``12.7``."""


class QStr(str):
    """A quoted string token."""


_WS = " \t\r\n"


def parse(text):
    """Parse a whole file into a list of top-level nodes."""
    pos = 0
    n = len(text)
    out = []
    while True:
        while pos < n and text[pos] in _WS:
            pos += 1
        if pos >= n:
            return out
        node, pos = _parse_node(text, pos)
        out.append(node)


def parse_one(text):
    nodes = parse(text)
    if len(nodes) != 1:
        raise ValueError("expected exactly one top-level node, got %d" % len(nodes))
    return nodes[0]


def _parse_node(text, pos):
    if text[pos] != "(":
        raise ValueError("expected '(' at offset %d" % pos)
    pos += 1
    items = []
    n = len(text)
    while True:
        while pos < n and text[pos] in _WS:
            pos += 1
        if pos >= n:
            raise ValueError("unexpected end of input")
        c = text[pos]
        if c == ")":
            return items, pos + 1
        if c == "(":
            node, pos = _parse_node(text, pos)
            items.append(node)
        elif c == '"':
            s, pos = _parse_qstr(text, pos)
            items.append(s)
        else:
            start = pos
            while pos < n and text[pos] not in _WS and text[pos] not in "()":
                pos += 1
            items.append(Atom(text[start:pos]))


def _parse_qstr(text, pos):
    pos += 1  # opening quote
    buf = []
    n = len(text)
    while pos < n:
        c = text[pos]
        if c == "\\":
            nxt = text[pos + 1]
            buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
            pos += 2
        elif c == '"':
            return QStr("".join(buf)), pos + 1
        else:
            buf.append(c)
            pos += 1
    raise ValueError("unterminated string")


def _quote(s):
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    return '"%s"' % out


def dumps(node, indent=0):
    """Serialise a node using KiCad's tab-indented layout."""
    if isinstance(node, Atom):
        return str(node)
    if isinstance(node, QStr):
        return _quote(node)
    if isinstance(node, str):
        # Anything else that arrived as a plain str is treated as a quoted value.
        return _quote(node)
    if not isinstance(node, list):
        raise TypeError("cannot serialise %r" % (node,))

    pad = "\t" * indent
    # Leading scalars stay on the opening line; child nodes go on their own lines.
    parts = []
    head = []
    i = 0
    while i < len(node) and not isinstance(node[i], list):
        head.append(dumps(node[i], 0))
        i += 1
    children = node[i:]

    if not children:
        return "%s(%s)" % (pad, " ".join(head))

    # A node whose children are all short scalar-only lists (e.g. (xy 1 2)) is
    # kept on one line, matching how KiCad writes point lists.
    if all(isinstance(c, list) and not any(isinstance(x, list) for x in c) for c in children) \
            and sum(len(dumps(c, 0)) for c in children) < 72 and len(children) > 1:
        inline = " ".join(dumps(c, 0) for c in children)
        if head:
            return "%s(%s\n%s\t%s\n%s)" % (pad, " ".join(head), pad, inline, pad)
        return "%s(%s)" % (pad, inline)

    parts.append("%s(%s" % (pad, " ".join(head)) if head else "%s(" % pad)
    for c in children:
        parts.append(dumps(c, indent + 1))
    parts.append("%s)" % pad)
    return "\n".join(parts)


# ---------------------------------------------------------------- accessors

def head(node):
    return str(node[0]) if node and not isinstance(node[0], list) else None


def find_all(node, name):
    """Direct children of ``node`` whose head token is ``name``."""
    return [c for c in node if isinstance(c, list) and head(c) == name]


def find(node, name):
    got = find_all(node, name)
    return got[0] if got else None


def value(node, name, default=None):
    """The first scalar after the head token of child ``name``."""
    child = find(node, name)
    if child is None or len(child) < 2:
        return default
    return child[1]
