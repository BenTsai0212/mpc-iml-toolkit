# workflow 工具

開發流程用的 Node 工具，無相依套件（`package.json` 只為了 `npm test`）。指令清單見 [AGENTS.md](../../AGENTS.md) 第 2 節；本文件是各工具的參數與說明。

## 測試

`npm test --prefix tools/workflow` 以 Node 內建的 `node --test` 執行本資料夾（含 `hooks/`、`runner/`）所有 `*.test.mjs`。CI 的 `checks` job 也會執行。

除了各工具的單元測試，還會檢查 repo 內的文件：

| 測試 | 檢查 |
| --- | --- |
| `doc-commands.test.mjs` | Markdown 的 shell 程式碼區塊不加 `#` 註解（`AGENTS.md` 第 7 節）；`docs/workflow/upgrade.md` 的 shell 指令不含 `$(...)`、shell 變數與 `diff -` |
| `doc-rules.test.mjs` | 每項規則只留一份正本、文件與非測試的 `.mjs` 不出現 gh 的 Issue／PR `view` 子命令、備援模組的檔案只在 `templates/modules/fallback/`、相對連結與 `#錨點` 都指向存在的檔案與標題、`AGENTS.md` 不超過 80 行（憲法第 6 節「加上專案內容後 60～80 行」） |
| `check-sensitive.test.mjs` | repo 內已追蹤與未追蹤的新檔案沒有 email、個人路徑或禁用名稱 |

## 各工具

| 檔案 | 用途 |
| --- | --- |
| `bootstrap-github.mjs` | 新 repo 的標籤與看板 |
| `check-pr-body.mjs` | PR 描述要連到 Issue（CI） |
| `check-post-body.mjs` | agent 與決策中心貼出 PR 描述與留言前的檢查 |
| `headings.mjs` | 控制標題中英文對照表的正本，其他工具從這裡讀取（BenTsai0212/dev-workflow-template#129）；文件見 [docs/workflow/headings.md](../../docs/workflow/headings.md) |
| `check-sensitive.mjs` | 檔案中的 email、個人路徑與禁用名稱 |
| `scan-history.mjs` | git 歷史中的 email、個人路徑與禁用名稱（唯讀，只輸出報告） |
| `read-trusted.mjs` | 讀取 Issue 與 PR，只輸出可信身分的內容 |
| `harness-retro.mjs` | harness 指標（只讀），解讀用 `/harness-retro` |
| `hooks/confirm-main.mjs` | 合併與 push 到 main 的 hook（`.claude/settings.json` 的 `PreToolUse` 註冊）；合併類指令（`gh pr merge`、`gh api` 合併）在所有環境直接拒絕（deny，BenTsai0212/dev-workflow-template#123）；push 到 main 本機跳出確認（ask），雲端 session（`CLAUDE_CODE_REMOTE` 為 `true`）直接拒絕（deny），因為雲端的 ask 一律放行 |
| `runner/` | 自動化模組的 agent runner，見 [runner/README.md](runner/README.md) |

### bootstrap-github.mjs

```bash
node tools/workflow/bootstrap-github.mjs --repo <owner/name> [--modules core,online,collab,automation,goal] [--board] [--ruleset] [--lang zh-TW|en] [--dry-run]
```

- 依 `.github/labels.yml` 建立已啟用模組的標籤，並設定合併後自動刪分支（等同 `gh repo edit <owner/name> --delete-branch-on-merge`）；憲法第 9 節 B 段。
- `--modules` 預設只有 `core`。模組名稱對應 `docs/workflow/modules.md`：`core` 是核心、`online` 是上線、`collab` 是協作、`automation` 是自動化、`goal` 是目標模式。備援模組沒有標籤，不需要加；雲端執行模組沿用 `automation` 的標籤。
- `--board`（選用）：在 repo 的 owner 底下新建標題為 repo 名稱的看板，建立 Phase 與 Area 兩個單選欄位（各含佔位選項「未設定」），並 `gh project link` 到 repo。已有同名看板時不新建，只補缺少的欄位。auto-add 不是必要步驟，只列在待辦。不加時不建看板，核心流程只靠標籤。
- `--ruleset`（選用）：以 GitHub API 為預設分支建立名為 `protect-default-branch` 的 ruleset：禁止刪除、禁止強制推送、必須經 PR 才能合併（required approvals 0）。已有同名 ruleset 時不重複建立。GitHub Free 的私人 repo 不會套用 ruleset。
- `--dry-run` 只列出將執行的 `gh` 指令（含 ruleset 的請求內容）；仍會讀取現有標籤、看板與 ruleset，不做任何寫入。
- 不需要設定檔，也不複製範本看板。

### check-pr-body.mjs

```bash
PR_BODY='Closes #1' PR_LABELS='[]' node tools/workflow/check-pr-body.mjs
```

