import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, normalize, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

// 規則文件：每項規則只留一份正本，其他地方只放連結（#55）
const ROOT = fileURLToPath(new URL('../../', import.meta.url));

/**
 * 符合 patterns 的檔案：已追蹤的，加上尚未 git add、且沒被 .gitignore 排除的新檔案
 * （#110，比照 #95 的 check-sensitive.mjs；新文件在 git add 前也要檢查）。
 */
export function repoFiles(root, patterns) {
  const ls = (args) => execFileSync('git', ['-C', root, 'ls-files', '-z', ...args, '--', ...patterns], { encoding: 'utf8' })
    .split('\0').filter(Boolean);
  return [...new Set([...ls([]), ...ls(['--others', '--exclude-standard'])])].filter((f) => existsSync(join(root, f)));
}

const mdFiles = repoFiles(ROOT, ['*.md']);
const read = (file) => readFileSync(join(ROOT, file), 'utf8');

// 程式碼區塊與行內程式碼裡的連結不算
const stripCode = (text) => text.replace(/```[\s\S]*?```/g, '').replace(/`[^`\n]*`/g, '');

/** 每項規則的特徵字串與它的正本；特徵字串只能出現在正本。 */
const SINGLE_SOURCE = [
  { what: '三級確認表', marker: '| ① 先做後列', source: 'docs/workflow/github-writes.md' },
  { what: '合併的低風險條件', marker: '不含 `docs/workflow/`、`docs/adr/`、`docs/rfcs/`', source: 'docs/workflow/github-writes.md' },
  { what: '可信身分的列舉', marker: '`OWNER`、`MEMBER` 或 `COLLABORATOR`', source: 'docs/workflow/agent-workflow.md' },
  { what: '`plan-first` 的適用情況', marker: '資料庫 schema、登入權限、金流', source: 'docs/workflow/decision-center.md' },
  { what: '核心硬規則表', marker: '| 硬規則 | 來源 | 可刪條件 |', source: null },
  // 目標模式改為事件觸發＋決策時段（#102）
  { what: '決策包的格式', marker: '## 決策包（', source: 'docs/workflow/decision-center.md' },
  { what: '批次授權', marker: '視為逐項授權', source: 'docs/workflow/github-writes.md' },
  // 為注意力放寬確認規則（#106）
  { what: '合併省略編號', marker: '人回覆「合併」視為授權', source: 'docs/workflow/github-writes.md' },
  { what: '照選定的選項送出 `## 決定`', marker: '選定一個選項', source: 'docs/workflow/github-writes.md' },
  { what: '已定案的 Issue 直接建立', marker: '逐項討論定案', source: 'docs/workflow/github-writes.md' },
];

for (const { what, marker, source } of SINGLE_SOURCE) {
  test(`一份正本：${what}只出現在 ${source ?? '（不再以表格出現）'}`, () => {
    const hits = mdFiles.filter((f) => read(f).includes(marker));
    assert.deepEqual(hits, source ? [source] : [], `${what}出現在：${hits.join('、')}`);
  });
}

// 備援改為選用模組（#55 PR B）：核心不再帶 /pm-apply 的檔案與操作說明
test('備援模組：pm-actions.md 與 /pm-apply 只在 templates/modules/fallback/，核心只留連結', () => {
  for (const f of ['docs/workflow/pm-actions.md', '.claude/commands/pm-apply.md']) {
    assert.equal(existsSync(join(ROOT, f)), false, `${f} 應移到 templates/modules/fallback/`);
  }
  for (const f of ['templates/modules/fallback/pm-actions.md', 'templates/modules/fallback/pm-apply.md']) {
    assert.ok(existsSync(join(ROOT, f)), f);
  }
  // 讀不到 GitHub（例如在手機上）是日常情況，留在核心（PR #57 修正要求）
  assert.match(read('docs/workflow/decision-center.md'), /完全讀不到 GitHub（例如在手機上）時，只依交接文件工作/);
  const allowed = (f) => f === 'docs/workflow/modules.md' || f.startsWith('templates/modules/fallback/');
  for (const marker of ['Claude in Chrome', 'Claude outputs/pm/']) {
    const hits = mdFiles.filter((f) => !allowed(f) && read(f).includes(marker));
    assert.deepEqual(hits, [], `「${marker}」出現在核心文件：${hits.join('、')}`);
  }
});

