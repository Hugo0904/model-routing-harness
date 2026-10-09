# E1 能力盤點

MRH-001 / R1 / E1，報告 `MRH-001-R1-E1-B-001`。2026-10-10 Asia/Taipei。本文件是 B 的證據報告；A 尚未驗收，S2–S6 保留。Supported 表示該列明示的證據邊界已成立；unverified 表示缺少必要證據；unsupported 限定在目前工具／版本／契約。三者均不等於正式啟用。

## 結論與下一個完整工作包

Codex 有官方記載的 pre-spawn 攔截與參數改寫基礎，兩個安裝版本的隔離 schema／設定／Hook 發現也可重現。然而 **Top Main 真正交回工作、Fixed 真正採用指定模型，以及 Jev 的產品/API 契約仍未驗證**。目前不能據此宣稱自動路由可用。

建議 A 接著裁決並派發一個完整「獨立核心＋事實儲存＋CLI/JSON＋隔離 Codex 接頭候選」工作包：核心接受明確、可注入的分級結果；宿主能力描述與實際執行證据獨立；沒有 Jev 官方契約時網路接頭明列未支援。保留 explicit-model、0.5 門檻、fail-open、Top Main/Fixed、並行／冪等／事實統計的原始需求。Canopy 缺席是正常模式；Monitor 先交資料契約，不寫既有專案。

**需要 A 決定的單一設計問題：**是否先完成上述獨立能力與 Codex 候選，將真實 Main handback／Fixed／Goal 採用及 Jev 網路接頭設為不可宣稱支援的驗收缺口，並在原 GPT 窗口取得 Jev 原文/API 與宿主驗證方法後補齊？這是執行順序與設計裁決，不是降低 R1 的完成條件。

## 身分、規範與保留邊界

已透過 `read_thread(A)` 核對人類 turn `01a12263-5420-7cc0-a440-83566f3c110a`／user item `01a12263-6236-7952-95aa-34770afcf341`，含「分工讓B開始工作 B使用 gpt6.1 sol xhigh」。同 task、A/B、用途的通訊授權沿用。

`read_settings.py --thread-id 01a12265-1821-76b3-be93-acf74e1485c9` 讀回 B 本回合 `01a12265-19e4-7492-a9c2-676ac9a96e11`：`gpt-6.1-sol / xhigh`，cwd `/Users/shawn/Code`，recorded at `2026-10-09T20:40:16.293Z`。這是回合設定證據，不能冒充 provider 回傳的實際型號。

遵循 workspace AGENTS、supervised-delivery、engineering-workflow-router、core-development、risk-based-verification；規範與證據詳見唯一任務記錄。只修改新專案，不建立 Goal、不改主模型、既有三專案、C2C、正式 Hook 或全域設定，不 push、不發第三方憑證請求。

## 路徑與 Git

四個目錄的 physical path 都等於 `/Users/shawn/Code/<project>`，不是符號連結。完整非敏感 Git 路徑快照在 [e1-repositories.json](evidence/e1-repositories.json)。

| 專案 | Git / current working tree | 本輪處置 |
|---|---|---|
| Canopy | `main`, `6ef9c6a21b6d5ce8712bbde797675438fb8d1f3d`；73 個 dirty entries，包含公開來源／文件 | 唯讀；下文引用目前 working tree，不假稱 HEAD 或已採用 runtime |
| adaptive-agent-workbench | `main`, `704b2ced4a400bbb6c72b5ea9fc23b52a379bdb2`；19 個 dirty entries | 唯讀；Skill 維護仍屬此 canonical repo |
| Canopy-Task-Monitor | 存在，無 Git repository；`git rev-parse HEAD` 回傳 fatal not a git repository | 沒有 branch/HEAD/dirty 可讀回；沒有初始化或修改它 |
| model-routing-harness | A 先建立 REQUIREMENTS 與 task record，原本無 `.git` | E1 可初始化 `mrh-001` 並提交本專案文件與 probe；最終 SHA 在任務記錄／報告 |

最近規範入口：Canopy `AGENTS.md:7,19,76–81`；Monitor `AGENTS.md:1–20`；workbench `AGENTS.md:1–41`。Monitor 不能把 UI/帳本當執行證明；Canopy 公開投影不能夾帶原始 prompt、Seed、hidden reasoning、憑證與任意路徑。

