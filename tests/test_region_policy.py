import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from colorstats.analyze import color, region_policy, segment, shade
from colorstats.queue.core import Claim, NonRetryableError
from colorstats.stats.snapshot import _groups
from tests.test_segment import payload as payload


def prediction(image, payload, parameters):
    semantic = np.zeros((image.height, image.width), dtype=np.uint8)
    semantic[0, :4] = [2, 12, 1, 4]
    semantic[1, :2] = 8
    mask = np.ones(semantic.shape, dtype=bool)
    rows = [(label, (semantic == 8) if label.startswith("window_") else mask.copy(),
             0.99 if label == "window_frame" else 0.5)
            for label in payload["prompts"]]
    return semantic, rows, {"batch_size": 1}


@pytest.fixture
def regional_payload(payload, monkeypatch):
    with Image.open(payload["input_path"]) as image:
        pixels = np.array(image)
    pixels[0, :4] = [[0, 0, 255], [255, 0, 0], [255, 165, 0], [0, 128, 0]]
    pixels[1, :2] = [0, 255, 255]
    Image.fromarray(pixels).save(payload["input_path"])
    root = Path(payload["input_path"]).parent / "oneformer"
    root.mkdir()
    labels = json.loads(Path(region_policy.__file__).with_name("oneformer-labels.json").read_text())
    for name in region_policy.MODEL_FILES:
        (root / name).write_text("fixture", encoding="utf-8")
    (root / "config.json").write_text(json.dumps({"id2label": labels}), encoding="utf-8")
    (root / "preprocessor_config.json").write_text(json.dumps({"metadata": labels}),
                                                   encoding="utf-8")
    files = {p.name: segment._hash(p) for p in root.iterdir()}
    monkeypatch.setattr(region_policy, "MODEL_FILES", files)
    (root / "provenance.json").write_text(json.dumps({
        "repository": region_policy.REPOSITORY, "revision": region_policy.REVISION,
        "license": "MIT", "files": files,
    }), encoding="utf-8")
    payload.update(method=region_policy.METHOD, input_run_id=str(uuid.uuid4()),
                   input_sha256=segment._hash(payload["input_path"]), prompts={
                       "wall_main": "wall", "wall_secondary": "secondary wall",
                       "vegetation_tree_canopy": "tree", "tree_trunk": "tree trunk",
                       "rock_face": "rock", "window_glass": "glass", "window_frame": "frame",
                   })
    payload["model_paths"]["oneformer"] = str(root)
    return payload


def make_claim(payload, handler, stage):
    return Claim(uuid.uuid4(), uuid.uuid4(), stage, uuid.uuid4(), handler.config_hash(payload),
                 payload, 1, datetime.now(UTC))


@pytest.fixture
def policy_payload(regional_payload, monkeypatch):
    from colorstats.analyze import segment_models

    monkeypatch.setattr(segment_models, "predict_regions", prediction)
    prepared = segment.prepare(make_claim(regional_payload, segment, "segment"))
    for temporary, target in prepared.files:
        temporary.replace(target)
    policy = copy.deepcopy(prepared.data["region_policy"])
    run_id = str(uuid.uuid4())
    policy["run_id"] = run_id
    return {"input_path": regional_payload["input_path"],
            "input_sha256": regional_payload["input_sha256"],
            "input_run_id": regional_payload["input_run_id"], "region_run_id": run_id,
            "region_policy": policy, "regions": [], "taxonomy_version": "0.1.0",
            "license_class": "open", "output_path": str(Path(regional_payload["output_path"])
                                                        .with_name("colors.json"))}


