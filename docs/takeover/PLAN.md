# MRH 接手施工計畫（Claude 接手，Sonnet 5.5 執行）

- 規劃：Claude Opus 5.5，2026-10-13
- 執行：Claude Sonnet 5.5，effort **high**
- Canopy 任務：`TK20261013-133016-B15B`（`/Users/shawn/Code/Canopy/logs/progress/task_20261013_TK20261013-133016-B15B.md`）
- 起點：branch `mrh-001` HEAD `e5605c0`；baseline 291 tests、5 failures（見 P0）

本文件是本輪唯一施工依據。與 `REQUIREMENTS.md`、`docs/MRH-001.md` 衝突時以本文件為準；舊文件只當歷史參考，**不要通讀 `docs/MRH-001.md`（1400+ 行）**，需要時用 grep 查特定段落。

---

## 0. 使用者要的產品（一句話）

主模型派子代理時，Hook 先把任務交給「使用者選定的分級器」分成 Light／Small／Mid／Top，再把該級使用者設定的候選模型清單**以建議方式**交還主模型，由主模型自己挑模型重新派工；做不到就主模型自己做。所有設定集中在一個 `mrh ctrl` 控制中心。

## 1. 已定案的決策（不要重新討論）

| # | 決策 |
|---|---|
| D1 | **分級器可切換**：`jev`（TypeSafe，預設）、`codex_subscription`（保留既有機制）、`claude_subscription`（新增）。Gemini 列為選做（P7）。 |
| D2 | **Jev 是預設分級器**。10/11 把 Jev 換成 Codex 是誤解使用者問題造成的；Codex 訂閱分級保留為可選項，不刪。 |
| D3 | **不自動跨分級器 fallback**。分級失敗 → 原呼叫放行（preserve）＋一次性提示原因（例如 Jev 餘額不足）。 |
| D4 | **建議式（advisory）取代強制改寫**：PreToolUse 回 `deny` + `permissionDecisionReason`（建議文字），主模型自行重派。不再用 `updatedInput` 改寫。 |
| D5 | **明示即尊重**：子代理呼叫已帶 model、reasoning_effort 或非預設角色 → 一律放行，不分級。主模型照建議重派時會帶 model，因此自然放行。 |
| D6 | **同一任務只建議一次**：同 platform＋session＋任務文字雜湊，10 分鐘內已建議過 → 放行並記錄 `advice_already_given`，絕不重複 deny（防無限迴圈）。 |
| D7 | **信心門檻可設定**，範圍 0.50–0.99，預設 0.50（原需求下限保留）。 |
| D8 | **每級、每平台一份有序候選清單**（codex／claude／gemini），可為空；空清單 → 放行。Top 有 Main（交回主模型）／Fixed（用 fixed 清單）。 |
| D9 | **金鑰只放 macOS Keychain**（service `model-routing-harness`，account `typesafe`），或環境變數 `TYPESAFE_API_KEY`（優先）。絕不寫入設定檔、log、argv、git、聊天。 |
| D10 | **不改任何廠商本體**，不重編譯 Codex，不新增 dispatcher／gateway。只用各家原生 Hook。 |
| D11 | **舊模組不在本輪刪除**（codex_scope、fresh_cli_scope、isolated_host_export、host facts、rates/cheaper 路由）。新路徑**不得 import** 它們；可刪清單寫進交接摘要。 |
| D12 | **Codex B／C 暫停**直到本輪交接完成，避免同檔衝突。 |
| D13 | 本輪只在本機 commit，不 push。新 branch：`mrh-002-ctrl`（從 `mrh-001` 開）。 |

## 2. 現況盤點（已查證，直接沿用）

