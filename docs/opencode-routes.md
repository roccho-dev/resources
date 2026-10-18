# OpenCode の経路

2026-10-18 JST の観測と予定。現在の経路を保持し、別経路は置換せず併存させる。

## モデルへの接続

| 経路 | 実行先・モデル指定 | 確認できたこと | 状態・次の工程 |
|---|---|---|---|
| OpenCode の無料 DeepSeek | NixOS own OCI / OpenCode 2.0.30 / `opencode/deepseek-v4.1-flash-free` | 実推論で `(17+23)*2 → 80`、正常終了。実際のツールで gh の調査、bare clone・worktree 作成・既存 helper による repo binding を実行 | 実証済み。現在の経路として保持 |
| DeepSeek 公式 API | 同じ OpenCode からの追加候補。公式 API の `deepseek-flash` は観測時点で V4.1 Flash 1017 を案内 | 提供元の案内まで。NixOS の接続・実推論は未確認 | 候補。未採用・未接続 |
| OpenRouter | 同じ OpenCode からの追加候補。`openrouter/deepseek/deepseek-v4.1-flash-1017` | 日付付きモデルの掲載まで。NixOS の接続・実推論は未確認 | 候補。未採用・未接続 |
| 別経路 | 方式・提供元・モデルは未指定 | User が「今の経路を残したまま別経路」を予定 | 予定。上の候補からの選択も未確定 |

無料経路の成功は、日付付き **1017** の実行証拠ではない。確認できた実モデル指定は日付なしの無料 alias であり、公式 API の rolling alias も固定版とは区別する。

観測時点の通常 HOME の OpenCode 接続 metadata は空。無料経路の実証では鍵を供給せず、試験用の分離 config/data/cache を使い、通常の既定モデル・接続設定を変更していない。

実機の CLI は次の Nix 出力を使用した。これは観測値であり、今後の実行を手転記したパスや checksum だけで許可するものではない。

```text
/nix/store/jcy8bg3is10bqjhb99ykps3q6diz3bl8-opencode2-2.0.30/bin/opencode
```

## GitHub への認証

| 対象 | 経路・保存先 | 確認済み | 未完了 |
|---|---|---|---|
| OpenCode の shell から使う gh | NixOS own OCI の既存 gh wrapper → repo が宣言した principal → native gh。principal は `roccho-dev`、保存先は `/work/repos/.auth/roccho-dev/gh` | `/work/repos/resources.git/.worktrees/gh-auth-20261018` を既存 stable helper で binding。bind exit 0、9設定を独立読戻し、worktree clean | 2026-10-18 19:50 JST 時点で native device login は追加 `read:org` の本人許可待ち。保存先の config/hosts は未生成。認証成功は未証明 |
| Codex の GitHub connector | Codex の既存接続 | `roccho-dev` の profile を取得済み | この接続を NixOS の gh 認証として扱わない |

`gh` は cwd の repo binding で認証先を選ぶ。repo 外での「未認証」表示や `-R` 指定だけでは、binding 済み repo の状態を判定できない。wrapper は `GH_TOKEN` などの上書きを除去するため、環境変数を足す修正案はこの経路に適合しない。

本人許可後は、同じ保存先の native account metadata と実 API の login が `roccho-dev` で一致し、同じ worktree から wrapper 経由の API が通ることを確認する。token・device code・認証 URL の一時値はこの表へ記録しない。

## 別経路を加えるとき

現行経路の設定・認証・履歴は保持する。別経路は提供元と実モデル指定、実行場所、認証方式、実応答とツール実行の結果をこの表へ追記し、「予定」「候補」「接続済み」「実証済み」を実際の到達点に合わせて更新する。予定の記載だけで新しい鍵の発行・有料利用・既定経路の切替を実施しない。

DSH は OpenCode の接続先ではなく別クライアントである。[導入 PR #38](https://github.com/roccho-dev/resources/pull/38) の準備・CI・実機 UI 検証と、通常 profile への採用完了を区別する。OpenCode の認証が DSH に引き継がれたとは扱わない。

## 参照

- [無料 alias の提供元定義](https://github.com/anomalyco/models.dev/blob/dev/providers/opencode/models/deepseek-v4.1-flash-free.toml)
- [日付付き 1017 の掲載](https://models.dev/models/deepseek/deepseek-v4.1-flash-1017/)
- [DeepSeek 公式の 1017 更新案内](https://api-docs.deepseek.com/updates/#deepseek-v41-flash-1017-update)
- [native gh と binding の実装](../profile/gh.nix)
- [提供入口・版固定・更新と復旧](windows-migration-preparation.md)
