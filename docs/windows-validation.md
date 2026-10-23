# Windows 驗證紀錄

2026-10-21，以 Windows 原生 x64 環境驗證；未使用 WSL。原始宿主紀錄、個人路徑與金鑰不納入 repository。

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

下列為最初 Windows 批次的 91 個測試，涵蓋安裝與衝突保護、ACL／reparse／hardlink、跨程序鎖、逾時與後代清理、含空白路徑、實際 PowerShell／cmd Hook、原生 Claude 註冊接頭、範圍規則、金鑰契約、設定、分級與統計、Jev transport／protocol。它不是後續每個 commit 都重跑的證據。另核對文件連結與 `git diff --check`。

```powershell
$env:PYTHONPATH = 'src'
python -B -m unittest tests.windows.test_setup tests.windows.test_platform tests.windows.test_claude_native tests.windows.test_workspace tests.windows.test_bundle tests.infrastructure.test_secrets tests.infrastructure.test_settings_v2 tests.infrastructure.test_claude_hook tests.advisory.test_engine tests.advisory.test_gears tests.adapters.test_typesafe tests.adapters.test_typesafe_protocol -q
```

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

來源由 `6d10f9f` 接續，Windows 10 Enterprise LTSC 19044 x64、Claude Code 2.1.303。本批沒有重跑狀態卡或整套測試，沒有呼叫 Jev 或模型。

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

零 capabilities 下的 Winsock 失敗仍未解決。增加 `registryRead` 會改變權限範圍，沒有在本批自行加入；Claude profile 保持停用。這是未完成的路由功能，不是完整 Windows Claude 支援。

Mac 的 sandbox-exec 分支保留，共用 initialize 參數與解析的相關檢查在 Windows 執行。Mac 仍需實機驗證版本探測、隔離 initialize、逾時／後代清理及實際 Hook 採用；本批不宣稱 Mac 已重驗。

## 2026-10-23 Hook 啟動預算修正

完整階段觀測確認，PowerShell 與 bootstrap 驗證在 supervisor 的 1 秒起點之前；原 Windows 接頭在起點後先啟動 Python gate，再啟動第二個 Python。一次觀測中 gate 到約 0.63 秒才準備好，第二個 Python 尚未進入 runtime，supervisor 就已逾時。移除第二次啟動後，另一次觀測顯示 runtime 匯入約 0.67 秒、兩次設定驗證約 0.13 秒，仍略超過原預算。

Windows Hook 現在於同一個 Python gate 執行 runtime：先加入 kill-on-close Job，才透過原本的私有管線放行。普通外部 CLI 仍沿用既有 gate；LPAC 不變。runtime 僅在需要分級時載入 engine，只有保留的 Codex 封包事件才載入 packet 處理器；辨識條件與公開 `marked`／`PREFIXES` 契約保留。兩次設定驗證、範圍、明示選型、DB 記錄、故障告警及原有 1／2.5／48 秒期限均未移除或延長。

- 新 gate 與既有程序樹清理共 **4 PASS**，包含 Job 綁定拒絕時不執行目標、同程序執行、UTF-8 stdin 及逾時清除後代。
- 受影響的 supervisor 與路由檢查 **7 PASS、0 FAIL／ERROR／SKIP**：完整性拒絕、PowerShell 含空白路徑、UTF-8 控制管線與期限、Claude 停用／建議／明示選型、DB 故障、設定競態及保留封包拒絕。均使用本機合成事件／分類替身，不代表實際 Jev 或 Claude 子代理採用。
- `27edf8f` 正式安裝世代 `e601b55c557ae31b8be4cbc9` 的 Claude 原生 Pre／Post 均 exit 0、輸出 `{}`，停用 profile 的啟動路徑通過。外層總時間約 1.50／1.41 秒，含 PowerShell 與 bootstrap，不能當成 supervisor 的 1 秒耗時。設定／統計、舊髒檔及其他插件保全已核對；Claude 仍為 enabled=false、export=false。成功 Post 記錄另追加同一案例驗證，不與前述 7 項重複相加。

Mac supervisor 與 sandbox-exec 啟動方式未改。共用 runtime 的匯入時機及 Codex 封包辨識已改；若要宣稱 Mac 實機相容，最小追加驗證是停用 profile 的 Pre／Post、啟用後一般建議與明示選型／Post 記錄，以及保留封包的拒絕或原有處理。Windows 的上述結果不能代替這些 Mac 宿主觀測。

