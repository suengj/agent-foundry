from sample_service import greet


def test_greet() -> None:
    assert greet("world") == "hello, world"
