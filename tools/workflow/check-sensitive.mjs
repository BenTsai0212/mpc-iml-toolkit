#!/usr/bin/env node
// email 與個人路徑檢查（#49）：個人 email 與 /Users/<名稱>、/home/<名稱> 這類路徑，不論 repo 是否公開都不寫進檔案、PR 描述與留言。
// 用法：
//   node tools/workflow/check-sensitive.mjs               掃描已追蹤與未被 .gitignore 排除的未追蹤文字檔（#94）
//   node tools/workflow/check-sensitive.mjs --file <路徑>  只檢查一個檔案（例如送出 Issue 或留言前的自我檢查）
// 另外比對本機的禁用名稱清單（#96，見 DENIED_NAMES_PATH）。
// 輸出只有檔案、行號與種類（email／個人路徑／禁用名稱），不輸出命中的內容。通過時以 0 結束，有命中時以 1 結束。
// check-post-body.mjs 匯入同一套規則。
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// 放行的網域：RFC 2606 保留的網域，比對本身與子網域
const RESERVED_DOMAINS = ['example.com', 'example.org', 'example.net'];
// 放行的頂級網域：RFC 2606／6761 保留，加上文件說明格式時常用的 .tld（不是實際存在的頂級網域）
const RESERVED_TLDS = ['test', 'example', 'invalid', 'localhost', 'tld'];

const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g;

const underDomain = (domain, base) => domain === base || domain.endsWith(`.${base}`);

/**
 * 放行的 email：noreply@…、git@<主機>（SSH 的 clone 網址，例如 git@github.com:owner/repo.git，不是個人信箱）、
 * *.noreply.github.com、example.com／.org／.net 與其子網域、保留頂級網域。
 */
export function isAllowedEmail(address) {
  const at = address.lastIndexOf('@');
  const local = address.slice(0, at).toLowerCase();
  const domain = address.slice(at + 1).toLowerCase();
  if (local === 'noreply' || local === 'git') return true;
  if (underDomain(domain, 'noreply.github.com')) return true;
  if (RESERVED_DOMAINS.some((base) => underDomain(domain, base))) return true;
  return RESERVED_TLDS.includes(domain.slice(domain.lastIndexOf('.') + 1));
}

/** 找出一行中的 email；頂級網域不是英文字母的不算（例如套件版本 pkg@1.2.3）。 */
export function findEmails(line) {
  return [...String(line ?? '').matchAll(EMAIL)]
    .map((m) => m[0])
    .filter((address) => /^[A-Za-z]{2,}$/.test(address.slice(address.lastIndexOf('.') + 1)));
}

/**
 * 個人路徑：/Users/<名稱>、/home/<名稱>。
 * GitHub Actions 的 /home/runner 不算；`/Users/<名稱>` 這種角括號佔位不算（名稱只比對英數字、`.`、`_`、`-`）。
 */
export const PERSONAL_PATH = /\/(?:Users\/|home\/(?!runner(?![\w.-])))[\w.-]+/;

// 禁用名稱清單（#96）：專案名、合作者名等不寫進檔案、PR 描述與留言的名稱。清單本身不進版本控制（.gitignore）。
export const DENIED_NAMES_PATH = 'tools/workflow/denied-names.local.txt';
// 測試用：指定其他清單檔
export const DENIED_NAMES_ENV = 'WORKFLOW_DENIED_NAMES_FILE';

/** 解析清單：一行一個，前後空白不算；空行與 # 開頭的行略過。 */
export function parseDeniedNames(text) {
  return String(text ?? '').split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith('#'));
}

/**
 * 清單檔的路徑：有 WORKFLOW_DENIED_NAMES_FILE 時用它；否則是主要工作目錄的 DENIED_NAMES_PATH。
 * runner 在另一個 git worktree 執行，不進版本控制的檔案只在主要工作目錄，所以由 git common dir 找主要工作目錄。
 */
