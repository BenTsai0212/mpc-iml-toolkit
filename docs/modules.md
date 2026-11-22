# 模組

`src/mpc_iml/` 每個 module 一行。本文件只描述 `main` 上實際存在的內容；新增或修改 module 的 PR 在同一個 PR 更新該 module 的那一行。

| 路徑 | 內容 |
| --- | --- |
| `src/mpc_iml/` | 工具包本體（import 名稱 `mpc_iml`）；格式見 ADR 0002 |
| `src/mpc_iml/osc.py` | OSC sender，Wekinator 預設 |
| `src/mpc_iml/events.py` | 事件型別 |
| `src/mpc_iml/recording.py` | JSON Lines 錄音讀寫 |
| `src/mpc_iml/frames.py` | pad 對應與 frame |
| `src/mpc_iml/midi.py` | MIDI 位元組解碼 |
| `src/mpc_iml/sources.py` | 即時 MIDI 與重播的事件來源、錄音、MIDI clock 輸入 `ClockInput` |
| `src/mpc_iml/record.py` | 錄音 CLI：`python -m mpc_iml.record`；`--clock`／`--clock-port` 同時錄下 MIDI clock，經 `LiveSource.inject` 與 pad 共用時間基準，預設關閉 |
| `src/mpc_iml/grid.py` | 錄音的格點回讀 CLI：`python -m mpc_iml.grid <錄音>`，以 `clock.tag_recording` 標出每個 pad 打擊的小節、step 與偏移 |
| `src/mpc_iml/examples.py` | 從錄音建立訓練範例；特徵集 `default_features`、`played_features`、`pressure_features` |
| `src/mpc_iml/model.py` | 模型擴充點 |
| `src/mpc_iml/sklearn_backend.py` | 內建 scikit-learn 模型 |
| `src/mpc_iml/loop.py` | IML 迴圈：訓練、執行、重新訓練 |
| `src/mpc_iml/demo.py` | 參考範例：`python -m mpc_iml.demo` |
| `src/mpc_iml/new.py` | 練習 repo 範本：`python -m mpc_iml.new <資料夾>`，範本檔在 `project_template/` |
| `src/mpc_iml/presets.py` | preset plugin 介面：entry point 群組 `mpc_iml.presets`，內建 `demo`、`pressure`、`ensemble`；暫定的 `Preset.state` 傳回 preset 的狀態回覆，ADR 0009；暫定的 `Preset.data_folder` 在載入 preset 時傳入 engine 的資料夾，#173、ADR 0010 |
| `src/mpc_iml/engine.py` | OSC 控制的 engine：`python -m mpc_iml.engine <資料夾>`，協定見 ADR 0004，1.1 版的 MIDI learn 見 ADR 0005，1.2 版的 `/mpciml/layout` 與前端共用規格見 ADR 0006，1.3 版的 kit、module 與 pad 選擇見 ADR 0007，1.4 版的 MIDI clock 同步見 ADR 0008：`--clock` 開虛擬輸入 `mpc-iml clock`，預設關閉；1.5 版的 preset 狀態回覆 `/mpciml/preset/<name>/<reply>` 見 ADR 0009 |
| `src/mpc_iml/launch.py` | 音樂家用的指令 `uv run mpc-iml`：啟動 engine 並開啟 `patches/mpc-iml.pd`，`--no-patch` 只啟動 engine |
| `src/mpc_iml/midi_out.py` | MIDI CC 輸出與排程音符的 `send_message`，預設開虛擬 port `mpc-iml` |
| `src/mpc_iml/pressure.py` | 內建 preset `pressure`：pressure 對應到 8 個合成參數，輸出名稱見 ADR 0007；entry point 是 `make_preset`，每次建立都有新的 drift 狀態 |
| `src/mpc_iml/melody.py` | `ensemble` 旋律層的 loop 與規則：loop `keys`、`pluck`（loop 檔，見 `loops`），`LoopNote` 的 `chord`（下一小節的和弦）與 `semitones` 寫出趨近音，每個 loop 有三個完整的變奏（#158：`melody_variation` 依上一小節的打擊數與 hat 選擇，`melody_ornaments` 決定裝飾音），依上一小節的鼓決定下一小節的 `Follower`（變奏、層級、velocity、亮度，與沒有鼓時的 `no-drums` 規則 `lead`、`hold`、`thin`），以及樂句結尾的 surprise：`surprise`（有種子的抽選）、`octave_up`、`passing`；不做 I/O |
| `src/mpc_iml/bass.py` | #148：`ensemble` 的 bass loop `boom`、`walk`（loop 檔，見 `loops`）的 kick 規則：kick 位置決定變奏的 `bass_variation`、kick 數決定裝飾音的 `bass_ornaments`、kick 位置決定重音的 `accent`、surprise 的 `bass_fill`；不做 I/O |
| `src/mpc_iml/rhythm.py` | RFC 0005 第 6 步（#189）：`ensemble` 的節奏轉換，把變奏的音符起點移向上一小節的鼓，不增減音符、不改音高與順序：`motif` 依 pad 角色讀出 kick、snare、hat 的 step、velocity 與偏移（同一 step 取最大聲），`Memory` 保留樂句的 motif（相近的小節沿用），`lock`（bass 音移到 `REACH` 2 step 內最近的空 kick）、`answer`（`lock` 移過的音再晚一個 16 分音符）、`backbeat`（旋律移向 snare 與 hat；hat 有奇數 step 時用 16 分音符，否則只用 8 分音符），`fixed_steps` 的骨架音與 `chord` 1 的趨近音不動，移動的音取該打擊偏移的 `FEEL` 0.5，打擊少於 `MIN_HITS` 2 時照原樣，打擊多於音符時先取 8 分音符格點；`bass_stage` 依樂句位置選擇 bass 的轉換（第 1 小節照原樣，第 2、3 小節 `lock`，第 4 小節 `answer`），`Taken` 記下取自鼓的 step 與移動；不做 I/O |
| `src/mpc_iml/drift.py` | RFC 0004 實驗 A：`pressure` 的 drift 模式，以包住模型的 `DriftModel` 實作，預設關閉；控制項 `/mpciml/preset/pressure/drift/…` |
| `src/mpc_iml/ensemble.py` | 內建 preset `ensemble`，RFC 0005 的第一步：pad 角色與跟隨 kick 的 bass，`mpc-iml` port 的 channel 2，模式 `bass` 為 `loop`（預設，#148，每個小節線依上一小節的 kick 改變下一小節，需要 `--clock`，沒有時改為每個 kick 一個音）、`rule`（#138 的規則式 bass，immediate 與 bar 兩層可各自開關）或 `off`，pad 16 切換；#144 的旋律層在 channel 3，每個小節線依上一小節的鼓改變下一小節，需要 `--clock`，pad 15 切換 follow、fixed、off（follow 與 fixed 同時適用 bass loop）；#153 的 `melody-mode` 一次設定旋律的 follow、fixed、off；#158 的兩個 loop 以變奏跟隨鼓，沒有鼓時依 `no-drums`（預設 `lead`）與 `fade-bars`（預設 8）；`surprise 0-2`（預設 1，#178）在每個 4 小節樂句的最後一小節以 1/2 機率加入意外：0 關閉，1 只有 bass fill，2 為 bass fill、旋律高八度或經過音，以 `Ensemble(seed=…)` 的種子抽選；不用模型；控制項 `/mpciml/preset/ensemble/…`；`state` 回覆 bass 與旋律模式的 next 與 playing、loop、和弦進行、設定與 pad 角色（ADR 0009），以及 `no-drums`、`fade-bars`、`surprise` 與正在演奏的變奏 `variation`，按 pad 15、16 後與正在演奏的模式、變奏或轉換改變的小節線呼叫 `report()`；#189 的 `rhythm 0-2`（預設 1，不在演奏中調整）以 `rhythm` 把 bass 變奏的音符起點移向上一小節的 kick，2 時旋律也以 `backbeat` 移向 snare 與 hat（各自的樂句記憶、`BarPlan.transform` 與 `taken`、回覆 `rhythm` 與 `transform`、樂句開頭的 log）；#159 的 `learn-cc` 在 clock 未執行時只送出亮度 CC 的掃動，讓 DAW 對應，第 8 組有 `learn_CC` 按鈕；entry point 是 `make_preset` |
| `src/mpc_iml/content.py` | module 與 kit 的 JSON 格式與載入：entry point 群組 `mpc_iml.content`，內建檔案在 `modules/pressure/`、`kits/pressure/` |
| `src/mpc_iml/loops.py` | #173、ADR 0010：`ensemble` 的 loop 檔格式 `mpc-iml-loop`（每個檔一個 bass 或旋律 loop 與其變奏，音高寫成和弦音、`chord`、`semitones`，另有 `offset`、`skeleton`）的驗證 `parse_loop` 與從 content 的 `loops/ensemble/` 讀取的 `load_loops`，以及從 engine 資料夾的 `loops/` 讀取使用者 loop 檔的 `load_user_loops`（壞檔略過並計數）；內建 loop 檔在 `loops/ensemble/`，由 `ensemble.CONTENT`（entry point `ensemble-content`）登記，`ensemble` 建立時讀取，`offset` 經 `Scheduler` 以 tick 播放；`ensemble` 的 `reload-loops` 重新讀取使用者 loop，`bass-loop-step`、`loop-step` 切換 loop，回覆 `loop-errors` 是略過的檔案數，ADR 0009 的修訂 |
| `src/mpc_iml/smf.py` | #173、ADR 0010：Standard MIDI File 的讀寫 `read`、`write`，只用標準函式庫：讀取格式 0 與 1（running status、velocity 0 的 Note On 當 Note Off，略過 meta 與 sysex；SMPTE division 與格式 2 拒絕），寫出格式 0（`write`），`track`、`tempo`、`file` 組成其他檔案；給 loop 的 import、export 與 #166 的 MIDI 下載使用 |
| `src/mpc_iml/loop_midi.py` | #173、ADR 0010：MIDI clip 與 loop 變奏的轉換，不做檔案 I/O：`from_midi` 依和弦進行與起始小節把音高對應到最近的和弦音（小節最後 2 個 step 的非和弦音趨近下一小節的和弦，`chord` 1，同距時取較高的音），step 四捨五入到 16 分音符、餘數存為 `offset`，velocity 轉成權重，channel 2 的音是裝飾音；`to_midi` 寫回 clip，裝飾音在 channel 2；指令 `python -m mpc_iml.loops import <clip.mid>`（`--part`、`--name`、`--variation`、`--into`、`--progression`、`--start-bar`、`--bars`、`--ornament-below`，預設寫到 `./mpc-iml-data/loops/`）、`export <loop> <out.mid>`、`check <檔案>` |
| `src/mpc_iml/generation.py` | 從 kit 產生訓練範例、替換單一 pad 的 take、錄音格式第 2 版的拆分與合併 |
| `src/mpc_iml/webdemo/` | #166：不需硬體的 `ensemble` 網頁 demo；`sim` 以模擬的 MIDI clock 離線執行真正的 `ensemble`（步進格點 → 音符與每小節的表，讀 `Ensemble.plans`；`replay` 依錄下的時間重播 `record --clock` 的錄音，從 Start 到下一個 Stop，最多 64 小節），`synth` 以 numpy 合成鼓、bass 與 keys，`roll` 以 numpy 畫 piano roll，`midifile` 以 `smf` 寫出 type 1 MIDI 檔，`app` 是 Gradio 頁面（步進格點與錄音兩個分頁；只有 `build` 匯入 Gradio），`__main__` 沒有 `demo` extra 時印出安裝提示 |
| `src/mpc_iml/clock.py` | ADR 0008：MIDI clock 的解析、tempo 與小節位置、pad 打擊的格點標記，在格點送出 MIDI 訊息與測試節奏的 `Scheduler`（`/mpciml/clock/test`，`--clock-lead-ms`），以及給 preset 的暫定介面 `ClockAccess`（`Preset.clock`，沒有 `--clock` 時也會呼叫；`on_pad`、`on_bar`（每個小節線收到 `BarStart`，含上一小節的打擊）、`send_now`，以及要求 engine 再送一次 preset 狀態的 `report`），與從錄音標出格點的 `tag_recording`；只用標準函式庫 |
| `src/mpc_iml/patches/` | `patches/mpc-iml.pd` 是適用所有 preset 的 Pure Data 前端（ADR 0006，第 2 組 Kit 與輸出名稱依 ADR 0007，第 9 組 Messages 的 clock 顯示與 `test` 開關依 ADR 0008；`ensemble` 的第 8 組 Ensemble 依 ADR 0009，位於第 7 組右邊的欄，畫布 1490 × 840，loop 以 `<` 名稱 `>` 選擇並有 `reload` 與 `errors`（#173）；`demo`、`pressure` 與 `ensemble` 都指向它） |
