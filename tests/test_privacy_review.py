import pytest

from colorstats.privacy_review import decision, is_new


@pytest.mark.parametrize("people,pixels,accepted", [
    ("absent", 0, True),  # 像・絵も両方の根拠が陰性であることを必要とする。
    ("present", 0, False), ("present", 1, False), ("present", 500, False),
    ("absent", 1, False), ("uncertain", 0, False), (None, 0, False),
    ("absent", None, False),
])
def test_二つの陰性根拠以外は採用しない(people, pixels, accepted):
    assert (decision(people, pixels)["decision"] == "accepted") is accepted


def test_新版の欠損参照を旧契約として扱わない():
    assert is_new({"contract": "image-review-v1"})
    assert is_new({"privacy_review_run_id": "missing"})
    assert not is_new({"person_mask": None})


@pytest.mark.parametrize("key", ["contract", "image_gate_hash", "privacy_review_hash",
                                 "region_policy_hash", "image_gate_input_sha256",
                                 "person_mask_sha256", "analysis_domain"])
def test_新版の項目はnullだけでも旧契約にならない(key):
    assert is_new({key: None})
