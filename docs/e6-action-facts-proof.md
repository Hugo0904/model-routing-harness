# E6：各路由分支的事實資格與宿主契約缺口

0.3.0 的政策修正已實作：Main／Fixed 不再被不相關的 parent effort 或原成本未知擋住。這以明確 synthetic 的最小快照驗證；正式 resolver 尚無建立必要事實的公開契約，因此正式 Main／Fixed／一般路由仍未支援，完整 R1 未完成。原始需求與目前總表在 [REQUIREMENTS](../REQUIREMENTS.md)。

## 內部契約與效果邊界

`facts.py` 的 frozen `HostSnapshot`／`Fact`／`TargetFacts` 是 MRH 內部介面，綁 platform／session／turn／call 及 synthetic partition。每個欄位有 known／unknown、immutable value、bounded source，known 必須在同 scope；source 名稱本身不驗證。Malformed／foreign snapshot 保留且記固定 reason，不把 raw snapshot 存進 DB。Settings、task、tool_input 不可宣告關鍵能力 known。舊 dictionary 只在明確 synthetic proposal 中經隔離轉接；configuration_known 已不影響政策，缺 deny 也不補成可用。

| 分支 | 必要事實 | 可保持未知 |
|---|---|---|
| Main | role 未受 model／effort 保護、同次 delegation 可 deny、Main policy | parent／original effort、cost、target、rewrite |
| Fixed | role 未受保護、可 rewrite、valid Fixed preference、target model 及 effective effort 相容 | parent、original baseline、cost |
| Light／Small／Mid | Fixed 的相關 rewrite／target 條件，加 original resolved model／effort 與更低的 conservative sourced rate vector | parent model；不能以它代替原基準 |

顯式 child model 最先保留，零 host resolution／分類；已知角色保護不覆寫，unknown protection 也不能產生效果。原 task 明示的有效 effort 優先，policy 的明示 effort 次之；目標 effort 可以獨立於 parent。需要繼承時，unknown effective effort 保留；已知繼承值只核對、不偷偷強制寫入。Top Fixed 既有成本例外保留。

先計算是否有任一 configured 分支可合法執行；沒有就零 context／classifier／key／HTTP，以 Top 分支 blocker 作 deterministic reason。Top 可行而一般成本未知時可分類；結果若選一般分支仍保留其精確缺口。0.49／0.5、failure／timeout、HMAC／body 隱私、凍結決策／replay／correlated Post 與 evidence partitions 延續。Historical unresolved reason 可繼續讀取，現行 production partial path 使用 `missing_role_protection`。

獨立 reviewer 找到並處理 cached effect 的 P2 反例：service 的 cache hit 曾略過新快照，使已 cached 的 Fixed rewrite 在 protected-effort／foreign-turn replay 仍輸出。現已讓 fresh route 和 cached effect 共用 facts validation／action eligibility。Cache effect 在本次事實無效或 current policy action／patch 與原 intent 不同時 neutral，留 bounded `cached_effect_preserved` diagnostic；不重新分類、讀 key、增 attempt或改寫歷史 decision／stats。公開入口負例先成功 cache Main／Fixed，再以 protected role、foreign turn、缺 deny／unsupported effort 及 Fixed policy effort mismatch 重送，驗 neutral與原 counters不變。

## 已收束的精確版本檢查

既有 shell0.159.3、Desktop-bundled CLI0.162.0-alpha.17.2，各自在 owned temporary HOME／CODEX_HOME 產生官方 app-server schemas；沒有 auth、account 或模型請求。Generated trees 分別314／317個檔，tree hash／命令／捕獲限制見 [contract-gap JSON](evidence/e6-host-contract-gap.json)。Outer command exit0已捕獲；generator獨立 exit 未保留，只能從 set-e 繼續推知成功，時間亦未測。沒有保存完整 schemas 或每個 stem 的完整路徑。

