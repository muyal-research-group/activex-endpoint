from axo_shared.active_objects.models import ActiveObjectRecord


def test_active_object_record_is_frozen_and_defaults():
    record = ActiveObjectRecord(
        id="ao1", owner_user_id="user-1", class_name="MyActiveObject",
        state="RUNNING", created_at=100.0,
    )
    assert record.seen_on_endpoints == []


def test_active_object_record_tracks_multiple_endpoints_softly():
    record = ActiveObjectRecord(
        id="ao1", owner_user_id=None, class_name="MyActiveObject",
        state="RUNNING", created_at=100.0, seen_on_endpoints=["n0", "n1"],
    )
    assert record.seen_on_endpoints == ["n0", "n1"]
