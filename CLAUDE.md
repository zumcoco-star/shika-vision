# shika-vision

ブラウザだけで動く読み上げアプリ集(`index.html`=歯科ビジョン読み上げ / `yomiage.html`=画像よみあげ)。
それぞれ HTML 1ファイルで完結する静的Webアプリ(ビルド・依存なし)。

## このリポジトリは public

**このリポジトリは一般公開されており、GitHub Pages で誰でもアクセスできる状態にある。**

- 公開URL: https://zumcoco-star.github.io/shika-vision/ (`.github/workflows/pages.yml` が main への push ごとに自動デプロイ)
- したがって**個人情報・所属先の内部情報・認証情報・IDの類は、いかなる形でもコミットしない**。
  実データ・サンプル実データのハードコードも禁止。
- `actions/configure-pages` の `enablement: true` により、Pages を設定画面で無効化しても
  次の main への push で再有効化される。配信を止めるにはワークフロー自体の削除が必要。
- 可視性(public/private)の変更、Pages の有効/無効の切り替えは**オーナーだけが判断する**。
  Claude は自分の判断でこれらを変更しない。

## 共通の制約

- **依存追加・ビルドツール導入はしない。単一ファイル構成を保つ**
  (実行時のCDN読み込みは `yomiage.html` のOCRライブラリのみ限定例外・下記)
- データはブラウザの localStorage / IndexedDB のみに保存。**サーバ・外部送信なし**。この性質を壊す変更はしない
- **ブラウザ標準ダイアログ(alert/confirm/prompt)は使わない**。確認・入力UIはアプリ内実装
  (インライン確認行・トースト通知)とする。iframe埋め込み環境ではサンドボックスにより
  標準ダイアログが無効化され「ボタンを押しても何も起きない」不具合になるため
- iPhone / iPad のホーム画面追加での利用を想定。`viewport` / `apple-mobile-web-app-*` メタタグを維持する
- 表示文言はすべて日本語
- 変更は作業ブランチ + PR 経由で行い、**公開して問題ない内容か確認してから main にマージする**
  (main へのマージ = 即時の一般公開)

## 音声の方針(両アプリ共通)

- Web Speech API を使用。既定では端末内(`localService`)の声を優先し、ブラウザ提供のネット経由音声は
  「（オンライン音声）」と明示ラベルの上、ユーザーが自分で選んだ場合のみ使う
  (読み上げテキストが外部に出るのはその場合のみ、という整理)
- 長文は文単位に分割して1文ずつ発話し、`onend` で次へ送る。
  pause/resume は環境差が大きいため使わず、「停止 + 現在文から再開」方式とする
- 読んでいる文をハイライトし、文のタップでそこから再生できるようにする

## 歯科ビジョン読み上げ (index.html)

- 日本歯科医師会「2040年を見据えた歯科ビジョン ― 令和における歯科医療の姿 ―」(2020年10月公表)の
  本文全4章を収録して読み上げるアプリ。設定としおりは localStorage(キー: `vision2040-yomiage-v1`)のみに保存
- 本文データは HTML 内に `<script type="application/json" id="bookData">` として埋め込む
  (単一ファイル・依存なし・CDN不使用を維持)。**本文の修正はこのJSONを直接いじらず、生成手順からやり直す**
- アプリ内に出典・「図表は非収録」の注記を常時表示する
- **本文データの生成手順**(原典は公表されているPDF):
  - PDFをローカルに取得できる章は `pypdfium2` でページ単位にテキスト抽出する
  - ファイルサイズ等の都合で直接DLできない章は、別経路で取得したテキストを使う
  - **どちらの経路でも、ページ末尾に次ページ冒頭の数行が先読みで混入する**。
    行単位で重なりを検出して落としてから段落を再構成すること(この処理を省くと本文が二重になる)
- 動作確認は Playwright ヘッドレスChromiumで、`speechSynthesis` をモックに差し替えて
  読み上げの連鎖・図表スキップ・停止・連続再生まで検証する

## 画像よみあげ (yomiage.html)

- 画像(書類・本・貼り紙など)を保存すると端末内OCRで文字を読み取り、音声で音読するアプリ。
  データ(画像・テキスト・設定)は IndexedDB(`yomiage-db`)と localStorage(キー: `yomiage-settings-v1`)
  のみに保存し、**画像・テキストの外部送信なし**
- **OCRライブラリ(Tesseract.js v6)のみ、初回に jsDelivr CDN から実行時に取得する**
  (「依存追加なし・単一ファイル」原則の限定例外。npm導入・ビルドはしない)。
  取得するのはプログラム本体と日本語認識データ(計約4MB・ブラウザ内にキャッシュ)だけで、
  OCR処理自体はWebAssemblyで端末内実行。オフライン時はOCR不可だが、保存済みデータの音読と
  テキスト手入力は動く
- OCR精度の作り: 前処理(EXIF向き・拡縮・グレースケール・コントラスト伸長)
  → Tesseract(jpn best_int / 縦書きは jpn_vert + PSM5)
  → 後処理(NFKC正規化・CJK間の誤空白除去・文末判定つき行結合・ノイズ行除去)
- `window.__tessPaths` で workerPath/corePath/langPath を上書き可能(テスト・自己ホスティング用フック)。
  動作確認は Playwright ヘッドレスChromiumで、CDN取得物を npm 取得のローカルファイルに差し替えて
  実OCRまで通すE2Eで行う(テスト資材はリポジトリに含めない)

### 自己完結版ビルド (scripts/build-yomiage-ipad.mjs)

外部CDNが遮断される埋め込み環境(CSPの厳しいiframe等)向けに、OCR一式
(Tesseract.js 本体・worker・WASM コア・日本語/縦書きデータ)をすべて埋め込んだ
自己完結版(約10.4MB)を生成するスクリプト。アプリ本体ロジックは無改変で、
前段の埋め込みローダー + 既存の `window.__tessPaths` フックだけで完結する。

```
npm i --prefix /tmp/yomiage-build tesseract.js@6 @tesseract.js-data/jpn @tesseract.js-data/jpn_vert
node scripts/build-yomiage-ipad.mjs --modules /tmp/yomiage-build/node_modules --out /tmp/yomiage-ipad.html
```

技術メモ:
1. worker はコアJS(WASM内蔵版) + worker.min.js を連結した blob Worker
   (`TesseractCore` を事前定義すると worker 内の `importScripts` がスキップされる)
2. 言語データは worker が読む idb-keyval 互換キャッシュ
   (DB `keyval-store` / store `keyval` / キー `./<lang>.traineddata`)へ起動時に gz のまま注入
   (worker が自前解凍)
3. `{code,data}` 直渡しは tesseract.js 6.0.1 の `initialize` が言語名に `l.data` を使うバグがあり使えない

**GitHub Pages 配信ではこのビルドは不要**(CDNをそのまま読めるため `yomiage.html` が直接動く)。
CSP付き埋め込み配信をする場合にのみ使う。
