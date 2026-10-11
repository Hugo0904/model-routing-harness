# E19：Codex 訂閱分級器與真實驗收

新 profile 的分級來源是 `codex_subscription`，固定使用 `gpt-6-luna / low`，使用官方 CLI 的 ChatGPT 訂閱登入，不要求 API key。D44 後已完成三次真實分級與兩個原生子任務；兩次 Hook 分級都低於 0.5，保留原委派，尚未驗到便宜模型改寫。子代理的四級模型、推理強度、Main／Fixed 選單沿用已接受的 E17R 設計。這次只驗自有 CLI 環境，已撤回；原正式 home 的全域指令限制與完整 R1 仍保留。

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

原正式登入 home 確實有 AGENTS；僅查存在性，沒有讀內容。D44 前相同乾淨環境下，官方 public status 確認原 home 為 ChatGPT；當時全新自有 home 的 public status 是 `Not logged in`。[登入邊界](evidence/e19-auth-boundary.json)。這個原 home 的產品 guard 仍會在任何 auth／模型子程序前，以 `codex_subscription_home_instructions` 保留原委派並請求顯示固定警告。

D44 已由 A 裁決，在同一自有空驗收環境以官方 browser login 使用同帳號；本人完成登入後，public status 確認 ChatGPT。登入／status／parent 明確使用 file store，classifier 沿 pin 的同一預設 file store。沒有刪除、遮蔽或修改正式 AGENTS，沒有複製登入資料，也沒有換 API key 路徑。僅該工作區的 MRH 曾 prepare／register／trust／export／enable，驗收後均已撤回。

## 證據與剩餘義務

聚焦證據涵蓋 settings/provider 切換與 CAS、舊 TypeSafe 設定、嚴格解析、self-reported confidence／0.5 guard、程序輸出上限與取消、recursion、API／未知 auth 拒用、PreToolUse 的明示／null 與失敗保留、統計隔離和新版 bundle 入口。訂閱 attempts、官方 CLI 已知 usage、configured model 分開統計；未取得 provider-confirmed model identity，不填 response model、Jev 美元價或訂閱成本。既有 JSON 欄位保留；synthetic 與 live 分區保留。

[51 項不同聚焦檢查](evidence/e19-focused.json)通過；兩個 scripted Responses 的原版程序隔離檢查耗時 0.749 秒。獨立入口檢查耗時 5.607 秒，核對 37 個 application source records、33 個 Python modules 與全部 2,059 個 manifest records；驗證 provider 切換保留舊歷史／政策／權限、disabled Hook 零 DB、recursion 中立及實際 bundled adapter 的全域指令 guard。入口執行後 manifest 未變，自有暫存 root 已刪除。[入口證據](evidence/e19-bundle-entry.json)。

套件 source commit 為 `eedd8254f5a04f5c6b78b2e3268e10b6acf3221a`；archive SHA256 `7706742578a0297f9f2404fa8cd048e98a5411dc669adccdaa7eeae8805bdaea`，manifest SHA256 `c9894bd595ce30b457e5e347a7c5c7ea351fb49a38d3d12d4fc8add1bba5f53e`。[建置紀錄](evidence/e19-build.json)。沿用原固定 cache／CPython 3.11.17 及 19 項 notices，只建置這一份新 bundle，保留先前已接受候選。

上面的 E19 初版 isolation／bundle 證據沒有真實模型呼叫；D44 後的真實證據另列下方。E17R 受測 native scope、原參數保留、Main／Fixed／null 和 D23 證據沿用，沒有重跑舊 gate 或重建未變 bundle。

本次沿 [E18 準備](e18-live-acceptance-plan.md)的任務與 public `thread/read` configured-model／child-result 證據，但 **撤回其中 TypeSafe key 輸入、TypeSafe provider 設定和 Jev-only 驗收步驟**，改用本頁的 subscription provider／20 秒新 profile。先做 literal classification，再進支持的 Hook/native child 路徑。沒有操控分類結果、改 0.5、mock、facts injection 或 provider/model fallback。

## D44 後的真實結果

唯一環境為 `/private/tmp/mrh-e19-live-4p1wkjl9`，新 CODEX_HOME、空 workspace、獨立 MRH state；登入前準備並保持 disabled/export denied，本人登入後才開本次測試權限。正式 home、AGENTS、App 與其他 Hooks 均未改。[準備](evidence/e19-live-setup.json)、[public auth](evidence/e19-live-auth.json)、[官方 MRH trust](evidence/e19-live-trust.json)。

| 操作 | 真實分類 | 路由／結果 | 觀察耗時 |
|---|---|---|---|
| standalone literal 排序分級 | Light／0.99 | 分級成功；這次沒有原生委派 | 5.838 秒 |
| 原生 generic 排序委派 | Mid／0.03 | low_confidence 保留；child、同 parent 都完成 `[1, 2, 3]` | 22.485 秒 |
| 原生 generic reservation tradeoff 委派 | Mid／0.18 | low_confidence 保留；child、同 parent 都完成假設協定 | 31.336 秒 |

三次分級均透過官方訂閱程序 returned，沒有使用 API key。standalone CLI usage 為 2,100 input／21 output；MRH live stats 的兩次 Hook classifier usage 為 4,689 input／42 output。合計這三個 **classifier** invocations 為 6,789 input／63 output；parent／child 用量與總帳單未保存／未知，不能把這個數字當全部模型費用。CLI invocations 不等於 HTTP request 數，requested `gpt-6-luna` 不等於已證 provider inference identity。[首分級](evidence/e19-live-classification.json)、[live stats](evidence/e19-live-stats.json)。

V2 的公開 `subAgentActivity.agentThreadId` 提供實際 child ID；空 legacy `receiverThreadIds` 並不代表沒有 child。讀回同 parent 關聯、`modelProvider=openai`、有效設定及原生結果。[排序](evidence/e19-live-ordinary.json)的 child `gpt-6.1-sol / low` 只在舊 native process 關閉後讀到 latest persisted；不稱 current loaded。讀取方式已在同一驗收單位修正，沒有重跑該付費任務。[tradeoff](evidence/e19-live-tradeoff.json)在 child active 時透過 public `thread/read` 確認 `gpt-6.1-sol / low`，完成後仍為同設定，對上 child 的實際 agentMessage／completed turn，再對上原 parent 最終答案／completed turn。兩個 parent 前後仍為 Sol6.1/low。MRH Post receipts 仍只是 reported=2、confirmed=0，沒有把外部 native 證據倒灌為 provider-observed model。

兩次 Hook 分級低信心是實際模型自報結果，不是解析或網路失敗；沒有把 standalone 0.99 注入到另一個委派，也沒有降低門檻。故真 subscription classifier、真子代理與同 parent 完成已觀測；**普通便宜模型改寫尚未觀測**。Top Main 未命中，Top Fixed、Goal、原 home／App 正式採用、完整 R1 仍未完成。已達原最多三次 classifier 呼叫上限，沒有新增第四次或隱藏重試；native user turns 使用兩次。

同環境完成 disable、export denied、workspace 清空，官方 plugin／marketplace remove 後 list 讀回均無 MRH；官方明確 file-store logout 後 public status 為 `Not logged in`。自有 native processes 已結束，僅本次有 marker 的 root 已刪除；去敏證據保留，正式登入未清理。[撤回讀回](evidence/e19-live-cleanup.json)。沒有為 closure 重跑 51 項有效檢查、E17R 或重建 bundle。
