import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import {
  LABELS_FILE, RULESET_NAME, formatCommand, labelCommand, parseArgs, parseGhJson, parseLabels, planLabels, run,
} from './bootstrap-github.mjs';

const realLabels = readFileSync(LABELS_FILE, 'utf8');

test('parseLabels：解析 repo 內的 labels.yml', () => {
  const groups = parseLabels(realLabels);
  assert.deepEqual(Object.keys(groups), ['core', 'online', 'collab', 'automation', 'goal']);
  assert.deepEqual(groups.goal, [{ name: 'goal-mode', color: '006b75', description: '目標模式：已核准的目標，決策 agent 在範圍內自動推進（試驗中）' }]);
  assert.equal(groups.core.length, 12);
  assert.deepEqual(groups.core[0], { name: 'type:feat', color: '1d76db', description: '新功能' });
  assert.ok(groups.core.some((l) => l.description.includes('## 決定')), '描述中的 # 不是註解');
});

test('parseLabels：無法解析的行指出行號', () => {
  const text = '# 註解\ncore:\n  - { name: "a", color: "ffffff", description: "x" }\n  - { name: b }\n';
  assert.throws(() => parseLabels(text), /第 4 行/);
  assert.throws(() => parseLabels('core:\n  - { name: "a", color: "fff", description: "x" }\n'), /第 2 行/);
  assert.throws(() => parseLabels('  - { name: "a", color: "ffffff", description: "x" }\n'), /第 1 行.*不在任何群組/);
});

test('parseLabels：忽略空行與註解，顏色轉小寫', () => {
  const groups = parseLabels('\n# x\ncore:\n\n  - { name: "a", color: "ABCDEF", description: "" }\n');
  assert.deepEqual(groups, { core: [{ name: 'a', color: 'abcdef', description: '' }] });
});

const groups = parseLabels('core:\n  - { name: "a", color: "111111", description: "A" }\n  - { name: "b", color: "222222", description: "B" }\n  - { name: "c", color: "333333", description: "C" }\nonline:\n  - { name: "d", color: "444444", description: "D" }\n');

test('planLabels：不存在 → create；不同 → update；相同 → skip（名稱與顏色不分大小寫）', () => {
  const plan = planLabels(groups, ['core'], [
    { name: 'B', color: '222222', description: '舊描述' },
    { name: 'c', color: '333333', description: 'C' },
  ]);
  assert.deepEqual(plan.map((s) => `${s.action}:${s.label.name}`), ['create:a', 'update:b', 'skip:c']);
  assert.equal(planLabels(groups, ['core'], [{ name: 'a', color: 'AAAAAA', description: 'A' }])[0].action, 'update');
});

test('planLabels：只建立所選模組；不認得的模組報錯', () => {
  assert.deepEqual(planLabels(groups, ['online']).map((s) => s.label.name), ['d']);
  assert.equal(planLabels(groups, ['core', 'online']).length, 4);
  assert.throws(() => planLabels(groups, ['core', 'nope']), /nope.*可用：core、online/);
});

test('labelCommand 與 formatCommand', () => {
  const label = { name: 'type:feat', color: '1d76db', description: '新功能 與 空白' };
  assert.deepEqual(labelCommand('o/r', { action: 'create', label }).slice(0, 4), ['gh', 'label', 'create', 'type:feat']);
  assert.equal(labelCommand('o/r', { action: 'update', label })[2], 'edit');
  assert.equal(formatCommand(['gh', 'label', 'create', "it's", 'a b', 'type:feat']), `gh label create 'it'\\''s' 'a b' type:feat`);
});

test('parseArgs：預設只有 core；--repo 必填', () => {
  assert.deepEqual(parseArgs(['--repo', 'o/r']), { repo: 'o/r', modules: ['core'], board: false, ruleset: false, dryRun: false });
  assert.deepEqual(parseArgs(['--repo', 'o/r', '--board', '--ruleset']), { repo: 'o/r', modules: ['core'], board: true, ruleset: true, dryRun: false });
  assert.deepEqual(parseArgs(['--repo=o/r', '--modules', 'core,online', '--dry-run']).modules, ['core', 'online']);
  assert.throws(() => parseArgs([]), /--repo/);
  assert.throws(() => parseArgs(['--repo', 'noslash']), /--repo/);
  assert.throws(() => parseArgs(['--repo', 'o/r', '--bogus']), /不認得/);
});