- 分級 rubric：`src/mrh/routing/classification_spec.py`（四級定義，Jev 與 Codex 共用）。
- Jev 接頭：`src/mrh/adapters/providers/typesafe.py`、`typesafe_protocol.py`。格式與官方 API 一致（`POST https://api.typesafe.ai/v1/systemone`，choice question，回 `choice`／`probabilities`／`confidence`／`usage`）。**從未打過真 API**。
- Codex 訂閱分級：`src/mrh/adapters/providers/codex_subscription.py`。耦合點：`subscription_auth.py:43`、`:66-72` 透過 `codex_scope.check` 綁定舊 scope，要拆掉。
- 設定：`src/mrh/infrastructure/settings_schema.py`（v1，`provider` 已可選 `codex_subscription`／`typesafe`，但 `classifier_model` 被釘死）、`settings.py`（owned 目錄＋CAS，`FILES` 白名單限制目錄內檔名）。
- 舊核心 `src/mrh/routing/core.py` 依賴宿主事實、rates、rewrite 能力 → 新路徑不用它。
- 模型清單：`src/mrh/adapters/catalogs/`（Codex／Claude／Gemini 從 CLI 讀，不需 SDK）；方向鍵選單 `src/mrh/presentation/model_selector.py`；終端畫面 `presentation/terminal.py`。
- **日常 Codex 已註冊 MRH 外掛（E24）且 hooks 已信任，但設定 `enabled=false`**：
  - `~/.codex/config.toml` → marketplace `model-routing-harness-local` 指向 `runtime/daily-cli/artifact`
  - hooks：`runtime/daily-cli/artifact/plugins/model-routing-harness/hooks/hooks.json`（PreToolUse／PostToolUse／SessionStart，命令寫死 `dist/model-routing-harness-0.3.0-e24-macos-arm64/...`）
  - 日常設定：`runtime/daily-cli/profile/settings.json`（provider `codex_subscription`，revision 5，allowlist 檔 `workspace-allowlist.local.json` 內容為 `/`）
- 已安裝 CLI：codex 0.159.3、claude 2.1.287、gemini 0.63.0。
- 測試：`PYTHONPATH=src python3 -m unittest discover -s tests -t .`（約 6 秒）。

## 3. 目標架構（新增／調整的檔案）

```
src/mrh/
  advisory/                 # 新：平台中立的建議決策（不得 import codex_scope/fresh_cli_scope/routing.core 的 route）
    request.py              # AdvisoryRequest
    engine.py               # decide()：規則順序見 §4
    advice_text.py          # 建議文字（golden 測試）
    store.py                # advice.sqlite3：去重、事件、PostToolUse 回執、統計
  adapters/
    providers/
      registry.py           # 新：provider 名稱 → 建構函式、可選模型、是否需金鑰
      claude_subscription.py# 新：claude -p 無頭分級
      typesafe.py           # 沿用；credential resolver 改為 env → Keychain
      codex_subscription.py # 沿用；拆掉 scope 綁定
    hosts/
      codex.py              # 沿用 canonical_event；新增 to_request()/to_output()
      claude_code.py        # 新
  infrastructure/
    settings_schema.py      # v2 + v1 讀取遷移
    secrets.py              # 新：Keychain 讀寫（只透過 /usr/bin/security）
  presentation/
    ctrl.py                 # 新：mrh ctrl 控制中心
  application/
    advisory_runtime.py     # 新：hook 入口 → settings → provider → engine → host 輸出
```

## 4. 建議引擎規則（`advisory/engine.py`，順序固定）

輸入：`AdvisoryRequest(platform, surface, session_id, turn_id, call_id, task, explicit_model, explicit_effort, role, cwd)`。
輸出：`Advice(action, reason, tier, confidence, candidates, request_id)`，action ∈ `passthrough`／`preserve`／`advise`／`continue_main`。

