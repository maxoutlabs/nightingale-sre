# Scenario 3: Logic Bug
# Bug: fibonacci() returns 'a' instead of 'b' at the end of the loop.

def fibonacci(n):
    """Return the nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1, fib(2)=1, ...)."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return a  # BUG: should be `return b`


def test_fibonacci_base_cases():
    assert fibonacci(0) == 0
    assert fibonacci(1) == 1


def test_fibonacci_small():
    # fib sequence: 0,1,1,2,3,5,8,13,21,34,55
    assert fibonacci(2) == 1   # passes (a=1 after 1 loop iter, but b=1 too)
    assert fibonacci(3) == 2   # FAILS: returns a=1, expected b=2
    assert fibonacci(4) == 3   # FAILS: returns a=2, expected b=3


def test_fibonacci_large():
    assert fibonacci(5) == 5    # FAILS: returns 3, expected 5
    assert fibonacci(10) == 55  # FAILS: returns 34, expected 55