export function deniedNamesFile(env = process.env) {
  if (env[DENIED_NAMES_ENV]) return env[DENIED_NAMES_ENV];
  const here = dirname(fileURLToPath(import.meta.url));
  let root = resolve(here, '..', '..');
  try {
    const common = execFileSync('git', ['-C', here, 'rev-parse', '--path-format=absolute', '--git-common-dir'], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
    if (common.endsWith('/.git')) root = dirname(common);
  } catch {
    // 不在 git repo 中：用本檔所在的 repo
  }
  return join(root, DENIED_NAMES_PATH);
}

/** 讀取禁用名稱；清單檔不存在時回傳空陣列。 */
export function loadDeniedNames(file = deniedNamesFile()) {
  return parseDeniedNames(readText(file));
}

let deniedNamesCache;
const defaultDeniedNames = () => (deniedNamesCache ??= loadDeniedNames());

/** 不分大小寫的子字串比對。 */
export function hasDeniedName(line, names) {
  const lower = String(line ?? '').toLowerCase();
  return names.some((name) => lower.includes(name.toLowerCase()));
}

/**
 * 逐行檢查一段文字（含程式碼區塊）。回傳 [{ line: 行號（從 1 起算）, kind: 'email' | '個人路徑' | '禁用名稱' }]。
 * names 省略時讀取本機的禁用名稱清單。
 */
export function scanText(text, names = defaultDeniedNames()) {
  const findings = [];
  String(text ?? '').split(/\r?\n/).forEach((content, i) => {
    if (findEmails(content).some((address) => !isAllowedEmail(address))) findings.push({ line: i + 1, kind: 'email' });
    if (PERSONAL_PATH.test(content)) findings.push({ line: i + 1, kind: '個人路徑' });
    if (hasDeniedName(content, names)) findings.push({ line: i + 1, kind: '禁用名稱' });
  });
  return findings;
}

/** 讀取文字檔；不存在、是資料夾或含 NUL（二進位檔）時回傳 null。 */
export function readText(path) {
  let buffer;
  try {
    buffer = readFileSync(path);
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'EISDIR') return null;
    throw error;
  }
  return buffer.includes(0) ? null : buffer.toString('utf8');
}

const gitFiles = (root, args) =>
  execFileSync('git', ['-C', root, 'ls-files', '-z', ...args], { encoding: 'utf8' }).split('\0').filter(Boolean);

export function trackedFiles(root) {
  return gitFiles(root, []);
}

/** 尚未 git add、且沒被 .gitignore 排除的新檔案（#94）。 */
export function untrackedFiles(root) {
  return gitFiles(root, ['--others', '--exclude-standard']);
}

/** 預設掃描的範圍：已追蹤的檔案加上未追蹤的新檔案。 */
export function repoFiles(root) {
  return [...trackedFiles(root), ...untrackedFiles(root)];
}

/** 檢查多個檔案；回傳「檔案:行號：種類」的清單，不含命中的內容。 */
export function checkFiles(files, root = '.') {
  const findings = [];
  for (const file of files) {
    const text = readText(resolve(root, file));
    if (text === null) continue;
    for (const f of scanText(text)) findings.push(`${file}:${f.line}：${f.kind}`);
  }
  return findings;
}

function main(argv) {
  const i = argv.indexOf('--file');
  let findings;
  if (i >= 0) {
    const file = argv[i + 1];
    if (!file) {
      console.error('用法：node tools/workflow/check-sensitive.mjs [--file <路徑>]');
      process.exitCode = 2;
      return;
    }
    if (readText(file) === null) {
      console.error(`無法讀取文字檔：${file}`);
      process.exitCode = 2;
      return;
    }
    findings = checkFiles([file]);
  } else {
    const root = execFileSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
    findings = checkFiles(repoFiles(root), root);
  }
  if (!findings.length) {
    console.log('沒有 email、個人路徑或禁用名稱。');
    return;
  }
  console.error(`找到 ${findings.length} 處 email、個人路徑或禁用名稱（只列位置，不列內容）：\n${findings.map((f) => `- ${f}`).join('\n')}`);
  console.error('改用 user@example.com、/Users/<名稱>/…、<名稱> 這類佔位寫法。');
  process.exitCode = 1;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