## 2026-10-23 Winsock 原因定位

自行編譯的 x64 Win32 helper 在隔離外呼叫 WSAStartup／WSACleanup 均回傳 0；相同映像經既有零 capabilities LPAC 接頭執行，WSAStartup 回傳 10107。helper 只初始化 Winsock，沒有呼叫 socket、connect、模型或任務。

僅在該 helper 程序內觀測 System32 `ws2_32.dll` 的 IAT，直接記錄到 `RegOpenKeyExA(HKLM, System\CurrentControlSet\Services\WinSock2\Parameters, ...)` 回傳 `ERROR_ACCESS_DENIED (5)`；隔離外相同 API／資源開啟成功。只追加權限欄位的一次 LPAC 觀測取得 `samDesired=0x00020019 (KEY_READ)`、options=0，並未要求 registry 寫入。隔離外原次沒有記錄 mask／options，未重跑，也不宣稱這兩個參數已完成跨環境對照。

觀測沿用 token、零 capabilities、映像、Job 與清理檢查，沒有加 capability 或修改登錄檔 ACL。這將問題定位到此環境的 LPAC Winsock 資源存取，排除了必須先有 Claude 任務、模型解析或 Hook 逾時才出錯；不是 Claude 程序內部的逐呼叫 trace。IAT 僅作診斷，未加入產品。現有安全契約內沒有可直接採用的修法，Claude 清單與實際子代理仍未通過，路由保持停用。

## 2026-10-23 零 capabilities 契約邊界

- 唯讀讀回 `WinSock2\Parameters` 的 ACL：讀取權限只給 BU、AC（ALL APPLICATION PACKAGES）與 `registryRead` capability SID；沒有個別 package SID，也沒有 ALL RESTRICTED APPLICATION PACKAGES。AppContainer token 除一般檢查外還須通過 package／capability 檢查，零 capabilities 的 LPAC 因此必然被拒。
- Claude 2.1.303 為 Bun v1.4.4 Windows 編譯，內含 libuv。libuv 的 `uv_loop_init` 先跑 `uv__once_init` → `uv__winsock_init`，`WSAStartup` 失敗即 `uv_fatal_error` 中止；先前 LPAC stderr `WSAStartup: (10107) ...` 與此格式一致。stream-json initialize 需要事件迴圈，沒有旗標、環境變數或 stdin 型態能略過 Winsock。Node 版同樣使用 libuv。
- 正式入口 `mrh models --host claude` 本日重跑仍為 `claude_catalog_initialize_failed`、exit 2。

結論：在零 capabilities LPAC 契約下，原 initialize 無法成功，除非放寬隔離（`registryRead`、一般 AppContainer 或系統 ACL）或改用另一個清單來源（隔離外 broker、其他 sandbox、版本鎖定的離線快照）。這些都會改變安全邊界或資料語意，須由使用者決定；未做任何一項，Claude profile 維持停用。

## 2026-10-23 registryRead：Claude 清單通過

使用者決定（2026-10-23）以 LPAC 加單一 `registryRead` 取得 Claude 清單，取代先前「零 capabilities」限制。依據：`WinSock2\Parameters` 的 ACL 只對 BU、ALL APPLICATION PACKAGES 與 `registryRead` SID 授讀；Chromium 的 LPAC 沙箱也一律附 `registryRead`。

