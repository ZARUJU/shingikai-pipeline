# アーキテクチャ案

## 1. 基本方針

このプロジェクトでは、以下の 2 つを明確に分けて管理するのがよいです。

- データ: 利用者に提供するための整形済み成果物
- ワークフロー: そのデータをどう取得・更新したかという手順

目的は、会議体ごとの更新ロジックを追いやすくしつつ、共通処理の再利用性も確保することです。現段階では、ワークフローは YAML 等の宣言ファイルではなく、会議体ごとの Python コードとして持つ方針を基本にします。

## 2. 保存形式

保存形式は、まずは JSON を主軸にするのが妥当です。

- Python から扱いやすい
- 差分確認がしやすい
- 将来的に静的サイトや API に流し込みやすい

推奨イメージ:

```text
data/
  councils/
    digital-ai-advisory-board/
      council.json
      rosters/
        2025-01-01.json
      meetings/
        2025-02-14.json
        2025-03-01.json
      documents/
        2025-report.json
```

### council.json

会議体の基本情報を持つファイルです。

```json
{
  "id": "digital-ai-advisory-board",
  "title": "AI戦略会議",
  "organization": "デジタル庁",
  "source_urls": {
    "portal": "https://example.jp/council",
    "meetings": "https://example.jp/council/meetings"
  }
}
```

### meetings/*.json

各回の開催記録を 1 ファイル 1 レコードで持たせます。

```json
{
  "id": "2025-02-14",
  "held_at": "2025-02-14T10:00:00+09:00",
  "title": "第1回 AI戦略会議",
  "source_url": "https://example.jp/council/1",
  "materials": [
    {
      "title": "資料1",
      "url": "https://example.jp/council/1/doc1.pdf"
    }
  ],
  "minutes": {
    "status": "available",
    "url": "https://example.jp/council/1/minutes.pdf"
  },
  "transcript": {
    "status": "not_published",
    "url": null
  }
}
```

この単位にしておくと、欠損補完や手修正の影響範囲が小さくなります。

## 3. 欠損や未公開の表現

審議会データでは、単に値が空というだけでなく、意味の異なる欠損が発生します。たとえば次のような違いがあります。

- 公開されていない
- 過去分が見当たらず不明
- まだ確認していない
- その会議体にはそもそも当該項目がなさそう

そのため、重要な項目では値そのものと状態を分けて持つのがよいです。

例:

```json
{
  "transcript": {
    "status": "not_published",
    "url": null,
    "note": "議事要旨のみ公開"
  },
  "roster": {
    "status": "unknown",
    "as_of": null,
    "members": []
  }
}
```

`status` の候補としては、当面以下を想定します。

- `available`: 確認でき、実データがある
- `not_published`: 公開されていないことを確認した
- `unknown`: 有無を判断できない
- `not_checked`: まだ確認していない
- `not_applicable`: その項目自体が対象外

これにより、フロントエンドや後続処理で「空データ」を誤解しにくくなります。

## 4. ワークフローの持ち方

透明性を担保したいという目的はありますが、現段階では会議体ごとの Python モジュールで処理を書く方が現実的です。

```text
src/
  shingikai/
    councils/
      digital_ai_advisory_board.py
      digital_administrative_research.py
```

例:

```python
def run() -> None:
    index_html = fetch_html(MEETINGS_URL)
    meeting_links = extract_meeting_links(index_html)

    for link in meeting_links:
        detail_html = fetch_html(link.url)
        meeting = parse_meeting(detail_html, link.url)
        write_meeting_json(meeting)
```

この形でも、少なくとも以下は明示できます。

- 入口 URL
- 実行手順
- どこで個別パースしているか
- どの JSON を出力しているか

YAML のような宣言方式は、複数会議体を実装して共通パターンが十分見えてから再検討すれば十分です。

## 5. コード構成案

Python コードは、会議体固有ロジックと共通処理を分けます。

