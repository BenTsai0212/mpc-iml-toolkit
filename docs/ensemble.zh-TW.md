# ensemble 指南

[English](ensemble.md) | 繁體中文

內建 preset `ensemble` 的說明，從 [README](../README.zh-TW.md) 移來（#212）。

## 演奏 preset ensemble

內建的 preset `ensemble`（`src/mpc_iml/ensemble.py`，[RFC 0005](rfcs/0005-drum-led-ensemble.md)
的第一步，#138、#144、#148、#158）演奏跟隨鼓的 bass 與旋律。不用模型，也不需要訓練：照常在
MPC Sample 上打鼓。有 `--clock` 時，bass 在固定的和弦進行上循環一段 loop，你每一小節的
**kick** 決定 loop 的下一小節（見[下文](#bass-loop)）。bass 一次只發一個音，以 MIDI 音符送到
虛擬 port `mpc-iml` 的 **channel 2**。同一組和弦上還會在 **channel 3** 循環一段短旋律，你每一
小節怎麼打，決定旋律的下一小節（見[下文](#旋律-loop)）。engine 在任何狀態都會演奏，不需要按
`run`。

每個 pad 有一個角色。預設是 boom-bap 的配置（pad 1 在左下；每個 bank 都一樣）：

| Pad | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| 1-4 | kick | snare | hat（閉合） | hat（開放） |
| 5-8 | kick | snare（clap 或 rim） | hat | other |
| 9-16 | other | other | other | other |

只有 `kick` 會帶出 bass，所以請把 MPC program 的 kick 放在 pad 1 或 5。pad 16 用來切換 bass
的模式（見下文），不發出 bass；pad 15 用來切換旋律（見下文）。

bass 有三種模式：

- **loop**（預設，需要 `--clock`）：持續循環的 bass loop，每一小節的 kick 改變下一小節
  （見 [bass loop](#bass-loop)）。
- **rule**：#138 的規則式 bass，每個 kick 以和弦根音發出一個音符，分為兩層（見下文）。它是
  拿來和 loop 比較的「只有因果」的 bass。
- **off**：沒有 bass。

rule bass 有兩層，可以用控制項 `immediate` 與 `bar`（見 [ensemble 的控制項](#ensemble-的控制項)）
各自開關來比較：

- **immediate**：kick 立刻發出一個 bass 音符，和弦取自該下打擊所在的小節。打得越重越大聲
  （velocity 1-127 變為 50-120）。音符在 2 個 16 分音符後結束（`length`），DAW 沒有播放時則
  在 0.25 秒後結束。
- **bar**（需要 `--clock`）：一個小節中每個 kick 的位置，在**下一個**小節的同一位置以該小節的
  和弦發出 bass 音符。上一小節的 kick 晚一小節回來；沒有 kick 的小節之後就是沒有 bass 的小節。
  第一個 clock tick 之前的打擊不採用。
- **both**（預設）：每個 16 分音符最多一個 bass 音符。在 bar 層即將發出的音符附近打 kick 時，
  你的 kick 發聲，回聲取消；回聲已經發出時，你的 kick 不發出 bass。節奏穩定時聽到的是
  immediate 層；省略某個 kick 的地方，由上一小節的 kick 補上。

和弦取自一個和弦進行：`minor-two`（預設：Am7 兩小節，再 Fmaj7 兩小節）或 `minor-four`
（Dm7、Gm7、Bbmaj7、A7，各一小節），或五個 hip-hop 和弦進行之一（#236）：

| 和弦進行 | 和弦（小節數） |
| --- | --- |
| `dark-minor` | Cm7（2）、Dbmaj7（2）：陰暗的 i–♭II 循環 |
| `lofi-descent` | Fmaj7、Em7、Dm7、Cmaj7（各 1）：lo-fi 的下行 |
| `minor-turn` | Bm7b5（1）、E7（1）、Am7（2）：小調的 ii–V–i |
| `soul-minor` | Am7（2）、Dm7（2）：soul 的 i–iv |
| `two-five-one` | Dm7（1）、G7（1）、Cmaj7（2）：ii–V–I |

loop 的音寫成和弦音，所以每個 loop 都能在每個和弦進行上演奏。和弦性質有 `m7`、`maj7`、`7` 與
`m7b5`（根音、小三度、減五度、小七度）。bass 在第 1 八度演奏（A1 是 MIDI 音符 33）。Live 的
MIDI Clock Type 設為 **Song** 時，Live 的第 1 小節就是和弦進行的開頭。每個和弦進行是套件中的
和弦進行檔（`mpc-iml-progression`，ADR 0011）；`uv run python -m mpc_iml.progressions list`
列出它們與和弦，`uv run python -m mpc_iml.progressions check <檔案>` 檢查一個檔案。

### 為 bass 設定 Live

1. 以 preset 與 clock 啟動 engine，終端機視窗保持開啟。Pure Data 前端也會開啟，並在第 8 組
   **Ensemble** 顯示模式（見[下文](#pure-data-的-ensemble-群組)）；`ensemble` 用不到其中的
   控制項，加上 `--no-patch` 就不會開啟：

   ```bash
   uv run mpc-iml --preset ensemble --clock
   ```

2. 在 Live 的 Settings > Link, Tempo & MIDI > MIDI Ports，為輸出 `mpc-iml clock` 打開
   **Sync**，MIDI Clock Type 設為 **Song**（同[跟隨 DAW 的速度](../README.zh-TW.md#跟隨-daw-的速度midi-clock)），
   並為輸入 `mpc-iml` 打開 **Track**。
3. 新增一條 MIDI 軌並放上 bass 樂器（例如 Live 的 Drift 的 bass preset）。MIDI From 設為
   `mpc-iml`，下方的 channel 設為 **Ch. 2**，Monitor 設為 **In**。
4. 在 Live 按 Play，以 pad 1 的 kick 打一個節奏。在 Live 按 Stop 會結束正在發聲的 bass 音符，
   並取消尚未發出的音符。

按 **pad 16** 依序切換 bass 的 loop → rule → off。終端機會顯示新的模式（`ensemble: bass loop`、
`ensemble: bass rule` 或 `ensemble: bass off`），patch 的第 8 組 **Ensemble** 也會顯示（`next`
立即改變，`now` 在小節線改變）。從下一個小節線開始生效（Live 停止時立即生效）。
preset 從 loop 開始。

沒有 `--clock` 時，`ensemble` 仍會載入，bass 在每個 kick 發出一個音符（immediate 層，loop 模式
也一樣），一律使用第一個和弦與 0.25 秒的音符；bass loop、bar 層與旋律關閉，engine 印出
`ensemble: no MIDI clock (start with --clock); bass loop, bar layer and melody off, bass plays on each kick`。
有 `--clock` 時，DAW 停止或尚未開始播放期間，rule bass 也是這樣演奏，bass loop 則等 Live 開始
播放。

### bass loop

有 `--clock` 且 Live 正在播放時，loop 模式的 bass 演奏以和弦音寫成的 loop（與旋律相同，見
[下文](#旋律-loop)），所以會跟著和弦進行的每個和弦走。它的趨近音與經過音瞄準**下一個**小節的
和弦：在下一個根音的半音或全音之下，帶進和弦的轉換。有六個 loop：

- `boom`（預設）：一小節、有休止的 boom-bap 線條：第 1 拍的根音與第 3 拍的五度、一個 ghost
  note、高八度的根音，以及進入下一小節的趨近音。
- `walk`：兩小節、動得更多的線條，有一個經過音與幾個趨近音。
- `knock`：兩小節的 boom-bap 線條，由根音、五度與 ghost 七度組成（#232）。
- `lazy`：兩小節的 lo-fi 線條，稍微落在拍子後面（#232）。
- `soul`：兩小節、有旋律的線條，上到八度再下來，以半音往上走進下一小節（#232）。
- `sub`：兩小節的 half-time 線條，長的根音加上一個八度的跳音，像 808（#232）。

每個 loop 有三個**變奏**，每個都是完整的 bass 線條（#158）：`home`（上面描述的 loop）、`push`
（提前一個 16 分音符的音，回應往前推的 kick）與 `drive`（`boom` 是 8 分音符，`walk` 是四分音符的
walking）。每個變奏有完整的線條（層級 1），上面再加**裝飾音**（層級 2：ghost note 與經過音），
所以稀疏的小節不會只剩骨架。

**kick 每小節改變 loop 一次。** bass 只聽 **kick** pad。每到小節線，剛結束那一小節的 kick
決定下一整個小節：

| 你上一小節的 kick | bass 的下一小節 |
| --- | --- |
| kick 的位置與數目 | **變奏**：5 下以上奏 `drive`；否則有 kick 不在四分音符的格點上（往前推或切分的 kick）就奏 `push`；否則（1-4 下都在拍上）奏 `home`。 |
| kick 的數目 | **裝飾音**：3 下以上在完整的線條上加上裝飾音。 |
| kick 的平均 velocity | **音量**：velocity 1-127 變為 50-120。 |
| kick 的位置 | **重音**：離你打 kick 的位置在一個 16 分音符以內的 bass 音符保持完整的 velocity，其他音符以其 0.8 演奏，讓線條貼著你的 kick 節奏。 |

沒有 kick 的小節（只有 snare 與 hat 的小節也算）依 `no-drums` 的設定（見[鼓停下時](#鼓停下時)）：
預設 bass 繼續奏 `home` 的線條。在 Live 按 Start 之後，bass 會等你的第一個 kick。pad 15 與 16
的打擊不計入。

pad 15（見下文）也會在 **follow** 與 **fixed** 之間切換 bass loop：fixed 不論 kick 怎麼打，都以
velocity 100、不加重音奏出 `home` 變奏的所有音符（與 #158 之前相同的音符）。pad 15 的 **off** 只關掉旋律；bass loop 保持
fixed，直到再按一次 pad 15 回到 follow。

### 旋律 loop

有 `--clock` 且 Live 正在播放時，`ensemble` 在和弦進行上循環一段短旋律，以 MIDI 音符送到
`mpc-iml` 的 **channel 3**（`src/mpc_iml/melody.py`）。音符以和弦音（根音、三度、五度、七度）
寫成，所以 loop 會跟著每個和弦走，和弦從小調換成大調時也一樣。有六個 loop：

- `keys`（預設）：稀疏的兩小節鍵盤 riff。
- `pluck`：一小節的 8 分音符琶音。
- `rhodes`：兩小節的 Rhodes 和弦（三度、七度與九度同時）（#232）。
- `flute`：兩小節的主奏動機，由三度、九度與根音組成（#232）。
- `horns`：短促的 soul 銅管，一次兩個音（#232）。
- `bells`：高音、稀疏的 lo-fi 鐘聲，稍微落在拍子後面（#232）。

hip-hop 的 loop（`knock` 到 `bells`）也會奏和弦音以外的音：九度（根音往上一個全音）與趨近音；
下文的變奏描述的是 `keys` 與 `pluck`，其他 loop 的描述在它們的 loop 檔案中。`rhodes` 與 `horns`
有幾個音同時開始，它們全部都會發聲；surprise `passing` 會移動最後一個 step 上和弦的每一個音。

旋律從第 4 八度開始（A4 是 MIDI 音符 69）。與 bass 相同，每個 loop 有三個變奏，每個都是完整的
線條，上面再加裝飾音（#158）：`home`（上面描述的 loop）、`open`（較長的音：`keys` 在第一小節
提問、高八度回答，`pluck` 是往上到持續七度的四分音符琶音）與 `busy`（`keys` 是反拍 8 分音符上的
短促和弦，`pluck` 是跨兩個八度的 16 分音符琶音）。

**鼓每小節改變 loop 一次。** 每到小節線，剛結束那一小節的打擊決定下一整個小節；小節中間不會
改變：

| 你的上一小節 | 旋律的下一小節 |
| --- | --- |
| 打擊數（所有 pad）與 hat | **變奏**：hat 落在奇數的 16 分音符上（16 分音符的 hat）或 14 下以上奏 `busy`；5 下以下（鼓留出空間）奏 `open`；否則奏 `home`。 |
| 打擊數 | **裝飾音**：8 下以上在完整的線條上加上裝飾音。 |
| 平均 velocity | **音量**：velocity 1-127 變為 50-120，與 bass 相同。 |
| `hat` pad 的打擊 | **亮度**：在小節線於 channel 3 送出 CC 74，目標從沒有 hat 時的 48 到 16 下以上的 110，每小節與上一小節最多相差 24，突然的變化分散到幾個小節（#218）。在 Live 中把它對應到濾波器或亮度旋鈕。 |

所以只有 kick 與 snare 帶出較有旋律感的 `open`，8 分音符的 hat 帶出 `home` 與其裝飾音，16 分
音符的 hat 帶出 `busy`。空小節依 `no-drums`（見[鼓停下時](#鼓停下時)）。在 Live 按 Start 之後，
旋律會等你的第一下打擊。pad 15 與 16 的打擊不計入。

按 **pad 15** 依序切換 follow → fixed → off。**fixed** 不論鼓怎麼打，都以 velocity 100 奏出
旋律 loop 的 `home` 變奏的所有音符、不送 CC，也以 velocity 100、不加重音奏出 bass loop 的 `home`
的所有音符（與 #158 之前相同的音符，沒有 surprise），可以拿來和 **follow** 比較。**off** 只關掉旋律（bass loop 保持 fixed）。終端機會顯示新的模式
（`ensemble: melody follow`、`ensemble: melody fixed` 或 `ensemble: melody off`），patch 的
第 8 組 **Ensemble** 也會顯示，從下一個小節線開始生效。preset 從 follow 開始。

**still**（#233，控制項 `melody-mode still`，用於盲測與練習）讓旋律保持不變、bass 照常跟隨：
不論鼓怎麼打、包括沒有鼓的小節，旋律 loop 每小節都以 velocity 100 奏出 `home` 變奏與裝飾音，
並在每個小節線以同一個值（79）送出亮度 CC（不淡出也不停止；`no-drums` 與 `fade-bars` 只作用於
bass）。bass 與 follow 時一樣跟隨 kick，規則、學習、`want` 與 pad 16 都照常。學習不選擇旋律的
變奏：like 只計入 bass，`learn demo` 時 pad 15 與 `want melody` 不做任何事（終端機顯示
`ensemble: pad 15 ignored, the melody is still`）。pad 15 不會切換到 still：從 still 按下會到
fixed，再到 off 與 follow。`chose` 與狀態行中旋律的來源為 `still`。

要在 Live 聽到旋律，新增第二條 MIDI 軌並放上鍵盤樂器（例如電鋼琴，或 Drift 的 pluck preset）。
MIDI From 設為 `mpc-iml`，channel 設為 **Ch. 3**，Monitor 設為 **In**。在 Live 按 Stop 會結束
正在發聲的旋律音符。

以 **learn CC** 把 CC 74 對應到樂器的濾波器 cutoff（#159）。Live 播放時，旋律在 channel 3 的音符
會在每個小節線比 CC 早到 Live，MIDI Map Mode 會抓到音符而不是 CC：

1. 停止 Live（engine 繼續執行）。
2. 在 Live 按右上角的 **MIDI**（或按 Cmd-M），再點選鍵盤樂器的濾波器旋鈕。
3. 點 patch 第 8 組 **Ensemble** 的 **learn_CC**（或送出 `/mpciml/preset/ensemble/learn-cc`）。它
   只在 channel 3 送出 CC 74（旁邊的標示顯示 `CC 74 ch 3`），是一段短的掃動，不送其他訊息。
   對應時不要打 pad：Live 停止時 kick 也會發出 bass 音符。
4. 再按一次 **MIDI**。再點一次 **learn_CC** 會把旋鈕掃回去，也可以確認對應。

接著啟動 Live 並打 `hat` pad：濾波器在下一個小節線改變。Live 播放時，`learn-cc` 得到
`/mpciml/error bad_arguments`。

### 鼓停下時

停止打鼓時，樂團繼續演奏，把焦點交給旋律，就像鼓手停打幾小節時期待的那樣（#158）。控制項
`no-drums`（見 [ensemble 的控制項](#ensemble-的控制項)）決定 loop 在沒有鼓的小節（bass 是沒有 kick
的小節）演奏什麼：

| `no-drums` | 沒有鼓的小節 |
| --- | --- |
| `lead`（預設） | 旋律奏 `open` 變奏加上裝飾音（往前帶的線條）；bass 奏 `home` 的線條、不加裝飾音，讓出空間。 |
| `hold` | 兩者都保持最後一個有鼓的小節的變奏與裝飾音。 |
| `thin` | #158 之前的規則，用來比較：一個空小節奏 loop 的骨架（`boom` 是根音與五度），連續兩個則停止。 |

`lead` 與 `hold` 時，loop 在 `fade-bars` 個空小節內（預設 8）保持你最後一個有鼓的小節的音量；
其中最後兩個小節淡出（該 velocity 的 0.7，再來 0.4），之後 loop 停止。`fade-bars 0` 不會停止。
亮度的 CC 保持原值。下一次打擊之後的小節 loop 回來，奏那一小節選出的變奏。fixed 模式一直演奏。

### 一點驚喜

每個 4 小節樂句的最後一小節有 1/2 的機率出現一個你沒有直接要求的變化（#158）。`surprise 1`
（預設，#178）時是第 4 拍的 bass **fill**（根音、五度、八度與進入下一小節的趨近音組成的 16 分音符
音群）。`surprise 2` 再加上兩種旋律的 surprise：旋律在該小節高八度（**octave**），或**經過音**
（**passing**：旋律在該小節的最後一個音改為下一小節和弦音的半音之下）。終端機會顯示每一次（`ensemble: surprise fill in bar 7`）。surprise 只出現在
跟隨鼓或沒有鼓時繼續演奏的小節，fixed 模式、`no-drums thin` 與淡出的小節不會出現。rule bass 時
沒有 fill，旋律關掉時只有 fill。`surprise 0` 關掉它。抽選是隨機的，每次載入 `ensemble` 都用新的
種子。

### 寫自己的 bass 線條

loop 是 loop 檔案（ADR 0010）：上面列出的 loop 是內建的，你也可以不修改工具包
就加入自己的 loop（#173）。在 Live 寫一段線條，轉成 loop 檔案，然後演奏：

1. 在 Live 建立一個 1、2 或 4 小節、從小節線開始的 MIDI clip，在 `minor-two` 的和弦上寫 bass
   線條：**Am7** 2 小節，再 **Fmaj7** 2 小節（或 `minor-four`：Dm7、Gm7、B♭maj7、A7，各 1 小節）。
   寫在 A1（MIDI note 33）附近，這是 bass 預設的八度；旋律是 A4。照你想要的方式演奏：不在格線上的
   音、ghost note 與和弦外音都會保留。
2. 在 clip 上按右鍵，選 **Export MIDI Clip…**，例如存成 `my-boom.mid`。
3. 在工具包的資料夾把它轉成 loop 檔案。名稱由小寫英文字母、數字與連字號組成：

   ```bash
   uv run python -m mpc_iml.loops import my-boom.mid --part bass --name my-boom
   ```

   這會寫出 `mpc-iml-data/loops/my-boom.json`（`uv run mpc-iml` 的資料夾），並印出音符如何被讀取：
   和弦音、進入下一個和弦的趨近音、其他音，以及不在格線上的音（保留為 `offset`）。每個音都存成和弦音，
   所以換和弦進行時線條會跟著和弦走。在 `minor-four` 上寫的話加 `--progression minor-four`（也可以是你自己的和弦進行，從 `--data` 讀取，預設 `mpc-iml-data`）；clip 從
   Fmaj7 開始時加 `--start-bar 2`；加 `--ornament-below 60` 會把 velocity 低於 60 的音當作裝飾音
   （只在鼓打得較密時演奏）。
4. 這個 clip 是 `home` 變奏。要加入給往前推的 kick 與密集 kick 的變奏，再寫兩個 clip，加到同一個
   檔案：

   ```bash
   uv run python -m mpc_iml.loops import my-boom-push.mid --variation push --into mpc-iml-data/loops/my-boom.json
   uv run python -m mpc_iml.loops import my-boom-drive.mid --variation drive --into mpc-iml-data/loops/my-boom.json
   ```

   沒有寫的變奏會演奏 `home`。旋律用 `--part melody`，變奏是 `open` 與 `busy`。
5. 在第 8 組 **Ensemble**（見[下文](#pure-data-的-ensemble-群組)）按 **reload**，再以 `bass loop`
   旁的 `<` `>` 選擇這段線條。每次載入 `ensemble` 時，engine 也會讀取這個資料夾。無法使用的檔案會被
   略過：終端機顯示檔名與原因，第 8 組的 `errors` 顯示略過的檔案數。
   `uv run python -m mpc_iml.loops check mpc-iml-data/loops/my-boom.json` 不需要 engine 就能檢查檔案。

要從內建的線條開始，把它匯出成 clip，拖進 Live 再修改：
`uv run python -m mpc_iml.loops export boom boom.mid`（其他變奏加 `--variation push`）。kick 的規則、
裝飾音與 bass 的 fill 對你的線條與內建的線條一樣有效。

### 寫自己的和弦進行

和弦進行是一個小 JSON 檔（ADR 0011），不必改工具包就能加入自己的和弦（#236）。存成
`mpc-iml-data/progressions/<名稱>.json`，檔名等於 `name`（小寫英文字母、數字與連字號）：

```json
{
  "format": "mpc-iml-progression",
  "format_version": 1,
  "name": "my-two",
  "preset": "ensemble",
  "tonic": "Bb",
  "chords": [
    {"root": 0, "quality": "m7", "bars": 2},
    {"root": 5, "quality": "7", "bars": 2}
  ]
}
```

- `tonic` 是音名：`C` 到 `B`，可加 `#` 或 `b`。
- 每個和弦有 `root`（0-11，主音之上的半音數）、`quality`（`m7`、`maj7`、`7` 或 `m7b5`）與
  `bars`（1-4，預設 1）。最多 8 個和弦，全長 1、2、4 或 8 小節。這個例子先 Bbm7 兩小節，再
  Eb7 兩小節。

以 `uv run python -m mpc_iml.progressions check mpc-iml-data/progressions/my-two.json` 檢查，
再按群組 8 的 **reload**（同時重新讀取你的 loop 與和弦進行），用 `progression` 旁的 `<` `>`
選擇。你的和弦進行排在內建的之後；`uv run python -m mpc_iml.progressions list --data mpc-iml-data`
列出全部。無法使用或名稱重複的檔案會略過：終端機寫出檔名與原因，回覆 `progression-errors`
是略過的檔案數（群組 8 的 `errors` 只計 loop 檔）。reload 之後，改過的檔案從下一小節開始；
刪掉正在演奏的和弦進行的檔案時，它會繼續演奏，直到你選擇另一個。

### Pure Data 的 Ensemble 群組

patch（`src/mpc_iml/patches/mpc-iml.pd`，ADR 0009）的第 8 組 **Ensemble** 位於第 7 組
**Outputs** 右邊的欄，顯示 `ensemble` 正在演奏的內容，並以點擊切換模式、loop 與和弦進行。以
第 1 組 **Connect** 的 preset 按鈕載入 `ensemble`，或以 `--preset ensemble` 啟動。整個 patch
在 14 吋 MacBook 的螢幕上不必捲動就能看到全部（1490 × 840）。

| 群組中的項目 | 作用 |
| --- | --- |
| `bass`：`loop`、`rule`、`off` | 設定 bass 的模式。`now` 顯示正在演奏的模式，`next` 顯示要求的模式。 |
| `melody`：`follow`、`fixed`、`off` | 設定旋律的模式（`melody-mode`），`now` 與 `next` 同 bass。`still`（#233）沒有按鈕；以控制項設定時 `now` 與 `next` 會顯示。 |
| `bass loop`、`melody loop` | `<` 與 `>` 選擇 engine 列出的上一個或下一個 loop（內建的 loop 依名稱排列；再來是安裝的與你自己的 loop），下方的方塊顯示選擇的 loop。 |
| `reload`、`errors` | `reload` 重新讀取你的 loop 與和弦進行檔案（`reload-loops`，見[寫自己的 bass 線條](#寫自己的-bass-線條)、[寫自己的和弦進行](#寫自己的和弦進行)）；`errors` 顯示略過的 loop 檔案數（`loop-errors`）。 |
| `progression` | `<` 與 `>` 選擇 engine 列出的上一個或下一個和弦進行（`minor-two`、`minor-four`，再來是其他的依名稱排列），下方的方塊顯示選擇的和弦進行。 |
| `octave`、`melody octave` | bass 的八度（0-3）與旋律的八度（2-6）的數字方塊。 |
| `roles` | 每個 pad 的角色，唯讀，與 pad 一樣排成 4 列 4 個（13-16 在最上面）。 |
| `learn_CC`、`CC`、`ch` | 送出 `learn-cc`，在 Live 對應亮度的 CC（[旋律 loop](#旋律-loop)）；`CC` 與 `ch` 顯示它送出的 CC 與 channel（`filter-cc`、`melody-channel`）。 |

如標題旁的文字所說，Live 播放時，改變從下一個小節線開始。在 MPC 上按 pad 15 或 16 也會顯示在
群組中：`next` 立即改變，`now` 在該模式開始演奏的小節線改變；Live 停止時兩者都立即改變。沒有
`--clock` 時，旋律不會演奏，所以旋律的 `now` 一直是 `off`。

這個群組一直存在。載入其他 preset 時，它的方塊顯示 `-`（八度的數字方塊保留最後的數字），點擊會在
第 9 組 **Messages** 的狀態列得到 `inactive_preset`：請先載入 `ensemble`。pad 的角色、MIDI
channel、`length`、`immediate`、`bar`、`filter-cc`、切換模式的 pad、`no-drums`、`fade-bars` 與 `surprise` 仍只能以 OSC 設定（見
[ensemble 的控制項](#ensemble-的控制項)）。Max for Live 裝置沒有 Ensemble 群組。

### ensemble 的控制項

控制項是送到 engine 控制 port（6450）的 preset 訊息。Pure Data patch 的第 8 組 **Ensemble**
（見[上文](#pure-data-的-ensemble-群組)）送出常用的控制項；其他的請從任何 OSC client 送出：

| 訊息 | 值 | 預設 | 意義 |
| --- | --- | --- | --- |
| `/mpciml/preset/ensemble/bass` | `loop`、`rule` 或 `off` | `loop` | bass 的模式 |
| `/mpciml/preset/ensemble/bass-loop` | bass loop 的名稱（內建的 loop，例如 `walk` 或 `knock`，或你自己的） | `boom` | bass 的 loop |
| `/mpciml/preset/ensemble/bass-loop-step` | 1 或 -1 | - | `bass-loops` 中的下一個或上一個 bass loop，到尾端時繞回 |
| `/mpciml/preset/ensemble/immediate` | 0 或 1 | 1 | rule bass 的 immediate 層 |
| `/mpciml/preset/ensemble/bar` | 0 或 1 | 1 | rule bass 的 bar 層 |
| `/mpciml/preset/ensemble/progression` | 和弦進行的名稱（`progressions`） | `minor-two` | 和弦進行 |
| `/mpciml/preset/ensemble/progression-step` | 1 或 -1 | - | `progressions` 中的下一個或上一個和弦進行，到尾端時繞回 |
| `/mpciml/preset/ensemble/octave` | 0-3 | 1 | bass 的八度（1 時為 A1） |
| `/mpciml/preset/ensemble/length` | 1-16 | 2 | rule bass 的音符長度（16 分音符數） |
| `/mpciml/preset/ensemble/channel` | 1-16 | 2 | bass 的 MIDI channel |
| `/mpciml/preset/ensemble/role` | pad 1-16，再接 `kick`、`snare`、`hat` 或 `other` | 上表 | 一個 pad 的角色，所有 bank 都適用 |
| `/mpciml/preset/ensemble/layer-pad` | 0-16 | 16 | 切換 bass 模式的 pad；0 表示不使用 |
| `/mpciml/preset/ensemble/melody-mode` | `follow`、`fixed`、`off` 或 `still` | `follow` | 以一則訊息設定旋律的模式（設定 `melody` 與 `follow`）；`off` 也取消尚未發出的音符；`still`（#233）：旋律奏 `home`、bass 照常跟隨 |
| `/mpciml/preset/ensemble/melody` | 0、1 或 `still` | 1 | 旋律；0 時也取消尚未發出的音符，1 以原本的模式開啟，`still` 以 `melody-mode still` 開啟 |
| `/mpciml/preset/ensemble/loop` | 旋律 loop 的名稱（內建的 loop，例如 `pluck` 或 `rhodes`，或你自己的） | `keys` | 旋律的 loop |
| `/mpciml/preset/ensemble/loop-step` | 1 或 -1 | - | `loops` 中的下一個或上一個旋律 loop，到尾端時繞回 |
| `/mpciml/preset/ensemble/reload-loops` | 無 | - | 重新讀取 `<資料夾>/loops/` 中的 loop 檔案與 `<資料夾>/progressions/` 中的和弦進行檔案；改變的 loop 從下一個小節線開始演奏，改變的和弦進行從下一小節開始 |
| `/mpciml/preset/ensemble/follow` | 0 或 1 | 1 | 1：鼓改變 bass 與旋律的 loop；0：fixed；兩者都結束 `still` |
| `/mpciml/preset/ensemble/melody-octave` | 2-6 | 4 | 旋律的八度（4 時為 A4） |
| `/mpciml/preset/ensemble/melody-channel` | 1-16 | 3 | 旋律與其 CC 的 MIDI channel |
| `/mpciml/preset/ensemble/filter-cc` | 0-127 | 74 | 亮度的 CC；0 表示不送 |
| `/mpciml/preset/ensemble/melody-pad` | 0-16 | 15 | 切換旋律的 pad；0 表示不使用 |
| `/mpciml/preset/ensemble/learn-cc` | 無 | - | 只在旋律的 channel 送出亮度的 CC（0、32、64、96、127，下一則訊息往下），讓 DAW 對應；clock 執行中或 `filter-cc` 為 0 時拒絕 |
| `/mpciml/preset/ensemble/no-drums` | `lead`、`hold` 或 `thin` | `lead` | 兩個 loop 在沒有鼓的小節演奏什麼（[鼓停下時](#鼓停下時)） |
| `/mpciml/preset/ensemble/fade-bars` | 0-32 | 8 | loop 停止前的空小節數（最後兩個淡出）；0 不會停止 |
| `/mpciml/preset/ensemble/surprise` | 0-2（0 關閉，1 只有 bass fill，2 再加上旋律的 surprise） | 1 | 每個 4 小節樂句結尾的 surprise（[一點驚喜](#一點驚喜)） |
| `/mpciml/preset/ensemble/rhythm` | 0、1 或 2 | 0 | 1：bass 線條的音移向上一小節的 kick（每個 4 小節樂句的第一小節照原樣，之後移動，最後一小節再晚一個 16 分音符）；2：旋律的音也移向上一小節的 snare 與 hat（每個樂句的第一小節照原樣）；0：照寫好的線條。#194 之前預設為 1：人工檢查時，在 hip-hop 等穩定的風格中，移動的 bass 有時聽起來不在拍上 |
| `/mpciml/preset/ensemble/learn` | `off`、`likes` 或 `demo` | `off` | `likes`：每個 loop 的變奏來自你的「喜歡」教給它的選擇，從規則開始，pad 16 改為**喜歡**而不切換 bass 模式（bass 模式在演奏前設定）；`demo`：pad 16 與 15 選擇你要的 bass 與旋律變奏，該 loop 演奏它，每個這樣打鼓的小節成為一個範例，`auto` 演奏範例教給的選擇（決策樹；少於 4 個範例或只有一種變奏時用規則）；`off`：規則（#196） |
| `/mpciml/preset/ensemble/like` | 無 | - | 與 `learn likes` 時的 pad 16 相同：喜歡樂團在這個小節演奏的內容（第一拍內是上一小節）；`learn off` 或 clock 未執行時拒絕 |
| `/mpciml/preset/ensemble/want` | `bass` 或 `melody`，接 `auto` 或它的一個變奏 | `auto` | 與 `learn demo` 時的 pad 16、15 相同：你要該 loop 演奏並學習的變奏；不是 `learn demo` 時拒絕 |
| `/mpciml/preset/ensemble/save-profile` | 無 | - | 立即把學到的內容存到資料夾的 `learn/ensemble.json`（profile）；`learn likes` 或 `demo` 時每個 4 小節樂句開頭也會儲存 |
| `/mpciml/preset/ensemble/load-profile` | 無 | - | 重新讀取 profile（載入 `ensemble` 時也會讀取）；檔案不存在或無法讀取時拒絕 |
| `/mpciml/preset/ensemble/reset-learning` | 無 | - | 回到規則：忘記喜歡的權重與範例（檔案在下次儲存時才改變）；`uv run python -m mpc_iml.learn show` 不需要 engine 就能印出 profile |
| `/mpciml/preset/ensemble/learn-log` | 0 或 1 | 0 | 1：每小節在資料夾的新檔 `learn/log-<時間>.jsonl` 寫一行（情境、各 loop 演奏的內容與來源、規則的選擇、喜歡、範例），用來比較學習模式，不改變演奏；0：寫完並關閉；`uv run python -m mpc_iml.learn summary <log>` 印出每個模式的喜歡比例、與規則不同的比例與範例數 |
| `/mpciml/preset/ensemble/mode-pads` | 0 或 1 | 1 | 1：pad 15、16 切換旋律與 bass 的模式；0：不切換模式（`learn likes` 時仍是喜歡、`learn demo` 時仍是想要的變奏），盲測比較時送出（[盲測比較](trials.md)） |
| `/mpciml/preset/ensemble/status` | 0 或 1 | 1 | 1：clock 執行時，每個小節線與每次按 pad 16、15 後在終端機印出一行狀態（見下文）；0：不印，盲測比較時送出（[盲測比較](trials.md)）。clock 未執行時被忽略的按壓兩種設定都會印出 |

再次載入 `ensemble` 或重新啟動 engine 時，設定回到預設值。值不正確時得到
`/mpciml/error bad_arguments`；載入其他 preset 時送給 `ensemble` 的訊息得到
`inactive_preset`。bass 的模式與旋律的控制項從下一個小節線開始生效。

**狀態回覆**（協定 1.5，ADR 0009）：engine 在 `preset/load` 之後、完整狀態中（`hello`、
`state/get`）、每個成功的控制項之後、按 pad 15 或 16 之後，以及正在演奏的 bass 或旋律模式、正在演奏的
變奏或轉換改變的小節線，把 `ensemble` 的完整狀態以 `/mpciml/preset/ensemble/<reply>` 訊息送到回覆 port
（6451）：

| 回覆 | 參數 |
| --- | --- |
| `bass` | 下一個與正在演奏的模式（`loop`、`rule`、`off`） |
| `melody-mode` | 下一個與正在演奏的模式（`follow`、`fixed`、`off`、`still`） |
| `bass-loop`、`loop`、`progression` | 選擇的名稱 |
| `bass-loops`、`loops`、`progressions` | 可選擇的名稱（loop：內建、安裝的、你自己的，各依名稱排序；和弦進行：`minor-two`、`minor-four`，再來是其他內建的依名稱排列，然後是安裝的，最後是你自己的） |
| `octave`、`melody-octave`、`channel`、`melody-channel`、`length`、`filter-cc`、`layer-pad`、`melody-pad`、`immediate`、`bar` | 值（`immediate` 與 `bar` 為 0 或 1） |
| `roles` | 16 個角色，pad 1-16 |
| `no-drums` | 值（`lead`、`hold`、`thin`） |
| `fade-bars`、`surprise` | 值（`surprise` 為 0-2） |
| `variation` | 正在演奏的 bass 變奏與旋律變奏（該 loop 靜音、不是 loop 或沒有 `--clock` 時為 `-`） |
| `loop-errors` | 上次讀取時略過的 loop 檔案數 |
| `rhythm` | 值（0、1 或 2） |
| `transform` | 正在演奏的 bass 與旋律的轉換（`plain`、`lock`、`answer`、`backbeat`；該 loop 靜音、不是 loop 或沒有 `--clock` 時為 `-`） |
| `learn` | 學習模式（`off`、`likes`、`demo`） |
| `likes` | 載入 `ensemble` 之後計入選擇的「喜歡」次數 |
| `chose` | 正在演奏的 bass 與旋律變奏的來源（`rule`、`bandit`、`model`、`want`，`melody-mode still` 時旋律為 `still`；該 loop 靜音、不是 loop 或沒有 `--clock` 時為 `-`） |
| `learned` | 最多 4 個 `<部分>:<情境>><變奏>`，學到的最高選擇與規則不同的情境（沒有時為 `-`） |
| `want` | `learn demo` 時你要的 bass 與旋律變奏（沒有時為 `auto`） |
| `examples` | 以 `learn demo` 示範的 bass 與旋律範例數（含 profile 中的範例） |
| `profile-errors` | 上次讀取 profile 失敗時為 1（演奏規則，樂句開頭不覆寫該檔），否則為 0 |
| `learn-log` | 寫出每小節的 log 時為 1，否則為 0 |
| `mode-pads` | pad 15、16 切換模式時為 1，否則為 0 |
| `status` | 印出狀態行時為 1，否則為 0 |
| `progression-errors` | 上次讀取時略過的和弦進行檔案數 |

名稱與參數依 preset 的版本管理（ADR 0004）。

**狀態行**（#230）：`status 1`（預設）時，終端機在 Live 演奏中的每個小節線，以及每次按
pad 16、15 之後印出一行，例如：

```text
ensemble: bar 12  Am7  bass drive (rule)  melody home (rule)  16: keep drive  15: keep home
```

依序是小節（從 Start 的 0 起算）與它在演奏中的和弦進行裡的和弦（#236）、bass 與旋律正在演奏的變奏與選擇的來源（`rule`、`bandit`、
`model`、`want`，`melody-mode still` 時旋律為 `still`；該 loop 不發聲時為 `-`），以及現在按 pad 16、15 會做什麼：`learn demo` 時為
`keep <變奏>`、`next <變奏>`，`learn likes` 時 pad 16 為 `like`，`mode-pads 1` 時為切換到的模式
（`bass rule`、`melody fixed`），什麼都不做時（`mode-pads 0`，或 `learn demo` 且 `melody-mode still`
時的 pad 15）為 `-`。clock 未執行（Live 停止或預備拍）時按
pad 16、15 而沒有作用，會印出 `ensemble: pad 16 ignored, the clock is not running`，`status 0`
時也會印出。狀態行只用於顯示，不改變演奏。

### 比較兩層

#138 的人工檢查，使用 MPC Sample、依上文設定好的 Live，速度約 90 BPM：

1. 按一次 pad 16，讓終端機顯示 `ensemble: bass rule`。
2. 以 boom-bap 節奏（pad 1 為 kick、pad 2 為 snare、pad 3 為 hat）在每種設定各演奏 5 分鐘：
   只有 **immediate**（送 `bar 0`）、只有 **bar**（`immediate 0`、`bar 1`）、**both**
   （`immediate 1`、`bar 1`），以上文的控制項切換。
3. 每一段結束後寫一列：

   | 模式 | 好玩（1-5） | 像我（1-5） | 備註 |
   | --- | --- | --- | --- |
   | immediate | | | 時間點；bass 是否跟著 kick？ |
   | bar | | | |
   | both | | | |

4. bass 正在發聲時在 Live 按 Stop，確認沒有音符持續發聲。

### 檢查旋律

#144 的人工檢查，使用 MPC Sample、依上文為 bass 與旋律設定好的 Live（bass 在 Ch. 2，鍵盤在
Ch. 3 並以 **learn_CC** 把 CC 74 對應到濾波器，見[旋律 loop](#旋律-loop)）、為 `mpc-iml clock` 打開 Sync 且 MIDI Clock Type 為 **Song**，
並執行 `uv run mpc-iml --preset ensemble --clock`：

1. 旋律 **follow**（終端機顯示 `ensemble: melody follow`）演奏 5 分鐘：稀疏的小節（只有 kick 與
   snare）與忙碌的小節（8 或 16 分音符的 hat、重擊）交替，並停打一小節與兩小節。
2. 旋律 **fixed**（按一次 pad 15）以同樣的節奏演奏 5 分鐘。
3. 每一段結束後寫一列：

   | 旋律 | 好玩（1-5） | 像我（1-5） | 備註 |
   | --- | --- | --- | --- |
   | follow | | | 密度、音量與亮度的變化，聽起來是鼓造成的嗎？晚一小節的反應自然嗎？兩個空小節後停止恰當嗎？ |
   | fixed | | | |

4. 兩者都在發聲時在 Live 按 Stop，確認兩個 channel 都沒有音符持續發聲。

### 檢查 bass loop

#148 的人工檢查：bass 與旋律有鼓所帶動的音樂內容時，音樂家是否覺得自己在帶領樂團？比較
**兩者**（內容與因果）、**只有內容**（loop 固定）與**只有因果**（rule bass）。依
[檢查旋律](#檢查旋律)設定 MPC Sample 與 Live，執行 `uv run mpc-iml --preset ensemble --clock`，
速度約 90 BPM。

每一段都用同樣的 boom-bap 節奏，各約 5 分鐘：稀疏的小節（只有 kick 與 snare）、忙碌的小節
（16 分音符的 hat、4-5 個 kick、重擊），再停打一小節與兩小節。

| 段落 | 設定 | 比較 |
| --- | --- | --- |
| 1. 兩者 | 預設：`ensemble: bass loop`、`ensemble: melody follow` | 內容**與**因果 |
| 2. 只有內容 | 按一次 pad 15：`ensemble: melody fixed`（兩個 loop 都固定） | 沒有因果的內容 |
| 3. 只有因果 | 按一次 pad 16：`ensemble: bass rule`；再按一次 pad 15：`ensemble: melody off` | 只有 #138 的 bass |

1. 依序演奏三段，每次按 pad 後確認終端機。
2. 每一段結束後寫一列：

   | 段落 | 好玩（1-5） | 像我（1-5） | 備註 |
   | --- | --- | --- | --- |
   | 兩者 | | | 是否覺得自己在帶領樂團？bass 的密度、音量與重音，聽起來是 kick 造成的嗎？沒有 kick 的小節 bass 變薄恰當嗎？ |
   | 只有內容 | | | |
   | 只有因果 | | | |

3. bass 與旋律都在發聲時在 Live 按 Stop，確認 channel 2 與 3 都沒有音符持續發聲。

### 檢查變奏

#158 的人工檢查：以變奏、而不是減少音符來跟隨鼓，是否讓與樂團一起演奏更好玩？以相同的設定、相同的
boom-bap 節奏（稀疏的小節、忙碌的小節，再停打一小節與兩小節），各約 5 分鐘，重複
[檢查 bass loop](#檢查-bass-loop) 的三段。預設是 `no-drums lead`、`fade-bars 8` 與 `surprise 1`。

1. **兩者**：預設（`ensemble: bass loop`、`ensemble: melody follow`）。也試試不在拍上的 kick（例如
   第 2 拍的反拍）、16 分音符的 hat，以及停打 10 小節以上。
2. **只有內容**：按一次 pad 15（`ensemble: melody fixed`）。
3. **只有因果**：按一次 pad 16（`ensemble: bass rule`）；再按一次 pad 15（`ensemble: melody off`）。
4. 每一段結束後寫一列：

   | 段落 | 好玩（1-5） | 像我（1-5） | 備註 |
   | --- | --- | --- | --- |
   | 兩者 | | | 稀疏的小節中，bass 聽起來是完整的 bass 線條嗎？停打時焦點是否交給了旋律，8 個空小節之後發生什麼事？改變鼓（不在拍上的 kick、16 分音符的 hat、稀疏的小節）是否帶出聽得出不同的音樂？樂句結尾的 surprise 是受歡迎還是干擾？ |
   | 只有內容 | | | |
   | 只有因果 | | | |

5. 選擇性：以 `no-drums thin` 或 `surprise 0` 再演奏一次第 1 段來比較。
6. bass 與旋律都在發聲時在 Live 按 Stop，確認 channel 2 與 3 都沒有音符持續發聲。

### 檢查 Ensemble 群組

#153 的人工檢查，依上文設定好 Live，為 `mpc-iml clock` 打開 Sync，執行
`uv run mpc-iml --clock`（patch 會開啟）：

1. 按第 1 組的 preset 按鈕 `ensemble`。第 8 組 **Ensemble** 顯示預設值：bass `loop`/`loop`、
   旋律 `follow`/`follow`、`boom`、`keys`、`minor-two`、八度 1 與 4，以及上表的角色。整個
   patch 不必捲動就能看到全部，方塊沒有重疊。
2. 在 Live 按 Play。從 patch 點擊每個 bass 模式、bass loop、旋律模式、旋律 loop 與和弦進行，
   並改變兩個八度。確認 `next` 立即改變、`now` 在下一個小節線改變，且聽到的內容相符。
3. 在 MPC Sample 上按 pad 16 與 pad 15 切換所有模式，在群組中確認同樣的事。
4. 按第 1 組的 `connect`：群組再次顯示相同的狀態。
5. 按 preset 按鈕 `pressure`：群組顯示 `-`，在群組中點擊時狀態列得到 `inactive_preset`。
6. 確認 Pd 視窗沒有紅色的錯誤。

### 不需硬體試玩

一個小網頁以真正的 `ensemble` 規則演奏你填寫的鼓格子，不需要 MPC、Live 或 MIDI clock，任何人都能
聽到鼓如何決定樂團演奏的內容（#166）。需要選用的 `demo` extra（Gradio）：

```bash
uv sync --extra demo
uv run python -m mpc_iml.webdemo
```

打開它印出的網址（`http://127.0.0.1:7860`）。格子的每一列是一個小節中的一種鼓（kick、snare、
hat；0 是不打，1～127 是力度）。選一個範例或放上鼓點，選好設定，按 **Play**。網頁以一個小型
合成器演奏鼓、bass 與鍵盤，並顯示一張表：每個小節的鼓，以及樂團為下一個小節選擇的變奏、裝飾音、
力度與亮度。
設定 **rhythm** 就是樂器的 `rhythm`（#189）：`off`（預設值，#194）照寫好的線條演奏；`bass` 時
bass 線條的音移向上一小節的 kick；`bass and melody` 時旋律的音也移向 snare 與 hat。
表的 `transform` 欄列出 bass 與旋律的轉換（`plain`、`lock`、`answer`、`backbeat`；不發聲時為
`-`），`took` 欄列出每條移動的線條取用的鼓，以及其音移到的步，例如 `kick 1 7 11 → bass 7`。
在鋼琴捲簾中，移動的音以該聲部顏色較淺的色調顯示。以 `bass` 演奏同一個格子，就能把移動的線條與
原樣的線條對照來聽。
設定 **melody mode** 也有 `still`（#233）：鍵盤每小節奏 `home`、bass 照常跟隨，表中旋律標示
`(still)`。
相同的格子與 seed 一定發出相同的聲音。表的下方有鋼琴捲簾顯示鼓、bass 與鍵盤，**MIDI file**
下載這首曲子（鼓在 channel 10，bass 在 2，鍵盤在 3，附亮度 CC 74），可在 DAW 中開啟。

**recording** 分頁改為演奏以 `python -m mpc_iml.record --clock` 錄下的錄音：樂團的回應與
engine 當時的回應完全相同，速度依錄音，範圍從 clock 的 Start 到下一個 Stop，最多 64 小節。
pad 1 與 5 是 kick，2 與 6 是 snare，3、4 與 7 是 hat（任何 bank）。第二張表列出格子上的
每一次 pad 敲擊，與 `python -m mpc_iml.grid` 印出的相同。

要讓隊友從另一台電腦打開，加上 `--share`：Gradio 經由它的分享伺服器產生暫時的公開連結（72 小時
內、demo 執行期間有效）。只在確定要分享時使用；預設只在本機。

demo 會關閉 Gradio 的使用分析（除非你已經設定，否則把 `GRADIO_ANALYTICS_ENABLED` 設為
`False`），所以它本身不會送出任何資料給 Gradio。`--share` 仍會經過 Gradio 的分享伺服器。
