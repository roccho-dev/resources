# resources

NixOS・Windows・非NixOSのNix OCIを、宣言と検証済み成果物から再現する。OS/user設定とIaCの正本をここに集める。

現時点は構成案。実装の移管・適用はまだ行わない。

## Tree

```text
resources/
├─ flake.nix / flake.lock        # 合成・公開output・依存固定
├─ profile/
│  ├─ dev.nix                    # own/rent共通の開発package
│  ├─ gh.nix                     # own/rent/dev共通のprincipal routing
│  ├─ codex.nix / releases.json  # 公式releaseの選択・固定・検証契約
│  └─ fonts.nix                  # Linux/Windows共通のfont選択
├─ nixos/                        # 新設
│  ├─ system.nix / user.nix      # OS/serviceとuser設定
│  └─ hosts/<host>.nix           # hardware・host固有入力
├─ windows/                      # 現hosts/commonを移す
│  ├─ nix.nix                    # native OS/user設定・package選択
│  ├─ pack.py / test_pack.py     # 宣言→inventory/manifest/ZIP
│  ├─ win.ps1                    # 適用・照合・復旧・ledger
│  └─ …                         # 既存helper・proof・READMEを保持
├─ oci/
│  ├─ common.nix                 # own/rentの共有mount・Nix設定
│  ├─ dev/                       # 公式Nix bootstrap＋trusted dev image
│  ├─ own/                       # local開発・専用home/work/nix
│  └─ rent/                      # remote開発・SSH/Tunnel・状態継続
├─ extensions/
│  ├─ github/                    # 資源rootと限定した適用入口
│  ├─ git-state/                 # backend toolchainとsynthetic proof
│  ├─ release-watch/             # release検証・更新提案
│  └─ cloudflare/                # 将来envsから移管するIaC
├─ docs/                         # 設計・受入・移行記録
└─ .github/workflows/            # 既存の検証・配布を保持
```

図の省略は削除を意味しない。dev/own/rentは用途と信頼境界で分ける。dev専用profileは残し、共有できるgh等だけを同じ定義から使う。

## 宣言と適用

```text
Config(r, h) = Spec(r) ⊕ Binding(r, h)
# roleの不変条件と対象固有入力を合成する
# Windows復帰用manifestは生成projection。別の手編集Bindingを作らない

Artifact(r, h) = Build(Source, Config(r, h), LockedInputs)
# NixOS closure / Windows ZIP / OCI image・profile
# CIが検証した同じ成果物を配布する

Runtime' = Apply(Artifact(r, h), Secret, Runtime)
# 秘密と保存状態を成果物から分離し、宣言した差分を適用する
# 状態継続・失敗時復旧も確認する
```

Windowsは既存のNix宣言→Python pack→PowerShell適用を引き継ぐ。Windows nativeでNixを実行する前提にはしない。

公式の[nixos/nix](https://releases.nixos.org/nix/nix-2.34.0/manual/installation/installing-docker.html)はNixと最小実行環境を持つコンテナ。NixOSのOS構成とは別に扱い、bootstrap用digestを固定する。独自dev/own/rent imageの定義も保持する。

## 境界

- resources: IaC、OS/user設定、成果物、targetの適用実装・秘密slotの形式とwriter。
- envs: 暗号化秘密、供給/配置、非秘密の受渡し記録。
- source tree外: 平文秘密、private identity、auth/session、volume、ledger、provider state。

Cloudflare rootは現在envsにある。移管時に責務と参照を切り替え、同じ資源を二つのrootで管理しない。stateの保存先や所有権の変更は別工程とする。

## 移行案

基準は[windows proposals / 615ea7d](https://github.com/roccho-dev/windows/tree/615ea7d97edaf5889bd7968f5a1feb90b8297b09)。

- hosts/profile → profile、hosts/own/codex.nix → profile/codex.nix。
- hosts/common → windows。共通font選択だけprofile/fonts.nixへ。
- hosts/own → oci/own、hosts/rent → oci/rent。
- flake.nix内のrent本体・state import・seed/start → oci/rent。既存hosts/rent/nix.nixはssh.nixへ。
- oci/devは保持、infra → extensions。NixOS構成は新設。

相対path、CI、Release/source SHA、consumer契約を追随させる。image名・volume名・ledger・SSH key path・管理対象資源・state backendは、一括置換しない。既存proofと復旧経路を保ち、resourcesへの切替確認後にwindowsをdeprecatedにする。

構成の検討: [完成形ツリー](https://github.com/roccho-dev/resources/issues/1)
