# 安裝與設定四級模型

目前可使用的是本機 CLI／設定候選。它能展示、編輯及保存模型政策；正式 Codex Hook 尚未啟用，設定好不代表委派已開始經過 Jev。以下使用 Python 3.11+，不需要先提供 API key。

## 先看畫面

```sh
/Users/shawn/Code/model-routing-harness/demo --color --width 120
```

Demo 使用隔離的五筆示範資料並自動清除；不是你的實際委派歷史。`--plain` 關閉色彩，省略 `--width` 會依目前終端寬度排列。

## 安裝 CLI

下面的 venv 與設定路徑由你明確選擇，與已安裝 Codex 分開。這份指南沒有替你執行正式安裝。

```sh
python3.11 -m venv "$HOME/.local/share/mrh/venv"
"$HOME/.local/share/mrh/venv/bin/python" -m pip install --no-index --no-deps --no-build-isolation /Users/shawn/Code/model-routing-harness
mrh_cli="$HOME/.local/share/mrh/venv/bin/mrh"
mrh_settings="$HOME/.local/share/mrh/codex/settings.json"
"$mrh_cli" settings init --path "$mrh_settings"
```

`init` 只接受全新的資料夾或已屬於 MRH 的設定資料夾；不會接管任意既有 JSON。設定檔必須使用完整路徑，檔名是 `settings.json`。每個宿主可使用各自的設定目錄；目前只有 Codex 候選接頭，不能把另存設定當成 Claude／Gemini 已支援。

## 修改模型與推理強度

```sh
"$mrh_cli" settings edit --path "$mrh_settings"
```

編輯器依序詢問 Light、Small、Mid 的模型與 effort，接著是 Top 模式。模型名稱與 effort 是你要求的值，並不是已驗證的帳號支援清單。

- Enter：保留目前值。
- `unset`：移除 Light／Small／Mid 的模型指定，保留原委派。
- `inherit`：不指定 effort，讓宿主沿用其規則；畫面不會猜繼承後的數值。
- Top `Main`：交回目前主代理，不在此更改主視窗模型或 effort。
- Top `Fixed`：指定子代理模型與可選 effort。
- 檢查最後的修改摘要，輸入 `save` 才保存；`cancel`、EOF 或儲存確認前 Ctrl-C 都不寫入。

如果編輯期間同一份設定被更新，儲存會拒絕覆蓋並要求重開。修改模型不會自動開啟路由、允許 task 外送，或改掉費率、workspace 等其他設定。既有 `settings configure --policy /absolute/policy.json` 仍可用，兩種方式操作同一份設定。

## 確認保存的內容

```sh
"$mrh_cli" settings view --path "$mrh_settings" --color --width 120
"$mrh_cli" status --settings "$mrh_settings" --color --width 120
"$mrh_cli" settings show --path "$mrh_settings"
"$mrh_cli" stats --settings "$mrh_settings" --json
```

`view` 顯示目前四級配置；`status` 加上同資料夾事件庫的歷史統計。配置表與歷史次數分開，修改政策不會重算舊事件。`show`／`stats --json` 提供原始資料，`--details` 可查看完整統計。`--settings` 與 `--db` 不能同時指定。

## 任務是如何被分級的

Jev 讀取本次子任務與四級標準，回傳等級及信心度，MRH 再套用你的模型政策：

| 等級 | 判斷方向 |
|---|---|
| Light | 機械性處理，成果容易直接檢查 |
| Small | 需要閱讀理解，但範圍與驗收明確 |
| Mid | 實作、測試或診斷等較大工作 |
| Top | 跨系統設計、證據衝突或重要取捨 |

這不是把 Light 固定等同某個低階模型，也不是把 Mid 固定成 high effort。分類標準與提示詞目前不提供使用者編輯入口；信心度低於 0.5 仍保留原呼叫。明確指定模型、受保護角色、相容性與成本檢查仍適用，Fixed 不會繞過它們。

## 已驗證與尚未完成

[E9R 安裝版證據](e9r-configured-table-proof.md) 已涵蓋離線安裝、實際 CLI 編輯、同檔讀回及寬窄終端呈現。[E8](e8-live-hook-proof.md) 已驗隔離 source 的真實 Hook 子程序控制，但不是你目前已安裝的 Codex。

正式宿主採用、真 Jev／模型／帳號、自主 Main 接回和 Goal、Desktop UI 尚未完成。主模型不會因此被切換。畫面中的 unknown／Unavailable 不表示零用量或沒有費用。原生 Mac Terminal 外觀尚未觀測；目前可見證據來自真實 PTY 輸出與 xterm.js。
