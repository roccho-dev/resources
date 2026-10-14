# Host / Relation の隔離SOURCE候補（未採択）

[ADRS #630](https://github.com/roccho-dev/adrs/issues/630) と [resources #1](https://github.com/roccho-dev/resources/issues/1) の**既存の意味と責務**を変更しない。合意・admission済みの正式Host関係schemaや実配置の正本ではない。

`nixos/tests/host_relation_source.py`はCIのメモリ内だけで、外部から渡されたHost ID、`contains`、`manages`、任意`wrap`の関係を検査する。Host IDをOS・repo・image・path・implementation refから**生成しない**。異なるHostで同じsource実装を再利用できる。

- `contains(parent,child)`：外部から渡されたHostだけを参照し、自己参照と循環を拒否。同じ`scope`の同一childに異なるparentがある場合は拒否。別`scope`の実体は別に判定。
- `manages(parent,child)`：containsとは独立で複数管理元を許可。権限/認証/管理作用の成功を**推定しない**。
- `wrap`：contains上のみ任意属性。OCI/VM以外や`null`でもHostの同一性を変えない。wrapが無いHostを拒否しない。導入時の値集合や正式表現は既存ownerのadmission判断に残す。
- 検証出力は常に`admission=NOT_ADMITTED`、`observed_running=UNPROVEN`、`target_authority=NOT_GRANTED`、`effect=FORBIDDEN`。現在の実Hostを読まず、環境変数/秘密・SSH・Docker・Nix配備・新runtime台帳を使わない。

### SOURCE受入とowner境界

[既存`own-oci.yml`](https://github.com/roccho-dev/resources/blob/proposals/.github/workflows/own-oci.yml)の`source-vm`ジョブにread-onlyのPython隔離試験のみ追加。既存trigger/permissionsは不変、従来のNixOS VM結果も引き続き必要。実Hostのrelation採択、同時点の稼働同定、後のCI別source/Hostの結合、認証・管理権限は別の正規許可と実証が必要。

**ただの提案に留める理由**：ADRS #630 と resources #1 は「意味・どの既存schemaで宣言するか」をまだ正式採択していない。SOURCEでできる反例テストを先に実装し、**通常のHost生成/更新入口へ接続しない**。このfixtureが正しかっただけでV6 S1/S2/S3の実Target受入は閉じない。

責任：Host/Relation/wrap＝resources/ADRS、Build/Tool候補C＝windows、admitted D/Binding＝envs、actual O/E＝各Target。各PRのhead/tree/runを別途読戻し、同じ固定RがSOURCE範囲で独立反証する。