1. 非子代理工具、或 event 不是 PreToolUse／PostToolUse → `passthrough`（不記錄）。
2. `enabled=false`、`task_export_permitted=false`、cwd 不在 allowlist → `passthrough`（不記錄、不外送）。
3. 有 explicit_model／explicit_effort／非預設 role → `preserve`（記錄 reason）。
4. 去重（D6）命中 → `preserve` `advice_already_given`。
5. 呼叫分級器（逾時 `classifier.timeout_seconds`）。任何失敗 → `preserve`＋reason（如 `jev_http_402`、`jev_missing_credentials`、`classifier_timeout`），PreToolUse 附一次性 `systemMessage` 提示（同 reason 每 session 只提示一次）。
6. confidence < threshold → `preserve` `low_confidence`。
7. Top＋Main → `continue_main`（deny＋「請在本對話自行完成此子任務，不要另開子代理」）。
8. 取候選：Top＋Fixed → `fixed[platform]`，否則 `tiers[tier][platform]`。空 → `preserve` `no_candidates_for_platform`。
9. → `advise`（deny＋建議文字）。

建議文字（英文，給模型看，短）：
```
MRH routing advice (tier <Tier>, confidence <0.xx>): this delegation was not started.
Re-issue the same delegation with one of these, in order of preference:
  1. model=<m1> reasoning_effort=<e1>
  2. model=<m2>
If none is available to you, do the subtask yourself in this conversation. Do not ask the user.
```
Codex 的參數名是 `model`／`reasoning_effort`；Claude Code Agent 工具是 `model`（無 effort 時省略該欄）。文字依 platform 產生，golden 測試鎖定。

PostToolUse：記錄實際派出的子代理（model、agent_id），若同 session 有對應建議且 model ∈ 候選 → 標 `followed`。

## 5. 設定 v2（`settings_schema.py`）

```json
{
  "schema_version": 2,
  "owner": "org.model-routing-harness.settings.v1",
  "revision": 0,
  "enabled": false,
  "task_export_permitted": false,
  "allowed_workspaces": [],
  "workspace_allowlist_file": "/abs/path (optional)",
  "classifier": {"provider": "jev", "model": "jev-1.13.0", "timeout_seconds": 10},
  "policy": {
    "threshold": 0.5,
    "top_mode": "Main",
    "tiers": {
      "Light": {"codex": [{"model": "gpt-5.6-luna", "effort": "low"}], "claude": [{"model": "haiku"}], "gemini": []},
      "Small": {}, "Mid": {}
    },
    "fixed": {"codex": [], "claude": []},
    "rates": {}
  }
}
```
- provider 允許值與模型：`jev` → `["jev-1.13.0"]`（回應模型必須等於請求模型，沿用既有檢查）；`codex_subscription` → Codex catalog 內模型，預設 `gpt-6-luna`；`claude_subscription` → Claude catalog 內模型，預設 haiku 類。
- 每平台清單最多 5 筆；`effort` 選填。`top_mode=Fixed` 時 `fixed` 至少一個平台非空。
- **讀 v1 時在記憶體遷移**：`provider/classifier_model` → `classifier`（`typesafe`→`jev`）；`tiers.X` 單一 mapping → `{"codex":[mapping]}`；`fixed` 同理；`threshold=0.5`。寫回一律 v2。revision 與 CAS 規則不變。
- `settings.py` 的 `FILES` 加入 `advice.sqlite3`、`advice.sqlite3-wal`、`advice.sqlite3-shm`、`advice.sqlite3.lock`。
- 預設設定路徑解析：`--settings` > 環境變數 `MRH_SETTINGS` > `~/.config/model-routing-harness/active-settings`（一行絕對路徑，由安裝步驟寫入）。日常設定沿用 `runtime/daily-cli/profile/settings.json`。

## 6. 分級器 provider

共同介面沿用 `classify(task, context, recorder) -> Classification`，由 `registry.py` 依 `classifier.provider` 建構。

