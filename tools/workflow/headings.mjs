// 控制標題對照表（BenTsai0212/dev-workflow-template#129）：流程靠留言開頭的固定標題運作，這裡是中英文標題的唯一正本。
// 工具（check-post-body.mjs、runner、harness-retro.mjs）都從這裡讀取；判斷時兩種語言等價，
// 要寫哪一種由 repo 的流程語言（AGENTS.md 第 0 節「流程語言：zh-TW | en」，預設 zh-TW）決定。
// 文件的對照表在 docs/workflow/headings.md，由 headings.test.mjs 確認與本檔一致。

export const LANGS = ['zh-TW', 'en'];
export const DEFAULT_LANG = 'zh-TW';

// 每個控制標題：[zh-TW, en]。括號說明的規則兩種語言相同，例如「## 決定（補充）」「## Decision (addendum)」。
const TABLE = {
  plan: ['## 計畫', '## Plan'],
  stop: ['## agent 停止', '## Agent stopped'],
  fix: ['## 修正回報', '## Fix report'],
  todo: ['## 合併後待辦', '## Post-merge tasks'],
  decision: ['## 決定', '## Decision'],
  changeRequest: ['## 修正要求', '## Change request'],
  mergeAuth: ['## 合併授權', '## Merge authorization'],
  decisionPack: ['## 決策包', '## Decisions needed'],
  goalProgress: ['## 目標進度', '## Goal progress'],
  alert: ['## 即時通知', '## Alert'],
  start: ['## 開工', '## Started'],
  runnerReminder: ['## runner 提醒', '## Runner reminder'],
  postReview: ['## 事後審查紀錄', '## Post-merge review'],
};

/** { key: { 'zh-TW': '## …', en: '## …' } } */
export const HEADINGS = Object.freeze(Object.fromEntries(
  Object.entries(TABLE).map(([key, [zh, en]]) => [key, Object.freeze({ 'zh-TW': zh, en })]),
));

/** 某個標題在指定語言的寫法；lang 不認得時用預設語言。 */
export const heading = (key, lang = DEFAULT_LANG) => HEADINGS[key][LANGS.includes(lang) ? lang : DEFAULT_LANG];

/** 某個標題的所有寫法（中文在前）。 */
export const allHeadings = (key) => LANGS.map((lang) => HEADINGS[key][lang]);

/**
 * 文字（去掉開頭空白）是否以 h 開頭。
 * 以英文字母結尾的標題，後面不能緊接英文字母、數字或連字號：「## Decision」不算「## Decisions needed」的開頭。
 * 中文標題沿用原本的 startsWith（行為不變）。
 */
export function startsWithHeading(text, h) {
  const s = String(text ?? '').trimStart();
  if (!s.startsWith(h)) return false;
  if (!/[A-Za-z]$/.test(h)) return true;
  return !/^[A-Za-z0-9-]/.test(s.slice(h.length));
}

/** 文字開頭是哪一種語言的 key 標題；都不是時回傳 null。 */
export function headingLang(text, key) {
  return LANGS.find((lang) => startsWithHeading(text, HEADINGS[key][lang])) ?? null;
}

/** 文字是否以 key 標題（任一種語言）開頭。 */
export const startsWithAny = (text, key) => headingLang(text, key) !== null;

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** 第一行正好是 key 標題，可接括號說明（全形或半形），例如「## 決定（補充）」「## Decision (addendum)」。 */
export function headingLineRe(key, lang) {
  const langs = lang ? [lang] : LANGS;
  const alts = langs.map((l) => escapeRe(HEADINGS[key][l])).join('|');
  return new RegExp(`^(?:${alts})(?:\\s*[（(][^）)\\n]*[）)])?\\s*$`);
}

/** 去掉第一行開頭的 key 標題與其後的冒號，回傳其餘文字（例如停止回報的原因）。 */
export function afterHeading(line, key) {
  const lang = headingLang(line, key);
  if (!lang) return String(line ?? '');
  return String(line).trimStart().slice(HEADINGS[key][lang].length).replace(/^\s*[：:]\s*/, '').trim();
}

/**
 * 從 AGENTS.md 的內容讀出流程語言（第 0 節「- 流程語言：zh-TW | en」）。
 * 沒有這一行時是預設語言；值不認得時 error 說明原因，lang 仍回傳預設語言。
 */
export function processLang(agentsText) {
  const m = /^-\s*流程語言[：:]\s*[`*]*([A-Za-z0-9-]*)/m.exec(String(agentsText ?? ''));
  if (!m) return { lang: DEFAULT_LANG, error: null };
  const value = m[1];
  if (LANGS.includes(value)) return { lang: value, error: null };
  return { lang: DEFAULT_LANG, error: `AGENTS.md 的流程語言「${value}」不是 ${LANGS.join('、')} 之一` };
}
