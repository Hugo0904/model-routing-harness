# E16：Gemini 公開 CLI 的離線模型選單

本單元實作 Gemini CLI **0.63.0** 的工具預設模型清單，接入原 discovery／refresh／selector／CAS；沒有 Gemini routing adapter、帳戶 availability、真 provider 或正式 Hook 採用宣稱。A 已親自驗證清單、保存／返回／取消及來源變動時拒絕保存；[A 驗收](evidence/e16-a-acceptance.json) 發現更新後缺少保留原設定的重新確認入口，已交 E16R 修正，尚未接受完整 R2 更新流程。原 R1／R2／R3 整體義務保留。

## 實際公開來源

安裝的 CLI 未提供直接 model-list 子命令；使用官方 [ACP stdio 模式](https://geminicli.com/docs/cli/acp-mode/)。實際只發 JSON-RPC `initialize` 與新 `session/new`，不 authenticate／load 舊 session／prompt／user message。原始 [對照實測](evidence/e16-acp-probe.json) 顯示：沒有 key 時，new session 回 `-32000` 缺少 key；只在拒絕外連的隔離子程序放入固定無效、非 secret placeholder 後，CLI 回傳完整 `models.availableModels`。這是本機 presence-check 後產生的工具預設，沒有證明伺服器認證或登入成功，也沒有攔截／假造任何 provider 回應。

實際清單為 6 個選項。保留 `auto` alias；`gemini-3.1-pro-preview-customtools` 的 label 雖為 `gemini-3.1-pro-preview`，保存的是原 `modelId`，不以 label 改寫 request ID。其餘 ID、版本與 snapshot 見 [來源實測](evidence/e16-source-catalog.json)。ACP 的 approval modes 不是 reasoning effort；這一版本沒有回模型專屬 effort enum，因此只提供 inherit，不借用 thinking budget 或其他字串。

Parser 要求對應 integer request ID、JSON-RPC／ACP protocol version、精確 agent 名稱／版本、非空完整 models、唯一安全 modelId、可用 label，以及 current model 確實在清單中。錯誤、partial、duplicate、未知欄位／effort、未知 version 或 callback 不轉成假 availability／retirement，只有固定安全原因碼。

## 身分與隔離

Gemini 是既有 npm CLI，Node 仍是所選 CLI 的 prerequisite，沒有把 Node／SDK 安裝要求加給 MRH。只辨識已檢查的 npm package name/bin/layout 與其既有 prefix Node；不尋找／下載任意 runtime。Gemini binding 的 `executable_sha256` 是整個公開 npm payload、相對 symlink identity 與 Node bytes 的 composite digest，其他 CLI 仍用原 executable hash。不能只靠入口 stub 不變而沿用舊 snapshot；refresh 前後與保存前均重新核對。

在 fresh owned HOME／cwd／TMP 中，複製既有公開 CLI／Node payload，核對 copied bytes，保留原 E12R／Claude profile 的 deny-default、deny-/Users、deny-keychain program／Mach lookup、deny-network 與 owned-only writes。這讓 npm 套件位於使用者的 `.nvm` 時也能運作，且不放寬真 home 的讀取。Env allowlist 不轉送真 API key／OAuth／Google account；placeholder 只存在這個離線子程序。Fresh public settings 關閉 auto-update、hooks、telemetry、auto-memory，MCP 空白，沒有使用者 extensions。新 workspace 未被信任，也不 skip trust／執行 project agents。

[實際 copied-Node canaries](evidence/e16-isolation.json) 均拒絕：假私人檔讀取、owned root 外寫入、`security help` 程式執行與 loopback connect；沒有查詢真正 keychain 項目。原始 probe 兩個 groups、實作中的 public ACP process tree 和 entry verification 都在受控生命週期收尾。Timeout／錯誤仍清理自有 group；若 group 無法確認消失，保留 owned files 並回固定 cleanup failure，不能把刪資料夾當成程序已退出。

## 操作與檢查

[實際 bundled entry](evidence/e16-bundled-entry.json) 在 fresh owned HOME／cwd、PATH 沒有額外 Python／Node alias、外部 MRH developer source不進入 import path的環境，從新候選包操作 Gemini。所需 Node 來自已安裝 CLI 的副本。實際 24×56 PTY 用方向鍵／Enter：選 Gemini → 選 model → effort 回 model → save 回 effort → 保存 `gemini-3.1-pro-preview-customtools`／inherit 到 revision 1。再次選別的 model 並取消，policy 及實際 SQLite/key/lock history bytes 相同。Enabled/export false、workspaces empty、proposals/Jev attempts 0。

只改自有 CLI 副本的一份 public chunk，入口 stub 不變；下次 refresh 偵測 composite digest 改變，顯示 `tool_changed_rebind_required`／唯讀舊清單／Retry-Back-Cancel，以方向鍵 Enter 取消，policy 不變。真 vendor installation 未改。[終端文字](evidence/e16-save-back.txt)、[取消](evidence/e16-cancel.txt) 與 [失敗取消](evidence/e16-failure-cancel.txt) 是實際 PTY 文字，僅移除 ANSI CSI 與行尾 padding，不是 screenshot。

受影響 checks：Gemini protocol／package identity／CAS，加原 selector 與 D23，共 **39 tests** 通過，精確結果見 [驗證](evidence/e16-verification.json)。第一輪 fixture 複製 macOS system `true` 的 restricted flags 被 sandbox 拒絕，改成只複製測試 bytes/mode；沒有改 production 允許條件。Entry harness 首輪缺 `struct` import，修正並把 PTY sizing 納入 cleanup 範圍；該輪不能算驗收，精確自有 argv 的宿主查詢無殘留，後續同隔離實測通過。沒有 startup-only 結案或削弱內層限制。

## Standalone 候選與範圍

新的候選留在 ignored `dist/model-routing-harness-0.3.0-e16-macos-arm64`，同名 `.tar.gz` 及 manifest/hash 給 A 本人操作。使用原 pin CPython **3.11.17**／release **20261009** cache、19 notices 與 E15 packager；沒有新公開下載或覆蓋 E15 候選。具體 artifact／source identity 見 [建置](evidence/e16-build.json)、[來源](evidence/e16-source-identity.json)、[清理](evidence/e16-cleanup.json)。

原 core／四級／Main／Jev／D23／notification semantics 未改；Codex／Claude 未改的邊界沿既有證據，只有共用 dispatcher/save identity 的直接 consumer checks。沒有重跑 E13/E14 full suites、native host build 或 OS matrix。macOS arm64 本機候選、installed Gemini 0.63.0／既有 Node 20.19.4 才是已驗範圍；沒有 account-confirmed catalog、真正模型/provider執行、跨 vendor runtime routing 或正式發布／signing／notarization／Gatekeeper bypass。

A 可從新候選的 `mrh model` 在 fresh profile 本人操作；舊 binding 遇 npm/Node update 需明確 rebind，不能自動沿用其 cache。問題依原授權直接交 B 修正，無需人類逐階段確認。Monitor context 仍 tasks=[]／缺 native user identity，已選 none，沒有替代 request/task/Goal；額度低於 7% 的原保存暫停規則不變。
