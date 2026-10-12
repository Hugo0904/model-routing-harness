# Desktop 接入契約：D68 結果與保留來源證據

**目前結果（D68-C-001）：原定 accepting adapter 的來源不變量不成立。** 已定位這個 bundled backend 正常啟動就會掛載、建立新 session 時會合併的 enterprise-managed cloud config。它可帶子代理預設與 default role，超出 D68 的本機 config／role 檔案守衛，且 native Hook 不提供該 session 的雲端 layer／binding。依 D68 的實質停止條件返回這個可達設定來源；沒有製作全 skip adapter，也沒有將 CLI 契約放寬。詳見文末 D68 與 `evidence/d68-desktop-source-boundary.json`。

D66／D67 是已由 A 接受的歷史來源單元。D67 outbound 仍是未送達；A 在 D68 直接讀取本地成果，不要求重送舊報告。下方保留各階段當時的證據與限制。

## D66：已安裝 Desktop 的建立請求來源

D67 的立即 caller 查證已追加於文末：找到真實 `pta` constructor、封閉的 extension-host request，以及另一條實際 fresh-local `mcp_app_follow_up` producer。它的 caller context 尚未在這次範圍證明受 key schema 限制；依 A 的停止條件返回這個具體邊界，沒有把 D66 的假設物件升格成實際輸入。

已定位實際 Desktop 的 conversation 建立／RPC 組裝鏈，證實它會在磁碟設定之外送入 request config。**尚未證明普通 fresh local UI 的所有 caller `configOverrides` 都不含 child-default／default-role／profile 覆寫**；process ancestry 加 SessionStart 的 lifecycle 身分不能替代這項資料。這不是重述泛用 app-server schema，也不是實際 App 接通證據。本輪不修改或啟用路由。

## 來源身分與查證方法

實際程式是 `/Applications/ChatGPT.app`（不是不存在的 `/Applications/Codex.app`），bundle ID `com.openai.codex`，版本 `26.1007.30912`／build `20156`。`package.json` 名称 `openai-codex-electron`，main 為 `.vite/build/early-bootstrap.js`。`webview/index.html` 載入 `assets/index-44a69cb8b3cd.js`，該入口再載入 app-shared／app-main／app-initial。

只用 Python 讀已安裝 `app.asar` 的 header 與指定程式 entry，搜尋 symbol 並讀限定片段；沒有執行其中 JavaScript、抽出整包、dump minified 整行、啟動程序或操作 UI。下列 offset 為 UTF-8 解碼後的 **character offset**，不冒充原始 TypeScript 行號。這兩個 frontend entry 宣告的 source maps 未包含在 installed asar，故沒有可引用的 original TS source／型別位置。

| 已安裝程式資源 | SHA256 |
|---|---|
| `Contents/Resources/app.asar` | `75e397e2280dde93b70a85aa926f4282c728eacc84dfeb15ba7fb6ddd84628af` |
| asar `.vite/build/main-CqEoQDOU.js` | `09d19386e1f23cf4ccbc950fc40d85a1e8a064a08be588b2a4be6a89f6ada9e6` |
| asar `webview/assets/app-shared-8bd9d0399038.js` | `607ad0866dd25ed3764711b4467a9b60708353a599485b5249ff4cbe0e870245` |
| asar `webview/assets/app-initial-6350d04672d0.js` | `604b5d2de4fbb41f3d0dc5b3662129c558e1c7b8aac8cc87225286f58dcfaf8f` |
| asar `.vite/build/src-BJv5Mk7n.js`（connection） | `72e2b366d574206f76fc079c79b64c31ce378970a797475ded8709908d338f08` |
| `Contents/Resources/codex-cli/bin/codex` | `50ab38ba21d0d9f8346f32f41848382f15b556190f3c7a07e885a4fb73e379c8` |

binary 只讀 hash，沒有執行 version／server／login。App plist 與 package version 相符；沒有從版本名推論已運行的 backend 設定。

## 已證實的建立鏈與輸入

