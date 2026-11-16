# 控制標題對照表

流程靠留言與貼文開頭的固定標題運作（例如人的決定是 `## 決定` 開頭的留言）。每個控制標題有中文與英文兩種寫法：

- **工具兩種都認得**：`check-post-body.mjs`、runner、`harness-retro.mjs` 判斷時中英文標題等價。
- **要寫哪一種由流程語言決定**：`AGENTS.md` 第 0 節的「流程語言：zh-TW | en」（沒有這一行時是 zh-TW）。`check-post-body.mjs` 只接受流程語言的那一種，另一種會說明應改寫成什麼。
- **括號說明的規則兩種語言相同**：例如 `## 決定（補充）`、`## Decision (addendum)`；全形與半形括號都可以。
- **英文標題的邊界**：以英文字母結尾的標題，後面不能緊接英文字母、數字或連字號，所以 `## Decisions needed` 不算 `## Decision`。

流程語言為 en 時：bootstrap 加 `--lang en`，第一個 PR 以 `templates/i18n/en/github/` 的英文範本（PR 範本、Issue 範本、`labels.yml`）覆蓋 `.github/`（憲法第 9 節 B 段第 2 步、C 段第 4 步）；停止回報的英文欄位見 [agent-workflow.md「停止時的回報」](agent-workflow.md#停止時的回報)，runner 自己貼出的停止回報與提醒也跟隨流程語言。

程式的正本是 [`tools/workflow/headings.mjs`](../../tools/workflow/headings.mjs)；下表由 `headings.test.mjs` 確認與它一致，修改時兩邊一起改。

| key | zh-TW | en | 用途 |
| --- | --- | --- | --- |
| `plan` | `## 計畫` | `## Plan` | `plan-first` 的計畫（agent-workflow 第 2 步） |
| `stop` | `## agent 停止` | `## Agent stopped` | 停止時的回報 |
| `fix` | `## 修正回報` | `## Fix report` | 修正模式的回報 |
| `todo` | `## 合併後待辦` | `## Post-merge tasks` | 人工待辦（agent-workflow 第 8 步） |
| `decision` | `## 決定` | `## Decision` | 人的決定 |
| `changeRequest` | `## 修正要求` | `## Change request` | 決策中心的修正要求 |
| `mergeAuth` | `## 合併授權` | `## Merge authorization` | 人授權決策中心合併 |
| `decisionPack` | `## 決策包` | `## Decisions needed` | 目標模式的決策包 |
| `goalProgress` | `## 目標進度` | `## Goal progress` | 目標模式的進度 |
| `alert` | `## 即時通知` | `## Alert` | 目標模式的即時通知 |
| `start` | `## 開工` | `## Started` | 雲端 code agent 的開工留言（`## 開工（#N）`／`## Started (#N)`） |
| `runnerReminder` | `## runner 提醒` | `## Runner reminder` | runner 的錯誤提醒 |
| `postReview` | `## 事後審查紀錄` | `## Post-merge review` | 決策中心的事後審查紀錄 |

〔來源：BenTsai0212/dev-workflow-template#129（要公開給英語社群的專案，Issue／PR 需全英文）｜可刪條件：不刪〕
