# D56：既有登入隔離與日常 generic 委派的最小資料來源

D56 已由原 A 正式送達；本回合可信 executor metadata 為 `gpt-6.1-sol/high`。A 已完成原 ChatGPT 對焦、人機驗證已解除；下方 D54 的瀏覽器阻礙描述只保留歷史。本單元只修改此文件，沒有施工派工或正常環境啟用。

## 1. 登入隔離：可實作候選與限制

**未找到兩個已安裝版本可直接跳過全域 AGENTS、同時維持原 auth home 的公開 invocation 選項。** 本輪只讀 shell `0.159.3` 與 Desktop 內附 `0.162.0-alpha.17.2` 的 `exec --help`：`--ignore-user-config` 限於 config.toml，`--ephemeral` 限於 session 落盤，`--ignore-rules` 限於 execpolicy；都不是全域指引隔離。[新版 home instructions provider](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/codex-home/src/instructions/mod.rs) 仍從指定 home 載入 AGENTS／override。沿用 E19 對舊版的真實隔離證據，沒有再試模型或重複指引探測。

兩次 help 都在 startup 嘗試建立 PATH alias 時被 sandbox 拒絕並警告，仍正常列出 help；沒有為此升權或修復，沒有執行登入或模型。這不是零 startup 嘗試的命令。

**最小候選是獨立、MRH 擁有的臨時 home，僅以 `auth.json` 檔案 symlink 引用原檔；不是把整個 home symlink 回原 home。** 原 home、AGENTS、既有 Hook 均不改。classifier 繼續使用既有 empty work、固定 Luna/low、工具／Hook／plugin／記憶停用與 project-doc 限制。這是依官方 storage 的 filesystem 行為提出的候選，並非官方提供的獨立 `auth-home` flag，也尚未宣稱通過真實登入驗證。

| Auth 模式 | 此候選可做什麼／不能做什麼 |
| --- | --- |
| File | 兩版 `FileAuthStorage` 以 `File::open` 讀 auth.json，以 `OpenOptions(create/write/truncate)` 更新同一路徑。檔案 symlink 會指向同一個原 auth 檔，MRH 不需讀、序列化或複製秘密；官方 CLI 仍讀取它。**CLI refresh 會寫回原檔，不能稱為唯讀引用** |
| Keyring | direct key 使用 canonical home 的 hash；乾淨臨時 home 是另一個 key。新版 secrets backend 也以 home 建立 namespace。沒有查到 CLI 的獨立 keyring-owner-home 選项；改 home 不會自動重用原 keyring 登入 |
| Auto | 先 keyring 再 file，不能把殘留 auth.json 視為一定正在使用的登入。若採 file reference，須明確確認所選原來源為 file；不能默默轉換原 keyring 登入 |
| Ephemeral auth | process 內存 store 以 home key 分隔，不會讓新 classifier 程序取得原程序 auth；它與 `exec --ephemeral` 是兩件事 |

官方來源：[0.159.3 storage](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/login/src/auth/storage.rs)、[0.162.0-alpha.17.2 storage](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/login/src/auth/storage.rs)、[新版 auth modes](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/config/src/types.rs)。本輪只對正常 `/Users/shawn/.codex/auth.json` 做 `lstat`：存在、原生 regular file、非 symlink、owner 為目前使用者、mode `0600`；沒有讀取內容或查 keyring。D54 config 沒有顯式 store mode，官方 enum 預設 File，但這些 metadata **不能證明目前 token 類型、有效性或 App 使用同一個登入來源**。

刷新責任仍在官方 CLI：兩版 `AuthManager` refresh 後呼叫 storage.save，refresh semaphore 屬單一 manager；引用同一檔案不產生跨程序 refresh 鎖。[舊版 manager](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/login/src/auth/manager.rs)、[新版 manager](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/login/src/auth/manager.rs)。因此並行 classifier 應由 MRH 單一寫入 owner／串行請求控制，但這不等於已協調所有日常 Codex 程序。原檔消失、換帳號、refresh 失敗或 reference 改變均保留原委派並記錄失敗；不能自動重登入。A 要裁決接受官方原有多程序 auth 更新語義，或要求額外共享 owner。清理只 unlink MRH 的 reference 並刪除自己的臨時目錄，不呼叫 logout、不追隨 symlink 刪 target。未建立任何 real reference；source 已足夠辨認 open/save 行為，不新增合成 filesystem 試驗。

