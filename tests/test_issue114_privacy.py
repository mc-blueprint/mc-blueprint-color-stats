from bench.issue114.privacy import classify, selection


def test_未検出と少量maskは主体が決まる場合だけ採用する():
    policy = {"subject_min": .01, "subject_margin": .02, "mask_max": .01}
    scan = {"subject_coverage": {"building": .5, "terrain": .1},
            "person_ratio": 0, "mask_ratio": 0}
    assert classify(scan, policy) == ("accepted", "building", "person_not_detected")
    assert classify(scan | {"person_ratio": .005, "mask_ratio": .01}, policy) == (
        "accepted", "building", "person_masked")
    assert classify(scan | {"mask_ratio": .010001}, policy)[0] == "pending"
    assert classify(scan | {"subject_coverage": {"building": 0, "terrain": 0}}, policy) == (
        "pending", None, "subject_unresolved")
    assert classify(scan | {"subject_coverage": {"building": .5, "terrain": .49}}, policy) == (
        "pending", None, "subject_ambiguous")


def test_無作為サンプルは入力順に依存せず保留と閾値付近も含める():
    rows = [{"asset_id": str(i).zfill(4), "person_ratio": .001 if i % 3 else 0,
             "mask_ratio": .001, "decision": "pending" if i < 10 else "accepted"}
            for i in range(150)]
    chosen, random_ids, boundary = selection(rows, {"mask_max": .01})
    reversed_chosen, reversed_random, reversed_boundary = selection(
        list(reversed(rows)), {"mask_max": .01})
    assert chosen == reversed_chosen and random_ids == reversed_random
    assert boundary == reversed_boundary
    assert len(random_ids) == 100 and len(boundary) == 40
    assert {str(i).zfill(4) for i in range(10)} <= {row["asset_id"] for row in chosen}
