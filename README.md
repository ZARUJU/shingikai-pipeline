# shingikai

審議会データを取得・整形し、JSON と簡易 UI として扱うためのリポジトリです。

このプロジェクトの運用は、次の 3 つに分けます。

- 新規登録: 新しい会議体を追加し、初回データを生成する
- 更新: 既存会議体の開催記録を定期更新する
- 修正: 取得漏れや誤判定を直し、対象データを再生成する

詳細は [docs/operations.md](/Users/kzk/Dev/_ok/v2/shingikai/docs/operations.md) を参照してください。設計の考え方は [docs/architecture.md](/Users/kzk/Dev/_ok/v2/shingikai/docs/architecture.md) にまとめています。

## セットアップ

```bash
uv sync
```

CLI は以下のいずれでも実行できます。

```bash
uv run python cli.py --help
uv run shingikai --help
```

## 運用コマンド

通常運用では `ops` サブコマンドを使います。`ops` は live fetch 前提で、GitHub Actions からの実行を想定しています。`fixtures/` は参照しません。

### 1. 新規登録

会議体の基本情報と開催記録をまとめて生成します。

```bash
uv run python cli.py ops add social-security-council
```

品質確認 JSON を同時に更新したくない場合は `--skip-quality` を付けます。

### 2. 更新

既存会議体の開催記録を更新し、あわせて品質確認 JSON も再生成します。定期実行向けです。

```bash
uv run python cli.py ops update social-security-council
uv run python cli.py ops update all
```

通常は `24` 時間より古いキャッシュだけ再取得します。`--refresh-hours` でしきい値を調整できます。`--force` を付けるとキャッシュを無視して再取得します。実行後は `data/_quality/meeting_gap_issues.json` も更新されます。

### 3. 修正

パーサ修正後に対象会議体を再生成し、品質確認 JSON も更新します。

```bash
uv run python cli.py ops repair social-security-council
```

## 開発・調査用コマンド

下位コマンドはローカル開発や個別調査向けです。`--use-fixture` を使えるのはこの系統だけです。

- `council export`: 会議体基本情報だけを出力する
- `meetings export`: 対象会議体の meetings/documents/rosters を出力する
- `meetings export-family`: 親会議体配下をまとめて出力する
- `hierarchy export`: 一覧ページから会議体階層を生成する
- `quality export`: `data/_quality/meeting_gap_issues.json` を再生成する

例:

```bash
uv run python cli.py hierarchy export social-security-council --use-fixture
uv run python cli.py quality export
uv run python ui.py
```

## データ配置

```text
data/
  councils/<council_id>/
    council.json
    meetings/*.json
    documents/*.json
    rosters/*.json
  _quality/
    meeting_gap_issues.json
    fetch_errors.json
  _reviews/
    meeting_gap_reviews.json
```

## GitHub Actions

定期更新用 workflow は [update-data.yml](/Users/kzk/Dev/_ok/v2/shingikai/.github/workflows/update-data.yml) です。

- 毎日定期実行し、`ops update all` を動かす
- `data/` 配下に差分が出たら PR を作る
- 品質確認 JSON も同時に更新する

## テスト

```bash
uv run python -m unittest discover -s tests -v
```
