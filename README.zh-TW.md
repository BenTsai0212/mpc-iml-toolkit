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

第一階段（Foundation）初期。要試跑整個迴圈，請依[參考範例](#參考範例)操作。目前有：

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

## 參考範例

在一台全新的 Mac 上，從頭到尾跑一次 IML 迴圈的最小範例：在 pad 上錄幾個範例，訓練內建的
1-最近鄰模型，再即時執行。範例在 pad 1（左下角，bank A）上分三類：**rest**（不碰
pad）、**soft**（輕按並按住 pad 1）與 **hard**（重按並按住 pad 1）。模型把類別編號送到
`127.0.0.1:12000` 的 `/wek/outputs`：1 rest、2 soft、3 hard。程式在
`src/mpc_iml/demo.py`。

需要一台 MPC Sample、一條 USB 線，以及一台有終端機（Terminal.app）的 Mac。

1. 以官方安裝程式安裝 [uv](https://docs.astral.sh/uv/)，再開一個新的終端機視窗，讓
   `uv` 指令生效：

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. 取得並安裝工具包（需要時 uv 也會安裝 Python 3.12）：

   ```bash
   git clone https://github.com/BenTsai0212/mpc-iml-toolkit.git
   cd mpc-iml-toolkit
   uv sync
   ```

   macOS 若要求為 `git` 安裝命令列開發者工具，請同意，安裝完再執行一次 `git clone`。

3. 設定 MPC Sample：以 USB 接上 Mac，在 MIDI 設定中把 **MIDI Port** 設為 **USB**、
   **Pad MIDI Out** 設為 **Always**，並關閉 **Full Level**（開著時每個 velocity 都是
   127，分不出 soft 與 hard）。

4. 在另一個終端機視窗啟動接收端並保持開著。類別改變時它會印出一行：

   ```bash
   cd mpc-iml-toolkit
   uv run python -m mpc_iml.demo listen
   ```

   選用，想聽到結果時：從官網或以 `brew install --cask pd` 安裝
   [Pure Data](https://puredata.info)（vanilla；patch 以 Pd 0.54 撰寫），打開
   `examples/reference/receiver.pd` 並調高音量。soft 發出 220 Hz、hard 440 Hz，rest 無聲。
   Pd 與終端機接收端不能同時監聽 12000 埠：使用 Pd 時先以 Ctrl-C 關閉終端機接收端（或以
   `--osc-port` 讓兩者用不同的埠）。

5. 在第一個視窗錄製範例。每一類終端機會先說明要做什麼並倒數 3 秒，再錄 3 秒：**rest**
   時不碰 pad；**soft** 時在倒數結束前輕按並按住 pad 1，按到下一個提示出現為止；**hard**
   同樣做法，改成重按。

   ```bash
   uv run python -m mpc_iml.demo record examples.jsonl --no-full-level
   ```

   `--seconds` 與 `--countdown` 可調整時間。要重錄時再執行一次。

6. 訓練並即時執行。指令先以 `examples.jsonl` 訓練，再讀取 pad 直到按 Ctrl-C。輕按並按住
   pad 1，再改成重按，然後放開：接收端依序顯示 2 soft、3 hard、1 rest。

   ```bash
   uv run python -m mpc_iml.demo run examples.jsonl
   ```

沒有 MPC 時，同一個範例可以從 `tests/data/` 的錄音執行（CI 測試的就是這條重播路徑）。
依第 4 步啟動接收端，然後：

```bash
uv run python -m mpc_iml.demo run tests/data/demo_examples.jsonl --replay tests/data/demo_performance.jsonl
```

重播約 2.5 秒，依序是 soft、hard、rest。`--replay` 也可以用自己以
`python -m mpc_iml.record` 錄的檔案。找不到 MPC 時，指令會列出看得到的 MIDI 輸入埠；
`--port` 可用名稱的一部分選擇其他埠。

範例使用自己的特徵（`played_features`，32 個值：每個 pad 按住時的 velocity 與
pressure），而不是預設的 49 個值，因為預設值在放開 pad 後仍保留最後的 velocity。範例不送
`/wek/inputs`。

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
