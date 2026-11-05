"""spawn境界でMapillaryの認証拒否を再現する。実通信は行わない。"""

from urllib.error import HTTPError

from colorstats.collect.mapillary import ENDPOINT, MapillaryAdapter


def prepare(claim):
    def opener(*args, **kwargs):
        raise HTTPError(ENDPOINT, claim.payload["http_status"], "fixture", {}, None)

    adapter = MapillaryAdapter(claim.payload["policy"], opener=opener)
    adapter.get(ENDPOINT)


def register(session, run, data):
    raise AssertionError("認証拒否したjobは登録しません")
