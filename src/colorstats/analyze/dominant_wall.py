"""正面領域の最大色クラスタを壁の観測色にする。画素の部位正解は推定しない。"""

import numpy as np
from PIL import Image

from colorstats.analyze.color import extract_colors

VERSION = "dominant-wall-color-v3"


def estimate(image: Image.Image, front: np.ndarray, *, clusters: int) -> dict:
    """正面の不透明画素をOKLabで分類し、最大クラスタの平均色・面積比を返す。

    frontは同寸のbool mask、clustersは正整数。黒白も含め、入力は変更しない。
    正面なし・不透明画素なし・最大クラスタ同面積はcolor=Noneとmissing_reasonを返す。
    不正な寸法・型・clustersはValueError。壁材や照明補正の推定値ではない。
    """
    if not isinstance(clusters, int) or isinstance(clusters, bool) or clusters < 1:
        raise ValueError("clustersは正整数で指定してください")
    if front.dtype != np.bool_ or front.shape != (image.height, image.width):
        raise ValueError("frontは画像と同寸のbool maskが必要です")
    if not front.any():
        return {"color": None, "missing_reason": "front_not_found"}
    opaque = np.asarray(image.convert("RGBA"))[:, :, 3] == 255
    if not (front & opaque).any():
        return {"color": None, "missing_reason": "no_opaque_pixels"}
    rows = extract_colors(image, front, clusters=clusters, clip_extremes=False)
    if len(rows) > 1 and rows[0]["area_ratio"] == rows[1]["area_ratio"]:
        return {"color": None, "missing_reason": "dominant_tie"}
    return {"color": rows[0]["observed_oklab"]["dominant"], "missing_reason": None,
            "dominant_area_ratio": rows[0]["area_ratio"], "cluster_count": len(rows),
            "front_pixels": int((front & opaque).sum())}
