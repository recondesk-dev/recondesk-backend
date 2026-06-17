from app.utils.helpers import flatten_dict, safe_float, slugify, truncate


def test_slugify():
    assert slugify("Hello World!") == "hello-world"
    assert slugify("  Invoice #001  ") == "invoice-001"


def test_flatten_dict():
    nested = {"a": {"b": {"c": 1}}, "d": 2}
    flat = flatten_dict(nested)
    assert flat == {"a.b.c": 1, "d": 2}


def test_safe_float():
    assert safe_float("3.14") == 3.14
    assert safe_float("bad", default=0.0) == 0.0
    assert safe_float(None) == 0.0


def test_truncate():
    assert truncate("Hello", max_length=10) == "Hello"
    assert truncate("Hello World", max_length=8) == "Hello W…"
