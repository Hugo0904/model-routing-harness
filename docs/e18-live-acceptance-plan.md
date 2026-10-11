# E18-C-001：真 Jev／真模型驗收準備

## A 整合決定 D42

A 已接受 E17R 修正版（D41）與 C 的 exact public schema 查證（`a8a1a7b`），採用本文件的隔離官方 app-server、真 Jev、原生 child 有效設定與結果讀回方案。實際 candidate 是 `/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.3.0-e17r-macos-arm64`；archive SHA256 `cdd8371c7d0dc91bd3658caad32f6f513cf48808be90bb37436d929c16aab60e`，manifest SHA256 `377b9bd2d679c782791ac14d2f34e40becf3a511b67f946543a68d54ba677b63`，prepared runtime SHA256 `b4cbe888b80b94512f6d97f243abe6cf4b4e06eed871794fe879393b252ce3ce`。後文 bundle placeholder 指此確定路徑；interactive argv 為 `codex --no-daemon --no-alt-screen -C <owned-workspace>`，收證據使用已接受的 `codex app-server --listen stdio://`。

一項依現有 native 證據的操作修正：E17R 使用 V2 `collaborationspawn_agent`，`receiverThreadIds` extractor 得到空集合，但原生事件實際包含不同於 parent 的 child `turn/completed.params.threadId`。因此後文 legacy `collabAgentToolCall/receiverThreadIds` 只在實際出現時使用，不是唯一 ID 來源，也不能從其缺席推論沒有 child。同一自有 RPC 連線收到 `thread/started` 或非 parent 的 `item/turn` 事件時，立即對該 ID 走公開 `thread/read`，核 `parentThreadId` 與原 parent 對應才納入；若 child 已完成但仍載入，讀回與 native 結果仍可相互核對。結果接回使用當前實際 V2 工具結果／訊息及同 parent 最後答案，不能要求一個未實際出現的 legacy wait item。Top Main 以真 MRH deny、完整本 turn 原生工具事件與無 replacement 委派、同 parent 實際完成交叉驗證，不以空 ID extractor 當零子任務證據。這是已知事件形狀的採證修正，沒有新增產品或重跑 scripted checks。

本輪最多三個測試回合，主要取得普通分級改寫及真 Top Main 的首次證據；Top 命中不保證，未命中如實保留。Top Fixed、同 Goal 後續委派等其餘原義務不因此取消或宣称全部 R1 完成。啟動需人類一次授權本文件的隔離安裝／信任／啟用、登入、公開測試文字外送與真帳戶用量，及提供遮罩輸入的 TypeSafe key。收到授權後由原 B 執行既定操作、A 驗收；C 準備單位至此接受，不再加查證。現在仍無真外部呼叫、登入或正式 Hook 啟用。

這份文件只完成 D39 的前置查證。沒有呼叫 Jev／模型、讀取秘密、安裝或啟用 Hook，也沒有執行產品測試。R1 仍待 A 驗收。B 保有 E17R runtime、fixture、封裝與整合所有權。

## 身分、授權與待置換資料

- A：`01a12262-186b-7670-9af0-59566703db4a`，local；C：`01a12b46-f59f-7cd3-88f3-43cf4116d603`，local。
- 已透過 `read_thread` 核實人類原訊息 `01a12b43-4a09-7630-a70e-37d842a4092e`（準備真驗收、一次說明授權、必要時建立 C）及 `01a12b43-9805-7f62-a772-194dd9c1b3ce`（允許不同分線 C）。只向同一 A 回報。
- 唯讀 settings helper 核實本 executing turn `01a12b46-f838-77e3-b9f7-9ab0e7796638` 為 `gpt-6.1-sol / high`。宿主聊天 cwd 是 Code 專案根 `/Users/shawn/Code`；全部專案命令明確使用 `/Users/shawn/Code/model-routing-harness`，`pwd` 已核對。沒有換模型或另建 checkout。
- 查證開始 HEAD：`dd1e3192781704e4de22f913d7abf704f37094d4`，branch `mrh-001`。A/B 已有 dirty edits，均保留。額度查讀為已用 41%，未觸及低於 7% 的保存停點。
- 執行前 A 必須以 B 的 **E17R-B-001** 填入：`<E17R_BUNDLE_ABSOLUTE_PATH>`、archive／manifest／installed runtime hashes，以及 `<B_ACCEPTED_INTERACTIVE_ARGV>`。舊 E17 final 包不能替代修正版。下文 `--no-daemon --no-alt-screen -C` 與 `app-server --listen stdio://` 是目前 E17R source 支援形式，尚待 B 的最終交付確認。