## Codex Desktop 與 shell CLI

| 能力 | 狀態、證據與限制 |
|---|---|
| 安裝版本 | supported（版本讀取）：Desktop bundle `/Applications/ChatGPT.app/Contents/Info.plist` 為 `26.1007.21159` / build `20052`；bundled CLI `0.162.0-alpha.17.2`。shell `/Users/shawn/.nvm/versions/node/v20.19.4/bin/codex` 為 `0.159.3`。不能合併兩者驗證狀態。 |
| 委派入口 | supported（本對話工具 schema）：`collaboration.spawn_agent` 可指定 `agent_type`, `model`, `reasoning_effort`, `fork_turns`。工具 runtime 的 canonical Hook 名稱仍需 host execution 證據。Desktop `create_thread(model, thinking)` 是獨立聊天建立，不是工具子代理；不是本產品的攔截目標。 |
| pre-spawn Hook | supported（官方文件＋本機發現契約）：`PreToolUse` 匹配 `spawn_agent`（別名 `Agent`），JSON `tool_input` 是委派參數；`tool_use_id`、session/turn 可供事件識別。兩版本的 `hooks/list` 可讀回 `^spawn_agent$` 合成 Hook，`trustStatus=untrusted`。**未執行 Hook。** |
| Hook 改寫／取消 | supported（文件）；unverified（這兩版本的 actual execution）：同步 `PreToolUse` 可用 `permissionDecision=allow` 與 `updatedInput` 替換參數，或 `deny` 取消工具。`continue:false` / `stopReason` 不是此事件的取消方法。`SubagentStart` 已太晚，不能據此取消建立。 |
| Top Main | unverified。否決 spawn 是可能的攔截手段，但不等於主代理已完成該工作；需要零 child creation、主代理接回原子任務、可讀回結果及主模型未變。只繼承主模型或追加提示均不能驗收此列。 |
| Top Fixed | supported（requested fields）；unverified（主 Luna＋實際指定高階 child＋main unchanged）：要排除角色檔覆寫、host fallback、model unsupported。A/B 目前 Sol 建立設定與 Luna explorer 回報，不能代替這個產品場景。 |
| 回合／Goal 後續委派 | supported（schema 有 Goal methods 與通用 pre-tool 事件）；unverified（同 Goal 後續新委派實跑）。`UserPromptSubmit` 只處理首 prompt 不足夠；不得為 E1 建立 native Goal。 |
| 有效設定與執行結果 | supported（schema shape）：`Thread.model` / `reasoningEffort` 明示只是 configured/persisted setting，**not per-turn execution telemetry**。`ModelVerification` enum 只有 `trustedAccessForCyber`，不能當型號採用證明。Hook completed 的 `id/status/duration/entries` 證明 Hook，不證明 provider 型號。spawn 回傳 agent ID、PostToolUse/Subagent lifecycle 需另做可靠關聯。 |
| 支援模型／effort | supported（本次 Desktop 工具 metadata）：`gpt-6.1-sol`、`gpt-6-sol`、`gpt-6-luna`、`gpt-6-astra` 及所列 effort；本輪 B exact 設定亦吻合。**shell CLI 帳號可用 catalog 未驗證**；不同 surface 不互借。生成 schema 的 effort 是非空字串，隔離 `config/read` 接受 `mrh-invalid`，因此 parse/config success 不能證明模型相容。 |
| 成本／用量 | unverified。沒有按本帳號/平台實測價格、tokens 或任務成本證據；不可從 family/tier 推定更便宜，也不可計算「節省」。 |

