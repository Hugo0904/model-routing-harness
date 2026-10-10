# E5R：preserve 也保留事實紀錄

0.2.1 修正 configured entry 的 explicit／unknown early return。通過既有 settings、enabled、export 與 workspace gate 的合法委派，保留原呼叫時也記錄 proposal／固定 outcome；Post 只按 accepted proposal／identity／partition 關聯收據，不重新查 host 能力。分類、API key 解析與 HTTP 都保持零。正式 resolver 仍未完成，完整 R1 未完成。

Explicit Pre 在 core 之前不再直接返回：先經不讀 key 的既有真 factory 取得 evidence partition，再走既有 Store／service／core，記 `explicit_model`，略過 host resolution 與分類。Unknown／resolver exception 以 bounded unavailable caps 記 `unresolved_host_configuration`，不猜測能力、不保存 raw exception。原 fixed-role／Fixed rewritten Post、HMAC/body 隱私、重送／conflict、gate 與 partition matching 保持。

Malformed session/turn/tool-use ID 在資料建立之前 neutral。Unrelated、disabled、export denied、out-of-scope、unowned／malformed settings 或 partition mismatch 也不增加 facts 或讀 provider key。Post 有 model 不會被當成新的 explicit 分類請求；收據只可 reported／synthetic，沒有 actual model／confirmed／successful Main handback promotion。

## 聚焦證據

18 項 affected configured-runtime／receipt／CLI-stat tests 通過，runner0.267秒、command0.364秒：[輸出](evidence/e5r-tests.txt)、[命令](evidence/e5r-test-run.json)。兩版 E5 保存的 explicit Pre/Post 都作為實際 consumer-shaped input 回放，未新啟動 host。

- explicit Pre／Post 重送仍是 proposals1、explicit_model1、attempts0、synthetic receipt1；host resolver、classifier、key、HTTP 都未執行。相同 ID 不同 body 仍拒絕，不覆寫原 outcome。
- unknown exception 的 Pre／Post 重送仍是 proposals1、unresolved1、attempts0、synthetic receipt1；Post 不查新能力。Pre 回放可再查 metadata，沒有新分類／provider retry。
- 正式 default unknown path 的離線回放記 reported receipt1，actual／confirmed0、key／HTTP0。這是保存事件在預設程序路徑的重播，不能稱為真 production 執行或新的 host evidence。
- 原 Fixed rewritten Post、known fixed-role、explicit protection 與 negative gates 保留；邏輯獨立的舊 runtime cases 改用不同 call IDs，避免被 immutable proposal conflict 掩蓋。
- CLI human／JSON 讀同一 corrected stats，讀回不增加 proposal／attempt／receipt；body、key、raw resolver exception 不入 facts。

## 新封裝入口

[Smoke JSON](evidence/e5r-package.json) 在新的 owned temporary venv 離線安裝0.2.1，再以 installed `mrh plugin prepare` 建 bundle；unmodified launcher 在 default-disabled 實際輸出 neutral且不建 DB。Code-level bootstrap 只從**新準備的 archive**載入同一 public CLI/settings reader／真 Typesafe factory，回放上述保存形狀並驗證 corrected accounting，不替換 classifier。

新 archive SHA256：`3207de1a309d82fa1caadecf8270c98a0acc0c10aaf960d28720afea865220bc`。Synthetic replay 是 proposals2／explicit1／unresolved1／receipts2／attempts0；正式 default-unknown 程序路徑另記 proposals1／reported1，但它也是同一離線 fixture input 的回放，沒有真 production child 或 provider 證據。兩分區沒有合併。所有 credential-resolution／HTTP counters0，CLI stats讀回不增量。

Smoke 實耗3.430秒，含 venv/package/archive準備、公開入口回放與最後暫存清理；每個 subprocess上限30秒，各命令時間在JSON保存。E5 兩次真正 native-installed 舊 archive hash仍是 `ee7917718ba4a547aaebf62b5635487d1b4690cca00800373d0684041df6913d`，本輪沒有把舊 native run改稱使用新bytes。安裝／trust／launcher機制未變，沿用已接受的E5結果，沒有重跑native lifecycle、full core/provider、Goal或真 API。

本輪範圍只到 configured-entry accounting；沒有放寬任何 host-routing guard或新增resolver設計。原E5 JSON proposals5/receipts3是歷史結果，不能自行改成修正後計數。版本與回放限制總表在 [E5R verification](evidence/e5r-verification.json)，待A接受。暫存venv/bundle/state已清理，沒有正式Hook、真憑證/provider、A/BGoal或其他專案寫入。
