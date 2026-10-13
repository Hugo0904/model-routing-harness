# Model Routing Harness（MRH）

**Route the task, not the session.** 主模型要派子代理時，MRH 先請一個便宜的「分級器」判斷這件工作多難（Light／Small／Mid／Top），再把你為該等級設定的模型清單**以建議的方式**交回主模型；由主模型自己挑、自己重派。做不到就由主模型繼續做。

```
主模型要派子代理 ─▶ Hook ─▶ 分級器（Jev／Codex 訂閱／Claude 訂閱）─▶ 等級＋信心度
      ▲                                                              │
      └──── 建議：「請改用 haiku／gpt-5.6-luna:low…，否則自己做」 ◀───┘
```

- 是**建議**，不是強制改寫。主模型沒有照做，MRH 不會再攔第二次（同一任務 10 分鐘內只建議一次）。
- 你或主模型已經明確指定模型、推理強度或專門角色 → 一律尊重，不分級。
- 分級失敗（沒額度、逾時、金鑰錯誤）→ 原呼叫照常放行，只提示一次原因。
- 不改任何廠商本體，只用各家原生 Hook。目前支援：**Codex**、**Claude Code**。Gemini CLI 只有模型清單，尚未接 Hook。

## 控制中心

所有設定都在一個地方：

```sh
mrh                          # 什麼都不加：列出所有指令
mrh ctrl                     # 互動選單（↑↓ 選擇、Enter 確認、Esc 或 ← 返回上一步、Ctrl-C 離開）
mrh status [--days N]         # 終端儀表板：流程、難度表（含價格）、分段比例條、進度條（80–120 欄自適應）
mrh stats [--days N]          # 中文統計
mrh ctrl show [--json]       # 目前設定一覽
mrh ctrl set KEY VALUE       # 腳本用；mrh ctrl keys 列出所有 KEY
mrh key status jev           # 金鑰狀態（只顯示有沒有，不顯示內容）
```

可設定：路由開關、分級器（Jev／Codex 訂閱／Claude 訂閱）與模型與逾時、四級各平台的候選模型（有序，可帶推理強度，如 `gpt-5.6-luna:low`）、Top 交回主模型（Main）或用固定清單（Fixed）、信心門檻（0.50–0.99）、生效資料夾（`/` 代表全部）。

模型清單會標明 CLI 宣告來源與更新時間；宣告不等於帳號實際可用。清單更新失敗時，快取或內建參考會標成未確認，可查看但不可從互動選單新增；離線不當作下架，原有候選仍可保留、排序或移除。工具已明確宣告失效的項目不能新增，原設定與歷史保留。明確使用者的 `ctrl set` 腳本配置沿原契約，不因此增加帳號探測。

統計只把能對上同任務、回合與工具呼叫的後續委派列為已確認採用；請求模型與已回報執行模型分開，舊紀錄缺少關聯時明示未知。分級失敗仍列入分級嘗試／已開始呼叫，沒有回報用量時不當作零成本。

Monitor 的資料出口是 `mrh status --json --days 7`（`--days 0` 為全部）。終端卡片與 JSON 使用同一份統計及公開設定組裝；JSON 保留統計欄位，另有 `status.format_version`、`status.generated_at`、路由開關、`status.classifier` 與 `status.policy`（門檻、Top 模式、各級及 Fixed 候選）。`mrh stats --json` 保留原統計契約。同版已安裝指令比對已確認這份組裝與唯讀行為。Monitor 只需讀這份出口，不另存快照、不存取 Monitor DB，也不做 App 畫面；統計出口不建立缺少的設定或 DB。

Canopy 保留既有 `ContextSummary` 與分級器 `context_summary` 的選配介面；目前 advisory 入口傳入 `None`，尚未接上 live Canopy。此輪不讀私人記憶、Hook 暫存或對話，也不修改 Canopy Core。

## 分級器與費用

| 分級器 | 需要 | 費用 | 速度 |
|---|---|---|---|
| **Jev**（預設，TypeSafe） | TypeSafe API key（存 macOS Keychain） | 每百萬 input token $0.042、output 免費；一次分級約 440 token，**約 $0.02／千次** | 約 0.4 秒 |
| Codex 訂閱 | 已登入的 Codex CLI | 用訂閱額度 | 數秒 |
| Claude 訂閱 | 已登入的 Claude Code | 用訂閱額度 | 約 5–10 秒 |

Jev 回傳每一級的機率；訂閱分級的信心度是模型自評，沒有校準，兩者不等價。金鑰設定：

```sh
mrh key set jev      # 由 macOS 提示輸入，金鑰不經過 MRH、不進任何檔案
```

## 日常操作

