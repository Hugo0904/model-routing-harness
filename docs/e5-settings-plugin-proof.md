# E5：自有 plugin 與公開設定

0.2.0 已提供 MRH 自有 bundle、公開 settings CLI 與既有 TypeSafe factory 的共同入口；兩版 stable native CLI 的隔離安裝、信任、入口執行與移除已通過。正式 host resolver 缺少必要契約，維持保留原呼叫；完整 R1 尚未完成。本包待 A 驗收，沒有正式啟用或真 API 證據。

## 準備、註冊與停用

先在選定的 venv 離線安裝本套件。Bundle root 必須是 canonical absolute、fresh 或可驗證的 MRH 自有目錄；既有未知內容、symlink、其他 UID 或 group/other 可寫目錄均拒絕。State 必須在 bundle 之外，parent 已存在。以下是操作指南，沒有對使用者正式環境執行：

```sh
mrh plugin prepare --root /absolute/mrh-bundle --settings /absolute/mrh-state/settings.json
mrh plugin show --root /absolute/mrh-bundle
codex plugin marketplace add /absolute/mrh-bundle --json
codex plugin add model-routing-harness@model-routing-harness-local --json
codex plugin list --json
```

Prepare 只建立 MRH 的 `.agents/plugins/marketplace.json`、`plugins/model-routing-harness/plugin.json`、hooks、launcher、獨立 stdlib `runtime.pyz` 與 binding／hash ledger。Python3.11+ 使用明確解析的已安裝 interpreter，以 `-I` 執行 archive；不靠 repo cwd、PYTHONPATH 或下載依賴。Native commands 的結果與 `/hooks` 目前定義的 review／trust 是另外的步驟。產品 show 保持 registration/trust unverified，不把準備成功當成安裝成功。

