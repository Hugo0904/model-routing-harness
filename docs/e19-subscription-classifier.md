# E19：Codex 訂閱分級器與真實驗收

新 profile 的分級來源是 `codex_subscription`，固定使用 `gpt-6-luna / low`，使用官方 CLI 的 ChatGPT 訂閱登入，不要求 API key。D44 的三次分級與兩個子任務之後，D45 已在第一回 ordinary native turn 實際切換到 gpt-5.6-luna／low，child 與原 parent 都完成排序；公開原生鏈由 A 獨立確認。D48 另完成 Luna parent 的真 Top Main blocked／no-child／同 parent 答案。Hook 原始 message 的舊診斷捕捉仍缺失。子代理的四級模型、推理強度、Main／Fixed 選單沿用已接受的 E17R 設計。這次只驗自有 CLI 環境；MRH 已 disabled／export denied，臨時 observer 已撤回，同一登入／home／workspace／state／parent-child sessions／pointer 保留到 A 驗收整體成果。原正式 home 的全域指令限制與完整 R1 仍保留。

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


## D45 的實際普通切換與保留環境

同一 root `/private/tmp/mrh-e19-d45-mrc5zw54` 沿用未改的 E19 bundle／adapter、官方 0.159.3 與原 public comparator。逾時登入只在該 home 重開一次；本人完成後 official public status 為 ChatGPT／exit 0，未重建 root、複製憑證或改正式登入。[準備](evidence/e19-d45-setup.json)、[public auth](evidence/e19-d45-auth.json)、[官方 trust](evidence/e19-d45-trust.json)。先前 login-pending 檔為歷史 snapshot，現況以 auth／retained-session 為準。

第一回 ordinary native turn 的分類是 **Small／0.99**，MRH 請求 `gpt-5.6-luna／low`。公開 PreToolUse call ID 與 V2 `subAgentActivity.id` 相同，再對上 `agentThreadId`、child 的 `parentThreadId`。在 child **active** 時 public `thread/read` 核得 `gpt-5.6-luna／low／openai`；child 與同一 parent 都 completed 並回 `[1, 2, 3]`。parent 前後保持 `gpt-6.1-sol／low`。這證明該次 configured model 切換及執行結果，不證明 provider 後端 inference identity 或一般分級可靠度。[原生鏈](evidence/e19-d45-ordinary-1.json)、[結果](evidence/e19-d45-result.json)。A 已獨立確認這條公開鏈足以驗收本次普通切換，不需要第二回。

本批只用了 **1 次 classifier CLI invocation／1 次 native user turn**，保留前批 3 次，共 4 次；未做第二回、未改模型／prompt／0.5 或其他保護，也未重建 bundle／重跑有效檢查。classifier public CLI usage 為 2,229 input／21 output；parent public final total 為 45,342 input／85 output，child 為 17,239 input／27 output（其中 reasoning output 12，已含在 output 中）。本回已知三者合計 64,943 tokens；費用與實際節省仍未知，CLI invocation 不等於 HTTP request 數。[統計](evidence/e19-d45-stats.json)。

臨時 observer 的五個 inert 案例保持 `{}`、零模型／網路，原 MRH launcher／runtime／binding hash 不變；固定版官方 handlers 並行，因此 observer 不是 pre-inference barrier／deny gate。本回 observer 實際回報 `out_of_scope`，未保存原始 message；native run 的 `bounded_original_input_not_verified` 保留，不以 parent prompt 或 child 答案重建文字。[中立檢查](evidence/e19-d45-observer-inert.json)。曾補讀自有私有 rollout 做 metadata 診斷，這不符合本次指定公開來源；已停止，不列為公開輸入或切換驗收證據，只保存已發生的來源事實。[來源紀錄](evidence/e19-d45-observer-gap.json)。Hook 原始輸入缺口仍未知。

已以官方介面移除 observer plugin／marketplace，`hooks/list` 讀回只剩原兩個 MRH Hook。相同 settings 已 disabled／export denied，仍只綁原 owned workspace；native 驗收與讀回程序均 exit 0。public login status 仍為 ChatGPT，沒有 logout／home 刪除。保留 home、workspace、state、原 parent／child sessions 與 ignored pointer `/Users/shawn/Code/model-routing-harness/build/e19-d45-pointer.json`，直到整體使用者成果由 A 驗收；回報或單批完成都不觸發登入清理。[同目標讀回及保留](evidence/e19-d45-retained-session.json)。

