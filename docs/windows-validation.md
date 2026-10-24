# Windows 驗證紀錄

本頁按日期保存 Windows 原生 x64 的驗證，未使用 WSL；各批版本、樣本及失敗分開，不合併為全平台通過。最初環境為 2026-10-21，後文的停用／缺證據只描述當時狀態。後續直寫診斷採用見[驗證摘要](validation.md#2026-10-25-直寫診斷採用程式-13b651f)。原始宿主輸出、個人路徑與金鑰不納入 repository。

| 項目 | 結果 |
| --- | --- |
| 環境 | PowerShell 7.6.5、Git 2.53.0.windows.3、CPython 3.11.9 x64。 |
| 宿主 | Codex 0.163.0-alpha.10.2、Claude Code 2.1.303，分別確認 CLI 登入；不把登入當成模型使用證據。 |
| 安裝 | 私有 CPython、已簽章宿主複本、不可變安裝代與 manifest 完整性檢查通過。 |
| 重跑、更新與退版 | 在真帳號重跑、退回前一相容安裝代，再更新回最新版；設定、SQLite 統計與其他宿主設定的比對值均相同，金鑰及 Codex 信任保留。 |
| 原生 Hook | Codex 與 Claude 原生插件均可註冊及讀回；Codex 的兩個 Hook 由使用者審閱後，公開介面回報 `trusted`。 |
| 金鑰 | 使用者在原生密碼欄輸入；Credential Manager 查詢只回報已設定，未輸出金鑰。 |
| 外送範圍 | 由使用者明確允許全部專案，保存為 Windows `allowed_workspaces: ["*"]`；Claude 獨立 profile 仍停用及禁止外送。 |
| Jev | 中文合成任務實際呼叫成功，回應版本 `jev-1.13.0`；此證據與安裝檢查分開。 |
| 實際子代理採用 | 原生 Codex 合成任務經真實 Jev 分為 Small，記錄 `advice_given` 及 `advice_reissue`；MRH 與子代理 session 均確認 `gpt-6.1-sol / high`，結果為 `MRH_NATIVE_OK`。MRH PostToolUse 自身未回報 resolved model，實際模型由該子代理 session 另行核對。 |
| Mac | 這份紀錄不含 Mac 實機結果。POSIX launcher 與原版逐位元組相同，runtime lock、既有授權與版本檢查保留。 |

最初 Windows 批次有 91 個測試，涵蓋安裝與衝突保護、ACL／reparse／hardlink、跨程序鎖、逾時與後代清理、含空白路徑、實際 PowerShell／cmd Hook、原生 Claude 註冊接頭、範圍規則、金鑰契約、設定、分級與統計、Jev transport／protocol。它不是後續每個 commit 都重跑的證據。另核對文件連結與 `git diff --check`。

UNC 完成路徑規則測試，沒有真實網路分享的實機結果。當時 Windows Claude catalog、訂閱分級器、Codex packets 與 Gemini 保持不可用；Claude 後續進度見下節，其他邊界見 [相容性](compatibility.md)。目前 Codex 原生加密的 `message` 不能直接供分類，依既有契約使用可讀的 `task_name`。

後續另有使用者 PATH、專案根綁定與 supervisor 的差異驗證，以及實際安裝與一般命令讀回；各批沿用自己的來源與回執，沒有合併成「重跑最初 91 項」。

## 2026-10-22 Windows 離線回歸

在 Windows 10 x64、CPython 3.11.9 的隔離副本驗證 `0007b77`，執行 `tests.windows` 的 bundle、claude_native、path、platform、setup、workspace 六個模組，共 68 個案例，涵蓋目前的 `source_identity` 與測試暫存目錄實作。

| 執行 | 通過 | 失敗 | 錯誤 | 略過 | 耗時 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 首次六個模組 | 51 | 17 | 0 | 0 | 73.547 秒 |
| 修正離線 runner 後，只重測原失敗案例 | 17 | 0 | 0 | 0 | 48.343 秒 |

首次 17 項失敗都發生在安裝就緒檢查：測試使用假的宿主接頭，但模型清單查詢仍找到真實 Codex，嘗試執行 `--version` 時被 runner 攔截。修正僅在一次性 runner 將 `public_models` 替換為拋出 `CatalogError("host_unavailable")`，走既有的清單不可用處理；產品程式、測試案例、斷言與真宿主攔截均未更動。這不提供真實模型清單查詢的證據。

原次 51 項通過結果沿用，合計 68 個案例均有通過證據，並非同一輪 68 項全數通過。所有測試保留 HOME／state 暫存導向與網路、真實憑證讀取限制；未呼叫 Jev 或模型，未更新正式安裝。這批不包含 Mac 重測、Windows 手動移除或真帳號安裝的重新驗證。

後續將清單不可用的替身納入 `tests/windows/test_setup.py`，並在既有來源身分案例補上兩項檢查：文件與 Git commit 改變時指紋不變，程式內容改變時指紋會改變。以 `0007b77` 加上這份測試修正，在同一 Windows 隔離環境只執行原 17 項安裝案例及加強後的來源身分案例，結果為 **18 PASS、0 FAIL／ERROR／SKIP**，耗時 44.235 秒。這次 runner 未提供模型清單替身，隔離由正式測試本身完成。本批未修改產品程式，不代表同時進行的分析資料或 `mrh status` 新功能已通過 Windows 驗證。

## Mac 修正後的 Windows 差異驗證

針對 Mac PATH、skill 管理與目標旁原子中介檔的修正，另跑了五項 Windows 原生隔離案例，結果為 **4 PASS、1 SKIP、0 FAIL／ERROR**。原 unittest 輸出耗時 0.617 秒，外層量測 0.625 秒。

| 案例 | 結果 |
| --- | --- |
| Claude 設定目錄與 CLI 目錄別名 | PASS |
| MRH 自改 skill 明確覆寫前的外部復原副本 | PASS |
| 原子發布失敗時保留原件並清除中介檔 | PASS |
| Windows 宿主複本於目標旁發布、複製失敗清理 | PASS |
| 外來／額外／連結內容的合併拒絕案例 | SKIP：`symlinks unavailable` |

SKIP 對應 `SkillCompletionTests.test_force_never_accepts_foreign_extra_or_linked_content`；整個案例不算 PASS，連結拒絕仍缺此 Windows 原生證據。沒有為補滿數字更動系統權限或重跑。

這批案例對應的 Windows 產品程式沒有因 Mac 修正而改變，所以沒有為純 Mac 的差異重跑。

這批使用隔離測試目錄及合成檔案／簽章回應，不執行假 exe，也不動真 skill、PATH、憑證或宿主設定。Jev／模型呼叫、網路及子程序執行嘗試均為 0。正式安裝、既有修改、設定、DB 與 Hook 的前後雜湊一致；隔離副本、腳本及空測試備份根移除後均讀回不存在，原始輸出與清理回執保留。

這批結果只涵蓋上表五項案例，不代表 Windows 的完整重新驗證。既有的 Mac 實機證據沿用原版本與來源；Windows 測試與隔離 shell 測試也不能代替 Mac 真實帳號的採用結果。

## 2026-10-22 Claude Windows LPAC 與獨立 profile

來源由 `6d10f9f` 接續（`6a90435` 的 LPAC／每宿主就緒判斷），Windows 10 Enterprise LTSC 19044 x64、Claude Code 2.1.303。本批沒有重跑狀態卡或整套測試，沒有呼叫 Jev 或模型。

| 邊界 | 結果 |
| --- | --- |
| 原探針 | 原檔雜湊相符，沒有重跑；原次 CreateProcessW 回報 WinError 2，未送 initialize。 |
| LPAC 讀回 | 新接頭在懸停狀態核對 token、零 capabilities、package SID、低完整性、Job 與映像。另以 AccessCheck 確認自己的 SID 可用、ALL APPLICATION PACKAGES 不可用；不依賴本機不接受的 token class 46。 |
| 原生拒絕與清理 | `tests.windows.test_lpac` **7 PASS、0 FAIL／ERROR／SKIP**。原生 C payload 確認隔離外合成檔案讀寫及映像寫入遭拒、環境不繼承、隔離內可寫、輸出上限、matching metadata／逾時清理、失敗 assignment／token 檢查不解除懸停，以及 profile 刪除讀回。 |
| 程序樹 | 此系統的 LPAC 直接建立子程序回報 Access Denied；新路徑沒有成功建立後代程序的實機證據。既有 Job 接頭未改動，沿用其後代清理測試；不把直接拒絕冒稱新接頭成功執行後代程序。 |
| 網路 | 原生 payload 載入 Winsock 後，WSAStartup 回報 10107，未進入 socket/connect；這證明本次網路路徑不能啟動，沒有成功初始化 Winsock 後的連線拒絕證據。 |
| Claude 清單 | 真正 LPAC 可讀 `--version`，initialize 卻在 WSAStartup 10107 結束，**尚未取得模型清單**。曾回傳 5 模型的早期修改探針錯把 ChildProcessPolicy 當作 LPAC 屬性，只是一般 AppContainer，不能算 LPAC 通過。正式常數已修正為 `0x2000f`，未退回較弱隔離。 |
| Windows catalog 契約 | **5 PASS**：initialize-only 封包、錯誤／逾時／EOF 拒絕、映像變更拒絕、Claude receipt hash，以及既有 Codex discovery 契約。共用 initialize 解析另有 **4 PASS**。 |
| 安裝器與獨立設定 | 模型清單、policy、key、scope、enabled、routing 改為每個宿主分開驗證。兩模組首輪 48 項中 44 PASS，4 項新增 fixture 缺 ownership marker；補齊後只重跑相關 8 項全通過，最後快照檢查補強後再跑 4 項全通過。均使用替身，不能代替真實清單及啟用。 |
| Hook／路由契約 | Windows 合成 profile **1 PASS**：停用時不分類、啟用 fixture 的 Claude 建議與明示選型保護。既有 POSIX runtime 3 項因 `/` 範圍 fixture 不適用 Windows 而未通過，沒有刪除平台檢查；改用獨立 Windows fixture 證明該邊界。 |
| Claude 實際子代理 | 未執行，未證明採用。 |

本批的零 capabilities Winsock 失敗未解決，Claude profile 當時保持停用，不能稱完整支援。後續由使用者批准的 registryRead 修正及實際採用另列於下節，不回寫為本批通過。

本批僅在 Windows 檢查共用 initialize；sandbox-exec 分支保留，未提供 Mac 實機重驗證據。後續 Mac 結果見[Mac 紀錄](mac-handoff.md)，兩者不互相替代。

## 2026-10-23 Hook 啟動預算修正

觀測顯示 PowerShell／bootstrap 在 supervisor 起點之前；起點後的 Python gate 約 0.63 秒才就緒，第二個 Python 尚未進 runtime 就被原 1 秒期限截止。`27edf8f` 改成同程序 gate：先加入 kill-on-close Job，再由私有管線放行；外部 CLI 與 LPAC 保留原路徑。engine 延至需要分級才匯入，packet 模組只在保留事件匯入，`marked`／`PREFIXES` 契約不變。另次匯入約 0.67 秒、兩次設定驗證約 0.13 秒，仍可能超原預算；此修正沒有改 1／2.5／48 秒期限或移除任何安全／記錄檢查。

| 證據 | 結果與範圍 |
| --- | --- |
| gate／程序樹 | 4 PASS：Job 綁定拒絕不執行、同程序、UTF-8 stdin、逾時清後代。 |
| supervisor／路由 | 7 PASS、0 FAIL／ERROR／SKIP；完整性、含空白 PowerShell 路徑、控制管線、政策期限、停用／建議／明示保護、DB 故障、競態及保留封包。合成事件與替身，不是 Jev／子代理採用。 |
| 正式停用路徑 | 世代 `e601b55c557ae31b8be4cbc9` 的 Claude 原生 Pre／Post exit 0、`{}`。外層 1.50／1.41 秒含 PowerShell／bootstrap，不能當 supervisor 1 秒耗時；設定／統計／舊髒檔／其他插件保全，enabled=false、export=false。成功 Post 另補同案例，不與 7 項重複加總。 |

Mac supervisor／sandbox-exec 啟動未改；共用匯入與 packet 辨識已改，這批 Windows 結果不代替後續 Mac 原生觀測。

## 2026-10-23 Winsock 原因定位

x64 Win32 helper 在隔離外 WSAStartup／WSACleanup 均為 0；同映像在零 capabilities LPAC 內為 10107，未呼叫 socket／connect／模型／任務。只在 helper 內觀測 System32 ws2_32.dll 的 IAT，直接看到 `RegOpenKeyExA(HKLM, System\CurrentControlSet\Services\WinSock2\Parameters, ...)` 回 5；隔離外相同資源可開。追加欄位的 LPAC 觀測為 `samDesired=0x00020019 (KEY_READ)`、options=0，未要求寫入；隔離外原次未記 mask／options，未重跑補對照。

token、零 capabilities、映像、Job／清理維持，未加權限或改 ACL。這定位了此環境的 Winsock 資源存取，不依賴先有 Claude 任務、模型解析或 Hook 逾時；不是 Claude 內部 trace。IAT 僅作診斷，未加入產品，當時清單與實際採用仍未通過。

## 2026-10-23 零 capabilities 契約邊界

Winsock 鍵 ACL 只授讀給 BU、AC（ALL APPLICATION PACKAGES）及 registryRead SID，沒有個別 package SID 或 ALL RESTRICTED APPLICATION PACKAGES；零 capabilities LPAC 無法通過 package／capability 檢查。Claude 2.1.303 為 Bun 1.4.4 Windows 編譯，libuv 的 `uv_loop_init → uv__once_init → uv__winsock_init` 會初始化 Winsock，失敗即 uv_fatal_error，與 stderr 10107 一致。initialize 需要事件迴圈，無旗標／環境／stdin 型態可略過，Node 版也用 libuv。當日正式 models 入口仍 exit 2、claude_catalog_initialize_failed。

當時未採取 registryRead、一般 AppContainer、系統 ACL 修改或隔離外 broker／其他 sandbox／版本鎖定快照：它們都改變安全或資料契約。這是舊零 capabilities 契約的限制，後續批准如下，不能把原次失敗改判。

## 2026-10-23 registryRead：Claude 清單通過

使用者批准 LPAC initialize 加單一 registryRead（`0983c1f`），取代舊零 capabilities 限制；--version 仍零。依據是 Winsock ACL 的授權 SID，Chromium LPAC 也附該 capability。名稱白名單只允許 registryRead，SID 由 DeriveCapabilitySidsFromName 推導；懸停 token 必須恰好等於所求 SID，多／少／不同均不解除懸停，讀回亦吻合。

| 證據 | 結果與界線 |
| --- | --- |
| 原生拒絕 | LPAC＋catalog 19 PASS、0 FAIL。Winsock 鍵可讀、寫回 5；HKLM\SECURITY、自建預設 ACL canary 鍵及隔離外檔案讀寫／映像寫入回 5，環境不繼承。Winsock 啟動 0，第一個 socket 回 10013（WFP）。Windows 部分既有鍵如 HKCU\Software／HKLM\SAM 容器本已授 registryRead，不能拿它們當私有 canary。 |
| 真清單 | 鎖定 hash 的 Claude 2.1.303，約 22 秒取得 default／opus／fable／sonnet／haiku，各 low～max 五級 effort；沒有模型請求。 |
| 其他 Windows 測試 | claude_native、claude_routing、platform 共 29 項中 28 PASS；跨程序鎖在受保護 Python -I 下子程序找不到 mrh，屬 runner 邊界，後續標準 PYTHONPATH 通過另記。 |

本批未重驗 Mac sandbox-exec。catalog 的 LPAC 不代表子代理本身在 LPAC 執行。

### 啟用與真實子代理驗證（2026-10-23）

使用者允許所有本機磁碟與 UNC 的 Claude 專案任務送 Jev 後啟用；routing ready、enabled、export 允許，Codex revision 6 未變。Claude 政策為 Light haiku:max、Small sonnet:high、Mid opus:xhigh、Top Main。

首次原生最小任務：Jev Light/0.87，Pre 攔截原委派並建議 haiku/max → 重發後 child completed/OK。advice_given 與 advice_reissue 關聯，children requested haiku/max、resolved claude-haiku-5-5、followed=1；attempts 只有一次 classification_requested→requested→started→returned。沒有重複分類、派工、Hook 逾時或 cli.exe／host-tools 孤兒。這一份證據只涵蓋 Light；catalog 隔離與子代理宿主權限、requested effort 與獨立實際 effort 分開。

### 其餘情境的真實驗證與觀察到的 Hook 逾時（2026-10-23）

同一 Claude 工作階段／profile，門檻 0.5（設計下限），13 個不同合成任務的結果：

| 情境 | 結果 |
| --- | --- |
| Light | 0.87 → haiku/max 重發，resolved claude-haiku-5-5、followed=1。 |
| Small | 先有低信心 0.47／0.45 保留原呼叫；第 4 次任務更明確，0.68 → sonnet/high，resolved claude-sonnet-5-5、followed=1。 |
| Mid | 先兩次 Mid 0.50 對 Small 0.38～0.47，信心 0.33，保留原呼叫；第 3 次 Mid 0.87 → opus/xhigh，resolved claude-opus-5-5、followed=1。 |
| Top | 1.00、continue_main／top_main_requested，攔下委派並交主模型，沒有替代 child。 |
| 明示／具名 | sonnet/high 為 preserve／explicit_model，無 Jev；Explore 為 preserve／named_role、followed=0。 |
| Post 失敗注入 | Pre 寫入後 30ms 對自有 DB BEGIN EXCLUSIVE 12 秒後 ROLLBACK。原 child 完成、無重複派工，該次 children 未新增；integrity_check ok，advice／children＝9／5，符合預期。 |

原 1 秒期限下兩次 Pre 回報 time budget exhausted，未重試，沒有 advice／attempts／Post 記錄；另一次明示模型 Pre 正常但 Post 無列，原因無法區分逾時或其他。非同步 Post 沒有可見訊息，不能由無警告推論沒有遺失。

啟動觀測不處理事件：首批 25 次 中位數 0.56 秒、第 90 百分位 1.09、最大 2.02，4 次超 1 秒；另兩批各 25 次 中位數 0.34～0.36，超時各 0／3 次。匯入 0.22～0.40 秒，其餘程序啟動波動；pyz 加 pyc 僅快約 30ms，未消除離群，已還原。當時未提高期限，原呼叫保留且未重複派工；後續授權分兩階段如下。

### Pre 第一階段期限放寬到 2.5 秒（2026-10-23，提交 `dc71528`，世代 `19f901e64351045cfba74f4f`）

僅 Windows Pre 等待首行政策由 1.0 改 2.5 秒；當時本機政策及 Post 仍 1 秒，Jev 2.5 秒／已驗證非 Jev 48 秒與完整性、設定二次驗證、Job／清理不變，POSIX launcher 文字未改。

| 證據 | 結果 |
| --- | --- |
| 回歸 | 新增 2 項：1.3 秒啟動時 Pre 得建議、Post 仍約 1 秒截止；3 秒啟動時 Pre 約 2.5 秒截止且無決策。首項舊版 1.17 秒被殺、新版通過。platform／claude_routing／claude_native／claude_catalog／setup 五模組 75 項中 74 PASS，另一項為上述 -I 跨程序鎖 runner 問題。 |
| 循序 4 組 | Light 0.83～0.87，建議→重發→child 完成，4/4 關聯及 Post followed=1，0 逾時。 |
| 並行 6 組 | 12 Pre／6 Post：首階段 6/6 分類、0 逾時；本機 1 秒重發 Pre 僅 3/6 成功，Post 僅 2/6 記錄。原呼叫／child 仍完成，無重複或孤兒，部分關聯缺失。 |

這只解決原第一階段，不代表當時並行重發／Post 已修好。

### 本機 Pre 重發 2.5 秒、Post 2.0 秒（2026-10-23，提交 `8a2fcee`，世代 `7da51e233a0e4fb94c3bd5d2`）

第二次批准僅 Windows：本機政策 Pre 1→2.5 秒、Post 1→2 秒，launcher 接受政策 2.0；Claude Post 宿主 2→5 秒，因 PowerShell／bootstrap 另耗約 1～1.5 秒。Jev 2.5 秒／非 Jev 48 秒、SQLite 等待、安全／Job、當時 Codex 宿主 2 秒及所有非 Windows 值不變。

- 回歸新增 3 項、改 1 項：1.3 秒啟動成功、3 秒 Pre 截止、本機 Pre／Post 在 3.5 秒啟動時各 2.5／2 秒截止，非 Windows 仍 1 秒、Claude 宿主 5 秒；新案例舊版失敗，共用 hook_budget 斷言改依平台。受影響項目除 -I runner 鎖案例與 13 項原有 POSIX 假設失敗外通過，這些原 HEAD 也同樣失敗。
- 既有 Claude 工作階段仍載舊宿主 2 秒：並行 6 組建議 6/6、重發 Pre6/6、Post2/6。**全新工作階段**載入 5 秒後，同負載建議／重發／Post 皆 6/6、followed=1，6 child 完成，無逾時／重複／遺留程序。

此樣本只涵蓋 Light；當時 Codex 宿主仍 2 秒，不能推論 Codex 高並行。Mac 行為值未改，共用模組的 Mac 驗收另記。

### Codex 共用 launcher 實測與 `setup.ps1` 修正（2026-10-23）

| 項目 | 結果與界線 |
| --- | --- |
| Codex 0.163.0-alpha.10.2 | 世代 7da51e233a0e4fb94c3bd5d2，並行 4 child 全部完成；5 Pre（4 通過、1 攔下 Light0.57→gpt-6-luna/max）及 4 Post 均記錄，0 逾時。首次誤用 ephemeral，宿主因缺 rollout 拒絕 spawn，非 MRH；該次 Pre 無逾時、重發／Post followed=1。當時 Codex 宿主仍 2 秒，較小樣本不證明高並行。 |
| PowerShell 5.1 | `9d50280` 將 Python 探測字串改單引號，避免 5.1 剝原生引數雙引號而誤報無 Python；真 powershell.exe 測試證明舊寫法失敗。setup --check 實讀 installed／integrity verified／routing ready，runtime 未變、未重裝。 |
| 跨程序鎖 | 文件標準 PYTHONPATH 方式通過；前述 -I 子程序無 mrh 是 runner 啟動問題，保留原批失敗，不改成同輪全過。 |

### Codex Post 5 秒、設定讀取競態與 Small／Mid 並行（2026-10-23，提交 `212b002`、`0aac0c0`，世代 `0bf5fa9d0ab28976ad98cc98`）

| 變更／觸發 | 直接證據與限制 |
| --- | --- |
| Codex 宿主 Post 5 秒 | 212b002 的 codex_hook_timeout Windows5／其他平台 2，函式與生成 JSON 均有測試。安裝因定義 hash 改變呈 unverified／native_hook_trust，使用者原生審閱後 trusted、routing ready；config 差異僅 Post trusted_hash 與 marketplace 指標。信任後 4 child／4 Pre／4 Post 全記錄、無逾時；Jev Small0.32～0.47 皆低於 0.5 而保留原呼叫，不能當成採用建議的並行證據。 |
| Claude Small／Mid | 新工作階段 3 Small＋3 Mid：5 建議（Small0.68／0.69、Mid0.75×3）→重發 5/5→Post5/5、followed=1，sonnet/high×2、opus/xhigh×3。Mid child 因 runner 給的 Bash 權限太窄無法執行 Python，與 MRH 無關。 |
| 第 6 個 Pre settings unavailable | 無記錄、原呼叫繼續。owned.verify 列目錄後 lstat 時 SQLite 側檔消失，FileNotFoundError 被當 settings_unowned。180 次單純並行讀全成功；私有副本 3 讀取＋3 SQLite 開關程序重現，修前約 4100 次中 10 次（約 0.24%），修後 3776 次為 0。0aac0c0 只在 Windows 略過消失的-wal／-shm，未知檔名／其他消失檔仍拒絕，非 Windows 不變；新測試舊版失敗。 |
| 受影響測試 | 98 項中 97 通過，另一項為-I runner 跨程序鎖，標準 PYTHONPATH 通過。確定性回歸與壓力對照支持該修正，少量實測不能證明不再發生或估日常故障率。 |

Windows 非 MRH 的 model、model_reasoning_effort、service_tier 與 10 月 22 日備份不同；安裝器不寫這些鍵，寫入者／時間未證實。舊 Claude 工作階段重載才採用新宿主期限；Mac 結果見[Mac 紀錄](mac-handoff.md#5-未決項目與已解決項目)，不互相替代。

## 2026-10-24 雙模式與 packets 正式採用（程式 `670272f`）

一般打包與 dev＋packets 分開驗證：經驗證 bootstrap、獨立 runtime、PEP 660 純路徑連結及 site-free Python 保留；一般模式不依賴 checkout，外部設定／統計／憑證／資料引用不自動搬移。LPAC capabilities、Job、完整性與時限不變，設計見[開發指南](development.md#本機開發安裝--dev)。

分批保留 70 PASS／1 預期 SKIP；後續 workspace gate、兩個 legacy 與不靠 GC 的真 SQLite 關閉四項 PASS，再加 staging 重複 UUID 修正後 lost-ACK PASS。補驗未再有 staging 深層建檔錯誤，不表示任意長路徑都支援。

**77 個唯一 ID＝75 PASS、1 FAIL、1 預期 SKIP**，不是同一輪全過。原不完整事件的 dev Hook FAIL 原因未定；插樁 marker 成功與五次失敗限定捕捉未重現只屬診斷，不增加原生 PASS、不改判原 ID、不證明 fixture 錯誤或產品已有確認缺陷／修復。

另一次未插樁、完整合法普通事件精確取得 dev Hook 標記（0.438 秒）；來源移走後 CLI exit2 並明確回報來源不可用，切一般模式且來源仍移走時 help exit0。啟動鏈／Job／2.5 秒期限保留，fixture 清理成功；這是正常輸入及模式邊界的補證，不覆寫原 FAIL。

當次 development＋packets 正式採用：兩宿主註冊／routing、Codex trusted／packets、CLI／Hook 的 manifest／binding／descriptor／PTH／來源／runtime 讀回一致，pending 空、無待恢復交易。repo 外真安裝入口 check／status／ctrl 成功，安裝 107.61 秒，未重跑 provider、真派工或產品測試。來源為合格受保護 checkout；未放寬來源條件、改 workspace ACL／PowerShell 政策或另建 clone，只有實際 dev_source 修改會生效。

兩 profile、指標、白名單、非 MRH 設定語意、PATH／憑證存在狀態及兩 SQLite schema／全部原列重數保全，不宣稱 DB bytes 或總列數相同；舊 runtime／安裝代／Git 保留、自有暫存清理，無 stage 異常。Mac 同批保全見[驗證摘要](validation.md)。

### 既定發布模式：packaged＋packets（正式切換已完成）

安裝範圍僅使用者本機 Mac 開發環境用 dev，Windows 及其他環境用 packaged＋packets；前次 Windows dev 屬技術歷史。`8d74957` 從乾淨已發布來源沿原參數省略 dev，完成一次正式切換：execution_mode=installed、source 空，app/mrh.pyz 與兩 Hook runtime 匹配，無 dev_source／editable；manifest／獨立 runtime 一致。兩宿主註冊／routing、Codex 信任／packets 就緒，Hook bytes 保留，pending 空、無待恢復交易。當時保留的 checkout 供更新，不是執行依賴，修改不再即時生效。

repo 外真入口 check／status／ctrl 各 exit0；安裝 139.906 秒、check31.328、status0.797、ctrl0.672，各一次。原設定、兩 SQLite schema／原列重數與其他宿主語意均保全、無 stage 殘留；未重跑測試／provider／真派工，原不完整事件 FAIL 原因仍未定、不改判。以上來源／備份保留描述當次結果，之後依明確授權清除用完副本不影響原證據；模式操作見[開發指南](development.md#本機開發安裝--dev)。
