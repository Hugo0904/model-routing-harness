# Internal protocol and statistics contract v1

這是 MRH 本專案的內部格式，**不是 Jev wire API**。目前只有明確合成 classifier 注入；production UnavailableClassifier 不讀憑證、不發請求，預設零重試。

## 路由與配置

`core.route(Proposal, policy, host_capabilities, classifier, optional_context)` 是純政策；`service.process(...)` 加 Store 原子 claim、冪等、fail-open。平台接頭只轉換事件、參數與結果。

Identity 含 platform/surface/session/turn/tool-call 五部分，都是有界識別字。Message／未知 tool_input 僅在記憶體供分類或 transient Hook rewrite 使用；DB 只保存 locally keyed HMAC fingerprint。同 ID 不同 input 拒絕；completed replay 回 cached patch，pending/crash 保留原呼叫，不重送未知請求。一次 proposal 的決策凍結，新委派使用新 ID。

Classifier `classify(task, permitted_context_or_none, record_attempt)` 回 `Classification(tier, confidence, reason_code)`。Tier 是 Light/Small/Mid/Top，confidence 有限 [0,1]，bool 不是數值。Attempt callback 對應每次 transport invocation；本版只有 scripted synthetic attempts，live Jev attempts 為 0。錯誤只留固定原因/stage，無 raw exception。

順序：canonical delegation → 顯式 child model／known fixed role 保留並略過分類 → known host precedence → valid policy → optional context → valid classification → `<0.5` 保留 → Top Main/Fixed 或成本比較。主模型選擇不是指定 child。0.5 有資格繼續，但不能越過 compatibility/cost guard。

Policy 包含 top_mode（Main 預設／Fixed）、fixed／tiers 的 model/effort 對照、timeout_seconds（正有限且 <=30，預設1），以及 rates。Rate vector 要相同 currency/unit/service、sourced source_ref、相同所有已知 billed component keys；target 每項不高且至少一項較低才可路由。缺資料保留 cost_unknown，只表示 configured estimate，無 measured savings。

Capabilities 由同 surface 可信 owner 注入：configuration_known、main_model/main_effort、roles known/fixed_model/rewrite_allowed、models available/efforts。未知 precedence 保留。原 proposal 顯式 effort 留存並需 target 支援，不為強行接受而丟掉它。合成 capabilities 不代表帳號 catalog。

Decision v1：preserve/request_child/return_to_main、固定 reason、tier/confidence（可null）、model/effort-only patch、synthetic、bounded context_status。Store complete 另驗證型別/枚舉/欄位，不讓 cached patch 夾帶正文。

## Optional background

只接受程序注入 `ContextSummary(summary, source_ref, permitted_export=True)`；沒有 shell plugin 或 Canopy 私人檔案接頭。上游必須確認可外送 allowlist/來源；字串遮罩不能保證匿名化。上限2048 UTF-8 bytes；超大、未授權、敏感 marker、錯誤、timeout 都改走 task-only。Context 不保存、不加 confidence。Default absent；既有 activity/statistics export 不是 background-summary 契約。

## Facts and observation

SQLite transaction/unique IDs 保護獨立 process writers。32-byte HMAC secret 在 DB 旁 *.key、0600、初始化鎖，不提交/匯出。現有 DB key 缺失時拒絕重建；pending 不自動重試。查詢不用 classifier、不新增事實。

`Store.record_observation(receipt, verifier=None)` 白名單：event_id/proposal_id/platform/surface/session_id/turn_id/tool_call_id/agent_id/evidence_kind/source_ref；optional actual_model/model_evidence。所有欄位驗證，只接受 completed 的同五段 correlation，Top Main child receipt 拒絕。同 event ID changed content 或同 agent 另一次 receipt 拒絕，不重複計數；後續補充 model evidence 的升級介面尚未實作。

Evidence kind：synthetic/reported/host_observed/provider_observed。Source label 本身不驗證；host/provider 要 future trusted adapter verifier 正面確認，CLI 沒有該 verifier/official importer。Synthetic proposal 不能升成 observed。actual_model 要 provider_observed 證據；requested/configured/self-report 不是 actual。候選 PostToolUse 只有 reported（或 explicit simulation 的 synthetic）receipt，沒有 actual-model claim。缺 authoritative schema 只留固定 unavailable/rejected reason。

## Read-only statistics

正式本機出口 `mrh stats --db <explicit-path> --json`；CLI 與 future Monitor 共用 Store.stats 物件。--synthetic 獨立分區；refresh 不新增 proposal/attempt、不呼叫分類器。

Schema1：updated_at、partition、proposals、jev_attempts、synthetic_attempts、classified_tasks、low_confidence_tasks、pending_proposals、tiers、outcomes、requested_models、confirmed_children、simulated_children、reported_children、actual_models、unknown_actual_model_children、cost/tokens/quota（不可取得null）、capabilities。另有 platforms/surface 的 proposal 彙總，以及各類 stable event_ids（每類最多100，超過時 event_ids_truncated=true）；不匯出 content fingerprint。updated_at 是本機保存的最近事實/完成時間，不是 vendor telemetry。

classified_tasks 包含取得有效 tier/confidence 的 low-confidence；tiers 組成分母就是它，不能當 completion progress。Requested 與 verified actual 分開；Main 不算child；synthetic/reported 不算confirmed。用量/價格/額度未知保留null，零次live requests不等於零成本證明。

Monitor 本階段只有格式、合成例與查詢說明，無 DB/API 寫入或 daemon。Consumer 須保留 schema/version/time/platform/correlation；要求/configured/host observed/provider actual 不混算。讀取失敗不影響 routing。

## Codex / installer boundaries

只有 PreToolUse+canonical spawn_agent 進 route。Default `{}` 不改權限或參數。Explicit simulation 才序列化 Main deny／Fixed updatedInput；transient replacement 保留原子任務/未知欄位，但不持久化、不放公開 stats。Deny 只請求接回，未驗證主代理續作/zero actual child；rewrite 未驗證型號採用。

預覽讀 explicit target，不 dump private commands。A D3：public apply/disable 拒絕 exclusive_target_unverified；只有自行建立、持有 synthetic home 的 helper 可測候選。Lock 只保護同 helper 合作呼叫，不保護非合作編輯器；反例保留在 tests。無 auto-trust/force/unsafe，真正 S4 shared-home 安裝/停用仍未完成。

Claude/Gemini 未支援，介面差異見 [盤點](capabilities.md)，不能共用 Codex tool name/effort。
