## Issue #85: 建築subjectの地域・年代

`subject.location` は収集層のregion文字列、`subject.era` はera文字列のまま維持する。
unknownはNULLで、既存の非NULL値を上書きしない。地形subject・assetは変更しない。
確定画像（asset.subject_idで参照される画像）を持つ建築subjectだけを集計・反映し、
成功したsubject同定runのsubject_keysでWikidata IDを
一意に確認できる対象だけ取得する。キーなし・競合はunknownのまま記録する。

`python -m colorstats.stats.subject_attributes --snapshot <新規JSON> --wikidata-cache <cache>
--code-version <版> [--dry-run] [--offline] [--cancel-run <run UUID>]` で実行する。
DB接続は既存のDATABASE_URLを使用する。初回dry-runで取得し、本実行は同じcacheをofflineで使う。
#79の取得モジュール、User-Agent、レート制限、要求hash別cacheを再利用し、新規依存はない。
取得失敗・欠損・出力失敗・DB失敗はrun全体の失敗で、部分反映しない。

`configs/subject_attributes.yaml` に国ID→regionと西暦の閉区間→eraを固定する。
時代は共通区分（古代:499年まで、中世:500～1499年、近世:1500～1799年、近代:1800年以降）で、
地域固有の時代区分とは区別する。P17の全有効claimが同じregionを指す場合だけinferred。
P17のないP131・P625・撮影GPSから国境界を推測しない。未対応国・競合はunknown。
P571は精度を年区間へ展開し、全有効claimの区間が単一era内ならinferred。
before/afterは年・月・日・時・分・秒それぞれの精度単位で計算し、月・日の幅を年数にしない。
月末・うるう日は元の暦で計算する。年代境界はグレゴリオ暦基準で扱い、
暦換算をしないユリウス暦は、区間が各era開始年の前後1年に重なる場合unknownとする。
境界跨ぎ、異なるera、修飾付き年代、対応外暦・紀元前等はunknown。
世紀・千年紀の1始まりは[Wikidata日付仕様](https://www.wikidata.org/wiki/Help:Dates)に従う。

state（inferred/unknown/preserved）、理由、元値・更新後値、Wikidata項目ID・revision・
P17/P131/P625/P571の完全claim、asset GPS、設定、要求・応答hashはsnapshotへ保存する。
成功runはstage=subject、method=subject-attributes-v1で識別し、parametersに設定・集計・
変更箇所、output_paths.snapshotに根拠JSONを保存する。APIは#79と同じ要求を使い、
返却結果から4属性だけを今回の根拠へ記録する。既存の列・層照合APIは変更しない。

#72の取引・排他・snapshot作成を共有し、属性反映はsubject表だけをロックする。
取消は指定成功runの変更前値・更新後値・現在値と後続の属性変更runを照合し、
そのrunが新規に付けたままの値だけを戻す。取消範囲は元snapshotのsubjectとし、
現在は確定画像がない対象や旧実装が誤って反映した候補も含めて戻す。
取消自体もdry-run・1取引・新規snapshot。
同じ値を別経路で書き戻した操作は既存スキーマに履歴がなく識別できないため、
対象列を外部操作した場合は元snapshotと現在の編集履歴を確認してから取消する。

docs/schema.mdへの反映は#74第2段階で行う。
