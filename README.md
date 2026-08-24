# FC町田ゼルビア 2026/27 試合日程（非公式ファンページ）

町田ゼルビアの公式サイト（zelvia.co.jp）の情報をもとにした、非公式のスケジュール表示ページです。

- `index.html` … 表示ページ本体（Android Material Design風）
- `schedule.json` … 試合データ本体。ページはこれを読み込んで表示する
- `scripts/update_schedule.py` … 公式サイト（日程）とJリーグ公式サイト（結果スコア）を再取得して `schedule.json` を自動更新するスクリプト
- `.github/workflows/update.yml` … 上記スクリプトを毎日自動実行するGitHub Actions設定

---

## 1. オンラインに公開する（GitHub Pages・無料）

1. GitHubアカウントを作成（すでに持っていればスキップ）
2. 新しいリポジトリを作成する（例: `zelvia-schedule`）。Public（公開）にする
3. このフォルダの中身をすべてそのリポジトリにアップロードする
   - GitHubのWeb画面から「Add file → Upload files」でドラッグ&ドロップでもOK
   - `.github/workflows/update.yml` を含む隠しフォルダも忘れずに（Web UIでアップロードする場合、フォルダごとドラッグすれば含まれます）
4. リポジトリの **Settings → Pages** を開く
5. 「Build and deployment」の Source を **Deploy from a branch** にし、Branch を `main` / `/(root)` に設定して Save
6. 数分待つと `https://あなたのユーザー名.github.io/zelvia-schedule/` で公開されます

これで誰でもそのURLにアクセスすれば見られるようになります。

---

## 2. 自動更新を有効にする

GitHub Pagesと組み合わせると、放っておいても毎日最新の日程に更新されます。

1. リポジトリの **Settings → Actions → General** を開く
2. 「Workflow permissions」を **Read and write permissions** に変更して Save
   （これをやらないと、自動更新スクリプトがファイルをコミットする権限がなくエラーになります）
3. これで `.github/workflows/update.yml` の設定により、**毎日 日本時間7:00** に自動で
   1. 公式サイト（zelvia.co.jp）の試合日程ページを取得し、J1・ルヴァンカップの日程を最新化
   2. Jリーグ公式サイト（jleague.jp）の「戦績」表を取得し、消化済み試合のスコアを反映（J1に限らず、天皇杯・ルヴァン・ACL2も日付が一致すれば反映されます）
   3. 変更があれば `schedule.json` を自動コミット
   が実行されます
4. GitHub Pagesは、mainブランチが更新されると自動で再公開してくれるので、追加の作業は不要です

手動で今すぐ更新を試したい場合は、リポジトリの **Actions** タブ →
「Update Zelvia schedule」→ **Run workflow** ボタンで即実行できます。

### 更新結果の確認方法
- Actionsタブで実行ログが見られます。緑のチェックが成功、赤い×が失敗です
- 失敗しても `schedule.json` は上書きされない設計になっているので、ページが壊れることはありません

---

## 3. 天皇杯・ACL2（AFCチャンピオンズリーグ2）について

以下の理由により、この2つの大会は**自動更新の対象外**にしています。

- **天皇杯**: 対戦相手が「未定」の間は公式サイトの表記フォーマットが変わり、自動取得が不安定なため
- **ACL2**: 個別のマッチデー日程（対戦日・キックオフ時刻・会場）が、公式サイトの「試合日程一覧」にまだ掲載されないケースが多いため（2026年8月時点ではグループ組み合わせのみ発表・詳細は「決定次第お知らせ」の状態でした）

これらの情報が公式発表されたら、`schedule.json` を直接編集してください。1件あたりの書式は以下の通りです。

```json
{
  "comp": "ACL2",
  "round": "MD1",
  "home": true,
  "sort": "2026-09-15",
  "date": "09.15",
  "day": "wk",
  "dayLabel": "火",
  "time": "19:00",
  "opp": "上海申花（中国）",
  "logoText": "申花",
  "stadium": "町田GIONスタジアム"
}
```

- `comp`: `"J1"` / `"YBC"`（ルヴァン）/ `"EMP"`（天皇杯）/ `"ACL2"`
- `home`: ホームなら `true`、アウェイなら `false`、未定なら `null`
- `sort`: 並び替え用のISO日付（`YYYY-MM-DD`）。この値で全体が日付順に並びます
- `day`: `"sat"`（土=青） / `"sun"`（日=赤） / `"wk"`（平日=グレー）
- 相手の公式ロゴ画像を使いたい場合は `logo` に `zelvia.co.jp` のファイル名を指定、
  ロゴ画像が無い場合は `logoText` に短い略称（2〜3文字程度）を指定してください

編集して保存し、GitHubにアップロード（コミット）すれば、Pagesが自動で反映します。

---

## 4. 注意事項

- このページは非公式のファン制作物です。キックオフ時刻・会場は変更になることがあります
- 最新の正式情報は必ず [公式サイトの試合日程ページ](https://www.zelvia.co.jp/match/game/series/2026-27/) をご確認ください
- 自動更新スクリプトは公式サイトのHTML構造に依存しています。サイトが大幅リニューアルされると
  動かなくなる可能性があります。その場合は `scripts/update_schedule.py` の正規表現部分を
  実際のページ構造に合わせて調整してください