本次普通切換完成；Top Main／Fixed、Goal、正式採用與完整 R1 保留為原剩餘義務，沒有被本次結果豁免。原始輸入診斷另列，未拿未授權來源填補，也未為此再消耗呼叫。A 負責整體驗收與原範圍後續安排。


## D47：剩餘政策、同 Goal 與實際啟用入口

沿用同一登入／home／workspace／state、原 E19 套件與有效證據，沒有重做 ordinary sorting、menu matrix、isolation 或全套測試。正常規劃是兩個 Goal/Main 回合及一個 Fixed 回合；另做一次已理解的 driver/readback 補驗，實際 **4 次 classifier／4 個 native turn**，以前 4 次保留，全部批次共 8 次。[結果與用量](evidence/e19-d47-result.json)、[live stats](evidence/e19-d47-stats.json)。classifier 本批已知 9,374 input／84 output；公開 native final totals 依 thread 保存，Goal parent 跨回合累計只取最後一筆，沒有重複加總。費用／節省未知。

| 本次回合 | 真實分類及路由 | 實際結果／接受界線 |
|---|---|---|
| 同 Goal 的跨系統 inventory/payment/shipping 設計 | Mid／0.18；low_confidence 保留 | child 與同 Sol6.1 parent 完成設計；未命中 Main |
| 同 Goal 的 lease-expiry/reallocation/shipping-ack failure analysis | Small／0.39；low_confidence 保留 | fresh call／proposal／classifier 與實質答案；未命中 Main |
| Luna parent 的 Top Fixed 設計 | Top／0.98；top_fixed_requested | child configured Sol6.1／low，child 與同 Luna parent 完成；same loaded readback 為 idle，沒有 active 目標 snapshot |
| 單次 legacy-readback 修正觀測 | Mid／0.99；cost_unknown 保留 | driver 可從 legacy receiver ID 捕捉 active child；本回是 Luna／low，不能拿來補前一回 Sol 的 active 證據 |

同一新建原生 Goal `01a12c0d-f94f-7a11-93fc-f85fce184ae2` 的 thread／createdAt／objective 在 before、between 與 after 保持相同，兩個實際 turn／call／proposal 不同、各有一次 fresh 訂閱分級。兩個工作完成後，原生 Goal 自行標 complete。driver 原本只接受 active，修正讀回判斷後，經 public RPC 確認同 Goal complete 並 clear／get=null，**沒有重跑模型**。這是 harness 明確開始兩回合的真訂閱 Goal 證據，未證自主排程。[Goal 原生鏈](evidence/e19-d47-goal-main.json)、[同 Goal 關閉讀回](evidence/e19-d47-goal-close.json)。

Fixed 首回的 proposal call ID 與公開 legacy collabAgentToolCall ID／receiver UUID 一致，public model／effort、child-parent 關聯、child 和 parent completed 都保存。driver 只在 V2 subAgentActivity 做即時讀回，漏了此回 legacy child identity；因此首回只保留同 process 中 loaded-idle metadata，未改稱 active。D47 允許的單次 readback 修正支援兩種原生 identity，初始化 metadata probe 最多三次。補驗雖真正捕捉 active，分類沒有再命中 Top，故不拼接兩回成一個完整成功、不再抽樣。[首次 Fixed](evidence/e19-d47-fixed.json)、[修正界線](evidence/e19-d47-fixed-readback-repair-setup.json)、[單次補驗](evidence/e19-d47-fixed-active-repair.json)。Main 真 Top deny／same-parent handback 與嚴格的 Fixed active 目標鏈仍未完成，交 A 按真結果裁決，未改 rubric／confidence／0.5 或注入答案。

驗收用 model／effort 和 Top policy 已透過 owned config／CAS 恢復原值，再 prepare／官方 plugin refresh／核對 cache 和原兩個 Hook trust。MRH disabled／export denied，parent 原設定 Sol6.1／low、Top Main、普通 mappings／rates／history 不變。same-home public status 仍 ChatGPT；全部 native 驗收／讀回程序結束，Goal 已 clear；沒有 logout、原正式 home 更動、observer 重裝、私有 rollout 診斷或 bundle 重建。原及新 thread refs／pointer／home／workspace／state 保留到 A 驗收整體成果。[最後同目標讀回](evidence/e19-d47-restored-session.json)。B 有效 model／effort 不能由公開 read_thread 取得，僅保留 A 的請求設定，不宣稱該 metadata 已驗證。

模型選單已透過真正 CLI 把 `$MRH_ROOT/model-bindings` 關聯同一 `$MRH_ROOT/state/settings.json`，避免另一份 profile。初始關聯程序在綁定後取消等待逾時，已終止 owned process、沒有 Save；後續 shipped Registry/profile consumer 核對同 settings／pin／版本，原政策已恢復。[關聯及讀回](evidence/e19-d47-profile-association.json)。

