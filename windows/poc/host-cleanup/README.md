# host-cleanup PoC

JSONLで対象を明示する、Windows / PowerShell 7向けの小さな候補収集・確認ツールです。
現段階はDryRun専用で、判断はすべて `keep`、削除数は常に0です。
本番削除・定期実行・100GB以上の安全な削減は未実現です。

## 使い方

このフォルダで実行します。付属のJSONLは架空のパスを使った例です。

```powershell
pwsh -NoProfile -File ./host-cleanup.ps1 -Config ./examples/planning-example.jsonl
```

対象フォルダを明示して候補を収集し、確認結果を表示します。
`-InventoryOutput` は新規ファイルを指定します。既存ファイルは上書きしません。

```powershell
./host-cleanup.ps1 -InventoryRoot 'C:\example\input' -InventoryOutput 'C:\example\objects.jsonl' -MaxDepth 2
```

`-Apply` は拒否します。JSONLの形式は [共通schema](contracts/host_cleanup_object.v1.schema.json) を参照してください。
`class` は `planning_only`、`status` は `proposed` / `pending` / `retain` / `unknown` に限定します。
不正な行があればファイル全体を拒否し、終了コード2を返します。

## 配置と責任

```text
host-cleanup/
├─ host-cleanup.ps1    # 利用者の入口（選択処理担当）
├─ inventory/          # メタデータによる候補収集と専用試験
├─ selective/          # 選択処理の補助と専用試験
├─ contracts/          # 共通JSONL形式
├─ examples/           # 合成データだけの使用例
└─ docs/               # 構成と検証結果
```

実装担当は別々の作業ブランチを使い、独立評価担当が両方を確認します。
管理担当が通常の修正をつなぎ、統合・公開担当が同じ成果を1件のPRにまとめます。

JSONLの文字列をコマンドとして実行しません。候補収集はファイル本体を読まず、属性を取得します。
選択処理で現在値と照合するのはサイズと更新時刻です。ファイルID・リンク数・割当量の実体照合や削除適格性の証明はありません。
収集では保護名・reparse point・クラウド属性・複数リンク等を除外します。名前による除外は保護対象すべてを網羅する保証にはなりません。

## 試験

Windows / PowerShell 7で、専用作業領域内の合成データだけを使います。生成したfixtureは残します。

```powershell
pwsh -NoProfile -File ./inventory/tests/Test-Inventory.ps1
pwsh -NoProfile -File ./selective/tests/Test-HostCleanupPlan.ps1
```

検証結果と残課題は [検証記録](docs/verification.md)、処理の流れは [構成図](docs/architecture.mmd)、担当分担は [組織図](docs/organization.mmd) を参照してください。
