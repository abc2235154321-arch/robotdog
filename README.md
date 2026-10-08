# robotdog

Pupper V3 的獨立實驗腳本：語音指令、一般人物跟隨、單人鎖定、衣服顏色選擇與預覽。

本次匯入來源是機器狗 `/home/pi/pupper-tests/` 的實際下載內容。程式放在儲存庫根目錄，部署時仍使用 `/home/pi/pupper-tests/`。不是完整的 Pupper 系統映像，也不包含 `pupperv3-monorepo`。

## 版本與安全限制

- 此快照的 Hailo 偵測使用官方校正／投影影像。尚未包含新的原圖 YOLO 實驗；沒有 `--raw` 模式。
- 衣服顏色使用 HSV 規則，不是人臉辨識，也不能保證同一人的身分。光線、同色衣服、遮擋與人物誤偵測可能造成錯誤。
- 動作模式需明確 `--execute`；語音非停止動作另需輸入 `y`。`STAND` 是停止跟隨並檢查已啟動的站立控制器，不會從零啟動馬達。
- 先做無動作觀察，再在有人工監督、可手動急停、遠離樓梯的空地測試。沒有可靠的障礙物避讓；語音停止不是硬體急停。
- 不要同時啟動不同的馬達、相機、Hailo 或跟隨堆疊。不要使用遠端語音服務的成功回覆代替實際控制器檢查。
- 不同腳本的速度與執行時間不同，請讀取各腳本；單人／顏色主堆疊有時間上限與清理流程。
- 上傳與安裝不會自動啟動機器狗。

## 系統分工

機器狗的 H5 麥克風 → 桌機 Whisper STT → 狗上的 Qwen 分類 → 固定白名單動作腳本 → ROS 2。

視覺由狗上的官方相機／Hailo 程式提供，再由本資料夾做單人鎖定或衣服顏色分析。預覽不需要 OpenCV HighGUI；可使用網頁與 Tk 顯示器。

## 需要另外準備

- 已安裝並完成硬體設定的 Pupper V3、ROS 2 Jazzy，以及 `/home/pi/pupperv3-monorepo/ros2_ws/install/setup.bash`。
- 官方相機、Hailo 模型與相機校正資料，以及 neural_controller 等 ROS 套件。此儲存庫不提供這些套件、模型或校正備份。
- 狗端 Python 3.11、NumPy 1.x 相容目錄 `ros-numpy1`，以及隔離的 `.venv-voice`。
- 狗端 `llama.cpp` 的 `llama-server` 與 Qwen3-0.6B Q4_0 GGUF；模型需要另外取得。
- 桌機的 Windows Whisper STT 服務（HTTP 8008，需提供 `/health` 與相容轉錄端點）。同事的 Windows-server 專案不在這份狗端資料夾中，不能只靠本儲存庫重建桌機服務。
- 可錄音的麥克風；每次使用 `--list-devices` 確認索引，不要假設永遠是 2。

## 取得程式（在狗的 Bash）

若 `/home/pi/pupper-tests` 已存在，先備份並比對，**不要直接覆蓋既有目錄**。第一次安裝且該路徑不存在時：

```bash
git clone https://github.com/abc2235154321-arch/robotdog.git /home/pi/pupper-tests
```

程式有固定的 `/home/pi` 路徑；其他帳號需逐項調整，不可直接假定相容。

只在尚未建立環境時執行以下安裝，不要替換系統 ROS 的 NumPy：

```bash
env -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 -m venv /home/pi/pupper-tests/.venv-voice
env -u PYTHONPATH /home/pi/pupper-tests/.venv-voice/bin/python -m pip install numpy sounddevice
env -u PYTHONPATH /home/pi/pupper-tests/.venv-voice/bin/python -m pip install \
  --only-binary=:all: --no-deps --target /home/pi/pupper-tests/ros-numpy1 'numpy==1.26.4'
```

本機 Whisper 的 `voice_qwen_dry_run.py` 還需要 `faster-whisper` 與另外下載的 Whisper 模型；遠端版本不需要在狗上跑 Whisper。ROS 腳本則使用官方環境的 `/usr/bin/python3`，不是語音虛擬環境。

## 無馬達觀察（在狗的 Bash，分開終端機）

先確認沒有執行中的馬達或相機／Hailo 堆疊。官方 `llm-agent` 若正占用音訊或控制資源，可以暫時停止；不會刪除它。