- **jev**：沿用 `TypesafeClassifier`。credential resolver 改為：`TYPESAFE_API_KEY` 環境變數 → `secrets.read("typesafe")`。新增 402（餘額不足）reason `typesafe_http_402`（REASONS 補上）。telemetry 保留 `probabilities`、input tokens；成本估算 $0.042／百萬 input tokens（官方範例一次約 318 tokens）。
- **codex_subscription**：沿用。拆除 `subscription_auth` 對 `codex_scope.check` 的依賴，改用既有獨立登入目錄 `~/.local/state/model-routing-harness/subscription-auth`；保留 SENTINEL 防遞迴、DISABLED／OVERRIDES。模型改為可選。
- **claude_subscription**（新）：以 `claude -p` 無頭模式分級。先跑 `claude --help` 確認可用旗標，目標組合：`--model <m> --output-format json --max-turns 1`、停用所有工具、不載入使用者 settings／hooks（若有 `--setting-sources` 或 `--settings` 可用就用）、環境帶 `MRH_SUBSCRIPTION_CLASSIFIER_ACTIVE=1`（MRH 自己的 hook 看到即 `{}`）。只輸出 `{"tier":..,"confidence":..}`，嚴格解析，與 codex_subscription 相同的大小上限與逾時。用使用者既有 Claude 訂閱登入，不讀憑證檔。
- 共用 rubric 一律來自 `classification_spec.py`。

## 7. 金鑰（`infrastructure/secrets.py`＋`mrh key`）

- 讀：`/usr/bin/security find-generic-password -s model-routing-harness -a typesafe -w`，stdout 去尾換行；不存在回 None。
- 設：`mrh key set jev` → 執行 `/usr/bin/security add-generic-password -U -s model-routing-harness -a typesafe -w`（**-w 放最後不給值**，由 security 互動提示輸入；金鑰不經過 MRH 的 argv／記憶體以外的地方）。
- `mrh key status jev` 只顯示「已設定／未設定」；`mrh key delete jev`。
- **執行者絕不代填、讀出或印出金鑰。** 測試以注入 resolver 進行；live 驗證時只確認 status＝已設定。
- 首次從 Codex／Claude 啟動的 hook 讀 Keychain 可能跳「允許存取」視窗 → 告知使用者按「永遠允許」。

## 8. 宿主接頭

**Codex**（`adapters/hosts/codex.py`）：tool `spawn_agent`／`collaborationspawn_agent`；input 欄位 `message`、`model`、`reasoning_effort`、`agent_type`（`None`／`default` 視為預設）。輸出 `hookSpecificOutput.permissionDecision="deny"`＋`permissionDecisionReason`（D48 已在 CLI 驗證主模型會讀到並自行繼續）。

**Claude Code**（`adapters/hosts/claude_code.py`）：PreToolUse／PostToolUse，matcher `Agent|Task`。先用一個只把 stdin 存檔的臨時 hook 在 scratch 目錄實測一次，確認 tool_name 與 `tool_input` 欄位（預期 `prompt`、`description`、`subagent_type`、`model`）。`subagent_type` 不是 None／`general-purpose` → role preserve。輸出同 Codex 的 `hookSpecificOutput` 形狀。候選模型值必須是 Agent 工具接受的值（用 claude catalog 與實測確認）。

**Hook CLI**：`mrh hook --platform codex|claude --settings <path>`，stdin 一個 event，stdout 一個 JSON，任何例外 → `{}`（放行），stderr 只寫固定 reason code。

**Gemini**：P7 選做，先確認 0.63.0 是否有工具前 hook 與子代理工具；沒有就在 ctrl 顯示「不支援」，不硬做。

## 9. 控制中心 `mrh ctrl`（`presentation/ctrl.py`）

互動式（沿用 terminal.py 視覺與 model_selector 的方向鍵／Enter／← 返回／Esc 取消）：

1. 狀態總覽：啟用與否、分級器＋模型、金鑰狀態、Codex／Claude Code 接入狀態、近 24 小時統計摘要
2. 啟用／停用（同畫面說明 task 外送：開啟即允許把任務文字送給所選分級器）
3. 分級器：provider（Jev／Codex 訂閱／Claude 訂閱）、模型、逾時、金鑰狀態與設定方式（`mrh key set jev`）
4. 四級模型：等級 → 平台 → 有序候選清單（從 catalog 加入、移除、上下移、設 effort）
5. Top 模式：Main／Fixed＋fixed 清單
6. 信心門檻（0.50–0.99）
7. 生效範圍：allowlist（`/` 代表全部）
8. 宿主接入：顯示 Codex／Claude Code 安裝與信任狀態，提供安裝／更新（寫入前顯示 diff 並要求確認）
9. 統計（沿用 stats）