def test_exclusion_union_conflict_and_missing():
    semantic = np.array([[2, 12, 1, 0, 4, 34, 8, 16, 19]], dtype=np.uint8)
    mask = np.ones(semantic.shape, dtype=bool)
    labels = ["wall_main", "wall_secondary", "tree_trunk", "vegetation_tree_canopy",
              "rock_face", "rock_scree", "window_glass", "window_frame", "snow_ice"]
    original = mask.copy()
    rows = []
    for label in labels:
        candidate = mask
        if label.startswith("window_"):
            candidate = semantic == 8
        elif label == "rock_scree":
            candidate = semantic == 34
        elif label == "snow_ice":
            candidate = np.zeros(semantic.shape, dtype=bool)
        rows.append((label, candidate, 1))
    masks, reasons, metrics = region_policy.constrain(semantic, rows, labels)
    assert masks["real_building/wall"].sum() == 2
    assert masks["real_terrain/tree"].sum() == 1
    assert masks["real_terrain/rock_face"].sum() == 1
    assert reasons["conflict"].sum() == 2
    assert reasons["sky"].sum() == reasons["person"].sum() == 1
    assert reasons["semantic_mismatch"].sum() == 1
    assert "real_terrain/snow_ice" in metrics["missing_roles"]
    assert metrics["coverage"] == 4 / 9 and metrics["void_rate"] == 5 / 9
    assert np.max(sum(masks.values())) == 1
    np.testing.assert_array_equal(mask, original)


def test_all_void_is_reported_as_missing():
    semantic = np.array([[2, 12, 1]], dtype=np.uint8)
    masks, reasons, metrics = region_policy.constrain(semantic, [], ["wall_main"])
    assert not masks["real_building/wall"].any()
    assert metrics["coverage"] == 0 and metrics["void_rate"] == 1
    assert metrics["missing_roles"] == ["real_building/wall"]
    assert reasons["person"].sum() == reasons["sky"].sum() == 1
    assert metrics["semantic_pixels"] == {"sky": 1, "person": 1}
    assert metrics["excluded_pixels"]["person"] == 0


def test_parent_table_covers_taxonomy_and_excludes_sky_person():
    from colorstats.schema.taxonomy import load_taxonomy

    taxonomy = load_taxonomy(Path("taxonomy"))
    labels = {label for group in taxonomy["parts"]["groups"].values() for label in group}
    labels.update(taxonomy["terrain"]["labels"])
    assert set(region_policy.ALLOW) == labels
    assert region_policy.parent_table_reference()["version"] == "ade-role-parents-v2"
    assert all(ids and ids == sorted(set(ids)) and not {2, 12} & set(ids)
               and all(0 <= value < 150 for value in ids) for ids in region_policy.ALLOW.values())
    assert not {4, 72} & set(region_policy.ALLOW["snow_ice"])
    assert not {16, 34, 68} & set(region_policy.ALLOW["vegetation_tree_canopy"])


@pytest.mark.parametrize("semantic_id", [0, 1, 25, 48, 51, 79, 84, 88])
def test_building_parent_clips_candidate_without_promoting_entire_building(semantic_id):
    semantic = np.full((1, 5), semantic_id, dtype=np.uint8)
    candidate = np.array([[False, True, True, False, False]])
    masks, _, metrics = region_policy.constrain(semantic, [("wall_main", candidate, 0.8)],
                                                ["wall_main"])
    np.testing.assert_array_equal(masks["real_building/wall"], candidate)
    assert metrics["coverage"] == 2 / 5


@pytest.mark.parametrize("label,semantic_id", [
    ("window_glass", 1), ("window_glass", 8), ("roof_surface", 1), ("roof_surface", 86),
    ("column", 42), ("stairs_entry", 53), ("railing", 95), ("ground_soil", 94),
    ("ground_grass", 17), ("rock_scree", 16), ("water", 109), ("snow_ice", 16),
])
def test_coarse_or_specific_parent_preserves_only_matching_candidate(label, semantic_id):
    semantic = np.array([[semantic_id, 2, 12]], dtype=np.uint8)
    masks, _, _ = region_policy.constrain(semantic, [(label, np.ones((1, 3), dtype=bool), 0.8)],
                                          [label])
    assert sum(int(mask.sum()) for mask in masks.values()) == 1