| 實際 symbol／bounded span | 可證明的來源與效果 |
|---|---|
| initial `GGi`，`4914300–4916200` | 建立輸入 mapper 從 caller 解構 `configOverrides:c`，其 output 明確為 `config:c`。同時帶 cwd、workspace roots、collaborationMode、serviceTier、permissions、threadSource、threadStartKind。它沒有排除 agent/default/profile keys。這是實際 frontend mapper，不能把它的 caller 物件當磁碟設定。 |
| initial `HGi`，`4910583–4912100` | local conversation 發起器使用 `mode/threadStartKind` default 分支，移除一個動態工具 feature key後仍傳剩餘 `n.config`；呼叫 `jg(scope,host).startConversation`，以 `TGi(...).readCreationInputs` 供 inputs。它也被 voice／worktree 等來源使用；本輪沒有證明所有普通新聊天必經同一唯一 UI caller。 |
| shared `Xdn`，`3098114–3100700` | request assembler 取 `config:v`，先建立 request，再做 `O.config={...O.config,...v}`，另加入 memory settings 與 explicit `model_reasoning_effort`。local/default、非 browser/durable 路徑最後回 method `thread/start`；durable／Aeon 有不同方法／過濾分支，不能一起接受。 |
| shared `Qdn.buildNewConversationParams/buildThreadCodexConfig`，`3100800–3102820` | selected parent model/service tier/cwd、permissions／approval、personality、feature inputs與instructions交給 `Hin`。local 才使用 `configuration.readCodexConfig(cwd)`；不能從這點推論 child 繼承值，parent selection與child-default是不同輸入。 |
| shared `Hin`，`2896880–2899300`；`wDt`，`1942569–1943420` | `configRequirements/read`＋permission selection；`fetchCodexConfig` 回傳 keys 被複製進 config。之後 feature overrides、shell-environment policy、dynamic tools／developer instructions各有組裝步驟。default feature的 `Pwt/Iwt`（`1910206–1911920`）作版本相容與 `features.*` merge，沒有替 caller config 作 child-default whitelist。 |
| shared `fzn.readCodexConfig`，`3654380–3654680` | local callback 呼叫 Desktop bridge 的 `mcp-codex-config`，傳 cwd，拿 response.config。不是直接把整份使用者 config讀進renderer。 |
| main `mcp-codex-config` handler，`1423066–1423170`；`buildMcpCodexConfig`，`1431935–1432820` | 實際 native Desktop handler 合併 `_c`（browser/computer-use MCP）、`Xc`（Codex App tools MCP）、`y_e`（artifact template skills）、`da`（artifact session MCP）。來源包含 host connection、App feature availability、packaged resources、plugin/skills metadata。此查證只讀建構程式，沒有呼叫 bridge 或讀任何真設定值。 |
| shared `Grn`，`2876369–2877080`；`wV`，`2869630–2869950` | local search-MCP normalization 與 Pages工具停用。`Grn` 遇 `config.profile!=null` 就跳過該 normalization；`wV` 保留其他 config keys。實際 producer 因此認得 profile overlay，不能因 base request 沒有 top-level profile 就推論沒有 profile作用。 |

這條鏈已明確區分磁碟／requirements來源、Desktop MCP補丁、selected parent/permissions、caller額外 config。未在上述 builders看到直接構造 `agents.default_subagent_model` 或 default-role 的 literal，**不等於整個普通 UI 的 caller payload已受限制**。真正尚缺的是普通 fresh local UI `configOverrides` 的完整生成／過濾契約，以及它與當次 Hook session 的可核對關係；不是再問 backend接受哪些鍵。

### 一個具體的來源級反例

若 mapper 的建立輸入帶 `configOverrides={"agents.default_subagent_model":"gpt-6-astra"}`，`GGi` 會把該 object 放進 `config`；`HGi` 只移除指定 feature key，`Xdn` local 分支再以 spread 合併，`wV` 不刪該 key。故「Desktop的 request只等於 inspected disk＋固定MCP補丁」不是這條來源鏈的無條件不變量。帶 profile 的同類輸入還會使 `Grn` 提早保留 config。

這是讀來源得到的 **條件式 propagation 反例**，沒有送出該請求，也沒有觀察到本機 UI 實際帶這個值；它不證明現在的普通聊天確實改了child模型。反過來也不能把未讀的caller狀態默認為空。

## 同聊天後續設定、refresh 與 producer 身分

