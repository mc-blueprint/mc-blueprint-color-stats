"""可視壁材の新policy。検出部位を壁から差し引き、旧policyは変更しない。"""

import json
from pathlib import Path

import numpy as np

from colorstats.analyze import region_policy
from colorstats.analyze.segment import _digest

METHOD = "oneformer-visible-wall-v2"
VERSION = "visible-wall-policy-v2"
WALL = "real_building/wall"
THRESHOLD = 0.35
WALL_THRESHOLD = 0.55
EXTRA_PROMPTS = {"exclude/balcony": "balcony", "exclude/shop": "shopfront",
                 "exclude/sill": "window sill"}
EXCLUDE_LABELS = {"plinth", "stairs_entry", "column", "beam", "corner_quoin", "half_timber",
                  "window_glass", "window_frame", "door", "shutter", "arch", "roof_surface",
                  "eave", "ridge", "gable_trim", "chimney", "dormer", "cornice", "band_course",
                  "railing", "relief", "accent_other", "vegetation_attached", "light_fixture"}


def configuration():
    """可視壁材の定義・候補閾値・除去対象と、改行に依存しないclass-info識別を返す。"""
    return {"version": VERSION, "definition": "窓・扉・装飾などを除いた、壁材が見えている面",
            "wall_threshold": WALL_THRESHOLD, "candidate_threshold": THRESHOLD,
            "other_building_threshold": WALL_THRESHOLD, "text_threshold": 0.25,
            "extra_prompts": EXTRA_PROMPTS, "exclude_labels": sorted(EXCLUDE_LABELS),
            "parents": region_policy.PARENT_TABLE, "roles": region_policy.PARENTS,
            "terrain": sorted(region_policy.TERRAIN), "transform": region_policy.TRANSFORM,
            "class_info": _digest(json.loads(Path(region_policy.__file__).with_name(
                "oneformer-classes.json").read_text("utf-8"))),
            "order": "raw-part-union-subtract-wall-then-parent-and-conflict-void"}


def policy_hash():
    return _digest(configuration())


def constrain(semantic, rows, labels, exclusion_rows=()):
    """親制約前の検出部位unionを壁から除き、排他role・理由・診断を返す。

    rowsは通常のtaxonomy候補、exclusion_rowsはEXTRA_PROMPTSの補助候補。
    confidenceは候補採否だけに使う。同親はunion、残る異role重複はvoid。
    検出されない部位の補完・GT利用はせず、入力を変更しない。
    """
    region_policy.constrain(semantic, rows, labels)
    parts = np.zeros(semantic.shape, dtype=bool)
    wall = parts.copy()
    for label, mask, score in rows:
        if label in EXCLUDE_LABELS and score > THRESHOLD:
            parts |= mask
        if region_policy.PARENTS.get(label) == WALL and score > WALL_THRESHOLD:
            wall |= mask
    for label, mask, score in exclusion_rows:
        if (label not in EXTRA_PROMPTS or mask.dtype != np.bool_ or mask.shape != semantic.shape
                or not 0 <= score <= 1):
            raise ValueError("壁の補助除去候補のラベル・寸法・型が不正です")
        if score > THRESHOLD:
            parts |= mask
    accepted = []
    for label, mask, score in rows:
        if score > (THRESHOLD if label in region_policy.TERRAIN else WALL_THRESHOLD):
            accepted.append((label, mask & ~parts if region_policy.PARENTS.get(label) == WALL
                             else mask, score))
    masks, reasons, metrics = region_policy.constrain(semantic, accepted, labels)
    reasons["wall_parts"] = wall & parts
    metrics["wall_before_subtraction_pixels"] = int(wall.sum())
    metrics["wall_subtracted_pixels"] = int((wall & parts).sum())
    metrics["wall_remaining_candidate_pixels"] = int((wall & ~parts).sum())
    metrics["auxiliary_candidates"] = len(exclusion_rows)
    return masks, reasons, metrics
