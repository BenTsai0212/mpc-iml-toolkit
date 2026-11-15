import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  checkFiles, DENIED_NAMES_ENV, DENIED_NAMES_PATH, deniedNamesFile, findEmails, isAllowedEmail, loadDeniedNames, parseDeniedNames, PERSONAL_PATH,
  scanText, repoFiles, trackedFiles, untrackedFiles,
} from './check-sensitive.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..', '..');
const SCRIPT = join(HERE, 'check-sensitive.mjs');

// 本檔也在 repo 掃描範圍內：會命中的範例以片段組成，不以完整字串出現在檔案中
const at = (local, domain) => `${local}@${domain}`;
const users = (name) => `/${'Users'}/${name}`;
const home = (name) => `/${'home'}/${name}`;

test('findEmails：找出一行中的 email；頂級網域不是英文字母的不算', () => {
  assert.deepEqual(findEmails(`寄到 ${at('alice', 'mail.co')} 或 ${at('b.c+d', 'corp.co.uk')}`), [at('alice', 'mail.co'), at('b.c+d', 'corp.co.uk')]);
  assert.deepEqual(findEmails('npm i pkg@1.2.3'), []);
  assert.deepEqual(findEmails('@scope/pkg@2.0.0'), []);
  assert.deepEqual(findEmails('git@github.com:owner/repo.git'), ['git@github.com']);
  assert.deepEqual(findEmails('沒有 email'), []);
  assert.deepEqual(findEmails(undefined), []);
});

test('isAllowedEmail：放行 noreply、GitHub noreply、example 網域與保留頂級網域', () => {
  for (const address of [
    'noreply@anthropic.com',
    'git@github.com', 'git@gitlab.com', 'GIT@github.com',
    '12345+someone@users.noreply.github.com',
    'user@example.com', 'user@example.org', 'user@example.net', 'user@mail.example.com',
    'user@host.test', 'user@host.example', 'user@host.invalid', 'user@localhost.localhost', 'user@domain.tld',
  ]) {
    assert.equal(isAllowedEmail(address), true, address);
  }
});

test('isAllowedEmail：其他 email 不放行（反例）', () => {
  for (const address of [
    at('alice', 'mail.co'), at('noreply2', 'corp.co'), at('git2', 'github.com'), at('gitter', 'corp.co'), at('my.git', 'corp.co'), at('user', 'notexample.com'), at('user', 'example.com.evil.co'),
    at('user', 'noreply.github.com.evil.co'), at('user', 'host.tld.co'),
  ]) {
    assert.equal(isAllowedEmail(address), false, address);
  }
});

test('PERSONAL_PATH：/Users/<名稱> 與 /home/<名稱>；/home/runner 與角括號佔位不算', () => {
  for (const s of [users('alice'), `${users('a.b-c')}/Projects`, home('alice'), home('runner2'), home('runner.x')]) {
    assert.equal(PERSONAL_PATH.test(s), true, s);
  }
  for (const s of [
    '/Users/<名稱>/Projects', '/home/<名稱>/x', '/home/runner', '/home/runner/work/repo', '/Users/', '/usr/local/bin',
    '~/.agent-runner', '/tmp/claude-<uid>',
  ]) {
    assert.equal(PERSONAL_PATH.test(s), false, s);
  }
});

test('scanText：逐行回報行號與種類，同一行可同時命中兩種', () => {
  const text = ['第一行', `email ${at('alice', 'mail.co')}`, 'user@example.com', `\`${users('alice')}\``, `${home('bob')} ${at('x', 'y.co')}`].join('\n');
  assert.deepEqual(scanText(text), [
    { line: 2, kind: 'email' }, { line: 4, kind: '個人路徑' }, { line: 5, kind: 'email' }, { line: 5, kind: '個人路徑' },
  ]);
  assert.deepEqual(scanText('a\r\nb'), []);
  assert.deepEqual(scanText(null), []);
});

test('checkFiles：只輸出檔案、行號與種類，不輸出命中的內容；略過二進位檔與不存在的檔案', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'check-sensitive-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  writeFileSync(join(dir, 'a.md'), `ok\n${at('alice', 'mail.co')}\n${users('alice')}/x\n`);
  writeFileSync(join(dir, 'b.bin'), Buffer.from([0, 1, 2, ...Buffer.from(at('alice', 'mail.co'))]));
  const findings = checkFiles(['a.md', 'b.bin', 'missing.md'], dir);
  assert.deepEqual(findings, ['a.md:2：email', 'a.md:3：個人路徑']);
  assert.ok(findings.every((f) => !f.includes('alice')));
});

test('指令 --file：命中時 exit 1，輸出不含命中的內容；沒有命中時 exit 0', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'check-sensitive-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const bad = join(dir, 'comment.md');
  const good = join(dir, 'ok.md');
  writeFileSync(bad, `## 計畫\n\n路徑 ${users('alice')}/repo，聯絡 ${at('alice', 'mail.co')}\n`);
  writeFileSync(good, '## 計畫\n\n路徑 /Users/<名稱>/repo，聯絡 user@example.com\n');
  const run = (...a) => spawnSync(process.execPath, [SCRIPT, ...a], { encoding: 'utf8' });
  let r = run('--file', bad);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /comment\.md:3：email/);
  assert.match(r.stderr, /comment\.md:3：個人路徑/);
  assert.doesNotMatch(r.stdout + r.stderr, /alice/);
  r = run('--file', good);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(run('--file').status, 2);
  assert.equal(run('--file', join(dir, 'missing.md')).status, 2);
});

