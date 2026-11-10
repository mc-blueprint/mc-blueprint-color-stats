"""表示用の訳語。処理定義の根拠はdocs/region-policy.mdとregion-parents-v2.md。"""

NAMES = {
    "plinth": "基部・台座", "stairs_entry": "入口階段",
    "wall_main": "主壁", "wall_secondary": "副壁", "gable_wall": "妻壁",
    "column": "柱", "beam": "梁", "corner_quoin": "隅石", "half_timber": "木骨",
    "window_glass": "窓ガラス", "window_frame": "窓枠", "door": "戸・扉",
    "shutter": "窓の戸・日除け", "arch": "アーチ", "roof_surface": "屋根面",
    "eave": "軒", "ridge": "棟", "gable_trim": "妻側の縁飾り", "chimney": "煙突",
    "dormer": "屋根窓", "cornice": "コーニス", "band_course": "帯状石材",
    "railing": "手すり", "relief": "浮彫", "accent_other": "その他の建築装飾",
    "path": "舗装された歩行面", "fence": "柵", "vegetation_attached": "付着植物",
    "light_fixture": "照明器具", "floor_visible": "可視の床・地面",
    "ground_soil": "土の地面", "ground_grass": "草地", "rock_face": "岩面",
    "rock_scree": "岩屑", "sand": "砂地", "snow_ice": "雪・氷", "water": "水域",
    "vegetation_low": "低い植生", "vegetation_tree_canopy": "樹冠",
    "tree_trunk": "幹", "path_natural": "自然の道",
    "wall": "壁（主壁・副壁・妻壁の和集合）", "tree": "立木（樹冠・幹の和集合）",
}

# 親表の「根拠」を表示に使う。物理的な細分境界を親クラスから推測しない。
NOTES = {
    "plinth": "基部・台座の候補を壁・建物・baseで制約する。",
    "stairs_entry": "入口階段の候補を建物・stairs・stairway・stepで制約する。",
    "column": "柱候補を壁・建物・columnで制約する。",
    "beam": "梁候補を壁・建物で制約する。専用の親クラスはない。",
    "corner_quoin": "隅石候補を壁・建物で制約する。専用の親クラスはない。",
    "half_timber": "木骨候補を壁・建物で制約する。専用の親クラスはない。",
    "window_glass": "窓ガラス候補を建物・windowで制約する。窓枠との競合は除く。",
    "window_frame": "窓枠候補を壁・建物・windowで制約する。窓ガラスとの競合は除く。",
    "door": "戸の候補を建物・door・screen doorで制約する。",
    "shutter": "窓付属の戸・日除け候補を建物・window・blindで制約する。",
    "arch": "アーチ候補を壁・建物・戸・柱で制約する。",
    "roof_surface": "屋根候補を建物・awning・canopyで制約する。屋根専用の親はない。",
    "eave": "軒候補を建物・awning・canopyで制約する。屋根面との細分条件は定義未記載。",
    "ridge": "棟候補を建物の範囲に限定する。専用の親クラスはない。",
    "gable_trim": "妻側の縁飾り候補を壁・建物で制約する。",
    "chimney": "煙突候補を壁・建物で制約する。室内fireplaceは親に含めない。",
    "dormer": "屋根窓候補を建物・windowで制約する。",
    "cornice": "コーニス候補を壁・建物で制約する。装飾同士の細分条件は定義未記載。",
    "band_course": "横方向の石材帯の候補を壁・建物で制約する。",
    "railing": "手すり候補を建物またはfence・rail・bannisterで制約する。",
    "relief": "建物表面の浮彫候補を壁・建物・sculptureで制約する。",
    "accent_other": "建物表面の装飾候補を壁・建物・sculptureで制約する。その他の範囲は定義未記載。",
    "path": "歩行面の候補をfloor・road・sidewalk・pathで制約し、建物全体は親に含めない。",
    "fence": "柵候補をfence・rail・bannisterの専用クラスで制約し、建物全体は親に含めない。",
    "vegetation_attached": "付着植物候補をtree・plant・flower・palmで制約する。",
    "light_fixture": "照明候補を建物または照明の専用クラスで制約する。",
    "floor_visible": "可視床・地面の候補をfloor・sidewalk・earth・path・landで制約する。",
    "ground_soil": "裸地・耕地・土の道に属する地面候補を残す。",
    "ground_grass": "草・植物・耕地に属する草地候補を残す。立木全体は含めない。",
    "rock_face": "mountain・rock・hillに属する岩面候補を残す。山全体を岩面にはしない。",
    "rock_scree": "地面・山・岩・丘・陸地に属する岩屑候補を残す。",
    "sand": "一般地面・sand・landに属する砂地候補を残す。",
    "snow_ice": ("地表・山・岩・丘・陸地にある雪候補を残す。"
                 "雪専用の親はなく、地面全体を雪にはしない。"),
    "water": "水・海・川・プール・滝・湖に属する水域候補を残す。",
    "vegetation_low": "草・植物・耕地・花に属する低い植生候補を残す。",
    "vegetation_tree_canopy": "tree・palmに属する樹冠候補を残す。",
    "tree_trunk": "tree・palmに属する幹候補を残す。",
    "path_natural": "earth・path・dirt track・landに属する自然の道候補を残す。",
    "wall": "主壁・副壁・妻壁の候補を壁・建物で制約し、和集合にする。建物全体は含めない。",
    "tree": "樹冠・幹の候補をtree・palmで制約し、和集合にする。山・岩・雪は親に含めない。",
}
for _label in ("wall_main", "wall_secondary", "gable_wall"):
    NOTES[_label] = "壁・建物を親にする壁候補。主壁・副壁・妻壁の区別の条件は定義未記載。"

