#!/usr/bin/env node
// git 歷史掃描（#98）：公開 repo 前，找出歷史中曾經寫入的 email、個人路徑與禁用名稱。唯讀，只輸出報告。
// 用法：
//   node tools/workflow/scan-history.mjs   在 repo 內執行，掃描所有 ref（分支、標籤、遠端分支等）可達的 commit
// 掃描每個 commit 新增的內容（git log -p 的 + 行），以及 author 與 committer（名稱與 email）。
// 規則與 check-sensitive.mjs 相同（匯入同一套規則，含本機的禁用名稱清單）。
// 輸出只有 commit、檔案與種類，不輸出命中的內容、email 或名稱。沒有命中時以 0 結束，有命中時以 1 結束，git 失敗時以 2 結束。
// 只執行 git log（加上 GIT_OPTIONAL_LOCKS=0），不改寫歷史、不修改工作區與 index。
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { loadDeniedNames, scanText } from './check-sensitive.mjs';

// 每個 commit 的開頭：\x01<hash>\0<author>\0<committer>（\x01 不會出現在 diff 的結構行開頭）
const COMMIT_MARK = '\x01';
const FORMAT = `${COMMIT_MARK}%H%x00%an <%ae>%x00%cn <%ce>`;

/** git log 的參數：所有 ref、只要差異、不用外部 diff 與 textconv、前綴固定為 a/ b/（不受使用者設定影響）。 */
export const LOG_ARGS = [
  '-c', 'core.quotePath=false',
  'log', '--all', '--no-color', '--no-ext-diff', '--no-textconv', '--src-prefix=a/', '--dst-prefix=b/',
  '--unified=0', '-p', `--format=${FORMAT}`,
];

const HUNK = /^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@/;
// 檔名命中時不輸出檔名
export const HIDDEN_FILE = '<檔名已隱藏>';

/** git 以 C 字串引號包住特殊檔名時去掉引號（只處理常見的跳脫）。 */
function unquotePath(path) {
  if (!path.startsWith('"') || !path.endsWith('"')) return path;
  return path.slice(1, -1).replace(/\\(.)/g, (_, c) => ({ t: '\t', n: '\n', '"': '"', '\\': '\\' })[c] ?? c);
}

/**
 * 解析 git log 的輸出（逐行），回傳命中的清單 [{ commit, file, kind, count }]，依 commit、檔案、種類合併。
 * file 是檔名、`(author)`、`(committer)`，或檔名本身命中時的 HIDDEN_FILE。
 */
export async function scanLog(lines, names) {
  const found = new Map();
  const add = (commit, file, kind) => {
    const key = `${commit}\0${file}\0${kind}`;
    const f = found.get(key);
    if (f) f.count += 1;
    else found.set(key, { commit, file, kind, count: 1 });
  };
  let commit = null;
  let file = null;
  let oldLeft = 0;
  let newLeft = 0;
  for await (const line of lines) {
    if (oldLeft > 0 || newLeft > 0) {
      // hunk 內：依 hunk 標頭的行數讀完，內容即使以 diff、+++ 開頭也不會被當成結構行
      if (line.startsWith('+')) {
        newLeft -= 1;
        for (const { kind } of scanText(line.slice(1), names)) add(commit, file, kind);
      } else if (line.startsWith('-')) {
        oldLeft -= 1;
      } else if (line.startsWith(' ')) {
        oldLeft -= 1;
        newLeft -= 1;
      }
      continue;
    }
    if (line.startsWith(COMMIT_MARK)) {
      const [hash, author, committer] = line.slice(1).split('\0');
      commit = hash;
      file = null;
      for (const [role, identity] of [['(author)', author], ['(committer)', committer]]) {
        for (const { kind } of scanText(identity, names)) add(commit, role, kind);
      }
    } else if (line.startsWith('diff --git ')) {
      file = null;
    } else if (line.startsWith('+++ ')) {
      const path = unquotePath(line.slice(4));
      const name = path.startsWith('b/') ? path.slice(2) : path;
      const hits = scanText(name, names);
      file = hits.length ? HIDDEN_FILE : name;
      for (const { kind } of hits) add(commit, file, `檔名：${kind}`);
    } else {
      const m = HUNK.exec(line);
      if (m) {
        oldLeft = m[1] === undefined ? 1 : Number(m[1]);
        newLeft = m[2] === undefined ? 1 : Number(m[2]);
      }
    }
  }
  return [...found.values()];
}

/** 掃描 root 的 git 歷史；git 失敗時丟出錯誤。names 省略時讀取本機的禁用名稱清單。 */
export async function scanHistory(root = '.', names = loadDeniedNames()) {
  const git = spawn('git', ['-C', root, ...LOG_ARGS], {
    env: { ...process.env, GIT_OPTIONAL_LOCKS: '0', GIT_PAGER: 'cat' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stderr = '';
  git.stderr.setEncoding('utf8').on('data', (d) => { stderr += d; });
  const exited = new Promise((resolve, reject) => {
    git.on('error', reject);
    git.on('close', resolve);
  });
  exited.catch(() => {}); // 下面 await 時才處理

  const findings = await scanLog(createInterface({ input: git.stdout, crlfDelay: Infinity }), names);
  const code = await exited;
  if (code !== 0) throw new Error(`git log 失敗（結束碼 ${code}）：${stderr.trim()}`);
  return findings;
}

/** 報告的一行：commit 前 12 碼、檔案、種類與行數；不含命中的內容。 */
export function formatFinding({ commit, file, kind, count }) {
  return `${commit.slice(0, 12)} ${file}：${kind}${count > 1 ? `（${count} 處）` : ''}`;
}

async function main(argv) {
  if (argv.length) {
    console.error('用法：node tools/workflow/scan-history.mjs（在 repo 內執行，不接受參數）');
    process.exitCode = 2;
    return;
  }
  let findings;
  try {
    findings = await scanHistory();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
    return;
  }
  if (!findings.length) {
    console.log('git 歷史中沒有 email、個人路徑或禁用名稱。');
    return;
  }
  const commits = new Set(findings.map((f) => f.commit)).size;
  console.error(`git 歷史中有 ${commits} 個 commit 命中 email、個人路徑或禁用名稱（只列位置，不列內容）：\n${findings.map((f) => `- ${formatFinding(f)}`).join('\n')}`);
  console.error('是否改寫歷史由人決定；本工具不修改任何東西。');
  process.exitCode = 1;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