- shared 的 follow-up／resume preparation（`2903800–2904900`）仍可呼叫同一 `readCodexConfig(cwd)`／`Hin` 組裝；turn dispatch（`3051291–3052800`）送 `F.request` 至 `turn/start`。已找到 model/effort／collaboration等parent設定路徑，沒有在本輪證明所有 `F.request` 與 caller override的 keys全集，因此不宣稱「後續一定不能改 child defaults/role」。既有 D65 backend refresh 證據可沿用其原版本與範圍，但不能只用它代表這份 Desktop frontend全部producer。
- shared 的 thread-settings path（`3083200–3084020`）送 `thread/settings/update {threadId,...t}`；main daybreak/model choice path（`1068380–1068670`）則明確送 model／effort，並可能 `config/batchWrite`、清除 prewarm。parent model更新與可見diskwrite可以另核；generic `...t` caller未證明全集，不能由一個model-selector例子排除所有設定來源。
- main `_fe.createRequest/send`（`732500–734980`）對 start／resume／fork／turn 都使用同一 connection；connection chunk有 local `stdio`與其他transport分支。這支持以已安裝resource/binary pin區分軟體來源，**不支持以祖先程序判定這一次一定來自某個ordinary UI builder**。本輪沒有讀實際PID/argv、重啟程序或假設所有 local都用一個已核stdiospawn方式。
- 可具體看到另一個Desktop producer：initial `1396600–1397300` 的 MCP extension host直接送 `thread/start`，`ephemeral:true`、`threadSource:"mcp_extension_host"`，使用同類 `jg(scope,host)` request client。即使 App祖先相同，也不是一般聊天。resume／child／remote另有來源／transport，但本輪未證明 SessionStart會公開 builder身份或上述 caller config；不能把 lifecycle `startup`單獨升格成 ordinary-producer證明。此處沒有重做 D56 泛用 backend schema盤點。

## 給 A 的最小接續決定

可沿用：已安裝版本與資源pin、local/default相對durable／remote分支、這組真正 request assembler、同connection其他producer的反例。暫時不能沿用的斷言是「凡Desktop祖先＋fresh startup就可推定沒有hidden child-role/default/profile override」。

A 的單一決策是：如何取得／約束 **普通 fresh local UI 的 caller override全集與當次producer關係**，再據此定 finite Desktop contract；若現有官方可見資料尚不足，就保留這一個精確缺口，不把 CLI 契約直接放寬給所有 App-server clients。這份文件沒有提出替代dispatcher、private reader或新的路由架構，也沒有撤銷 App 原義務。其他 fresh-root CLI 的B施工／驗收不因這份來源報告重跑或等待。

## 本輪操作邊界

C exact turn `01a12eb5-2376-7340-bc92-6874a4be20a7` 經 metadata-only helper核為 `gpt-6.1-sol/high`；人類 A user `01a12eb0-610c-7760-b065-f1469ad3d1ad` 已由 supported read_thread核實，原 A/C 分線授權沿用。唯一寫入為本文件。未讀私人session/DB/記憶/認證或個人config，未呼叫私有API／攔 traffic／注入debugger，未launch/restart/UI/login/model/install，無tests/build/newGoal/subagent。B/A的dirty edits、E20/profile/dist與 `/` allowlist不改。

Monitor context仍缺current native user／task，check可讀但pending selection回 `current_host_turn_unavailable`；不捏造ledger身分／接受。這是來源檢視與精確待決事項交付，**不是實際App使用驗收**。

## D67：立即 caller 的實際構造與停止點

沿同一 installed source 的 mapper aliases 做直接 caller 查找，不重讀 D66 assembler／泛用 backend schema。`app-initial` export 明確將 `pta → Hvt`、`GGi → QOt`、`HGi → nkt`；直接 importer 為 asar `webview/assets/new-thread-a920912d4148.js`（SHA256 `15fdb588ff6481eddc910c32098313b823a27105ed4501b48af634d5cd4922bb`，5,094 characters）。本次只為這些 alias查 import header，不建立整個 App graph。

