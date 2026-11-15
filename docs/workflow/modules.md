# 模組

核心每個專案都啟用；其他模組依各自的啟用時機（見各節標題與「自動化」的啟用條件）。啟用的模組記錄在 `AGENTS.md` 的專案設定。

## 如何啟用或停用

1. 開 Issue（`rfc`）說明原因。
2. 寫一份 ADR 記錄決定。
3. 以 PR 更新 `AGENTS.md` 的「啟用模組」，並加入該模組的檔案、標籤與規則。

template repo 本身的決定記在 rfc Issue，不寫 ADR：`docs/adr/` 會被複製到新專案，且 ADR 0001 保留給新專案的技術選型。從 template 建立的專案仍照上述步驟寫 ADR。（試驗中）

## 核心（每個專案）

| 類別 | 內容 |
| --- | --- |
| 文件 | RFC 0001 專案章程、輕量 ADR |
| 規則 | `AGENTS.md` 第 5 節硬規則、第 6 節先問人清單（含帳號登入、金鑰輸入、安裝系統軟體：由人處理，決策 agent 同樣不輸入帳號與金鑰） |
| 流程 | 一 Issue 一 PR、`Closes`／`Refs`、停止回報與 `## 決定`、修正模式、`plan-first`、快速通道 |
| 標籤 | `type:*`、`blocked`、`changes-requested`、`needs-human`、`rfc`、`plan-first`、`fast-lane`、`phase:*`、`area:*` |
| 防護 | 合併確認 hook、PR 描述檢查 CI |

## 協作（有第二個人，或他人使用的 agent）

| 類別 | 內容 |
| --- | --- |
| 規則 | 開工認領、分區與熱點檔案、新 Issue 需另一位負責人同意後才實作、RFC 給對方審、高風險 PR（類別見 `decision-center.md` 第 4 節）需要非作者核准、agent commit 加上 Co-Authored-By 標記 |
| 自動化工具 | 個人的自動化工具（例如 runner）不放進共用 repo，放在各自的本機、repo 之外；repo 只共用標籤與規則。要共用工具時先寫 ADR（試驗中） |
| 指標 | 只衡量流程（CI 首次通過率、停止次數等），不比較個人（試驗中） |
| 流程 | 同步會議：複製 `templates/modules/collab/sync.md` 到 `.github/ISSUE_TEMPLATE/` |
| 標籤 | `sync` |

## 上線（有正式環境或真實使用者）

| 類別 | 內容 |
| --- | --- |
| 規則 | 不碰正式資料庫與部署；合併後確認正式環境；一次合併一個；低流量時段合併 |
| 流程 | 合併前需外部設定的 PR 保持 Draft 並加 `needs-setup`；回退流程寫成文件；外部監控 |
| 標籤 | `needs-setup` |
| 防護 | CI：帶 `needs-setup` 的 PR 失敗 |

## 高風險（資料庫遷移、金流、權限、個資）

| 類別 | 內容 |
| --- | --- |
| 規則 | 每項技術選型寫 ADR；營運開關預設關閉；migration 不隨部署自動執行；不修改已套用的 migration |
| 流程 | 相關 Issue 一律 `plan-first`；高風險檔案優先細讀；CI 用真實資料庫服務測試 |
| 防護 | CI：比對已套用的 migration 是否被修改 |

## 自動化（本機 runner 依標籤接手 Issue）

runner 依 GitHub 標籤接手工作、啟動 coding agent 執行 `/work-on-issue`，並在 GitHub 回報結果；觸發與合併仍由人決定。本節是自動化模組規則的正本；操作方式見 `tools/workflow/runner/README.md`。

