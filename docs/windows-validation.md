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