```text
src/
  shingikai/
    models/
      council.py
      meeting.py
      roster.py
    councils/
      digital_ai_advisory_board.py
      digital_administrative_research.py
    utils/
      fetch.py
      cache.py
      html.py
      normalize.py
      io.py
cache/
  http/
fixtures/
  html/
```

責務のイメージ:

- `models/`: 保存データの構造定義
- `councils/`: 会議体ごとの取得・パース手順
- `utils/`: fetch, キャッシュ制御, HTML 抽出, 日付正規化, JSON 書き出しなどの共通部品
- `cache/`: 実運用で再利用する HTTP キャッシュ
- `fixtures/`: 開発時に使う保存済み HTML やサンプルレスポンス

この構成なら、各ファイル自体が会議体ごとの処理手順書になります。

## 6. HTTP アクセスとキャッシュ

アクセスを抑えつつ更新確認したいので、取得層と解析層を分けておくのが重要です。

基本方針:

- 本番運用では条件付き GET を使う
- 開発中は保存済み HTML を優先して読む
- パーサは「HTTP から取ったか、ローカルから読んだか」を意識しない

想定する流れ:

1. URL ごとに前回取得時の `ETag` と `Last-Modified` を保持する
2. 次回アクセス時に `If-None-Match` / `If-Modified-Since` を付けて取得する
3. `304 Not Modified` なら保存済み本文を再利用する
4. `200 OK` なら本文とレスポンスメタデータを更新する

保存イメージ:

```text
cache/
  http/
    digital-ai-advisory-board/
      meetings-index.body.html
      meetings-index.meta.json
```

`meta.json` にはたとえば次のような内容を持たせます。

```json
{
  "url": "https://example.jp/council/meetings",
  "etag": "\"abc123\"",
  "last_modified": "Tue, 18 Mar 2025 10:00:00 GMT",
  "fetched_at": "2026-03-18T12:00:00+09:00",
  "status_code": 200
}
```

これにより、更新確認のためのアクセスは行いつつ、不要な本文再取得を減らせます。

## 7. 開発時の HTML 再利用

HTML 解析の調整中は、毎回実サイトへアクセスせず、保存済みの HTML に対してパーサを実行できるようにするのがよいです。

たとえば次の 2 モードを持たせます。

- `live`: 実サイトへアクセスし、必要ならキャッシュも更新する
- `fixture`: 保存済み HTML を入力としてパーサだけを動かす

イメージ:

```python
def run(use_fixture: bool = False) -> None:
    if use_fixture:
        index_html = load_fixture_html("digital_ai_advisory_board/index.html")
    else:
        index_html = fetch_html_with_cache(MEETINGS_URL)

    meeting_links = extract_meeting_links(index_html)
```

重要なのは、`parse_meeting()` のような関数を HTML 文字列や DOM を受け取る純粋な処理に寄せることです。そうすれば、取得元がネットワークでもローカルファイルでも同じコードを使えます。

## 8. 実装方針

最初から汎用化しすぎず、以下の順で進めるのが安全です。

1. まず 1 会議体だけを対象に JSON 出力まで通す
2. その過程で共通化できる処理だけ `utils/` に切り出す
3. 取得層に `ETag` / `Last-Modified` ベースのキャッシュを入れる
4. 開発用に fixture HTML からパーサを回せるようにする
5. 2 会議体目でファイル構成とデータ表現の妥当性を確認する
6. 形式が固まってから管理画面や補正フローを考える

## 9. 当面のおすすめ

当面は次の方針が最も現実的です。

- 成果物は `data/.../*.json` に保存する
- 会議体ごとの取得手順は `councils/*.py` に書く
- 共通処理だけ `utils/` に切り出す
- HTTP 取得は `ETag` と `Last-Modified` を使って最小限にする
- 開発中は保存済み HTML を fixture として使えるようにする
- 逐語録や名簿は `status` を持たせて未公開や不明を区別する
- 例外的な補正だけ手作業 JSON 編集を許容する

これなら、可読性・差分管理・透明性のバランスがよいです。