- PR 描述要有 `Closes #N` 或 `Refs #N`（GitHub 的 close／fix／resolve 關鍵字也算）；帶 `fast-lane` 標籤的 PR 除外。
- HTML 註解與程式碼中的關鍵字不算。
- CI 的 `PR body` workflow（`.github/workflows/pr-body.yml`）在 PR 開啟、編輯、更新與標籤變更時執行；本文與標籤只經環境變數傳入。

### check-post-body.mjs

```bash
node tools/workflow/check-post-body.mjs --issue N --kind <種類> <檔案>
```

- 以 `gh … --body-file` 貼出 PR 描述或留言前執行，通過後以同一個檔案貼出。
- 種類與各自的要求見 `docs/workflow/agent-workflow.md`「貼出 PR 描述與留言」：`pr`、`plan`、`stop`、`fix`、`todo`，以及決策中心用的 `decision`、`change-request`（`docs/workflow/decision-center.md` 第 5 節）。
- 控制標題依 repo 的流程語言檢查（`AGENTS.md` 第 0 節「流程語言」，沒有時是 `zh-TW`）：開頭是另一種語言的標題時，說明應改寫成哪一個。`--lang zh-TW|en` 可覆寫。對照表見 [docs/workflow/headings.md](../../docs/workflow/headings.md)。
- 所有種類都檢查 email、個人路徑與禁用名稱（規則與 `check-sensitive.mjs` 共用），只輸出行號與種類。
- runner 執行時（有 `RUNNER_RUN_TMP`）另檢查檔案位置與修改時間，並且不接受標準輸入。
- 通過時以 0 結束，不通過時以 1 結束。

### check-sensitive.mjs

```bash
node tools/workflow/check-sensitive.mjs [--file <檔案>]
```

