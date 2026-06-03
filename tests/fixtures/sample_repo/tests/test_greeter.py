from greeter import greet


def test_greet() -> None:
    assert greet() == "new"