EXCLUSIONS = {
    "sky": ("空", "semantic mapでskyとされた全画素。部位候補がない場所も含む。"),
    "person": ("人物判定画素", "semantic mapでpersonとされた全画素。"
               "像や絵と実在人物の一致は保証しない。"),
    "conflict": ("異roleの競合", "親制約後のrole所属数が2以上の画素。"
                 "同じ親role内の和集合は含まない。"),
    "semantic_mismatch": ("親領域との不一致", "raw候補のうち、親制約後のrole所属数が0の画素。"
                          "空・人物・競合の画素は含まない。"),
    "void": ("有効領域なし", "親制約後のrole所属数が1でない全画素。"
             "候補外・空・人物・競合なども含む。"),
}

CODE_NAMES = {
    "accepted": "採用", "rejected": "除外", "pending": "保留",
    "present": "実在人物あり", "absent": "実在人物なし", "uncertain": "判別不確実",
    "building": "建物", "terrain": "地形", "mixed": "主体混在", "other": "その他・対象外",
    "unknown": "不明", "True": "はい", "False": "いいえ", "None": "不明・未記録",
    "photograph": "写真", "building_detail": "建築部位の接写", "document": "文書",
    "sheet_music": "楽譜", "diagram": "図面・図表", "artwork": "絵・図版",
    "portrait": "肖像", "flower": "花など植物の接写",
    "real_people": "実在人物あり・不明のため保留", "aerial_or_unknown": "上空写真または視点不明",
    "black_and_white": "白黒・単色調色", "dark_or_unknown": "暗所または明暗不明",
    "subject_unresolved": "主体が混在・不明", "subject_conflict": "確定主体と画像判定が矛盾",
    "non_target": "対象外", "invalid_schema": "判定形式が不正", "input_hold": "入力確認で保留",
    "gate_enqueue_failed": "画像判定の投入前に停止", "unjudged": "未判定",
    "api_or_job_failure": "APIまたは処理失敗", "both_absent": "画像判定・画素判定とも人物なし",
    "disagreement": "画像判定と人物画素が不一致", "unknown_evidence": "人物根拠が不明",
    "human_hold": "人の指摘による保留", "person_not_detected": "人物検出なし",
    "person_masked": "人物maskあり", "subject_ambiguous": "主体混在",
    "person_over_limit": "人物面積超過", "image-gate-v2": "画像内容判定第2版",
    "image-gate-v1": "画像内容判定第1版", "region-policy-v1": "親領域による制約第1版",
}


def mask_description(label, kind):
    """候補・有効領域・除外を分けて、根拠のある処理定義と訳語を返す。"""
    if kind in {"exclusion", "person"} and label in EXCLUSIONS:
        return EXCLUSIONS[label]
    key = label.rsplit("/", 1)[-1]
    name = NAMES.get(key, "名称未記載")
    note = NOTES.get(key, "定義未記載。")
    if kind == "raw":
        missing = "部位の細分条件は定義未記載。" if "定義未記載" in note else ""
        return name, (f"{name}として検出されたraw候補。{missing}"
                      "親領域による制約・空・人物・競合の除去は未適用で、有効maskとは異なる。")
    return name, f"{note} 候補と許容親領域の共通部分だけを使い、空・人物・異roleとの競合は除く。"
