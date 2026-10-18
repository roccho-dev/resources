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

Codex App は `~/.ssh/config` とその Include だけから alias を見つける。置くのは windows の明示 opt-in mode
`ClientSsh` だけで、`~/.ssh/config` へ手で追記しない。

実行の条件:

- `ClientSsh` / `ClientSshTest` は、install 済みの logon 用 runtime（`kind=own-resume-runtime`）では動かない。
  その runtime は `OwnResume` / `OwnResumeTest` しか受け付けない。
- 使うのは、windows の canonical な公開 Release の `windows-dist.zip` である。
  - 次の 3 つの checksum が一致することを確かめる: CI の build が出した値、Release の `.sha256`、
    受け取った bytes から計算し直した値。
  - そのうえで、新しい空のディレクトリ（`<dist>`）に展開したものを使う。
  - 展開後は、`win.ps1` が自身の inventory を検証する。
  - `-Mode Validate` の `source` が、その Release の commit と一致すること。
- 実行するのは、宣言された host（G6I3）で、Explorer から起動した、昇格していない Windows PowerShell 5.1（`powershell.exe`）とする。
  次の process は、`HostCaller` の package 文脈と権限の検査で、書き込む前に拒否される:
  packaged app（`\WindowsApps\` 配下）から起動したもの、PowerShell 7、管理者、SYSTEM。
- 実行ポリシーは、host の既存の設定のまま使う。`-ExecutionPolicy` の指定、ファイルの unblock、ポリシーの変更はしない。
  拒否された場合は止めて、その事実を返す。
- 2 つの入力は、resources の exact な公開 revision の checkout（`<checkout>`）にある絶対 path で渡す。

```powershell
powershell.exe -NoProfile -File "<dist>\win.ps1" -Mode Validate
powershell.exe -NoProfile -File "<dist>\win.ps1" -Mode ClientSshTest -ClientConfig "<checkout>\windows\ssh\versapro.config" -ClientKnownHosts "<checkout>\windows\ssh\versapro.known_hosts"  # 読むだけ
powershell.exe -NoProfile -File "<dist>\win.ps1" -Mode ClientSsh -ClientConfig "<checkout>\windows\ssh\versapro.config" -ClientKnownHosts "<checkout>\windows\ssh\versapro.known_hosts"
```

- 移行の前の `ClientSshTest` は、`Client SSH slot differs from the declaration; pending.` で止まるのが正しい。
  - ここまでで確かめられるのは、配布物、引数、実行の文脈、入力、所有物の drift、alias の衝突だけである。
  - 枠の所有、backup、他に所有された Include 行は、`ClientSsh` が書き込む前に検査する。
- `HostRemove` は、client の枠だけを外す操作ではない。所有しているすべての host の effect を元に戻す。
  client の巻き戻しには使わない。この guide は、client だけの巻き戻しを提供しない。

- `ClientSsh` は 2 つの file を所有 slot `~/.ssh/windows-client/{config,known_hosts}` に置く。そのうえで main config の
  所有 Include 1 行を `Include windows-rent/config windows-own/config` から
  `Include windows-rent/config windows-own/config windows-client/config` に移す。元の bytes は保つ。
  そのため各 Host の `UserKnownHostsFile` はこの slot（`~/.ssh/windows-client/known_hosts`）を指す。
- 入力と所有の検査で、次のいずれかに当たれば何も書かずに拒否する:
  - 宣言が strict・batch・identity-only・pin 済みでない。
  - alias が他の file と衝突する。
  - 所有物が変わっている。
- 最後の `ssh -F ~/.ssh/config -G` による確認は、収束した後の事後条件である。
  これが失敗した場合は止める。書いた所有状態はそのまま残る。
  - 原因を取り除いた後で、同じ `<dist>` と `<checkout>` で同じ `ClientSsh` を再実行する。
  - それで解決できない場合は止めて、そのままの状態を返す。
  - `HostRemove` は使わない。`~/.ssh/config`、`windows-client` の枠、ledger も手で編集しない。
- `ClientSsh` を使わない既存・新規の legacy mode は 2 path のままである。
- `versapro-ssd` / `versapro-own-oci` は既存の `g6i3-own` / `windows-rent` / `nixos-vm` と名前が衝突しない。

採用条件（adoption gate）:

1. `ClientSsh` を含む windows の公開 revision がある。その revision は canonical で、exact な CI と R の受け入れを済ませている。
2. 移行の前に、P が規範記録で次を確かめ、共有する reader の採用を明示的に受け入れる。
   - 確かめる内容: 移行の後に、`ClientSsh` より前の版の `OwnLogon`/`HostRemove`/`RentSsh`/`OwnSsh` を実行しない。
   - 理由: 旧版はどれも 3 path の Include 行を受け付けない。旧版の `OwnLogon` は、logon Task を切り替えた後で失敗する。
     つまり書く前に拒否するのではなく、途中まで作用してから失敗する。
3. その後に、別の LIVE_GO がある。

この条件がそろうまでは、手作業で置いた `~/.ssh/versapro-installer-20261008/config-own-oci` を `-F` で指定する経路をそのまま使う。
この経路は main config に触れない。source の外にあって保持しているだけの一時的なもので、IaC の一部ではない。

確認は次の 2 つ:

- `ssh -G -F ~/.ssh/config versapro-own-oci` が `proxyjump versapro-ssd`、`hostkeyalias versapro-own-oci`、
  `stricthostkeychecking true`、slot の `userknownhostsfile` を返す。
- `ssh versapro-own-oci id -u` が `1000` を返す。

## Codex App

- 接続の登録は公式の deeplink を使う: `codex://settings/connections/ssh/add?name=versapro-own-oci`。
  既存の SSH alias を管理接続として追加するもので、自動接続は無効。
  使うのは上の `ssh -G -F ~/.ssh/config` が alias を解決した後だけ。その後 project として `/work/repos/nixos-dev-smoke` を開く。
