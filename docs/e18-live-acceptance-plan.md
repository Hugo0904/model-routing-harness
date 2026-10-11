# E18-C-001：真 Jev／真模型驗收準備

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

A 在隔離 home 建立最小 config，parent 採本次已接受 native evidence 的 `gpt-6.1-sol / low`，只在這個新驗收 session 選定，不改既有主視窗。使用官方 OpenAI provider，無 custom URL、profile、default role、自訂 catalog、session／turn model-effort override。新 config 的必要 multi-agent/code-mode、Hook 與 Standard speed 狀態須從 pin 的正式介面確認後，再 prepare；不能套用 fixture 的 loopback provider、`approval_policy=never` 或 auth bypass。未證明 Standard 計價適用時，普通級成本前提保留未知。

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

2026-10-11 讀取的官方 [Codex Pricing](https://developers.openai.com/codex/pricing) 已有 Standard credit rates。這是 credit 計價配置比較，**不是 API 美元價、包含用量的總帳單，或帳戶一定可用的證明**。相同 Standard 計價服務下，三項每百萬 tokens 向量：GPT-6.1 Sol `50 / 2.5 / 250`、GPT-5.6 Luna `5 / 0.5 / 30`（input／cached input／output）。Fast／Ultrafast 與 included subscription multipliers 另有條件；本次不把不同 speed／服務的單價混成同一比較。

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

5 秒是這輪建議 Jev deadline，在既有 `0 < timeout <= 30` 內，不是成功保證。若真帳戶是 API 或無法確認上列 credit 比較適用，不填不相符 rates；具體缺口是「該實際服務與 speed 的 baseline／target 三項一致單價」，由 A 決定是否先只驗 Main。不能把 ordinary preserve 算普通改寫完成。

## 最小任務、證據與停點

建議最多 3 個 user turns：先一個普通任務、再一個有設計取捨的任務；第三個只給一次修正明確原因後的補驗。每個要求僅一個 generic child，model／effort 留 unspecified 或 null，不能使用 special role，也不能用「請判定 Top」操控 classifier。沒有 Goal、自動續跑、網頁／repo讀取、工具執行或檔案變更。

普通任務：`Delegate exactly one generic subtask, without specifying its model or reasoning effort: sort the literal numbers [3, 1, 2] ascending and return only the sorted array. Wait for that result and report it. If a hook returns the unexecuted subtask to you, do it here without delegating again. Do not use files, commands, web access, or other tasks.`

設計取捨任務：`Delegate exactly one generic subtask, without specifying its model or reasoning effort: design a tiny hypothetical two-service reservation protocol when network partitions can occur and payment confirmation may be delayed. Explain the conflict between avoiding duplicate reservations and maintaining availability, choose a tradeoff, and state one recovery rule. Limit the answer to 150 words. Wait for the result; if a hook returns this unexecuted subtask to you, complete it in this same parent without a replacement child. Use no real data, files, commands, or web access.`

以上只提高普通／Top 出現的可能，**不保證 tier 或 confidence**。真 Jev 不是受控 fixture；低信心、ordinary、Top 與失敗都如實記錄。第三輪仍未命中必要分支就保留未知，不改 Jev 回傳、不無限試題。

推薦 A 選擇同一隔離官方 `app-server --listen stdio://` 收集公開 protocol stream，沿已有 Rpc／native evidence 的方法使用官方 `initialize` → `initialized` → `thread/start` → `turn/start`，不傳 model/effort/config override。這不是新產品 dispatcher；若 A 先用 TUI，依官方 agent／status 畫面讀回。不要以 TUI 文案、自報模型或 MRH requested count 取代原生證據。官方 [App server](https://developers.openai.com/codex/app-server) 支持 thread/read 與 item/turn notifications；pin 的精確回應欄位仍須由執行者核 public schema，不從私有 rollout 取得。

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
2. **普通改寫及原生結果**：同一 native generic proposal、MRH routed reason/target；原生 delegate item、子 thread/reference、子完成 result，父收到該 result。原生 scope/config/readback 若提供模型／effort，就記該來源。PostToolUse 在 `src/mrh/codex.py` 只產生 reported child，不能單独證明實際 model。既有 E17 的 upstream request capture 是 scripted provider；真實 OpenAI 這輪不得攔截 Authorization、TLS 或加 proxy。若 pin 的公開介面不能提供 child effective model/effort 或 provider-confirmed model，精確標示「原生 child 完成、requested target 已記錄；實際模型仍未驗證」，回 A 決定可接受證據，不冒充完成。
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

提問前 A 須先接受 E17R 修正版、決定公開模型證據是否足夠，以及確認 credit-rate applicability。若仍有具體差異，把差異加入同一次問題，不讓人類代跑我們能操作的命令。這輪不涵蓋正式 home 長期啟用、Top Fixed／Goal 全 R1 覆蓋、其他平台或發布。

## 來源範圍

本文件依 D39/D38/D37、REQUIREMENTS §四／八，以及 `src/mrh/{cli,settings,settings_schema,codex_scope,codex_defaults,core,typesafe,typesafe_protocol,runtime,codex,store}.py`、`docs/e17-scoped-hook.md`、既有 `scripts/verify_scoped_host.py` native evidence 方法查證。只執行官方 login／marketplace remove 的 `--help`（無登入／provider action），並讀官方 Authentication、Pricing、App server、TypeSafe Models/API 頁。準備文件沒有替 B 執行測試，也沒有把進行中的 E17R dirty bytes 視為最終 bundle。
