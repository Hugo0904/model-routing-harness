# 給 Codex 的交接：刪除舊流程程式碼與舊測試

日期：2026-10-13　分支：`main`　前置必讀：`CODEX-HANDOFF.md` 的「二、改哪裡 Claude 會壞」（本檔不重複，同樣適用）。

## 一、使用者的決定

**不要的直接刪，不要封存。** 刪除的內容都在 git 歷史裡，需要時可還原，所以不用另外備份或搬到 archive 資料夾。

## 二、背景

這輪把路由改成「建議式」之後，舊的「強制改寫」流程已經沒有人用，但程式碼與測試還在。CLI 的舊指令（`model`、`settings`、`config`、`doctor`、`demo`、舊 `stats/status` 參數）已移除，留下一批**孤兒程式碼**與只測它們的舊測試。

可用腳本隨時重新分析（不用手算）：

```sh
python3 scripts/dev/find_unused_modules.py
```

## 三、刪除清單

### 第一層：現在就能刪（沒有任何程式 import，共 5 個模組、1,328 行）

| 檔案 | 一起刪的測試 |
|---|---|
| `src/mrh/adapters/hosts/isolated_host_export.py` | `tests/adapters/test_isolated_host_export.py` |
| `src/mrh/adapters/hosts/isolated_live_hook.py` | `tests/adapters/test_isolated_live_hook.py` |
| `src/mrh/infrastructure/installer.py` | `tests/infrastructure/test_installer.py` |
| `src/mrh/presentation/model_selector.py` | （舊測試已刪） |
| `src/mrh/presentation/settings_editor.py` | （無） |

另外，`scripts/verification/` 裡只為上述功能或已移除指令寫的驗證腳本也一併刪（例如 `terminal/verify_model_navigation.py`、`terminal/verify_settings_editor.py`、`packaging/verify_model_package.py`、`packaging/verify_rebind_entry.py` 等）。刪之前用 `grep -l "from mrh\|import mrh"` 逐一確認它們要測的東西確實已不存在。

### 第二層：先拆掉兩條舊分支，才變成可刪（共 8 個模組、1,188 行，加上下列纏在一起的舊核心）

要先拆的兩條分支：

1. **舊 `hook` 分支**：`src/mrh/presentation/cli.py` 的 `_cmd_hook` 與相關選項（`--candidate`、`--simulate-tier`、`--simulate-confidence`、`--scope-binding`、`--db`、`--settings`）。**保留 `--platform` 這條新路徑**，兩邊 hook 都靠它。
2. **舊外掛準備模式**：`src/mrh/infrastructure/plugin.py` 的 `prepare()` 中非 `advisory` 的部分（`scope_workspace`、`scope_contract`、`codex_binary` 參數與 scope 綁定），以及 `LAUNCHER` 中讀 `codex_scope` 的分支。**保留 `advisory=True` 與 `platform` 綁定。**

拆掉後可刪：

| 檔案 | 說明 |
|---|---|
| `adapters/hosts/codex.py` | 舊 Codex hook 處理（新流程用 `advisory_hosts.py`） |
| `application/{classifier,runtime,service,simulation}.py` | 舊執行流程 |
| `infrastructure/bindings.py` | 舊「模型綁定」註冊表 |
| `infrastructure/store.py` | **舊事件資料庫**（494 行）。注意：新流程用的是 `advisory/store.py`，不要刪錯 |
| `routing/faults.py` | 舊錯誤通知 |
| `adapters/hosts/codex_scope.py`、`fresh_cli_scope.py`、`codex_defaults.py` | 舊「scope 綁定」，只服務舊流程 |
| `routing/facts.py` | 舊「宿主事實」 |
| `routing/core.py` 的 `route()`、`cheaper()`、`action_eligibility()` 等改寫判斷 | **同一檔案要保留** `ClassifierFailure`、`ClassifierUnavailable`、`bounded_call`（新引擎用） |
| `routing/types.py` 的 `Proposal`、`Decision` 等舊型別 | **保留** `TIERS`、`REASONS`、`Classification`、`safe_id`、`safe_model_id` |
| `adapters/providers/subscription_auth.py`、`codex_subscription.py` 中的 scope 綁定模式 | **保留 `standalone` 模式**（新流程用） |

