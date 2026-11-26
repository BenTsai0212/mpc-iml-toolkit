# 量測單音與建立樂器

[English](sounds.md) | 繁體中文

[RFC 0006](rfcs/0006-sounds-for-the-band.md) 第 1 步的前半（#268）：一個單音的錄音在放進 sound set 之前，先確認它實際上是什麼。產生單音的模型不一定奏出要求的音高：在最初以這種方式產生的音中，音名都對，但有幾個音的八度錯了，另有兩個音不乾淨。第 1 步的後半（#270）以量測過的音建立樂器，見[建立樂器](#建立樂器)；最後一部分（#272）把樂器與鼓聲整理成 [sound set](#sound-set)。

## 執行

這個指令需要 `numpy`，隨 `demo` extra 安裝：

```bash
uv sync --extra demo
uv run python -m mpc_iml.sounds.notes bass-E1.wav bass-A1.wav
```

每個檔案印一行：

```text
file                         note        Hz  cents   clean   rich  attack
bass-E1.wav                  E1        41.3     +4   99.8%  24.6%     -2c
```

無法讀取或量測的檔案寫到錯誤輸出，處理完其他檔案後以狀態 1 結束。

讀取 WAV 檔：16、24、32 bit PCM 與 32 bit float，mono 或 stereo。不認得的 chunk（`fact`、`PEAK`、`LIST`、`bext` 等）會略過，其他格式以錯誤拒絕。不需要音訊函式庫。錄音留在你的電腦上；測試只用合成的音。

## 數值的意思

- **note** 與 **cents**：離基頻最近的 MIDI 音，以及相差多少；正值是偏高。音高量的是 **sustain**（聲音開始後 0.15 s 起），不是起音：撥弦或敲擊聲的起音常常偏高，依起音調音的 sample 會偏低。
- **Hz**：sustain 的基頻。候選的基頻本身要是頻譜峰，或它的第 2 與第 3 泛音都在。沒有這條規則時，多了一個雜散分音的音會被讀成基頻是實際一半或三分之一的乾淨音。
- **clean**：頻譜峰的能量落在基頻泛音上（35 cents 內）的比例。乾淨的有音高的音接近 100%；雜音或不是泛音的分音會降低它。最強的這種分音記為 `other`（頻率與比最強峰低多少 dB）。
- **rich**：泛音 2 到 4 附近的能量比例。純正弦波接近 0%；低泛音強的明亮 bass 超過 50%。
- **attack**：前 120 ms 與 sustain 相差多少 cents。起音偏高的撥弦音這裡是正值。
- 在 Python 中，`measure` 另外給出聲音開始的 frame（第一個距峰值 40 dB 內的樣本）、音量降 20 dB 所需的時間、錄音長度與峰值音量。

靜音的錄音，以及聲音開始後不到約 0.3 s 的錄音，會被拒絕。

## 建立樂器

第 1 步的後半（#270）把一位樂手的單音錄音做成任何 SFZ 播放器都能載入的樂器，讓它能在樂團的軌道上演奏：

```bash
uv run python -m mpc_iml.sounds.instrument bass bass-*.wav --out bass-set --low E1 --high G3
```

寫出 `bass-set/bass.sfz`，用到的音放在 `bass-set/samples/`；每個 region、每個被排除的檔案（附原因）、每段沒有音到得了的鍵各印一行：

```text
bass: samples/bass-E1.wav      keys   0-30  centre  28 (E1)  tune -4  level +1.2 dB  from bass-E1.wav
bass: left out bass-A1-take2.wav: another take of A1 is cleaner
bass: no note within 6 semitones of D3 to G3
```

規則：

- 每個檔案依上文量測。無法讀取或量測的檔案附原因排除，其他檔案照常使用。
- **clean** 低於 98.5% 的音排除。
- 每個音高只留一個音：同一音高有好幾個 take 時留最乾淨的；加 `--prefer rich` 時留 **rich** 最高的（小喇叭也放得出來的 bass）。
- 每個音負責到與相鄰音的中點為止的鍵；最低與最高的音延伸到鍵盤兩端。
- 切掉音前的靜音：sample 從聲音開始前 32 個 frame 起，結尾 10 ms 淡出。
- 拉平音量：每個音前 0.4 s 的音量調到留下的音的中位數，最多調高或調低 9 dB；之後任何樣本的峰值都不超過 −1 dB full scale。
- 每個音寫成 24 bit WAV，取樣率與聲道數與原錄音相同，檔名是 `<名稱>-<音名>.wav`（`#` 寫成 `s`，例如 `keys-Fs4.wav`）。
- SFZ 檔有一行 `<global>`（2 ms 起音、`--release` 的釋放時間，預設 0.25 s，力度影響音量），每個音一行 `<region>`，含負責的鍵、音與量到的 cents（`tune`）。
- 加 `--low` 與 `--high`（這個聲部演奏的最低與最高音；兩個都給或都不給）時，列出這個範圍內離每個留下的音都超過 6 個半音的鍵。

