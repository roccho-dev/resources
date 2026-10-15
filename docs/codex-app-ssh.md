# Codex desktop App から VersaPro own OCI へ SSH 接続する

Windows 上の Codex desktop App が、物理 VersaPro の NixOS 上で動く own OCI（dev, UID 1000）へ標準 SSH で入り、
`/work/repos` で開発するための client 側宣言。VersaPro 側（NixOS・own OCI・Codex/Pi の T）は `nixos/` が持つ。

## 宣言

- `windows/ssh/versapro.config`: 2 つの Host。
  - `versapro-ssd`: 物理 VersaPro の root 管理経路（1 段目）。`192.168.0.103` は LAN 上の locator にすぎず、
    同一性は pin した host key（`HostKeyAlias versapro-ssd-1804BQ0831CWM370`）で確かめる。
  - `versapro-own-oci`: own OCI の dev。sshd は host の loopback（`127.0.0.1:2223`）だけで待つため、
    `ProxyJump versapro-ssd` で 1 段目を経由する。ProxyJump は既定の config を読むので、1 段目も同じ strict な pin のまま使われる。
- `windows/ssh/versapro.known_hosts`: 上の 2 つの HostKeyAlias の公開 host key（各 1 行）。秘密ではない標準の pin。
  秘密鍵・認証情報はこの repository に置かない。認証は既存の `~/.ssh/id_ed25519_windows_own` を使う。

## 置き方

1. `~/.ssh/versapro/known_hosts` を、存在しない場合だけ `windows/ssh/versapro.known_hosts` と同じ bytes で置く。
2. `windows/ssh/versapro.config` の Host block を main の `~/.ssh/config` に追記する。同名の Host が既にあれば追記しない。
   **Include 行は追加しない。** main config の Include は `Include windows-rent/config windows-own/config` だけとする
   （windows `hosts/common/win.ps1` の SSH writer はそれ以外の Include と Match を拒否する）。
   `versapro-ssd` / `versapro-own-oci` は既存の `g6i3-own` / `windows-rent` / `nixos-vm` と名前が衝突しない。
3. 確認: `ssh -G versapro-own-oci` が `proxyjump versapro-ssd`、`hostkeyalias versapro-own-oci`、
   `stricthostkeychecking true` を返し、`ssh versapro-own-oci id -u` が `1000` を返すこと。

## Codex App

- 接続の登録は公式の deeplink を使う: `codex://settings/connections/ssh/add?name=versapro-own-oci`
  （既存の SSH alias を管理接続として追加する。自動接続は無効）。その後 project として `/work/repos/nixos-dev-smoke` を開く。
- App は login shell の PATH にある `codex` を remote で起動する。own OCI では `/bin/codex` が own-dev profile を指す。
- own OCI の Docker 既定 seccomp では user namespace が使えず、Codex 内側の sandbox（bubblewrap）が動かない。
  そのため、この接続の thread では OCI を外側の隔離境界として「Full access」を thread ごとに選ぶ。
  既定の approval / sandbox 設定は変えない。信頼済みの repository だけで使う。

## 変更時（owner が行う）

- LAN の locator が変わったとき: `versapro-ssd` の `HostName` を source で更新する。host key は変わらないので pin は更新しない。
- host key が変わったとき（SSD の再導入、own OCI の home volume を失ったとき）: 既存の pin を上書きせず、
  信頼済みの経路で新しい公開鍵を確かめてから、owner が source の pin を更新し、PR で review する。
  `StrictHostKeyChecking` を弱めて回避しない。