// AGENTS.md 精簡（#55 PR C）：細節放在各工具的 README，AGENTS.md 只留指令與「路徑＋一句話」。
// 上限依憲法第 6 節「核心 `AGENTS.md` 目標 40～50 行，加上專案內容後 60～80 行」：本測試隨 template 複製到新專案，
// 新專案加上自己的指令與結構後可到 80 行，所以上限是 80，不是 template 本身的行數（PR #58 修正要求）。
const AGENTS_MAX_LINES = 80;
test(`AGENTS.md 不超過 ${AGENTS_MAX_LINES} 行`, () => {
  const lines = read('AGENTS.md').replace(/\n$/, '').split('\n').length;
  assert.ok(lines <= AGENTS_MAX_LINES, `AGENTS.md 有 ${lines} 行（上限 ${AGENTS_MAX_LINES}，見憲法第 6 節「規則要掙來」）`);
});

// 目標模式（#62）：模組檔案、標籤、規則各在一處
test('目標模式：模組檔案與標籤存在，例外規則只寫在 github-writes.md', () => {
  for (const f of ['templates/modules/goal/goal-card.md', 'templates/modules/goal/wake-prompt.md']) {
    assert.ok(existsSync(join(ROOT, f)), f);
  }
  assert.match(read('.github/labels.yml'), /^goal:\n {2}- \{ name: "goal-mode"/m);
  assert.match(read('docs/workflow/modules.md'), /^## 目標模式/m);
  assert.match(read('docs/workflow/decision-center.md'), /^## 10\. 目標模式/m);
  const hits = mdFiles.filter((f) => read(f).includes('### 目標模式下的例外'));
  assert.deepEqual(hits, ['docs/workflow/github-writes.md']);
  // 喚醒的 session 不合併；授權只在決策中心對話（#62 決定 D）
  assert.match(read('templates/modules/goal/wake-prompt.md'), /即使有人在這個 session 回覆授權，也不合併/);
  // 喚醒的 session 照文字執行時的範圍與步驟（PR #63 修正要求）
  const dc = read('docs/workflow/decision-center.md');
  assert.match(read('templates/modules/goal/wake-prompt.md'), /處理目標卡範圍以外的工作。範圍＝帶 `goal-mode` 的目標卡本身、掛在其下的子 Issue，以及對應這些子 Issue 的 PR/);
  assert.match(dc, /只處理目標卡的範圍：帶 `goal-mode` 的目標卡本身、掛在其下的子 Issue，以及對應這些子 Issue 的 PR/);
  assert.match(dc, /上次審查後有新的 `## 修正回報`、尚未再審的/);
  assert.match(dc, /依第 5 節第 5、7 項送修正要求/);
  // 範本不預設 goal-mode（#62 決定 2）
  assert.doesNotMatch(read('templates/modules/goal/goal-card.md').split('---')[1], /goal-mode/);
});

// 修憲時版本號一致（#102）：憲法開頭的版本、版本紀錄最後一列、AGENTS.md 的憲法版本
test('憲法版本：開頭、版本紀錄最後一列與 AGENTS.md 一致', () => {
  const constitution = read('docs/workflow/constitution.md');
  const head = /^- 版本：(v[\d.]+)/m.exec(constitution)?.[1];
  const rows = [...constitution.matchAll(/^\| (v[\d.]+) \|/gm)].map((m) => m[1]);
  const agents = /憲法版本：(v[\d.]+)/.exec(read('AGENTS.md'))?.[1];
  assert.ok(head, '憲法開頭找不到「- 版本：vX.Y」');
  assert.equal(rows.at(-1), head, '版本紀錄最後一列與開頭的版本不同');
  assert.equal(agents, head, 'AGENTS.md 的憲法版本與憲法不同');
});

// 雲端執行（#85）：模組、prompt 範本、雲端步驟與決策中心的規則各在一處
test('雲端執行：prompt 範本可直接貼上，分支格式具體、不用 claude/ 前綴', () => {
  const prompt = read('templates/modules/cloud/trigger-prompt.md');
  const body = prompt.split('\n---\n')[1];
  assert.ok(body, '範本以分隔線區分說明與要貼上的內容');
  assert.match(body, /<owner\/repo>/);
  assert.match(body, /@<決定者帳號>/);
  assert.match(body, /`<type>\/<N>-<slug>`/);
  assert.match(body, /\*\*不用 `claude\/` 前綴\*\*/);
  assert.match(body, /其他情況（別的標籤、對象不符、讀不到觸發事件）→ 立即結束，不留言、不改標籤、不做任何事/);
  assert.match(body, /check-post-body\.mjs/);
  // #87：寫出檢查結果、自動附加的結尾不算違反原樣貼出
  assert.match(body, /PR 描述的「驗證」與 `## 修正回報` 寫出 `check-post-body\.mjs` 的檢查結果（種類與「檢查通過」）/);
  assert.match(body, /agent 自己不要再另外加結尾/);
  const usage = prompt.split('\n---\n')[0];
  assert.match(usage, /排程任務 1：Issue 加上標籤且標籤屬於 agent:ready/);
  assert.match(usage, /排程任務 2：PR 加上標籤且標籤屬於 changes-requested/);
  assert.match(read('docs/workflow/modules.md'), /一個排程任務只能設一個 GitHub 事件觸發條件/);
  assert.match(body, /合併 PR、推送 `main`/);
  assert.match(read('docs/workflow/modules.md'), /^## 雲端執行/m);
  assert.match(read('docs/workflow/agent-workflow.md'), /^## 在雲端執行時/m);
  assert.match(read('docs/workflow/decision-center.md'), /^## 11\. 雲端執行/m);
});

// 工作區（#127）：一個 Project 管同一客戶的多個 repo；規則在 modules.md，操作在 decision-center 第 12 節
test('工作區：模組、決策中心一節與兩個範本存在，範本可直接貼上', () => {
  assert.match(read('docs/workflow/modules.md'), /^## 工作區/m);
  assert.match(read('docs/workflow/decision-center.md'), /^## 12\. 工作區/m);
  assert.match(read('docs/workflow/constitution.md'), /^\| 工作區 \|/m);
  const instructions = read('templates/modules/workspace/instructions.md');
  const body = instructions.split('\n---\n')[1];
  assert.ok(body, '範本以分隔線區分說明與要貼上的內容');
  // 登記表的欄位（#127 結論 2）
  assert.match(body, /\| repo \| 角色 \| 客戶 \| 可見性 \| 建立時的 template 版本 \| 目前憲法版本 \| 交接文件名稱 \| 相依的 repo \|/);
  assert.match(body, /只寫入目標 repo/);
  assert.match(read('templates/modules/workspace/handoff.md'), /^## 2\. 相依與合併順序/m);
  // 分組準則只有一份正本
  const hits = mdFiles.filter((f) => read(f).includes('Project 的邊界＝客戶與保密範圍'));
  assert.deepEqual(hits, ['docs/workflow/modules.md']);
});

/** GitHub 的標題錨點：轉小寫、去掉標點（含全形）、空白換成 -；重複的標題加 -1、-2。 */
export function anchors(markdown) {
  const seen = new Map();
  const out = new Set();
  for (const line of markdown.replace(/```[\s\S]*?```/g, '').split('\n')) {
    const m = /^#{1,6}\s+(.+?)\s*#*\s*$/.exec(line);
    if (!m) continue;
    const text = m[1].replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/<[^>]+>/g, '');
    const base = text.toLowerCase().replace(/[^\p{L}\p{M}\p{N}\p{Pc} -]/gu, '').replace(/ /g, '-');
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    out.add(n ? `${base}-${n}` : base);
  }
  return out;
}

test('anchors：與 GitHub 的錨點規則一致（中文、全形標點、行內程式碼、重複標題）', () => {
  const a = anchors('## 0. 前置檢查\n## 5. 把決定送回 GitHub\n## 2. 合併：依風險分兩種授權（試驗中）\n### 先審計畫（`plan-first`）\n## 重複\n## 重複\n```\n## 不是標題\n```');
  for (const id of ['0-前置檢查', '5-把決定送回-github', '2-合併依風險分兩種授權試驗中', '先審計畫plan-first', '重複', '重複-1']) {
    assert.ok(a.has(id), id);
  }
  assert.ok(!a.has('不是標題'));
});

/** files（相對於 root）中指向不存在的檔案或標題的相對連結。 */
export function brokenLinks(root, files) {
  const readIn = (file) => readFileSync(join(root, file), 'utf8');
  const broken = [];
  for (const file of files) {
    for (const [, target] of stripCode(readIn(file)).matchAll(/\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g)) {
      if (/^[a-z][a-z0-9+.-]*:/i.test(target)) continue;
      const [path, hash] = target.split('#');
      const dest = path ? normalize(join(dirname(file), decodeURIComponent(path))) : file;
      if (!existsSync(join(root, dest))) {
        broken.push(`${file} → ${target}（檔案不存在）`);
        continue;
      }
      if (hash && dest.endsWith('.md') && statSync(join(root, dest)).isFile()) {
        if (!anchors(readIn(dest)).has(decodeURIComponent(hash))) broken.push(`${file} → ${target}（找不到標題）`);
      }
    }
  }
  return broken;
}

test('repoFiles＋brokenLinks：未追蹤的新文件也檢查，被 .gitignore 排除的不檢查（#110）', () => {
  const dir = mkdtempSync(join(tmpdir(), 'doc-rules-'));
  try {
    execFileSync('git', ['init', '-q', dir], { stdio: 'ignore' });
    writeFileSync(join(dir, '.gitignore'), 'ignored.md\n');
    writeFileSync(join(dir, 'tracked.md'), '# 標題\n\n[有效](new.md#新文件)\n');
    execFileSync('git', ['-C', dir, 'add', 'tracked.md'], { stdio: 'ignore' });
    writeFileSync(join(dir, 'new.md'), '# 新文件\n\n[壞連結](missing.md)\n[壞錨點](tracked.md#沒有這個標題)\n');
    writeFileSync(join(dir, 'ignored.md'), '[壞連結](also-missing.md)\n');
    const files = repoFiles(dir, ['*.md']);
    assert.deepEqual([...files].sort(), ['new.md', 'tracked.md']);
    assert.deepEqual(brokenLinks(dir, files).sort(), [
      'new.md → missing.md（檔案不存在）',
      'new.md → tracked.md#沒有這個標題（找不到標題）',
    ]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('文件中的相對連結都指向存在的檔案與標題', () => {
  const broken = brokenLinks(ROOT, mdFiles);
  assert.deepEqual(broken, [], `\n${broken.join('\n')}`);
  assert.ok(mdFiles.length > 10 && relative(ROOT, ROOT) === '');
});

// agent 只讀可信身分的內容（#65）：文件與程式不再以 gh 的 view 子命令讀 Issue／PR，改用 read-trusted.mjs；
// runner 的允許清單也不含這兩個指令（#65 決定：連只讀 labels 的寫法也不用）。測試檔中的範例字串除外。
test('不以 gh 的 issue／pr view 讀取：.md 與非測試的 .mjs 都不出現，runner 設定一致', () => {
  const files = repoFiles(ROOT, ['*.md', '*.mjs']).filter((f) => !f.endsWith('.test.mjs'));
  const pattern = /\bgh\s+(issue|pr)\s+view\b/;
  const hits = files.filter((f) => pattern.test(read(f)));
  assert.deepEqual(hits, [], `改用 node tools/workflow/read-trusted.mjs：${hits.join('、')}`);
  assert.match(read('docs/workflow/agent-workflow.md'), /node tools\/workflow\/read-trusted\.mjs --issue N/);
  const { permissions } = JSON.parse(read('tools/workflow/runner/runner-settings.base.json'));
  assert.deepEqual(permissions.allow.filter((p) => pattern.test(p.replace(/^Bash\(|\*?\)$/g, ''))), []);
  for (const p of ['Bash(gh api*/comments*)', 'Bash(gh api*/reviews*)']) assert.ok(permissions.deny.includes(p), p);
});
