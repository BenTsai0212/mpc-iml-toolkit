# 公開前檢查清單

把 repo 從私人改為公開前，依序執行下列檢查（#100）。工具只找出位置，不修改任何東西；命中後怎麼處理、要不要公開，由人決定（見[需要人判斷的事項](#需要人判斷的事項)）。

工具的參數與輸出格式見 [tools/workflow/README.md](../../tools/workflow/README.md)。

## 執行前

- **在本機的主要工作目錄執行**：禁用名稱清單只在本機（見第 1 步），雲端 session 沒有這個檔案，在雲端執行時禁用名稱的比對會整個略過，且不會提示。
- **暫存檔放在 repo 外**：第 3、4 步的輸出檔放在家目錄等 repo 以外的位置。放在 repo 內時，第 2 步的 `check-sensitive.mjs` 會把它當成未追蹤的新檔案掃描，也可能被誤 commit。檢查完刪除。
- 先 `git fetch --all` 取得所有遠端分支：`scan-history.mjs` 與第 3、4 步只掃本機看得到的 ref。

## 1. 準備禁用名稱清單

專案名、合作者名等不能公開的名稱，由人寫在本機的 `tools/workflow/denied-names.local.txt`（格式見 [tools/workflow/README.md](../../tools/workflow/README.md#禁用名稱清單)）。清單本身已列在 `.gitignore`，內容不寫進 Issue、PR 或任何檔案。

第 2～4 步的工具都讀這份清單，所以先準備好；清單不存在時禁用名稱的比對會略過，其他檢查照常。

## 2. 目前的檔案：`check-sensitive.mjs`

```bash
node tools/workflow/check-sensitive.mjs
```

- 掃描已追蹤的檔案，加上尚未 `git add`、且沒被 `.gitignore` 排除的新檔案。
- 輸出「檔案:行號：種類」，種類是 `email`、`個人路徑` 或 `禁用名稱`；不輸出命中的內容，到該檔案的該行查看。
- 以 0 結束表示沒有命中；以 1 結束時逐項處理（改成 `user@example.com`、`/Users/<名稱>/…`、`<名稱>` 這類佔位寫法），處理後重跑到以 0 結束。

## 3. git 歷史：`scan-history.mjs`

```bash
node tools/workflow/scan-history.mjs
```

- 掃描所有 ref 可達的 commit 新增的內容（之後已刪除的也算）、檔名，以及 author 與 committer 的名稱與 email。
- 輸出「commit 前 12 碼 檔案：種類」：
  - 檔案是 `(author)`／`(committer)` 時，命中的是 commit 的作者資訊。
  - 檔案是 `<檔名已隱藏>` 時，命中的是檔名本身。
  - 要看內容時在本機執行 `git show <commit> -- <檔案>`，不要把內容貼到 Issue 或 PR。
- 第 2 步已處理的內容，在歷史中仍然看得到，這一步仍會命中。歷史中的命中只能靠改寫歷史移除，是否改寫由人決定。

## 4. `scan-history.mjs` 未涵蓋的部分

`scan-history.mjs`（#99）不掃下列內容。前三項以 git 輸出到 repo 外的暫存檔，再以 `check-sensitive.mjs --file` 檢查（不需改工具）；輸出的行號對應暫存檔，人在本機開啟暫存檔對照。

### commit 訊息

公開後 commit 訊息一樣看得到（Epic #93 的 `## 決定（補充）`）。

```bash
git log --all --format=%H%n%B > ~/commit-messages.txt
node tools/workflow/check-sensitive.mjs --file ~/commit-messages.txt
```

每個 commit 的訊息前一行是完整的 commit hash；命中的行往上找到最近的 hash，就是該 commit。`Co-Authored-By: … <noreply@…>` 這類 noreply 信箱已放行。

有附註標籤（annotated tag）時，標籤訊息也一併檢查：

```bash
git for-each-ref --format='%(refname)%0a%(contents)' refs/tags > ~/tag-messages.txt
node tools/workflow/check-sensitive.mjs --file ~/tag-messages.txt
```

### 合併 commit 自身的差異

`scan-history.mjs` 不掃合併 commit 的差異，但解決衝突時新寫的內容只在合併 commit 中。

```bash
git log --all --merges --cc -p --format=%H > ~/merge-diffs.txt
node tools/workflow/check-sensitive.mjs --file ~/merge-diffs.txt
```

暫存檔也包含各 parent 原有的行，這些內容第 3 步已列出，重複的命中可以略過。

### 純改名與新增空檔的檔名

`scan-history.mjs` 從差異中取得檔名，沒有內容差異的檔案（純改名、新增空檔）的檔名不掃。列出歷史中出現過的所有檔名：

```bash
git log --all --format= --name-only > ~/file-names.txt
node tools/workflow/check-sensitive.mjs --file ~/file-names.txt
```

找到命中的檔名後，以 `git log --all --oneline -- <檔名>` 找出相關的 commit。

### 雲端 session 沒有禁用名稱清單

清單只在本機，雲端 session 執行的檢查（例如在雲端貼出 PR 描述與留言前的 `check-post-body.mjs`）不比對禁用名稱。雲端寫進 repo 的內容，在本機執行本清單的第 2～4 步可以補上；雲端貼到 GitHub 的 Issue、PR 與留言沒有工具檢查，列在[需要人判斷的事項](#需要人判斷的事項)。

檢查完刪除第 4 步的暫存檔：

```bash
rm ~/commit-messages.txt ~/tag-messages.txt ~/merge-diffs.txt ~/file-names.txt
```

## 需要人判斷的事項

以下事項本清單只列出，不替人決定：

- **是否改寫 git 歷史**：第 3、4 步在歷史中的命中，只能靠改寫歷史移除。改寫會讓既有的 clone、fork 與 PR 的 commit 對不上，要不要改寫、怎麼改寫由人決定（#64 第 9 項）。
- **命中是否可以公開**：例如本來就公開的 email、刻意寫出的名稱。工具不區分，要人逐項判斷。
- **授權條款**：repo 目前沒有 `LICENSE`。公開時是否附授權條款、採用哪一種，由人決定。
- **GitHub 上的內容**：Issue、PR、留言、審查、Release 說明與 Wiki 在 repo 公開後一樣看得到，本 repo 沒有掃描這些內容的工具（Epic #93 範圍外）。是否檢查、怎麼檢查由人決定。
- **憲法第 10 節「公開」**：把「來源」欄改寫成不依賴私人連結的描述、移除協作者帳號（[constitution.md](constitution.md#10-演進與修憲)）。
- **公開的時機與範圍**：例如先公開 template 還是連同其他 repo、公開前是否先建立新的乾淨 repo。
