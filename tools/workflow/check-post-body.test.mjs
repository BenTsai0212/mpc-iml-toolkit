import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkContent, checkPostBody, checkSensitiveContent, checkSource, KINDS } from './check-post-body.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCRIPT = join(HERE, 'check-post-body.mjs');
const ok = (body, issue, kind) => assert.deepEqual(checkContent(body, { issue, kind }), [], `應通過：${body}`);
const ng = (body, issue, kind) => assert.notDeepEqual(checkContent(body, { issue, kind }), [], `應拒絕：${body}`);

test('checkContent：PR 描述要有 Closes／Refs 本 Issue', () => {
  ok('## 為什麼\n\nCloses #104\n', 104, 'pr');
  ok('Refs #104', 104, 'pr');
  ng('Closes #999', 104, 'pr');
  ng('Closes #1040', 104, 'pr');
  ng('見 #104', 104, 'pr');
  ng('`Closes #104`', 104, 'pr');
  ng('<!-- Closes #104 -->', 104, 'pr');
  assert.match(checkContent('Closes #999', { issue: 104, kind: 'pr' })[0], /#999/);
});

test('checkContent：留言的開頭標題與 Issue 編號', () => {
  ok('## 計畫（#104）\n\n內容', 104, 'plan');
  ok('\n## agent 停止：測試失敗\n\n- Issue：#104', 104, 'stop');
  ok('## 修正回報（#104）\n\n- ✅ 已完成', 104, 'fix');
  ok('## 合併後待辦（#104）\n\n- [ ] 確認', 104, 'todo');
  ng('## 計畫\n\n內容', 104, 'plan');
  ng('## 計畫（#1041）', 104, 'plan');
  ng('計畫（#104）', 104, 'plan');
  ng('## agent 停止（#104）', 104, 'plan');
  ng('## 計畫 `#104`', 104, 'plan');
  ng('', 104, 'stop');
});

test('checkSource：runner 執行時檔案必須在 RUNNER_RUN_TMP 底下、不是舊檔，不接受標準輸入', () => {
  const runTmp = join(tmpdir(), 'repo', '.runner-tmp', '20261102-104');
  const started = Date.parse('2026-11-02T10:00:00Z');
  const base = { runTmp, startedMs: started, mtimeMs: started + 5e3, nowMs: started + 10e3 };
  assert.deepEqual(checkSource({ ...base, file: join(runTmp, 'pr.md') }), []);
  assert.deepEqual(checkSource({ ...base, file: join(runTmp, 'sub', 'pr.md') }), []);
  assert.equal(checkSource({ ...base, file: join(tmpdir(), 'pr.md') }).length, 1);
  assert.equal(checkSource({ ...base, file: join(runTmp, '..', 'pr.md') }).length, 1);
  assert.equal(checkSource({ ...base, file: `${runTmp}-x/pr.md` }).length, 1);
  assert.equal(checkSource({ ...base, file: join(runTmp, 'pr.md'), mtimeMs: started - 60e3 }).length, 1);
  assert.equal(checkSource({ ...base, file: '-' }).length, 1);
});

test('checkSource：手動執行（沒有 RUNNER_RUN_TMP）時不檢查來源、位置與修改時間', () => {
  const now = Date.parse('2026-11-02T10:00:00Z');
  assert.deepEqual(checkSource({ file: '-', runTmp: null, startedMs: NaN }), []);
  assert.deepEqual(checkSource({ file: '/tmp/a.md', runTmp: null, startedMs: NaN, mtimeMs: now - 86400e3 }), []);
});

test('checkSource：runner 執行時缺少 RUNNER_RUN_STARTED 不通過', () => {
  assert.equal(checkSource({ file: '/w/t/a.md', runTmp: '/w/t', startedMs: NaN, mtimeMs: 0 }).length, 1);
});

test('checkPostBody：參數錯誤時列出原因', () => {
  const r = checkPostBody(['--kind', 'x'], {});
  assert.equal(r.ok, false);
  assert.equal(r.errors.length, 3);
  assert.deepEqual(KINDS, ['pr', 'plan', 'stop', 'fix', 'todo', 'decision', 'change-request']);
});

// 重現 #39：另一個專案在共用的暫存資料夾留下同名檔案，本次的寫入失敗，agent 沿用了舊檔
test('重現：其他專案留下的同名暫存檔不會通過檢查', (t) => {
  const root = mkdtempSync(join(tmpdir(), 'check-post-body-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const shared = join(root, 'shared-tmp');
  const runTmp = join(root, 'worktree', '.runner-tmp', '20261102T100000-104');
  mkdirSync(shared, { recursive: true });
  mkdirSync(runTmp, { recursive: true });
  const started = new Date(Date.now() - 60e3);
  const old = new Date(started.getTime() - 3600e3);
  const env = { RUNNER_RUN_TMP: runTmp, RUNNER_RUN_STARTED: started.toISOString() };
  const run = (args, e = env, input) =>
    spawnSync(process.execPath, [SCRIPT, ...args], { env: { PATH: process.env.PATH, ...e }, encoding: 'utf8', input });

  // 其他專案的檔案：別的 Issue 編號，修改時間較早
  const other = join(shared, 'body.md');
  writeFileSync(other, '## 為什麼\n\n其他專案的內容\n\nCloses #999\n');
  utimesSync(other, old, old);
  let r = run(['--issue', '104', '--kind', 'pr', other]);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /不要貼出/);
  assert.match(r.stderr, /RUNNER_RUN_TMP/);

  // 內容剛好正確的舊檔也拒絕
  const lookalike = join(shared, 'plan.md');
  writeFileSync(lookalike, '## 計畫（#104）\n\n舊的內容\n');
  utimesSync(lookalike, old, old);
  assert.equal(run(['--issue', '104', '--kind', 'plan', lookalike]).status, 1);

  // 同名檔被複製進本次的資料夾但修改時間較早，仍拒絕
  const copied = join(runTmp, 'body.md');
  writeFileSync(copied, '## 為什麼\n\nCloses #104\n');
  utimesSync(copied, old, old);
  r = run(['--issue', '104', '--kind', 'pr', copied]);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /舊檔/);

  // runner 執行時不接受標準輸入
  assert.equal(run(['--issue', '104', '--kind', 'pr', '-'], env, 'Closes #104\n').status, 1);

  // 本次寫入 RUNNER_RUN_TMP 的新檔通過；通過的檔案就是 gh --body-file 要貼出的同一個路徑
  const fresh = join(runTmp, 'pr-104.md');
  const content = '## 為什麼\n\n本次的內容\n\nCloses #104\n';
  writeFileSync(fresh, content);
  r = run(['--issue', '104', '--kind', 'pr', fresh]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(readFileSync(fresh, 'utf8'), content);

  // 手動執行（沒有 RUNNER_RUN_TMP）：只檢查內容；其他 Issue 的內容仍拒絕
  assert.equal(run(['--issue', '104', '--kind', 'pr', '-'], {}, 'Closes #104\n').status, 0);
  assert.equal(run(['--issue', '104', '--kind', 'pr', other], {}).status, 1);
  assert.equal(run(['--issue', '999', '--kind', 'pr', other], {}).status, 0);
});

// 流程說明：agent-workflow.md 中每個 gh … --body-file <路徑>，前面都有以同一個路徑執行的 check-post-body.mjs
test('agent-workflow.md：貼出的檔案就是檢查通過的檔案', () => {
  const doc = readFileSync(join(HERE, '..', '..', 'docs', 'workflow', 'agent-workflow.md'), 'utf8');
  const blocks = [...doc.matchAll(/```bash\n([\s\S]*?)```/g)].map((m) => m[1].split('\n').map((l) => l.trim()));
  let posts = 0;
  for (const lines of blocks) {
    lines.forEach((line, i) => {
      const m = /^gh (?:pr create|pr edit|pr comment|issue comment)\b.*--body-file (\S+)/.exec(line);
      if (!m) return;
      posts++;
      assert.notEqual(m[1], '-', `不用標準輸入：${line}`);
      const checks = lines.slice(0, i).filter((l) => l.startsWith('node tools/workflow/check-post-body.mjs '));
      assert.ok(checks.some((l) => l.endsWith(` ${m[1]}`)), `貼出前沒有檢查同一個檔案：${line}`);
    });
  }
  assert.ok(posts >= 4, `應至少有 PR 描述、修正模式的 PR 描述更新、人工待辦與停止回報四處貼出（找到 ${posts}）`);
  assert.match(doc, /寫入失敗時不執行 `gh`/);
});

// ---- email 與個人路徑（#49）----
// 本檔也在 repo 掃描範圍內：會命中的範例以片段組成
const email = `alice${'@'}mail.co`;
const userPath = `/${'Users'}/alice/repo`;

test('checkSensitiveContent：逐行回報 email 與個人路徑，程式碼區塊也檢查，只輸出行號與種類', () => {
  const body = ['Closes #49', '', `聯絡 ${email}`, '```', `cd ${userPath}`, '```', `\`${email}\``].join('\n');
  const errors = checkSensitiveContent(body);
  assert.deepEqual(errors, ['第 3 行：email', '第 5 行：個人路徑', '第 7 行：email']);
  assert.ok(errors.every((e) => !e.includes('alice')));
  assert.deepEqual(checkSensitiveContent('Closes #49\n/Users/<名稱>/repo、user@example.com、/home/runner/work'), []);
});

test('指令：email 或個人路徑命中時不通過，輸出不含命中的文字並提示佔位寫法', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'check-post-body-sensitive-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const file = join(dir, 'pr.md');
  writeFileSync(file, `## 為什麼\n\nCloses #49\n\n路徑 ${userPath}\n`);
  const r = spawnSync(process.execPath, [SCRIPT, '--issue', '49', '--kind', 'pr', file], {
    env: { PATH: process.env.PATH }, encoding: 'utf8',
  });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /第 5 行：個人路徑/);
  assert.match(r.stderr, /佔位/);
  assert.doesNotMatch(r.stdout + r.stderr, /alice/);
  assert.equal(checkPostBody(['--issue', '49', '--kind', 'pr', file], {}).ok, false);
});

