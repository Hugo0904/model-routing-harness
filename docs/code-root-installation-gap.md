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
