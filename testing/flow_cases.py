"""Assert shapes shared by the host tests and the RPython flow tests.

``entry`` dispatches to every shape so that one annotation covers them all:
they have to unify in a single RPython program.
"""

SOURCE = """
from cot_assert import annotated

def compare(x, y):
    assert x + 1 == y
    return x

def boolop(x, y):
    assert x > 0 and (y > 0 or y < -5), "x and y"
    return x + y

def chain(x, y):
    assert 0 < x < y
    return y - x

def strings(n):
    s = "ok" if n else "nope"
    assert s == "ok"
    return len(s)

class Box(object):
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

def attributes(n):
    box = Box(n)
    assert box.get() * 2 == box.value + 4
    return n

def manual(n):
    if n > 3:
        raise annotated("n too big").annotate("n", n).annotate("half", n / 2.0)
    return n

def entry(which, a, b):
    if which == 0:
        return compare(a, b)
    if which == 1:
        return boolop(a, b)
    if which == 2:
        return chain(a, b)
    if which == 3:
        return strings(a)
    if which == 4:
        return attributes(a)
    return manual(a)
"""

# (args, result) where the asserts hold
PASSING = [
    ((0, 1, 2), 1),
    ((1, 1, 2), 3),
    ((1, 1, -6), -5),
    ((2, 1, 2), 1),
    ((3, 1, 0), 2),
    ((4, 4, 0), 4),
    ((5, 2, 0), 2),
]

# (args, path, message, labels, values) for failing ones; values as RPython
# renders them
FAILING = [
    ((0, 1, 5), 0, None, ["x", "x + 1", "y"], ["1", "2", "5"]),
    ((1, -1, 5), 0, "x and y", ["x"], ["-1"]),
    ((1, 1, -3), 1, "x and y", ["x", "y", "y"], ["1", "-3", "-3"]),
    ((2, 0, 2), 0, None, ["x"], ["0"]),
    ((2, 3, 2), 1, None, ["x", "y"], ["3", "2"]),
    ((3, 0, 0), 0, None, ["s"], ["'nope'"]),
    (
        (4, 3, 0),
        0,
        None,
        ["box", "box.get()", "box.get() * 2", "box", "box.value", "box.value + 4"],
        ["<object>", "3", "6", "<object>", "3", "7"],
    ),
    ((5, 5, 0), 0, "n too big", ["n", "half"], ["5", "2.5"]),
]
