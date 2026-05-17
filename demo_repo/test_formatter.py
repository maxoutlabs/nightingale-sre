# Scenario 2: Broken Import
# Bug: 'DefaultDict' does not exist in collections (correct name is 'defaultdict')

from collections import OrderedDict, DefaultDict  # ImportError: cannot import name 'DefaultDict'


def group_by_first_char(items):
    """Group strings by their first character."""
    result = DefaultDict(list)
    for item in items:
        if item:
            result[item[0].lower()].append(item)
    return dict(result)


def test_group_empty():
    assert group_by_first_char([]) == {}


def test_group_basic():
    result = group_by_first_char(["apple", "avocado", "banana"])
    assert "a" in result
    assert len(result["a"]) == 2
    assert "b" in result
    assert result["b"] == ["banana"]


def test_group_case_insensitive():
    result = group_by_first_char(["Apple", "avocado"])
    assert "a" in result
    assert len(result["a"]) == 2
