# Windows → resources：移行準備の判断範囲

全移行の正本は [resources #25](https://github.com/roccho-dev/resources/issues/25)、実装・最新の公開headとCI結果は [PR #31](https://github.com/roccho-dev/resources/pull/31)。本書は切替前の確認入口であり、全計画・可変の進捗台帳を複製しない。

2026-10-17のUser指示により、進行中Issue/PRの引継ぎは触らず、先にresourcesを移行判断可能にする。ここでの準備完了は、固定source候補の必要CIと比較が通り、切替対象・限界・復旧条件を読めること。実移行、未merge系列の継承、独立した最終受入、Archive可能とは別である。

## 基準と再確認

移行元の基準は `docs/windows-migration.jsonl` のsource行だけに置く。候補はそのWindows版の実装・既存試験を引き継ぐ。配置入力はroot flake/lockが指す `roccho-org/envs` の固定sourceを使い、秘密ではない2 JSONを元bytesと比較する。envs PR #104は未mergeの候補であり、実配備で採択されたことは意味しない。

`Windows migration source inventory` は固定checkoutを検査し、実際に観測した元branch headを別に記録する。通常の検査は版不一致を拒否する。明示した `--preparation` だけが、固定版の準備検証を続けながら `upstream_review_required=true` を残す。新しい差分の自動採用・欠落の容認・migration_completeの変更はしない。

2026-10-17の読取で、元repoの `f30f79c3419635f800fc48479901cc85aae6624f` は基準からdevの `oci/dev/nix.nix` と `oci/dev/proof.sh` が進んでいた。この差分と進行中Issue/PRの処遇は準備後に判断する。旧repoを凍結・closeせず、最新実装まで移管済みとは表示しない。

## ここまでなら進められる（今回の限界）

| 対象 | 準備の出口 | 今回行わないこと |
|---|---|---|
| ファイル・出力 | 固定sourceの全path対応、rootの既存公開出力を評価・build | 未merge PRや実Host上の未公開ファイルの引継ぎ |
| Windows/OCI/profile/extensions | 移管先の実装と元の正常・異常・継続試験 | 本番の設定・認証・volumeの変更 |
| Nix | root flake一本、lockにwindows inputなし、必要成果物をbuild | nixpkgs二版の不要な統一 |
| フォント・core | 元fontsの全内容とown core derivationの一致 | 見た目の変更や端末の再設定 |
| OpenCode | 同じNix own-profileのCLIから指定した無料モデルの実応答 | 有料モデルへの自動fallback、旧認証の転用 |
| envs配置入力 | 固定inputのbuildと元2 JSONのbytes一致 | APIキー・secretの取得、移送、失効 |
| CI | 同じ公開headの必要workflowを成功まで修正 | 元試験の省略、別headのGreenの流用 |
| GHCR/Release | 配布物とworkflowを検査し、公開切替の前提を記録 | 新旧publisherの切替や実publish |
| Host・周辺 | 切替単位、事前状態、判定・復旧条件を明記 | G6I3/VersaPro/own/rent/devへの実applyや追加reboot |
| 進行中Issue/PR | User判断により保留として参照を残す | transfer、merge、close、元担当の変更 |
| 独立評価 | 第三者が再取得・評価できるsourceとCI証拠を揃える | このwriterの自己検査を独立R受入と呼ぶこと |
| Archive | 準備と全移行の条件を分ける | windowsをArchive・削除すること |

## 準備の機械検証

同じPR headで、棚卸し・旧新比較、`ci`、`own OCI`、`release watch`、`opencode-deepseek-v4.1-free` を読む。必要ジョブの失敗・実行中・予期しないskipは準備成功へ数えない。非活性にしたpublish/proposeのskipは、未実施の境界として明記する。

- 棚卸しはGit object metadataに基づき、重複・未分類・別checkoutを拒否する。準備モードでもUNMIGRATEDと未確認分類を保持する。
- 同じCIで、移行元と移管先のfontsディレクトリ全体、own coreのderivation、配置入力2 JSONを比較する。
- root flakeとlockを検査し、稼働build用のwindows inputを使わない。旧repoの固定版は比較用の読取元としてのみ残る。
- Windows、own/rent/dev、NixOSの必要な元検査を保持する。実機の認証・状態はfixtureの成功から推定しない。
- DeepSeek実応答は指定したモデルの生成textを検査する。提供停止や不明な応答はFAILであり、有料へ切替しない。

準備結果は、PRのhead・tree・各run/jobの組で記録する。全検査の終端を読まずに準備完了としない。`migration_complete=false` は本番移行の未完を表し、固定sourceの準備検証とは別の状態である。

## 準備後の切替と復旧の入口

| 単位 | 切替前に読むもの | 受入と復旧 |
|---|---|---|
| 配布元 | 旧のactive publish、同一tagのwriter、GHCR権限、Release取得元 | 一つのwriterだけ切替。新成果物のdigest・取得を確認するまで旧成果物を保持。結果UNKNOWNなら再送せずreadback |
| G6I3/Windows | 現在のRelease、Restore/OwnResume/ClientSshの参照と台帳、既存の復旧入力 | 通常更新で対象だけ切替し、既存RestoreTest等で確認。旧版を保持し、許可された一致条件下の復旧だけを使う |
| VersaPro/own/rent/dev | 採用source/image/tool世代、実主体、home/work/nixの保持先と権限 | 各ownerの通常更新。接続、CLI、必要auth/session/work保持を実確認。tool rollbackはデータ巻戻しではない |
| envs/state/release-watch | 実Binding主体、stateの正本・writer・復旧、scheduleの宛先 | repository名だけを機械的に置換しない。対象/権限/担当の一致を確認して別に採否 |
| 旧repo | 新規差分、未完系列、旧取得・schedule・stateへの実依存 | Userが延期した引継ぎをここで検討。残依存0・独立R・最終採否が揃うまで現役を維持 |

失敗は「未送信の技術失敗」「既知の失敗」「送信後の結果不明」を区別する。不足のある工程だけに戻り、公開・切替・Archiveを盲目に再実行しない。履歴URL、既存GHCR名、認証targetの識別子を残存する稼働build依存と同一視しない。