最小實作差異：在 subscription adapter 明確分開「原 auth 來源」與「classifier 執行 home」，把 home 指引 guard 改成檢查獨立執行 home；保留原來源型態／owner／權限和失敗檢查，仍由官方 CLI 使用 auth。若來源為 keyring／auto 未確定，不套用 file 候選。此變更與 CLI pin 支援範圍由 A 派工，本輪未實作。

## 2. 日常 Hook：控制介面可用，最小缺口是已解析的角色／原 child model

**目前 App 內附 native binary 的 Hook 契約可用。** E4 `docs/evidence/e4-bundled-host.json` 已在這個確切版本驗證 native PreToolUse deny／updated-input、PostToolUse，以及 synthetic Fixed／保留 explicit／低信心／失敗；shell E4 同樣可用。那是 native binary＋synthetic provider 證據，不是 Desktop UI 正常 home 安裝或真實付費模型驗收；不重跑。版本差異本身不能當成不支援，MRH 的單一 SHA pin 應成為已知能力契約選擇，而非全 App 拒絕理由。

[兩版共通 schema](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/hooks/src/schema.rs) 提供 `session_id/turn_id/tool_use_id/cwd/model/tool_name/tool_input`、permission mode，以及可選 caller `agent_id/agent_type`。其中 caller agent_type **不是待建立 child 的角色**；child 指定仍從 `tool_input.agent_type/model/reasoning_effort` 判定。`transcript_path` 不使用。[新版 hook_runtime](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/core/src/hook_runtime.rs) 的 model 直接取當次 step 的 model_info；這足以替代把正常 config 的 Astra/max 當當前模型。schema 沒有 parent effective effort、已解析的 child role model／effort 或 original child baseline。

[child_config](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/core/src/agent/child_config.rs) 先取當次 step model／effort，再套用明確或 turn config 的 default-subagent model／effort，之後套 role。V2 非 full-history generic 仍可能解析配置的 default role；full-history 與指定 role 有不同分支。不能因 tool_input 未寫 model，或 caller 不是某個 named role，就宣稱待派 child 沒有固定 model／effort。

官方最小配置查詢是 `config/read`，傳 canonical Hook cwd、`includeLayers=true`；回傳 config、origins、layers，會合併 project／user／managed／CLI layers，不需掃 Code tree。[Params](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/app-server-protocol/schema/typescript/v2/ConfigReadParams.ts)、[Response](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/app-server-protocol/schema/typescript/v2/ConfigReadResponse.ts)、[實作](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/app-server/src/config_manager_service.rs)。只需取 agents/default-subagent 與實际被選 role 的 model／effort 來源，必要 target 支援資料沿用既有 catalog 契約；不能保存／外送整份 config。