實際操作見 [啟用與停用指令](quickstart.md)：獨立入口、明確同 profile、模型選單、export／enable、官方 `--no-daemon -C` 互動啟動、disable／deny-export／status／stats，以及另選 workspace 的 scope reprepare 說明。shipped parser 的 11 個指令、真 profile reader、startup allowlist、文件 shell 定義與實際 readonly settings／public auth consumer 已核對，沒有再呼叫模型或替其他 workspace 啟用。archive／manifest／application hash 不變。[操作指令驗證](evidence/e19-d47-operator-commands.json)。

這是 pinned local CLI 的已觀察與可操作範圍；原未知 Hook input、Main、Fixed active 目標讀回、Desktop／正式 global adoption、自主 Goal 排程與完整 R1 維持原分母／未完成，不把此單位稱整個任務完成。


## D48：Fixed／Goal 接受與 Luna Main 完成

A 的 D48／`b937dc0` 正式接受 D47 的 Goal fresh classification／fulfilled lifecycle、同環境恢復與操作指令，以及 **第一回** Fixed 的同 call configured Sol6.1／low child／結果。公開 started／completed collabAgentToolCall 明列 model／effort，對上真 Top/0.98 proposal／receiver child，再對上同仍運行 process 的 loaded-idle metadata、child/wait 答案和原 Luna parent 完成；原 configured-model/result 要求已滿足。A 撤回其額外的 active-only 時間點要求。歷史 idle、修正 run Mid/0.99 與第四次呼叫照實保留，不改舊 evidence、不拼接不同回合或升格 provider-confirmed。

D48 只做一個尚缺的 Luna Main 回合，同 root/auth/pointer/bundle，以首次 Fixed 的公開 prompt 為來源，請 parent 逐字一次 generic 委派，沒有模型／effort／tier／confidence 注入，也沒有新 Goal。executor metadata-only helper 核得這次 B 的 exact turn `01a12c42-614e-7c81-9719-5aae53b47904` 為 `gpt-6.1-sol/xhigh`；這只確認 executor 設定，不代替原生驗收證據。[準備與公開 task 來源](evidence/e19-d48-preflight.json)。

真分級為 **Top／0.99**，proposal action `return_to_main`、reason `top_main_requested`。public PreToolUse completed 的同 call `exec-f79f60c2-231a-4178-a4de-a2970596196b` 明確為 **blocked**，feedback 指明該委派未執行、應在同 parent 完成且不得另派。沒有 child、沒有替代委派，parent `01a12c4d-8d0e-76a3-b93d-e44f58200b76` completed 實質 inventory/payment/shipping 設計答案；前後仍是 `gpt-5.6-luna／low`。因此也觀察到 Luna 作為 Main 時，Top 工作直接回到該 Luna parent，不偷偷切換主模型。[公開原生鏈](evidence/e19-d48-main-luna.json)、[同 call 收整](evidence/e19-d48-result.json)。

本回觀察 15.682 秒，唯一一個 classifier CLI invocation／native turn；全批次累計 **9** 個 classifier invocations，沒有重跑已接受 ordinary／Fixed／Goal／UI／isolation。classifier CLI usage 為 2,180 input／21 output；public parent final total 為 68,284 input／571 output（reasoning output 89 已含 output）。backend inference identity、實際費用／節省保持未知。[統計](evidence/e19-d48-stats.json)。

已停止本次 native process（exit 0）、CAS disable／export-deny，僅把 owned parent model／effort 恢復原 Sol6.1／low；Main policy、其他設定、mappings／rates／history 維持原值。same scope reprepare／official refresh 後 cache integrity 和原兩個 trusted MRH Hook 讀回通過，same-home public status 仍 ChatGPT。沒有 logout／root 重建或刪除／observer／私有驗收 session 讀取／新 Goal／bundle rebuild；原及新 refs、state、home、workspace、model registry 與 pointer 都保留到整體成果驗收。[同目標恢復與保留](evidence/e19-d48-retained-session.json)。

README／[啟用指令](quickstart.md)只更新接受狀態與本回 Main 結果；既有已驗操作指令／command matrix 沿用，不為文字狀態重跑。A 已於 D50 接受這份 Main 證據，受測的 ordinary／Fixed／Main／Goal CLI 鏈已齊。原未知 Hook input 診斷、Desktop／global／正式採用、自主 Goal 排程和完整 R1 分母／界線不變；本頁不自行把整個任務標完成。