- 實作：`windows_lpac.isolated(..., capabilities=)` 名稱白名單（僅 `registryRead`），SID 由 `DeriveCapabilitySidsFromName` 推導；懸停 token 必須恰好列出要求的 SID，多、少或不同均不解除懸停。只有 initialize 帶 `registryRead`，`--version` 維持零。
- 讀回：推導的 SID 等於 Winsock 鍵 ACL 的授權 SID；真實 token 零要求時為空清單，要求時恰好該 SID。
- 邊界（原生 payload，`tests.windows.test_lpac` 加 catalog **19 PASS、0 FAIL**）：Winsock 鍵可讀、寫入回 5；`HKLM\SECURITY` 與使用者自建 canary 鍵回 5；Winsock 啟動為 0，但第一個 socket 回 10013（WFP 拒絕）；隔離外檔案讀寫與映像寫入仍 5；環境不繼承。注意 Windows 自己在部分系統／使用者鍵（例如 `HKCU\Software`、`HKLM\SAM` 容器本身）的 ACL 已列 `registryRead`，這些鍵可被開啟，所以 canary 用全新的預設 ACL 子鍵。
- 真實 initialize（鎖定雜湊的 Claude 2.1.303，約 22 秒）取得 default、opus、fable、sonnet、haiku 共 5 個模型，每個支援 low 至 max 五級 effort，無模型請求。
- 其他 Windows 測試：`test_claude_native`、`test_claude_routing`、`test_platform` 共 29 項中 28 PASS；`test_platform` 的跨程序鎖測試在 `-I` 受保護 Python 下子程序找不到 `mrh`，屬測試啟動方式，與本改動無關。

Mac 的 sandbox-exec 分支與此檔無關，不受影響，也未重驗。
### 啟用與真實子代理驗證（2026-10-23）

使用者明確同意所有本機磁碟及 UNC 路徑下的 Claude 專案任務內容可送往 Jev 分類後，執行 `--host claude --all-workspaces --enable`；安裝器回報 Claude routing ready、enabled、export 已允許，Codex profile（revision 6）未被更動。Claude 政策取自驗證清單：Light `haiku:max`、Small `sonnet:high`、Mid `opus:xhigh`、Top 交回主 AI。

在已載入該外掛的 Claude Code 工作階段，用原生 Agent 工具派一個最小、無敏感資料的任務（只回覆 OK）：

- Pre Hook 攔截原委派，Jev 分級為 Light、信心 0.87，建議 `haiku` / `max`，原委派未啟動。
- 依建議重發同一委派後，子代理完成並回報 OK。
- `advice`：一筆 `advise`／`advice_given`，一筆 `preserve`／`advice_reissue`，後者關聯到前者並記錄 haiku／max。
- `children`：一筆，requested `haiku`／`max`，resolved `claude-haiku-5-5`，followed=1。
- `attempts`：Jev 僅一次 `classification_requested`→`requested`→`started`→`returned`；重發沒有再次呼叫分級器，也沒有重複委派。
- 無 Hook 逾時，無 `cli.exe`／host-tools 孤兒程序。

證據分開：子代理本身由宿主以既有權限執行；catalog 探測程序才是 LPAC＋`registryRead`，兩者不互相證明。這只是一次 Light 層級的最小驗證，未涵蓋 Small／Mid／Top、使用者明示指定模型、Post 失敗或 Mac。
### 其餘情境的真實驗證與觀察到的 Hook 逾時（2026-10-23）

同一個工作階段、同一份已啟用的 Claude profile（門檻 0.5，下限由設計限定為 0.5），共 13 個不同任務的原生 Agent 委派，任務內容皆為無敏感資料的合成任務：

| 情境 | 結果 |
| --- | --- |
| Light | `advise`（0.87）→ 依 `haiku`／`max` 重發 → 子代理 followed=1，resolved `claude-haiku-5-5`。 |
| Small | 先有 2 次 `preserve`／`low_confidence`（Small 0.47、0.45，低於門檻，原委派照常執行）；第 4 次任務更明確，`advise`（Small 0.68）→ `sonnet`／`high` 重發 → followed=1，resolved `claude-sonnet-5-5`。 |
| Mid | 先有 2 次 `preserve`／`low_confidence`（Mid 0.50 對 Small 0.38～0.47，信心 0.33）；第 3 次 `advise`（Mid 0.87）→ `opus`／`xhigh` 重發 → followed=1，resolved `claude-opus-5-5`。 |
| Top | 判為 Top（1.00），`continue_main`／`top_main_requested`，委派被攔下並指示主模型自己做，沒有建立替代子代理。 |
| 明示模型 | `model=sonnet`、`effort=high`：`preserve`／`explicit_model`，不呼叫 Jev，原呼叫保留。 |
| 具名角色 | `Explore`：`preserve`／`named_role`，原呼叫保留，子代理記錄 followed=0。 |
| Post 失敗（受控注入） | 背景程序在 Pre 寫入後 30 毫秒對 MRH 自己的 Claude `advice.sqlite3` 取得 `BEGIN EXCLUSIVE` 並持有 12 秒後 `ROLLBACK`。原子代理照常完成、沒有重複委派；該次 `children` 沒有新增列；`PRAGMA integrity_check` 為 ok，advice 9、children 5 與預期一致。 |