| 類別 | 內容 |
| --- | --- |
| 啟用條件 | 全部滿足才啟用：CI 有實際檢查（不是佔位步驟）；手動執行 `/work-on-issue` 至少 3 次；停止流程（`blocked` → `## 決定`）與修正模式（`changes-requested`）各實測一次 |
| 標籤 | `agent:ready`：可以交給 agent，由人加，或決策 agent 經人確認後加。`agent:working`：runner 處理中，由 runner 加、由 runner 移除 |
| 規則 | runner 只負責觸發與記錄，不做判斷。接工作順序：自己 PR 上的 `changes-requested` → 已有 `## 決定`（只採信可信身分寫的）的 `blocked` → `agent:ready`（最舊的先做）。同一專案一次只做一件（專案鎖），整台電腦同時執行的件數以全機名額限制（預設 2，公平輪流、做完一件就交還），在專用的 git worktree 從 `origin/main` 開始；開始時把 `agent:ready` 換成 `agent:working`，結束時移除 `agent:working`；claude 執行失敗或逾時時 runner 保存進度、自己留 `## agent 停止` 並加 `blocked`（訂閱額度用完時例外：全機冷卻到恢復時間、標籤還原，不留停止回報）；runner 準備階段的錯誤只發本機通知；同一錯誤連續 3 次且與某張 Issue 有關時，在該 Issue 留 `## runner 提醒`（不改標籤、不影響 `## 決定`） |
| 看板 | 標籤是主要依據。runner 開始時設 In progress、結束時設 Review；決策 agent 開工時核對看板與實際狀況並修正（憲法第 5 節） |
| 防護 | 規則由本模組規定，數值由各專案設定：全機名額與專案鎖（見 `tools/workflow/runner/README.md`「全機名額」，附來源與可刪條件）、`PAUSE` 檔緊急暫停；執行時段、單件時間上限，`agent:working` 長時間沒有 runner 時留言回報；sandbox 開啟，sandbox 不可用時不執行，網路只允許必要網域；禁止指令清單（合併或關閉 PR、關閉或刪除 Issue、repo／secret／release 操作、push main、強制推送、`git reset --hard`、`rm -rf`、`sudo`、`curl`、`wget`、DELETE API）；計費保護（環境中有 API key 時不執行，啟動後 `apiKeySource` 不是 `none` 就立即終止）；log 即時寫入，結尾記錄輪數、時間、token 用量 |
| runner 放置位置 | 個人專案（未啟用協作）：repo 的 `tools/workflow/runner/`，隨 template 複製、升級走 PR；個人設定（repo、帳號、worktree 路徑、看板編號）放不進版本控制的 `config.local.json`，log、lock、`PAUSE` 放不進版本控制的資料夾。多人協作（啟用協作）：放在各自的本機、repo 之外（見「協作」） |
| 已驗證 | 2026-11-07 轉為「已驗證」（#89，人決定）。轉換條件：✅ 實測合併確認 hook 在 `claude -p`（無人值守）下回傳 `ask` 時的行為（等同拒絕），並寫進 runner 說明（#24）；✅ runner 在第二個專案實際跑過（#20） |

## 雲端執行（雲端排程任務依標籤接手 Issue，試驗中）