// 禁用名稱（#96）：虛構的佔位名稱，只用暫存清單檔
test('禁用名稱：命中時不通過，輸出不含名稱與該行內容；清單檔不存在時略過', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'check-post-body-names-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  assert.deepEqual(checkSensitiveContent('Closes #96\n\n感謝 ZORBLAX 團隊', ['Zorblax']), ['第 3 行：禁用名稱']);
  const list = join(dir, 'names.txt');
  writeFileSync(list, '# 測試用\nZorblax\n');
  const file = join(dir, 'pr.md');
  writeFileSync(file, '## 為什麼\n\nCloses #96\n\n感謝 zorblax 團隊\n');
  const run = (namesFile) => spawnSync(process.execPath, [SCRIPT, '--issue', '96', '--kind', 'pr', file], {
    env: { PATH: process.env.PATH, WORKFLOW_DENIED_NAMES_FILE: namesFile }, encoding: 'utf8',
  });
  let r = run(list);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /第 5 行：禁用名稱/);
  assert.match(r.stderr, /佔位/);
  assert.doesNotMatch(r.stdout + r.stderr, /zorblax|團隊/i);
  r = run(join(dir, 'missing.txt'));
  assert.equal(r.status, 0, r.stderr);
});

// ---- 決策中心的貼文（#53）----

