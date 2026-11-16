import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  afterHeading, allHeadings, DEFAULT_LANG, heading, headingLang, headingLineRe, HEADINGS, LANGS, processLang, startsWithAny, startsWithHeading,
} from './headings.mjs';

const DOC = fileURLToPath(new URL('../../docs/workflow/headings.md', import.meta.url));

test('對照表：文件的表格與 headings.mjs 一致（單一正本）', () => {
  const rows = readFileSync(DOC, 'utf8').split('\n')
    .map((l) => /^\| `(\w+)` \| `([^`]+)` \| `([^`]+)` \|/.exec(l))
    .filter(Boolean)
    .map(([, key, zh, en]) => [key, { 'zh-TW': zh, en }]);
  assert.deepEqual(Object.fromEntries(rows), JSON.parse(JSON.stringify(HEADINGS)));
});

test('對照表：每個標題兩種語言都有，且同一語言中不會被另一個標題當成開頭', () => {
  assert.deepEqual(LANGS, ['zh-TW', 'en']);
  assert.equal(DEFAULT_LANG, 'zh-TW');
  for (const lang of LANGS) {
    const hs = Object.values(HEADINGS).map((h) => h[lang]);
    for (const h of hs) assert.match(h, /^## \S/);
    for (const a of hs) for (const b of hs) if (a !== b) assert.ok(!startsWithHeading(b, a), `${b} 不應算 ${a}`);
  }
});

test('startsWithHeading：英文標題後面不能接英文字母、數字或連字號；中文沿用 startsWith', () => {
  assert.ok(startsWithHeading('## Decision\n- x', '## Decision'));
  assert.ok(startsWithHeading('  \n## Decision (addendum)', '## Decision'));
  assert.ok(startsWithHeading('## Decision（補充）', '## Decision'));
  assert.ok(startsWithHeading('## Agent stopped: tests fail', '## Agent stopped'));
  assert.ok(!startsWithHeading('## Decisions needed', '## Decision'));
  assert.ok(!startsWithHeading('## Decision-making', '## Decision'));
  assert.ok(!startsWithHeading('ok. ## Decision', '## Decision'));
  assert.ok(startsWithHeading('## 決定事項', '## 決定'), '中文的行為不變');
});

test('headingLang／startsWithAny：中英文都認得', () => {
  assert.equal(headingLang('## 計畫（#1）', 'plan'), 'zh-TW');
  assert.equal(headingLang('## Plan (#1)', 'plan'), 'en');
  assert.equal(headingLang('## Planning', 'plan'), null);
  assert.ok(startsWithAny('## Change request\n- [ ] a', 'changeRequest'));
  assert.ok(!startsWithAny('## Fix report', 'changeRequest'));
  assert.deepEqual(allHeadings('decision'), ['## 決定', '## Decision']);
  assert.equal(heading('decision', 'en'), '## Decision');
  assert.equal(heading('decision', 'xx'), '## 決定', '不認得的語言用預設');
});

test('headingLineRe：第一行正好是標題，可接括號說明', () => {
  const any = headingLineRe('decision');
  for (const l of ['## 決定', '## 決定（補充）', '## Decision', '## Decision (addendum)', '## Decision（補充）']) assert.ok(any.test(l), l);
  for (const l of ['## 決定補充', '## 補充決定', '## Decisions', '## Decision addendum']) assert.ok(!any.test(l), l);
  assert.ok(!headingLineRe('decision', 'en').test('## 決定'));
  assert.ok(!headingLineRe('decision', 'zh-TW').test('## Decision'));
});

test('afterHeading：取出標題後的文字', () => {
  assert.equal(afterHeading('## agent 停止：測試失敗', 'stop'), '測試失敗');
  assert.equal(afterHeading('## Agent stopped: tests fail', 'stop'), 'tests fail');
  assert.equal(afterHeading('## Agent stopped', 'stop'), '');
});

test('processLang：讀 AGENTS.md 第 0 節的流程語言，沒有時是 zh-TW', () => {
  assert.deepEqual(processLang('# AGENTS\n## 0. 專案設定\n- 決定者：@x\n'), { lang: 'zh-TW', error: null });
  assert.deepEqual(processLang('- 流程語言：en\n'), { lang: 'en', error: null });
  assert.deepEqual(processLang('- 流程語言: `zh-TW`（預設）\n'), { lang: 'zh-TW', error: null });
  const bad = processLang('- 流程語言：fr\n');
  assert.equal(bad.lang, 'zh-TW');
  assert.match(bad.error, /fr/);
  const real = readFileSync(new URL('../../AGENTS.md', import.meta.url), 'utf8');
  assert.equal(processLang(real).error, null, '本 repo 的 AGENTS.md 可以讀出流程語言');
});