```bash
sudo systemctl stop llm-agent
bash /home/pi/pupper-tests/run_appearance_vision_only.sh
```

在另一個狗端終端機啟動顏色觀察：

```bash
bash /home/pi/pupper-tests/show_appearance_color_test.sh --color red --web-preview
```

預覽服務為狗端 `http://127.0.0.1:8766`，不對外直接開放。需要在狗的桌面顯示時：

```bash
DISPLAY=:0 bash /home/pi/pupper-tests/show_appearance_desktop_viewer.sh
```

結束時先 Ctrl+C 關閉觀察／顯示器，再 Ctrl+C 關閉視覺主終端機。觀察與正式馬達堆疊不要重複執行。

## 語音連線與檢查

先在桌機另外啟動既有 Windows STT 服務，確認以下命令成功（**桌機 PowerShell**）：

```powershell
curl.exe -sS --max-time 5 http://127.0.0.1:8008/health
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:18014:127.0.0.1:8008 pi@pupper.local
```

保留這個 SSH 視窗。若 `pupper.local` 無法解析，改用你自行確認的狗端 IP；不要公開個人 IP 或密碼。若遠端埠已占用，先確認現有 tunnel 是否有效，不要直接殺掉不明 sshd。

在狗端另一終端機啟動 Qwen，將 `MODEL` 改成你本機實際的 GGUF 路徑：

```bash
MODEL=/path/to/Qwen3-0.6B-Q4_0.gguf
/home/pi/llama.cpp/build/bin/llama-server -m "$MODEL" --host 127.0.0.1 --port 8081 -c 2048 -t 4
```

在狗端檢查兩個服務及麥克風：

```bash
curl -sS --max-time 5 http://127.0.0.1:18014/health
curl -sS --max-time 5 http://127.0.0.1:8081/health
env -u PYTHONPATH /home/pi/pupper-tests/.venv-voice/bin/python \
  /home/pi/pupper-tests/voice_remote_qwen_dry_run.py --list-devices
env -u PYTHONPATH /home/pi/pupper-tests/.venv-voice/bin/python \
  /home/pi/pupper-tests/voice_remote_qwen_dry_run.py --stt-url http://127.0.0.1:18014 --port 8081 --check
```

先使用不帶 `--execute` 的語音測試。服務重啟、斷網或 SSH 視窗關閉後，需重新確認所有連線。

## 顏色跟隨（會啟動馬達）

確認已結束觀察堆疊、準備好手動停止方式後，在狗端主終端機執行：

```bash
bash /home/pi/pupper-tests/run_voice_appearance_stack.sh 600
```

等待 12 馬達校正完成及 `READY`；此時站立但跟隨仍未啟用。在另一狗端終端機先檢查：

```bash
env -u PYTHONPATH /home/pi/pupper-tests/.venv-voice/bin/python \
  /home/pi/pupper-tests/voice_remote_qwen_dry_run.py \
  --device 2 --stt-url http://127.0.0.1:18014 --port 8081 --appearance-follow --execute --check
```

只有檢查成功後才去掉 `--check` 開始收音；麥克風索引依實際列表調整。顏色模式需指定上衣顏色，例如「跟隨穿紅色上衣的人」，不是任意外觀描述。支援 red、orange、yellow、green、blue、purple、black、white、gray。

停止顏色跟隨（馬達仍可能通電）：

```bash
bash /home/pi/pupper-tests/voice_appearance_robot_action.sh STOP
```

主堆疊終端機 Ctrl+C 才是關閉完整堆疊；異常時使用實體／手動停止方式。

## 未公開內容與協作

匯入保留根目錄的 68 個 `.py`、`.sh`、`.urdf`、`.md` 原始檔。不包含 `.venv-voice`、`ros-numpy1`、模型、快取、日誌、診斷照片、歷史校正備份及編輯器暫存。這些檔案仍保留在本機備份，沒有被刪除。

儲存庫為 Public：任何人能下載，但直接推送仍需擁有者邀請為 collaborator。請使用分支與 pull request 協作。不要提交 `.env`、API token、SSH 私鑰、音訊、相機照片、日誌或大型模型。

此次只做來源匯入與靜態語法檢查；不代表重新驗證過狗端硬體、人物辨識或動作安全。新機器仍需重新完成上述觀察與檢查。

此儲存庫未新增開源授權；若要重用或散布，請確認作者及依賴套件的授權。
