"""Per-runner key derivation (N1).

The property that matters: a key must be reproducible from the master secret
plus the label nonce alone, because that is all a restarted orchestrator has.
If this breaks, adoption silently produces runners nobody can authenticate to.
"""
from app.keys import derive_key, mint_nonce

SECRET = "master-secret-for-tests"


def test_derivation_is_reproducible():
    n = mint_nonce()
    assert derive_key(SECRET, "u-alice", n) == derive_key(SECRET, "u-alice", n)


def test_key_changes_with_every_input():
    n1, n2 = mint_nonce(), mint_nonce()
    base = derive_key(SECRET, "u-alice", n1)
    assert base != derive_key(SECRET, "u-bob", n1), "uid must affect the key"
    assert base != derive_key(SECRET, "u-alice", n2), "nonce must affect the key"
    assert base != derive_key("other-secret", "u-alice", n1), "secret must affect it"


def test_uid_and_nonce_cannot_be_transposed():
    # A naive f"{uid}{nonce}" concatenation would collide here. The separator
    # is what stops ("ab","c") and ("a","bc") producing the same key.
    assert derive_key(SECRET, "ab", "c") != derive_key(SECRET, "a", "bc")


def test_nonces_are_unique_and_hex():
    seen = {mint_nonce() for _ in range(500)}
    assert len(seen) == 500
    assert all(len(n) == 32 and int(n, 16) >= 0 for n in seen)


def test_key_shape():
    k = derive_key(SECRET, "u-alice", mint_nonce())
    assert len(k) == 64 and int(k, 16) >= 0