test('checkContent decision：開頭必須是 ## 決定，可接括號說明', () => {
  ok('## 決定\n\n- 採用選項 1', 53, 'decision');
  ok('## 決定（補充）\n\n- 另外…', 53, 'decision');
  ok('## 決定 (修改)\n\n- 改為…', 53, 'decision');
  ok('\n## 決定\n- 不必提到 Issue 編號', 53, 'decision');
  ng('## 補充決定\n\n- 另外…', 53, 'decision');
  ng('## 決定補充\n\n- 另外…', 53, 'decision');
  ng('## 決定：選項 1', 53, 'decision');
  ng('決定\n\n- 選項 1', 53, 'decision');
  ng('### 決定', 53, 'decision');
  ng('', 53, 'decision');
  assert.match(checkContent('## 補充決定', { issue: 53, kind: 'decision' })[0], /## 決定（補充）/);
});

test('checkContent change-request：開頭是 ## 修正要求，且至少一個未勾選的核取方塊', () => {
  ok('## 修正要求\n\n- [ ] 改 A\n- [x] 已完成的 B', 53, 'change-request');
  ok('## 修正要求（第二輪）\n\n* [ ] 改 A', 53, 'change-request');
  ng('## 修正要求\n\n- 改 A', 53, 'change-request');
  ng('## 修正要求\n\n- [x] 改 A', 53, 'change-request');
  ng('## 修正要求\n\n```\n- [ ] 範例\n```', 53, 'change-request');
  ng('請修正：\n\n- [ ] 改 A', 53, 'change-request');
  assert.equal(checkContent('改 A', { issue: 53, kind: 'change-request' }).length, 2);
});

test('指令 decision／change-request：套用 email 與個人路徑檢查；手動執行時不檢查檔案位置與時間', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'check-post-body-dc-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const old = new Date(Date.now() - 86400e3);
  const write = (name, body) => {
    const f = join(dir, name);
    writeFileSync(f, body);
    utimesSync(f, old, old);
    return f;
  };
  const run = (kind, file) => checkPostBody(['--issue', '53', '--kind', kind, file], {});
  assert.equal(run('decision', write('d.md', '## 決定（補充）\n\n- 選項 2\n')).ok, true);
  assert.equal(run('change-request', write('c.md', '## 修正要求\n\n- [ ] 改 A\n')).ok, true);
  const leak = run('decision', write('d2.md', `## 決定\n\n- 路徑 /${'Users'}/alice/x\n`));
  assert.equal(leak.ok, false);
  assert.deepEqual(leak.errors, ['第 3 行：個人路徑']);
  assert.equal(run('change-request', write('c2.md', `## 修正要求\n\n- [ ] 寄給 alice${'@'}mail.co\n`)).ok, false);
});
