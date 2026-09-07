def test_get_leader_returns_highest_term(client, collections):
    collections.consensus.insert_one({"_id": 1, "term": 1, "leader_ids": ["n0"], "reported_by": ["n0"]})
    collections.consensus.insert_one({"_id": 3, "term": 3, "leader_ids": ["n1"], "reported_by": ["n0", "n1"]})
    collections.consensus.insert_one({"_id": 2, "term": 2, "leader_ids": ["n0"], "reported_by": ["n0"]})

    response = client.get("/consensus/leader")
    assert response.status_code == 200
    assert response.json()["term"] == 3
    assert response.json()["leader_ids"] == ["n1"]


def test_get_leader_returns_404_when_nothing_reported_yet(client):
    response = client.get("/consensus/leader")
    assert response.status_code == 404
