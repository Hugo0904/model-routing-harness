# 給 Codex 的交接：完成 Codex 端串接（Claude 端已完成，請勿弄壞）

日期：2026-10-13　分支：`mrh-002-ctrl`　先讀本檔，再讀 `HANDOFF.md`（整體狀態）、`PLAN.md §16`（偏離）、`docs/evidence/l2-codex-cli.json`（Codex 實測）。

## 一、你要完成的事

**目標**：在使用者日常的 Codex（CLI 與桌面 App）上，讓 MRH 真的把子代理派到分級器建議的較便宜模型。Claude Code 端已完成並啟用。2026-10-13 B 接管的 Codex 建議文案候選，在隔離 CLI 的 10 次有效試跑中均收到建議、重新委派，並觀察到子代理使用 `gpt-5.6-luna / low` 完成任務；日常及桌面 App 的接受仍由 A／C 處理。

### B 的 CLI 交付（MRH-002-CLI-B-001）

- 只增加 Codex 建議文案：要求重新呼叫 `spawn_agent`、使用 `fork_turns="none"`，並提供必要的子任務上下文；Claude 文案、引擎及資料契約不變。
- 重用 9 次批次＋pilot3，有效試跑為 10/10；全部啟動共 12 次，另兩次前置試跑的缺少 Hook 證據／未設定候選模型情況完整保留。實際模型與推理強度取自官方 `thread/read`，不只看 DB 的 `followed`。詳見 [CLI 證據](../evidence/l2-codex-advice-20261013.json)。
- 原始 343 項單元測試只有 PLAN §15 的 5 個既有失敗，輸入未變而沿用；同候選的 Claude smoke 新一輪 **9/9**。候選封裝為 `dist/model-routing-harness-0.4.0-codex-advice`，程式內容與已安裝、daily 及 scratch runtime 一致，B 未重裝。
- 日常設定仍為 `enabled=true / provider=jev`；Claude settings、Codex hooks 與 launcher 均符合保留的原始雜湊。C 獨占正常 Codex registry／trust／App 驗證，B 不並寫；本交付不宣稱桌面或整體完成。

### 已確認的事實（不要重做）
1. Codex 0.159.3 交給 Hook 的 `tool_input.message` 是**密文**（`gAAAA…` Fernet 格式），換模型、換 multi_agent 設定都一樣。可讀欄位只有：`task_name`（主模型取的短標籤，如 `rename_variable`）、`model`、`cwd`、`transcript_path`、`turn_id`。目前用 `task_name` 分級（Jev 對 slug：改名類 Light 0.85–0.97、調查類 Mid 0.99、設計類 Top 0.65，含糊的低於門檻放行）。
2. 主模型幾乎每次帶 `agent_type: "worker"`、`fork_turns: "all"`。`worker` 已設為「視為預設角色」（`policy.generic_roles.codex`）；使用者自訂的 `luna_worker`、`risk_reviewer` 等 7 個角色一律不干預。
3. 舊 L2 兩次有建議的跑法：一次主模型回報「被擋」就停（提示詞寫了 exactly once）、一次自己做完；當時 **0/2 照建議改派**。此為歷史基準；新文案候選的隔離 CLI 結果為上列 10/10。Claude Code 舊對照：6/6 照建議改派。
4. Codex 工具名為 `spawn_agent` 或 `collaborationspawn_agent`；PostToolUse 的 `tool_response` 是 JSON 字串，含 `agent_id` 或 `task_name`。
5. Codex 外掛已刷新為 0.4.0；hook 定義（`hooks.json`）改指向固定安裝路徑，**使用者還需在 Codex `/hooks` 信任 2 個 hook**（Pre／PostToolUse），否則 Codex 端不會作用。

### 建議的工作順序
| # | 工作 | 說明／驗收 |
|---|---|---|
| 1 | 確認 hook 在 Codex CLI 與 **桌面 App** 都載入並信任 | App 完全沒實測過。原 C 的 probe：`docs/advisory-app.md`、`scripts/verify_app_advisory.py` |
| 2 | 讓主模型照建議做，擇一或組合，**各測 ≥10 次記錄遵從率** | (a) 調整 `advice_text.advise()` 的 Codex 措辭（強調「重派是預期做法，不是錯誤」）；(b) **直接填入模式**：Claude Code 實測 `updatedInput` 可讓 hook 直接改寫 model/effort（子代理實際跑 haiku 5.5、主模型不知情、不用多一個來回）；Codex 早期 E 階段也驗證過 allow＋updatedInput 可改子模型，但當時因「看不到角色／原模型」而放棄——現在已知 `agent_type` 可讀、明示 model/effort 可讀，條件足夠；(c) 不要把兩平台強綁同一模式，做成**每平台可設定**（`ctrl`：advise／fill） |
| 3 | 改善 Codex 分級依據 | `task_name` 太薄。評估用官方 `UserPromptSubmit` hook 把使用者原話存進 advice DB（以 session＋turn 為鍵），委派時一併送分級；這會多一個 hook（需再信任一次）。注意：**不要讀 `transcript_path`**（私人紀錄，先前規範禁止） |
| 4 | `fork_turns: "all"` 時改 model 是否被接受 | 未測。若 Codex 對 fork 忽略／拒絕 model，建議無效，需在 `CodexHost` 標記並放行 |
| 5 | Gemini CLI hook | 目前只有模型清單。先確認 0.63.0 有無工具前 hook 與子代理工具 |
| 6 | 清理舊模組 | 清單見 `HANDOFF.md`「未完成」第 7 點；**刪前確認 Claude 路徑沒用到**，並跑回歸檢查 |

