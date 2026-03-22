# 2026-03-20 MHLW データ品質メモ

- `回次なし + 資料のみ` の行が MHLW 一覧で会議として出力されることがあり、`meeting_gap_issues.json` の「開催記録数超過」の主因になっていた。
- 品質判定でも `no-round` 会議をそのまま超過件数に含めていたため、重複回次ではなくても過剰検知していた。
- 対応方針:
  - `minutes_links` と `announcement_links` がなく、`materials_links` のみを持つ `no-round` 行は文書として扱う。
  - 超過件数は総会議数ではなく、回次付き会議数を基準に判定する。
