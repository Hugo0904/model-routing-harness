# E14：保留原呼叫，也讓故障可見

E14-B-001 已完成本機修正與受影響驗證；來源 commit 為 `f22e2a82fdeef2cd45ddbb3d204d80226b481ea2`。A 已核對來源與原生證據，親自操作公開 Hook、獨立 launcher 和 24×56 CLI，接受本單元；詳見 [A 驗收](evidence/e14-a-acceptance.json)。整體 MRH-001 與 R1／R2／R3 仍未完成。

## 行為與資料界線

共用 `faults.py` 只將白名單原因轉成固定文字，供 Hook 與既有統計使用。分類器 timeout／error、無效回應、事件持久化等故障會保留原呼叫並輸出頂層 `systemMessage`。通知指出失敗事項、呼叫如何處理，以及同一 profile 的 `mrh stats --details --settings …` 或 `--db …`；不插入 task、憑證、原始例外或未信任路徑。正常 explicit／role／低信心／cost 保留與主機事實不足另列，沒有活動不代表故障，也不代表已啟用。

D23 的選定 target 下架／不可用仍 deny 並保持原鎖定語意。已決定的 stop 遇到 complete／latch 寫入失敗，也會警告紀錄未確認，並維持 deny。通知狀態寫入失敗不改變已確認的路由決策，不授權派工、不重分類、不改寫 cached decision、原 history 或 child receipts。沒有委派後的自動 fallback／重播。

SQLite 保持 `user_version=3`，公開 stats 保持 `schema_version=2`。只新增可重入建立的 `notifications` 表及 stats 的衍生 `routing_status`／`notifications` 欄位。原 proposals、attempts、tier 分母、synthetic／live 分區、實際 child 證據及 cost／quota／token unknown 值不變；既有 `updated_at` 仍只讀 canonical facts，通知另有時間。

`routing_status` 將完成的 canonical proposals 分為 classified child request、classified main request、normal retention、fault fallback、operator stop 與 unavailable readiness。通知觀測包含 Hook 重播，與 classifier attempts、canonical proposals 分開。profile 的既有 event store 內，以 platform／surface／session／synthetic 為 scope，原子 claim 第一個警告；重複故障累計觀測，不重播警告。只有後續完成、有效且有 returned attempt 的實際路由評估可清除該 scope 的故障狀態。舊 success cache、保存設定、刷新 catalog、沒有活動皆不能宣稱恢復；恢復後重播舊 fault 不重開通知 episode。恢復分類器評估不解除 D23 stop。

`warning_claims` 是要求發送的次數，不是 UI 收到的次數；沒有 UI acknowledgement，因此 claim 後的主機斷線／顯示狀態仍可能未知。狀態只描述已觀測 scope，不能偵測未呼叫、不信任或未註冊的 Hook。存儲或 launcher 故障無法可靠去重時仍發出固定且有界警告，明示紀錄／去重不可依賴，故障可能沒有進入歷史。沒有另建監控服務或第二份路由狀態。

獨立 launcher 只用標準函式庫：驗證固定 binding／runtime hash，隔離執行 Python runtime，丟棄原始 stderr，限制輸入／stdout readback；載入、完整性、異常退出或未完成均可自行警告，不 import 故障 core。CLI 外層不再把有效 PreToolUse 的 runtime import failure 當成成功 `{}`；共用警告模組也無法載入時以非零退出讓 launcher 接手。Runtime watchdog 48 秒、原生 Hook timeout 50 秒，給既有最長 30 秒分類評估及 claim／complete／notification 的 SQLite 等待留出空間。沒有改變分類器的 timeout 或重試契約。

封裝新增模組後超過既有 64 KiB 更新讀取限制，runtime 更新改用 `_old_artifact` 已採用的 16 MiB 上限；其他檔案仍保留 64 KiB、所有權、symlink、雜湊與原 lock 規則。

## 已驗證範圍

[受影響檢查](evidence/e14-verification.json)：125 個 unittest 通過，5.555 秒，涵蓋 timeout／error／malformed、並行／重複觀測、canonical history 不變、跨 session／profile、相關恢復、未知 readiness、safe canary、持久化失敗、D23 stop／寫入失敗、實際準備的 launcher 完整性／import／部分模組缺失，以及直接 CLI／stats 消費端。

兩個 D32 指定過時測試已修正：migration 明確驗 SQLite 3，JSON stats 仍 2；accounting 的詳細文字命令明確加 `--details`，保留所有 JSON identity、history、unknown、read-purity 斷言。直接 CLI consumer 的 `test_integration` 另有同類舊詳情預期，在 E14 前 `fe99ca1` 已與 compact 呈現不符；同樣只加 `--details`，保留原斷言。受影響 runtime 的失敗測試現驗固定警告及不外送／不洩漏，沒有刪除保留行為檢查。曾誤選不存在的 `test_attempts`，沒有把該 loader error 算通過；實際 attempt timeout／late／cancellation 檢查位於 `test_typesafe`，最終命令只含存在且實際執行的選項。

