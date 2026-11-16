[English](README.md) | 繁體中文

# mpc-iml-toolkit

用 Akai MPC Sample 與 Mac 做互動式機器學習（IML）的基礎工具包。MPC 透過 USB
作為手勢控制器（16 個 pad 的力度與 polyphonic aftertouch）與音訊介面；模型在 Mac
上執行。

工具包提供 IML 循環共用的基礎：錄製範例、訓練、即時執行，再修改範例重新訓練。
每一個 IML 實踐（一個研究問題、一首作品、一個教學單元）各有自己的 repository，
依賴固定版本的本工具包，透過擴充點替換輸入、模型與輸出，而不修改工具包本身。

核心使用 Python：以 `python-rtmidi` 讀取 MIDI 輸入，以 `scikit-learn` 建立模型，
再以 OSC 輸出到任何合成器、Max、Pure Data 或 nn~。專案章程見
[RFC 0001](docs/rfcs/0001-project-charter.md)，技術選型見
[ADR 0001](docs/adr/0001-technology-choices.md)（兩者皆為英文）。

## 目前狀態

第一階段（Foundation）初期。目前只有套件骨架與開發環境設定，尚無工具包功能，
套件也尚未發布。第一個版本（`v0.1.0`）之前，介面可能隨時變動。

## 開發

需要 [uv](https://docs.astral.sh/uv/)（必要時會自動安裝 Python 3.12），以及執行
workflow 工具測試用的 Node.js 22。

```bash
uv sync --locked
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

標記 `@pytest.mark.hardware` 的測試需要接上 MPC Sample，預設略過。接上 MPC 後執行：

```bash
uv run pytest -m hardware
```

CI（`.github/workflows/ci.yml` 的 `checks` job）先執行 workflow 工具測試
（`npm test --prefix tools/workflow`），再依序執行上列指令。

## 專案流程

工作在 GitHub Issue 中規劃，由 coding agent 以 pull request 實作，再由人審查與合併。
agent 的規則見 [AGENTS.md](AGENTS.md)。[`docs/workflow/`](docs/workflow/) 底下的
workflow 文件與 `AGENTS.md` 以繁體中文撰寫；Issue、pull request 與 commit 使用英文。

## 授權

[MIT](LICENSE)。RAVE、nn~ 等選用擴充有各自的授權（CC BY-NC 4.0，僅限非商業用途），
工具包不會內含或要求安裝它們。
