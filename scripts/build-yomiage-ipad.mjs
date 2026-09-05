#!/usr/bin/env node
// yomiage.html の「クラウド表示版(claude.ai Artifact用)」を生成するスクリプト。
//
// Artifact は CSP で外部ホストへの通信が遮断されるため、通常版が初回に CDN から
// 取得する OCR 一式(Tesseract.js 本体・worker・WASM コア・日本語認識データ)を
// すべて HTML に埋め込み、1ファイルで完結させる(出力 約11MB・Artifact上限16MB内)。
// アプリ本体のロジックは無改変。前段に埋め込みローダーを差し込むだけ:
//  - worker: コアJS(WASM内蔵版)+worker.min.js を連結した blob Worker
//    (TesseractCore を事前定義すると worker 内の importScripts が丸ごとスキップされる)
//  - 言語データ: worker が読む IndexedDB キャッシュ(idb-keyval 標準ストア
//    keyval-store/keyval・キー ./<lang>.traineddata)へ起動時に gz のまま注入し、
//    createWorker は注入完了を待ってから実行(fetch 自体が発生しない)
//    ※ {code, data} 直渡しは tesseract.js 6.0.1 の initialize が言語名に l.data を
//      使ってしまうバグ(Init -1)があるため使えない
//  - 受け口はアプリ既存の window.__tessPaths フック(workerBlobURL:false)
//
// 使い方:
//   npm i --prefix /tmp/yomiage-build tesseract.js@6 @tesseract.js-data/jpn @tesseract.js-data/jpn_vert
//   node scripts/build-yomiage-ipad.mjs --modules /tmp/yomiage-build/node_modules --out /tmp/yomiage-ipad.html
//
// 出力ファイルは巨大なためリポジトリにはコミットしない(claude.ai の Artifact として配信)。

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
function argOf(name, dflt) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : dflt;
}
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const srcPath = argOf("--src", join(repoRoot, "yomiage.html"));
const modules = argOf("--modules", null);
const outPath = argOf("--out", "yomiage-ipad.html");
if (!modules) { console.error("--modules <node_modulesのパス> を指定してください"); process.exit(1); }

const b64 = (p) => readFileSync(p).toString("base64");
const workerB64 = b64(join(modules, "tesseract.js/dist/worker.min.js"));
const coreB64 = b64(join(modules, "tesseract.js-core/tesseract-core-simd-lstm.wasm.js"));
const jpnB64 = b64(join(modules, "@tesseract.js-data/jpn/4.0.0_best_int/jpn.traineddata.gz"));
const vertB64 = b64(join(modules, "@tesseract.js-data/jpn_vert/4.0.0_best_int/jpn_vert.traineddata.gz"));
const tessMin = readFileSync(join(modules, "tesseract.js/dist/tesseract.min.js"), "utf8");

let html = readFileSync(srcPath, "utf8");

// 文字列パッチ(見つからなければビルド失敗にして、本体改修時の追従漏れを検知する)
function patch(oldStr, newStr) {
  if (!html.includes(oldStr)) { console.error("パッチ対象が見つかりません:\n" + oldStr); process.exit(1); }
  html = html.replace(oldStr, newStr);
}

// 文言をクラウド表示版向けに調整
patch(
  "保存すると自動で文字を読み取り、音声で音読できます。<br>画像もテキストもこの端末の中だけに保存されます。",
  "保存すると自動で文字を読み取り、音声で音読できます。<br>画像もテキストも端末内でのみ処理・保存されます。<br>※このクラウド表示版は端末やアプリの都合で保存が消えることがあります。大事な文はコピーして控えてください。"
);
patch(
  "（初回のみ読み取りプログラムと日本語データ計約4MBを取得・2回目以降は端末内キャッシュ）",
  "（読み取りに必要なプログラムと日本語データはこのページに内蔵済み・外部取得なし）"
);
patch(
  "文字読み取りも端末内で実行されます（読み取りプログラム本体のみ初回にCDNから取得）。",
  "文字読み取りも端末内で実行されます（必要なプログラムはこのページに内蔵・外部取得なし）。"
);
patch(
  "端末やブラウザのデータ消去で保存内容は消えるため、大切な内容はテキストをコピーして控えてください。",
  "このクラウド表示版（claude.aiのArtifact）では、端末やアプリの都合で保存内容が消えることがあります。読み上げ用の一時利用と考え、大切な内容はテキストをコピーして控えてください。"
);

// 埋め込みローダーをアプリ本体スクリプトの直前に挿入
const prelude = `<script>
${tessMin}
</script>
<script>
"use strict";
// ===== クラウド表示版 埋め込みローダー(build-yomiage-ipad.mjs が生成) =====
(function(){
  const WORKER_B64 = "${workerB64}";
  const CORE_B64 = "${coreB64}";
  const LANG_B64 = { jpn: "${jpnB64}", jpn_vert: "${vertB64}" };
  function b64ToBytes(b){ const s = atob(b); const u = new Uint8Array(s.length); for(let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return u; }
  // コアJS(WASM内蔵)+worker.min.js を連結した blob Worker。TesseractCore が
  // 事前定義されるため worker 内の importScripts(コアCDN取得)はスキップされる
  const workerUrl = URL.createObjectURL(new Blob([b64ToBytes(CORE_B64), "\\n;\\n", b64ToBytes(WORKER_B64)], { type: "application/javascript" }));
  window.__tessPaths = { workerPath: workerUrl, workerBlobURL: false, corePath: "embedded" };
  // 言語データ: worker が参照する idb-keyval 互換キャッシュへ gz のまま注入
  // (worker 側は gzip マジックナンバーを見て自前で解凍するため gz のままで良い)
  function seedCache(key, bytes){
    return new Promise((res, rej) => {
      const r = indexedDB.open("keyval-store");
      r.onupgradeneeded = () => { r.result.createObjectStore("keyval"); };
      r.onsuccess = () => {
        const db = r.result;
        const tx = db.transaction("keyval", "readwrite");
        tx.objectStore("keyval").put(bytes, key);
        tx.oncomplete = () => { db.close(); res(); };
        tx.onerror = () => { db.close(); rej(tx.error); };
      };
      r.onerror = () => rej(r.error);
    });
  }
  const seeded = Promise.all(
    Object.keys(LANG_B64).map(c => seedCache("./" + c + ".traineddata", b64ToBytes(LANG_B64[c])))
  ).catch(e => { console.warn("言語データのキャッシュ注入に失敗:", e); });
  const orig = Tesseract.createWorker;
  Tesseract.createWorker = async function(langs, oem, opts, cfg){
    await seeded;
    return orig(langs, oem, opts, cfg);
  };
})();
</script>
`;
patch('<script>\n"use strict";', prelude + '<script>\n"use strict";');

writeFileSync(outPath, html);
console.log("生成完了: " + outPath + " (" + (Buffer.byteLength(html) / 1024 / 1024).toFixed(1) + " MB)");
