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

第一階段（Foundation）初期。目前有：

- 依 Wekinator 預設的 OSC sender（`mpc_iml.osc`；`/wek/inputs` 送到 6448 埠、
  `/wek/outputs` 送到 12000 埠）；
- MIDI 訊息與範例標記的事件型別（`mpc_iml.events`）；
- 以 JSON Lines 讀寫錄音（`mpc_iml.recording`）；
- 由事件計算 frame，每個 frame 產生 49 個 OSC 輸入值（`mpc_iml.frames`）；
- 事件來源（`mpc_iml.sources`）：以 `python-rtmidi` 讀取 MPC 的即時 MIDI 輸入，以及
  重播錄音，兩者對下游可互換；MIDI 解碼在 `mpc_iml.midi`；
- 即時輸入的錄音工具：

  ```bash
  uv run python -m mpc_iml.record out.jsonl --duration 5 --firmware 1.3.0 --no-full-level
  ```

  不加 `--duration` 時錄到按 Ctrl-C 為止。
- 由錄音中 `example_start`／`example_end` 區段建立訓練範例，類別編號固定不變
  （`mpc_iml.examples`）；
- 模型擴充點（`mpc_iml.model.Model`：`fit` 與 `predict`）與內建的 scikit-learn
  模型：1 近鄰分類器與 MLP 迴歸器（`mpc_iml.sklearn_backend`）；
- IML 迴圈（`mpc_iml.loop.IMLLoop`）：以範例訓練，再讓事件來源經過 frame 與模型執行，
  把特徵送到 `/wek/inputs`、預測送到 `/wek/outputs`。可以修改範例並重新訓練，不必
  重新啟動。`model_factory=None` 時關閉內建後端，只送 `/wek/inputs`，由 Wekinator
  擔任模型：

  ```python
  from mpc_iml.loop import IMLLoop
  from mpc_iml.osc import inputs_sender, outputs_sender
  from mpc_iml.recording import read_recording
  from mpc_iml.sklearn_backend import Classifier

  loop = IMLLoop(Classifier, inputs=inputs_sender(), outputs=outputs_sender())
  loop.examples.add_recording("examples.jsonl")
  loop.train()
  loop.run(read_recording("performance.jsonl").events)
  ```

  錄音的事件以最快速度執行。即時來源（`LiveSource` 或
  `ReplaySource(..., realtime=True)`）依來源的時鐘執行：不論有沒有 MIDI，每
  1 / rate 秒產生一個 frame（100 Hz 時是 10 ms），所以按住不動的 pad 也會持續送出。
  某一步花的時間超過一個 frame 間隔時，丟棄遲到的 frame：下一個 frame 是已到時間的
  最新一個，包含其時間之前的所有事件；`loop.dropped_frames` 記錄略過的 frame 數。
  以 `duration` 與 `stop` 結束執行：

  ```python
  from mpc_iml.sources import LiveSource

  with LiveSource() as source:
      loop.run(source, duration=60)
  ```

  不經過迴圈時，`mpc_iml.frames.realtime_frames` 產生相同的即時 frame。

格式見 [ADR 0002](docs/adr/0002-recording-and-osc-formats.md)。套件尚未發布。
第一個版本（`v0.1.0`）之前，介面可能隨時變動。

## 建立練習 repo

`python -m mpc_iml.new` 建立一個以相依套件使用本工具包、而不複製其程式碼的專案：
`pyproject.toml` 把 `mpc-iml-toolkit` 固定在執行中版本的 git tag，另有待替換的空模型
（`src/<package>/model.py`）、以錄音訓練並在重播上執行的程式、測試、範例錄音與簡短的
README。套件名稱取自資料夾名稱（可用 `--name` 指定）。

```bash
uv run python -m mpc_iml.new ../my-practice
```

目前還沒有 tag：版本是 `0.0.0`，在第一個版本加上 tag 之前，`v0.0.0` 的固定版本無法安裝。
在那之前，請在新專案中以 `uv add --editable <mpc-iml-toolkit 的路徑>` 改指向本機的
checkout，再執行 `uv sync`。

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
