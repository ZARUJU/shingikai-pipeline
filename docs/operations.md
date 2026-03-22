# 運用フロー

## 目的

このリポジトリの運用を、`新規登録` `更新` `修正` の 3 種類に分けて迷わず実行できるようにする。

## 基本方針

- 通常運用は `cli.py ops ...` を入口にする
- `ops` は live fetch 前提で、GitHub Actions からそのまま実行できるようにする
- 個別の取得・解析ロジック修正は `src/shingikai/councils/` 以下で行う
- 品質確認は `data/_quality/meeting_gap_issues.json` を基準に見る
- `ops add` `ops update` `ops repair` は品質確認 JSON 生成まで含めて運用する
- 詳細な調査や一時的な確認では、既存の `council` `meetings` `hierarchy` `quality` サブコマンドを使う
- `fixtures/` はローカル開発専用であり、運用コマンドからは参照しない

## 1. 新規登録

想定:

- 新しい会議体を `data/councils/` に載せたい
- 初回の `council.json` `meetings/` `documents/` `rosters/` を生成したい

標準コマンド:

```bash
uv run python cli.py ops add <council_id>
```

必要に応じて使うオプション:

- `--force`: キャッシュを無視して再取得する
- `--output-dir <dir>`: 一時ディレクトリや検証用ディレクトリに出力する
- `--skip-quality`: 品質確認 JSON の再生成を省略する

補足:

- 一覧ページから会議体自体を追加したいときは、先に `hierarchy export` を使う
- `ops add` は会議体基本情報も書き出す

## 2. 更新

想定:

- 既存会議体の新着開催記録を定期取得したい
- スケジューラや cron から定期実行したい

標準コマンド:

```bash
uv run python cli.py ops update <council_id>
uv run python cli.py ops update all
```

補足:

- `ops update` は開催記録の再生成に加えて、品質確認 JSON も更新する
- 通常は `--refresh-hours 24` 相当で、古いキャッシュだけを再取得する
- 一覧ページを live fetch し、既存 `data/` と差分がない会議は詳細ページ再取得を避ける
- もっと短い間隔で確認したい場合は `--refresh-hours <hours>` を使う
- 品質確認 JSON を今回は更新しないなら `--skip-quality` を使う
- ネットワーク再取得が必要なときだけ `--force` を付ける

## 3. 修正

想定:

- 欠番や過剰取得が `data/_quality/*.json` に出ている
- パーサ修正後に対象会議体だけ再生成したい
- コーディングエージェントに修正を依頼し、その後の再生成手順を統一したい

標準コマンド:

```bash
uv run python cli.py ops repair <council_id>
```

修正時の基本手順:

1. `data/_quality/meeting_gap_issues.json` を確認する
2. 原因を `src/shingikai/councils/` や共通処理から特定する
3. テストを追加または更新する
4. `ops repair` で対象会議体を再生成する
5. `quality export` または再生成済み品質 JSON を確認する

よくある原因:

- 会議でない文書を開催記録として拾っている
- より深い階層の過去ページを取れていない
- 親ページに混在した内部委員会を誤って同一会議体へ入れている

## 補助コマンド

これらは開発・調査向けです。`--use-fixture` を使う場合はこちらを使います。

### 会議体階層を更新する

```bash
uv run python cli.py hierarchy export <root_council_id>
```

### 品質確認 JSON を更新する

```bash
uv run python cli.py quality export
```

### UI で保存済みデータを確認する

```bash
uv run python ui.py
```

## GitHub Actions 運用

- 定期更新は [update-data.yml](/Users/kzk/Dev/_ok/v2/shingikai/.github/workflows/update-data.yml) で行う
- workflow は `ops update all` を実行し、`data/` 配下に差分があれば PR を作る
- fixture は Actions に持ち込まない