沒有任何錄音能用時，指令印出原因並以狀態 1 結束。

### 樂器演奏哪些音

樂器可以只演奏樂團的音中屬於它的部分（#274）。以四個選項指定，都以樂團送出的音（任何移調之前）計：

- `--part bass|melody`：它演奏樂團的哪個聲部。只記在 `sound-set.json`，SFZ 檔不過濾 MIDI channel。
- `--keys <低> <高>`：它演奏的最低與最高音，以音名表示（例如 `--keys C5 G9`）。預設：所有鍵。
- `--min-velocity <1-127>`：只演奏力度至少這麼大的音。預設 1。
- `--octave <-4..4>`：比收到的音高這麼多個八度發聲。預設 0。

SFZ 檔只用基本的 opcode 做到這些，任何 SFZ 播放器都能播放：

- 八度：每個音的 `pitch_keycenter` 每個八度往下移 12 個半音，鍵在移動後的音之間的中點分界。加 `--octave 1` 時，送到 A1 的音以 A2 的 sample 原音高播放。會把音移出鍵盤的八度在寫入任何檔案之前拒絕。
- 鍵：每個 region 的鍵截到 `--keys` 之內。負責的鍵完全在範圍外的音沒有 region 也沒有 sample，附原因排除。
- 力度：`--min-velocity` 大於 1 時，`<global>` 行加上 `lovel`。
- 使用預設值時，SFZ 檔與 sample 與不加這些選項時相同。

`--low` 與 `--high` 也以樂團送出的音計，只檢查同時在音域與 `--keys` 內的鍵是否有 6 個半音內的音。選項不是預設值時，印出的第一行說明樂器演奏哪些音：

```text
bell: plays the melody part, keys C5 to G9 (72-127)
```

例如 2026-11-25 演奏的 set 中，三個樂器分擔一個旋律聲部：keys 負責 C5 以下的音、bell 負責 C5 以上、pad 只負責力度大的音：

```bash
uv run python -m mpc_iml.sounds.instrument keys keys-*.wav --out band-set --part melody --keys C-1 B4
uv run python -m mpc_iml.sounds.instrument bell bell-*.wav --out band-set --part melody --keys C5 G9
uv run python -m mpc_iml.sounds.instrument pad pad-*.wav --out band-set --part melody --min-velocity 86
```

要比收到的音高一個八度發聲的 bass 加 `--part bass --octave 1`。每個樂器放在自己的軌道上，接收它的聲部（三個旋律樂器都接收旋律的 channel），前面不加鍵、力度過濾，也不移八度。

### 樂團的演奏者

樂團檔（ADR 0014，`python -m mpc_iml.bands list`）為每個演奏者寫一行：它的 `plays`（聲部、鍵、`min_velocity`、八度）與建立樂器時的預設值（`release`、`prefer`）。建立每個演奏者時，`--part`、`--keys`、`--min-velocity` 與 `--octave` 取自它的 `plays`，`--release` 與 `--prefer` 取自它的那一行。鍵寫成音名：0 是 C-1，71 是 B4，72 是 C5，127 是 G9。以 `trap` 樂團（`src/mpc_iml/bands/ensemble/trap.json`）為例：

```bash
uv run python -m mpc_iml.sounds.instrument 808 808-*.wav --out trap-set --part bass --keys C-1 G9 --min-velocity 1 --octave 0 --release 0.08 --prefer rich
uv run python -m mpc_iml.sounds.instrument keys keys-*.wav --out trap-set --part melody --keys C-1 B4 --min-velocity 1 --octave 0 --release 0.25 --prefer clean
uv run python -m mpc_iml.sounds.instrument bell bell-*.wav --out trap-set --part melody --keys C5 G9 --min-velocity 1 --octave 0 --release 0.3 --prefer clean
uv run python -m mpc_iml.sounds.instrument pad pad-*.wav --out trap-set --part melody --keys C-1 B4 --min-velocity 86 --octave 0 --release 0.5 --prefer clean
```

