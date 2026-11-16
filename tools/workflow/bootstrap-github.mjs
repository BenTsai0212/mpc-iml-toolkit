#!/usr/bin/env node
// 從 template 建立新 repo 後，一個指令完成標籤、合併後刪分支，以及選用的看板與 ruleset（憲法第 9 節 B 段第 2～4 步）。
// 用法：node tools/workflow/bootstrap-github.mjs --repo <owner/name> [--modules core,online,collab,automation,goal] [--board] [--ruleset] [--lang zh-TW|en] [--dry-run]
// --modules 預設只有 core；--board 新建看板並連結；--ruleset 為預設分支建立 ruleset；
// --lang en 改用英文的標籤描述（templates/i18n/en/github/labels.yml）與看板佔位選項，給流程語言 en 的 repo（BenTsai0212/dev-workflow-template#129）；預設 zh-TW。
// --dry-run 只列出將執行的 gh 指令（仍會讀取現有標籤、看板與 ruleset，不做任何寫入）。
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const LABELS_FILE = join(HERE, '..', '..', '.github', 'labels.yml');
/** 流程語言 en 的標籤定義：名稱、顏色與群組與 LABELS_FILE 相同，只有描述是英文（BenTsai0212/dev-workflow-template#129）。 */
export const LABELS_FILE_EN = join(HERE, '..', '..', 'templates', 'i18n', 'en', 'github', 'labels.yml');
export const BOOTSTRAP_LANGS = ['zh-TW', 'en'];

