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

**清除統計**（只清統計資料，不碰設定與金鑰；刪除前一定先預覽，並要你輸入確認）：

```sh
mrh stats reset --today        # 今天
mrh stats reset --days 7       # 最近 7 天內（30、或任意天數都可以）
mrh stats reset --all          # 全部
```

互動時預覽後要輸入「刪除 N」（N 是預覽顯示的總筆數）才會真的刪除，輸入其他內容就取消；在腳本中沒加 `--yes` 只會顯示預覽。`mrh ctrl` 選單的「清除統計」也是同樣流程。範圍內所有統計資料表（委派、分級器呼叫、子代理、通知）一起清除，**包含除錯用的分級器呼叫紀錄**。

**統計保留期限**：預設保留 365 天，超過的紀錄會自動刪除（每天最多整理一次，由 hook 在記錄子代理時順便做，不拖慢派工）。調整：`mrh ctrl set stats.retention_days 180`（`0` 代表永久保留）；選單「統計保留天數」也可以改。每次委派約佔 1 KB，所以即使每天 200 次，一年也只有約 70 MB。

**資料放哪裡**：設定檔 `settings.json` 與統計資料庫 `advice.sqlite3` 在同一個資料夾（路徑見 `mrh ctrl show` 最後一行）。資料庫只存次數、等級、模型等，**不存任務內容**。想清空統計請用上面的 `mrh stats reset`。

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

## 現況與限制

**實測結果**（證據在 `docs/evidence/`，樣本數仍少，長期請看 `mrh stats`）：
- Jev：輕量、中等、頂級三個樣本都分對，約 0.4 秒。
- Claude Code：輕量任務被建議後，主模型改派 Haiku 5.5 並帶 effort；Top 由主模型自己做；內建 Explore 不被干預；Jev 金鑰錯誤時委派照常執行。
- Codex CLI：10 次有效試跑全部照建議改派；桌面 App：10 次中 8 次改派、2 次因信心不足而保留原委派。

**統計怎麼算「照建議改派」**：同一平台、同一對話、同一回合內，主模型改派的模型與推理強度符合當次建議就算；不比對任務文字。舊紀錄依同一規則推定。目前只能顯示「改派幾次、用了哪些模型」，**算不出省下多少錢**，因為 hook 拿不到子代理實際用了多少 token，也不知道主模型原本會用什麼。

**限制**：
- 設定檔是 v2；舊 v1 讀取時自動遷移，第一次用 `mrh ctrl` 存檔時才改寫。
- Codex 0.159.3 把委派內文（`message`）加密後才交給 Hook，MRH 只能讀到主模型取的短標籤 `task_name`（如 `rename_variable`），分級依據較弱，含糊的標籤信心度低會自動放行。Codex 主模型常帶 `agent_type: worker`，MRH 預設視同預設角色；你自訂的角色（如 `luna_worker`）一律不干預（`mrh ctrl set generic_roles.codex worker`）。
- 你的 Router 技能若已替子代理指定模型與推理強度，MRH 依「明示就尊重」讓開，所以只有沒指定時才會輪到 MRH。
- Claude Code 的子代理 `effort` 參數需 2.1.292 以上，`haiku`／`sonnet` 別名要 2.1.293 以上才對應到 5.5 系列（Homebrew 請用 `claude-code@latest`）。
- Gemini CLI 只有模型清單，尚未接 Hook。

## 維護注意事項（改程式前必讀）

**同一份程式碼同時服務 Claude Code 與 Codex**：兩邊的 hook 都執行 `runtime.pyz`，共用檔案一改，部署後兩邊同時受影響。

| 範圍 | 注意 |
|---|---|
| 共用核心：`advisory/*`、`settings_v2.py`、`advisory_runtime.py`、`plugin.py` 的 `LAUNCHER`、`adapters/providers/*` | 改動兩邊都吃到；`engine.py` 不要寫平台特例 |
| `advisory_hosts.py` | `ClaudeHost` 與 `CodexHost` 各自獨立，不要一般化；建議文字的推理強度參數名不同（Codex 為 `reasoning_effort`、Claude 為 `effort`），不要統一 |
| `advisory/store.py` | 資料庫 schema 只能加表／欄位，統計與儀表板都讀它 |
| 路徑不可搬、不可改名 | `~/.local/share/model-routing-harness/app`、`runtime/daily-cli/artifact`（`launcher.py`、`binding.json`、`runtime.pyz`）。Claude 的 hook 在 `~/.claude/settings.json`，指向這些檔案 |
| Codex `hooks.json` | 內容或命令一變，Codex 會要求在 `/hooks` 重新信任 |

改完後：`PYTHONPATH=src python3 -m unittest discover -s tests -t .`，再依「安裝」一節的升級流程部署，最後跑回歸檢查 `python3 scripts/verification/claude_smoke.py --yes`（**會真的呼叫 Claude 與 Jev，約 $0.3，須明確同意**）。

金鑰只放 macOS Keychain 或環境變數，不進任何檔案、報告或 commit。分級器預設是 Jev。

## 開發

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -t .
```

需求在 `REQUIREMENTS.md`；驗證證據在 `docs/evidence/`（見 `docs/README.md`）；測試用固定資料在 `tests/fixtures/`。需要追查歷史請用 `git log`。
