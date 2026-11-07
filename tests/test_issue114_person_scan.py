import numpy as np
import pytest
from bench.issue114.person_scan import subject_coverage
from PIL import Image


def test_主体は重なりを合算せずmask和集合で測る(tmp_path):
    path = tmp_path / "wall.png"
    Image.fromarray(np.array([[255, 0], [0, 0]], dtype=np.uint8)).save(path)
    assert subject_coverage([("wall", path), ("wall", path)], (2, 2), {"wall"}, set()) == {
        "building": 0.25, "terrain": 0.0,
    }
    with pytest.raises(ValueError, match="寸法"):
        subject_coverage([("wall", path)], (3, 3), {"wall"}, set())
