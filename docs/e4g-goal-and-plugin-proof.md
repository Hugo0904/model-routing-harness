# E4G：隔離 Goal 與原生 plugin 前提

E4G 已補上兩個安裝版 app-server 的實際暫存 Goal 跨回合攔截證據，並完成原生 plugin 的唯讀前提核對。這是 D7 的交付，待 A 接受；完整 R1／S4 尚未完成。沒有正式啟用 Hook、安裝 plugin 或呼叫真實 provider。

## 實際 Goal 的兩個回合

| 執行檔 | Goal／兩次重新分級 | 含清理的 fixture 耗時 | 外層命令實耗 |
|---|---|---:|---:|
| Shell CLI 0.159.3 | 通過 | 2.573 秒 | 2.655 秒 |
| Desktop 隨附 CLI 0.162.0-alpha.17.2 | 通過 | 1.962 秒 | 2.143 秒 |

原始證據：[Shell](evidence/e4g-shell-goal.json)、[bundled CLI](evidence/e4g-bundled-goal.json)。後者是 app-server 執行檔，沒有操作 Desktop UI。

每次執行都建立全新私有 HOME／CODEX_HOME／workspace，透過原生 CLI 信任審核接受精確 fixture Hook，`hooks/list` 讀回兩個 Hook 都 trusted。Provider 僅為無憑證的 127.0.0.1 腳本伺服器；模型目錄沿用 E4 的對應公開 release tag、SHA256、合成型號與 native v1 capability overrides。這些不是預設 v2／code-mode 或實際模型的證據。

在同一個實際暫存 thread 中，依序讀回沒有 Goal、建立 active Goal、第一回合前、兩回合之間、第二回合後的 active 狀態。`threadId`、`createdAt`、objective 都一致；兩個 parent turn ID 不同，每回合的 `PreToolUse` 都有新的 `tool_use_id`，各重新分類一次。兩次 Main 都 deny、沒有 child thread／child provider 請求；主模型設定與請求仍為合成 parent／low。Goal 隨後設為 complete、讀回，再 clear 並讀回 null。兩個 app-server 均 exit 0，owned 程序、伺服器及暫存都已結束／移除。

第二回合由 harness 明確發出 `turn/start`。因此接受範圍是「同一 active Goal 的後續回合委派仍會被攔截和分級」；主代理自主接回、Goal 自動喚醒與實際智能完成仍未驗證。Goal RPC 在本次 fixture 的 `experimentalApi=true` session 中實際執行；此結果不建立跨版本穩定 API 保證。所有分級與 provider usage 都是合成資料，live Jev attempts／confirmed children 均為 0。

## Plugin 的預期路徑與版本差異

下表的本機證據只有版本與 help 文字；沒有實際 register／install／disable／remove，也沒有 plugin Hook 載入證據。兩版顯示相同命令，但未驗證其 runtime 行為。原始盤點與來源見 [plugin 前提 JSON](evidence/e4g-plugin-prerequisites.json)。

| 操作／契約 | 0.159.3 | 0.162.0-alpha.17.2 |
|---|---|---|
| Marketplace 來源查詢／登記 | help 有 `plugin marketplace list`／`add <SOURCE>` | 同左 |
| 可用 plugin 查詢 | help 有 `plugin list --available --json` | 同左 |
| 安裝 | help 有 `plugin add <PLUGIN[@MARKETPLACE]>` | 同左 |
| 個別 plugin 停用 | 官方文件指定 `/plugins` 瀏覽器按 Space 切換；未操作 | 同左 |
| 移除 | help 有 `plugin remove <PLUGIN[@MARKETPLACE]>`；marketplace 有獨立 remove | 同左 |
| Hook 載入與信任 | 官方文件描述 enabled plugin 的 hooks/hooks.json 或 manifest Hook，仍需一般信任審核；未實測 plugin Hook | 同左 |
| Plugin RPC | tag source 定義相關方法；官方文件將 list/read/install/uninstall 標為開發中、禁止 production client 使用 | 同左 |

官方 [Developer commands](https://learn.chatgpt.com/docs/developer-commands) 將 `codex plugin`／`codex plugin marketplace` 標為 Stable；[Plugins](https://learn.chatgpt.com/docs/plugins) 說明 marketplace 與 `/plugins` 切換。help 中繼承的 `--enable`／`--disable` 是 feature flags，不能當成個別 plugin 停用命令。這提供下一段實作的預期原生入口；MRH 自己的 plugin、marketplace 格式與隔離安裝仍須由 A 定案及後續驗證。

官方 [Hooks](https://learn.chatgpt.com/docs/hooks) 描述 plugin Hook 也需 review／trust，目前定義新增或改變時先略過；安裝或啟用 plugin 不代表信任其 Hook。沒有使用繞過信任的旗標。

官方 [App Server](https://learn.chatgpt.com/docs/app-server) 明確將 `plugin/list`、`plugin/read`、`plugin/install`、`plugin/uninstall` 列為開發中，production client 不應呼叫。[0.159.3](https://raw.githubusercontent.com/openai/codex/rust-v0.159.3/codex-rs/app-server-protocol/src/protocol/common.rs) 與 [0.162.0-alpha.17.2](https://raw.githubusercontent.com/openai/codex/rust-v0.162.0-alpha.17.2/codex-rs/app-server-protocol/src/protocol/common.rs) protocol source 都定義這些方法及 marketplace add/remove/upgrade；`plugin/search` 標為 experimental。來源定義或 schema 出現本身不證明 production support，也未找到個別 plugin toggle RPC。下一段不應採用開發中的 plugin RPC 作為正式安裝契約。

## 聚焦檢查與保留邊界

新增 5 項 Goal fixture 檢查全通過，外層實耗 0.109 秒：[輸出](evidence/e4g-tests.txt)、[命令與耗時](evidence/e4g-test-run.json)。覆蓋兩回合 lifecycle、unsupported RPC 不啟動回合、建立拒絕不冒充 PASS、Goal 身分中途改變時停止且清理、同回合或重複 call ID 不得冒充跨回合證據。E3／E4 的核心、provider、封裝與 12 個既有 host 情境沿用既有結果，未重跑。

本次只修改開發 harness、測試、文件與證據；CLI／TypeSafe 正式接線、native plugin 安裝實作、第三方 Hook 共存驗證、正式設定 shape 仍待 A 指派。S5 的實際 Canopy／Monitor 整合不在首階段範圍。歷史審查拒絕仍保留，D7 新增直接人類授權後以相同審查路徑取得本次執行准許。沒有 A／B execution Goal、真憑證或其他專案寫入。