`lofi` 樂團的 `bass` 加 `--octave 1`：它比樂團送出的音高一個八度發聲。

## Sound set

第 1 步的最後一部分（#272，[ADR 0013](adr/0013-sound-set-folders.md)）：放著為一個樂團做的樂器與鼓聲的資料夾就是一個 **sound set**：

```text
<資料夾>/
  sound-set.json
  <樂器>.sfz
  samples/<樂器>-<音名>.wav
  hits/<鼓聲>.wav
```

`sound-set.json` 記錄這個 set 有什麼。每個樂器：SFZ 檔、建立時的設定（`prefer`、`release`、`clean`）、演奏哪些音（`plays`：`part`、`keys`、`min_velocity`、`octave`）、音域與沒有音到得了的鍵，以及每個來源錄音量到了什麼、用在哪個 region 或為什麼被排除。每個鼓聲：sample、從哪個錄音切出來、長度與音量調了多少。來源錄音只記檔名，不複製進 set，所以資料夾可以搬移或分享。

把樂器建到資料夾時，會把它加進 `sound-set.json`（同名的樂器則取代其項目），其他樂器與鼓聲保持不變。再建一次時刪除不再使用的 sample，其他檔案不刪。名稱只用小寫字母、數字與連字號。

### 鼓聲

每個鼓聲是一個 WAV 檔，從一個錄音切出：

```bash
uv run python -m mpc_iml.sounds.hits kick kick-take-2.wav --out band-set --seconds 0.6
```

寫出 `band-set/hits/kick.wav`、記錄這個鼓聲並印一行：

```text
kick: hits/kick.wav  0.60 s  level -2.1 dB  from kick-take-2.wav
```

鼓聲從聲音開始前 32 個 frame 起（第一個距峰值 40 dB 內的樣本），長度是 `--seconds`（預設 0.5 s），結尾 30 ms 淡出，峰值比 full scale 低 3 dB；寫成 24 bit WAV，取樣率與聲道數與原錄音相同。靜音的錄音會被拒絕。set 不把鼓聲對應到 pad：請放到你自己的 pad 上。

### 檢查 set

```bash
uv run python -m mpc_iml.sounds.soundset check band-set
```

列出找到的每個問題（格式，以及檔案提到但資料夾裡沒有的 SFZ 檔、sample 與鼓聲），有問題時以狀態 1 結束。`sound-set.json` 無法接受時，建立樂器與鼓聲的指令在寫入任何檔案之前以狀態 1 結束。

## 試聽

[RFC 0006](rfcs/0006-sounds-for-the-band.md) 的第 2 步（#278）：不開 DAW 就聽到一個樂團配上一個 sound set 的聲音。

```bash
uv run python -m mpc_iml.sounds.audition lofi lofi-set --out lofi-audition
```

樂團是內建樂團（`python -m mpc_iml.bands list`）。它的試聽 pattern 像網頁 demo 一樣離線經過 `ensemble`，使用樂團的內容與速度；`--bars 8` 只演奏前 8 小節。指令把 24 bit WAV 寫到 `--out`：set 中演奏某個聲部的每個樂器一個 `<樂器>.wav`，以及 `drums.wav` 與 `band.wav`。每個檔案的長度是整首（各小節再加一小節，即樂團回應最後一小節的那一小節）加上最長的 release。每寫一個檔案印一行，並說明：樂團中哪些演奏者在 set 裡沒有同名的樂器、哪些樂器不演奏任何聲部（`part` 為 `null`）而被略過、每個聲部有幾個音沒有樂器演奏、哪些鼓沒有鼓聲。

它做的事：