Claude Code 的雲端排程任務在 GitHub 的標籤事件觸發時開一個雲端 session，執行 `/work-on-issue` 或修正模式；不需要開著本機電腦。與「自動化」（本機 runner）擇一使用。agent 在雲端的步驟見 [agent-workflow.md「在雲端執行時」](agent-workflow.md#在雲端執行時)。

| 類別 | 內容 |
| --- | --- |
| 啟用條件 | 全部滿足才啟用：main 有 ruleset（禁止直接推送、必須經 PR、禁止強制推送與刪除）；repo 已安裝 Claude GitHub App；同一個 repo 只用雲端或本機 runner 其中一種（記在 `AGENTS.md` 的啟用模組）；第一次使用時以 `agent:ready` 觸發、`changes-requested` 觸發各實測一次 |
| 觸發 | 建立兩個排程任務，各設一個 GitHub 事件觸發條件：一個是「Issue 加上標籤且標籤屬於 `agent:ready`」，一個是「PR 加上標籤且標籤屬於 `changes-requested`」。一個排程任務只能設一個 GitHub 事件觸發條件（另外能加的只有排程與 API 觸發），所以兩種觸發各要一個排程任務。兩個貼同一份 prompt，由 prompt 第 1 步判斷對象與標籤。Connectors 全部移除（GitHub 存取經 Claude GitHub App）〔來源：#85 的合併後實測（#87）｜可刪條件：一個排程任務可以設多個 GitHub 事件觸發條件時〕 |
| 標籤 | 沿用自動化模組的 `agent:ready`、`agent:working`（`bootstrap-github.mjs --modules automation` 建立）。開始時 `agent:ready` 換成 `agent:working`；開出 PR、停止回報或修正回報後移除 `agent:working` |
| 流程 | 把 `templates/modules/cloud/trigger-prompt.md` 填好角括號的欄位；建立上述兩個排程任務，各自貼上同一份 prompt、設定各自的觸發條件，並各自移除所有 Connectors |
| 不移植的 runner 功能 | 全機名額與額度冷卻（雲端 session 不佔本機的名額；雲端與其他 Claude 用量共用方案額度，額度用完時排程任務的執行直接以額度錯誤停止，之後由人再送訊息，不需要 runner 的冷卻）；進度保存（雲端環境會推送工作分支）；`## runner 提醒`（沒有常駐的程序累計錯誤）；看板同步（雲端不能用 GraphQL，看板由決策 agent 開工時核對）。每小時的補漏排程先不做：漏掉的觸發由決策中心開工時檢查（[decision-center.md](decision-center.md#11-雲端執行啟用時) 第 11 節） |
| 防護 | `.claude/settings.json` 的 `permissions.deny`、合併確認 hook 在雲端改為拒絕（合併類指令在所有環境都拒絕）、main 的 ruleset（[憲法第 6 節「程式化防護」](constitution.md#程式化防護)）。雲端的 hook `ask` 一律放行，所以只靠 `deny` 與 ruleset 擋 |
| 回退 | 兩個排程任務都停用，從 `AGENTS.md` 的啟用模組移除本模組；帶 `agent:working` 的 Issue 依實際狀況改回 `agent:ready` 或移除 |

## 目標模式（核准目標後由兩個 agent 推進，試驗中）

人核准一張目標卡後，決策 agent 由 PR 事件與排程喚醒，在目標範圍內審查 PR、送修正要求、派下一批子 Issue；code agent（本機 runner 或雲端執行）接手實作與修正。人只在每天的決策時段看一次決策包，以及收到即時通知時出手。

| 類別 | 內容 |
| --- | --- |
| 啟用條件 | 自動化模組或雲端執行模組其一已啟用（雲端執行不限時段、標籤加上即開始）；決策時段已決定（每天一次，時間與時區記在 `AGENTS.md` 第 0 節）；喚醒方式已決定：D1 排程任務（1 個，GitHub 事件選「所有 pull request 事件」，另加排程觸發），D2 備案（人在對話說「繼續」，一次處理累積的工作）。觸發後的分流見 [decision-center.md](decision-center.md#10-目標模式啟用時) 第 10 節。〔來源：#93 回顧、#102｜可刪條件：目標模式停用時〕 |
| 成本 | 「所有 pull request 事件」會讓每個 PR 觸發多次 session，無關事件約 20～40 秒即結束；試用時記錄觸發次數，太多時改為「PR 已開啟」與「PR 已關閉」兩個排程任務（試驗中） |
| 規則 | 模式按目標選：專案層級只決定是否啟用本模組，每個目標（Epic）各自選用，預設是協作模式（現行做法）。核准目標卡（含預定子 Issue 清單）是人唯一的大決定（③），核准後由決策 agent 加 `goal-mode`。範圍內降為 ① 的寫入見 [github-writes.md](github-writes.md#目標模式下的例外試驗中)。預算預設值：最多 5 張子 Issue、7 天、每個 PR 最多修正 2 輪（目標卡可改）。一定停下來找人的事項與喚醒時的步驟見 [decision-center.md](decision-center.md#10-目標模式啟用時) 第 10 節。暫停：人拿掉 `goal-mode`，或在對話說「切回協作」，下一次喚醒時停止推進 |
| 流程 | 複製 `templates/modules/goal/goal-card.md` 到 `.github/ISSUE_TEMPLATE/goal.md`；把 `templates/modules/goal/wake-prompt.md` 填好後貼到排程任務；`node tools/workflow/bootstrap-github.mjs --repo <owner/name> --modules goal` 建立標籤 |
| 標籤 | `goal-mode` |
| 防護 | 不能預先授權合併；合併授權只在決策中心對話，喚醒的 session 一律不合併；`## 決定`、移除 `plan-first` 維持 ③；目標範圍不得含高風險類別（[decision-center.md](decision-center.md#4-審查-pr三段式) 第 4 節），碰到時該部分轉回協作模式；可升級條件見 github-writes.md |

## 工作區（一個 Project 管同一客戶的多個 repo，試驗中）

一個 Claude Project（工作區 Project）管理同一個客戶與保密範圍內的多個 repo。未啟用時維持一個 Project 對一個 repo（[憲法第 5 節](constitution.md#5-claude-project)）。本節是工作區規則的正本；每段對話的開場、寫入範圍與開工彙整見 [decision-center.md](decision-center.md#12-工作區啟用時) 第 12 節。

| 類別 | 內容 |
| --- | --- |
| 啟用條件 | 同一客戶與保密範圍內有兩個以上 repo，由同一個決策中心管理。啟用記在登記表上每個 repo 的 `AGENTS.md` 啟用模組 |
| 分組準則 | Project 的邊界＝客戶與保密範圍。同一客戶的多個 repo 可放同一個工作區 Project；公開的 repo（例如領域模板）不和任何客戶 repo 同一個 Project；每個客戶的 fork 各自一個 Project。共用的領域經驗經 template 與 `template-feedback` Issue 流通，不靠放在同一個 Project。〔來源：#127（多個 repo 同一個 Project 時，風險都出在客戶邊界：示範頁並排而開錯、跨客戶沿用設計、知識庫放了多個客戶的提案內容，不在產品類型）｜可刪條件：不刪〕 |
| repo 登記表 | 工作區 Project 的指示中有一張表，是唯一的 repo 清單（repo 數量只看這裡）。欄位：repo、角色、客戶、可見性、建立時的 template 版本、目前憲法版本、交接文件名稱、相依的 repo。新增或移除 repo 時先改登記表。〔來源：#127（repo 數量在三份文件中寫法不同，跨 repo 的相依只記在單邊）｜可刪條件：工作區模組停用時〕 |
| 交接文件 | 分兩層。工作區交接（`templates/modules/workspace/handoff.md`）：跨 repo 的狀態、相依與合併順序、各 repo 開啟中的 `template-feedback` Issue 連結，不重複各 repo 的內容。各 repo 交接：沿用 `templates/claude-project/handoff.md`，[decision-center.md](decision-center.md#1-開工) 第 1、8 節的過時檢查與收斂規則各自適用。〔來源：#127｜可刪條件：工作區模組停用時〕 |
| 自動化 | 以 repo 為單位：雲端執行的排程任務、runner、目標卡、決策包都屬於單一 repo；工作區只負責彙整。〔來源：#127｜可刪條件：工作區模組停用時〕 |
| 流程 | 建立工作區 Project 時，把 `templates/modules/workspace/instructions.md` 填好後貼到 Project 指示，把 `templates/modules/workspace/handoff.md` 與各 repo 的交接文件放進知識庫。不包含產品型（同一產品拆成多個 repo、需要跨 repo 的合併順序）的協調規則 |
| 標籤 | 無（`bootstrap-github.mjs` 的 `--modules` 不需要加這個模組） |

## 備援（GitHub MCP 不能用時）

決策 agent 的 GitHub MCP 長期不能用，或需要 MCP 沒有對應工具的操作時啟用。MCP 能用時不需要。

| 類別 | 內容 |
| --- | --- |
| 規則 | MCP 不能用時，決策 agent 用 Claude in Chrome 讀取 GitHub，寫入逐項經人同意；Chrome 也不能用時，把操作寫成 `/pm-apply` 操作清單，由人在 Claude Code 執行並確認 `confirm` 項目（合併不在清單中，由人在 GitHub 網頁進行，#123）；完全讀不到 GitHub 時依 [decision-center.md](decision-center.md#1-開工) 第 1 節（核心）。寫入的確認等級照 [github-writes.md](github-writes.md) |
| 流程 | 複製 `templates/modules/fallback/pm-actions.md` 到 `docs/workflow/pm-actions.md`（清單格式、`auto`／`confirm` 兩表、執行規則、結果檔格式），複製 `templates/modules/fallback/pm-apply.md` 到 `.claude/commands/pm-apply.md`；清單與結果放在 `Claude outputs/pm/`（不進版本控制） |
| 標籤 | 無（`bootstrap-github.mjs` 的 `--modules` 不需要加這個模組） |
