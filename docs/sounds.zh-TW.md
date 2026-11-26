# 量測單音與建立樂器

[English](sounds.md) | 繁體中文

[RFC 0006](rfcs/0006-sounds-for-the-band.md) 第 1 步的前半（#268）：一個單音的錄音在放進 sound set 之前，先確認它實際上是什麼。產生單音的模型不一定奏出要求的音高：在最初以這種方式產生的音中，音名都對，但有幾個音的八度錯了，另有兩個音不乾淨。第 1 步的後半（#270）以量測過的音建立樂器，見[建立樂器](#建立樂器)。

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

## 已知的缺口

在低音（約 E2 以下）旁，分析窗的旁瓣可能被算成一個不在泛音上的弱峰，約比最強峰低 30 dB。這讓乾淨的低音的 `clean` 最多少半個百分點，`other` 會指出這個旁瓣。方法保持不變，讓結果能與已演奏過的 sound set 比較。
