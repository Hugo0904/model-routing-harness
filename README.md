# Model Routing Harness（MRH）

**Route the task, not the session.** 主模型要派子代理時，MRH 先請一個便宜的「分級器」判斷這件工作多難（Light／Small／Mid／Top），再把你為該等級設定的模型清單**以建議的方式**交回主模型；由主模型自己挑、自己重派。做不到就由主模型繼續做。

```
主模型要派子代理 ─▶ Hook ─▶ 分級器（Jev／Codex 訂閱／Claude 訂閱）─▶ 等級＋信心度
      ▲                                                              │
      └──── 建議：「請改用 haiku／gpt-5.6-luna:low…，否則自己做」 ◀───┘
```

- 是**建議**，不是強制改寫。主模型沒有照做，MRH 不會再攔第二次（同一任務只建議一次）。
- 你或主模型已經明確指定模型、推理強度或專門角色 → 一律尊重，不分級。
- 分級失敗（沒額度、逾時、金鑰錯誤）→ 原呼叫照常放行，只提示一次原因。
- 不改任何廠商本體，只用各家原生 Hook。目前支援：**Codex**、**Claude Code**。Gemini CLI 只有模型清單，尚未接 Hook。

## 控制中心

所有設定都在一個地方：

```sh
mrh                          # 什麼都不加：列出所有指令
mrh ctrl                     # 互動選單（↑↓ 選擇、Enter 確認、Esc 或 ← 返回上一步、Ctrl-C 離開）
mrh status [--days N]         # 終端儀表板：流程、難度表（含價格）、分段比例條、進度條（80–120 欄自適應）
mrh stats [--days N]        # 中文統計
mrh ctrl show [--json]       # 目前設定一覽
mrh ctrl set KEY VALUE       # 腳本用；mrh ctrl keys 列出所有 KEY
mrh key status jev           # 金鑰狀態（只顯示有沒有，不顯示內容）
```

可設定：路由開關、分級器（Jev／Codex 訂閱／Claude 訂閱）與模型與逾時、四級各平台的候選模型（有序，可帶推理強度，如 `gpt-5.6-luna:low`）、Top 交回主模型（Main）或用固定清單（Fixed）、信心門檻（0.50–0.99）、生效資料夾（`/` 代表全部）。

模型清單會標明 CLI 宣告來源與更新時間；宣告不等於帳號實際可用。清單更新失敗時，快取或內建參考會標成未確認，可查看但不可從互動選單新增；離線不當作下架，原有候選仍可保留、排序或移除。工具已明確宣告失效的項目不能新增，原設定與歷史保留。明確使用者的 `ctrl set` 腳本配置沿原契約，不因此增加帳號探測。

統計只把能對上同任務、回合與工具呼叫的後續委派列為已確認採用；請求模型與已回報執行模型分開，舊紀錄缺少關聯時明示未知。分級失敗仍列入分級嘗試／已開始呼叫，沒有回報用量時不當作零成本。

Monitor 資料出口沿用 `mrh status --json --days 7`（`--days 0` 為全部）；保留統計欄位，另有 `status` 區塊（格式版本、產生時間、路由開關、分級器、門檻、Top 與各級模型），只輸出 CLI 卡片所用的公開設定。CLI 與 JSON 共用同一組裝；`stats --json` 原統計契約保留。不新增快照或 Monitor DB 存取，也不做 App 畫面。未建立設定／DB時，不由統計出口建立它們。

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
mrh ctrl set enabled on                # 啟用路由（off 為停用；開新的 Claude Code／Codex 對話才會載入）
mrh ctrl dashboard --days 7            # 儀表板
mrh ctrl stats --days 1                # 文字統計（--days 0 為全部）
mrh key status jev                     # 金鑰狀態；mrh key set jev 存入／更換
```

**設定各難度用的模型**（格式 `模型:推理強度`，多個以逗號分隔，越前面越優先，每格最多 5 個）：

```sh
mrh ctrl set tiers.Light.claude "haiku:medium"
mrh ctrl set tiers.Small.claude "haiku:xhigh"
mrh ctrl set tiers.Mid.claude   "sonnet:high"
mrh ctrl set tiers.Mid.codex    "gpt-6.1-sol:medium, gpt-6-luna:high"
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
5. Claude Code 沒作用：確認版本（見下方限制）與 `~/.claude/settings.json` 內有 MRH 的 hook；改完程式後可用 `python3 scripts/verification/claude_smoke.py` 做回歸檢查。

