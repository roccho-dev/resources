# resources

場所や端末が変わっても、積み重ねた判断を失わず、自分の意図に沿った環境で仕事を続けるために。

[提供入口・版固定・更新と復旧](docs/windows-migration-preparation.md) ／ [提供開始の現行判定・実証](https://github.com/roccho-dev/resources/pull/31)

```text
resources/
├─ flake.nix           # 全体の整合性を保つため
├─ flake.lock          # 時間が経っても同じ前提へ戻れるため
├─ profile/            # 同じ判断を繰り返す負担を減らすため
├─ nixos/              # 固有の前提を尊重し、無理な共通化を避けるため
├─ windows/            # 異なる制約の下でも、必要な使い心地を失わないため
├─ oci/                # 用途と信頼境界の違いが、互いの継続性を損なわないため
├─ extensions/         # 外部との関係の変化に、全体の判断を引きずられないため
├─ docs/               # 判断の理由を将来の自分へ残すため
└─ .github/workflows/  # 変更を信頼して受け入れる根拠を失わないため
```

共有すべき判断は一貫させ、違いが必要な場所には違いを残す。環境を作り直すことが、考え直すことの繰り返しにならないようにする。

### Standalone versa semlint owner consumer

`packages.x86_64-linux.own-semlint-versa` exposes only `ops-semlint-owner`. Its compile-time binding uses the existing own identity and the existing JEV ciphertext from envs, checks currentness and recipient through the shared launcher, builds the exact Ops `semlint-owner` package before decryption, and passes stdin to that fixed entry under a clean child environment. The only arguments are exact accepted `--envs-sha` and `--ops-sha`; no key, target or program selector is accepted.

This standalone output is not added to the default own profile, Pi, Core or Base. The compiled-binding check is not live-key validity, provider admission, G1/G2 or automatic return evidence. Real use requires a separate finite source/target/input admission; actual store, operator and provider costs remain unknown until measured.