- 沒有參數時掃描已追蹤的文字檔（`git ls-files`），加上尚未 `git add`、且沒被 `.gitignore` 排除的新檔案（`git ls-files --others --exclude-standard`）；`--file` 只檢查一個檔案，例如決策中心送出 Issue 或留言前的自我檢查。
- 找出不在放行規則內的 email，以及 `/Users/<名稱>`、`/home/<名稱>` 形式的個人路徑（`/home/runner` 與角括號佔位不算）。
- email 的放行規則：`noreply@…`、`git@<主機>`、`*.noreply.github.com`、`example.com`／`.org`／`.net`、保留頂級網域。
- 另外比對[禁用名稱清單](#禁用名稱清單)。
- 公開 repo 前的檢查順序與解讀見[公開前檢查清單](../../docs/workflow/pre-publish-checklist.md)。
- 輸出只有檔案、行號與種類，不輸出命中的內容。
- 通過時以 0 結束，有命中時以 1 結束，參數錯誤時以 2 結束。

### scan-history.mjs

```bash
node tools/workflow/scan-history.mjs
```

- 公開 repo 前，找出 git 歷史中曾經寫入的 email、個人路徑與禁用名稱（BenTsai0212/dev-workflow-template#98）。在 repo 內執行，不接受參數。
- 不掃 commit 訊息、合併 commit 本身的差異、純改名與新增空檔的檔名；這些部分的檢查方式見[公開前檢查清單](../../docs/workflow/pre-publish-checklist.md)。
- 掃描所有 ref（`git log --all`：分支、標籤、遠端分支等）可達的 commit：每個 commit 新增的內容（之後已刪除的也算）、檔名，以及 author 與 committer 的名稱與 email。合併 commit 本身的差異不掃（內容已在各 parent 的 commit 中）。
- 規則與 `check-sensitive.mjs` 相同（匯入同一套規則，含[禁用名稱清單](#禁用名稱清單)）。
- 輸出只有 commit（前 12 碼）、檔案與種類，同一個 commit、檔案與種類合併成一行並註明處數；author／committer 寫成 `(author)`／`(committer)`，檔名本身命中時寫成 `<檔名已隱藏>`。不輸出命中的內容、email 或名稱。
- 唯讀：只執行 `git log`（設定 `GIT_OPTIONAL_LOCKS=0`），不改寫歷史、不修改工作區與 index。是否改寫歷史由人決定。
- 沒有命中時以 0 結束，有命中時以 1 結束，git 失敗（例如不在 repo 中）或參數錯誤時以 2 結束。

### 禁用名稱清單

專案名、合作者名等不寫進檔案、PR 描述與留言的名稱，`check-sensitive.mjs` 與 `check-post-body.mjs` 命中時擋下，種類是「禁用名稱」（BenTsai0212/dev-workflow-template#96）；`scan-history.mjs` 也比對。

- 路徑：主要工作目錄的 `tools/workflow/denied-names.local.txt`，已列在 `.gitignore`，不進版本控制。runner 在另一個 worktree 執行時也讀主要工作目錄的這個檔案。
- 格式：UTF-8 文字檔，一行一個名稱；前後空白不算，空行與 `#` 開頭的行略過。
- 比對：不分大小寫，以子字串比對（名稱出現在一行中的任何位置都算）。
- 檔案不存在時略過，其他檢查照常。
- 輸出只有位置與種類，不印出名稱與該行內容；清單的內容由人在本機建立，不寫進 Issue、PR 或任何檔案。
- 測試以環境變數 `WORKFLOW_DENIED_NAMES_FILE` 指定暫存清單檔，不讀寫真實清單。

### read-trusted.mjs

```bash
node tools/workflow/read-trusted.mjs --issue N | --pr N [-R <owner/name>]
```

- agent 讀 Issue 與 PR 的唯一方式（`docs/workflow/agent-workflow.md` 第 0 步）。只以 `gh api`（REST）讀取，不用 GraphQL；留言、審查、行內審查意見以 `--paginate` 讀取所有頁。
- 輸出 JSON：`issue`／`pr`（標題、本文、標籤、作者與 `authorAssociation`、`trusted`；PR 另有 `headRefName`、`baseRefName`、`isDraft`），以及 `comments`、`reviews`（PR）、`reviewComments`（PR）、`skipped`、`notices`。
- 只輸出可信身分寫的項目；其他人寫的、缺少身分欄位的只計入 `skipped` 的筆數，不輸出內容。
- Issue 或 PR 的作者不可信時，標題與本文為 `null`，`notices` 提示依「外部 Issue」停止。
- 未指定 `-R` 時用目前目錄的 repo。成功時以 0 結束，讀取失敗時以 1 結束，參數錯誤時以 2 結束。
- 測試（`read-trusted.test.mjs`）只用假資料，不連網。

### harness-retro.mjs

```bash
node tools/workflow/harness-retro.mjs --since <YYYY-MM-DD> [--until <YYYY-MM-DD>] [--repo <owner/name>] [--decider <帳號>]
```

- 計算期間內的 harness 指標，輸出 Markdown 表格；每項指標附算法與限制。指標的用途見憲法第 10 節。
- `--until` 預設是今天；期間以 UTC 計，包含 `--until` 當天。未指定 `--repo` 時用目前目錄的 origin。
- 只以 `gh api` 讀取，不寫入 GitHub；遇到速率限制時等 60 秒重試，3 次仍失敗就說明原因並以 1 結束。參數錯誤時以 2 結束。
- 指標：
  - PR 數（已合併、開啟中、關閉未合併）。
  - 曾被要求修正的 PR 與輪數（Issue events 的 `labeled: changes-requested`）。
  - agent 停止的次數與原因。
  - CI 首次通過率。
  - 人的介入（`## 修正要求` 留言）。
  - 等待人的工作。
  - 規則文件（`AGENTS.md`、`docs/workflow/`）的修改次數。
- 「注意力」段（BenTsai0212/dev-workflow-template#113）：
  - agent @ 決定者：期間內 agent 的 Issue／PR 留言中 @ 決定者的則數（一則 @ 多次算一次），依天（UTC）分列並給平均每天則數（除以期間天數，含沒有 @ 的天與 `--until` 當天）。決策包（`## 決策包` 開頭）另外列出，並給扣除後的則數與平均。
  - 決定者：`--decider <帳號>`；未指定時讀目標 repo 預設分支 `AGENTS.md` 第 0 節的「決定者：@帳號」，讀不到時這項顯示「—」並說明。報告只寫帳號名稱、不寫 `@帳號`，貼到 GitHub 時不會通知決定者。
  - agent 的留言：agent 與人可能共用帳號，所以不看作者，而看內容：含 `Generated by [Claude Code]` 頁尾，或以 agent 的標題開頭（`## agent 停止`、`## 計畫`、`## 修正回報`、`## 合併後待辦`、`## 修正要求`、`## 決策包`、`## 目標進度`、`## 即時通知`）。以 `## 決定`、`## 合併授權` 開頭的留言即使由決策 agent 代送（帶頁尾）也不算。程式碼區塊與行內程式碼中的 @ 不算（GitHub 不會通知）。
  - `## 決定`、`## 合併授權`：期間內以該標題開頭的留言則數，不分帳號。
- 限制：
  - agent 與人共用帳號時，只能依留言標題（與 Claude Code 頁尾）判斷誰寫的；本機 agent 以 `gh` 貼出、沒有頁尾也不以上述標題開頭的留言，不算 agent 的留言。
  - PR 審查（review）的內文不計。
  - 「等待人的工作」是執行當下的狀態，不是期間結束時。
  - CI 的 run 依分支名稱與 PR 開啟期間對應到 PR；GitHub 對篩選後的 workflow run 清單最多回傳 1000 筆。
- 計算邏輯是純函式，測試（`harness-retro.test.mjs`）只用假資料，不連網。