```sh
mrh status                             # 卡片儀表板（預設過去 7 天）
mrh stats                              # 中文統計（預設過去 24 小時）
mrh ctrl show                          # 目前設定一覽（含難度表）
mrh ctrl set enabled on                # 路由開關；off 為停用
mrh ctrl dashboard --days 7            # 儀表板
mrh ctrl stats --days 1                # 文字統計（--days 0 為全部）
mrh key status jev                     # 金鑰狀態；mrh key set jev 存入／更換
```

**設定各難度用的模型**（格式 `模型:推理強度`，多個以逗號分隔，越前面越優先，每格最多 5 個）：

```sh
mrh ctrl set tiers.Light.claude "haiku:medium"
mrh ctrl set tiers.Small.claude "haiku:xhigh"
mrh ctrl set tiers.Mid.claude   "sonnet:high"
mrh ctrl set tiers.Light.codex "gpt-6-luna:high"
mrh ctrl set tiers.Small.codex "gpt-6-luna:max"
mrh ctrl set tiers.Mid.codex   "gpt-6.1-sol:high"
```

Claude 可用 `low／medium／high／xhigh／max`，別名 `haiku`、`sonnet`、`opus`。Codex 的模型與推理強度以 `mrh ctrl` 選單列出的清單為準。

**其他設定項目**（`mrh ctrl keys` 會列出全部）：

| 想做的事 | 指令 |
|---|---|
| 換分級器 | `mrh ctrl set classifier.provider jev`（或 `codex_subscription`、`claude_subscription`） |
| 調整信心門檻 | `mrh ctrl set threshold 0.65`（0.50–0.99，越高越保守） |
| Top 難度交回主模型／改用固定清單 | `mrh ctrl set top_mode Main`（或 `Fixed`，需先設 `fixed.<平台>`） |
| 限制只在某些資料夾生效 | `mrh ctrl set allowed_workspaces "/Users/me/專案A,/Users/me/專案B"`（`/` 代表全部） |
| 視為預設角色（不當成專門角色） | `mrh ctrl set generic_roles.codex worker` |

**資料放哪裡**：設定檔 `settings.json` 與統計資料庫 `advice.sqlite3` 在同一個資料夾（路徑見 `mrh ctrl show` 最後一行）。資料庫只存次數、等級、模型等，**不存任務內容**。想清空統計，把 `advice.sqlite3*` 移走即可，下次會自動重建。

**出問題時**：
1. `mrh ctrl show`：路由是否開啟、適用範圍是否包含目前資料夾、金鑰是否已設定。
2. `mrh key status jev`：注意環境變數 `TYPESAFE_API_KEY` 的優先順序比 Keychain 高，過期的環境變數會蓋掉正確的金鑰。
3. `mrh ctrl stats`：看「沒有介入的原因」，例如金鑰無效、信心低於門檻、專門角色。
4. Codex 沒作用：在 Codex 輸入 `/hooks`，確認 `model-routing-harness` 的 hook 已信任。
5. Claude Code 沒作用：確認版本（見下方限制）與 `~/.claude/settings.json` 內有 MRH 的 hook。`python3 scripts/verification/claude_smoke.py` 會真的呼叫 Claude 與 Jev（約 $0.3）；本輪必要回歸已獲使用者授權，等候選固定後統一安排，沿用有效結果，不無故重複呼叫。

## 安裝（macOS arm64）

封裝內含私有 Python，不需另外安裝 SDK。安裝位置固定；Codex 是否需要重新信任，取決於 Hook 定義是否改變：

```sh
python3 scripts/packaging/build_standalone.py --cache build/e15-public-assets --output dist/<名稱> --archive dist/<名稱>.tar.gz
python3 scripts/packaging/install_local.py --bundle dist/<名稱> --settings <settings.json 絕對路徑>
#   → ~/.local/share/model-routing-harness/app、~/.local/bin/mrh、~/.config/model-routing-harness/active-settings
mrh plugin prepare --advisory --root <artifact 目錄> --settings <settings.json> --python ~/.local/share/model-routing-harness/app/runtime/bin/python3.11
# Codex：codex plugin marketplace add <artifact 目錄>（首次）→ codex plugin add model-routing-harness@model-routing-harness-local → Codex 內 /hooks 信任
mrh install claude --artifact <artifact 目錄>            # 只顯示差異
mrh install claude --artifact <artifact 目錄> --apply    # 套用（自動備份，保留其他 hook）
```

升級：重建封裝 → `install_local.py` → `mrh plugin prepare --advisory …`（同參數）→ `codex plugin add …`。只有 Codex `hooks.json` 定義雜湊不變，才沿用原信任；有變更時需在 `/hooks` 重新審閱。Claude 的 `~/.claude/settings.json` 命令必須保留固定 Python 與同一個 `launcher.py claude` 入口，不能省略尾端的 `claude` 參數。

內部 Hook 入口由宿主透過 stdin 傳入事件；目前保留的形式為：

