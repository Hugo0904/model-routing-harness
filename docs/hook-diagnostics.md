# Hook 診斷收集

Mac 與 Windows 使用同一個本機診斷開關。新安裝預設關閉；開啟後會自行管理目前使用者的收集器與登入啟動，不需要另開終端機守著。兩台各自控制，沒有雲端上傳或跨機同步。

```sh
mrh ctrl diagnostics on
mrh ctrl diagnostics status --json
mrh ctrl diagnostics off
mrh ctrl diagnostics clear
```

`on` 會確認收集器已就緒才成功。重複 `on` 保留已就緒的同一服務；`status` 分開顯示 `enabled`、`collector`（off／ready／degraded）、`ready`、登入啟動註冊及完整日誌路徑。`enabled` 是期望狀態，不能代替 `ready`。診斷控制獨立於路由設定，即使 routing settings 無法解析，也能查看或停止收集器。

`off` 先禁止新發送、撤掉 endpoint，再停止及移除自有登入項，保留日誌。`clear` 只在關閉時執行，只清除已辨識且通過 ownership 檢查的三個診斷日誌，不刪設定、統計、packet、備份、驗收證據或其他檔案。開啟時執行 `clear` 會提示先 `off`。

## 位置與保留

控制資料位於 `locations.default_config_root()/hook-diagnostics`，與路由 settings schema 分開。正式日誌位於 `locations.runtime_root()/diagnostics/hook-observation`，以 `status` 回報的完整路徑為準，不依賴工作目錄或 checkout，也不回退到系統 tmp。

預設 Mac 日誌是 `~/Library/Caches/model-routing-harness/diagnostics/hook-observation/`；Windows 位於目前使用者的 MRH ProgramData runtime 內。控制目錄、endpoint 與日誌沿用 MRH owned／私有 ACL 邊界。endpoint capability 不會出現在 status 或日誌。

日誌只有 `events-0.jsonl`、`events-1.jsonl`、`events-2.jsonl`，每檔最多 1 MiB，最多三檔；啟動及寫入時移除超過七天的自有日誌，不另設清理排程。不認識或 ownership 不安全的檔案保留並回報錯誤，不擴大清理範圍。

每行只保存接收時間、版本、codex／claude 平台，以及 `stage`、內建 exception class、整數或 null 的 `winerror`／`child_rc`、受限整數 `elapsed_ms`。不保存輸入、輸出正文、任務名稱、例外訊息、堆疊、環境、路徑、憑證或 capability。明確的採用 self-check 使用固定 `self_check` 階段，收件驗證後由獨占 writer 只移除這種標記，保留其他自然故障紀錄；它不代表真實故障已發生。

## 失敗不影響原工作

既有 Hook 的 producer 只在失敗時，以 nonblocking IPv4 loopback UDP 盡力傳送一筆安全紀錄。每程序最多一次，原五欄 frame 至多 192 bytes，含 envelope 至多 512 bytes，每次 Hook 至多父子兩筆。producer 啟動最多讀一份 2 KiB endpoint descriptor；缺失、格式錯誤、owner／ACL 不安全、無 receiver 或 send failure 都直接放棄，不重試、不等 ACK、不等磁碟、不建立程序、不改 stdout、exit 或 deadline。

收集器只收 127.0.0.1、正確 capability／版本及完整白名單資料；錯誤或超長資料直接丟棄，不能寫 raw payload。診斷 UDP 取代測試版的 stderr 傳輸，保留 Python／raw stderr 的隱私保護，不把 runtime stderr 送回 Host。清理觀測只在清理成功後恢復原錯誤階段；清理本身拋錯仍原樣傳遞，不吞錯、不改 Job、control FD／handle 或清理順序。

收集器持有獨占 owned writer lock，避免多 writer。檔案錯誤讓診斷 `degraded`，原 Hook 仍繼續；修復條件後的正常收件可恢復 ready。UDP 不承諾不丟資料或零成本；讀 descriptor、序列化及傳送仍有少量開銷。

## 登入、更新與移除

Mac 使用目前使用者的 `org.model-routing-harness.hook-diagnostics` LaunchAgent；Windows 使用目前使用者、Interactive／Limited 的 `ModelRoutingHarness-HookDiagnostics-<SID>` 登入 Scheduled Task。僅開啟時存在，不提權、不修改其他登入項，不定時執行測試，也不要求登出或重開機。停止依賴已驗證的 native service identity 與 owned 配置，不按任意 PID 找程序終止。

正常 installer 產生並核對 launcher／runtime／manifest。升級或 rollback 在原子切換 generation 後沿用 desired enabled，透過同一 owner 重新綁定 receiver；新安裝仍預設 off。診斷失敗回報 degraded，不回滾或改動可用的路由資料。登入項建立或啟動失敗會回復該次診斷變更，保留原啟用配置；owner 不明或原生登入政策拒絕時不繞過。

Mac 的原卸載流程會先關閉診斷，再處理 Hook／安裝移除；關閉失敗就不拆除 receiver 所需安裝。Windows 不另建卸載框架：先 `mrh ctrl diagnostics off`；如需移除自有日誌，再 `mrh ctrl diagnostics clear`。兩者都保留正式路由資料。

## 驗證邊界

已接受的 DIAG22 r2 階段、白名單序列化、stderr 隱私及 cleanup guard 證據沿用，沒有重跑 Windows 九組故障矩陣。新增證據僅覆蓋 UDP／receiver、控制與登入生命週期、正常 installer 接線，以及 Mac／Windows 各自的正式啟用讀回。採用證據使用同一 producer 的安全 self-check，確認收件後清除測試標記並保持 on，不呼叫 provider、DB 或注入真實故障。

觀察範圍從 Hook supervisor 與 child Python 已啟動後開始。OS 無法啟動 Python、Windows bootstrap 在已驗證 launcher 前失敗不在功能邊界；runtime 自行捕捉並轉為正常 JSON 的錯誤也不保證會留下例外紀錄。歷史 editable Hook 回 `{}` 的根因仍未知，不用本次整合改判原 FAIL。正式啟用完成後，只在日常使用中持續觀察，不把重現歷史故障、壓測或其他改善列為後續完成條件。
