# Browser/Input結合 — tty-split-20261013-v1 / C

## 目的

A（Chrome ↔ cdp-tty）とB（bcon ↔ Meltype ↔ Shell/Editor）を独立完成させ、
最後に同じ候補版setで bcon → Meltype → cdp-tty → 既存Chrome Target を結合する。
Xという中間製品、別のBrowser/Profile、追加の変換器・runnerは作らない。

A: [ops #534](https://github.com/roccho-org/ops/pull/534)
B: [Meltype #3](https://github.com/roccho-dev/Meltype/pull/3)
結合の移行元: [resources #3](https://github.com/roccho-dev/resources/pull/3)、
[Meltype #2](https://github.com/roccho-dev/Meltype/pull/2)。
設計はadrs #615/#618を参照し、正式採択や元条件の置換をこの文書だけで行わない。

## 受入の受渡し

| 旧要件/証拠 | 新しい所有と扱い |
|---|---|
| Meltype #2の実Native/候補/子PTY/TTY復旧 | Bの単独証拠をexact版で受け取る。CでCoreを複製しない |
| cdp-ttyの表示/入力/継続・旧ops #433反例 | Aが単独完成。Cはその同版を消費し、Meltype修正でViewer不具合を隠さない |
| bcon → Meltype → cdp-tty → 同じTargetの日本語DOM | Cの実入力受入。直接DOM書換えや試験側insertTextで代用しない |
| typed候補表示/選択/確定 → DOM | Cの実入力受入。元ID/型/選択をBの証拠と照合し、表示差分だけで確定成功にしない |
| resources #3のE01〜E12 | 本結合が担う部分との対応を残す。残りのHost契約を自動closeしない |

## 移設前の保全

旧Meltype #2の `d673872560f7e6b3b20fed1452f6949c55c722f1` と旧resources #3の
`8f3ef91df8e33b6188f970d302d8dd4baeb6fee8` は移行元であり、変更済み新成果と混同しない。
C側の実試験・CI入口・証拠出力・旧要件対応が成立するまで、旧結合試験を削除/skip/弱化しない。
移設先が未完成の間もA/Bの独立作業は進める。個別合格だけで全体DONEにはしない。

## 結合受入

- A/Bの候補版commit/tree、実artifact hash、bcon/OS/試験版を固定し、同じ組を実行する。
- 実bconの画面とキーから、通常日本語および型付き候補を同じChrome Target/入力欄へ確定し、DOMを別経路で読戻す。
- 候補画像とBrowser画像の共存、誤入力先/二重確定/古い応答の拒否、resize、再接続、終了、端末復旧を検査する。
- Viewer終了後もChrome PID/Target/Profileを保持。秘密・利用者の本番Profileを試験へ使わない。
- 失敗は境界前後の実値と版を残し、原因コードの所有先A/Bへ返す。Cが他repoの製品コードをコピー修正しない。
- 実物理端末・実Provider・独立Rなど、必要な証拠が欠ければ未達を残す。VM/fixtureを昇格させない。
- A/B各mergeとCの全体合格は別。Cのmergeには固定候補版set全体の合格・独立reviewを要求する。

現在の差分は結合責務・移設条件の固定だけ。実試験の移設・再実行・全体完成は未完了。
本PRは新規恒久OS設定、本番配備、既存PRのmerge/close、担当/権限変更を行わない。
