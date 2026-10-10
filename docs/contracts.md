# Routing and statistics contract v2

這是 MRH 內部政策／facts 格式，**不是 Jev wire API**。TypeSafe 接頭預設關閉；E5 公開設定／installed Hook 共用既有 factory，透過 HTTP 邊界替身驗證。正式 host resolver 資訊不足時保留原呼叫，零網路／憑證讀取、零重試。E3／E5 provider 證據全為 synthetic。

## 路由與配置

`core.route(Proposal, policy, host_capabilities, classifier, optional_context)` 是純政策；`service.process(...)` 加 Store 原子 claim、冪等、fail-open。平台接頭只轉換事件、參數與結果。

Identity 含 platform/surface/session/turn/tool-call 五部分，都是有界識別字。Message／未知 tool_input 僅在記憶體供分類或 transient Hook rewrite 使用；DB 只保存 locally keyed HMAC fingerprint。同 ID 不同 input 拒絕；completed replay 回 cached patch，pending/crash 保留原呼叫，不重送未知請求。一次 proposal 的決策凍結，新委派使用新 ID。

Classifier `classify(task, permitted_context_or_none, guarded_attempts)` 回 `Classification(tier, confidence, reason_code)`。Tier 是 Light/Small/Mid/Top，confidence 有限 [0,1]，bool 不是數值。E3 對真 serializer/parser 使用 fake transport，但 live Jev attempts 仍為 0。錯誤只留固定 reason/stage，無 raw exception。

順序：canonical delegation → 顯式 child model／known fixed role 保留並略過分類 → known host precedence → valid policy → optional context → valid classification → `<0.5` 保留 → Top Main/Fixed 或成本比較。主模型選擇不是指定 child。0.5 有資格繼續，但不能越過 compatibility/cost guard。

Policy 包含 top_mode（Main 預設／Fixed）、fixed／tiers 的 model/effort 對照、timeout_seconds（正有限且 <=30，預設1），以及 rates。Rate vector 要相同 currency/unit/service、sourced source_ref、相同所有已知 billed component keys；target 每項不高且至少一項較低才可路由。缺資料保留 cost_unknown，只表示 configured estimate，無 measured savings。

Capabilities 由同 surface 可信 owner 注入：configuration_known、main_model/main_effort、**original_model/original_effort/original_resolution_known=True**（解析 role／agents defaults 後的原委派基準）、roles known/fixed_model/rewrite_allowed、models available/efforts。普通 tier 比 original_model 的 rates，不比 main_model；缺原基準欄位保留 cost_unknown。原 effort 可明確為 null，其他值需安全有效。若 effort 影響計價，rate owner 必須供該已解析基準的保守 rate。原 proposal 顯式 effort 留存且需 target 支援。Fixed Top 既有例外不變；合成 catalog 不代表帳號型號。

Decision v1：preserve/request_child/return_to_main、固定 reason、tier/confidence（可null）、model/effort-only patch、synthetic、bounded context_status。Store complete 另驗證型別/枚舉/欄位，不讓 cached patch 夾帶正文。

## Optional background

只接受程序注入 `ContextSummary(summary, source_ref, permitted_export=True)`；沒有 shell plugin 或 Canopy 私人檔案接頭。上游必須確認可外送 allowlist/來源；字串遮罩不能保證匿名化。上限2048 UTF-8 bytes；超大、未授權、敏感 marker、錯誤、timeout 都改走 task-only。Context 不保存、不加 confidence。Default absent；既有 activity/statistics export 不是 background-summary 契約。

## Facts and observation

SQLite transaction/unique IDs 保護獨立 process writers。32-byte HMAC secret 在 DB 旁 *.key、0600、初始化鎖，不提交/匯出。現有 DB key 缺失時拒絕重建；pending 不自動重試。查詢不用 classifier、不新增事實。

`Store.record_observation(receipt, verifier=None)` 白名單：event_id/proposal_id/platform/surface/session_id/turn_id/tool_call_id/agent_id/evidence_kind/source_ref；optional actual_model/model_evidence。只接受 completed 同五段 correlation。Top Main 決策不合成 child，但後續 unexpected child receipt 保留為 handback anomaly；可信 verified receipt 可增加真 confirmed count，reported/synthetic 分別計數，沒有 successful-handback credit。Pending 拒絕。同 event ID changed content 或同 agent 別次 receipt 拒絕；model evidence 升級介面尚未實作。

Evidence kind：synthetic/reported/host_observed/provider_observed。Source label 本身不驗證；host/provider 要 future trusted adapter verifier 正面確認，CLI 沒有該 verifier/official importer。Synthetic proposal 不能升成 observed。actual_model 要 provider_observed 證據；requested/configured/self-report 不是 actual。候選 PostToolUse 只有 reported（或 explicit simulation 的 synthetic）receipt，沒有 actual-model claim。缺 authoritative schema 只留固定 unavailable/rejected reason。