| 實際 constructor／caller | 確定 keys、spread 與 validation |
|---|---|
| initial `pta`，`5252912–5256720` | 真的建立 `configOverrides`：局部 `k`只明寫 `model_reasoning_effort`、一個 `gTe` feature marker、`features.auth_elicitation`、`features.tool_suggest`、`tool_suggest.discoverables`，work-permissions分支另寫 `web_search`。`config/read`結果轉為 `O=hm(E)`，輸出在另一個 `config:O` 欄位，不能混成 `configOverrides`。 |
| 同 `pta`，`5256536–5256660` | 若 `context.firstTurnConfigOverrides`存在，真正 return 是 `{...t.firstTurnConfigOverrides,...k}`。局部確定keys覆蓋同名keys，**沒有排除其他keys的局部 validator**；這是實際constructor的輸入邊界，仍須核 caller的context來源，不假設它必然可包含任意key。 |
| initial `fso/hso`，`6545902–6547620` | 既有 `create_thread` worktree路徑 `lso → fso → hso` 的 `configOverrides`來源有封閉helper：`hso(model,thinking)`僅在model為null且thinking非null時回 `{model_reasoning_effort:thinking}`，其他情況為null。沒有caller config map直接spread到這個欄位；`mso`的model/effort則在collaborationMode。保留上游schema／input是否合法的界限，不將此範圍擴成全部新聊天。 |
| initial `UC` extension host，`1396600–1397300` | startup傳入固定 literal `{ephemeral:true, permissions:':read-only', threadSource:'mcp_extension_host'}`，options只有timeout。**沒有 config／profile／child-default／default-role request欄位，也沒有caller object spread。** 此producer輸入構造閉合；其disk/backend角色仍屬原宿主檢查，不由此literal推論。 |

### 新出現的實際 fresh-local producer

`new-thread-a920912d4148.js` 的 `Z(scope,{context:t,destination:n,...})` 在 `destination.hostId='local'` 有實際 Codex建立分支（`1081–2980`）。它將 **caller的 `context:t` 原樣交給 `j=pta`**，並指定 `agentMode:'auto'`、`shouldSendPermissionOverrides:false`、`collaborationMode:null`、projectless workspace。之後（約 `3950–4700`）實際呼叫 `V=HGi`，輸入含 `...P(L)`（`P=GGi`），明定 `threadSource:'mcp_app_follow_up'`、`turnTrigger:'mcp_app_new_thread'`。

此5,094-character caller裡的檢查是account／abort、user-gesture／response-items、workspace與image-model支援，**没有對 `context.firstTurnConfigOverrides`作 `parse`／`safeParse`或key whitelist**。但上游caller可能另有validation；本單元沒有證明那個schema，不將「本函式沒驗」說成「全鏈允許惡意keys」，也沒有觀察到真值。這是從已定位aliases找到的、另一個真實 fresh-local來源，不是用任意object造的反例。

按 D67「同一窄 call-site search看到另一個不可區分 producer就返回」的停止條件，在此停止。`mcp_app_follow_up`與 `mcp_extension_host`是不同 producer；不能只因後者literal乾淨，就把前者或普通context視為同樣封閉。本次亦未證明Hook可直接區分這個threadSource；若 A 已有同一步身分對應證據可沿用，不強制另造Hook欄位。

**單一待決事項：**有限Desktop contract須如何處理這個已可達的 `Z.context → pta.firstTurnConfigOverrides` 邊界？若要共用「無 relevant override」invariant，下一個必要事實是該context的實際上游producer／validated key schema；若已有可沿用的同一步身分，才可把此分支明確排除。這次不能據此開全App路由，也不表示需要再盤點所有client。

本輪前後均為 `gpt-6.1-sol/high`；中斷前turn `01a12ecc-0066-7401-b085-47ef91e424dd`、接續turn `01a12ed3-013d-7161-ae44-a5b854654b87` 的metadata-only核實保留。唯一修改本文件，無tests/build/JSexecution/UI/launch/model/private data讀取，無new Goal/agent；B/A與保留環境不動。D66已接受的resource身分／assembler evidence沿用，未重跑；新 direct-caller resource identity另列如上。

### D67-C-001 傳送狀態：未送達

來源成果已提交 `a5d27e76b37d3f89b963ad56d628775779724176`。向原 A 的 `send_message_to_thread` 被自動審查拒絕；一次有界 recovery 已用官方 `read_thread`核對原local督導身分與人類續作來源，再以同工具、同目的地、保留原資料重送，仍被拒絕。審查表示目的地已確認為同一本機工作執行緒，但帳號所有權／本次本機路徑與內部實作細節的明確傳送授權仍不足，並稱原D65授權不涵蓋D67 payload。

這是 enforced messaging boundary；不表示原同任務施工／回報意圖已撤銷。A未透過該工具收到D67報告，不宣称已送達，不換recipient/channel/tool、刪改敏感欄位或由其他聊天relay來繞過。報告保留在本文件，源碼查證單元已完成。本段保存當時未送達事實，不是替代派工或接受；後續 A 已在 D68 直接讀取並接受本地來源成果，舊 outbound 不再重送。