def test_parent_table_change_rejects_previous_result(policy_payload, monkeypatch):
    original = region_policy.parent_table_reference()
    monkeypatch.setitem(region_policy.ALLOW, "wall_main", [*region_policy.ALLOW["wall_main"], 14])
    assert region_policy.parent_table_reference()["sha256"] != original["sha256"]
    with pytest.raises(ValueError, match="policy hash"):
        color.config_hash(policy_payload)


@pytest.mark.parametrize("value", [np.array([[150]]), np.array([[-1]]), np.array([[0.0]])])
def test_invalid_semantic_class_map(value):
    with pytest.raises(ValueError, match="モデルID"):
        region_policy.constrain(value, [], ["wall_main"])


def test_ade_annotation_offset_and_processor_mismatch(regional_payload):
    root = Path(regional_payload["model_paths"]["oneformer"])
    labels = json.loads((root / "config.json").read_text())["id2label"]
    with pytest.raises(ValueError, match="モデルID"):
        region_policy.validate_labels({str(int(k) + 1): v for k, v in labels.items()})
    assert len(region_policy.validate_labels(labels)) == 64


@pytest.mark.parametrize("change", ["weight", "revision", "license", "extra"])
def test_model_provenance_rejects_changes(regional_payload, change):
    root = Path(regional_payload["model_paths"]["oneformer"])
    assert len(segment.config_hash(regional_payload)) == 64
    if change in {"revision", "license"}:
        record = json.loads((root / "provenance.json").read_text())
        record[change] = "other"
        (root / "provenance.json").write_text(json.dumps(record))
    else:
        (root / ("pytorch_model.bin" if change == "weight" else "extra.txt")).write_bytes(b"other")
    with pytest.raises(ValueError, match="証跡"):
        segment.config_hash(regional_payload)


def test_segment_preserves_raw_and_exports_semantic(policy_payload):
    policy = policy_payload["region_policy"]
    masks = region_policy.load_masks(policy_payload)
    raw = np.array(Image.open(Path(policy_payload["input_path"]).with_name("segments-0000.png")))
    assert np.all(raw == 255)
    assert masks["real_building/wall"].sum() == 43
    assert masks["real_terrain/tree"].sum() == 1
    assert not masks["real_building/window_frame"].any()
    assert not masks["real_building/window_glass"].any()
    semantic = np.array(Image.open(policy["semantic"]["path"]))
    assert semantic[0, :4].tolist() == [2, 12, 1, 4]
    assert policy["metrics"]["excluded_pixels"]["conflict"] == 2


@pytest.mark.parametrize("field", ["input", "sha", "size", "run", "policy", "mask", "jpeg"])
def test_policy_reuse_rejects_changed_pixels_coordinates_and_hashes(policy_payload, field):
    policy = policy_payload["region_policy"]
    if field == "input":
        Image.new("RGB", (8, 6), "blue").save(policy_payload["input_path"])
    elif field == "sha":
        policy_payload["input_sha256"] = "0" * 64
    elif field == "size":
        policy["size"] = [6, 8]
    elif field == "run":
        policy["run_id"] = str(uuid.uuid4())
    elif field == "policy":
        policy["policy_hash"] = "0" * 64
    else:
        record = policy["roles"]["real_building/wall"]
        if field == "mask":
            Path(record["path"]).write_bytes(b"bad")
        else:
            Image.new("L", (8, 6), 255).save(record["path"], format="JPEG")
            record["sha256"] = segment._hash(record["path"])
    with pytest.raises(ValueError):
        color.config_hash(policy_payload)