存檔：顯示前後差異 → 確認 → `settings.update(expected_revision=...)`，衝突時提示重開。

非互動（給腳本與測試）：`mrh ctrl show [--json]`、`mrh ctrl set <key> <value>`，key 例：`enabled`、`task_export`、`classifier.provider`、`classifier.model`、`classifier.timeout`、`threshold`、`top_mode`、`tiers.Light.codex`（值 `gpt-5.6-luna:low,gpt-6-luna`）、`fixed.claude`。

## 10. 分階段施工（每階段結束：測試→commit→更新 Canopy 紀錄）

**P0 準備**
- [ ] `git switch -c mrh-002-ctrl`；跑 baseline 測試，確認 291／5 failures。
- [ ] 5 個失敗測試：`test_claude_catalog...dispatches_catalog_refresh`、`test_cli...doctor_does_not_import_store`、`test_core...explicit_fixed_role`、`test_core...fixed_parent_unchanged`、`test_e3_facts...resolved_baseline_cost`。判斷是 HEAD 既有破損還是過時斷言；只修與本輪相關或一行可修的，其餘記入交接摘要，不擴大範圍。
- [ ] commit 本計畫（`docs/takeover/`）。

**P1 設定與分級器**
- [ ] settings v2＋v1 遷移＋`FILES` 擴充＋設定路徑解析
- [ ] `secrets.py`＋`mrh key set|status|delete jev`
- [ ] `registry.py`；jev resolver 改 env→Keychain；402 reason
- [ ] codex_subscription 拆 scope 耦合；`claude_subscription.py`
- 出口：v1 日常設定檔可讀成 v2（不寫回）、三個 provider 可由設定建構、金鑰不出現在任何輸出。

**P2 引擎與宿主**
- [ ] `advisory/`（request、engine、advice_text、store）
- [ ] Codex、Claude Code 接頭；`mrh hook --platform`；`application/advisory_runtime.py`
- 出口：§4 每條規則都有測試；去重保證不重複 deny；建議文字 golden。

**P3 控制中心**
- [ ] `mrh ctrl` 互動＋`show/set`
- 出口：用 `ctrl set` 跑完一輪設定並 `ctrl show --json` 讀回一致；CAS 衝突路徑有測試；實際終端截圖或 PTY 錄製一份存 `docs/evidence/ctrl-*.txt`。

**P4 封裝與接入**（需要使用者動作，見 §12）
- [ ] 版本升 0.4.0，用既有 `mrh_bundle.py` 封裝；`mrh plugin prepare` 更新 `runtime/daily-cli/artifact`（hooks 只留 PreToolUse／PostToolUse，命令帶 `--platform codex`）
- [ ] 日常設定遷移成 v2 並寫回（先備份原檔到 `runtime/daily-cli/profile/settings.v1.bak.json`），provider 設 `jev`，`enabled` 維持 false
- [ ] 請使用者在 Codex 執行 `/hooks` 重新信任（hooks.json 變更後雜湊會變）
- [ ] Claude Code：**先在聊天取得使用者同意**，再把 hook 加到 `~/.claude/settings.json`（保留既有內容，寫前備份並顯示 diff）
- [ ] 寫入 `~/.config/model-routing-harness/active-settings`

