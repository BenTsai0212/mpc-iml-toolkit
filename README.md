# dev-workflow-template

個人開發 workflow 的 template：**Claude Project 做決策、coding agent 做實作、GitHub 記錄一切。**
新專案從這裡建立；新專案初始化時會改寫本 README。

- 版本：v0.33（試驗中，私人；以[憲法](docs/workflow/constitution.md)開頭的版本為準）
- 原則與分工：[憲法](docs/workflow/constitution.md)
- Claude Project 的操作手冊：[decision-center](docs/workflow/decision-center.md)
- coding agent 的規則：[AGENTS.md](AGENTS.md)、[agent-workflow](docs/workflow/agent-workflow.md)

## 開新專案

1. 建立 repo 並 clone：`gh repo create <owner>/<name> --private --template <template repo> --clone`。
2. 在新 repo 執行 bootstrap：`node tools/workflow/bootstrap-github.mjs --repo <owner/name> --modules <群組> [--board] [--ruleset] [--lang en]`（可先加 `--dry-run`，只列出不執行；流程語言為 en 時加 `--lang en`，標籤描述與看板佔位選項改用英文）。
   - 一定會做：依 `.github/labels.yml` 建立標籤，並設定合併後自動刪分支。`--modules` 只能填 `labels.yml` 裡有的群組（`core`、`online`、`collab`、`automation`、`goal`），預設 `core`。
   - `--board`（選用）：在 owner 底下新建看板（Phase 與 Area 欄位）並連結到 repo。不加時不建看板，核心流程只靠標籤。auto-add 不是必要步驟，需要時在看板的 Workflows 開啟。
   - `--ruleset`（選用）：為預設分支建立 ruleset（禁止刪除與強制推送、必須經 PR 才能合併）。GitHub Free 的私人 repo 不會套用 ruleset。
3. 決定是否刪除 GitHub 自動產生的預設標籤（不刪也不影響流程）。
4. 建立 Claude Project：貼上 `templates/claude-project/instructions.md` 並填好專案名與 repo，連結本機資料夾，把 `templates/claude-project/handoff.md` 放進知識庫。
5. 在 Claude Project 說「依 decision-center 初始化」。
6. 選擇 code agent 的執行方式（[modules.md](docs/workflow/modules.md)）：
   - 手動（核心）：由人在 Claude Code 執行 `/work-on-issue <編號>`。
   - 本機 runner（自動化模組）：runner 依 `agent:ready` 標籤接手 Issue，見 [runner/README.md](tools/workflow/runner/README.md)。
   - 雲端執行（雲端執行模組，試驗中）：Claude Code 的雲端排程任務依標籤事件接手，不需要開著本機電腦；需要 main 的 ruleset（bootstrap 加 `--ruleset`）與 Claude GitHub App，prompt 範本在 `templates/modules/cloud/trigger-prompt.md`。

   本機 runner 與雲端執行擇一使用；兩者都沿用 `automation` 群組的標籤（bootstrap 加 `--modules core,automation`）。

完整步驟見憲法第 9 節。

## 內容

| 路徑 | 內容 |
| --- | --- |
| `docs/workflow/` | 憲法、決策中心手冊、模組、agent 工作流程、決策 agent 寫入 GitHub 的確認規則、升級 template 的程序 |
| `docs/rfcs/`、`docs/adr/` | 專案章程與決策紀錄（索引為空，新專案自行填寫） |
| `AGENTS.md`、`CLAUDE.md` | coding agent 的規則（`CLAUDE.md` 只引用 `AGENTS.md`） |
| `.claude/commands/` | `/work-on-issue`（備援模組另有 `/pm-apply`） |
| `.github/` | Issue／PR 範本、標籤定義、CI 佔位 |
| `templates/` | Claude Project 指示與交接範本、預設不啟用的模組檔案（協作、目標模式、備援、雲端執行） |

## 修改 template

依憲法第 10 節：開 Issue（`rfc`）→ PR → 合併 → 版本號加一。
