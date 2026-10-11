# E11-B-001：Claude／Gemini 公開介面盤點

2026-10-11，依 A 的 D25 完成兩個介面的唯讀調查。E10R 已由 A 親自接受；本紀錄沒有實作 adapter、安裝套件、啟用 Hook、登入、查真實帳號或提交模型任務。模型清單與同一次委派的控制能力仍是不同證據；原 R1／R2 分母與缺口保留。

## Claude：有 SDK 清單與逐模型 effort 型別，尚無可宣稱工作的本機 adapter

本機 `/opt/homebrew/bin/claude` 指向 `/opt/homebrew/Caskroom/claude-code/2.1.267/claude`。在新建、已清除的 `/private/tmp/mrh-e11-help-*` HOME／cwd，清空憑證環境、關閉非必要流量並把 outbound proxy 指向閉合 loopback，公開 `--version` 回覆 **2.1.267**；`--help` 確認 session 的 `--model`、`--effort`、`--agents` 與 stream-json flags。這不是帳號或模型探測，且不能用 main-session flags 證明子代理配置。

官方 TypeScript SDK 公開包 **0.3.296**（本機未安裝／未執行）提供以下正式型別。來源是 [官方 npm metadata](https://registry.npmjs.org/@anthropic-ai%2Fclaude-agent-sdk/0.3.296) 與其 [固定版本公開 tarball](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.296.tgz)，僅在記憶體讀取 `package/sdk.d.ts`、`sdk.mjs`、`package.json`：

- `Query.supportedModels(): Promise<ModelInfo[]>`。`ModelInfo.value` 是請求值；`resolvedModel` 可選，用於別名對應的 wire ID。另有 `displayName`、`description`、`supportsEffort`、`supportedEffortLevels`（low／medium／high／xhigh／max）、`supportsAdaptiveThinking` 等能力欄位。缺少欄位不能推定支援；本次未執行 supportedModels、未取得本機實際清單，不能把型別中的示例當模型候選。
- `sdk.mjs` 的 `async supportedModels(){…}` 與 `async accountInfo(){…}` 都讀取 initialization 的既有結果，並非每次重新抓清單。刷新需要新的可靠初始化／生命週期，不能把重讀快取當 fresh observation。這些型別未給 retirement／撤權／完整帳號可用性訊號；清單遺漏不代表全球下架。
- `AccountInfo` 的 optional fields 有 email、organization、subscriptionType、tokenSource、apiKeySource、apiProvider。此型別沒有明確保證不可變的 account/workspace UUID；organization 字串也不能自行當唯一 UUID。可以描述安裝／backend scope，不能聲稱 account-confirmed binding。本次沒有呼叫 `accountInfo()` 或讀取憑證／私人狀態。
- `query()` 要求 `prompt: string | AsyncIterable<SDKUserMessage>`；其 Query constructor 啟動初始化，`streamInput()` 在 initialize 寫出後才消費 user messages。**可行推論**是以不產出 message、可取消的 async iterable 取得初始化 metadata，之後關閉 Query。這只是源碼支持的候選方法；未證明 installed CLI 2.1.267 能在無認證、無網路、無 task 的隔離條件完成它。不得以空字串 prompt 代替「沒有任務」，也不改用私有 stdin control RPC。
- `Options.pathToClaudeCodeExecutable` 可指定 executable；0.3.296 有自身 native optional packages。**SDK 與 CLI 版本不能由 patch number 自動配對**：一次假設 0.2.267 的 metadata 查詢得到 404，已停止猜測；這不是 SDK 不存在的證據。0.3.296 型別不證明已安裝 2.1.267 完整相容。

委派／控制已有正式入口：[SDK subagents](https://code.claude.com/docs/en/agent-sdk/subagents) 與 [SDK hooks](https://code.claude.com/docs/en/agent-sdk/hooks)。0.3.296 的 `AgentDefinition` 公開 model（別名或完整 ID）及 effort；`PreToolUse` 可 deny 或以 `updatedInput` 改參數，`PostToolUseFailure` 是候選失敗觀察事件。這些是 API 能力，**沒有證明 Agent tool 的當次 input 有可安全改寫的逐子代理 model/effort、固定角色優先順序或可靠錯誤分類**；也沒有 MRH 接入／實際停止證據。不得只憑 CLI main model 或 SDK 定義說所有委派已支援。

下一個可行契約供 A 決定：先釘住 SDK＋指定 CLI 的相容版本，只允許受控 root、無憑證、無 MCP／hooks／私人 settings、零 user messages 的初始化；若不能完成，回 `catalog_unavailable`，不得登入、fallback 或送 task。僅作 tool-advertised catalog；分開保存 request value 與可選 resolved ID，逐模型 effort 只採實際回傳欄位。**此探測／安裝不在 E11 已執行範圍，仍需 A 先確認依賴與副作用契約。**

## Gemini：ACP session 提供清單，但其取得路徑先做認證與聊天初始化

安裝入口 `/Users/shawn/.nvm/versions/node/v20.19.4/bin/gemini` 指向 `…/lib/node_modules/@google/gemini-cli/bundle/gemini.js`；同目錄 `package.json` 版本 **0.63.0**。入口第 110 行載入 **`gemini-6YZTUGIX.js`**，本次檢查的是這個實際入口 chunk，而非其他重複 chunk。公開 [ACP 文件](https://geminicli.com/docs/cli/acp-mode/) 說明 stdio JSON-RPC；已安裝 bundle 中的直接證據如下：

| 問題 | 已確認的來源與邊界 |
|---|---|
| 清單在哪裡？ | `GeminiAgent.initialize`（16597–16656）回 protocolVersion、authMethods、agentInfo、capabilities，**沒有 models**。`session/new` → `SessionManager.newSession`（16372–16457）才回 `models.availableModels`／`currentModelId`。不能把 initialize 宣稱為模型清單。 |
| ID／推理選項？ | `zModelInfo`（12679–12685）只有 modelId、name、optional description／_meta，無 per-model effort enum。`buildAvailableModels`（14997–15078）把候選 value 映到 modelId，含 auto alias；preview/dynamic options 受 auth/config/rollout 影響。沒有觀察實際帳號清單。不能把 approval modes 當 reasoning，或猜 thinking budget 對應 high／low。 |
| 認證／任務／網路？ | `newSession` 先 `loadSettings(cwd)`、`refreshAuth`；沒有 key 時會拒絕。接著 config.initialize、auto-memory、Gemini chat 初始化後才建清單。`prompt` 是另一個方法，所以明文 user prompt 並非這個 response 的必要步驟；但這也**不保證無認證／網路／其他寫入／模型相關初始化**。本次未執行 ACP。 |
| 綁定／刷新？ | agentInfo 是工具 name/version；sessionId 是新 session 的 random UUID，皆不能當 account ID。公開 response 未提供可保證的 account/workspace identity 或 retirement flag。新的 session 可重建清單但會再經認證／初始化；失敗不能當退休，快取不能標成 fresh。 |
| 換模型／停止？ | `unstable_setSessionModel`（16749–16761）轉呼叫 Session.setModel（15226–15229），設定 config 並回 `{}`，不是可用性／執行成功收據。ACP requestPermission 有 reject/cancel 選項，並非證明每筆委派必會進 permission gate。 |

已安裝公開 docs `bundle/docs/cli/model.md` 與 [官方 model 文件](https://geminicli.com/docs/cli/model/) 明確說 `/model`／`--model` 不覆寫 subagent model。另有 [BeforeTool 公開 Hook](https://geminicli.com/docs/hooks/reference/#beforetool) 的 deny、tool_input rewrite、continue=false 控制，以及 AfterTool error 欄位。這些提供後續接入方向，但目前沒有 MRH adapter、可靠同次委派 model/effort/role precedence 與單筆穩定 correlation 證據；**不可把全 session 換模型或殺整個 agent loop當作單筆子委派已符合要求**。

下一個可行契約供 A 決定：保留 Gemini unsupported／exact auth-required catalog gap。若未來授權真實 scoped session，只採該 session 的 `modelId` 並清楚標示 auto alias，無公開 effort enum 時僅保留未解析 inherit；不得從內部函式抄一張固定清單來充當 account catalog。若要允許純「shipped tool-default metadata」來源，必須另由 A 明定可靠來源、scope 與限制，不能由 B 自行把未 export 的 helper 做成 supported public API。

認證前置／nonempty key 檢查不等於證明 key 已經通過服務端認證；也不能單憑上述路徑宣稱「無真實憑證的清單取得絕對不可能」。本次沒有執行 session 路徑，是否能用受控無訊息初始化、完全離線且不讀真實憑證取得 tool-defaults，仍待 A 先確定副作用與來源契約。相同地，內部 helper 不算公開 API，不代表已發佈 metadata 絕對不可作為另一種明確標示的來源。

## 來源身份與收尾

| 靜態來源 | SHA-256 |
|---|---|
| Claude native 2.1.267 executable | `a681f3008f0050029aeebcab3af51bb6a55ddeb625a3af3141a4416d43cd2558` |
| 官方 SDK 0.3.296 tarball | `e966be99b6f047d56165e2ec03822f17a49beebd48ac8efb91dab1e48bcf69a7` |
| tarball 的 sdk.d.ts | `fc2866dfe2c01468edb19b1d94f26156bfacecdf1e7f1452b276ed2f8cc0b08f` |
| tarball 的 sdk.mjs | `5cf6f15237f9c84e6e5b724a10180478732457168921d7aa3e02632037cce299` |
| installed Gemini gemini-6YZTUGIX.js | `a64b06d8a06673cfae0134558e162e5b015d088a3751639c7d6dc4a88c67c1f8` |

原大型 Claude TypeScript HTML 文件仍回 400 size limit；新 Markdown URL被 web 工具以 unsupported text/markdown 拒絕；改由官方 npm 公開 source 建立 schema。sandbox DNS失敗後，工具審查允許唯讀 registry access。這些是取得證據的方法限制，不是 provider 缺乏 API 的證據。公開套件僅 RAM 讀取，沒有安裝或留下下載物；help 的新建 root 已刪除並讀回 absence。未執行 adapter、account/model probe、tests/builds、正式 Hook、Goal 或 push。

本紀錄以來源／語意／diff／連結一致性審查收尾；沒有為 prose 啟動產品測試。A 擁有下一個介面契約／整合決定。兩個 AI 的實際 MRH catalog/routing 支援仍未接受；缺口沒有從原需求移除。