## 安裝（macOS arm64）

封裝內含私有 Python，不需另外安裝 SDK。安裝到固定位置（之後升級路徑不變，hook 不需重新信任）：

```sh
python3 scripts/packaging/build_standalone.py --cache build/e15-public-assets --output dist/<名稱> --archive dist/<名稱>.tar.gz
python3 scripts/packaging/install_local.py --bundle dist/<名稱> --settings <settings.json 絕對路徑>
#   → ~/.local/share/model-routing-harness/app、~/.local/bin/mrh、~/.config/model-routing-harness/active-settings
mrh plugin prepare --advisory --root <artifact 目錄> --settings <settings.json> --python ~/.local/share/model-routing-harness/app/runtime/bin/python3.11
# Codex：codex plugin marketplace add <artifact 目錄>（首次）→ codex plugin add model-routing-harness@model-routing-harness-local → Codex 內 /hooks 信任
mrh install claude --artifact <artifact 目錄>            # 只顯示差異
mrh install claude --artifact <artifact 目錄> --apply    # 套用（自動備份，保留其他 hook）
```

升級：重建封裝 → `install_local.py` → `mrh plugin prepare …`（同參數）→ `codex plugin add …`。hook 指令路徑不變，信任不失效。

預設**停用**。用 `mrh ctrl` 開啟；開啟代表把子代理任務文字送給你選的分級器。停用：`mrh ctrl set enabled off`；移除 Claude hook：`mrh install claude --artifact … --remove --apply`。

## 現況與誠實的限制

實測（單次樣本，見 `docs/evidence/`）：Jev 三個難度樣本全部分對；Claude Code（Sonnet 主模型）被建議後改派 haiku 子代理，Top 級由主模型自己完成。**不代表主模型長期遵從率**——要看統計：`mrh ctrl stats`（「建議的效果」一欄的「主模型照建議改派」）。

- 設定檔 v2；舊 v1 讀取時自動遷移，第一次用 `mrh ctrl` 存檔時才改寫。
- **Codex 的限制**：Codex 0.159.3 把委派內文（`message`）加密後才交給 Hook，MRH 只能讀到主模型取的短標籤 `task_name`（如 `rename_variable`），分級依據較弱；含糊的標籤信心度低，會自動放行。Codex 主模型常帶 `agent_type: worker`，MRH 預設視同預設角色；你自訂的角色（如 `luna_worker`）一律不干預（`mrh ctrl set generic_roles.codex worker`）。
- 遵從率：Claude Code 實測的建議幾乎都被照做；Codex 早期 2 次實測都沒改派，但日常實際使用的統計顯示有照做，樣本仍少，請以 `mrh ctrl stats` 累積的數字為準。
- Claude Code 的子代理 `effort` 參數需 2.1.292 以上，`haiku`／`sonnet` 別名要 2.1.293 以上才對應到 5.5 系列（Homebrew 請用 `claude-code@latest`）。
- Codex App（桌面版）未實測；Gemini CLI 未接 Hook。
- 舊的「強制改寫」路徑與其測試仍在 repo 內但新流程不使用，見 `docs/takeover/HANDOFF.md` 的可刪清單。

## 開發

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -t .      # 5 個已知舊失敗，見 docs/takeover/PLAN.md §15
```

需求：`REQUIREMENTS.md`。接手與驗證紀錄：`docs/`（見 `docs/README.md`）。舊階段文件已刪除，需要追查歷史請用 `git log`。