上表 Hook 文件來源：[Codex Hooks](https://learn.chatgpt.com/docs/hooks)。實際 Hook input/output／改寫採用仍是 S4 驗證項。文件的 main schema 也可能超前 release。

模型設定優先序的官方描述：角色 TOML 的 `model` / `model_reasoning_effort` 可覆蓋 spawn/default/parent；一般解析先 explicit spawn，再 `[agents]` default，再 parent，換型號但未提供 effort 時可能用該型號 default。必須先檢查角色契約，不把「要求用 X」計成「X 已執行」。[Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

整體 config precedence 是 CLI override、受信任 project config、profile、user、cloud defaults、system defaults；政策限制另行約束。隔離 probe 已實證 CLI `model="mrh-cli-override"` 覆蓋暫存 home 的 synthetic model，只證明這兩層。[Config basics](https://learn.chatgpt.com/docs/config-file/config-basic)

現有正式 home 的唯讀形狀盤點：UserPromptSubmit / PreToolUse / PostToolUse / Stop 有 command handlers；pre/post matcher 為 `*`；config 另有 hooks table。沒有匯出命令內容或 credentials。新 installer 要保留兩來源，merge/preview/disable/trust 的完整行為留待後續實作驗證。

## E1 隔離 probe 與界線

[probe_codex_contracts.py](../scripts/probe_codex_contracts.py) 使用每次新建的 `TemporaryDirectory`、官方子程序 `CODEX_HOME` 選擇器、只傳必要環境、不複製 auth。只跑 version、generate-json-schema、app-server `initialize`, `config/read`, `hooks/list`，**沒有 thread/start 或 turn/start**。

正式結果：[e1-codex-contracts.json](evidence/e1-codex-contracts.json)，兩版本均成功生成 schema，CLI override、未信任 synthetic Hook 與任意 effort 字串都已讀回；實際執行 **0.933 秒**。JSON 含暫存 source path 以辨識隔離範圍；目錄已清除。

兩次中間證據也保留，以免刪掉診斷錯誤：

- initial（9.564 秒）：shell child PATH 用到舊 Node，ESM loader 錯誤；Desktop 的 `--strict-config` 不適用 schema generator。這些是 probe/tooling 錯誤。
- intermediate（0.776 秒）：修正 PATH 後兩版本工作；以 stdin EOF 啟动 app-server 沒有實際讀 config，不能驗收 invalid effort rejection。後續改用 `config/read` 得到最終結果並更正口頭回報。

初次隔離之外的 schema-only 生成約 0.19 秒（兩版本）；help/version/Git/文件查讀未逐項計時。沒有產品 tests、真實 Jev/OpenAI request、Hook trust bypass、正式 Hook 執行或模型成本測試。Top 行為、後續 Goal、provider 真實採用一律尚未驗證。這些不足不靠重跑 schema 填補。

## Claude Code 與 Gemini CLI

| 平台 | 已確認介面 | 目前限制 |
|---|---|---|
| Claude Code `2.1.267`，`/opt/homebrew/bin/claude` | 官方 `PreToolUse` 以 `updatedInput` 更換工具參數，可 deny；subagent 可指定模型並從 `/tasks` 查看 configured model | 相容接頭未實作／未實跑。官方 per-invocation `effort` 要 `2.1.292+`，**本機版本不符合此入口**；定義檔 effort 不冒充 per-call。組織模型限制可能替代 requested model，需 observed evidence。 |
| Gemini CLI `0.63.0`，`/Users/shawn/.nvm/versions/node/v20.19.4/bin/gemini` | 本機 bundled `docs/core/subagents.md:18–21`：agent 以自己的名字成為工具；frontmatter `model`／`agents.overrides.<name>.modelConfig` 決定模型。官方 `BeforeTool` 改写 `hookSpecificOutput.tool_input` 是合併語意，可 deny | 不是 Codex 的替換 JSON、也不是統一 `spawn_agent`。一般 task arguments 能否動態決定每次 agent model **unverified**；不能只塞 `model` field 假稱成功。reasoning 不套用 Codex effort。接頭尚未支援。 |

來源：[Claude hooks](https://code.claude.com/docs/en/hooks)、[Claude subagents](https://code.claude.com/docs/en/sub-agents)、[Gemini hooks](https://geminicli.com/docs/hooks/reference/)、[Gemini subagents](https://geminicli.com/docs/core/subagents/)。Gemini 本機 bundled docs 的 agent model schema 見 `bundle/docs/core/subagents.md:356–372,509–530`。目前只有版本／文件盤點，沒有對兩家發 credentialed requests、啟動 agent 或更改設定。型號示例不是帳號可用 catalog。

## Canopy 選配背景與 Monitor

這部分由獨立唯讀 `lean_explorer`（tool metadata 選擇 Luna/Max；沒有獨立 provider receipt）做 source map，B 整合。不是另一個 executor chat，沒有修改既有專案。

Canopy 的正式投影包括 `observe snapshot`, `observe evolution`, `observe activity --json`，見 `extensions/canopy_observatory/README.md:3`, `README.md:213`。Activity 契約 `canopy.observation.activity` schema 6 是有界活動／統計投影（`scripts/observe_activity.py:36,1010,1079`），明確排除 raw prompt/Seed/hidden reasoning，**不是第三方 routing background export**。

目前 working tree 的 snapshot schema 9（`scripts/observe_snapshot.py:47,2305`）可能包含卡片 summary/source summary/triggers、root 路徑（`1039–1079,2315–2318,2356–2362`）。本輪只讀程式，沒有執行 snapshot 或接觸記憶內容。不可把整個 snapshot 發到 Jev。新專案只保留背景摘要介面、來源與允許外送的顯式邊界；沒有已確認適合自動外送的正式契約，**live integration unverified，預設 absent**。Canopy 故障不能影響獨立分級。

Monitor 是 loopback API＋Python entry＋自身 ledger projection；`README.md:47`, `docs/api-contract.md:33,224`, `backend/monitor/app.py:151,201`。Public producer events 不能宣稱 official effect/acceptance。Telemetry 的 `agent_dispatch`/`agent_result` 限 producer `model_reported`（`backend/monitor/telemetry.py:12`, `docs/portable-entry.md:161`）；不是任意 route-stat import。`imports.py:16` 要 task snapshot v1，不能拿來塞 harness 統計。`docs/architecture.md:154` 的自動登錄等仍在施工。

因此 **Monitor route-stat ingestion 未驗證／未串接**。建議 harness 自己提供版本化 structured JSON 查詢與合成例，供 Monitor 原 owner 後續接入；不新增 daemon、不寫 Monitor DB、不用 refresh 增加計數、不將模型要求與採用混算。本輪未啟動 Monitor 服務或讀取 DB。

## C2C 與 Jev 來源缺口

根 `/Users/shawn/Code/.c2cignore` 明列 Canopy 與 Meld 有限路徑。用既有 `Codex with ChatGPT · Code` read_file 實測：`Canopy/AGENTS.md` lines 1–3 可讀；`model-routing-harness/REQUIREMENTS.md`, `adaptive-agent-workbench/README.md`, `Canopy-Task-Monitor/AGENTS.md` 都回 `ACCESS_DENIED_SENSITIVE_FILE`。這是白名單限制，不是專案不存在；沒有更換 connector/tunnel 或繞過拒讀。

原 GPT「分級器開發」`6ac87fe7-da4c-83ec-8081-19b331292214` 已唯讀取得 5 段近期對話（工具 `hasMore=false`）；MRH-001 正式基準來自 turn `4b09d4a4-9634-46cf-aa4e-c6598b1fe349`。這次讀回沒有 Facebook 原文 URL、圖片 pixels、Jev 官方網址、供應商、endpoint、authentication、response schema、價目或 source code。對話裡的 content-reference placeholders 也不是可追溯的官方 API 契約。

**Jev protocol = unverified / implementation unavailable pending source。** Light/Small/Mid/Top 與 0.5 政策來自 R1，不是已核對的服務 JSON 格式。不能猜成 Gemini、Groq、OpenAI-compatible endpoint 或任意便宜模型；不能把過往 GPT 建議的 MCP 派工改造帶進本範圍。A 保留原 GPT 設計對焦發送責任。

## E1 pass/fail 與停止

E1 完成的是決定接頭設計的有界盤點：每個必查能力已有狀態、來源與限制；兩版本合成 contract probe 可重現；已知 probe 修正與錯誤保留。沒有把 generic deny、configured model、繼承 child、schema 或 isolated config 冒充完整 routing。

S1 的 Jev 原始契約與 real host adoption 缺口由 A 裁決後續方法；S2–S6 未執行／未接受。到達 E1 指定 return condition，B 不啟動未派的設計實作。未建立正式完成百分比、native Goal、Monitor snapshot 或第二套進度系統。
