import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DENIED_NAMES_ENV } from './check-sensitive.mjs';
import { formatFinding, HIDDEN_FILE, scanHistory, scanLog } from './scan-history.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCRIPT = join(HERE, 'scan-history.mjs');

// 本檔也在 check-sensitive 的掃描範圍內：會命中的範例以片段組成，不以完整字串出現在檔案中
const at = (local, domain) => `${local}@${domain}`;
const users = (name) => `/${'Users'}/${name}`;
const OK_ID = { name: 'Tester', email: 'tester@example.com' };

/** 暫存 git repo（虛構資料）；commit 時以環境變數指定 author 與 committer。 */
function tempRepo(t) {
  const dir = mkdtempSync(join(tmpdir(), 'scan-history-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const git = (args, env = {}) => execFileSync('git', ['-C', dir, '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false', ...args], {
    encoding: 'utf8', env: { ...process.env, ...env },
  }).trim();
  const commit = (message, { author = OK_ID, committer = OK_ID } = {}) => {
    git(['add', '-A']);
    git(['commit', '-q', '--allow-empty', '-m', message], {
      GIT_AUTHOR_NAME: author.name, GIT_AUTHOR_EMAIL: author.email,
      GIT_COMMITTER_NAME: committer.name, GIT_COMMITTER_EMAIL: committer.email,
    });
    return git(['rev-parse', 'HEAD']);
  };
  git(['init', '-q', '-b', 'main']);
  return { dir, git, commit, write: (file, text) => writeFileSync(join(dir, file), text) };
}

const run = (cwd, namesFile) => spawnSync(process.execPath, [SCRIPT], {
  cwd, encoding: 'utf8', env: { PATH: process.env.PATH, [DENIED_NAMES_ENV]: namesFile },
});

test('歷史中已刪除的內容、author／committer email、禁用名稱都被找出；輸出不含命中的內容', async (t) => {
  const repo = tempRepo(t);
  // 清單檔放在 repo 外，避免被 commit
  const listDir = mkdtempSync(join(tmpdir(), 'scan-history-names-'));
  t.after(() => rmSync(listDir, { recursive: true, force: true }));
  const names = join(listDir, 'names.txt');
  writeFileSync(names, '# 測試用\nZorblax\n');

  repo.write('notes.md', `第一行\n路徑 ${users('alice')}/repo\n`);
  const c1 = repo.commit('add notes');
  repo.write('notes.md', '第一行\n');
  const c2 = repo.commit('remove path');
  const c3 = repo.commit('by author', { author: { name: 'Alice', email: at('alice', 'mail.co') } });
  const c4 = repo.commit('by committer', { committer: { name: 'Bob', email: at('bob', 'corp.co') } });
  // 只在另一條分支上、且在標籤上的 commit 也要掃到
  repo.git(['switch', '-q', '-c', 'side']);
  repo.write('side.md', 'the zorblaxian plan\nZORBLAX again\n');
  const c5 = repo.commit('side');
  repo.git(['tag', 'v1']);
  repo.git(['switch', '-q', 'main']);

  const findings = await scanHistory(repo.dir, ['Zorblax']);
  const key = (f) => `${f.commit} ${f.file} ${f.kind} ${f.count}`;
  assert.deepEqual(findings.map(key).sort(), [
    `${c1} notes.md 個人路徑 1`,
    `${c3} (author) email 1`,
    `${c4} (committer) email 1`,
    `${c5} side.md 禁用名稱 2`,
  ].sort());
  assert.ok(!findings.some((f) => f.commit === c2));

  const r = run(repo.dir, names);
  assert.equal(r.status, 1, r.stderr);
  const out = r.stdout + r.stderr;
  assert.match(out, new RegExp(`${c1.slice(0, 12)} notes\\.md：個人路徑`));
  assert.match(out, new RegExp(`${c3.slice(0, 12)} \\(author\\)：email`));
  assert.match(out, new RegExp(`${c4.slice(0, 12)} \\(committer\\)：email`));
  assert.match(out, new RegExp(`${c5.slice(0, 12)} side\\.md：禁用名稱（2 處）`));
  assert.doesNotMatch(out, /alice|bob|zorblax|mail\.co|corp\.co/i);
});

test('檔名本身命中時不輸出檔名', async (t) => {
  const repo = tempRepo(t);
  repo.write('zorblax-plan.md', 'ok\n');
  const c1 = repo.commit('add');
  const findings = await scanHistory(repo.dir, ['Zorblax']);
  assert.deepEqual(findings, [{ commit: c1, file: HIDDEN_FILE, kind: '檔名：禁用名稱', count: 1 }]);
  assert.doesNotMatch(formatFinding(findings[0]), /zorblax/i);
});

test('沒有命中時以 0 結束；清單檔不存在時略過禁用名稱', (t) => {
  const repo = tempRepo(t);
  repo.write('a.md', '聯絡 user@example.com，路徑 /Users/<名稱>/repo\n');
  repo.commit('ok');
  const r = run(repo.dir, join(repo.dir, 'missing-names.txt'));
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /沒有 email、個人路徑或禁用名稱/);
});

test('唯讀：不改變 ref、index 與工作區', (t) => {
  const repo = tempRepo(t);
  repo.write('a.md', `${users('alice')}\n`);
  repo.commit('one');
  repo.write('a.md', 'staged\n');
  repo.git(['add', 'a.md']);
  repo.write('b.md', 'untracked\n');
  const snapshot = () => [
    repo.git(['for-each-ref', '--format=%(refname) %(objectname)']),
    repo.git(['status', '--porcelain=v1']),
    repo.git(['diff', '--cached']),
    repo.git(['rev-parse', 'HEAD']),
  ];
  const before = snapshot();
  assert.equal(run(repo.dir, join(repo.dir, 'missing-names.txt')).status, 1);
  assert.deepEqual(snapshot(), before);
});

test('不在 git repo 中時以 2 結束', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'scan-history-norepo-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const r = spawnSync(process.execPath, [SCRIPT], {
    cwd: dir, encoding: 'utf8', env: { PATH: process.env.PATH, GIT_CEILING_DIRECTORIES: dirname(dir) },
  });
  assert.equal(r.status, 2);
});

test('scanLog：hunk 內以 +++、diff 開頭的新增行算內容，不當成結構行；刪除的行不算', async () => {
  const lines = [
    '\x01abc\0T <t@example.com>\0T <t@example.com>',
    '',
    'diff --git a/x.md b/x.md',
    '--- a/x.md',
    '+++ b/x.md',
    '@@ -1 +1,3 @@',
    `-${users('old')}`,
    `+++ ${users('alice')}`,
    '+diff --git zorblax',
    '+ok',
    '\\ No newline at end of file',
  ];
  const findings = await scanLog(lines, ['Zorblax']);
  assert.deepEqual(findings, [
    { commit: 'abc', file: 'x.md', kind: '個人路徑', count: 1 },
    { commit: 'abc', file: 'x.md', kind: '禁用名稱', count: 1 },
  ]);
});
