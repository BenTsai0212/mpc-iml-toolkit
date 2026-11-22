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

  不加 `--duration` 時錄到按 Ctrl-C 為止。加上 `--clock` 會同時錄下 DAW 從虛擬輸入
  `mpc-iml clock` 送來的 MIDI clock（或用 `--clock-port IAC`，與 engine 相同；DAW 的
  設定見[跟隨 DAW 的速度](#跟隨-daw-的速度midi-clock)），與 pad 寫在同一個檔案、同一個時間基準，格式是原有的
  raw `midi` 事件。該 port 的其他訊息會丟棄。沒有收到 clock 時仍會錄下 pad，並在 2 秒後
  印出一行仍在等待的提示（`MIDI clock: waiting for 'mpc-iml clock' ...`）。Live 只在播放時
  送出 clock，所以稍後才按 Play 也沒問題：收到第一個 clock 訊息時會印出
  `MIDI clock: receiving from 'mpc-iml clock'.`，Live 停止與再次播放時也各印出一行。
- 這種錄音的格點回讀：每個 pad 打擊輸出一行（以 tab 分隔），包含時間、小節、step、
  pad（`A01` 到 `H16`）、力度與偏離 step 的毫秒數（clock 未在執行時為 `-`），摘要印在
  標準錯誤。使用與 engine 相同的 `MidiClock`（`mpc_iml.clock.tag_recording`）：

  ```bash
  uv run python -m mpc_iml.grid out.jsonl --beats-per-bar 4 --resolution 16
  ```

  `--resolution` 可以是 `16`（預設）、`8` 或 `16t`（16 分音符三連音）。
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

格式見 [ADR 0002](docs/adr/0002-recording-and-osc-formats.md)；含有由 module 產生之
take 的錄音是 `format_version` 2
（[ADR 0007](docs/adr/0007-engine-protocol-1-3-kits-modules-and-pad-selection.md)），
沒有的仍是第 1 版。套件尚未發布。
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

## 20 分鐘開始演奏

給音樂家的路線：一個指令啟動 engine 並開啟 Pure Data 前端，之後都在 patch 上點按。從一個已經能演奏的
kit 開始（RFC 0003、ADR 0007），逐個 pad 修改，再在上面加上自己的示範。以下使用 preset `pressure`
（pad 的 pressure 對應到 8 個合成參數，細節見[演奏 preset pressure](#演奏-preset-pressure)）；前端對每個
preset 的操作方式相同（ADR 0006），沒有 kit 的 preset 的第 2 組 **Kit** 顯示為不可用。20 分鐘從
`uv sync` 開始計算。

開始之前：完成[參考範例](#參考範例)的第 1～3 步（uv、以 `uv sync` 安裝工具包、接好並設定
MPC Sample），並從官網或以 `brew install --cask pd` 安裝 [Pure Data](https://puredata.info)
vanilla 0.54 以上。安裝後先開啟 Pure Data 一次，讓 macOS 以它開啟 `.pd` 檔。

1. 在 `mpc-iml-toolkit` 資料夾以一個指令啟動全部，終端機視窗保持開啟：

   ```bash
   uv run mpc-iml
   ```

   engine 以資料夾 `mpc-iml-data` 啟動，並在 Pure Data 開啟前端
   `src/mpc_iml/patches/mpc-iml.pd`。patch 沒有開啟時，指令會印出它的路徑：從 Pure Data
   開啟該檔（File > Open）。在終端機按 Ctrl-C 停止 engine。

2. patch 會自動連線：第 1 組 **Connect** 顯示版本與 `state` `idle`，已安裝的 preset 列成按鈕。
   一直是空的時按 `connect`。按 preset 按鈕 `pressure`。第 2 組 **Kit** 這時列出 kit（`filter-play`
   在最前面）與 module，第 3 組 **Teach** 顯示以輸出名稱（`brightness`～`level`）標示的目標滑桿，
   第 7 組 **Outputs** 顯示同樣名稱的輸出與 learn 按鈕 `l1`～`l8`，第 6 組 **Library** 顯示名稱
   `pressure-examples`。

3. 從 kit 開始：在第 2 組 **Kit** 按 `filter-play`。engine 以 kit 產生的範例取代現有範例並訓練：
   `kit` 顯示 `filter-play`，狀態變成 `training` 再回到 `idle`，第 5 組 **Model** 的 `trained` 亮起。
   按 `run` 並演奏：pad 1～4 變亮，pad 5～8 加上 bite（brightness 與 resonance），pad 9～12 變暗，
   pad 13～14 產生 wobble，pad 15 彎曲音高，pad 16 不改變聲音。第 7 組的輸出跟著模型變化，engine
   在虛擬 port `mpc-iml` 送出 MIDI CC 20-27。

4. 在 DAW 對應 CC：按 `stop`，在狀態為 `idle` 時用 `l1`～`l8` 一次對應一個 CC，做法見
   [在 DAW 對應 MIDI CC](#在-daw-對應-midi-cc)，再按 `run`，從 MPC Sample 演奏合成器。使用 Ableton
   Live 12 時，[Ableton Live 入門 set](#ableton-live-入門-set) 已經做好對應：改開啟它，略過對應步驟。

5. 修改一個 pad：打開第 2 組的 `select_pad`，在 MPC Sample 上敲一個 pad。`pad` 顯示它的編號，
   `module` 顯示它的 module，`amount` 顯示 module 作用的強度。按另一個 module（例如 `wobble`），或
   拖動 `amount` 後放開：engine 只取代這個 pad 產生的範例並重新訓練，原本在執行時會繼續執行。也可以
   在 `pad` 輸入 pad 編號（1-16），不必敲 pad。重新訓練還在進行時再修改，狀態列會顯示錯誤；等重新
   訓練結束即可。改完後關掉 `select_pad`（按 `record` 也會關掉）。

6. 在上面加上示範：按 `stop`，把第 3 組的目標滑桿設成某個手勢想要的聲音，在 pad 上保持手勢，按第 4 組
   **Examples** 的 `record`，持續約兩秒，按 `stop_recording`。按 `train`，再按 `run`。示範與該 pad 的
   module 一起訓練：短的示範只稍微改變 module 的聲音，2～3 秒的示範會蓋過它。

7. 在第 6 組 **Library** 按 `save`，把範例連同 kit 與各 pad 的 module 存在
   `mpc-iml-data/pressure-examples.jsonl`；下次按 `load` 載回。

engine 的錯誤（例如在錯誤的狀態按了按鈕）顯示在第 9 組 **Messages** 的狀態列，不只在 Pd 視窗。

**從零開始錄音**（進階路線）：不用 kit，按第 4 組 **Examples** 的 `clear`（kit 也一併清除），所有範例
都自己錄。每個範例：把目標滑桿（0-1）設成想要的聲音，在 pad 上保持手勢，按 `record`，持續約兩秒，按
`stop_recording`。依序錄四個範例：休息（不碰 pad，目標值設成無聲）、pad 1 的最輕觸碰（目標值接近
休息）、輕按、重按，各自設定目標值。counts 顯示範例數量。然後按 `train`，`trained` 亮起後按 `run`。

`uv run mpc-iml` 的選項：指令後加資料夾名稱改用其他資料夾（`uv run mpc-iml my-data`）；
`--no-patch` 只啟動 engine，給 [Max for Live 裝置](#使用-max-for-live-裝置)或自己的前端使用；其他選項與 engine
相同（`--preset`、`--replay`、`--midi-port IAC`、各埠號；見[執行 engine](#執行-engine)）。

演奏時遇到問題，見[疑難排解](#疑難排解)。

## 執行 engine

engine 是長時間執行的 IML 迴圈，由前端（Pure Data、Max，之後是 app）以 OSC 控制訊息驅動；
協定見 [ADR 0004](docs/adr/0004-engine-control-protocol.md)，1.1 版見
[ADR 0005](docs/adr/0005-engine-protocol-1-1-midi-learn.md)，1.2 版見
[ADR 0006](docs/adr/0006-engine-protocol-1-2-layout-and-front-ends.md)，1.3 版見
[ADR 0007](docs/adr/0007-engine-protocol-1-3-kits-modules-and-pad-selection.md)，1.4 版見
[ADR 0008](docs/adr/0008-engine-protocol-1-4-midi-clock-sync.md)，1.5 版（preset 的狀態回覆）見
[ADR 0009](docs/adr/0009-engine-protocol-1-5-preset-state-and-ensemble-group.md)。依[參考範例](#參考範例)接好
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
短的掃動讓 DAW 學習，並回覆 `/mpciml/midi/sent <輸出> <controller>`。engine 回報 preset 時一併送出
`/mpciml/layout <targets> <controllers>`：preset 的目標值個數（分類為 0）與 MIDI controller
個數（沒有 MIDI 輸出為 0），讓前端顯示對應的控制項。按 Ctrl-C 停止 engine：關閉輸入與 socket，
進行中的訓練會先完成。

1.3 版為有輸出名稱的 preset（`pressure`；見[輸出名稱、module 與 kit](#輸出名稱module-與-kit)）
加上 kit。完整狀態與 `preset/load` 另外送出 `/mpciml/names`（輸出名稱）、`/mpciml/kit`（範例集
起始的 kit，沒有時為 `""`）與 `/mpciml/pads`（16 組 module 與 amount）。`/mpciml/kit/list` 與
`/mpciml/module/list` 回覆 `/mpciml/kits` 與 `/mpciml/modules`。`/mpciml/kit/load filter-play`
以 kit 產生的 take 取代整個範例集並訓練；`/mpciml/pad/module <pad> <module> [amount]` 改變一個
pad（1～16），保留錄下的示範並重新訓練（兩者都在 `idle`，或沒有進行中的重新訓練時在 `running`）。
在 `/mpciml/pad/select/start` 與 `/mpciml/pad/select/stop`（或 `record/start`、`preset/load`）
之間，MPC 上每次敲擊 pad 都會回報 `/mpciml/pad/hit <pad>`。`examples/clear` 也會清除 kit；
`examples/save` 把含產生 take 的範例集寫成錄音格式第 2 版，`examples/load` 會還原 kit 與各 pad
的 module。

適用所有 preset 的參考前端是 Pure Data patch `src/mpc_iml/patches/mpc-iml.pd`（vanilla 0.54
以上，不需外掛；ADR 0006）。先啟動 engine 再開啟 patch：開啟時會自動連線（重新啟動 engine 後按
`connect`），把已安裝的 preset 列成按鈕，並依載入的 preset 調整：`demo` 顯示類別按鈕，
`pressure` 顯示目標滑桿 `t1`～`t8` 與 learn 按鈕 `l1`～`l8`。engine 的錯誤顯示在 patch 的狀態列。
`uv run mpc-iml` 一步啟動 engine 並開啟這個 patch（[20 分鐘開始演奏](#20-分鐘開始演奏)）。

### 跟隨 DAW 的速度（MIDI clock）

1.4 版讓 engine 跟隨送出 MIDI clock 的 DAW 的速度、小節與拍（ADR 0008）。只有以 `--clock`
啟動 engine 時才同步：

```bash
uv run mpc-iml --clock
```

engine 會開一個叫 `mpc-iml clock` 的虛擬 MIDI 輸入，DAW 把它列為輸出。先啟動 engine 再開
DAW，或在 DAW 的 MIDI 設定把這個 port 關掉再打開。

- **Live**（任何版本）：在 Settings > Link, Tempo & MIDI > MIDI Ports，把輸出 `mpc-iml clock`
  的 **Sync** 打開，並把 MIDI Clock Type 設為 **Song**，讓 Live 送出歌曲位置。
- **Logic**：在 File > Project Settings > Synchronization > MIDI，打開 Transmit MIDI Clock
  並送到 `mpc-iml clock`，勾選 Song Position Pointer。

`--clock-port IAC` 改從名稱包含該文字的既有輸入 port 讀取 clock（等同同時指定 `--clock`）。
`--beats-per-bar 3` 設定每小節的四分音符數（預設 4；MIDI clock 不帶拍號）。engine 在每次狀態
改變、DAW 播放時每拍一次，以及完整狀態的最後回報 `/mpciml/clock <status> <bpm> <bar> <beat>`。
沒有 `--clock` 時狀態是 `off`，收到第一個 tick 前是 `waiting`，之後是 `running`，Stop 後是
`stopped`，0.5 秒沒有 tick 時是 `lost`；小節與拍從 1 開始（第一個 tick 前為 0）。pad 輸入、
錄製、訓練與執行都不會等待 clock。

要確認 engine 送出的音符落在拍上，送 `/mpciml/clock/test 1`：engine 從下一小節開始，在
`mpc-iml` MIDI 輸出上於第 1 拍送音符 72、其他拍送音符 60（長度一個 16 分音符）。在 DAW 把一條
MIDI 軌的輸入設為 `mpc-iml`、放任何樂器並啟用錄音監聽即可聽到；`/mpciml/clock/test 0` 停止。
DAW 按 Stop 時會結束正在發聲的音符，按 Play 或 Continue 後從下一小節重新開始。音符聽起來偏晚
時，`--clock-lead-ms 10` 讓排程的音符提早 10 ms 送出（或使用 Live 的 MIDI Clock Sync Delay）。

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

1. 以這個 preset 啟動 engine 與前端，終端機視窗保持開啟：

   ```bash
   uv run mpc-iml --preset pressure
   ```

   在 macOS 上，`mpc-iml` 這個 port 會出現在每個 MIDI app 的輸入中。若要改用 IAC bus，
   在 Audio MIDI Setup（音訊 MIDI 設定）開啟它（Window > Show MIDI Studio，按兩下 IAC Driver，
   勾選 Device is online），
   並加上 `--midi-port IAC`。MIDI port 無法開啟時，engine 會說明原因並繼續送 OSC。

2. 這個指令會在 Pure Data 開啟前端 `src/mpc_iml/patches/mpc-iml.pd`（沒有開啟時，從 File > Open
   開啟它印出的路徑）。patch 會自動連線：第 1 組 **Connect** 顯示版本與 `state` `idle`；載入
   `pressure` 後，第 2 組 **Kit** 列出 kit 與 module，第 3 組 **Teach** 顯示標示為 `brightness`～`level`
   的目標滑桿，第 7 組 **Outputs** 顯示 learn 按鈕 `l1`-`l8`。若在 patch 之後才重新啟動 engine，按
   `connect`。要從 kit 開始而不錄音，照[20 分鐘開始演奏](#20-分鐘開始演奏)第 3～5 步。

3. 錄幾個範例（第 4 組 **Examples**）。每個範例：把 8 個目標滑桿（0-1）設成想要的
   聲音，在 pad 上保持手勢，按 `record`（先送出目標值，再開始錄音），持續約兩秒，按
   `stop_recording`。先錄休息（不碰 pad，目標值設成無聲），再錄例如輕按 pad 1 與重按 pad 1，
   各自設定目標值。多個 pad 與其他力道的做法相同。若要讓輕觸的一端連續，另外錄一個能保持的
   最輕觸碰（手指放在 pad 1 上幾乎不施力），目標值接近休息，讓模型把最輕的 pressure 對應到
   休息附近。要重新開始（例如錄音順序錯了）時按 `clear`：刪除 engine 中所有範例，已存的檔案
   不受影響。在 `idle` 與 `running` 都可以使用，範例數會顯示新的數量。

4. 按 `train`（第 5 組 **Model**）。狀態變成 `training` 再回到 `idle`，`trained` 亮起。按
   `run` 並演奏：第 7 組的輸出滑桿跟著模型變化，MIDI CC 也跟著送出。`stop` 結束執行。
   `save` 與 `load`（第 6 組 **Library**）把範例存在 `mpc-iml-data/pressure-examples.jsonl`。

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

`pressure` 8 個輸出的建議對應，適用任何 DAW 與一般的減法合成器。範圍只是起點，請依聽感調整。
[Ableton Live 入門 set](#ableton-live-入門-set) 是實際範例。

| 輸出 | CC | 用途 | 一般減法合成器的建議目標 | 建議範圍 |
| --- | --- | --- | --- | --- |
| `brightness` | 20 | 聲音明亮或暗沉的程度 | 濾波器截止頻率 | 約 80 Hz 到 16 kHz |
| `resonance` | 21 | 濾波器在截止頻率共鳴的強度 | 濾波器共振 | 0 到約 85 % |
| `drive` | 22 | 顆粒感與增加的泛音 | 飽和或失真量 | 0 到約 50 % |
| `space` | 23 | 聲音的距離感與空間感 | 殘響 send 或 wet | 0 到 60 % |
| `motion` | 24 | 聲音的動態變化 | LFO 對聲像、濾波器或音量的深度 | 0 到約 50 % |
| `pitch` | 25 | 彎曲音高；靜止值在中間 | 音高或 detune | 約 -2 到 +2 個半音，或 ±20 cents 的 detune |
| `texture` | 26 | 噪音與粗糙感 | 噪音音量或波形 | 噪音 0 到約 30 %，或波形的完整範圍 |
| `level` | 27 | 聲音的音量 | 輸出增益 | 約 -24 dB 到 0 dB |

模型執行時 8 個 CC 會一起變化，MIDI learn 會抓到最先送來的那一個。請改在 engine 沒有執行時
（`state` 顯示 `idle`），用 patch 的 learn 按鈕 `l1`-`l8` 一次對應一個：

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

## 演奏 preset ensemble

內建的 preset `ensemble`（[RFC 0005](docs/rfcs/0005-drum-led-ensemble.md)）演奏跟隨 MPC Sample
上的鼓的 bass 與旋律：每一小節的鼓決定樂團的下一小節。以 MIDI clock 啟動：

```bash
uv run mpc-iml --preset ensemble --clock
```

不需要 MPC 或 Live 也能以網頁 demo 試聽：

```bash
uv sync --extra demo
uv run python -m mpc_iml.webdemo
```

完整的說明在 [docs/ensemble.zh-TW.md](docs/ensemble.zh-TW.md)：
[為 bass 設定 Live](docs/ensemble.zh-TW.md#為-bass-設定-live)、
[bass loop](docs/ensemble.zh-TW.md#bass-loop)、
[旋律 loop](docs/ensemble.zh-TW.md#旋律-loop)、
[寫自己的 bass 線條](docs/ensemble.zh-TW.md#寫自己的-bass-線條)、
[Pure Data 的 Ensemble 群組](docs/ensemble.zh-TW.md#pure-data-的-ensemble-群組)、
[ensemble 的控制項](docs/ensemble.zh-TW.md#ensemble-的控制項)與
[不需硬體試玩](docs/ensemble.zh-TW.md#不需硬體試玩)。

## Ableton Live 入門 set

不需對應步驟就能演奏 preset `pressure` 的 Live set（RFC 0003、#104），放在
[`assets/ableton/`](assets/ableton)：

- `mpc-iml-starter.als`：一條 MIDI 音軌 `mpc-iml`（輸入 All Ins，Monitor Auto），上面是一個
  Instrument Rack，8 個 macro 以 `pressure` 的輸出命名，已對應到 port `mpc-iml` 的 channel 1
  CC 20-27；
- `mpc-iml-starter.adg`：同一個 Instrument Rack 單獨存檔：Drift、Saturator、Auto Pan-Tremolo、
  Reverb 與 Utility。

需要 Ableton Live 12 的 Standard 或 Suite。只用 Live 內建的裝置，不需 Max for Live，沒有 sample，
也沒有第三方 plug-in。在 Live 12.4 Standard 建立並演奏過。

1. 先啟動 engine，讓 port `mpc-iml` 存在，終端機視窗保持開啟：

   ```bash
   uv run mpc-iml
   ```

2. 在 Live 開啟 `assets/ableton/mpc-iml-starter.als`。
3. 在 Settings > Tempo & MIDI 的 Input Ports 表格中，為 MPC Sample 開啟 **Track**，為 `mpc-iml`
   開啟 **Remote**（Track 關閉）。Live 會保留這些設定，只需設定一次。
4. 在 Pure Data 前端按 preset `pressure`，在第 2 組 **Kit** 載入一個 kit（例如 `filter-play`），
   等 `trained` 亮起，按 `run`，演奏 MPC Sample。macro 會跟著 pressure 變化。

macro 一覽（macro 0 到 127；channel 1，port `mpc-iml`）：

| Macro | 名稱 | CC | 參數 | 範圍 |
| --- | --- | --- | --- | --- |
| 1 | brightness | 20 | Drift low-pass frequency | 80 Hz 到 16 kHz |
| 2 | resonance | 21 | Drift low-pass resonance | 0 到 0.85 |
| 3 | drive | 22 | Saturator Drive | 0 dB 到 18 dB |
| 4 | space | 23 | Reverb Dry/Wet | 0 % 到 60 % |
| 5 | motion | 24 | Auto Pan-Tremolo LFO Amount | 0 % 到 60 % |
| 6 | pitch | 25 | Drift Osc 2 Detune | -0.50 到 +0.50（中央為準音，即 kit 的休息值 pitch 0.5） |
| 7 | texture | 26 | Drift Noise Gain | -inf dB 到 -10 dB |
| 8 | level | 27 | Utility Output Gain | -24 dB 到 0 dB |

固定設定：Drift 的 filter type II（24 dB）、filter envelope 調變（Freq Mod，Env 2）0 %、Osc 2 鋸齒波；
Saturator Dry/Wet 100 %；Auto Pan-Tremolo rate 4 Hz；Reverb decay 3.00 s。kit 的休息值仍是暫定，
休息時的聲音可能會改變。

rack `mpc-iml-starter.adg` 可以拖進其他 set，但不帶 CC 對應：對應只存在 `.als` 裡。在其他 set
中，依[在 DAW 對應 MIDI CC](#在-daw-對應-midi-cc) 對應 macro。

## 疑難排解

演奏時遇到問題，先檢查下列事項。engine 的錯誤顯示在 patch 第 9 組 **Messages** 的狀態列。

| 症狀 | 要檢查的事 |
| --- | --- |
| 沒有聲音 | DAW 音軌的 MIDI 輸入是 MPC Sample（或 All Ins），不是 `mpc-iml`：這個 port 只送 CC 與 `ensemble` 的 bass 和旋律，不送鼓的音符。音軌的 Monitor 是 In 或 Auto。MPC Sample 的 **MIDI Port** 設為 **USB**、**Pad MIDI Out** 設為 **Always**（[參考範例](#參考範例)第 3 步）。 |
| 有聲音，但參數或 macro 不動 | engine 正在執行，前端的 `state` 顯示 `running`（按 `run`）。在 Live 中，Settings > Tempo & MIDI 已為 `mpc-iml` 開啟 **Remote**。DAW 比 engine 先開啟時，port `mpc-iml` 當時還不存在：啟動 engine 後重新開啟 DAW（或在 DAW 的 MIDI 設定中把這個 port 關掉再開啟）。 |
| 對應遺失或錯誤 | 按 `stop` 讓 `state` 顯示 `idle`，再用 `l1`-`l8` 一次對應一個 CC，做法見[在 DAW 對應 MIDI CC](#在-daw-對應-midi-cc)。使用 Live 時，[Ableton Live 入門 set](#ableton-live-入門-set) 已經做好對應。 |
| patch 沒有反應 | 按 `connect`。仍沒有反應時，關閉 patch，在終端機按 Ctrl-C 停止 engine，再執行一次 `uv run mpc-iml`。 |
| engine 停止了，或 MPC Sample 沒有反應 | 重新插上 USB 線，以 Ctrl-C 停止 `uv run mpc-iml` 再重新啟動，然後按 preset（例如 `pressure`），載入 kit，再按 `run`。 |
| `ensemble` 沒有發出 bass | bass 軌的 MIDI From 是 `mpc-iml`、**Ch. 2**，且 Live 設定中輸入 `mpc-iml` 的 **Track** 已打開。kick 在 pad 1 或 5。bass loop 需要 `--clock` 且 Live 正在播放，按 Start 後會等你的第一個 kick；停打之後繼續演奏 `fade-bars` 個小節（預設 8；`no-drums thin` 時為兩個）。pad 16 可能已把 bass 切換到 `rule` 或 `off`（第 8 組 **Ensemble** 與終端機會顯示模式）；見[演奏 preset ensemble](docs/ensemble.zh-TW.md#演奏-preset-ensemble)。 |
| `ensemble` 沒有發出旋律 | engine 以 `--clock` 執行，Live 正在播放且為 `mpc-iml clock` 打開 Sync。鍵盤軌的 MIDI From 是 `mpc-iml`、**Ch. 3**。按 Start 後旋律會等你的第一下打擊；停打之後繼續演奏 `fade-bars` 個小節（預設 8；`no-drums thin` 時為兩個）。pad 15 可能已把它關掉（第 8 組 **Ensemble** 顯示 `off`，終端機顯示 `ensemble: melody off`）；見[旋律 loop](docs/ensemble.zh-TW.md#旋律-loop)。 |
| 修改 module 或 `amount` 後狀態列顯示 `wrong_state` | 重新訓練正在進行；稍等一下再試。 |
| 輕輕按住或快速輕敲時聲音幾乎不變 | 見[演奏 preset pressure](#演奏-preset-pressure) 中[在 DAW 對應 MIDI CC](#在-daw-對應-midi-cc) 最後的輕觸一端說明（#76）。 |

## 使用 Max for Live 裝置

Max for Live 裝置讓你不離開 Ableton Live 就能錄範例、訓練、執行與對應模型。它有 ADR 0006 的
7 組，按鈕名稱與順序和 Pure Data 前端相同，但還沒有 ADR 0007 的第 2 組 **Kit**，也沒有
ADR 0009 的第 8 組 **Ensemble**（只有 Pure Data 有），所以 patch 的第 3～7 組與第 9 組是裝置的
第 2～7 組，[20 分鐘開始演奏](#20-分鐘開始演奏)的錄音路線同樣適用；只有啟動與安裝
不同。這個裝置還沒有在 Live 中確認過（#86）。

需要 Live Suite，或 Live Standard 加上 Max for Live；[參考範例](#參考範例)的設定（第 1～3 步）；
以及[在 DAW 對應 MIDI CC](#在-daw-對應-midi-cc) 的 Live 設定（MPC Sample 開啟 **Track**，
`mpc-iml` 開啟 **Remote**）。

這個裝置是 Max MIDI Effect：放在 MPC Sample 的 MIDI 音軌上、樂器前面，pad 的 MIDI 原樣通過。
它和 Pure Data 前端用相同的埠號（6450、6451 與 12000）以 OSC 與 engine 溝通，所以兩者一次只能
執行一個：Live set 中有這個裝置時，關閉 `mpc-iml.pd`。它只用標準的 Max 物件，
不需要 external。

### 安裝裝置

repo 中有裝置的原始檔 `src/mpc_iml/patches/mpc-iml.maxpat`（由 `tools/m4l/build_device.py`
產生的 Max patcher）。在加入現成的 `mpc-iml.amxd` 之前，先用它建立一次裝置：

1. 在 Live 的瀏覽器中，從 Max for Live 把 **Max MIDI Effect** 拖到 MPC Sample 的 MIDI 音軌上、
   樂器前面。
2. 按裝置的編輯按鈕，在 Max 中開啟它。全選原有的物件（Cmd-A）並刪除：它們讓 MIDI 通過，
   而這個裝置自己會做。
3. 在 Max 開啟 `src/mpc_iml/patches/mpc-iml.maxpat`（File > Open），全選（Cmd-A）、複製
   （Cmd-C）後關閉，再貼上（Cmd-V）到裝置的視窗。
4. 在裝置視窗的 Patcher Inspector 開啟 **Open in Presentation**，讓 Live 顯示控制項而不是
   接線。
5. 另存為 `mpc-iml.amxd`（File > Save As），例如存在 User Library，再關閉 Max。下次從 User
   Library 把 `mpc-iml.amxd` 拖到音軌上即可。

### 用裝置演奏

1. 在 `mpc-iml-toolkit` 資料夾只啟動 engine，終端機視窗保持開啟：

   ```bash
   uv run mpc-iml --no-patch
   ```

   加上 `--preset pressure` 會以這個 preset 啟動；也可以在裝置中選擇。

2. 開啟 MPC Sample 音軌上有這個裝置的 Live set。裝置載入時會自動連線：第 1 組 **Connect**
   顯示 protocol 與 engine 版本、preset 與 `state` `idle`。如果一直是 `-`，按 `connect`（例如
   重新啟動 engine 之後）；`ping` 確認 engine 有回應。從選單選擇 preset。

3. 第 2 組 **Teach** 依 preset 變化。`pressure`：目標值滑桿 `t1`～`t8`。分類 preset（例如
   `demo`）：`class` 欄位與類別按鈕 `c1`～`c8`。

4. 錄範例、訓練與執行的方式同[20 分鐘開始演奏](#20-分鐘開始演奏)的「從零開始錄音」：第 3 組
   **Examples** 的 `record` 與 `stop recording`，第 4 組 **Model** 的 `train`、`run` 與
   `stop`。第 6 組 **Outputs** 以長條顯示模型輸出 `o1`～`o8`（`demo` 顯示預測的類別）。

5. 在狀態為 `idle` 時一次對應一個 CC：在 Live 進入 MIDI Map Mode（Cmd-M），點選輸出 1 要控制
   的參數，按裝置的 `l1`，再離開 MIDI Map Mode。裝置顯示 `output 1 on CC 20`。對 `l2`～`l8`
   重複。之後按 `run`，從 MPC Sample 演奏樂器。

6. 第 5 組 **Library** 的 `save` 以 `name` 欄位的名稱（預設 `pressure-examples`）把範例存在
   engine 的資料夾 `mpc-iml-data`；`load` 載回，`list` 顯示已存的名稱。

engine 的錯誤顯示在第 7 組 **Messages** 的狀態列，不只在 Max 視窗。裝置本身不把輸出對應到
Live 的參數（沒有 `live.remote~`）：控制參數仍是透過 engine 在 `mpc-iml` 送出的 CC，在其他
DAW 也一樣。

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

`clock` 同樣是**暫定的**（ADR 0008）：engine 每次載入 preset 時（不論有沒有 `--clock`），以
`mpc_iml.clock.ClockAccess` 呼叫這個函式。它可讀取 `state()` 與 `position(t)`，`on_hit(callback)`
則在 DAW 播放時收到每次 pad 敲擊放上格點後的 `GridHit`（小節、16 分音符的 step 與偏離 step 的量）。
`on_pad(callback)` 在任何 clock 狀態下、沒有 `--clock` 時也會收到每次 pad 敲擊的 `PadHit`；
DAW 播放時它的 `grid` 是 `GridHit`，否則是 `None`。`send_now(messages)` 立即在 `mpc-iml` port
送出音符與其他 MIDI 訊息；有 `--clock` 時，它開始的音符與排程的音符一樣在 Stop 時結束。
有 `--clock` 時，`scheduler`（`mpc_iml.clock.Scheduler`，否則是 `None`）在指定的小節與 step
送出這些訊息：`note(bar, step, note, velocity, length_steps)`、`at(bar, step, messages)` 與
`at_next_bar(messages, n)`；`cancel(handle)` 取消一筆。載入其他 preset 時，清除仍在排程中的訊息
並結束正在發聲的音符。`report()` 要求 engine 再送一次 preset 的狀態（見下文）；載入其他 preset
後不做任何事。

`state` 同樣是**暫定的**（ADR 0009）：這個函式以（回覆名稱, 參數）配對傳回 preset 目前的狀態；
名稱是小寫英文字母、數字與連字號，參數是 int、float 或字串。engine 在 `preset/load` 之後、完整
狀態中 `clock` 之後、每個成功的 preset 控制項之後，以及 preset 呼叫 `report()` 時（例如 pad
改變了模式之後），把每個配對以 `/mpciml/preset/<name>/<reply>` 送出。engine 在持有自己的 lock 時
呼叫 `state`，所以不要在持有控制項也會取得的 lock 時呼叫 `report()`。範例見 `ensemble`。

`tests/plugins/` 有一個完整的範例套件，`tests/test_presets.py` 安裝它並在錄製的 fixture
上執行。

### 輸出名稱、module 與 kit

regression preset 可以用 `output_names` 為輸出命名（每個 target 一個，小寫字母、數字與
連字號）。只有命名了輸出的 preset 才有 module 與 kit
（[ADR 0007](docs/adr/0007-engine-protocol-1-3-kits-modules-and-pad-selection.md)）：
**module** 描述按壓一個 pad 時哪些輸出如何變化，**kit** 是一個靜止時的聲音加上 16 個
pad 各自的 module。`pressure` 的輸出名稱是 `brightness`、`resonance`、`drive`、
`space`、`motion`、`pitch`、`texture`、`level`（CC 20-27），內建 9 個 module 與
`filter-play`（預設）、`texture-lab`、`ambient-space` 三個 kit
（`src/mpc_iml/modules/pressure/`、`src/mpc_iml/kits/pressure/`；靜止值在硬體試玩前是
暫定的）。engine 以 `/mpciml/kit/load` 載入 kit，以 `/mpciml/pad/module` 改變一個 pad
（[執行 engine](#執行-engine)）。

其他套件也能為不是自己定義的 preset 新增 module 與 kit：把 JSON 檔放在
`<root>/modules/<preset>/<name>.json` 與 `<root>/kits/<preset>/<name>.json`，並登記一個
`Content`：

```toml
[project.entry-points."mpc_iml.content"]
my-content = "my_package:CONTENT"
```

其中 `CONTENT = Content(preset="pressure", root="my_package:content")`。
`mpc_iml.content.load_library(preset)` 列出它們，
`mpc_iml.generation.GeneratedSet.from_kit(library, "filter-play")` 產生 kit 的訓練範例；
範例套件見 `tests/plugins/mpc_iml_example_content/`。

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