[原生證據](evidence/e14-native-warning.json)：本機 Codex CLI **0.159.3**、精確 binary hash、新 HOME／CODEX_HOME／workspace、原生 plugin 註冊與正式 Trust all and continue。沿用 E4／E5 的 Fixture／Rpc／trust／cleanup 與 TypeSafe bootstrap，沒有完整 E4／E5／E8 重播、source build、正式 Hook 變更或安裝 CLI 置換。公開 catalog 來自 exact `rust-v0.159.3`，TLS curl 下載並驗既有 pin；API provider 只指向無 Authorization 的 scripted loopback。

分類器 case 從實際安裝的 archive，透過明確 synthetic Host／FakeTransport 執行既有 TypeSafe factory。一次 in-process synthetic transport failure、一個 dummy credential resolver，沒有 Jev 網路請求或真 key。其頂層 `systemMessage` 與原生 `hook/completed` 的 warning entry 精確相同；native child 仍用原 `mrh-synthetic-parent`／low，原 dispatch 繼續。這一 case 的原生 warning event 已驗證，沒有單獨把它當成 Desktop 或 terminal 顯示證據。

Launcher case 在同一 fresh native plugin 恢復原始 launcher command，故意破壞 owned fixture archive，正式重新 trust；實際 30×100 PTY 明確顯示 integrity warning 及 original-call-preserved 文字，loopback child 仍以原 model／effort 繼續。[終端文字](evidence/e14-native-terminal.txt) 僅移除 ANSI CSI／OSC／單一 escape 控制碼及行尾顯示空白，是實際 PTY 輸出，沒有合成畫面或 screenshot。執行時 helper 位於上述 f22e2a8；交付時僅整理 helper 的逐字稿控制碼及行尾格式，格式整理前的逐字稿 hash 另留在 native JSON，未重做 routing 或改寫可見文字。原生測試 archive 與 launcher byte hash 必須和最終 source 相同，核對見 [來源](evidence/e14-source-identity.json)。

[摘要畫面](evidence/e14-dashboard.json)：實際 24×56／24×120 Screen PTY，透過 GNU Screen VT100／ANSI virtual display hardcopy 確認故障提案、正常保留、active state、觀測／claim／recovery 與詳情入口完整可見、沒有超欄，原 canonical stats 不變。這是終端畫面狀態證據，不是像素 screenshot。詳情 28／56／120 欄和彩色／純文字／控制字元清理由受影響 tests 覆蓋。沒有重做 selector、Claude catalog 或 E13 package gate。

[清理](evidence/e14-cleanup.json)：最後 native／Screen owned roots 不存在，direct processes 已退出；列出的六個 owned groups 經宿主 `pgrep -g` 為 exit 1、無輸出／錯誤。Sandbox 中的 exit 3 讀取拒絕沒有當成清理證據。暫時 hardcopy 已刪除，正式證據 JSON／文字保留。

精確版本依據為 [官方 Hook common output](https://learn.chatgpt.com/docs/hooks#common-output-fields) 與 [rust-v0.159.3 PreToolUse handler](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/pre_tool_use.rs)：`systemMessage` 進入 warning entry；warning 本身不阻止或改寫工具。沒有輸出不支援的 `continue`／`stopReason`／`suppressOutput`，也沒有把 model-visible additionalContext 代替 UI warning。

## A 本人驗收與續作

A 可先核對 source identity、native warning event／PTY transcript／56與120欄 hardcopy，親自操作同一候選的 CLI/status。以下開發 helper 只使用新 owned fixture；需要本機既有 Codex 0.159.3、Python 3.11、curl、GNU Screen、loopback／PTY 權限，不能換成真帳戶或正式 HOME：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts python3.11 scripts/verify_fault_display.py --output /absolute/owned/e14-display.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts python3.11 scripts/verify_fault_host.py --binary /absolute/pinned/codex --output /absolute/owned/e14-native.json --transcript /absolute/owned/e14-native.txt
```

實際 Desktop 顯示、其他 CLI／OS／版本、真 Jev／provider／child model identity、production readiness、original R1／R2（含 Gemini）／R3 仍未由本單元證明。E13 已接受的方向鍵／Enter 選 AI／model／effort／save／back／cancel 與先前下架／失敗清單證據沿用；本單元沒有修改 selector 契約。A 若有實際反例，依原授權直接交 B 修正，驗收無誤後繼續剩餘義務，不新增逐階段人類確認。

可信 Monitor context 沒有既有 task，且 `current_native_user_item_unavailable`，已選 none；沒有自行造原請求 ID、建立新 task／Goal、手寫舊 Canopy progress 或接入 live Monitor。這是紀錄能力缺口，並非本機功能驗證或整體接受證明。
