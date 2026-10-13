# Codex App 分級建議驗證

## 2026-10-13：真 App 批次與正常接入恢復

原 C 聊天以真實 Desktop App、原生委派工具、真 Jev 與 `fdb7428` 的已安裝程式完成一批隔離測試。10 次有效設定試次中，8 次收到 native deny/reason 建議，主代理保持相同子任務與名稱，以 `fork_turns="none"` 重派；8 個子代理的官方 `thread/read` 模型設定均為 `gpt-5.6-luna/low`，並完成排序。另 2 次信心低於既有 0.65 門檻，保留原委派並完成。最初準備設定的空值錯誤另計 1 次，未呼叫 Jev；修正後保留原紀錄。全部分母是 11 次，符合建議的委派為 8/8，採用候選的比例為有效試次 8/10、全部試次 8/11。

App 的 `subAgentActivity` 模型／強度欄位為 null。精確子代理 metadata 配合原生 started/completed 與回覆，證明宿主採用了設定並完成子任務，但不是每回合的供應商模型遙測；不以 DB 的 `followed` 或 requested 欄位取代證據。若原驗收要求 10 個採用候選的子代理，仍只有 8 個，不能把低信心放行算進去。整體與這個證據界線仍由原 A 接受。

本次新增 helper 的 `prepare-installed`：複製既有 launcher/runtime，不重建分類器；只放行原 C 的 session、cwd 與列出的排序測試名稱。原 `prepare` 固定 fixture 模式保留。其他 session/cwd/task 的直接檢查 3/3 回 `{}`，未增加紀錄。註冊、兩個 Hook 的信任與移除均使用官方介面。收尾已移除 A/C 臨時接入、恢復正常 MRH 啟用並讀回原 Hook 信任及其他外掛狀態。

人類之後要求的日常候選已用安裝的 `mrh ctrl` 套用並讀回：Light=`gpt-6-luna/high`、Small=`gpt-6-luna/max`、Mid=`gpt-6.1-sol/high`。只有這三個 Codex 清單及必要 revision 變更；Top、Claude、Jev 與其他欄位保留。這是設定證據，舊隔離候選的模型結果不適用於新候選。同期日常套件增加了 `040b840` 的統計變更，也未由本批舊版本證據驗證；保留後續提交及文件整理，不重跑既有 CLI/unit/Claude。

完整非敏感證據：[codex-app-c-20261013.json](../evidence/codex/codex-app-c-20261013.json)。原始自有隔離紀錄仍保存在 `runtime/codex-app-c-20261013/`。傳回原 A 的原生訊息遭自動核准審查拒絕，已提出明確傳送授權問題；目前只在本地保存，尚未送達或接受，不改工具／收件人繞過。

## 2026-10-11：D70-C-001 歷史保存點

目前完成的是**固定回覆 probe 的本地準備與直接介面檢查**，尚未完成真實 App Hook／parent 消費者驗證。沒有呼叫真分類器、建立 child 或讀到 App parent 的實際選模行為。原 CLI／核心／Main 等仍適用的證據保留；本次没有重跑。

`scripts/verify_app_advisory.py` 只建立獨立 external plugin artifact，沒有修改任何共用分類器、設定、廠商程式或 normal home。固定建議沿原使用者的 Codex `gpt-5.6-luna/low` 選項作傳輸 fixture，不更改 tier preferences，不宣稱是真分類結果。實際產品採用仍須使用 B 的同一套件與分類器。

## 已完成的直接接點

helper 的 external plugin 格式沿現有 owner：marketplace 的 local source／policy、plugin 根目錄 `plugin.json` 與 `extensions.com.openai.hooks`。只匹配明確 session ID、canonical cwd、兩個 native spawn tool names，以及一段固定的無專案資料小任務。其他 session／cwd／task 回 `{}`，且不記錄；明示 model／effort、named role 通過；Post 只記錄匹配的 probe。建議使用真正 `hookSpecificOutput.permissionDecision=deny`／`permissionDecisionReason`，不以 `systemMessage` 冒充送達主模型。log 不寫任務正文或 raw child response。

本地獨立 subprocess stdin/stdout 檢查已覆蓋上述接點，以及生成的 plugin 形狀。這些是 **synthetic public helper interface**，不是原生 Hook 載入、信任、App parent 或實際分類的證據。紀錄：`d70-c-app-preparation.json`；測試暫存 plugin／log 已清除並確認 absence。

