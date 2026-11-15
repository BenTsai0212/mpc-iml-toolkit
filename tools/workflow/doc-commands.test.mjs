import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// 文件中的 shell 指令區塊不加 # 註解：macOS 的 zsh 預設不把互動輸入的 # 當註解，照著複製會出錯（#43）
const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const SHELL_LANGS = new Set(['bash', 'sh', 'zsh', 'shell']);

// 一行中是否有 # 註解：行首或空白後、不在引號內的 #；#! 開頭的行不算
function hasComment(line) {
  if (/^\s*#!/.test(line)) return false;
  let quote = null;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quote) {
      if (c === '\\' && quote === '"') i++;
      else if (c === quote) quote = null;
    } else if (c === '\\') {
      i++;
    } else if (c === "'" || c === '"') {
      quote = c;
    } else if (c === '#' && (i === 0 || /\s/.test(line[i - 1]))) {
      return true;
    }
  }
  return false;
}

// 回傳 shell 區塊中符合 match 的行，格式為「行號: 內容」
function shellLines(text, match) {
  const found = [];
  let fence = null;
  let lang = null;
  text.split('\n').forEach((line, i) => {
    const m = line.match(/^\s*(`{3,}|~{3,})\s*([^\s`]*)/);
    if (!fence && m) {
      fence = m[1];
      lang = m[2].toLowerCase();
      return;
    }
    if (fence && m && m[1][0] === fence[0] && m[1].length >= fence.length && line.trim() === m[1]) {
      fence = null;
      return;
    }
    if (fence && SHELL_LANGS.has(lang) && match(line)) found.push(`${i + 1}: ${line.trim()}`);
  });
  return found;
}

// 回傳 shell 區塊中含 # 註解的行
export function shellComments(text) {
  return shellLines(text, hasComment);
}

// 回傳 shell 區塊中含 $(...)、shell 變數或 diff -（讀標準輸入）的行：
// Claude Code 的權限檢查拒絕前兩者，sandbox 下 diff - 讀不到標準輸入（#77）
export function shellExpansions(text) {
  return shellLines(text, (line) => /\$[({A-Za-z_]|\bdiff\s+(.*\s)?-(\s|$)/.test(line));
}

test('找出行尾與整行的註解', () => {
  const text = ['```bash', 'npm test   # 註解', '# 整行', '  # 縮排的整行', 'npm run build', '```'].join('\n');
  assert.deepEqual(shellComments(text), ['2: npm test   # 註解', '3: # 整行', '4: # 縮排的整行']);
});

test('檢查 bash、sh、zsh、shell 區塊，含清單內縮排的區塊與 ~~~', () => {
  for (const lang of ['bash', 'sh', 'zsh', 'shell']) {
    assert.deepEqual(shellComments(['```' + lang, 'ls # x', '```'].join('\n')), ['2: ls # x']);
  }
  assert.deepEqual(shellComments(['- 步驟', '', '  ```bash', '  ls # x', '  ```'].join('\n')), ['4: ls # x']);
  assert.deepEqual(shellComments(['~~~sh', 'ls # x', '~~~'].join('\n')), ['2: ls # x']);
});

test('#!、引號內與網址中的 # 不算', () => {
  const text = [
    '```bash',
    '#!/usr/bin/env bash',
    "gh issue view N --jq '.a #b'",
    'echo "a # b" \'c # d\'',
    'curl https://example.com/page#section',
    'echo ${#arr[@]} a#b',
    '```',
  ].join('\n');
  assert.deepEqual(shellComments(text), []);
});

test('不檢查區塊外的文字與其他語言的區塊', () => {
  const text = [
    '# 標題',
    '```json',
    '{ "a": 1 } # x',
    '```',
    '```',
    'ls # 未標語言',
    '```',
    '```markdown',
    '## 計畫（#1）',
    '```',
    '```bash',
    'ls',
    '```',
  ].join('\n');
  assert.deepEqual(shellComments(text), []);
});

test('repo 內 Markdown 的 shell 指令區塊沒有 # 註解', () => {
  const files = execFileSync('git', ['ls-files', '*.md'], { cwd: ROOT, encoding: 'utf8' })
    .split('\n')
    .filter(Boolean);
  const problems = files.flatMap((file) =>
    shellComments(readFileSync(`${ROOT}${file}`, 'utf8')).map((line) => `${file}:${line}`),
  );
  assert.deepEqual(problems, [], '說明請寫在程式碼區塊外');
});

test('找出 $(...)、shell 變數與 diff -', () => {
  const text = [
    '```bash',
    'git ls-tree -r "$(git rev-list HEAD)"',
    'ls "$TMPDIR/a"',
    'echo ${HOME}',
    'sed s/a/b/ f | diff - g',
    'diff -u a b',
    "gh api x --jq '\\(.sha) \\(.path)' > <dir>/a.txt",
    'diff <dir>/a.txt <dir>/b.txt',
    '```',
  ].join('\n');
  assert.deepEqual(shellExpansions(text), [
    '2: git ls-tree -r "$(git rev-list HEAD)"',
    '3: ls "$TMPDIR/a"',
    '4: echo ${HOME}',
    '5: sed s/a/b/ f | diff - g',
  ]);
});

test('upgrade.md 的 shell 指令不含 $(...)、shell 變數與 diff -', () => {
  assert.deepEqual(shellExpansions(readFileSync(`${ROOT}docs/workflow/upgrade.md`, 'utf8')), []);
});