**Hook 逾時（未解決）**：兩次 Pre 回報 `hook time budget exhausted`（原呼叫保留，依提示未重試），這兩次沒有任何 `advice`／`attempts` 記錄，也沒有 Post 子代理記錄。另有一次明示模型委派的 Pre 正常但 Post 沒有子代理記錄（單次，原因未能分辨是逾時還是其他）。Post 在非同步 Agent 流程下沒有出現使用者可見的訊息，所以這類遺失不易察覺。

原因觀測：launcher 的第一階段期限是 1.0 秒（自 supervisor 啟動起算），要等 runtime 匯入與兩次設定驗證後回報政策，才延長到 Jev 路徑的 2.5 秒；`launch_seconds` 的 1.0 秒也是 Post 的上限。以無副作用的方式量測 Hook 子程序到回報政策為止的啟動時間（受保護 Python、已安裝 runtime 與設定，不處理事件）：第一批 25 次中位數 0.56 秒、p90 1.09 秒、最大 2.02 秒、4 次超過 1.0 秒；其後兩批各 25 次中位數 0.34～0.36 秒，超過 1.0 秒為 0 與 3 次。匯入約佔 0.22～0.40 秒，其餘是行程啟動，離群值來自行程啟動的環境波動。把預編譯 `.pyc` 放進 pyz 只讓中位數快約 30 毫秒，不能消除離群，已還原，未留在程式中。

沒有提高任何時限。要降低發生率只能放寬第一階段期限或再減少行程數，兩者都會改變既有 Hook 契約，須使用者決定；在那之前，失敗的行為是設計的「保留原呼叫並提示」，且在本次觀察中從未造成重複委派。
### Pre 第一階段期限放寬到 2.5 秒（2026-10-23，提交 `dc71528`，世代 `19f901e64351045cfba74f4f`）

使用者同意只放寬 Windows PreToolUse 的第一階段期限（child 回報第一行政策之前）：由 1.0 秒改為 2.5 秒，與 Jev 路徑視窗相同。實作在 `plugin._windows_launcher` 的轉換，POSIX launcher 文字不變。PostToolUse 仍是 1.0 秒；child 回報的政策仍會取代期限（本機政策 1.0 秒、Jev 2.5 秒、已驗證非 Jev 48 秒皆不變）；完整性、設定二次驗證、Job 綁定與程序清理都沒動。

- 測試：新增 2 項（啟動延遲 1.3 秒時 Pre 取得真實建議、Post 仍約 1 秒被截止；啟動延遲 3.0 秒時 Pre 仍在約 2.5 秒截止且無決策）。舊 launcher 下第一項失敗（1.17 秒即被殺），新 launcher 通過。受影響的 `test_platform`、`test_claude_routing`、`test_claude_native`、`test_claude_catalog`、`test_setup` 共 75 項中 74 PASS；失敗的是前述跨程序鎖測試（受保護 Python `-I` 下子程序找不到 `mrh`，與本改動無關）。
- 真實委派，循序 4 組：Pre 建議（Light 0.83～0.87）→ 重發 → 子代理完成，4 組全部有 `advice_reissue` 關聯與 Post 子代理記錄（followed=1），0 逾時。
- 真實委派，同時 6 組（12 個 Pre、6 個 Post 並行，負載遠高於一般使用）：第一階段 Pre 6/6 成功分級，0 逾時。但仍維持 1.0 秒的兩處在負載下失敗：明示模型的重發 Pre（本機政策 1.0 秒）6 個中 3 個回報「hook time budget exhausted」，Post 6 個只記到 2 個。逾時時原呼叫皆保留、子代理照常完成、沒有重複委派或孤兒程序，但這些事件缺少記錄或關聯。

結論：第一階段放寬解決了原本最常見、也最影響使用者的失敗（分級前被殺、整個建議流程消失），一般循序使用已不再出現逾時；並行負載下，每個被採納的建議之後的明示重發 Pre（本機 1.0 秒政策）與 Post（1.0 秒）仍會逾時。進一步放寬這兩處屬於另一項時限變更，未經使用者同意，沒有做。