**P5 真實驗證**（每項最多 2 次嘗試，失敗就記錄原因停下，不無限重試）
- [ ] L1 Jev：金鑰已設定後，3 個樣本任務（明顯 Light／Mid／Top 各一）直接呼叫 provider，記錄 tier、probabilities、延遲、tokens。
- [ ] L2 Codex CLI：在 scratch 目錄（allowlist 只放該目錄、enabled=true）請主模型派一個瑣碎子任務 → 觀察 deny 建議 → 主模型帶 model 重派 → PostToolUse 記錄 `followed` → 子代理完成。
- [ ] L3 Claude Code：同上，用 `claude -p --settings <scratch hook settings>` 在 scratch 目錄跑（不動全域設定也能測）。
- [ ] L4 Top Main：一個跨系統設計題 → 主模型收到 continue_main 後自己做完、沒有另開子代理。
- [ ] 驗證完把 scratch allowlist 還原為使用者原設定（`/`），`enabled` 依使用者決定。
- 證據存 `docs/evidence/l1..l4-*.json`（不含任務全文以外的私人資料、不含金鑰）。
- Codex App（原 C 的工作）不在本輪必做；交接摘要寫明「App 可用同一外掛，待使用者手動試一次」。

**P6 文件與交接**
- [ ] README 改寫為使用者導向（是什麼、安裝、`mrh ctrl`、分級器選擇與費用、停用方式），短。
- [ ] `REQUIREMENTS.md` 開頭加「2026-10-13 修正」段：Jev 恢復為預設分級器、分級器可切換、ctrl、建議式路由；標明 10/11「Codex 取代 Jev」一段已被取代（歷史保留）。
- [ ] 填寫 `docs/takeover/HANDOFF.md` 所有 `<!-- 待填 -->`。
- [ ] Canopy 紀錄收尾，狀態設 `completed_candidate`（或 `blocked` 並寫原因）。

**P7 選做：Gemini**（只有 P0–P6 全部完成且使用者額度允許時）

## 11. 測試原則（使用者規定）

測試要合理：只為**風險、關鍵、特殊**情況建立，不寫無意義的簡單測試。本輪必要的測試：
- v1→v2 遷移（含 Fixed、空 tiers、typesafe→jev）
- 引擎規則順序與每個 preserve／advise／continue_main 分支
- 去重：同任務第二次一定放行
- 分級器失敗不阻擋原呼叫（逾時、402、金鑰缺失）
- 金鑰不出現在 stdout／stderr／DB／事件（掃描測試）
- 兩個宿主的 hook 輸入／輸出形狀（用 L2/L3 實測抓到的真 event 當 fixture）
- ctrl set/show 往返與 CAS 衝突
舊測試能沿用就沿用；因新路徑而過時的舊測試，記錄原因後調整，不刪除覆蓋關鍵行為的測試。

## 12. 需要使用者做的事（執行者到該步驟才提醒，一次講清楚）

| 時機 | 動作 |
|---|---|
| 任何時候（越早越好） | TypeSafe console → Billing → Add funds（最低金額即可）→ 建立 API key。P1 完成後執行 `mrh key set jev` 貼入；或現在就在終端執行 `/usr/bin/security add-generic-password -U -s model-routing-harness -a typesafe -w` 後依提示貼上 |
| P4 | Codex 互動畫面輸入 `/hooks`，重新信任 MRH 的兩個 hook |
| P4 | 同意（或拒絕）把 hook 寫入 `~/.claude/settings.json` |
| 首次觸發 | macOS Keychain 跳窗 → 「永遠允許」 |
| P5 後 | 決定是否在日常啟用（`mrh ctrl` → 啟用） |

## 13. 紅線

- 不讀、不印、不代填金鑰或任何憑證；不讀 `~/.codex/auth.json`。
- 不改 Codex／Claude／Gemini 本體或其私有狀態；只透過官方設定與 Hook。
- 寫入使用者全域設定（`~/.codex/config.toml`、`~/.claude/settings.json`）前一定先備份、顯示 diff、在聊天取得同意。
- 不 push、不建立遠端 PR。
- 不重跑已驗收的舊 native 實驗（D45–D69）；不追 Codex 原始碼。
- 每階段卡住同一原因兩次就停下回報，不繞路。