def test_color_and_shade_use_roles_without_child_observations(policy_payload):
    original = Path(policy_payload["input_path"]).read_bytes()
    colored = color.prepare(make_claim(policy_payload, color, "color"))
    payload = {**policy_payload, "method": "none"}
    shaded = shade.prepare(make_claim(payload, shade, "shade"))
    for result in (colored, shaded):
        assert not any(result.data[key] for key in ("observations", "regions", "relations"))
        assert result.data["roles"]["real_building/wall"]["area"] == 43
        assert result.data["roles"]["real_terrain/tree"]["area"] == 1
        assert result.data["roles"]["real_terrain/rock_face"]["missing"]
    observed = colored.data["roles"]["real_building/wall"]["observations"][0]["observed_oklab"]
    expected = color.extract_colors(Image.new("RGB", (1, 1), "orange"))[0]["observed_oklab"]
    assert observed["dominant"] == pytest.approx(expected["dominant"])
    assert observed["dominant"] == pytest.approx(shaded.data["roles"]["real_building/wall"]
                                               ["observations"][0]["observed_oklab"]["dominant"])
    assert Path(policy_payload["input_path"]).read_bytes() == original


def test_all_void_color_and_shade_are_missing_without_raw_fallback(policy_payload, monkeypatch):
    for record in policy_payload["region_policy"]["roles"].values():
        Image.new("L", (8, 6), 0).save(record["path"])
        record["sha256"] = segment._hash(record["path"])
    monkeypatch.setattr(shade, "correct", lambda *a, **k: pytest.fail("全面欠測で補正しない"))
    for handler, stage, extra in ((color, "color", {}), (shade, "shade", {"method": "gray-world"})):
        payload = {**policy_payload, **extra}
        data = handler.prepare(make_claim(payload, handler, stage)).data
        assert all(row["missing"] and not row["observations"] for row in data["roles"].values())


@pytest.mark.parametrize("field", ["mask_path", "person_mask"])
def test_new_policy_rejects_unversioned_additional_mask(policy_payload, field):
    policy_payload[field] = policy_payload["input_path"]
    with pytest.raises(ValueError, match="別のmask"):
        color.config_hash(policy_payload)


@pytest.mark.parametrize("size,orientation", [((8, 6), 6), ((2561, 1), 1)])
def test_segment_rejects_unbounded_or_unoriented_prep(regional_payload, size, orientation):
    image = Image.new("RGB", size, "orange")
    exif = Image.Exif()
    exif[274] = orientation
    image.save(regional_payload["input_path"], exif=exif)
    regional_payload["input_sha256"] = segment._hash(regional_payload["input_path"])
    with pytest.raises(ValueError, match="向き"):
        segment.config_hash(regional_payload)


def test_runner_refuses_old_segment_for_new_policy():
    from types import SimpleNamespace

    from ops.deploy.m3_analysis import _check_policy_reuse

    source = SimpleNamespace(parameters={"payload": {"method": "sam2-dino"}})
    with pytest.raises(ValueError, match="旧segment"):
        _check_policy_reuse(source, {"segment": {"method": region_policy.METHOD}})


def test_snapshot_reads_effective_roles_and_keeps_quality_pending(policy_payload):
    policy = copy.deepcopy(policy_payload["region_policy"])
    run_id = uuid.UUID(policy.pop("run_id"))
    segment_run = {"id": run_id, "parameters": {"region_policy": policy},
                   "output_paths": {r["path"]: r["path"] for r in [policy["semantic"],
                                    *policy["roles"].values(), *policy["exclusions"].values()]}}
    chosen = {"segment": run_id, "color": uuid.uuid4()}
    run = {"parameters": {"payload": policy_payload},
           "config_hash": color.config_hash(policy_payload)}
    groups = list(_groups({"id": uuid.uuid4(), "domain": "real_building"}, chosen, [],
                          run, segment_run, {}))
    wall = next(row for row in groups if row["role"] == "real_building/wall")
    assert wall["data"]["area"] == 43
    assert not wall["eligible"] and not wall["quality_eligible"]
    run["parameters"]["payload"] = {k: v for k, v in policy_payload.items() if k != "region_policy"}
    with pytest.raises(ValueError, match="region-policy"):
        list(_groups({"id": uuid.uuid4(), "domain": "real_building"}, chosen, [],
                     run, segment_run, {}))


