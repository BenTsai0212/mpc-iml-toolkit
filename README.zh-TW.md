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

`v0.1.0` 是第一個版本（見英文的 [changelog](CHANGELOG.md)）；0.x 期間介面仍可能變動。
第一階段（Foundation）。要試跑整個迴圈，請依[參考範例](#參考範例)操作。目前有：

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
   同樣做法，改成重按。soft 與 hard 要明顯不同，例如用指尖輕觸與用整根手指用力按。終端機顯示
   「Release pad 1 now.」時，在下一次倒數前放開 pad。

   ```bash
   uv run python -m mpc_iml.demo record examples.jsonl --no-full-level
   ```

   錄製時接收端不會有反應：要到第 6 步（`demo run`）才會反應。`--seconds` 與
   `--countdown` 可調整時間。要重錄時再執行一次。

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

範例使用特徵集 `mpc_iml.examples.played_features`（32 個值：每個 pad 按住時的
velocity，放開時為 0，接著是 pressure），而不是預設的 49 個值，因為預設值在放開 pad 後仍保留
最後的 velocity。範例不送 `/wek/inputs`。

### 演奏用的特徵集

預設特徵（`mpc_iml.examples.default_features`）是 ADR 0002 的 49 個 `/wek/inputs` 值。
它們在 `Note Off` 後仍保留 pad 最後的 velocity，所以剛演奏完的「休息」frame 看起來像最後
一次敲擊，以它訓練的模型可能回答最後的聲音而不是休息。要在演奏中即時反應的模型，請使用
`played_features`：放開的 pad 為 0，所以剛演奏完的休息就是休息。在接受特徵的地方傳入，
例如 `ExampleSet(features=played_features)` 或 preset 的 `features=`。preset `demo`
使用它；49 個 `/wek/inputs` 值不變。

只靠 pressure 演奏的樂器可以用 `pressure_features`（16 個值：每個 pad 的 pressure，0-1）。
它不含 velocity 與按住旗標，所以按下 pad 後，在 MPC 回報 pressure 之前輸入不變，輸入從 0
開始上升。preset `pressure` 使用它。

## 執行 engine

engine 是長時間執行的 IML 迴圈，由前端（Pure Data、Max，之後是 app）以 OSC 控制訊息驅動；
協定見 [ADR 0004](docs/adr/0004-engine-control-protocol.md)，1.1 版見
[ADR 0005](docs/adr/0005-engine-protocol-1-1-midi-learn.md)。依[參考範例](#參考範例)接好
MPC 後，指定一個存放範例集的資料夾來啟動：

```bash
uv run python -m mpc_iml.engine my-data
```

engine 在 `127.0.0.1:6450` 接收控制訊息，把回覆與狀態回報送到 `127.0.0.1:6451`，以
preset `demo` 啟動（`--preset` 指定其他 preset）。執行中會把 preset 的特徵送到
`/wek/inputs`（6448 埠），模型輸出送到 preset 的輸出（`demo` 是 12000 埠的
`/wek/outputs`）。`--control-port`、`--reply-port`、`--inputs-port`、`--outputs-port`
可改埠號。沒有 MPC 時，`--replay <錄音>` 改為以實際速度播放一次錄音：

```bash
uv run python -m mpc_iml.engine my-data --replay tests/fixtures/recordings/hold-pressure.jsonl
```

前端的操作流程例如：`/mpciml/hello 1`（engine 回覆版本與完整狀態；版本與回覆埠等整數參數
也接受值為整數的 float，例如 `1.0`，所以 Pure Data 不設型別標記的一般訊息也能用）、
`/mpciml/class soft`、`/mpciml/record/start`、演奏、`/mpciml/record/stop`，接著
`/mpciml/train`、`/mpciml/run`、`/mpciml/stop`。`/mpciml/examples/save <名稱>` 寫入
`my-data/<名稱>.jsonl`（ADR 0002 格式的錄音）；engine 不會寫入這個資料夾以外的地方。每個
訊息都會得到回覆、狀態回報或 `/mpciml/error`。有 MIDI 輸出的 preset，在 `idle` 或 `training`
時送 `/mpciml/midi/learn <輸出>`（1 是第一個 controller），engine 只在該 controller 送出一段
短的掃動讓 DAW 學習，並回覆 `/mpciml/midi/sent <輸出> <controller>`。按 Ctrl-C 停止 engine：關閉輸入與 socket，
進行中的訓練會先完成。

## 演奏 preset pressure

內建的 preset `pressure`（`src/mpc_iml/pressure.py`，[RFC 0002](docs/rfcs/0002-platform-positioning.md)
的情境 1）把 pad 的 pressure 同時對應到 8 個合成參數。示範幾個手勢，每個手勢附上
應該產生的 8 個值，模型就學會其間的對應（一對多迴歸，內建的 MLP）。它使用
`pressure_features`，所以敲擊的 velocity 沒有作用。執行中會送出：

- 8 個 float 的 `/wek/outputs` 到 `127.0.0.1:12000`，給 Pure Data 或任何 OSC 接收端（不縮放：
  通常是 0-1，偶爾稍微超出）；
- channel 1 的 MIDI control change 20-27（輸出 1 是 CC 20，輸出 8 是 CC 27），從 0-1 縮放到
  0-127，送到名為 `mpc-iml` 的虛擬 MIDI port，給 DAW 的合成器。CC 只在值改變時送出，
  `running` 以外不送。

需要[參考範例](#參考範例)的準備（第 1～3 步），以及前端用的
[Pure Data](https://puredata.info)（vanilla 0.54 或更新版本）。

1. 以這個 preset 啟動 engine，視窗保持開啟：

   ```bash
   uv run python -m mpc_iml.engine my-data --preset pressure
   ```

   在 macOS 上，`mpc-iml` 這個 port 會出現在每個 MIDI app 的輸入中。若要改用 IAC bus，
   在 Audio MIDI Setup（音訊 MIDI 設定）開啟它（Window > Show MIDI Studio，按兩下 IAC Driver，
   勾選 Device is online），
   並加上 `--midi-port IAC`。MIDI port 無法開啟時，engine 會說明原因並繼續送 OSC。

2. 在 Pure Data 開啟前端 `src/mpc_iml/patches/pressure.pd`。它會向 engine 送 `hello` 並載入
   preset；狀態欄顯示 `idle`，Pd 視窗印出每個回覆（`mpc-iml: …`）。若在 patch 之後才啟動
   engine，再按一次 `hello`。

3. 錄幾個範例。每個範例：把左邊 8 個目標滑桿 `t1`-`t8`（0-1）設成想要的聲音，在 pad 上
   保持手勢，按 `record`（先送出目標值，再開始錄音），持續約兩秒，按 `stop_recording`。
   先錄休息（不碰 pad，目標值設成無聲），再錄例如輕按 pad 1 與重按 pad 1，各自設定目標值。
   多個 pad 與其他力道的做法相同。若要讓輕觸的一端連續，另外錄一個能保持的最輕觸碰（手指
   放在 pad 1 上幾乎不施力），目標值接近休息，讓模型把最輕的 pressure 對應到休息附近。

4. 按 `train`。狀態變成 `training` 再回到 `idle`，`trained` 顯示 1。按 `run` 並演奏：右邊
   的 `o1`-`o8` 滑桿跟著模型變化，MIDI CC 也跟著送出。`stop` 結束執行。`save` 與 `load`
   把範例存在 `my-data/pressure-examples.jsonl`。

patch 在 12000 埠接收 `/wek/outputs` 來顯示，而一個埠只能由一個程式接收。若要以 OSC 驅動
Pd 合成器，以 `--outputs-port <埠>` 啟動 engine，讓合成器接收該埠（patch 的輸出滑桿此時
不動），或關閉這個 patch，改從自己的 patch 送控制訊息。

### 在 DAW 對應 MIDI CC

`mpc-iml` 只送 channel 1 的 CC 20-27，不送音符；讓合成器發聲的音符來自 MPC Sample 本身。
這個 port 只在 engine 執行時存在，所以先啟動 engine，再開啟 DAW 的 MIDI 設定。為輸入
`mpc-iml`（或 IAC bus）開啟遠端控制，再把 channel 1 的 CC 20-27 對應到合成器參數：

- **Ableton Live**：在 Settings > Tempo & MIDI 的 Input Ports 表格中，為 MPC Sample 開啟
  **Track**，為 `mpc-iml` 開啟 **Remote**（Track 關閉）。音軌的 MIDI 輸入維持 MPC Sample
  （或 All Ins）；設成 `mpc-iml` 不會有聲音，因為這個 port 不送音符。進入 MIDI Map Mode
  （Cmd-M），點選參數，送出它的 CC，再離開 MIDI Map Mode。
- **Logic Pro**：選取參數，選擇 Logic Pro > Control Surfaces > Learn Assignment for
  "<參數>"（Cmd-L），送出它的 CC，再關閉 Learn。
- 可以直接輸入 CC 編號的 DAW：直接輸入 20-27。

模型執行時 8 個 CC 會一起變化，MIDI learn 會抓到最先送來的那一個。請改在 engine 沒有執行時
（狀態框顯示 `idle`），用 patch 的 learn 按鈕 `l1`-`l8` 一次對應一個：

1. 在 DAW 為輸出 1 要控制的參數開始 MIDI learn。
2. 按 patch 的 `l1`。engine 只送 CC 20，從 0 掃到 127，DAW 就學到它。再按一次會從 127 掃回 0，
   也可以用來確認對應。
3. 結束 MIDI learn，再對 `l2`（CC 21）到 `l8`（CC 27）重複。

`l3` 送 CC 22，與 `t3`、`o3` 同為輸出 3。從自己的前端送 `/mpciml/midi/learn 3` 效果相同。
執行中送這個訊息會得到 `wrong_state` 錯誤，請先按 `stop`。錄範例之前或之後對應都可以；重新
訓練後對應會保留。

輕觸一端的表現（#76）：

- 慢慢輕按時，輸出從休息開始隨 pressure 上升。MPC Sample 在碰到 pad 約 70 ms 後才回報
  pressure，所以輸出從那時開始變化；在那之前維持休息。
- 非常輕地按住 pad 時，MPC Sample（firmware 1.3.0）會在 pressure 降到最低時送出
  `Note Off`，70-273 ms 後再送出新的 `Note On`。這個 preset 不看 velocity 與按住旗標，
  所以輸入只從最後的 pressure（127 中的 1-3）降到 0 再回來，和放輕力道一樣，輸出維持在
  原本附近，不會掉回休息。
- 沒有持續施力的快速輕敲幾乎沒有作用。

輸出沒有平滑處理；若演奏時確實有影響，之後再加入。

## 撰寫 preset

preset 把特徵函式、模型、選用的固定類別編號與輸出對應包成一個有名稱的單位，以 plugin
方式載入（RFC 0002）。參考範例就是內建的 preset `demo`（`mpc_iml.demo.PRESET`）。外部
套件不必修改工具包即可新增 preset：

1. 在自己的套件中定義 `Preset`（`src/mpc_iml/presets.py`）：

   ```python
   from mpc_iml.presets import MidiCcOutput, OscOutput, Preset

   PRESET = Preset(
       name="my-preset",
       version="0.1.0",
       description="One line for listings",
       features=my_features,
       model_factory=MyModel,
       outputs=(OscOutput(), MidiCcOutput(controllers=(20, 21))),
       patch="my_package:patches/main.pd",
   )
   ```

   `features` 與 `classes` 就是 `ExampleSet(features=..., classes=...)` 的參數，
   `model_factory` 就是 `IMLLoop` 的參數（`None`：由 Wekinator 當模型）。`OscOutput` 預設為
   `127.0.0.1:12000` 的 `/wek/outputs`。`MidiCcOutput` 為每個輸出值宣告一個 CC 編號，並把
   `ranges`（預設 0-1）縮放到 0-127；engine 在 `running` 時送出（`mpc_iml.midi_out`，
   見[演奏 preset pressure](#演奏-preset-pressure)）。`patch`
   是套件內的前端 patch，寫成 `<package>:<path>`。`name` 只能用小寫字母、數字與連字號；
   `list` 與 `load` 保留給核心訊息（ADR 0004），使用時丟出 `PresetError`。

2. 在自己套件的 `pyproject.toml` 登記；entry point 也可以指向回傳 `Preset` 的函式：

   ```toml
   [project.entry-points."mpc_iml.presets"]
   my-preset = "my_package:PRESET"
   ```

3. 套件與工具包安裝在同一個環境後，`available_presets()` 會列出它，
   `get_preset("my-preset").build_loop()` 回傳使用其特徵、模型與第一個 `OscOutput` 的
   `IMLLoop`。preset 無法載入、不是 `Preset` 或名稱重複時丟出 `PresetError`。

`controls`（控制名稱對應到處理函式）**在 ADR 0004 接受前是暫定的**：engine 只在 `<name>`
是目前啟用的 preset 時，把 `/mpciml/preset/<name>/<control>` 連同訊息的參數轉給
`<control>` 的處理函式。型別仍可能改變。

`tests/plugins/` 有一個完整的範例套件，`tests/test_presets.py` 安裝它並在錄製的 fixture
上執行。

## 建立練習 repo

`python -m mpc_iml.new` 建立一個以相依套件使用本工具包、而不複製其程式碼的專案：
`pyproject.toml` 把 `mpc-iml-toolkit` 固定在執行中版本的 git tag，另有待替換的空模型
（`src/<package>/model.py`）、以錄音訓練並在重播上執行的程式、測試、範例錄音與簡短的
README。套件名稱取自資料夾名稱（可用 `--name` 指定）。

```bash
uv run python -m mpc_iml.new ../my-practice
```

在新專案中執行 `uv sync` 即可安裝固定的版本。若要改用本機的工具包 checkout，請在新專案中
執行 `uv add --editable <mpc-iml-toolkit 的路徑>`，再執行 `uv sync`。

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

pad 測試會等 10 秒，等待 pad A01 快速按下再放開：請輕點 pad，不要按住。

CI（`.github/workflows/ci.yml` 的 `checks` job）在 Ubuntu 與 macOS
（`ubuntu-latest`、`macos-latest`）上執行：各自先執行 workflow 工具測試
（`npm test --prefix tools/workflow`），再依序執行上列指令；硬體測試一律略過。

## 專案流程

工作在 GitHub Issue 中規劃，由 coding agent 以 pull request 實作，再由人審查與合併。
agent 的規則見 [AGENTS.md](AGENTS.md)。[`docs/workflow/`](docs/workflow/) 底下的
workflow 文件與 `AGENTS.md` 以繁體中文撰寫；Issue、pull request 與 commit 使用英文。

## 引用

在研究中使用本工具包時，請引用它。引用資訊在 [CITATION.cff](CITATION.cff)；
GitHub 的 repo 頁面會顯示為「Cite this repository」。版本號與發布日期在第一次發布時補上。

## 授權

[MIT](LICENSE)。RAVE、nn~ 等選用擴充有各自的授權（CC BY-NC 4.0，僅限非商業用途），
工具包不會內含或要求安裝它們。
執行時相依套件的授權列在 [docs/licenses.md](docs/licenses.md)（英文）。
