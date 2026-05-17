def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def test_add():
    assert add(2, 2) == 4

def test_subtract():
    # This test is intentionally broken
    assert subtract(2, 2) == 1
