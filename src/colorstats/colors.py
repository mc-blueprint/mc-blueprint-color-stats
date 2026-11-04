"""ブロック色と観測色で共通の色空間変換。"""

import sys

import colour
import numpy as np

if getattr(sys.modules.get("matplotlib"), "__spec__", None) is None:
    sys.modules.pop("matplotlib", None)

QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)


def rgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """0〜1のsRGB配列を、伝達関数を復号してOKLabへ変換する。"""
    xyz = colour.RGB_to_XYZ(
        rgb,
        colourspace=colour.RGB_COLOURSPACES["sRGB"],
        apply_cctf_decoding=True,
    )
    return np.asarray(colour.XYZ_to_Oklab(xyz))