## 建議環境與官方登入

建議沿用已安裝、未修改的官方 native CLI，另用單一自有 E18 root 隔離 `CODEX_HOME`、workspace、MRH state、plugin。不更動原本 home、Hook、主模型或 App；沒有 gateway／新派工器。這也避開正式 home 的 Canopy／profile／額外設定層可能使初始 scope 拒絕的問題。原始 REQUIREMENTS 第八節要求隔離設定；首次實測不向人類正式 home 安裝。

官方 [Authentication](https://learn.chatgpt.com/docs/auth) 提供 `codex login status`、`codex login`、`codex login --device-auth`。沿用同一 home 且快取有效時，CLI 能沿官方介面使用現有登入；文件沒有提供「把 App 的登入匯出給另一個隔離 home」的介面。隔離 home 不假定已登入，先由官方 status 確認，再必要時正式瀏覽器登入。file store 會在 CODEX_HOME 留下憑證；其他 store 的跨 home 沿用不能從本輪資料保證。絕不複製 auth.json、不直接讀 keychain／session。登入頁或 MFA 需要人類本人操作，其他準備由執行者完成。

以下均是**授權後**的操作，非本輪執行紀錄。A 選定自有、無空格的絕對 root，先確認不存在／沒有他人資料；保持同一環境到撤回讀回。`CODEX_HOME` 只在專用終端／子程序設定，不寫 shell profile：

```sh
MRH_E18_ROOT=/absolute/owned-e18-root
MRH_E18_CLI=/Users/shawn/.nvm/versions/node/v20.19.4/lib/node_modules/@openai/codex/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex
MRH_E18_ENTRY=<E17R_BUNDLE_ABSOLUTE_PATH>/mrh
MRH_E18_WORK="$MRH_E18_ROOT/workspace"
MRH_E18_SETTINGS="$MRH_E18_ROOT/state/settings.json"
umask 077
mkdir -p "$MRH_E18_ROOT/home" "$MRH_E18_WORK"
export CODEX_HOME="$MRH_E18_ROOT/home"
"$MRH_E18_CLI" --no-daemon login status
# status 未登入才執行；不要把 status 的帳戶識別寫入公開證據。
"$MRH_E18_CLI" --no-daemon login
# 瀏覽器登入無法使用才選官方 --device-auth；不換憑證搬移途徑。
```

正式登入／mode status 尚未操作，帳戶對目標模型的可用性亦未知。本機 pin 為 `codex-cli 0.159.3`、binary SHA256 `4d210f7c5a18fd0386434df23b5bdbb8c0e7257d3e8a2b30b0769c8bbe99a878`。若已安裝檔更新，不更換或降級正式 Codex；報 A 決定這個先決條件。

A 在隔離 home 建立最小 config，parent 採本次已接受 native evidence 的 `gpt-6.1-sol / low`，只在這個新驗收 session 選定，不改既有主視窗。使用官方 OpenAI provider，無 custom URL、profile、default role、自訂 catalog、session／turn model-effort override。新 config 的必要 multi-agent/code-mode、Hook 與 speed 狀態須從 pin 的正式介面確認後，再 prepare；不能套用 fixture 的 loopback provider、`approval_policy=never` 或 auth bypass。本次以公開 Standard credit 向量作明示的模型配置比較基準；記錄實際 speed/provider 差異，不把向量當成實際帳單。

## 金鑰與實際外送內容

執行者先在使用者可見的專用終端準備所有命令；人類只在遮罩輸入提示輸入 TypeSafe key，不能貼在聊天或命令字面值。不要用 `printenv`、`env`、`set -x`、`curl -v`、HTTP header dump 或錄製輸入。

```sh
# zsh；在已完成準備、即將啟動 CLI 的同一專用終端。
unsetopt XTRACE
read -rs 'TYPESAFE_API_KEY?TypeSafe key（遮罩、不保存）: '
printf '\n'
export TYPESAFE_API_KEY
"$MRH_E18_CLI" --no-daemon --no-alt-screen -C "$MRH_E18_WORK"
unset TYPESAFE_API_KEY
```

Key 只進程環境持有，供真 Hook 的 `environment_credential()` 取得；不寫 settings／policy／證據檔，不讀出來驗證。缺 key 時保留原委派且記錄失敗。清理需終止持有 key 的 CLI／子程序及關閉專用終端；`unset` 不會清除仍活著的子程序環境。

`src/mrh/typesafe.py` 固定 HTTPS `POST https://api.typesafe.ai/v1/systemone`，Bearer header，不跟隨 redirect，沒有 SDK 重試。`typesafe_protocol.serialize_request` 固定 `model=jev-1.13.0`，`state.task` 是原委派文字；可選 `state.context_summary`，加 `questions.tier` choice、四級 rubric。目前 runtime 沒接入 context provider，這次不新增摘要來源；只使用下面的公開合成任務。沒有 repo、全對話、登入資料、DB 或 key 放進 body。官方 [API reference](https://docs.typesafe.ai/api) 與 [Models](https://docs.typesafe.ai/models) 支持端點、request shape、pin 及 usage。

## 現有 prepare／權限／外送／啟用介面

A 建立 `policy.json`（位置在 state 之外），內容見下一節；不是修改產品。所有這些命令在同一 export CODEX_HOME 的專用環境執行：

```sh
"$MRH_E18_ENTRY" plugin prepare --root "$MRH_E18_ROOT/plugin" --settings "$MRH_E18_SETTINGS" --scope-workspace "$MRH_E18_WORK" --codex-binary "$MRH_E18_CLI"
"$MRH_E18_ENTRY" plugin show --root "$MRH_E18_ROOT/plugin"
"$MRH_E18_ENTRY" settings show --path "$MRH_E18_SETTINGS"
"$MRH_E18_ENTRY" settings configure --path "$MRH_E18_SETTINGS" --provider typesafe --policy "$MRH_E18_ROOT/policy.json" --allow-workspace "$MRH_E18_WORK"
"$MRH_E18_CLI" --no-daemon plugin marketplace add "$MRH_E18_ROOT/plugin" --json
"$MRH_E18_CLI" --no-daemon plugin add model-routing-harness@model-routing-harness-local --json
"$MRH_E18_CLI" --no-daemon plugin list --json
```

先從 `plugin show` 核對 `inspected-configuration`、canonical home/workspace、pin／hash／mapping。prepare 仍是 disabled、export denied；`live_routing_ready` 並非真驗收結論。scope 拒絕就回 A，不修正式 config 或偷讀私有資料。

用 B 接受的 interactive argv 啟動，透過官方 `/hooks` review/trust **僅 MRH 這個 plugin 的當前定義**；不要改其他 Hook。完成 trust、沒有 task 外送前，再以既有設定介面明確開權限：

```sh
"$MRH_E18_ENTRY" settings configure --path "$MRH_E18_SETTINGS" --permit-task-export
"$MRH_E18_ENTRY" settings enable --path "$MRH_E18_SETTINGS"
"$MRH_E18_ENTRY" settings show --path "$MRH_E18_SETTINGS"
```

若 trust 變動會影響 prepare scope，先由同一 `plugin show` 重核；不能把失效 scope 當 live。工作區授權採 exact 自有 workspace；其子路徑也被 `workspace_allowed` 接受，故不要把個人資料放進該 root。不使用 legacy `mrh config --apply` 全域接法。

## 普通級價格資料與既有欄位

2026-10-11 讀取的官方 [Codex Pricing](https://developers.openai.com/codex/pricing) 已有 Standard credit rates。A 在 D40 選定這組公開向量作本次模型配置比較基準，**不是 API 美元價、包含用量的總帳單，或帳戶一定可用的證明**。三項每百萬 tokens 向量：GPT-6.1 Sol `50 / 2.5 / 250`、GPT-5.6 Luna `5 / 0.5 / 30`（input／cached input／output）。不需先購買 credits 或新增 API key 才能採用公開比較值。Fast／Ultrafast、其他 provider 與 included subscription multipliers 另有條件；實際差異要揭露，不能宣稱 Standard 向量已驗證實際帳单。

可以直接填 `policy.rates` 的既有 `currency/unit/service/source_ref/components`；`source_ref` 只能用 safe ID，URL 與日期留本文件，不加 schema。普通級 gate 是每項不高於 baseline 且至少一項低於，並非 token 總量預估。建議第一轮 Light/Small/Mid 都暫用同一便宜、已通過 native request 語法的 Luna/low，確保真 Jev 命中任一普通級都能驗改寫；不是宣稱三個級別的最佳產品預設。Top 維持 Main。

```json
{
  "top_mode": "Main",
  "timeout_seconds": 5,
  "tiers": {
    "Light": {"model": "gpt-5.6-luna", "effort": "low"},
    "Small": {"model": "gpt-5.6-luna", "effort": "low"},
    "Mid": {"model": "gpt-5.6-luna", "effort": "low"}
  },
  "rates": {
    "gpt-6.1-sol": {
      "currency": "credits", "unit": "per-million-tokens",
      "service": "codex-standard-credit", "source_ref": "openai-codex-pricing-2026-10-11",
      "components": {"input": 50, "cached_input": 2.5, "output": 250}
    },
    "gpt-5.6-luna": {
      "currency": "credits", "unit": "per-million-tokens",
      "service": "codex-standard-credit", "source_ref": "openai-codex-pricing-2026-10-11",
      "components": {"input": 5, "cached_input": 0.5, "output": 30}
    }
  }
}
```

5 秒是這輪建議 Jev deadline，在既有 `0 < timeout <= 30` 內，不是成功保證。`service=codex-standard-credit` 表示上述明示的配置比較基準，沒有宣稱使用者已購買 credits 或採該帳單服務。真用量／費用仍未知；若實測出現 speed/provider 差異，保留其觀察與比較限制，不更換數值冒充該服務價格。不能把 ordinary preserve 算普通改寫完成。

## 最小任務、證據與停點

建議最多 3 個 user turns：先一個普通任務、再一個有設計取捨的任務；第三個只給一次修正明確原因後的補驗。每個要求僅一個 generic child，model／effort 留 unspecified 或 null，不能使用 special role，也不能用「請判定 Top」操控 classifier。沒有 Goal、自動續跑、網頁／repo讀取、工具執行或檔案變更。

普通任務：`Delegate exactly one generic subtask, without specifying its model or reasoning effort: sort the literal numbers [3, 1, 2] ascending and return only the sorted array. Wait for that result and report it. If a hook returns the unexecuted subtask to you, do it here without delegating again. Do not use files, commands, web access, or other tasks.`

設計取捨任務：`Delegate exactly one generic subtask, without specifying its model or reasoning effort: design a tiny hypothetical two-service reservation protocol when network partitions can occur and payment confirmation may be delayed. Explain the conflict between avoiding duplicate reservations and maintaining availability, choose a tradeoff, and state one recovery rule. Limit the answer to 150 words. Wait for the result; if a hook returns this unexecuted subtask to you, complete it in this same parent without a replacement child. Use no real data, files, commands, or web access.`

以上只提高普通／Top 出現的可能，**不保證 tier 或 confidence**。真 Jev 不是受控 fixture；低信心、ordinary、Top 與失敗都如實記錄。第三輪仍未命中必要分支就保留未知，不改 Jev 回傳、不無限試題。

A 已在 D40 選定同一隔離官方 `app-server --listen stdio://` 收集公開 protocol stream，沿已有 Rpc／native evidence 的方法使用官方 `initialize` → `initialized` → `thread/start` → `turn/start`，不傳 model/effort/config override。這不是新產品 dispatcher。以下已從精確 pin 的公開 schema 核清讀回方法，不使用 TUI 文案、自報模型、MRH requested count 或私有 rollout 取代原生證據。

### D40 公開證據結論：thread/read 足以讀宿主有效設定

官方 [App server](https://developers.openai.com/codex/app-server) 的 `thread/read` 是唯讀讀回，沒有 resume、建立 turn 或改設定。精確 0.159.3 schema 的 `ThreadReadResponse.thread` 提供 `id`、`parentThreadId`、`modelProvider`、`model`、`reasoningEffort`、`status`。`model`／`reasoningEffort` 明定：thread 載入時是 **current configured**；未載入時是 latest persisted；可能為 null，**不是 per-turn execution telemetry**。因此可证明原生 child session 有效模型／effort與已完成結果，不要求攔 TLS 或證明 provider 内部 inference identity。

同一 Rpc 連線持續收事件，依序讀：

1. E19 的實際 V2 事件另以 `subAgentActivity.agentThreadId` 取得 child UUID，再用 `thread/read.parentThreadId` 確認 parent 關聯；這輪 legacy receiver 清單為空，不能視為沒有 child。以下 legacy 路徑僅在實際存在時使用。Parent 的 `item/completed.params.item.type=collabAgentToolCall` 且 `tool=spawnAgent`，取得 `senderThreadId`、`receiverThreadIds[]`、item `id` 與外層 `threadId`／`turnId`。`receiverThreadIds` 對應新建 child；item 自己的 `model`／`reasoningEffort` 明確是 **requested**，不可代替 child 讀回。
2. Child ID 出現後、尚未 close/shutdown 時，送下面 metadata read；對上 `result.thread.parentThreadId=原 parent ID`，child `model=gpt-5.6-luna`、`reasoningEffort=low`、`modelProvider=openai`。同時讀 parent，須仍為 Sol6.1/low。有 `thread/started` 事件也可取同一 Thread 欄位作早期快照；沒收到不能假定缺 child。
3. 收 child 的 `item/completed`（`item.type=agentMessage`，`text` 為結果），及 `turn/completed`（同 child `threadId`、`turn.id`、`turn.status=completed`）。完成後再 metadata read 核設定未變。`thread/settings/updated` 若出現，核對 `params.threadId` 與 `threadSettings.model/effort/modelProvider`；沒有這個事件不當作額外設定證明。未載入後的讀回標為 persisted，不標成 live configured；null 就保留未知。
4. Parent 的 `collabAgentToolCall` wait 結果提供 `agentsStates[childID].status/message`（message可為null），加 parent 最終 `agentMessage`／`turn/completed`，證明 native child 結果已接回同 parent。結果事件若漏收，可對**這次自有 child／parent**用 `includeTurns=true` 讀 `thread.turns[].items[]` 補讀；此值雖會從宿主歷史載入，但走官方公開 API，不直接讀私有檔案。schema 提醒 full-history hydration 對 paginated threads deprecated；若這次 read 無完整 items，保留缺口，不靠猜測補結果。

```json
{"id":101,"method":"thread/read","params":{"threadId":"<childID>","includeTurns":false}}
{"id":102,"method":"thread/read","params":{"threadId":"<parentID>","includeTurns":false}}
{"id":103,"method":"thread/read","params":{"threadId":"<childID>","includeTurns":true}}
```

Top Main 則對上 parent 原生 denied delegation/error item、MRH `top_main_requested`、沒有新的 receiver/child/thread-start、同 parent 後續實際 `agentMessage` 與 completed turn；parent metadata 前後仍為原模型／effort。不要只因少一個 child notification 就判 zero child，須核同 parent 整個 turn 的 delegate items／receivers；也不能把 denied tool item 的完成當作 parent 答案完成。全鏈沒有額外 `thread/resume`、`turn/start` 或模型覆寫讀回。

來源為未改官方 binary，SHA256 `4d210f7c5a18fd0386434df23b5bdbb8c0e7257d3e8a2b30b0769c8bbe99a878`，在 C 自有臨時 home 用 documented `codex --no-daemon app-server generate-json-schema --out <owned-scratch>/schema` 產生。查證檔案／SHA256：`v2/ThreadReadParams.json` `dfe040c6ac71d30795b8be3f3ff232e66f362a37f883b491e5d1ea367f470db4`；`v2/ThreadReadResponse.json` `3a0aaf9cff80796d07130b85723ca825f9203796d15c878f452083cf9f9a6f0a`（含 Thread、ThreadItem、CollabAgentState）；`v2/ThreadSettingsUpdatedNotification.json` `1decdf57238a1573ffbbf0bf695acba50888c1580e44670471dd88bfc2bd540f`。`ClientRequest.json` 列 `thread/read`，`ServerNotification.json` 列 `thread/settings/updated`。本輪只生成及讀 schema，沒有 server session／provider call；scratch 查證後移除，未把大 schema 帶入 repo。這是公開契約準備，不是已取得真 child runtime 證據。

每次以 MRH live stats 前後差及同一個 native parent/session/turn/tool reference 對上：

```sh
"$MRH_E18_ENTRY" stats --settings "$MRH_E18_SETTINGS" --json --details
```

stats 是彙總，沒有逐筆 confidence。若要逐筆對上，只讀這輪 MRH 自有 DB 的允許欄位；用 prepare/show 回傳的 `artifact.python` 作 `MRH_E18_PYTHON`，不讀 Codex 私有資料或 MRH keyed fingerprint／`.key`：

```sh
"$MRH_E18_PYTHON" -I -B - "$MRH_E18_ROOT/state/events.sqlite3" <<'PY'
import json, sqlite3, sys
from pathlib import Path
db = sqlite3.connect(Path(sys.argv[1]).as_uri() + '?mode=ro', uri=True)
db.row_factory = sqlite3.Row
query = """SELECT id, session_id, turn_id, tool_call_id, state,
json_extract(decision,'$.action') AS action,
json_extract(decision,'$.reason') AS reason,
json_extract(decision,'$.tier') AS tier,
json_extract(decision,'$.confidence') AS confidence,
json_extract(decision,'$.patch.model') AS requested_model,
json_extract(decision,'$.patch.reasoning_effort') AS requested_effort
FROM proposals WHERE synthetic=0 ORDER BY occurred_at"""
print(json.dumps([dict(row) for row in db.execute(query)], ensure_ascii=False))
db.close()
PY
```

必要證據分開判定：

1. **真 Jev**：live partition、`jev_attempts` 增加、`actual_provider_transport`、returned `jev-1.13.0`、實際 tier/confidence 判定與 usage（若 provider 未給則未知）。保留 error/timeout；不記 raw header/body/key。
2. **普通改寫及原生結果**：同一 native generic proposal、MRH routed reason/target；依 D40 上述 `thread/read` 核原生 child configured model/effort、parent關聯，再對 child完成與parent收到結果。PostToolUse 在 `src/mrh/codex.py` 只產生 reported child，不能單独證明有效 model。真 runtime 若欄位為null／只有persisted／缺結果，就精確記錄該缺口；正常取得有效session設定與原生結果即滿足這輪證據方案。Provider-confirmed inference identity仍未取得，不把它包進此主張，也不攔截 Authorization、TLS 或加 proxy。
3. **Top Main**：只有真 Top 且 confidence >= 0.5 才評這項。native deny reason 指回同 parent，未建立 child；同一 parent 在 deny 後產生實際答案，模型設定仍為原 parent，沒有 replacement spawn。`parent received`、`zero child`、`parent completed` 各有對應事件；缺任一项不算 Main 自主完成。命中其他級別則此項未覆蓋。

建議操作上限為 3 個 eligible Jev proposals、最多 3 children、3 個 user turns，每 turn 最長觀察 120 秒；遇到額外委派、provider失敗、scope失效、停止政策或不足額度立即原生 interrupt 並停用。這是執行者監看停點，**不是產品已有硬性外送次數／美元上限**；提示詞不能保證模型不多呼叫一次。Jev 本身單 proposal 無自動重試；Codex provider streaming/request 次數、reasoning tokens 無法從三個 user turns 給硬上限。A 必須在付費前確認這個限制；要求硬貨幣上限但 provider 沒有適用控制時，就保持未授權，不新增成本框架。

官方 Jev 價為 $0.042／1M input tokens，output 免費。若每次約 2,000 input、3 次，條件估計 $0.000252；沒有真 usage 不能稱實際花費。3 次各達官方 64k token request 上限的條件量級為 $0.008064，不涵蓋超出操作上限的呼叫。Codex 以實際 token、speed、帳戶計價為準，總額目前不可估；例：Standard parent 每次 20k input＋2k output 為 1.5 credits，Luna 同量為 0.16 credits，3 組為 4.98 credits，這只是公式示例，不是 token 預測／費用保證。沿用現有 usage／stats，不建新費用系統。

## 同一環境停用、撤回與讀回

```sh
"$MRH_E18_ENTRY" settings disable --path "$MRH_E18_SETTINGS"
"$MRH_E18_ENTRY" settings configure --path "$MRH_E18_SETTINGS" --deny-task-export --clear-workspaces
"$MRH_E18_ENTRY" settings show --path "$MRH_E18_SETTINGS"
"$MRH_E18_CLI" --no-daemon plugin remove model-routing-harness@model-routing-harness-local --json
"$MRH_E18_CLI" --no-daemon plugin marketplace remove model-routing-harness-local --json
"$MRH_E18_CLI" --no-daemon plugin list --json
"$MRH_E18_CLI" --no-daemon plugin marketplace list --json
unset TYPESAFE_API_KEY
```

先 interrupt／結束 active paid turns，再 disable；已開始 invocation 仍可能到 deadline。官方 `/hooks` 讀回 MRH 不再註冊、同 home 的 settings disabled/export denied/workspace empty，統計 live 計數無新增；不為 readback 再發付費 task。保留去敏證據及 MRH history，不用舊整份 config snapshot 覆蓋後續變更。只在這個隔離 home 使用 `codex logout` 清理其新 file-based login，先確認 store 不會牽連正式登入；store 未確認則保留待 A 裁決，不碰 shared keychain。停止全部自有程序後清理本輪確定 owned、非交付檔的 scratch，原始正式 home 不清理。只回報 binary hash 與 MRH settings 等允許來源，不讀登入秘密。

## A 可一次向使用者提出的問題

> 建議用現有官方 Codex CLI，在新的隔離 home／空白工作區驗收，保留你原本的 App、登入與 Hook。是否同意我們在這個隔離環境完成官方登入、僅安裝／信任／啟用 MRH，讓最多 3 個上述公開子任務送往 TypeSafe 並由你的 Codex 帳戶執行真模型，遇到額外委派或失敗就停，完成後停用及撤回？你只需在我們準備好的遮罩終端輸入 TypeSafe key，必要時完成官方登入／MFA，不需把 key 貼給我。Jev 3 次的條件最高量級約 US$0.0081；Codex 會消耗你帳戶用量，token／金額沒有現成硬上限，不能承諾固定費用。請一併確認你接受這個受次數與時間監看的用量範圍，並有可用的 TypeSafe key；若需硬金額上限，我們先停在此，不自行加購或擴建。

提問前 A 須先接受 E17R 修正版並整合上述公開證據方案；Standard credit 向量已依 D40 選為配置比較基準，不再要求購買 credits 或證明最終帳單。若仍有具體差異，把差異加入同一次問題，不讓人類代跑我們能操作的命令。這輪不涵蓋正式 home 長期啟用、Top Fixed／Goal 全 R1 覆蓋、其他平台或發布。

## 來源範圍

本文件依 D39/D38/D37、REQUIREMENTS §四／八，以及 `src/mrh/{cli,settings,settings_schema,codex_scope,codex_defaults,core,typesafe,typesafe_protocol,runtime,codex,store}.py`、`docs/e17-scoped-hook.md`、既有 `scripts/verify_scoped_host.py` native evidence 方法查證。只執行官方 login／marketplace remove 的 `--help`（無登入／provider action），並讀官方 Authentication、Pricing、App server、TypeSafe Models/API 頁。準備文件沒有替 B 執行測試，也沒有把進行中的 E17R dirty bytes 視為最終 bundle。