## 額度停止與共用 surface 釋放

人類來源 A turn `01a12f59-a681-74c3-91d8-5001b985a6ca`／item `01a12f59-ad4c-7c11-8586-0ab7e60da6a5` 已由 supported read_thread 核實。C turn `01a12f65-e0bc-7210-b995-8632f4dad7d4` 執行設定為 `gpt-6.1-sol/high`。起始 remaining 7%；本地 preparation 檢查後官方 usage 讀回 used 94%、remaining 6%、ordinaryUsageAllowed=true。依既定低於 7% 自然保存規則，在任何 normal-home／native／model 操作之前保存停止；沒有自行 reset。

**本次沒有操作 normal-home marketplace／plugin registration、trust、MRH binding／settings、auth 或 tier 清單，也沒有執行任何官方 plugin CLI 指令。** 因而不需要還原，也不冒稱做過一次「已變更後的恢復 readback」。C 的暫時共用 surface 保留已解除，B 不因本輪等待 registry 恢復。若 B 之後完成新的 normal 安裝，下次 C 必須以那時的實際狀態為原值，不套用舊 snapshot。

Monitor check ready，pending selection 為 `source_pending/unbound_existing_work`；目前可信 context 沒有 C 的 task_id。沒有冒用 A 的 tracked task、建立新 Goal 或寫第二套 task ledger。

## 原 C 的精確續接點

額度允許依原規則恢復時，使用同一原 C 聊天，不建立新 executor／聊天。先核實最新 D70、B 套件與目前 model／usage；不要再追隱藏 config、修 birth guard 或準備另一個 runtime。

1. 若 B 的共用 advisory 已能在原 App 的受限 test scope 使用，直接選最小真 App 消費者接點，沿用這段 probe 任務；不為取得另一個 label 而重跑舊 native deny/Main。
2. 若仍需固定回覆傳輸 probe，先用 helper `prepare --root <新的自有 probe 目錄> --session-id <原 C 的實際 native session> --cwd /Users/shawn/Code` 準備；不得以 task文字中的路徑作 scope。helper 回傳固定 literal 任務與官方 registration/remove 指令，但**不自動安裝或信任**。normal-home 操作前用正式介面保存精確原 MRH-only registration／trust／disabled 狀態，只操作這個獨立 probe。
3. 沿官方 registration／原生 `/hooks` review 信任確切兩個 definitions；不讀／改 private trust state、不重啟活動中的 App、不更換 binary、不加 dispatcher。若新 Hook 需要原 C 下一回合才載入，這時一次回報 A「準備已完成、具體載入續接點」，不能在尚未安裝的当前保存點假稱只等下一回合。
4. 首次普通委派任務不得預植 expected model，讓原主模型從實際 Hook reason 選自己的可用候選並明示 model／effort，或自行完成未執行任務。分別保存 pending child 被攔住、actual desktop parent 消費、child completion 或 parent continuation 的正式證據。requested/observed、固定 fixture／真分類器、App parent／bundled backend／source 必須分開。
5. 完成後只移除自有 probe，精確恢復並讀回原 MRH-only registration／trust／disabled 狀態，回原 A 解除 B normal-installation 依賴。B 完整套件的最終 App 採用仍是另一個未完成義務，不另造分類器。

這份保存點沒有完成 D70 的 App 接點單元或全產品驗收；真 App Hook、主模型行為、shared artifact 採用與清理／停用驗收仍待續作。

## D70-C-001 傳送狀態：未送達

保存成果 commit `e160d2e` 以原生 `send_message_to_thread` 回報原 local A，遭自動審查拒絕。送出前已核本輪人類來源、原目的地與工作授權；審查仍要求本批本機路徑、提交／helper實作及額度狀態對該聊天的明確傳送確認。既有同類授權核對沒有新增此批 payload 的明確確認，因此沒有再次重送。

技術上沒有 normal-registry restore 依賴，但 A 尚未透過此次工具收到這項 release 與 quota checkpoint。完整保存點保留；待人類明確允許這份 D70-C-001 傳至原 A 後，才沿同一路線續送。不改recipient/tool/channel、不刪改欄位或以其他聊天relay繞過，也不將本地保存視為送達／接受。施工仍遵守 remaining 6% 的原額度停止規則。
