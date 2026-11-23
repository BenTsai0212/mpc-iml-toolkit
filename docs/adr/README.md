# ADR：架構決策紀錄

ADR（Architecture Decision Record）記錄「決定了什麼、為什麼、放棄了什麼」。一個決策一份，一頁以內。

## 什麼時候寫

符合任一條件就寫：

- 難以反悔（資料庫、框架、資料模型、部署平台）。
- coding agent 可能想「改正」它。
- 曾在幾個選項之間猶豫。

其他決定寫在 Issue 或 PR 即可。

## 規則

- 檔名：`NNNN-<kebab-case-title>.md`，編號遞增不重用。ADR 0001 是技術選型。
- 狀態：`Proposed` → `Accepted`／`Rejected`；被取代時改為 `Superseded by ADR NNNN`，不刪除舊檔。
- 已 `Accepted` 的 ADR 不改寫決策內容；改方向就新增一份 ADR 取代它。
- 單人專案可先以 `Proposed` 合併，隔天重看再改 `Accepted`（選用的冷卻期）。
- 以 PR 提交，不能走快速通道。

## 範本

```markdown
# ADR NNNN：標題

- 狀態：Proposed
- 日期：YYYY-MM-DD
- 相關：Issue／PR／RFC

## 背景
## 選項
## 決定
## 後果（好處、代價、後續工作）
```

## 索引

| 編號 | 決策 | 狀態 |
| --- | --- | --- |
| [0001](0001-technology-choices.md) | Technology choices, adoption method and licence | Accepted |
| [0002](0002-recording-and-osc-formats.md) | Recording format and OSC message format | Accepted |
| [0003](0003-early-publication-and-cloud-execution.md) | Early publication and cloud execution | Accepted |
| [0004](0004-engine-control-protocol.md) | Engine control protocol | Accepted |
| [0005](0005-engine-protocol-1-1-midi-learn.md) | Engine protocol 1.1: MIDI learn | Accepted |
| [0006](0006-engine-protocol-1-2-layout-and-front-ends.md) | Engine protocol 1.2: preset layout, and the shared front-end spec | Accepted |
| [0007](0007-engine-protocol-1-3-kits-modules-and-pad-selection.md) | Engine protocol 1.3: kits, modules and pad selection | Accepted |
| [0008](0008-engine-protocol-1-4-midi-clock-sync.md) | Engine protocol 1.4: MIDI clock sync | Accepted |
| [0009](0009-engine-protocol-1-5-preset-state-and-ensemble-group.md) | Engine protocol 1.5: preset state replies, and a preset group in Pure Data | Accepted |
| [0010](0010-loop-files-for-ensemble.md) | Loop files for `ensemble` | Accepted |
| [0011](0011-progression-files-for-ensemble.md) | Progression files for `ensemble` | Proposed |