但該 query 沒有 session／turn／step selector；[loader](https://github.com/openai/codex/blob/rust-v0.162.0-alpha.17.2/codex-rs/app-server/src/config_manager.rs) 使用被查 app-server 自己的 CLI overrides。Hook 另起 app-server 查同一 cwd，只能得到另一個 process 的配置；即使接到原 server，config/read 仍不是正在執行 step 的完整捕獲配置。現有 command Hook 沒有已查明的同源 RPC endpoint／step projection。這是明確缺口，不能以新 dispatcher、讀私人 rollout、額外啟動 proxy 或擴大全域 snapshot 解決。

**最小可信輸入只有：** observed call IDs／cwd／parent model、原 tool_input；依 native 實際 resolution 已確認的 child role 是否固定 model／effort，以及原 child model（普通成本比較需要）。target effort 若設定明確值，使用該值與 catalog 支援集合；只有確實依賴繼承 effort 時才需要它。MRH `routing/core.py:149` 目前連 ordinary 的 original_effort 也要求 known，但後續 `cheaper` 只比較兩個 model rates，沒有使用這個值；A 可裁決縮小這個不消費值的門檻，**保留角色 effort 保護、明確 effort、target 支援與所有實際價格／信心度檢查**。本輪沒有改 core 或把未知 effort 填成 config default。

不可觀察時的精確 skip：有效 default／named role、default-subagent model 或父 App runtime override 無同源資料；不確定 full-history 規則；未通過來源／cwd／版本能力驗證；目標 effort 需要繼承卻未知。它們保留原委派並回報原因，不設成 unprotected，也不先付費分級。單純切換主模型不應再靠 exact config model 相等判定失效，因 Hook 已觀察當次 model；cwd 改為人類 canonical 白名單 gate，不能連帶移除上述配置來源驗證。

結論供 A 裁決：file-auth ephemeral reference 是小範圍可實作候選，需接受更新責任；日常 native Hook 控制層已有有效證據，但 generic role／ordinary baseline 的同源資料尚無 command-Hook 公開投影。若無可驗證的既有同源入口，完整 generic 日常自動路由仍有這個能力缺口，不能以正常 home 登錄成功宣稱完成。下一步應只裁決如何提供這兩個必要值或限定可證明的 generic 路徑，而不是要求全知 host snapshot。

本輪只讀已存 source／E4 與精確官方 tag source、兩次 help、上述 auth metadata 和 executor metadata；零模型／登入操作／real reference／build／測試／source 或正常 Hook 設定修改。保留原 E20 全部 session/history。新 Monitor context 的 `host-select --mode pending` 仍回 `current_host_turn_unavailable`，未回退舊 context 或製造 task ID。

---

# 日常 Codex Hook 現況與 MRH 限制（D54 修正後）

本文件是原 B 的唯讀事實回報。檔名沿用最初派工；最初的 Code-tree 盤點與遞迴安裝方案已撤回。本輪沒有掃專案樹、安裝、修改原有 Hook／設定／登入、執行模型、測試或打包。原 A 負責設計與整體驗收。

## 入口與目前狀態

日常執行入口是 Codex 的 Hook 登錄與委派事件。MRH 插件只匹配 `spawn_agent`／`collaborationspawn_agent` 的 `PreToolUse`、`PostToolUse`；設定入口另為 `mrh model`。工作區白名單是事件是否允許進入 MRH 的條件，不是 Hook 的安裝層級，也不要求每個專案另裝一次。

目前一般 home `/Users/shawn/.codex/hooks.json` 已登錄 Canopy 的 `UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop`，引用 `/Users/shawn/Code/Canopy/adapters/codex/canopy_hook.py`。本輪只輸出已知 Canopy 路徑與事件名稱，未匯出完整 command／設定。一般 home 的已啟用插件清單及上述 hooks 檔沒有 MRH 登錄；MRH 的兩個已信任 Hook 仍只在保留的 E20 隔離 home。

| 已觀察項目 | 事實與證據邊界 |
| --- | --- |
| 一般 shell CLI | npm wrapper 的公開版本為 `codex-cli 0.159.3` |
| Desktop | `/Applications/ChatGPT.app` 的 bundle ID 為 `com.openai.codex`；版本 `26.1007.30912`／`20156`；內附 CLI 為 `0.162.0-alpha.17.2` |
| App／CLI 是否實際載入同一組 Hook | 本輪沒有啟動正常 home 的新執行流程，尚未獨立觀察；版本或 home 檔案存在不能取代載入與事件證據 |
| 正常 home 的指引 | `AGENTS.md` 存在，`AGENTS.override.md` 不存在；沒有讀取其內容或任何 auth 檔 |
| 正常 config 的模型預設 | `gpt-6-astra`／`max`，僅為已讀設定預設 |
| 本次 B 的實際 executor | 可信 session／turn metadata 為 `gpt-6.1-sol`／`high`；不能拿 config 預設代替執行中的模型、推理或角色 |

## 哪些限制是 MRH 自己加入的

| 限制 | 來源與實際影響 |
| --- | --- |
| 固定 CLI `0.159.3` 與 binary SHA | MRH `codex_scope.py` 的有限相容性契約。Desktop 內附版本不同，目前不在此契約中 |
| exact cwd／home | MRH `check` 要求事件 cwd 等於單一綁定 workspace，`CODEX_HOME` 等於綁定 home；不是 Hook 必須逐專案安裝的官方要求 |
| startup 白名單 | MRH 只接受指定 interactive `--no-daemon` 或 `app-server --listen stdio://` 及少量參數；拒絕其他 flags／positionals，包括模型、profile、config 等覆寫。這是目前可驗證契約，不能推論官方不支援那些參數 |
| 拒絕額外 config／managed layers／default agent overrides | MRH `_configuration` 為避免猜優先序而加入；不能直接移除後宣稱取得有效執行事實 |
| 根路徑含後代的授權 gate | `settings.workspace_allowed` 已支援 root 或 descendants；但後面的 exact-cwd guard 仍存在，單改這個 gate 不能完成日常接入 |
| 訂閱 classifier 拒絕 home 指引 | 官方 pin 會另外讀全域 home 指引；MRH `sanitized_environment` 以檔案存在檢查拒絕 `AGENTS.md`／override。正常 home 會碰到 `home_instructions`，不能靠登錄 Hook 就宣稱正常分級 |

程式位置：`src/mrh/adapters/hosts/codex_scope.py`（版本常數、`_configuration`、`supported_startup`、`check`）；`src/mrh/infrastructure/settings.py:75`；`src/mrh/infrastructure/plugin.py:166`；`src/mrh/adapters/providers/codex_subscription.py:181`。

官方 `CODEX_HOME` 是 process 的 home 選擇機制；全域指引由 [CodexHomeUserInstructionsProvider](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/codex-home/src/instructions/mod.rs) 另行載入。既有本機 public source `build/e19-public/home-instructions.rs`、`config-core.rs` 與 E19 有效隔離證據沿用，不重跑。MRH classifier 現在繼承父程序 `CODEX_HOME`；讓父宿主與 classifier 分別使用已信任的 home 是待 A 裁決的接法，尚未實作或驗證，不能藉此搬移／複製憑證、移除 AGENTS 或更換登入。

## 保留 Canopy 與既有安裝

Canopy 的 prompt handler 回傳 `additionalContext`；tool handler 做活動紀錄，失敗不能改變原工具；Stop 失敗是 advisory 且 `continue: true`。本輪相關 source 沒有 `permissionDecision`／`updatedInput`。MRH 應保留現有登錄與 handler，獨立增加必要事件；不能包裝成替代 Canopy。既有 public dispatcher 使用 `FuturesUnordered` 並行 handler，設定排列不能當作資料先後保證。

保留環境 `/private/tmp/mrh-e19-d45-mrc5zw54` 包含原 home／work／state／plugin／model-bindings。E20 的 session、登入、revision 25、disabled／export-denied 與歷史全部沿用，沒有再讀憑證、登出或重建。其暫存位置與有限宿主契約仍不是日常安裝。registry 的程式預設位置為 `~/.local/state/model-routing-harness/model-bindings`；目前保留環境使用明確指定的位置。永久安裝與移交路徑仍由 A 決定，本輪不搬移。

## 最新需求與接續邊界

原 A 人類訊息 `01a12c8d-16c7-7da0-b475-4b53fbdaaafb` 要求先回原 ChatGPT 對話對焦日常 Hook，保留既有 Hook，接通後設定四級；在 MRH 專案建立不納 Git 的可編輯白名單，初值 `/Users/shawn/Code` 並涵蓋後代。這是新的明確 eligibility 需求，不恢復被撤回的 Code-tree 掃描／逐專案安裝。本輪不建立該檔或決定格式。

使用者隨後在 B 說「已經登入了 試試？」。B 查驗原 A 最新原生紀錄：A 先前保留的原對話為 `https://chatgpt.com/c/6ac87fe7-da4c-83ec-8081-19b331292214`，曾停在人機驗證；B 自己的 in-app browser 沒有該分頁，因此沒有另開或重送。這是登入完成的人工通知，尚非 B 已驗證頁面可送出。請 A 從自己的原分頁重試，先檢查是否已有送出／生成中回應，再接續原本對焦，不換對話、不重複付費試驗。

A 接續需裁決的具體缺口是正常 App／CLI 的有效宿主與每次委派的模型／推理／角色證據、classifier 的安全訂閱隔離來源、永久且可逆的安裝，以及白名單入口。不可降低明確模型／角色／安全保護來擴大 cwd。後續驗證只補這些消費者的直接事件與失敗邊界：既有 Hook 共存、白名單內外與取消／失敗保留、有效覆寫未知時保留原呼叫、隔離指引及當前登入保留。既有九次模型證據與 E20 套件驗收沿用，不因日常安裝自動重跑整套。

Monitor 的可信 context 沒有可用原請求身分，`host-select --mode none` 回 `current_host_turn_unavailable`；本輪沒有自造 task／ledger，這個紀錄缺口不等於成果完成或接受。