const GROUP = /^([A-Za-z][\w-]*):\s*$/;
const ITEM = /^\s+-\s*\{\s*name:\s*"([^"]+)",\s*color:\s*"([0-9a-fA-F]{6})",\s*description:\s*"([^"]*)"\s*\}\s*$/;

/** 解析 .github/labels.yml 目前的單行格式；無法解析的行丟出含行號的錯誤。 */
export function parseLabels(text) {
  const groups = {};
  let current = null;
  text.split('\n').forEach((raw, i) => {
    const line = raw.replace(/\r$/, '');
    if (!line.trim() || line.trimStart().startsWith('#')) return;
    const g = GROUP.exec(line);
    if (g) {
      current = g[1];
      groups[current] ??= [];
      return;
    }
    const m = ITEM.exec(line);
    if (m && current) {
      groups[current].push({ name: m[1], color: m[2].toLowerCase(), description: m[3] });
      return;
    }
    throw new Error(`labels.yml 第 ${i + 1} 行無法解析${m ? '（標籤不在任何群組下）' : ''}：${line.trim()}`);
  });
  return groups;
}

/** 依模組選出標籤，與現有標籤比對：不存在 → create；顏色或描述不同 → update；相同 → skip。 */
export function planLabels(groups, modules, existing = []) {
  const unknown = modules.filter((m) => !groups[m]);
  if (unknown.length) {
    throw new Error(`labels.yml 沒有模組：${unknown.join('、')}（可用：${Object.keys(groups).join('、')}）`);
  }
  const byName = new Map(existing.map((l) => [l.name.toLowerCase(), l]));
  return modules.flatMap((m) =>
    groups[m].map((label) => {
      const cur = byName.get(label.name.toLowerCase());
      if (!cur) return { action: 'create', label };
      const same = cur.color.toLowerCase() === label.color && (cur.description ?? '') === label.description;
      return { action: same ? 'skip' : 'update', label };
    }),
  );
}

export function labelCommand(repo, { action, label }) {
  const verb = action === 'create' ? 'create' : 'edit';
  return ['gh', 'label', verb, label.name, '--repo', repo, '--color', label.color, '--description', label.description];
}

/** 指令顯示用：含空白或特殊字元的參數加上單引號。 */
export function formatCommand(args) {
  return args.map((a) => (/^[\w@%+=:,./-]+$/.test(a) ? a : `'${a.replace(/'/g, `'\\''`)}'`)).join(' ');
}

/** gh 的 JSON 輸出；沒有資料時 gh 可能輸出空字串（例如剛建立、還沒有任何標籤的 repo），視為 fallback。 */
export function parseGhJson(out, fallback) {
  return out && out.trim() ? JSON.parse(out) : fallback;
}

export function parseArgs(argv) {
  const opts = { repo: null, modules: ['core'], board: false, ruleset: false, dryRun: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--dry-run') opts.dryRun = true;
    else if (a === '--board') opts.board = true;
    else if (a === '--ruleset') opts.ruleset = true;
    else if (a === '--repo') opts.repo = argv[++i];
    else if (a.startsWith('--repo=')) opts.repo = a.slice(7);
    else if (a === '--modules') opts.modules = (argv[++i] ?? '').split(',').map((s) => s.trim()).filter(Boolean);
    else if (a.startsWith('--modules=')) opts.modules = a.slice(10).split(',').map((s) => s.trim()).filter(Boolean);
    else if (a === '--lang') opts.lang = argv[++i];
    else if (a.startsWith('--lang=')) opts.lang = a.slice(7);
    else throw new Error(`不認得的參數：${a}`);
  }
  if (!opts.repo || !/^[\w.-]+\/[\w.-]+$/.test(opts.repo)) throw new Error('需要 --repo <owner/name>');
  if (!opts.modules.length) throw new Error('--modules 不能是空的');
  if ('lang' in opts && !BOOTSTRAP_LANGS.includes(opts.lang)) throw new Error(`--lang 只能是 ${BOOTSTRAP_LANGS.join('、')}`);
  return opts;
}

/** 看板的單選欄位；GitHub 的單選欄位至少要有一個選項，所以各放佔位選項「未設定」。 */
export const BOARD_FIELDS = ['Phase', 'Area'];
export const PLACEHOLDER_OPTION = '未設定';
export const PLACEHOLDER_OPTION_EN = 'Not set';

export const RULESET_NAME = 'protect-default-branch';

/** 預設分支的 ruleset：禁止刪除、禁止強制推送、必須經 PR 才能合併（required approvals 0）。 */
export function rulesetBody() {
  return {
    name: RULESET_NAME,
    target: 'branch',
    enforcement: 'active',
    conditions: { ref_name: { include: ['~DEFAULT_BRANCH'], exclude: [] } },
    rules: [
      { type: 'deletion' },
      { type: 'non_fast_forward' },
      {
        type: 'pull_request',
        parameters: {
          required_approving_review_count: 0,
          dismiss_stale_reviews_on_push: false,
          require_code_owner_review: false,
          require_last_push_approval: false,
          required_review_thread_resolution: false,
        },
      },
    ],
  };
}

/**
 * 主流程。exec(args, input) 執行 gh 並回傳 stdout（input 為標準輸入，可省略）；
 * 讀取類指令在 dry-run 時也會執行，寫入類只在非 dry-run 時執行。
 * 回傳 { writes, todos }，方便測試；writes 的每一項為 { args, input }。
 */
export function run({ argv, exec, readText = (f) => readFileSync(f, 'utf8'), log = console.log }) {
  const opts = parseArgs(argv);
  const [owner, name] = opts.repo.split('/');
  const en = opts.lang === 'en';
  const groups = parseLabels(readText(en ? LABELS_FILE_EN : LABELS_FILE));
  const writes = [];
  const todos = [];
  const write = (args, input) => {
    writes.push({ args, input });
    log(`${opts.dryRun ? '（試跑）' : ''}$ ${formatCommand(args)}${input === undefined ? '' : '（標準輸入為下方 JSON）'}`);
    if (input !== undefined) log(input);
    if (!opts.dryRun) return exec(args, input);
    return '';
  };
  // 讀取：dry-run 時讀不到就以 fallback 繼續（repo 可能還不存在）；實際執行時讀不到就停止。
  const read = (args, fallback, what) => {
    try {
      return parseGhJson(exec(args), fallback);
    } catch (error) {
      if (!opts.dryRun) throw error;
      log(`（試跑）無法讀取${what}：${error.message.split('\n')[0]}`);
      return fallback;
    }
  };

  log(`== 標籤（模組：${opts.modules.join('、')}）==`);
  const existing = read(['gh', 'label', 'list', '--repo', opts.repo, '--limit', '500', '--json', 'name,color,description'], [], '現有標籤，視為沒有標籤');
  const plan = planLabels(groups, opts.modules, existing);
  for (const step of plan) {
    if (step.action === 'skip') log(`略過（已存在且相同）：${step.label.name}`);
    else write(labelCommand(opts.repo, step));
  }
  const count = (a) => plan.filter((s) => s.action === a).length;
  log(`標籤：新增 ${count('create')}、更新 ${count('update')}、略過 ${count('skip')}`);

  log('== 合併後刪分支 ==');
  write(['gh', 'repo', 'edit', opts.repo, '--delete-branch-on-merge']);

  log('== 看板 ==');
  if (!opts.board) {
    log('未加 --board，不建立看板（核心流程只靠標籤）。');
  } else {
    const projects = read(['gh', 'project', 'list', '--owner', owner, '--limit', '200', '--format', 'json'], {}, ` ${owner} 的看板`).projects ?? [];
    const found = projects.find((p) => p.title === name && !p.closed);
    let number;
    let fields = [];
    if (found) {
      number = String(found.number);
      log(`略過建立：${owner} 已有標題為「${name}」的看板 #${number}`);
      fields = read(['gh', 'project', 'field-list', number, '--owner', owner, '--limit', '100', '--format', 'json'], {}, `看板 #${number} 的欄位`).fields ?? [];
    } else {
      const out = write(['gh', 'project', 'create', '--owner', owner, '--title', name, '--format', 'json']);
      number = opts.dryRun ? '<新看板編號>' : String(JSON.parse(out).number);
    }
    const fieldNames = new Set(fields.map((f) => f.name));
    for (const field of BOARD_FIELDS) {
      if (fieldNames.has(field)) log(`略過（欄位已存在）：${field}`);
      else write(['gh', 'project', 'field-create', number, '--owner', owner, '--name', field,
        '--data-type', 'SINGLE_SELECT', '--single-select-options', en ? PLACEHOLDER_OPTION_EN : PLACEHOLDER_OPTION]);
    }
    write(['gh', 'project', 'link', number, '--owner', owner, '--repo', name]);
    todos.push(`（選用）在看板（${owner} 的 #${number}「${name}」）的 Workflows 開啟 auto-add，新 Issue 才會自動加入看板`);
  }

  log('== ruleset ==');
  if (!opts.ruleset) {
    log('未加 --ruleset，不建立 ruleset。');
  } else {
    const rulesets = read(['gh', 'api', `repos/${opts.repo}/rulesets?per_page=100`], [], ' ruleset，視為沒有 ruleset');
    const same = Array.isArray(rulesets) && rulesets.find((r) => r.name === RULESET_NAME);
    if (same) log(`略過（已有同名 ruleset）：${RULESET_NAME}（id ${same.id}）`);
    else write(['gh', 'api', '--method', 'POST', `repos/${opts.repo}/rulesets`, '--input', '-'], JSON.stringify(rulesetBody(), null, 2));
    log('提醒：GitHub Free 的私人 repo 不會套用 ruleset（可以建立，但不生效）。');
    todos.push('確認 ruleset 是否生效：GitHub Free 的私人 repo 不會套用 ruleset');
  }

  log('== 需要人工處理 ==');
  if (!todos.length) log('無');
  todos.forEach((t, i) => log(`${i + 1}. ${t}`));
  if (opts.dryRun) log(`試跑結束：共 ${writes.length} 個寫入指令，未執行。`);
  return { writes, todos };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    run({
      argv: process.argv.slice(2),
      exec: (args, input) => execFileSync(args[0], args.slice(1), {
        encoding: 'utf8', input, stdio: [input === undefined ? 'ignore' : 'pipe', 'pipe', 'pipe'],
      }),
    });
  } catch (error) {
    console.error(`錯誤：${error.message.split('\n')[0]}`);
    process.exitCode = 1;
  }
}