- App は login shell の PATH にある `codex` を remote で起動する。own OCI では `/bin/codex` が own-dev profile を指す。
- own OCI の Docker 既定 seccomp では user namespace が使えず、Codex 内側の sandbox（bubblewrap）が動かない。
  そのため、この接続の thread では OCI を外側の隔離境界として「Full access」を thread ごとに選ぶ。
  既定の approval / sandbox 設定は変えない。信頼済みの repository だけで使う。

## Pi の ChatGPT OAuth

ブラウザは Windows、Pi は NixOS 上の own OCI で動く。この配置では、OAuth の戻り先
`127.0.0.1:1455` を標準 SSH で Pi の受信口へ転送する。ブラウザに認証画面が出ただけでは認証完了ではない。
screen-only Worker の認証画面は、この native 受信口を起動しない。以前の callback URL は再利用しない。

既存の Go 用入口とは保存先を分ける。

| 入口 | provider | 認証の保存先 |
|---|---|---|
| 通常の `pi --envs-sha …` | `opencode-go` | `~/.pi/agent-versapro-own-oci` |
| 同じ配布物の `pi-upstream` | `openai`（ChatGPT subscription） | `~/.pi/agent` |

Go 用 launcher は自身の `auth.json` が canonical な Go command と一致することを検査する。
そこへ ChatGPT の認証を追加したり、既存の認証ファイルをコピーしたりしない。ChatGPT 用に新しい wrapper、alias、profile は不要。

1. Windows で、上の strict な alias を使って接続する。1455 が使用中なら所有プロセスを確認し、別の認証を止めて奪わない。

   ```powershell
   ssh -tt -F "$HOME/.ssh/config" -o ExitOnForwardFailure=yes -L 127.0.0.1:1455:127.0.0.1:1455 versapro-own-oci
   ```

2. OCI では、採用済み Tool の resources revision に属する upstream 出力を使う。
   `<resources-revision>` は実際に配置した版へ置き換える。評価だけで新しい build や profile 選択は行わない。

   ```sh
   pi_output=$(nix eval --raw "github:roccho-dev/resources/<resources-revision>#packages.x86_64-linux.own-profile.piUpstream.outPath" --no-write-lock-file)
   test -x "$pi_output/bin/pi-upstream"
   cd "$HOME"
   PI_CODING_AGENT_DIR="$HOME/.pi/agent" PI_PACKAGE_DIR="$pi_output/share/pi" \
     "$pi_output/bin/pi-upstream" --no-tools --no-extensions --no-skills --no-prompt-templates --no-context-files --no-session
   ```

3. Pi の `/login openai` から、新しく生成された正規の認証 URL をブラウザで開く。
   先に Windows の `http://127.0.0.1:1455/` が Pi の 404 を返すことを確かめると、転送と受信口の疎通を確認できる。
   `ERR_CONNECTION_REFUSED` は受信口へ到達していない状態なので、本人に同意をやり直してもらう前に Pi と転送を直す。
   アカウント選択と同意は本人が行う。Pi と SSH は callback を受け取り保存が完了するまで終了しない。

4. ブラウザの `ChatGPT authentication completed`、Pi の login 成功、同じ保存先での native status を確認する。

   ```sh
   PI_CODING_AGENT_DIR="$HOME/.pi/agent" PI_PACKAGE_DIR="$pi_output/share/pi" \
     "$pi_output/bin/pi-upstream" auth check --provider openai --json --no-refresh
   stat -c '%a %u %n' "$HOME/.pi/agent" "$HOME/.pi/agent/auth.json"
   ```

   `status=ready` / `authType=oauth`、実行ユーザー所有の directory 0700 / file 0600 が確認条件。
   `--credentials`、認証ファイルの本文、token、認証 URL・code・state はログや PR へ出さない。
   この status は保存状態の確認であり、実推論の成功とは別である。利用可能性は、許可された最小の no-tools 応答を同じ入口で確認する。
   完了後は Pi と転送を閉じ、以後も同じ native 入口と保存先を使う。認証期限・失効時には正規の再認証が必要になる。

2026-10-18 に、配置済み Pi 1.0.4 のこの経路で callback、本人同意後の保存、native `ready/oauth` を実確認した。
[配置元の resources revision](https://github.com/roccho-dev/resources/commit/f859cc4b0a510d78e465fcf4c57be373678dad35) で
上の `piUpstream.outPath` も評価し、既存の Pi 1.0.4 出力と一致することを確認した。
CI の package/profile 検査や Worker の画面実証は、この実認証の代わりにしない。
upstream の [provider 手順](https://github.com/earendil-works/pi/blob/v1.0.4/packages/coding-agent/docs/providers.md) と
[標準保存先の設定](https://github.com/earendil-works/pi/blob/v1.0.4/packages/coding-agent/docs/configuration.md) も参照する。

## 変更時（owner が行う）

- LAN の locator が変わったとき: `versapro-ssd` の `HostName` を source で更新する。host key は変わらないので pin は更新しない。
- host key が変わったとき（SSD の再導入、own OCI の home volume を失ったとき）: 既存の pin を上書きせず、
  信頼済みの経路で新しい公開鍵を確かめてから、owner が source の pin を更新し、PR で review する。
  `StrictHostKeyChecking` を弱めて回避しない。
