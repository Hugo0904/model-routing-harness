# 安裝與設定四級模型

目前可使用的是本機 CLI／設定候選。新設定的分級來源是 Codex 訂閱，使用既有 ChatGPT 登入，不要求 API key；舊 TypeSafe 設定保留原來源。模型政策保存後，仍須通過 Hook scope、task 外送與啟用檢查。目前登入 home 的全域 AGENTS 會觸發隔離保護，真實分級尚未驗收，見 [E19 說明](e19-subscription-classifier.md)。以下來源操作使用 Python 3.11+；E19 獨立套件已內含執行環境。

## 先看畫面

```sh
/Users/shawn/Code/model-routing-harness/demo --color --width 120
```

Demo 使用隔離的五筆示範資料並自動清除；不是你的實際委派歷史。`--plain` 關閉色彩，省略 `--width` 會依目前終端寬度排列。

## 現在直接使用模型選單

需要 Python 3.11+，不需要 API key：

```sh
cd /Users/shawn/Code/model-routing-harness
PYTHONPATH=src python3.11 -m mrh model light
```

將 `light` 換成 `small`、`mid`、`top`，或省略等級進入選單。首次選擇已安裝工具並確認建立 MRH profile；單一綁定會自動載入。這是 MRH 設定關聯，不是帳號登入。

- ↑／↓ 選擇，Enter 確認；模型與推理強度不必手打。
- ← 回上一頁並保留草稿，Esc 取消；取消不保存政策。
- 最後選 Save 才保存。版本衝突或清單改變時，不會直接覆寫。
- Top 先選 Main 或 Fixed；Main 不更改主視窗模型，Fixed 再選子代理模型。

預設使用 MRH 自有使用者資料夾。`--root /完整路徑` 可指定另一個綁定登錄目錄，profile 會建立在該目錄的上一層。驗證請使用全新的自有父資料夾，避免混用正式設定。

## 安裝後用短指令

下面是一次性獨立安裝範例，尚未替你執行。請使用尚未存在的 venv 位置；不修改 Codex 登入、Hook 或全域 PATH。

```sh
python3.11 -m venv "$HOME/.local/share/mrh/venv"
"$HOME/.local/share/mrh/venv/bin/python" -m pip install --no-index --no-deps --no-build-isolation /Users/shawn/Code/model-routing-harness
source "$HOME/.local/share/mrh/venv/bin/activate"
mrh model light
```

日後在終端啟用同一個 venv 後，即可使用 `mrh model`。E10 已驗過套件入口與模組包含；E10R 修正經來源驗收，沒有把舊 wheel 當成本次修正版。

## 模型不能使用時

清單讀取失敗時可 Retry、Back 或 Cancel。舊清單只供顯示，不能確認新設定；連線失敗不會被誤判為模型下架。已確認下架的模型會提示手動選替代項目，保留舊設定與歷史。

在已驗證具備拒絕能力的接頭中，分級選定後若有可信事實確認目標模型／推理強度不可用，會停止該次委派，指出等級及指令，例如 `mrh model top`。更新後，操作者必須重新發起新委派；原委派保持停止，不會自動換模型、交給主模型或自行恢復。這已在隔離公開 Hook 驗證；正式宿主尚未採用，沒有可讀取的下游模型錯誤時也無法代為偵測。

## 進階設定

舊的 `settings edit` 文字輸入編輯器仍保留；正常選模型請使用上述 `model` 選單。以下讀取指令中的 `mrh_cli` 是安裝後的執行檔完整路徑，`mrh_settings` 是選單綁定的 profile 所使用之 `settings.json` 完整路徑；不要另外初始化另一份設定後誤以為是同一份。修改政策不會自動開啟路由、task 外送或改動其他權限。

## 確認保存的內容

```sh
"$mrh_cli" settings view --path "$mrh_settings" --color --width 120
"$mrh_cli" status --settings "$mrh_settings" --color --width 120
"$mrh_cli" settings show --path "$mrh_settings"
"$mrh_cli" stats --settings "$mrh_settings" --json
```

`view` 顯示目前四級配置；`status` 加上同資料夾事件庫的歷史統計。配置表與歷史次數分開，修改政策不會重算舊事件。`show`／`stats --json` 提供原始資料，`--details` 可查看完整統計。`--settings` 與 `--db` 不能同時指定。

## 任務是如何被分級的

所選分級來源讀取本次子任務與四級標準，回傳等級及信心度，MRH 再套用你的子代理模型政策。新設定使用 `gpt-6-luna / low` 作為分級器；四級清單選的是後續子代理的模型與推理強度，兩者分開設定：

| 等級 | 判斷方向 |
|---|---|
| Light | 機械性處理，成果容易直接檢查 |
| Small | 需要閱讀理解，但範圍與驗收明確 |
| Mid | 實作、測試或診斷等較大工作 |
| Top | 跨系統設計、證據衝突或重要取捨 |

分類標準與提示詞目前不提供使用者編輯入口；信心度低於 0.5 仍保留原呼叫。Codex 分級信心度是模型自報，尚未校準，不是 Jev 機率。明確指定模型、受保護角色、相容性與成本檢查仍適用，Fixed 不會繞過它們。

## 已驗證與尚未完成

A 已親自驗證 E10R 的 Codex 公開預設清單、方向鍵選擇／返回／保存、取消保存不變與錯誤引導；停止委派採隔離公開 Hook 逐步驗證。見 [A 驗收](evidence/e10r-a-acceptance.json)及[E10R 說明](e10r-operator-stop.md)。

| AI 工具 | 目前實際支援 |
|---|---|
| Codex CLI | 工具公開模型／推理清單、鍵盤選擇及保存；帳號權限與正式真模型委派未確認 |
| Codex Desktop | 可發現內附 CLI；Desktop UI 與正式完整整合未確認 |
| Claude Code | macOS 2.1.267 可直接讀 CLI 宣告清單、選模型與來源提供的 effort；不需 SDK。其他版本、帳號可用性與路由接頭仍未驗證，詳見 [E13](e13-claude-catalog.md) |
| Gemini CLI | 0.63.0 的工具宣告模型清單與 inherit 選單已驗收；CLI 更新可在同一份設定中重新確認，帳號可用性與路由接頭仍未驗證 |


[E9R 安裝版證據](e9r-configured-table-proof.md) 已涵蓋離線安裝、實際 CLI 編輯、同檔讀回及寬窄終端呈現。[E8](e8-live-hook-proof.md) 已驗隔離 source 的真實 Hook 子程序控制，但不是你目前已安裝的 Codex。

正式宿主採用、真訂閱分級／子模型、自主 Main 接回和 Goal、Desktop UI 尚未完成。主模型不會因此被切換。畫面中的 unknown／Unavailable 不表示零用量或沒有費用。原生 Mac Terminal 外觀尚未觀測；目前可見證據來自真實 PTY 輸出與 xterm.js。