## D68：實際 bundled backend 的設定來源阻礙

### 校正執行檔身分與可沿用證據

原 `codex-cli/bin/codex` SHA256 沒有改變，但該檔案是 POSIX shell launcher，最後 `exec` 至 `codex-cli/CodexCLI.app/Contents/MacOS/codex`。實際 Mach-O 的 SHA256 為 `0d5ac7aae20c4eda6242428d5e218c55ba96d8763fda2a271088ff37104b9d28`。已安裝 `codex-package.json`（SHA256 `95ea87bed0ff10cb2cbd9b0541b0e332b4c87f74efd961924029beb33bebb407`）與 binary 的非使用者版本字串均為 **`0.162.0-alpha.17.2`**。未執行 binary；D65 的 CLI `0.159.3` refresh 結論不代替本版來源核對。

ASAR 啟動 owner `.vite/build/application-network-startup-CfAQmSYg.js`（SHA256 `cd6e8a8fbc4354a6e6ff19c6e4bf6fc1fb3960c63708c83871357c6238f516a8`）的 `Qs/$s/tc/Ks/Ws.connect/Us.spawnProcess` 顯示 Darwin 預設選上述 Mach-O；基本 argv 為固定 `-c features.code_mode_host=true app-server --analytics-default-enabled`，可選環境來源只有 `chatgpt_base_url`／`openai_base_url`。額外 `getConfigOverrides` 的 main `j5`（約 `3246400–3246850`）取 Darwin 空的 `bootstrap.pT`、只回 `features.secret_auth_storage=true` 的 `pqe`、以及兩個 packaged plugin MCP enable flags。自訂 binary／command、額外 argv 與其他 transport 仍須拒絕；本次沒有讀取真實 process argv／環境。

普通 composer 的直接新增證據是 `app-primary-6f60e9ac4103.js`（SHA256 `7fe9c00b03cb1de3ebc3a4bf298fc44b13a7fe67ca9cc335a9e2ecda969a1321`）：`C9e`（`913325`）回封閉欄位；`plt`（`1234023`）只回四種 nested context；`fut` 的 image helper（`1267200–1268420`）只回 imageAttachments／imageCommentDrafts／prompt；`Zs`（`1384163`）將這些構成 composer context。`Put`（`1285000–1286500`）將 `additionalContextOverride` 合併在 **nested additionalContext**，不 spread 到外層 config override。沿用 A 的 widget `pi→Gc→Kc→Fr→createMcpAppThread` 補證與此版 Pages `xt` no-op，以及 D67 的 extension-host／worktree constructor；不是重新把 generic assembler 的任意輸入當 reachable producer。雲端阻礙出現後，不再擴展所有其他 caller 的盤點，也不宣稱全 producer 不變量已閉合。

### 可達來源：正常 App-server → cloud fragments → derived child defaults／roles

以下均為官方 **`rust-v0.162.0-alpha.17.2`** 對應版本來源；本機 binary／package 身分與來源 hash 分別保存，這是來源契約分析，不是執行觀察或可重現 build 證明。

