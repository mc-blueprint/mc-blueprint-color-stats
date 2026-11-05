"""収集計画器とソース別アダプターの共有契約。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SearchRequest:
    """1ページ分の検索。pageは0始まり、offset指定時はそちらを優先する。

    download_mode省略時はCommonsがthumbnail、他ソースが各既存方式のoriginal。
    原本取得はoriginalを明示する。providerをreplaceする際はNoneで既定を再解決できる。
    """

    provider: str
    query: str
    language: str = "en"
    page: int = 0
    offset: int | None = None
    limit: int = 10
    stratum: str | None = None
    download_mode: str | None = None

    def __post_init__(self):
        if self.download_mode is None:
            object.__setattr__(self, "download_mode", (
                "thumbnail" if self.provider == "wikimedia_commons" else "original"
            ))
        if self.download_mode not in ("original", "thumbnail"):
            raise ValueError("取得モードはoriginalまたはthumbnailです")
        if self.download_mode == "thumbnail" and self.provider != "wikimedia_commons":
            raise ValueError("縮小取得はCommonsだけに対応しています")
        if not self.query.strip() or not self.language.strip():
            raise ValueError("検索語と言語が必要です")
        if self.page < 0 or (self.offset is not None and self.offset < 0):
            raise ValueError("ページとオフセットは0以上です")
        if not 1 <= self.limit <= 10:
            raise ValueError("1回の検索件数は1〜10です")

    @property
    def start(self) -> int:
        return self.page * self.limit if self.offset is None else self.offset


@dataclass(frozen=True)
class Candidate:
    """原本URLと出典ページを区別する。rankは検索全体で0始まり、metadataはJSON値。

    attributionはアダプターが構成する帰属表示。原本取得を許可できない場合は
    exclusion_reasonへ理由を設定し、許可時はNoneとする。
    width/height/mimeは原本値。download_urlは明示した別取得先、renditionは
    provider/native_id/revision/variantと原本メタデータを持つ。受信値は取得後に記録する。
    """

    source_url: str
    original_url: str
    rank: int
    page: int
    title: str
    author: str | None
    license: str
    license_url: str | None
    description: str | None
    location: str | None
    width: int
    height: int
    mime: str
    metadata: dict = field(default_factory=dict)
    attribution: str | None = None
    exclusion_reason: str | None = None
    download_url: str | None = None
    rendition: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    """候補、実効API条件、続きのoffset（終端はNone）。自動で次ページへ進まない。"""

    candidates: list[Candidate]
    parameters: dict
    next_offset: int | None = None


class Adapter(Protocol):
    """searchはメタデータまで、downloadは指定variantを試行専用パスへ書く。

    両方にsource_policyを適用し、禁止ソース・restrictedの原本取得は例外にする。
    通信・APIエラーは呼出し元へ伝播し、キューが試行単位で再実行する。
    """

    def search(self, request: SearchRequest) -> SearchResult: ...

    def download(self, candidate: Candidate, target: Path) -> None: ...