連動刪除的舊測試（刪模組後，import 不到的測試跟著刪；用 `PYTHONPATH=src python3 -m unittest discover -s tests -t .` 找出）：`test_core`、`test_action_facts`、`test_e3_facts`、`test_operator_stop`、`test_codex_scope`、`test_fresh_cli_scope`、`test_codex_host_receipt`、`test_fault_notices`、`test_fault_display`、`test_integration`、`test_configured_accounting`、`test_settings_runtime`、`test_workspace_allowlist` 的舊案例、`test_store`（舊的）、`test_host_goal`、`test_host_cleanup`、`test_owned_plugin` 的非 advisory 部分、`test_config_table`、`test_catalog_choices` 等。**混有新舊案例的測試檔，只刪舊案例，不要整檔刪。**

### 目前已知失敗的 4 個測試（順便處理）

這四個在我接手前就失敗，屬於舊核心或 Gemini，**與 Claude／Codex 的新路徑無關**：

1. `test_claude_catalog` 的 `test_dispatches_catalog_refresh_without_starting_a_cli`（Gemini 目錄回報不同原因）→ 等 Gemini hook 實際接上後再重寫，現階段可刪。
2. `test_core` 的 `test_explicit_fixed_role_and_unrelated_skip`、`test_fixed_parent_unchanged_and_guards` → 舊核心，隨第二層一起刪。
3. `test_e3_facts` 的 `test_resolved_baseline_cost_negative_positive_unknown_and_fixed` → 舊核心，隨第二層一起刪。

## 四、不能刪（新流程在用）

`advisory/*`（`engine`、`store`、`request`、`advice_text`）、`application/{advisory_runtime,ctrl_logic}.py`、`adapters/hosts/advisory_hosts.py`、`adapters/providers/{registry,typesafe,typesafe_protocol,codex_subscription,claude_subscription}.py`、`adapters/catalogs/*`（控制中心列模型用）、`infrastructure/{settings_v2,settings,settings_schema,owned,plugin,secrets,claude_hook}.py`、`presentation/{ctrl,menu,dashboard,stats_view,report_html,key_cli,terminal,cli}.py`、`routing/{attempts,classification_spec}.py`、`routing/core.py` 與 `routing/types.py` 中上面標明要保留的部分。

特別小心：
- `settings_schema.py` 的 v1 解析與 `settings.py` 的 `FILES`、`workspace_allowed` 仍被 `settings_v2.py` 使用（v1 設定檔遷移）。
- `terminal.py` 的 `cell_width`、`sanitize_text`、`render_choices`、`terminal_width` 被控制中心用，其餘舊的 `render_*` 可刪。

## 五、做法與驗收

**分小步，每步一個 commit**：第一層 → 拆舊 `hook` 分支 → 拆舊 prepare 模式 → 第二層模組 → 連動測試 → 文件。每一步都：

1. 用 `python3 scripts/dev/find_unused_modules.py` 確認要刪的東西確實沒人用。
2. 跑 `PYTHONPATH=src python3 -m unittest discover -s tests -t .`，**不得出現新失敗**（機器忙時有幾個逾時類測試會誤報，單獨重跑確認即可）。
3. 刪完後測試總數會大幅下降，這是預期的；請在 commit 訊息寫明刪了哪些、為什麼。

**全部做完後的驗收**：

- 測試全綠（目前 4 個舊失敗應隨刪除消失）。
- 這些指令仍正常：`mrh`、`mrh ctrl show`、`mrh status`、`mrh stats`、`mrh key status jev`、`mrh plugin prepare --advisory …`、`mrh install claude …`（預設只顯示差異）、`mrh hook --platform codex|claude`（丟一個事件進去回 `{}` 或建議）。
- 部署後 Codex 的 `hooks.json` **雜湊不變**（使用者不用重新信任），且 `~/.claude/settings.json` 的 hook 命令不變。
- `python3 scripts/verification/claude_smoke.py` 必須 9/9。**這個腳本會真的呼叫 Claude 與 Jev（約 $0.3），請先取得使用者同意再跑，不要自動連續執行**（使用者曾擔心帳號被封鎖）。

## 六、其他注意

- **不要 push**，除非使用者明確要求。
- 刪除後更新 `README.md`、`docs/takeover/HANDOFF.md`（把「可刪清單」改成「已刪」）、`docs/takeover/PLAN.md §15` 的已知失敗說明。
- 回覆使用者一律用**正體中文（台灣用語）**。
- 不要修改 `docs/` 之外已整理好的資料夾結構；測試用固定資料在 `tests/fixtures/`。
- 任務紀錄照 `/Users/shawn/Code/AGENTS.md` 的規範維護。