1. [app-server 啟動](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/app-server/src/lib.rs#L533) 的 `ConfigManager` 先讀 bootstrap config，再在 `547` 起以 bootstrap auth 呼叫 `replace_cloud_config_bundle_loader`，然後 `load_latest_config`。這是正常啟動鏈，沒有只限 remote client 的分支。
2. [ConfigManager](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/app-server/src/config_manager.rs#L140) 建立 `cloud_config_bundle_loader`；`load_with_cli_overrides` 在 `455–466` 將 `policy_load.cloud_config` 傳入真正 `ConfigBuilder`。本機 argv／檔案都相同，仍不能由它們推定 cloud snapshot 為空。
3. [cloud bundle backend](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/cloud-config/src/backend.rs#L94) 將正式 response 的 `config_toml.enterprise_managed` fragments 映射成 `CloudConfigFragment`，保留其 `contents`。這是實際外部設定入口，不是任意 object 的假設呼叫。
4. [fragment parser](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/config/src/cloud_config_layers.rs#L93) 解析整個 TOML、解相對路徑並建立 `EnterpriseManaged` layer；strict 模式驗的是完整 `ConfigToml`，沒有排除 agents/default/profile 的 key whitelist。[bundle validation](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/cloud-config/src/validation.rs#L9) 也沒有移除此類 config keys。
5. [layer loader](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/config/src/loader/mod.rs#L211) 取得 cloud snapshot，`288` 將 cloud layers 置於 system 與 user 之間。user config 沒寫某 key 不會清除 lower cloud layer 的該 key。[AgentsToml](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/config/src/config_toml.rs#L753) 正式接受 `default_subagent_model`／`default_subagent_reasoning_effort` 與 role declarations；[core Config](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/core/src/config/mod.rs#L3911) 從 effective cfg 取這兩個 defaults，`3821` 的角色 loader 亦遍歷 effective layers。
6. [child config](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/core/src/agent/child_config.rs#L193) 在 spawn 未指定時優先使用 derived child defaults；不是一律以 Hook parent model 繼承。[native Hook schema](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/hooks/src/schema.rs#L499) 的 SessionStart 沒有 cloud layers／binding／effective child-default 或 role snapshot。

本次**沒有**讀取帳號、雲端快取、auth、private session 或實際 cloud payload，也沒有觀察到本帳號已收到特定子模型設定。確認的是：此已定位的正式來源能將 relevant keys 送入 resolver；原 finite disk guard 不能證明它不存在。這與 D66 的條件式 caller-object 例子不同，來源及正常啟動接續已找到；帳號當時的實值保持未知。

相同版本的 [runtime refresh](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/core/src/config/runtime_refresh.rs#L112) 從 `self.clone()` 更新 MCP／features／layer-backed runtime 欄位，保留 derived defaults／roles。這能保留初始設定，**不能把初始未證明的 cloud override 消除**。[root start Hook](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/core/src/hook_runtime.rs#L132) 可將 native ThreadSpawn 分成 SubagentStart；它也沒有增加 cloud 身分證明。

### 需要 A 改的單一契約與交付界限

D68 的「pinned App／binary＋native fresh SessionStart＋本機 configuration／role guard ⇒ empty relevant defaults／default role」不能作 accepting path。要使用 Hook parent 作 baseline，有限 Desktop contract 必須增加 **由原生宿主發出、與該 session 實際 loaded configuration 綁定的 cloud layer／default-role／child-default 證明**；單獨的磁碟檢查、版本 pin、当前另一次 config/read 或「未看到 default literal」不補足這項缺口。此輪沒有可供整合的 accepting adapter；也沒有建置全 skip 空殼來表示成功。

A 決定在既有官方能力及原授權內是否有這項證明來源，或將此 bundled 版本的 Desktop 接入明列未支援；不要求改 App、替換 binary、讀私人 cache／auth、停用 managed policy、加 dispatcher 或重跑 CLI 來消除這個缺口。仍保留原 App 最後 native delegation/readback／disable 的驗收義務，尚未到該步。

唯一版本化修改為本文件與新 sanitized evidence。無 runtime／adapter／測試變更、無 tests/build/model/UI/launch/install/trust；D66/D67、A 補證、CLI／核心／模型矩陣沿用。C 的 turn `01a12ee7-13a6-7322-9166-0d819d0be992` 已核 `gpt-6.1-sol/xhigh`；同一人類 item `01a12edd-5354-7a20-82b0-004744cdeb89`／turn `01a12edd-464c-78b1-a390-90ca4685f414` 已由 supported read_thread 核實。Monitor check ready，正常 escalation 後 pending selection 成功保存 `source_pending/unbound_existing_work`，仍無 task_id，不冒稱已登記／接受。B/A 檔案、真實 profile、E20、auth/history、dist 與 allowlist `/` 未修改。

### D68-C-001 傳送狀態：未送達

来源成果 commit `fa92c0e` 的完整 D68 報告以原生 `send_message_to_thread` 送往原 local A，遭自動審查拒絕。送出前已核原目的地與本輪直接人類來源；拒絕理由明示工作本身已獲授權，但未見本批 D68 本機路徑、已安裝 binary 身分與內部實作細節對該聊天的明確傳送授權。既有 D67 的相同授權核對已兩次被拒，當前人類來源也未新增 D68 payload 確認，因此不重複沒有新證據的重送。

本地成果與原 App 義務保留，A 未透過本次工具收到報告；待人類明確允許此 D68 payload 傳至原 A 才沿同 route 續送。沒有更換工具／目的地／channel、刪改敏感欄位或其他聊天 relay，也沒有把文件保存說成已交付或已接受。