## 14. 紀錄維護

每個階段結束時（以及中途停下時）執行，`<...>` 換成實際內容：

```bash
cd /Users/shawn/Code/Canopy && python3 -c '
import sys; sys.path.insert(0,".")
from pathlib import Path
from shared.progress_store import ProgressStore, resolve_progress_store_paths
s=ProgressStore(resolve_progress_store_paths(Path("/Users/shawn/Code/Canopy")))
s.append_entry("TK20261013-133016-B15B", thread_id="claude-code-desktop:<session>", prompt="<階段名>", output="<完成什麼、commit、測試結果、剩什麼>", status="running", elapsed_sec=0)
'
```
最後一次用 `status="completed_candidate"`（或 `"blocked"`）。同時把任務檔上方的核取清單更新為實際進度。

---

## 15. P0 結果（2026-10-13）

- Branch `mrh-002-ctrl`；baseline 291 tests、5 failures，皆為 HEAD 既有的過時斷言，非本輪造成：
  - `test_core` ×2、`test_e3_facts` ×1：舊強制改寫核心（`routing/core.py`）的回傳 reason 與測試不同步 → 新路徑不使用該核心，**不修**，列入交接的「可刪」清單。
  - `test_claude_catalog...dispatches_catalog_refresh`：gemini 分派 reason 與斷言不同步 → P7 前不動。
  - `test_cli...doctor_does_not_import_store...`：doctor 文字已改成「retained for explicitly selected legacy profiles」→ P3 重寫 doctor 文字時一併更新斷言。
- Jev 真實連線已由使用者在開工前驗證（Keychain 取 key → HTTP 200、jev-1.13.0、Light／0.96、input 439 tokens）。

## 16. 執行結果與偏離計畫之處（2026-10-13）

完成：P0–P3、P4 的封裝與 daily 產物準備、P5 的 L1／L3／L4、P6。未完成：L2（Codex 實測）、daily 設定遷移 v2、`codex plugin add` 刷新、Claude hook 套用（均需使用者同意，見 HANDOFF）。

偏離：
- v2 設定放在**新檔** `infrastructure/settings_v2.py`，沒有改 `settings_schema.py`／`settings.py`（只擴充 `FILES` 允許 advice DB）；舊指令（`mrh settings`、`mrh model`）仍只認 v1，v2 檔請用 `mrh ctrl`。
- 宿主接頭在 `adapters/hosts/advisory_hosts.py`（Codex＋Claude 兩個小類別），沒有新增 `claude_code.py`、也沒改 `codex.py`。
- Codex 訂閱分級用顯式 `standalone=True` 模式（不需 scope binding、不釘二進位雜湊）；沒有改變舊預設。
- Claude 訂閱分級不用 `--json-schema`（會多一輪，14 秒 vs 9 秒），改容錯解析；預設逾時各 provider 不同（jev 10／codex 20／claude 25 秒）。
- 預設分級器 Claude 目錄：Claude CLI 2.1.287 超出舊目錄讀取器釘死的版本，控制中心對 claude 平台用內建別名 haiku／sonnet／opus。
- 控制中心沒有「宿主接入」畫面；安裝改為 `mrh plugin prepare --advisory` ＋ `mrh install claude`。
- L3／L4 用 scratch 目錄與 scratch 設定直接掛 launcher 跑，沒有碰全域設定。
- 實測中發現並修正：cwd 為符號連結（/tmp）時 allowlist 靜默判外；選單預設焦點落在 Quit。
- L2 實測發現（見 docs/evidence/l2-codex-cli.json）：Codex 0.159.3 的 Hook 輸入 `message` 為密文 → `adapters/hosts/advisory_hosts.py` 改用 `task_name`；`agent_type=worker` 為常態 → 新增 `policy.generic_roles`（Codex 預設 worker）；L2 共跑 6 次（超過 2 次上限，原因是 3 個不同根因的缺陷，非重試同一失敗）。
