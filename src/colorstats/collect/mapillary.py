"""登録アプリの公開Mapillary Images APIだけを使う解析専用アダプター。"""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, urlunsplit

from colorstats.collect import Candidate, SearchResult
from colorstats.collect.http import HttpClient
from colorstats.collect.policy import license_class
from colorstats.store import temporary_path

ENDPOINT = "https://graph.mapillary.com/images"
FIELDS = "id,creator,sequence,captured_at,geometry,width,height,thumb_1024_url,detections{value}"
LICENSE = "cc-by-sa-4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"


class MapillaryAdapter(HttpClient):
    """固定検索条件のcursorをSTATE_DIRECTORYへ保存する。並行実行は単一ownerに限定。

    認証はCREDENTIALS_DIRECTORY/mapillary-client-tokenのみ。欠落時は通信しない。
    署名付き画像URLと認証値はメモリ内だけに保持し、候補・観測値には含めない。
    """

    def __init__(self, policy, **kwargs):
        super().__init__(policy, **kwargs)
        self._media = {}
        opener = self.opener

        def authorized(request, **options):
            parts = urlsplit(request.full_url)
            if parts.scheme != "https" or parts.port not in (None, 443):
                raise ValueError("MapillaryはHTTPSの標準ポートだけを使用します")
            if parts.hostname == "graph.mapillary.com":
                if parts.path != "/images":
                    raise ValueError("公開Images API以外への認証転送を拒否しました")
                directory = os.environ.get("CREDENTIALS_DIRECTORY")
                if not directory:
                    raise ValueError("Mapillary credentialがないためソースは無効です")
                try:
                    token = (Path(directory) / "mapillary-client-token").read_text().strip()
                except OSError:
                    raise ValueError("Mapillary credentialがないためソースは無効です") from None
                if not token.startswith("MLY|") or any(c.isspace() for c in token):
                    raise ValueError("Mapillary credentialの形式が不正です")
                request.add_header("Authorization", "OAuth " + token)
            elif not any(parts.hostname == host or (parts.hostname or "").endswith("." + host)
                         for host in self.policy["media_hosts"]):
                raise ValueError("公開APIと許可済み画像CDN以外への接続を拒否しました")
            return opener(request, **options)

        self.opener = authorized

    def get(self, url, **kwargs):
        try:
            return super().get(url, **kwargs)
        except HTTPError as error:
            code = error.code
            error.close()
            parts = urlsplit(url)
            safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            raise HTTPError(safe_url, code,
                            "Mapillary HTTP error", {}, None) from None

    def search(self, request):
        if request.provider != "mapillary" or request.query not in self.policy["searches"]:
            raise ValueError("Mapillaryの固定検索意図に対応していません")
        condition = self.policy["searches"][request.query]
        params = {"bbox": ",".join(map(str, condition["bbox"])),
                  "fields": FIELDS, "limit": request.limit}
        effective = {"endpoint": ENDPOINT, **params, "intent": request.query,
                     "condition": condition, "rank_basis": "request.start + index",
                     "variant": "thumb_1024_url"}
        key = hashlib.sha256(json.dumps(effective, sort_keys=True).encode()).hexdigest()
        directory = os.environ.get("STATE_DIRECTORY")
        if not directory:
            raise ValueError("Mapillaryの再開にはSTATE_DIRECTORYが必要です")
        state_dir = Path(directory) / "mapillary"
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = state_dir / (key + ".json")
        state = json.loads(path.read_text()) if path.exists() else {"0": {"after": None}}
        page = state.get(str(request.start))
        if page is None:
            raise ValueError("未確認offsetです。記録されたnext_offsetから順に再開してください")
        if page["after"]:
            params["after"] = page["after"]
        self.observe("search", {"effective": effective})
        data = self.get(ENDPOINT + "?" + urlencode(params), api=True)
        if "error" in data:
            raise RuntimeError("Mapillary APIが要求を拒否しました")
        items = data["data"]
        seen = {seq for offset, value in state.items() if int(offset) < request.start
                for seq in value.get("sequences", [])}
        candidates = []
        retrieved = datetime.now(UTC).isoformat()
        for index, item in enumerate(items):
            native = str(item.get("id", ""))
            sequence = item.get("sequence")
            creator = item.get("creator") or {}
            author = str(creator.get("id") or creator.get("username") or "") or None
            media = item.get("thumb_1024_url", "")
            parts = urlsplit(media)
            detections = item.get("detections", {})
            reasons = []
            if not native.isdecimal() or not sequence or not author or not item.get("captured_at"):
                reasons.append("identity_unverified")
            if (parts.scheme != "https" or not parts.hostname
                    or not any(parts.hostname == host or parts.hostname.endswith("." + host)
                               for host in self.policy["media_hosts"])):
                reasons.append("thumbnail_unverified")
            if not item.get("width") or not item.get("height"):
                reasons.append("non_image")
            if "data" not in detections or detections.get("paging"):
                reasons.append("privacy_unverified")
            elif any("human" in d.get("value", "") or "person" in d.get("value", "")
                     for d in detections["data"]):
                reasons.append("person_present")
            if sequence in seen:
                reasons.append("sequence_repeat")
            if sequence:
                seen.add(sequence)
            if license_class(self.policy, LICENSE) != "analysis_only":
                reasons.append("rights_unverified")
            landing = "https://www.mapillary.com/app/?pKey=" + native
            original = "https://graph.mapillary.com/" + native
            safe_media = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            candidate = Candidate(
                source_url=landing, original_url=original, rank=request.start + index,
                page=request.page, title=condition["intent"], author=author,
                license=LICENSE, license_url=LICENSE_URL,
                description=None, location=condition["region"],
                width=item.get("width", 0), height=item.get("height", 0), mime="image/jpeg",
                metadata={"native_id": native, "sequence": sequence,
                          "captured_at": item.get("captured_at"), "geometry": item.get("geometry"),
                          "retrieved_at": retrieved, "subject_status": "unconfirmed",
                          "privacy_review_required": True},
                attribution=f"{author or 'Mapillary contributor'} | {landing} | CC BY-SA 4.0",
                exclusion_reason=",".join(reasons) or None, download_url=safe_media,
                rendition={"provider": "mapillary", "native_id": native,
                           "revision": str(item.get("captured_at", "")),
                           "variant": "thumbnail", "api_variant": "thumb_1024_url",
                           "mime": "image/jpeg", "original": {
                               "width": item.get("width"), "height": item.get("height")}},
            )
            if not reasons:
                self._media[native] = media
            candidates.append(candidate)
            self.record_candidate(candidate, verified=not reasons)
        paging = data.get("paging", {})
        cursor = paging.get("cursors", {}).get("after")
        next_offset = (
            request.start + len(items) if items and paging.get("next") and cursor else None
        )
        state[str(request.start)]["sequences"] = [i["sequence"] for i in items if i.get("sequence")]
        if next_offset is not None:
            if state.get(str(next_offset), {}).get("after") != cursor:
                state = {offset: value for offset, value in state.items()
                         if int(offset) < next_offset}
                state[str(next_offset)] = {"after": cursor}
        temporary = temporary_path(path, "cursor")
        try:
            temporary.write_text(json.dumps(state), encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self.observe("search", {"api_next_offset": next_offset})
        return SearchResult(candidates, effective, next_offset)

    def download(self, candidate, target):
        if (candidate.exclusion_reason
                or license_class(self.policy, candidate.license) != "analysis_only"):
            raise ValueError(candidate.exclusion_reason or "rights_unverified")
        media = self._media[candidate.metadata["native_id"]]
        self.get(media, target=target)