## 二、改哪裡 Claude 會壞（必讀）

**同一份程式碼同時服務兩邊**。Claude 的 hook 與 Codex 的 hook 都執行 `runtime.pyz`（由 `mrh plugin prepare` 打包），所以任何共用檔案的改動，部署後 Claude 立刻吃到。

### A. 共用、改了兩邊都受影響
| 檔案 | 風險 |
|---|---|
| `src/mrh/advisory/engine.py` | 決策規則順序（明示→重放→去重→分級→門檻→Top→候選）。改順序或條件會同時改變兩邊行為；Claude 的「通用型子代理＝無角色」由 host 層決定，**不要在 engine 內寫平台特例** |
| `src/mrh/advisory/store.py` | advice.sqlite3 schema。只能 `CREATE IF NOT EXISTS`／加欄位要寫遷移；統計與報表都讀它 |
| `src/mrh/advisory/advice_text.py` | `EFFORT_PARAM = {"codex": "reasoning_effort", "claude": "effort"}`：**兩個參數名不同，不要統一**。改建議措辭先看 `tests/application/test_advisory_runtime.py` 的斷言 |
| `src/mrh/infrastructure/settings_v2.py` | 設定 schema（`policy.tiers.<等級>.<平台>` 各平台各一份清單、`generic_roles`、`threshold`）。改欄位會讓兩邊與 `mrh ctrl` 一起壞；v1 讀取遷移仍需保留 |
| `src/mrh/application/advisory_runtime.py` | hook 入口（閘門：未啟用／範圍外→不碰任何東西）。任何例外必須回 `{}`（放行） |
| `src/mrh/infrastructure/plugin.py` 的 `LAUNCHER` | 兩邊共用同一支 `launcher.py`；Claude 的 hook 以**命令列參數 `claude`** 指定平台，Codex 用 `binding.json` 的 `platform`。不要改參數協定、不要要求 binding 新欄位 |
| `src/mrh/adapters/providers/*` | Jev／Codex 訂閱／Claude 訂閱分級器，兩邊共用 |

### B. 只屬於 Claude，請不要「順手一般化」
- `src/mrh/adapters/hosts/advisory_hosts.py` 的 **`ClaudeHost`**：工具名 `Agent`／`Task`；欄位 `prompt`、`description`、`subagent_type`、`model`、`effort`；`subagent_type` 為空或 `general-purpose` 才當作無角色；PostToolUse 的 `tool_response.agentId`／`resolvedModel`。`CodexHost` 與它各自獨立，請只改 `CodexHost`。
- 共用小函式 `_text`、`_model`、`_readable_task`、`HOSTS` 字典：改簽名前先 grep 兩個 host 的使用處。

### C. 部署／路徑（動了 Claude hook 就失效，且不會擋工作但會悄悄停止分級）
- Claude 的 hook 寫在 `~/.claude/settings.json`，命令是：
  `~/.local/share/model-routing-harness/app/runtime/bin/python3.11 -I -B <repo>/runtime/daily-cli/artifact/plugins/model-routing-harness/launcher.py claude`
  → **不要搬移／改名／刪除**：安裝目錄 `~/.local/share/model-routing-harness/app`、`runtime/daily-cli/artifact`、其中的 `launcher.py`、`binding.json`、`runtime.pyz`。
- Codex 的 `hooks.json` 內容一改，Codex 會要求使用者重新 `/hooks` 信任（Claude 不受影響，但請先告知使用者）。
- 兩個 hook 共用同一個 `settings.json`（`runtime/daily-cli/profile/`）與 `advice.sqlite3`。不要換路徑。
- 升級流程（hooks.json 不變→Codex 不用重新信任；Claude 命令不變→不用重寫）：重建封裝 → `scripts/packaging/install_local.py` → `mrh plugin prepare --advisory …`（同參數）→ `codex plugin add model-routing-harness@model-routing-harness-local`。細節見 `README.md`「安裝」。

### D. 任何改動後必做的回歸檢查
```sh
PYTHONPATH=src python3 -m unittest discover -s tests -t .       # 只允許 PLAN.md §15 列的 5 個既有失敗
# 重建封裝並安裝後：
python3 scripts/verification/claude_smoke.py                    # 9/9 必須通過（約 $0.3；用獨立 scratch，不碰日常資料）
```
`claude_smoke.py` 驗證：Claude hook 安裝完整、輕量任務被建議且主模型改派 Haiku 5.5＋effort、內建 Explore 不被干預、使用者／主模型指定的模型被尊重、Jev 金鑰錯誤不擋工作。**失敗就不要交付。**

## 三、其他提醒
- **金鑰**：只在 macOS Keychain（`mrh key status jev`）或 `TYPESAFE_API_KEY`。不得寫入任何檔案、報告、commit。
- **分級器預設是 Jev**，不要改成 Codex 訂閱（10/11 那次是誤解使用者問題；使用者明確要 Jev）。
- **使用者決策**：路由是「建議式」（10/12），不是強制改寫。要新增 fill 模式，必須是**可切換、每平台可設定**，並先問使用者。
- **日常已啟用**（2026-10-13）。測試請用獨立 scratch 設定與目錄，不要在日常設定上開關；測試紀錄別留在日常 `advice.sqlite3`（會污染統計）。
- 使用者要求測試要精簡、只測風險／關鍵／特殊；文件保持精簡。
- 紀錄：進入實作請照 `/Users/shawn/Code/AGENTS.md`，任務紀錄在 Canopy `logs/progress`；本輪 Claude 的任務是 `TK20261013-133016-B15B`，可作為摘要參考。