// 假的 gh：記錄所有呼叫（含標準輸入）；讀取類回傳固定資料
const READS = ['label list', 'project list', 'project field-list'];
function fakeGh({ labels = [], projects = [], fields = [], rulesets = [], failReads = false, emptyReads = false } = {}) {
  const calls = [];
  const exec = (args, input) => {
    calls.push({ args, input });
    const key = args.slice(1, 3).join(' ');
    const reply = (data) => { if (failReads) throw new Error('HTTP 404'); return emptyReads ? '' : JSON.stringify(data); };
    if (key === 'label list') return reply(labels);
    if (key === 'project list') return reply({ projects });
    if (key === 'project field-list') return reply({ fields });
    if (args[1] === 'api' && !args.includes('--method')) return reply(rulesets);
    if (key === 'project create') return JSON.stringify({ number: 7 });
    return '';
  };
  return { exec, calls };
}
const isWrite = ({ args }) => !READS.includes(args.slice(1, 3).join(' ')) && !(args[1] === 'api' && !args.includes('--method'));
const writesOf = (gh) => gh.calls.filter(isWrite);
const cmd = (args, n = 3) => args.slice(0, n).join(' ');
const go = (argv, gh, out = []) => run({ argv: ['--repo', 'me/new-app', ...argv], exec: gh.exec, log: (l) => out.push(l) });

test('不加 --board：不建看板、不讀看板；預設設定合併後刪分支', () => {
  const gh = fakeGh();
  const out = [];
  const { todos } = go([], gh, out);
  assert.equal(gh.calls.some(({ args }) => args[1] === 'project'), false);
  assert.equal(gh.calls.some(({ args }) => args[1] === 'api'), false, '未加 --ruleset 不碰 ruleset');
  assert.deepEqual(writesOf(gh).at(-1).args, ['gh', 'repo', 'edit', 'me/new-app', '--delete-branch-on-merge']);
  assert.equal(writesOf(gh).filter(({ args }) => args[1] === 'label').length, 12);
  assert.match(out.join('\n'), /未加 --board，不建立看板/);
  assert.deepEqual(todos, []);
});