## Read-only statistics

正式本機出口 `mrh stats --db <explicit-path> --json`；CLI 與 future Monitor 共用 Store.stats 物件。--synthetic 獨立分區；refresh 不新增 proposal/attempt、不呼叫分類器。

Schema2 沿用：updated_at、partition、proposals、jev_attempts、synthetic_attempts、classified_tasks、low_confidence_tasks、pending_proposals、tiers、outcomes、requested_models、confirmed_children、simulated_children、reported_children、actual_models、unknown_actual_model_children、cost/tokens/quota（child資料不可取得null）、capabilities、platforms/surface、stable event_ids（每類最多100，超過有旗標）。不匯出 fingerprint；updated_at 是本機最近 facts 時間。新增 jev telemetry 及 handback_anomalies／handback_anomaly_evidence（confirmed/reported/synthetic）。

classified_tasks 含有效 low-confidence；tiers 分母就是它，不是完成進度。Requested／verified actual 分開；Main 請求不製造 child，後續 anomalous actual evidence 保留；synthetic/reported 不算confirmed。Unknown 保留 null，零live requests不等於零成本證明。Plain／NO_COLOR 條以不同 glyph／delimiter 與 counts/percentages 呈現組成。

Monitor 本階段只有格式、合成例與查詢說明，無 DB/API 寫入或 daemon。Consumer 須保留 schema/version/time/platform/correlation；要求/configured/host observed/provider actual 不混算。讀取失敗不影響 routing。

## Codex / installer boundaries

只有 PreToolUse+canonical spawn_agent 進 route。Default `{}` 不改權限或參數。Explicit simulation 或可信程序依賴才可能序列化 Main deny／Fixed updatedInput；replacement 保留原任務/未知欄位、不持久化正文。PostToolUse 的 rewritten input 可以含 model，仍以同五段 identity 關聯既有 proposal；explicit-model skip 只適用 Pre。E4／E4G／E5 驗證 native-v1 與 scripted provider 的 deny 零 child／合成型號採用，未驗證主代理自主續作或實際模型智能。

預覽讀 explicit target，不 dump private commands。A D3：public apply/disable 拒絕 exclusive_target_unverified；只有自行建立、持有 synthetic home 的 helper 可測候選。Lock 只保護同 helper 合作呼叫，不保護非合作編輯器；反例保留在 tests。無 auto-trust/force/unsafe，真正 S4 shared-home 安裝/停用仍未完成。

Claude/Gemini 未支援，介面差異見 [盤點](capabilities.md)，不能共用 Codex tool name/effort。

## TypeSafe wire adapter 與公開接線