- 哪個樂器演奏哪個音由 set 決定，不由樂團決定：音落在樂器某個 region 的鍵內、且力度不低於它的 `min_velocity`（即 SFZ 檔所寫）時，該樂器演奏它所屬聲部的這個音。樂團的 `bass` 音是 bass 聲部，`keys` 音是旋律聲部；一個音可以由好幾個樂器演奏。
- 一個音播放其 region 的 sample，以線性內插重新取樣，移動「音減 `pitch_keycenter`」個半音加 `tune` cents。2 ms 的起音，播到音結束後在樂器的 release 內淡出；sample 較早結束時就結束（不循環）。同一樂器中同音高的新音會結束前一個。
- 音量在力度 127 時為全音量，0 時低 16 dB，以 dB 成直線。樂團的 `kick`、`snare` 與 `hat` 以同樣的規則播放 set 中同名的鼓聲，落在格點上；沒有鼓聲的鼓不發聲。
- 不做混音：每個樂器與鼓直接相加，一個共同的 gain 讓 `band.wav` 的峰值比 full scale 低 1 dB。各個檔案使用同一個 gain，所以相加就是 `band.wav`。檔案是 stereo；mono 的 sample 在兩個聲道播放。
- set 的所有 sample 必須是同一個取樣率，也就是輸出檔的取樣率；有兩種取樣率的 set 會被拒絕。

它接近 SFZ player 在樂團的 track 上播放的聲音，但不相同。力度規則是 2026-11-25 聽過的 render 所用的規則；SFZ player 在 `amp_veltrack=85` 時的規則接近但不相同。沒有效果器、沒有亮度控制（CC 74）、沒有各演奏者的音量與聲像，鼓都在格點上，沒有 swing。它寫出的檔案不放進 repository。

指令背後的函式接受音符與載入的 set 並回傳陣列，所以網頁 demo 可以不寫檔就呼叫：`play(band, bars)` 執行試聽，`played(song)` 以秒給出音符，`audition(song, set)` 演奏全部，`render_notes(instrument, notes, rate, frames)` 以一個樂器演奏一串音符。

## 網頁 demo 的 band 分頁

[RFC 0006](rfcs/0006-sounds-for-the-band.md) 第 3 步的第一部分（#280）：在網頁 demo 中以已經做好的 sound set 做同樣的試聽，並有一個按鈕把 engine 設成這個樂團。把每個 sound set 放在同一個資料夾的各自子資料夾中，再以它啟動 demo：

```bash
uv sync --extra demo
uv run python -m mpc_iml.webdemo --sounds my-sound-sets
```

**band** 分頁由上而下有四個部分：

1. **選樂團**：一個內建樂團，顯示標題、說明、速度與內容，以及演奏者的表（名稱、聲部與演奏什麼）。
2. **選 sound set**：`--sounds` 中含有 `sound-set.json` 的子資料夾。`soundset check` 的檢查拒絕的 set 附原因列出，不能選；建立或修改 set 之後，按 **Read the folder again** 重新讀取資料夾。選定的 set 為樂團的每個演奏者列一行：同名的樂器（幾個 region，以及與演奏者不同時它演奏什麼），或 set 沒有這個樂器；接著是 set 中不是樂團演奏者的樂器，以及鼓聲。
3. **試聽**：像試聽指令一樣以 set 演奏樂團的試聽 pattern，播放整個樂團、每個樂器與鼓，並顯示指令會印出的各行。**bars** 滑桿只演奏前幾小節，預設是全部。
4. **演奏**：把樂團的 `bass-loop`、`loop` 與 `progression` 以 [docs/ensemble.zh-TW.md](ensemble.zh-TW.md) 的 preset 訊息送到本機 engine 的控制 port（6450），再列出要手動完成的事：在 DAW 設定的速度、每個樂器的 SFZ 檔與它的 track 接收的聲部（bass 或旋律）、鼓聲的路徑。UDP 訊息沒有回覆，所以頁面無法知道 engine 是否在執行：請確認樂團有改變。

已列出的 set 被刪除或在磁碟上改變、或有兩種取樣率時，頁面顯示訊息。沒有 `--sounds` 時分頁只顯示樂團，第 4 部分仍會送出控制項。這個分頁讀取本機的資料夾並送訊息到 engine，所以在 `--share` 時不在頁面上。

它還不描述演奏者的聲音、不產生音或鼓聲、不建立樂器，也沒有保留或重試：這些隨第 4 步加入。它不設定音量、效果器或 DAW 的速度，也不上傳任何東西。

## 已知的缺口

在低音（約 E2 以下）旁，分析窗的旁瓣可能被算成一個不在泛音上的弱峰，約比最強峰低 30 dB。這讓乾淨的低音的 `clean` 最多少半個百分點，`other` 會指出這個旁瓣。方法保持不變，讓結果能與已演奏過的 sound set 比較。
