# E19：Codex 訂閱分級器候選

新 profile 的分級來源是 `codex_subscription`，固定使用 `gpt-6-luna / low`，沿用官方 CLI 的 ChatGPT 訂閱登入，不要求 API key。子代理的四級模型、推理強度、Main／Fixed 選單沿用已接受的 E17R 設計。分級器已實作；目前這台機器的真實分級仍有下述隔離限制，不能稱已啟用或完成 R1。

## 現在可操作的入口

獨立候選位於 `dist/model-routing-harness-0.3.0-e19-macos-arm64/mrh`；內含既有 pin 的私人 Python，不需另外安裝 SDK、Python 或橋接服務。

```sh
MRH_E19_ENTRY=/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.3.0-e19-macos-arm64/mrh
"$MRH_E19_ENTRY" --help
"$MRH_E19_ENTRY" model light
"$MRH_E19_ENTRY" settings show --path /absolute/owned-profile/settings.json
"$MRH_E19_ENTRY" stats --settings /absolute/owned-profile/settings.json --details
```

選 AI、子模型、推理強度到 Save 的入口仍是 `model`。以上 `/absolute/owned-profile` 須換成同一選單綁定的實際 profile；不能另外建立設定後誤認為同一份。新建 profile 仍 disabled、task 外送 denied、工作區清單空白，分級逾時預設 20 秒；舊 profile 的 provider、逾時、映射、權限及歷史均不自動轉換。

若操作者明確要把既有 profile 改用訂閱，原 CAS 介面會一起保存 provider 與其固定分級器模型，不更動其他欄位，也不啟用 Hook：

```sh
"$MRH_E19_ENTRY" settings configure --path /absolute/owned-profile/settings.json --provider codex_subscription --expected-revision <current_revision>
```

保留 `--provider typesafe` 給原來明確使用 TypeSafe 的 profile；沒有 provider fallback。畫面會分別標示分級來源／分級器模型與四級子代理設定。

## 官方程序與輸入限制

使用未修改的 `codex-cli 0.159.3`，binary SHA256 `4d210f7c5a18fd0386434df23b5bdbb8c0e7257d3e8a2b30b0769c8bbe99a878`。先沿用既有 CLI 發現或已核驗 scope binding 的 binary，再檢查相同 pin／version；不替換安裝、更新 Codex 或切換模型。程序在自有空目錄執行，使用 stdin 任務 JSON、固定 `mrh-tier-v1` rubric、`--json --output-schema --ephemeral --ignore-user-config --sandbox read-only`。schema 只准 `tier` 與有限的 0..1 `confidence`。