官方來源於 2026-10-10 核對：[API](https://docs.typesafe.ai/api)、[models／pricing](https://docs.typesafe.ai/models)、[choice](https://docs.typesafe.ai/primitives/choice)、[confidence](https://docs.typesafe.ai/confidence)、[coding agents](https://docs.typesafe.ai/introduction/coding-agents)。固定 POST `https://api.typesafe.ai/v1/systemone`、標準 TLS checks、Bearer runtime key，不接受 configurable endpoint、不跟隨 redirect。沒有 SDK、credential file 掃描、CLI key 參數。

`classifier_from_config` 只接受 schema_version=1、enabled／task_export_permitted 布林、model=jev-1.13.0；[factory 範例](../examples/typesafe-disabled.json) 全關閉。兩個開關都明確 true 才評估 injected credential resolver／`TYPESAFE_API_KEY` runtime resolver。E5 `settings`／`hook --settings` 用[完整設定](../examples/settings-disabled.json)共用 strict reader，另要求 operator 的 canonical workspace 範圍與可信 host resolver。Disabled／無 export／out-of-scope／host 未解析／無 key 都是零 transport invocation。程序依賴介面如下；片段本身未啟用或讀 key：

```python
from mrh.typesafe import classifier_from_config
from mrh.service import process

classifier = classifier_from_config(config, credential_resolver=runtime_key_resolver)
decision = process(proposal, vetted_policy, vetted_capabilities, store, classifier,
                   optional_context=permitted_summary_provider)
```

公開設定 schema1 的 required fields：owner、revision、enabled、task_export_permitted、allowed_workspaces、provider=typesafe、classifier_model=jev-1.13.0、policy。未知欄位、duplicate keys、非有限數字、非 canonical lexical workspace、錯誤型別或超過65536 bytes 拒絕；不接受 key 值、URL 或自報 capabilities。寫入前也驗證序列化大小。原生 launcher 明確綁定 absolute settings.json，沒有 task-cwd 自動發現。可驗證的 MRH 自有 root 與 cooperating-writer lock 保護自身更新，expected revision 衝突拒絕；不宣稱非合作 writer 的 filesystem CAS。

`plugin prepare` 只改自己的版本化 plugin／marketplace／stdlib runtime archive，settings／telemetry 在外部自有 state root。重複準備不重新啟用，不覆寫既有 settings；own code 被外部修改或有未知內容／symlink／ownership 歧義則拒絕。Prepared、native installed、routing enabled、trust、live ready 是不同狀態。Native uninstall 不刪 separate state，也不恢復共享 snapshots。`settings disable` 讓新 invocation neutral 且零 classifier/key/transport；已 admission 的 invocation 可依 captured settings/deadline 完成，不宣稱遠端或跨程序取消，不會回寫設定重新開啟。詳細命令與實測邊界見 [E5](e5-settings-plugin-proof.md)。

Body 是 model/state/questions，state 只有 task 和許可的 context_summary；tier 為 choice，以 lower-case light/small/mid/top 使用本地 **mrh-tier-v1** rubric（mechanical／bounded comprehension／substantive implementation／cross-system tradeoff）。State 視為資料，不可改 tier／選模型。這不是原作者已驗證 prompt，也不是防 prompt injection 的保證。

Parser 要求 bounded safe model、answers.tier.type=choice、有效 choice、四個精確 probability keys、有限 [0,1]、總和近1、choice 為最大 probability；**直接採回應 confidence**，不取 max／重算。總和容差1e-6是本地浮點選擇，官方沒有明訂數字。Pin mismatch 保留原委派、另留 safe actual response model；它不是 child actual model。Client 在 persist 前移除 model 中包含本次 key/task/summary 的回顯。Malformed required data 回 typed reason；unknown JSON／raw body 全丟棄。Optional usage 缺失、bool、負數或溢位令兩 counters null。

Exact production `HttpTransport` 才可標 live；其他注入 transport 必須明確 synthetic=True，未知／自行宣稱 live 會拒絕。Fake transport 第一個操作必須呼叫提供的 enter()，未進入口不能算 started；這是受信任程序注入契約，不能把 arbitrary plugin 當 production verifier。Production connection/socket timeout 至多2秒且受 remaining deadline 限制；各 network 邊界核對 closed，每個 read1 chunk 重核 deadline，response 上限65536 bytes、finally close。Zero retry（一個 invocation）。401/422/429/529/5xx、network、timeout、oversize、redirect、malformed／mismatch 回固定 reason，沒有 raw headers/body/errors。

## Attempt lifecycle、deadline 與 Jev telemetry

Schema2 additive migration 保留 v1 欄位／outcome／timestamps；舊 attempt phase=legacy，原次數保留，不補 model／usage。新 stable attempt ID 是 proposal_id+local invocation ID，requested→started→returned/error/unknown。Request/object 建立不算 attempt；**transport entry admission** 才 started，這仍不是 vendor delivery／billing 證據。同 phase／metadata replay 冪等，終態衝突拒絕；Unknown 可補 late_outcome，不增 attempt count。保存 allowlisted requested/response model、有效 int64 tokens、固定 error_reason、kind/source 與 local timestamps，沒有正文／key／raw errors。

Core 完成或 timeout 關 gate，遲到 callback 與「invoke 到 transport entry」間隙取消都不能開始新 invocation。已進入口仍可能在本地 timeout 後完成：先 unknown，再 late_returned／late_error，不改已凍結 preserve，不重送。這不宣稱 remote cancellation。Socket 正在等待時的遠端處理仍屬 in-flight uncertainty。Optional context 有獨立小 timeout，逾時後只分類 task；分類使用自己的 shared operation deadline。

`jev` 包含 source、attempt_states、requested_models／response_models、input_tokens／output_tokens（全部 usage 已知才有總值，否則 null）、known_input_tokens／known_output_tokens（已知子集合）、usage_unavailable_attempts、estimated_cost。Unknown 與 late_returned 是同一次 attempt 的狀態／旗標，不能相加算次數。Jev reported model/tokens 不混入 child actual model/tokens；source 顯示 actual_provider_transport 或 explicit_synthetic_offline_transport，沒有新 provider rows 則 unavailable。E3 actual-provider count=0。

只有全部 provider rows usage 已知且 returned model 全匹配 jev-1.13.0，才用 reported input_tokens×$0.042／1,000,000（官方 output free）產生 **estimate**，附 USD、model、unit、price_source、price_date=2026-10-10。Synthetic estimate 仍是合成資料，不是帳單／savings／真 API 證據；unknown/mismatch 保持 null。Child cost/tokens/quota 與實測節省仍不可取得。
