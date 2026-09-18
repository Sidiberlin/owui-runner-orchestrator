"""Container/volume name derivation from an OWUI user id.

Docker names allow [a-zA-Z0-9_.-] and must start alphanumeric. The raw uid
always survives on a label, so collapsing to a hash loses nothing.
"""
from app.runners import safe_uid


def test_ordinary_uuid_passes_through():
    u = "9f8c1a2b-3d4e-5f60-7182-93a4b5c6d7e8"
    assert safe_uid(u) == u


def test_unsafe_characters_collapse_to_a_hash():
    for bad in ["../etc/passwd", "a b", "a/b", "a:b", "a$b", "a;rm -rf /"]:
        out = safe_uid(bad)
        assert out.isalnum() and len(out) == 32, bad


def test_leading_non_alphanumeric_is_hashed():
    # Docker rejects a leading '_' or '-'; this must not reach the daemon.
    assert len(safe_uid("_leading")) == 32
    assert len(safe_uid("-leading")) == 32


def test_overlong_uid_is_hashed():
    assert len(safe_uid("a" * 200)) == 32


def test_hashing_is_deterministic_and_distinct():
    assert safe_uid("a/b") == safe_uid("a/b")
    assert safe_uid("a/b") != safe_uid("a/c")


def test_distinct_unsafe_uids_do_not_collide():
    # Naive sanitising maps both of these to "a-b" and would hand two users
    # the same container and the same workspace volume.
    assert safe_uid("a/b") != safe_uid("a:b")