格式依官方 [Plugin packaging](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually)；原生 CLI 路徑與一般信任流程依 [Developer commands](https://learn.chatgpt.com/docs/developer-commands)、[Hooks](https://learn.chatgpt.com/docs/hooks)。不使用開發中的 plugin RPC，也不直接寫／恢復共享 hooks.json／config／marketplace snapshot。

```sh
mrh settings init --path /absolute/mrh-state/settings.json
mrh settings show --path /absolute/mrh-state/settings.json
mrh settings configure --path /absolute/mrh-state/settings.json --provider typesafe --policy /absolute/policy.json --allow-workspace /absolute/allowed-workspace --permit-task-export
mrh settings enable --path /absolute/mrh-state/settings.json
mrh settings disable --path /absolute/mrh-state/settings.json
codex plugin remove model-routing-harness@model-routing-harness-local --json
```

Init 不覆寫；configure 不改 enabled，enable 不授予 export 或 workspace。`--deny-task-export`／`--clear-workspaces` 分別撤回其 gate；workspace 清單是 explicit configure 指定的完整清單。更新可帶 `--expected-revision`，stale revision 回 `settings_conflict`；腐損與權限錯誤回固定 reason，不 echo 私人內容。[schema1 範例](../examples/settings-disabled.json) 預設 enabled/export 都 false、workspace 空；key 不入 JSON，provider／model／環境變數固定，不接受任意 URL。

Installed launcher 只用 binding 中的明確 absolute settings path。Hook 的 tool_input 或 task 不可授予外送權限，也不從其 cwd 尋找設定。兩個 gate、host cwd 的 canonical workspace 範圍與已解析 host context 都成立，才經既有真 `classifier_from_config` 建立 `TypesafeClassifier`；fixed `TYPESAFE_API_KEY` resolver 只在真正 classify 時使用。Show／doctor 不讀 key、不送分類。

Disable 使後續 invocation neutral，零 classifier／key／transport；已 admission 的舊 invocation 可用 captured settings/deadline 完成，沒有遠端或跨程序取消保證，也不會重新啟用。Native uninstall 只移除 plugin，separate settings／telemetry 保留；產品不隱含刪除資料。升級只替換已驗證的 own artifact，保留設定與權限；locks 僅串行 cooperating MRH writers，不宣稱保護非合作編輯器的 CAS。

## 真正缺少的 host 契約

官方 [Hook common fields](https://learn.chatgpt.com/docs/hooks#common-input-fields) 有 cwd／model，但沒有足夠資料證明 active turn effort、role/default model precedence、該次委派原 model/effort/cost baseline。Transcript 不穩定；[App Server config/model/turn](https://learn.chatgpt.com/docs/app-server#start-a-turn) 的另一程序 disk config、model/list／new-thread defaults 也不能證明這個 active invocation 的 override。沒有抓私人 state/transcript、推測 effort、拿公開 catalog 當帳戶 availability 或接受 user JSON 的 available=True。

`SupportedHostResolver` 是獨立 dependency，正式實作回 configuration unknown，保留原呼叫且不 resolve key／transport。需要宿主在同 invocation 的受支持介面正面提供上述有效值，才能完成 live readiness；不是設定或 policy 可以自行補出的事實。這是本次精確接口缺口，未改寫架構或加入 daemon／assume-known 開關。

## 兩版實際隔離證據

| Surface | Native lifecycle／11 情境 | 含準備與最終清理的 fixture 實耗 |
|---|---|---:|
| Shell CLI0.159.3 | 通過 | 9.768 秒 |
| Desktop 隨附 CLI0.162.0-alpha.17.2 | 通過 | 8.981 秒 |

原始 [Shell JSON](evidence/e5-shell-plugin.json)、[bundled JSON](evidence/e5-bundled-plugin.json) 含每個 native command/exit/readback、Hook trust/hash、turn/call/receipt IDs、父模型／effort 設定與 provider 請求。Native cache version 回 `local`，manifest 回 `0.2.0`；兩版實際 installed runtime SHA256 都是 `ee7917718ba4a547aaebf62b5635487d1b4690cca00800373d0684041df6913d`，不能只拿 repo SHA 當安裝 identity。

每版各一個 fresh HOME／CODEX_HOME／workspace，環境 allowlist 不轉送 credentials，沒有 auth file 複製。Loopback provider 無 Authorization，只做腳本 Responses，公開 release catalog 的精確 hash 與 native-v1 overrides 沿用 E4。沒有真 OpenAI／Jev、Desktop UI、預設 v2/code-mode 或智能自主完成證據。

情境涵蓋 native registration、add/list/重複 add 只有兩個 MRH Hook、信任前兩份 MRH 定義 untrusted 且不執行、官方 review 後三個 Hook trusted、**未修改的 installed launcher** 在 disabled 模式實際完成 Pre/Post、configured-disabled、enabled Main/Fixed、explicit skip、HTTP failure、第三方 co-deny、competing rewrite、disabled-again、第三方後續更新、native remove/list 無 installed plugin。產品自身沒有改 shared hooks.json；初始 bytes 在 install／disable 後相同，獨立 fixture writer 的後續 revision2 仍執行，remove 後也保留新 bytes與 separate state。

Enabled 案例使用**本次 test-only process bootstrap**：改隔離 cached plugin 的 own Hook definition，經另一輪官方 trust，從實際 installed runtime archive 載入相同 public CLI／settings reader／真 Typesafe factory，只在 code dependency 注入 synthetic host context 與 synthetic HTTP transport、dummy key。沒有替換 classifier，也沒有啟用真 API。這證明設定接線與 installed entry 行為，不能當成正式 host resolution。Unmodified launcher 的證據另外保留，沒有把 bootstrap 稱為 production launcher。

Fixed 的 native rewritten PostToolUse input 帶 model，收據仍以原 turn/call ID 關聯；每版 synthetic attempts5、synthetic child receipts3，live attempts／confirmed children 均0。第三方 deny 與 MRH Fixed updatedInput 同 call 被觀察到時，native child/request 都0。Competing rewrite 在本次兩版 fixture 採用 MRH fixed 型號；這是不受支持的競爭情境觀察，沒有 ordering guarantee。安裝時可從 native `/hooks`／hooks/list 看到多份定義；單次 MRH Hook input 沒有其他 Hook 的輸出，不能宣稱一般 per-call 衝突偵測。

## 聚焦檢查、修正與限制

34 項 schema／own IO／public CLI-factory／owned bundle／直接 CLI consumer checks 全通過，runner0.433秒、命令實耗0.540秒：[輸出](evidence/e5-tests.txt)、[計時](evidence/e5-test-run.json)。包括 gate 組合、out-of-scope／task 自報 permission 不授權、true serializer/parser、missing key／malformed config／transport failure、explicit／fixed-role skip、body/key 不持久化、stale revision/concurrent writers、inflight disable 邊界、非自有／symlink／wrong UID 零寫入、超限輸出保留原設定、repeat/update 保留 permissions。

獨立 risk reviewer 找到並覆核修正三項反例：設定序列化超過64KiB須在替換前拒絕；wrong UID空目錄須在marker寫入前拒絕；rewritten Post input不可被explicit Pre gate略過。原生 fixture 的兩次初期 diagnostic 分別是改過 display_name 的 UI 完成判斷不符（10.017秒）和錯把 pluginId 當 run.id（5.424秒），均清理；證據保留且未算 PASS。最後依實際 sourcePath 關聯 run，沒有 trust bypass 或產品權限修正。

每個準備／native subprocess 有30秒上限；TypeSafe 沿用原 deadline/timeout、零 retry。上述 fixture 計時含 offline package preparation、操作及清理；外層命令 wall／各 subprocess breakdown 未另量測，不捏造。沿用 E3/E4/E4G 未受影響的 core/provider/Goal evidence，未重跑全 suite、真 API 或 Goal。結果／review／cleanup總表見 [E5 verification](evidence/e5-verification.json)。
