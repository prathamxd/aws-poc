"""Unit tests that need only the Python standard library."""
from app.security import hash_password, verify_password
from app.workflow import STATUSES, can_transition, next_statuses


def test_password_hash_roundtrip():
    stored = hash_password("S3cure-pass")
    assert stored.startswith("pbkdf2_sha256$")
    assert "S3cure-pass" not in stored
    assert verify_password("S3cure-pass", stored)
    assert not verify_password("wrong", stored)


def test_password_hashes_are_salted():
    assert hash_password("same") != hash_password("same")


def test_verify_rejects_malformed_hash():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "md5$1$00$00")


def test_forward_workflow():
    assert can_transition("Open", "In Progress")
    assert can_transition("In Progress", "Resolved")
    assert can_transition("Resolved", "Closed")


def test_reopen_resolved():
    assert can_transition("Resolved", "In Progress")


def test_blocked_transitions():
    assert not can_transition("Open", "Closed")
    assert not can_transition("Open", "Resolved")
    assert not can_transition("Closed", "Open")
    assert not can_transition("Open", "Open")
    assert not can_transition("Unknown", "Open")


def test_next_statuses_follow_display_order():
    assert next_statuses("Resolved") == ["In Progress", "Closed"]
    assert next_statuses("Closed") == []
    assert STATUSES == ["Open", "In Progress", "Resolved", "Closed"]