test('--board：新建看板、建立 Phase 與 Area（佔位選項「未設定」）並連結；auto-add 只列在待辦', () => {
  const gh = fakeGh();
  const { todos } = go(['--board'], gh);
  const project = writesOf(gh).filter(({ args }) => args[1] === 'project').map(({ args }) => args);
  assert.deepEqual(project, [
    ['gh', 'project', 'create', '--owner', 'me', '--title', 'new-app', '--format', 'json'],
    ['gh', 'project', 'field-create', '7', '--owner', 'me', '--name', 'Phase', '--data-type', 'SINGLE_SELECT', '--single-select-options', '未設定'],
    ['gh', 'project', 'field-create', '7', '--owner', 'me', '--name', 'Area', '--data-type', 'SINGLE_SELECT', '--single-select-options', '未設定'],
    ['gh', 'project', 'link', '7', '--owner', 'me', '--repo', 'new-app'],
  ]);
  assert.equal(gh.calls.some(({ args }) => args[2] === 'copy'), false, '不再複製範本看板');
  assert.equal(todos.length, 1);
  assert.match(todos[0], /選用.*#7.*auto-add/);
});

test('--board：已有同名看板時不新建，只補缺少的欄位並連結', () => {
  const gh = fakeGh({ projects: [{ number: 9, title: 'new-app', closed: false }], fields: [{ name: 'Phase' }, { name: 'Status' }] });
  go(['--board'], gh);
  const project = writesOf(gh).filter(({ args }) => args[1] === 'project').map(({ args }) => args.slice(0, 4).join(' '));
  assert.deepEqual(project, ['gh project field-create 9', 'gh project link 9']);
  assert.ok(writesOf(gh).some(({ args }) => args.includes('Area')));
  assert.ok(!writesOf(gh).some(({ args }) => args.includes('Phase')));
});

test('--ruleset：以 API 為預設分支建立 ruleset，請求內容符合規格，並提醒 GitHub Free 私人 repo', () => {
  const gh = fakeGh();
  const out = [];
  const { todos } = go(['--ruleset'], gh, out);
  const post = writesOf(gh).find(({ args }) => args[1] === 'api');
  assert.deepEqual(post.args, ['gh', 'api', '--method', 'POST', 'repos/me/new-app/rulesets', '--input', '-']);
  const body = JSON.parse(post.input);
  assert.equal(body.name, RULESET_NAME);
  assert.equal(body.target, 'branch');
  assert.equal(body.enforcement, 'active');
  assert.deepEqual(body.conditions.ref_name.include, ['~DEFAULT_BRANCH']);
  assert.deepEqual(body.rules.map((r) => r.type), ['deletion', 'non_fast_forward', 'pull_request']);
  assert.equal(body.rules[2].parameters.required_approving_review_count, 0);
  assert.match(out.join('\n'), /GitHub Free 的私人 repo 不會套用 ruleset/);
  assert.ok(todos.some((t) => /GitHub Free/.test(t)));
});

test('--ruleset：已有同名 ruleset 時不重複建立', () => {
  const gh = fakeGh({ rulesets: [{ id: 42, name: RULESET_NAME }] });
  const out = [];
  go(['--ruleset'], gh, out);
  assert.equal(writesOf(gh).some(({ args }) => args[1] === 'api'), false);
  assert.match(out.join('\n'), /略過（已有同名 ruleset）/);
});

test('dry-run：列出標籤、刪分支、看板與 ruleset 指令，不呼叫任何寫入', () => {
  const gh = fakeGh({ labels: [{ name: 'blocked', color: 'b60205', description: '開發中卡住，或 agent 停下等待 ## 決定' }] });
  const out = [];
  const { writes, todos } = go(['--dry-run', '--board', '--ruleset'], gh, out);
  assert.equal(writesOf(gh).length, 0, '試跑不得執行寫入');
  assert.equal(writes.length, 11 + 1 + 4 + 1, '11 個標籤、刪分支、看板 create／2 個欄位／link、ruleset');
  const text = out.join('\n');
  assert.match(text, /（試跑）\$ gh label create type:feat --repo me\/new-app --color 1d76db --description '新功能'/);
  assert.match(text, /略過（已存在且相同）：blocked/);
  assert.match(text, /（試跑）\$ gh repo edit me\/new-app --delete-branch-on-merge/);
  assert.match(text, /\$ gh project create --owner me --title new-app --format json/);
  assert.match(text, /\$ gh project field-create '<新看板編號>' --owner me --name Phase/);
  assert.match(text, /\$ gh project link '<新看板編號>' --owner me --repo new-app/);
  assert.match(text, /\$ gh api --method POST repos\/me\/new-app\/rulesets --input -/);
  assert.match(text, /"required_approving_review_count": 0/);
  assert.match(text, /試跑結束：共 17 個寫入指令，未執行/);
  assert.equal(todos.length, 2);
});

test('dry-run：repo 還讀不到時視為沒有標籤、看板與 ruleset，仍列出指令', () => {
  const gh = fakeGh({ failReads: true });
  const { writes } = go(['--dry-run', '--modules', 'core,automation', '--board', '--ruleset'], gh);
  assert.equal(writesOf(gh).length, 0);
  assert.equal(writes.length, 14 + 1 + 4 + 1);
});

test('實際執行：讀取失敗時停止，不繼續寫入', () => {
  const gh = fakeGh({ failReads: true });
  assert.throws(() => go([], gh), /HTTP 404/);
  assert.equal(writesOf(gh).length, 0);
});

test('實際執行：建立或更新標籤', () => {
  const gh = fakeGh({ labels: [{ name: 'rfc', color: '000000', description: 'x' }] });
  go([], gh);
  const writes = writesOf(gh).map(({ args }) => args.slice(0, 4).join(' '));
  assert.ok(writes.includes('gh label edit rfc'));
  assert.ok(writes.includes('gh label create type:feat'));
});

test('parseGhJson：空輸出視為預設值', () => {
  assert.deepEqual(parseGhJson('', []), []);
  assert.deepEqual(parseGhJson('  \n', {}), {});
  assert.deepEqual(parseGhJson('[{"name":"a"}]', []), [{ name: 'a' }]);
});

test('實際執行：gh 的讀取輸出空字串時，仍正常建立標籤、看板與 ruleset', () => {
  const gh = fakeGh({ emptyReads: true });
  go(['--board', '--ruleset'], gh);
  const writes = writesOf(gh);
  assert.equal(writes.filter(({ args }) => args[1] === 'label' && args[2] === 'create').length, 12);
  assert.ok(writes.some(({ args }) => cmd(args) === 'gh project create'));
  assert.ok(writes.some(({ args }) => args[1] === 'api'));
});

test('不再有指向作者帳號的 config.json', () => {
  assert.equal(existsSync(join(dirname(LABELS_FILE), '..', 'tools', 'workflow', 'config.json')), false);
});
