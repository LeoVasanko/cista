import msgspec

from cista.protocol import FileEntry, UpdateMessage, UpdDel, UpdIns, UpdKeep
from cista.watching import format_update


def decode(data: str):
    return msgspec.json.decode(data, type=UpdateMessage).update


# Helper function to create a list of FileEntry objects
def f(count, start=0):
    return [FileEntry(i, str(i), str(i), 0, 0, 0) for i in range(start, start + count)]


def test_identical_lists():
    old_list = f(3)
    new_list = old_list.copy()
    expected = [UpdKeep(3)]
    assert decode(format_update(old_list, new_list)) == expected


def test_completely_different_lists():
    old_list = f(3)
    new_list = f(3, 3)  # Different entries
    expected = [UpdDel(3), UpdIns(new_list)]
    assert decode(format_update(old_list, new_list)) == expected


def test_insertions():
    old_list = f(3)
    new_list = old_list[:2] + f(1, 10) + old_list[2:]
    expected = [UpdKeep(2), UpdIns(f(1, 10)), UpdKeep(1)]
    assert decode(format_update(old_list, new_list)) == expected


def test_insertion_at_end():
    old_list = [*f(3), FileEntry(1, "xxx", "xxx", 0, 0, 1)]
    newfile = FileEntry(1, "yyy", "yyy", 0, 0, 1)
    new_list = [*old_list, newfile]
    expected = [UpdKeep(4), UpdIns([newfile])]
    assert decode(format_update(old_list, new_list)) == expected


def test_deletions():
    old_list = f(3)
    new_list = [old_list[0], old_list[2]]
    expected = [UpdKeep(1), UpdDel(1), UpdKeep(1)]
    assert decode(format_update(old_list, new_list)) == expected


def test_mixed_operations():
    old_list = f(4)
    new_list = [old_list[0], old_list[2], *f(1, 10)]
    expected = [UpdKeep(1), UpdDel(1), UpdKeep(1), UpdDel(1), UpdIns(f(1, 10))]
    assert decode(format_update(old_list, new_list)) == expected


def test_empty_old_list():
    old_list = []
    new_list = f(3)
    expected = [UpdIns(new_list)]
    assert decode(format_update(old_list, new_list)) == expected


def test_empty_new_list():
    old_list = f(3)
    new_list = []
    expected = [UpdDel(3)]
    assert decode(format_update(old_list, new_list)) == expected


def test_longer_lists():
    old_list = f(6)
    new_list = f(1, 6) + old_list[1:3] + old_list[4:5] + f(2, 7)
    expected = [
        UpdDel(1),
        UpdIns(f(1, 6)),
        UpdKeep(2),
        UpdDel(1),
        UpdKeep(1),
        UpdDel(1),
        UpdIns(f(2, 7)),
    ]
    assert decode(format_update(old_list, new_list)) == expected


def sortkey(name):
    # Define the sorting key for names here
    return name.lower()
