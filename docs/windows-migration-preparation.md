# Windows → resources：提供入口と移行の境界

全体の採否・現行成果版・CI/公開結果は [PR #31](https://github.com/roccho-dev/resources/pull/31) 冒頭 `windows-migration-phases-20261017-v3` を読む。全移行の入口は [#25](https://github.com/roccho-dev/resources/issues/25)。この文書は各依存repoが通常のPRで採用するための提供契約であり、可変の実行結果を別台帳へ複製しない。

## 3フェーズ

| フェーズ | 出口 |
|---|---|
| 1 提供開始（今回） | 固定SOURCEと必要配布物をresourcesから取得できる。同一公開版の必要検査に加え、公開・取得の実結果と更新・戻し方が揃う |
| 2 依存側移行 | 各consumerが自分のPR/通常更新で採用・読戻し。旧提供、更新、実行ref、schedule、必要stateへの依存と保留系列を解消し、windows repoの退役可否を確認 |
| 3 削除 | 比較元・履歴・復旧物を旧repoなしで保持し、対象と明示採否を確定して削除・読戻し。Archiveと削除は別 |

SOURCE検査成功、期限付きActions artifact、publishのskipだけでは1を満たさない。実Hostが未切替であることだけでは1を不合格にしない。旧repoの進行中Issue/PR・基準後dev差分は2へ保留し、今回変更しない。

## 各repoが採用する入口

対象プラットフォームは既存の `x86_64-linux`。Windows用スクリプト/配布物は既存契約のまま。取得する版はPRの成功結果又はReleaseが指すGit commitで固定し、可変branchやlatestを実配備の固定値としない。Git/Nix/registryが返すcontent identityを使い、手転記の別gateや新しい公開器は置かない。

| 提供 | resources側の入口 | 固定するもの・必要入力 |
|---|---|---|
| source/共通部品 | `github:roccho-dev/resources/<commit>` のroot flake | `flake.lock`を含むcommit。`lib.x86_64-linux.mkOwn`、`releaseVersions`、`packages.x86_64-linux`の既存出力 |
| Linux CLI | `own-profile`、`dev-profile`、`release-profile` | Claude Code/Codex/Pi/OpenCodeの既存profile。ownはBaseとToolを独立して選択。認証は各既存方式、volume/HOMEはconsumer所有 |
| own/rent画像 | `ghcr.io/roccho-dev/windows-own` / `windows-rent` | Releaseのimage descriptorが返すregistry digest。画像名は互換識別子であり旧repoの現役build依存ではない |
| Windows配布物 | resourcesのRelease `windows-<commit>` | `windows-dist.zip`とchecksum、同じsourceの`rent-image.json`、Baseも発行した版の`own-image.json`。manifest.sourceの一致を確認 |
| devの取得/build | `oci/dev/spec.json`のresources cloneUrl、`dev-image` / `dev-profile` | consumerの公開BindingのbaseSha/toolsRevを同じresources提供版へ別PRで選択。古いWindows commitをresourcesの新取得元に混ぜない。不要なdev GHCR公開は追加しない |
| 公開配置入力 | root lockの`host-bindings` input | envs PR104由来の公開2 JSON。固定bytesを比較する。実Binding採択、APIキー、認証targetの変更は別段階 |
| 管理部品 | `apps.x86_64-linux.github-root`、`git-state-backend` | resources root checkout・同originへ結び付いた既存principal。管理対象は引き続き`github_repository.windows`。実運用前にownerがstateの実在・正本・復旧・専有を確認 |

公開SOURCEには実credentialを含めない。管理部品のsource提供は、plan/adoptやstate新設・移送の許可ではない。既存key名、Host名、volume名、Pi等の認証target名をrepo名から機械的に変えない。特にstateがあるか不明なまま別backendへadoptしない。

## 公開・更新と戻し方

`ci`は既存のWindows/dev/own/rent検査を実施し、通常のproposals push、又は明示した手動publishだけで新commit専用画像とReleaseを発行する。既存tagの上書き・latest切替・consumer更新・旧publisher停止は行わない。公開stepは必要jobの成功後に、registry画像を別の空のDocker認証設定で取得し、Releaseを再取得して元bytes/checksum/manifest.sourceと照合する。何を実取得できたかはrun/jobの結果で判定する。

Tool-only更新ではown Baseを作り直さず、consumerは以前に採択したown digestを保持してToolのsourceを更新する。新しいReleaseはその条件を説明し、未発行のown digestを生成しない。rent digestとWindows配布物は同じsourceに結び付ける。

更新は通常のsource PRでpinを変更し、既存検査と同じ公開経路を通す。既存`release watch`は公式source/署名/bytes検査を保ち、手動 `propose=true` で通常のdraft更新PRを作る入口を持つ。cronはこのフェーズで有効化せず、旧scheduleも変更しない。OpenCode/Piへ別の更新器を追加しない。

戻すときは保持した前版のsource/Release/画像digestをconsumerの通常PRで再選択し、既存の世代・復旧手順で確認する。Tool世代の巻戻しはHOMEやデータの巻戻しではない。新しい版の確認前に旧Release・画像・作業・volumeを削除しない。source変更の取消しはGit標準のrevertを使い、実状態を独自scriptで推測復元しない。

公開操作のtimeoutは結果UNKNOWN。Release/tag/registryを読戻し、既に成功した作用を再送しない。既存Releaseを無条件に上書きして再実行を通す経路は作らない。

## 検査保証と残る境界

同じ公開headで、棚卸し/旧新比較、全体CI、own OCI/NixOS VM、更新監視verify、OpenCode指定無料モデルの実応答を確認する。元の正常・拒否・継続・GC・rollbackの検査を維持する。公開成功はこれらの成功と別に記録し、先行headのGreenを新headへ流用しない。

固定Windows比較元は `docs/windows-migration.jsonl` のsource行。最新upstreamは別に観測し、準備modeでも未継承差分と全移行未完を残す。比較目的の旧SOURCE取得は提供依存と分けるが、フェーズ3までに旧repoなしで取得可能な保管へ移し、比較検査を失わないようにする。

後段に残るものは、各consumerの入力・Restore/OwnResume/ClientSsh・source/image/Tool世代の採用、既存schedule/publisherの切替、必要stateの保管責務、基準後差分/元Issue/PRの処遇、実Host UX/認証/Cloudflare、独立した全移行受入、Archive/削除である。CIのfake/VM/昇格Windows検査を、clean非昇格Windows 11や実Hostの受入へ昇格させない。