兩版 Hook stdin 未包含在 app-server generated schemas，改讀各版 exact public tag 的 [0.159.3 Hook input](https://raw.githubusercontent.com/openai/codex/rust-v0.159.3/codex-rs/hooks/src/schema.rs) 與 [0.162.0-alpha.17.2 Hook input](https://raw.githubusercontent.com/openai/codex/rust-v0.162.0-alpha.17.2/codex-rs/hooks/src/schema.rs)。下表各列皆適用這兩個精確版本；相關欄位未觀察到版本差異。

| 精確來源／欄位 | 能建立的事實 | 仍缺的 same-call 語意 |
|---|---|---|
| tagged PreToolUseCommandInput：model、cwd、session_id／turn_id／tool_use_id | Hook model slug、workspace 及 correlation metadata | parent effort、effective config revision／validity；model 不是 provider actual identity |
| tagged Hook：tool_input 為 opaque JSON Value；SubagentStart.agent_type | proposed input／建立後的角色名 | pending-call effective role protection/source、defaults precedence；opaque input 不保證必要欄位 |
| tagged Hook input；既有 E4/E5 native control proofs | 已驗的 deny／rewrite 機制另存 | input 無同次 delegation 控制／共存有效性證明 |
| ThreadRead／Resume／StartResponse：Thread.model／reasoningEffort；TurnStartedNotification | loaded thread config 或最近 persisted config、turn status／time／items | 原 delegation resolved model／effort、per-call config revision；alpha rootTurnId 不補足此缺口 |
| ConfigReadParams／Response：cwd／includeLayers、config model／model_reasoning_effort | disk config／layers／origins | session／turn／call binding、有效 revision |
| ModelListResponse：defaultReasoningEffort／supportedReasoningEfforts | advertised model／effort catalog | pending role／account availability、繼承 target effort precedence與相容性 |
| turn／token-usage metadata | 活動／token telemetry | 原委派的 resolved baseline；本輪不新增 billing／token gate |

因此 production resolver 只將合法 canonical Hook model／cwd 放入 partial snapshot，其餘保持 unknown。兩版保存的實際 Hook 形狀在 default public path 回放會留下 `missing_role_protection`，零 provider；保存形狀回放不等於新 native／production 驗證。

**此公開契約搜尋已結束。**沒有另開 process 的 config/catalog workaround，也沒有 bridge、daemon、host patch、private transcript／state reader 或 assume-known 設定。後續若要實作 production routing，host-owned read-only export 至少要提供：same platform/session/turn/original-call binding、effective config revision／validity、protected role source、native control validity、原委派 resolved model／effort、scoped target model／effective-effort compatibility（含繼承值），以及 conservative configured cost source或明確 unavailable。這是設計需求，未實作／啟用，也未授權 host 變更；A 負責後續架構裁決。

## 本輪驗證與封裝

31 項修正後路由檢查通過（runner0.462秒／command0.575秒）；另1項公開 readiness diagnostic檢查通過（0.014／0.118秒），重用其餘未受影響結果。[命令](evidence/e6-test-run.json)、[輸出](evidence/e6-tests.txt)、[狀態檢查](evidence/e6-status-test-run.json)、[獨立 review closure](evidence/e6-review.json) 及完整版本／清理保存於 [verification](evidence/e6-verification.json)。只執行受影響的 core／public runtime／receipt／CLI 消費路徑及新封裝 smoke；新增 replay 反例造成必要重驗，早期結果另列而不冒充最終 bytes 的證據。

新最小快照案例涵蓋 Main／Fixed 正例、0.49／0.5、顯式 effort、未知繼承 effort、unknown／protected role、缺控制／target／effort、ordinary baseline／cost、Top 可行但回普通 tier、foreign scope／partition及 generic production dictionary。公開 CLI Hook 正例走既有 TypeSafe factory／parser與 fake HTTP；負例零 key／HTTP／attempt。重送只計一次 proposal／attempt，Post 仍分 synthetic／reported，actual／confirmed0。Synthetic dependency 只存在於測試程序，不能建立正式宿主能力。

`verify_accounting_package.py --evidence-prefix e6` 在暫存 venv 離線安裝，再由 installed mrh 準備**新** archive；未修改 launcher 的 default-disabled entry neutral且不建 DB。明確 synthetic bootstrap 從該 archive 載入同一公開 reader／factory，回放保存的 explicit／unknown Pre/Post、CLI/JSON一致與冪等；另以 default production code path 離線回放 reported-only，所有 key／HTTP0。此 smoke 未在 native host 中安裝／執行新版 bytes；[E5 native](e5-settings-plugin-proof.md) 的舊 hash與 [E5R archive](e5r-accounting-proof.md) 保留，不能冒充本輪 native驗證。

最終 archive SHA256：`664a7fd6804c107f1cc562cc1882094386a3041c521e57cec2057a315c1b0115`，與目前 source archive一致；[smoke](evidence/e6-package.json) 實耗3.086秒（含 venv／package／archive準備、入口回放與 owned cleanup）。較早3.412秒的成功 smoke在最後公開 diagnostic字串修改之前，舊 hash另存，不作最終 bytes證據。Synthetic replay proposals2／receipts2／attempts0；default production code path replay另有 reported-only receipt1、actual／confirmed0，仍是離線 fixture回放。

沿用未受影響的 E3 serializer／parser／transport/deadline、E4 native control、E4G Goal 和 E5 lifecycle／trust／共存證據；沒有重跑 Goal、native plugin lifecycle或 full provider suite。沒有真 credentials／provider、正式全域 Hook、A/B execution Goal、其他專案寫入或 push。Owned schema／smoke temp roots及 generated caches清理在 verification保存。Task tracking仍缺宿主 profile／穩定身分 context，不猜 Monitor ID或寫私人 DB；MRH-001 文件保留本輪交付。