官方 [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)說明 exec 的 JSON、schema、ephemeral 和沿用登入；[Authentication](https://learn.chatgpt.com/docs/auth)區分 ChatGPT 訂閱與 API key。固定版 `exec --help` 另明示忽略 user config 後 auth 仍使用 `CODEX_HOME`。

環境採白名單：只給登入所需的原 `CODEX_HOME`、自有空 `HOME`、基本 PATH／語系和自有暫存／SQLite 位置；不傳入 API key、parent thread、proxy／provider endpoint 或其他宿主環境。MRH 不讀 auth.json、keychain 或私人 session；登入／token refresh 由官方 CLI 負責。模型呼叫前使用同一環境的公開 `codex --no-daemon login status`，只接受 ChatGPT 狀態，另以 `forced_login_method="chatgpt"` 拒用 API 登入。PATH alias 的固定警告不改變登入判斷；其他未知狀態拒用。

套件控制會停用 hooks、plugins、apps、shell、multi-agent、code-mode、browser、computer-use、view-image、image-generation、memories、goals、sleep、tool-suggest 和 workspace-dependencies；停用 project instructions、skills 注入、plan／request-input 和 web search。沒有 `--ignore-rules`、approval／sandbox／trust bypass 或修改管理員限制。這些控制在本輪的原版官方程序中，搭配未修改的公開 pin catalog 及自有 loopback 回答，實際產生 `tools=[]`；不是只靠 prompt 要求不用工具。實際帳戶／remote catalog 的行為仍未做真模型驗收。

原委派任務與已允許的可選摘要才會進 stdin，不傳 repo、parent transcript、檔案內容或憑證。私有 recursion sentinel 只令 MRH 自己在 settings／DB／model 工作前回傳中立結果。明示子模型、明示 effort、特殊角色、disabled、export denied 和非授權 workspace 仍在模型程序前略過。一般失敗沿既有去重警告保留原委派，D23 的操作者停止政策維持獨立。

GuardedAttempts 同時管理逾時與本機程序群取消：先封住新啟動，再終止並收回自有程序；stdout／stderr 各有上限，沒有 adapter retry、替代模型或 provider。官方內部 provider 重試次數仍未知，故統計計算 **CLI invocation**，不稱單一 HTTP request。晚到結果不能路由。

## 已證實的隔離阻礙

原版 CLI 的 `CodexHomeUserInstructionsProvider` 另外讀取 `CODEX_HOME/AGENTS.override.md`、`AGENTS.md`，不受 `--ignore-user-config` 或 `project_doc_max_bytes=0` 排除。[官方固定版來源](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/codex-home/src/instructions/mod.rs)及[程序證據](evidence/e19-isolation.json)支持這一點：自有全域 canary 進入了 request；移除這個自有 canary 後，同一 invocation 的另一個 request 沒有 home／project／config canary 或 workspace path，工具也為空。

本機目前登入 home 確實有 AGENTS；僅查存在性，沒有讀內容。相同乾淨環境下，官方 public status 確認為 ChatGPT；全新自有 home 的 public status 則是 `Not logged in`。[登入邊界](evidence/e19-auth-boundary.json)。產品因此在任何 auth／模型子程序前，以 `codex_subscription_home_instructions` 保留原委派並請求顯示固定警告。

本輪沒有刪除、遮蔽或修改正式 AGENTS，沒有複製登入資料，也沒有換 API key 路徑。可供 A 判定的同 Hook 方案是：只對自有驗收 home 走官方 ChatGPT 登入，再沿既有 owned-workspace prepare／register／trust；這需要新登入動作，不能假定原授權已涵蓋，也沒有在本輪執行。不是要求使用者刪除原有保護。

## 證據與剩餘義務

聚焦證據涵蓋 settings/provider 切換與 CAS、舊 TypeSafe 設定、嚴格解析、self-reported confidence／0.5 guard、程序輸出上限與取消、recursion、API／未知 auth 拒用、PreToolUse 的明示／null 與失敗保留、統計隔離和新版 bundle 入口。訂閱 attempts、官方 CLI 已知 usage、configured model 分開統計；未取得 provider-confirmed model identity，不填 response model、Jev 美元價或訂閱成本。既有 JSON 欄位保留；synthetic 與 live 分區保留。

[51 項不同聚焦檢查](evidence/e19-focused.json)通過；兩個 scripted Responses 的原版程序隔離檢查耗時 0.749 秒。獨立入口檢查耗時 5.607 秒，核對 37 個 application source records、33 個 Python modules 與全部 2,059 個 manifest records；驗證 provider 切換保留舊歷史／政策／權限、disabled Hook 零 DB、recursion 中立及實際 bundled adapter 的全域指令 guard。入口執行後 manifest 未變，自有暫存 root 已刪除。[入口證據](evidence/e19-bundle-entry.json)。

套件 source commit 為 `eedd8254f5a04f5c6b78b2e3268e10b6acf3221a`；archive SHA256 `7706742578a0297f9f2404fa8cd048e98a5411dc669adccdaa7eeae8805bdaea`，manifest SHA256 `c9894bd595ce30b457e5e347a7c5c7ea351fb49a38d3d12d4fc8add1bba5f53e`。[建置紀錄](evidence/e19-build.json)。沿用原固定 cache／CPython 3.11.17 及 19 項 notices，只建置這一份新 bundle，保留先前已接受候選。

真實分級呼叫 **0**、真實驗收 turns **0**，已授權最多三次的額度未使用。没有正式 global registration／trust／export／enable；E17R 受測 native scope、原參數保留、Main／Fixed／null 和 D23 證據沿用。此輪 loopback 使用腳本回答，不能稱訂閱模型成功。

後續真實步驟沿 [E18 準備](e18-live-acceptance-plan.md)的任務與 public `thread/read` configured-model／child-result 證據，但 **撤回其中 TypeSafe key 輸入、TypeSafe provider 設定和 Jev-only 驗收步驟**，改用本頁的 subscription provider／20 秒新 profile。先有可隔離的官方訂閱登入，再做第一次 literal classification；其後才進支持的 Hook/native child 路徑。V2 的空 legacy receiver list 不能當作沒有子代理。Top Main 只有模型實際給出 confident Top 才驗，不操控分類結果。Top Fixed、Goal、未命中的 Top Main、真子模型與主代理完成及完整 R1 仍保留，沒有用本候選或局部證據結案。