```sh
mrh hook --platform codex --settings <settings.json 絕對路徑>
mrh hook --platform claude --settings <settings.json 絕對路徑>
```

`plugin prepare --advisory` 產生供兩邊共用的 `launcher.py`、`binding.json` 與 `runtime.pyz`。日常接入使用 `runtime/daily-cli/artifact`，兩邊讀同一份 `runtime/daily-cli/profile/settings.json`；升級時保留這些路徑。舊 `hook --candidate`、`--simulate-tier`、`--simulate-confidence`、`--scope-binding`、`--db` 分支、非 advisory prepare 模式及其舊 scope 綁定已從原始碼移除。

預設**停用**。用 `mrh ctrl` 開啟；開啟代表把子代理任務文字送給你選的分級器。停用：`mrh ctrl set enabled off`；移除 Claude hook：`mrh install claude --artifact … --remove --apply`。

## 現況與誠實的限制

已接受的原候選證據：Codex CLI 10 次有效試跑均按建議改派並完成；App 的 10 次有效試次中，8 次收到建議後改派、2 次因低信心保留原委派，全部完成。詳見 [CLI 紀錄](docs/evidence/codex/l2-codex-advice-20261013.json) 與 [App 紀錄](docs/evidence/codex/codex-app-c-20261013.json)。Claude 的既有紀錄也包含改派與 Top 由主模型自行完成。這些結果只適用於各自測過的版本與設定，**不代表日常長期遵從率**；統計中的請求模型、已回報模型與未知紀錄仍須分開看。

- 設定檔 v2；舊 v1 讀取時自動遷移，第一次用 `mrh ctrl` 存檔時才改寫。
- **Codex 的限制**：Codex 0.159.3 把委派內文（`message`）加密後才交給 Hook，MRH 只能讀到主模型取的短標籤 `task_name`（如 `rename_variable`），分級依據較弱；含糊的標籤信心度低，會自動放行。Codex 主模型常帶 `agent_type: worker`，MRH 預設視同預設角色；你自訂的角色（如 `luna_worker`）一律不干預（`mrh ctrl set generic_roles.codex worker`）。
- Claude Code 的子代理 `effort` 參數需 2.1.292 以上，`haiku`／`sonnet` 別名要 2.1.293 以上才對應到 5.5 系列（Homebrew 請用 `claude-code@latest`）。
- Gemini CLI 未接 Hook；Canopy live 選配接入未完成。
- 本輪原始碼清理已完成必要範圍，候選 `19f5021` 的 153 項單元測試全過並已由督導接受；剩餘舊 renderer 屬可選瘦身，不再追加清理。同版封裝已本機安裝，48 個產品模組一致，15 項已安裝指令與 Hook／設定保留比對已接受。本次同版 Claude／Jev 回歸 9/9 通過，成功 scratch 已清除，日常設定與 Hook 定義雜湊保持原值；整體最後驗收仍由督導確認。詳見 [HANDOFF](docs/takeover/HANDOFF.md) 與 [CODEX-CLEANUP](docs/takeover/CODEX-CLEANUP.md)。
- 本次 Claude 回歸涵蓋 Light 建議後重派、Haiku 5.5 的宿主模型回報與 medium 請求、Explore 保留、明示 Sonnet／medium 保留，以及 Jev 金鑰被拒絕時原委派仍完成。Light 的 `followed=1` 有同任務／回合／呼叫的關聯欄位配對；獨立的實際推理強度回讀未提供，不把請求值當作供應商遙測。
- 新 Codex 候選 `gpt-6-luna/high`、`gpt-6-luna/max`、`gpt-6.1-sol/high` 的三組明示參數已被原生工具接受，各建立一個子代理並由官方回讀確認完成排序。宿主回報沒有實際模型／推理強度欄位，這兩欄仍未知；不能拿請求值、主模型或原 `gpt-5.6-luna/low` 結果代替實際模型回讀，也不延伸成新版 Hook 端到端驗證。

## 開發

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -t .
```

原始碼 153 項、已安裝指令／保留比對 15 項與同版 Claude 回歸 9/9 的證據分開記錄，見 [PLAN](docs/takeover/PLAN.md) 與 [HANDOFF](docs/takeover/HANDOFF.md)。使用者已授權必要的 Claude／Jev 真服務回歸，不逐項詢問；按固定收尾清單與單一執行者安排，不擴項或重跑有效證據。可用 `MRH_SMOKE_EVIDENCE_DIR` 指定本機 smoke 報告目錄；腳本只保存必要的結果與關聯欄位，成功刪除自有 scratch，失敗則保留供判讀。

需求：`REQUIREMENTS.md`。接手與驗證紀錄：`docs/`（見 `docs/README.md`）。舊階段文件已刪除，需要追查歷史請用 `git log`。