test('預設掃描：未追蹤的新檔案也掃，被 .gitignore 排除的不掃（#94）', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'check-sensitive-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const git = (...a) => execFileSync('git', ['-C', dir, ...a], { encoding: 'utf8' });
  git('init', '-q');
  writeFileSync(join(dir, '.gitignore'), 'ignored.md\nlogs/\n');
  writeFileSync(join(dir, 'tracked.md'), 'ok\n');
  git('add', '.gitignore', 'tracked.md');
  writeFileSync(join(dir, 'new-email.md'), `聯絡 ${at('alice', 'mail.co')}\n`);
  writeFileSync(join(dir, 'new-path.md'), `ok\n${users('alice')}/repo\n`);
  writeFileSync(join(dir, 'ignored.md'), `${at('alice', 'mail.co')} ${users('alice')}\n`);
  mkdirSync(join(dir, 'logs'));
  writeFileSync(join(dir, 'logs', 'run.log'), `${home('alice')}\n`);

  assert.deepEqual(trackedFiles(dir).sort(), ['.gitignore', 'tracked.md']);
  assert.deepEqual(untrackedFiles(dir).sort(), ['new-email.md', 'new-path.md']);
  assert.deepEqual(repoFiles(dir).sort(), ['.gitignore', 'new-email.md', 'new-path.md', 'tracked.md']);

  const r = spawnSync(process.execPath, [SCRIPT], { cwd: dir, encoding: 'utf8' });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /new-email\.md:1：email/);
  assert.match(r.stderr, /new-path\.md:2：個人路徑/);
  assert.doesNotMatch(r.stderr, /ignored\.md|run\.log/);
  assert.doesNotMatch(r.stdout + r.stderr, /alice/);

  rmSync(join(dir, 'new-email.md'));
  rmSync(join(dir, 'new-path.md'));
  const ok = spawnSync(process.execPath, [SCRIPT], { cwd: dir, encoding: 'utf8' });
  assert.equal(ok.status, 0, ok.stderr);
});

test('repo 內的檔案（已追蹤與未追蹤的新檔案）沒有 email、個人路徑或禁用名稱', () => {
  assert.deepEqual(checkFiles(repoFiles(ROOT), ROOT), []);
});

// ---- 禁用名稱（#96）----
// 虛構的佔位名稱，只用暫存清單檔，不讀寫真實清單

test('parseDeniedNames：一行一個，略過空行與 # 開頭的行，去掉前後空白', () => {
  assert.deepEqual(parseDeniedNames('# 註解\n\nZorblax\n  Quux Labs  \r\n   # 也是註解\n'), ['Zorblax', 'Quux Labs']);
  assert.deepEqual(parseDeniedNames(null), []);
});

test('loadDeniedNames：清單檔不存在時回傳空陣列；deniedNamesFile 可由環境變數指定', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'check-sensitive-names-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  assert.deepEqual(loadDeniedNames(join(dir, 'missing.txt')), []);
  const file = join(dir, 'names.txt');
  writeFileSync(file, 'Zorblax\n');
  assert.deepEqual(loadDeniedNames(file), ['Zorblax']);
  assert.equal(deniedNamesFile({ [DENIED_NAMES_ENV]: file }), file);
  assert.ok(deniedNamesFile({}).endsWith(DENIED_NAMES_PATH));
});

test('清單檔的預設路徑已被 .gitignore 排除', () => {
  assert.equal(spawnSync('git', ['-C', ROOT, 'check-ignore', '-q', DENIED_NAMES_PATH]).status, 0);
});

test('scanText：禁用名稱不分大小寫、以子字串比對；清單為空時不影響其他檢查', () => {
  const names = ['Zorblax', 'quux labs'];
  const text = ['沒有', 'the zorblaxian app', 'QUUX LABS 合作', 'quux-labs 不算', `${users('alice')} ZORBLAX`].join('\n');
  assert.deepEqual(scanText(text, names), [
    { line: 2, kind: '禁用名稱' }, { line: 3, kind: '禁用名稱' }, { line: 5, kind: '個人路徑' }, { line: 5, kind: '禁用名稱' },
  ]);
  assert.deepEqual(scanText(text, []), [{ line: 5, kind: '個人路徑' }]);
});

test('指令：禁用名稱命中時 exit 1，輸出不含名稱與該行內容；清單檔不存在時略過', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'check-sensitive-names-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const list = join(dir, 'names.txt');
  writeFileSync(list, '# 測試用\n\nZorblax\n');
  const file = join(dir, 'comment.md');
  writeFileSync(file, '## 計畫\n\n這是 zorblax 的祕密行\n');
  const run = (namesFile) => spawnSync(process.execPath, [SCRIPT, '--file', file], {
    env: { PATH: process.env.PATH, [DENIED_NAMES_ENV]: namesFile }, encoding: 'utf8',
  });
  let r = run(list);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /comment\.md:3：禁用名稱/);
  assert.doesNotMatch(r.stdout + r.stderr, /zorblax|祕密行/i);
  r = run(join(dir, 'missing.txt'));
  assert.equal(r.status, 0, r.stderr);
});
