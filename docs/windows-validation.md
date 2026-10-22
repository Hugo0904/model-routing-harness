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

UNC 完成路徑規則測試，沒有真實網路分享的實機結果。Windows Claude catalog、訂閱分級器、Codex packets 與 Gemini 保持不可用，詳見 [相容性](compatibility.md)。目前 Codex 原生加密的 `message` 不能直接供分類，依既有契約使用可讀的 `task_name`。

後續另有使用者 PATH、專案根綁定與 supervisor 的差異驗證，以及實際安裝與一般命令讀回；各批沿用自己的來源與回執，沒有合併成「重跑最初 91 項」。

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
