"""Config parsing. These run on every operator-supplied string in .env."""
import pytest

from app.config import parse_duration, parse_size


@pytest.mark.parametrize("text,expected", [
    ("1g", 1024**3), ("768m", 768 * 1024**2), ("5G", 5 * 1024**3),
    ("512k", 512 * 1024), ("2gb", 2 * 1024**3), ("1024", 1024),
    ("1.5g", int(1.5 * 1024**3)), (" 320m ", 320 * 1024**2),
])
def test_parse_size(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("30m", 1800), ("45s", 45), ("2h", 7200), ("1d", 86400), ("90", 90),
])
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("bad", ["", "abc", "10x", "g", "1 2 3"])
def test_bad_values_raise_rather_than_defaulting(bad):
    # Silently defaulting a typo'd limit is how a host ends up unprotected.
    with pytest.raises(ValueError):
        parse_size(bad)