@pytest.mark.parametrize("fail", [False, True])
def test_oneformer_restores_coordinates_offline_and_unloads_before_candidates(
    regional_payload, monkeypatch, fail,
):
    import sys
    from contextlib import nullcontext
    from functools import lru_cache
    from types import SimpleNamespace

    from colorstats.analyze import segment_models

    events = []
    active = []
    labels = json.loads(Path(region_policy.__file__).with_name("oneformer-labels.json").read_text())

    class Tensor:
        def to(self, device):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.zeros((6, 8), dtype=np.int64)

    class Inputs(dict):
        def to(self, device):
            return self

    class ImageProcessor:
        def __init__(self, **kwargs):
            assert Path(kwargs["repo_path"], kwargs["class_info_file"]).is_file()
            self.size = {}
            self._max_size = 0

    class Tokenizer:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            assert kwargs == {"local_files_only": True}
            return cls()

    class Processor:
        def __init__(self, image_processor, tokenizer):
            self.image_processor = image_processor
            events.append("processor-offline")

        def __call__(self, images, task_inputs, return_tensors):
            assert images.size == (8, 6) and task_inputs == ["semantic"]
            assert self.image_processor.size == {"shortest_edge": 640, "longest_edge": 2560}
            return Inputs()

        def post_process_semantic_segmentation(self, outputs, target_sizes):
            assert target_sizes == [(6, 8)]
            events.append("restore")
            return [Tensor()]

    class PositionEmbedding:
        @lru_cache(maxsize=1)  # noqa: B019 - 公式実装の保持を再現するfixture
        def forward(self, shape):
            return shape

    class Model:
        config = SimpleNamespace(id2label=labels)

        def __init__(self):
            self.position = PositionEmbedding()

        def modules(self):
            return [self, self.position]

        @classmethod
        def from_pretrained(cls, path, **kwargs):
            assert kwargs == {"local_files_only": True, "weights_only": True}
            active.append(True)
            return cls()

        def eval(self):
            return self

        def to(self, device):
            return self

        def __call__(self, **kwargs):
            assert self.position.forward((6, 8)) == (6, 8)
            if fail:
                raise MemoryError("CUDA out of memory")
            return Tensor()

        def __del__(self):
            active.clear()
            events.append("unload")

    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True, reset_peak_memory_stats=lambda: None,
                             synchronize=lambda: None, max_memory_allocated=lambda: 10,
                             max_memory_reserved=lambda: 20, OutOfMemoryError=MemoryError),
        manual_seed=lambda seed: None,
        inference_mode=nullcontext, autocast=lambda *a, **k: nullcontext(), bfloat16="bf16",
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        OneFormerProcessor=Processor, OneFormerForUniversalSegmentation=Model,
        OneFormerImageProcessor=ImageProcessor, CLIPTokenizer=Tokenizer,
    ))
    monkeypatch.setitem(sys.modules, "transformers.models.oneformer.modeling_oneformer",
                        SimpleNamespace(OneFormerSinePositionEmbedding=PositionEmbedding))
    monkeypatch.setattr("importlib.metadata.version", lambda name: {
        "torch": "2.11.0", "transformers": "4.57.6", "Pillow": "12.0.0",
    }[name])
    monkeypatch.setattr(segment_models, "_unload", lambda: events.append("clear-cache"))

    def candidates(*args, **kwargs):
        assert not active
        assert kwargs == {"transient": True}
        events.append("candidates")
        return [], {}

    monkeypatch.setattr(segment_models, "predict", candidates)
    with Image.open(regional_payload["input_path"]) as image:
        if fail:
            with pytest.raises(NonRetryableError, match="GPU_OOM"):
                segment_models.predict_regions(image, regional_payload,
                                               segment._configuration(regional_payload))
            assert "candidates" not in events
        else:
            semantic, _, metrics = segment_models.predict_regions(
                image, regional_payload, segment._configuration(regional_payload),
            )
            assert semantic.shape == (6, 8) and semantic.dtype == np.uint8
            assert events.index("unload") < events.index("candidates")
            assert metrics["oneformer_peak_allocated_bytes"] == 10
    assert not active and "clear-cache" in events
    assert PositionEmbedding.forward.cache_info().currsize == 0
