# 疑難排解

Windows `project_root_not_ready` 表示綁定的原始碼根缺失或未通過既有路徑／權限檢查。先核對 `--check --json` 的 `project_root` 與各宿主欄位，恢復原本授權的目錄狀態後再重跑原安裝指令；不要刪除正式安裝代、放寬安全檢查，或把單機問題當成所有使用者都要搬移 checkout 的要求。

先在原始碼目錄執行對應平台的 `setup.ps1 --check --json` 或 `./setup --check --json`，再從一般目錄執行 `mrh status`。安裝、命令解析、Hook 信任、金鑰、政策與外送許可分開判斷；其中一項成功不代表全部就緒。

## 已安裝，為什麼沒有分級？

新 profile 預設停用且禁止外送。確認支援的平台、原生 Hook 信任、金鑰、候選政策與允許外送的範圍，再依[安裝指南](install.md)啟用。Windows Claude profile、訂閱分級器、Gemini 與 Codex packet 的限制不能靠手動設定略過。明示模型／effort、專門角色與不符合範圍的委派可按設計保留原呼叫。

`mrh classify` 會真的呼叫所選分級來源，可能有費用與資料外送，不是無作用的安裝檢查。

## 找不到 mrh，或終端仍使用舊入口

Windows PowerShell 用 `Get-Command mrh -All`，cmd 用 `where mrh`；Mac 用 `command -v mrh`。確認解析到本次安裝的入口，有同名工具、alias 或函式時先回報，不覆蓋。安裝器自動設定支援的使用者 PATH；持久設定與既有程序持有的環境不同，必要時重開終端及啟動它的編輯器，僅開新分頁未必有效。更新不應重複加入 PATH 或移除其他工具的項目。Mac 若回報未知 shell、自改區塊、不安全連結或無法確定的 `ZDOTDIR`，保留原件並處理具體原因，不任意換設定檔重試。詳見[安裝指南](install.md)。

絕對入口成功只證明該檔案可執行，還須從一般目錄執行 `mrh status`。Mac 可先用 `~/.local/bin/mrh` 診斷，Windows 的入口位置及實際 PATH 契約見[安裝指南](install.md)。

Mac 若曾依舊指南只在目前 shell 執行 `export PATH`，目前可解析不代表持久設定完整。更新會檢查登入及互動啟動檔，補上缺少的 MRH 區塊；已有效的區塊不重寫。`current_process_ready` 與 `future_terminal_ready` 分開判定，之後仍需從取得新環境的 shell 完成命令檢查。

## Claude 版本或模型清單失敗

Mac 最低版本為 2.1.296，接受嚴格 `X.Y.Z (Claude Code)` 格式並以數字比較；過舊請更新，格式不明則回報 CLI 問題。版本合格且 CLI 可用時，initialize 清單讀不到不阻擋 Hook 安裝；可用「直接輸入模型」手動設定，並保留清單未確認的標示。已確認下架／不可選模型或不支援的 effort 仍不能新增。清單失敗不等於模型已下架，也不代表帳號有使用權。

Windows 不借用這條手動路徑啟用 Claude 路由；原生註冊與 profile 限制見[相容性](compatibility.md)。Linux／WSL、Intel Mac 等未支援環境，不移除平台檢查來宣稱相容。

## 更新後需要重新信任 Hook

穩定指令的一般更新可沿用信任；命令、matcher、timeout 或安裝位置改變時仍可能需要重新審閱。使用原生 `/hooks`，不手改信任資料。已停用的插件不會被偷偷重新啟用。

## 安裝中斷或衝突

保留 journal、目前設定、仍被引用的安裝代及既有歷史備份，修正回報原因後用相同來源與參數重跑。退版只切換程式與 wiring，不還原舊統計或 profile；第一次安裝沒有前代可退。日常 Reset 不處理這些檔案，見[安裝生命週期](install-lifecycle.md)。

## 想快速清除暫存

`mrh cleanup` 只預覽；`mrh cleanup --apply` 或 `mrh ctrl` 的「清除暫存／Reset」清除固定專案暫存與快取，不動設定、統計、實驗、收集器、正式報表或派工回執。略過的項目會回報原因。根不可用時不改用系統 tmp；單獨使用 wheel 可明確設定可信 `MRH_PROJECT_ROOT`。

清理可讓當次分類失敗，但不是重送 Jev 或重派舊 packet 的許可；下一個新任務可正常重建。未知 release 保留原身分與 receipt。舊散落資料不自動刪除，見[日常操作](usage.md#清除可丟棄暫存)。

## Skill 更新被拒絕

`mrh skill status --host codex` 或 `--host claude` 查看原因。相同內容不重寫；不同內容不會默默覆蓋。自改的 MRH skill 只有在確認來源且明確給予 `--force --backup-dir` 後才先備份再變更，外來或額外內容、連結仍保留。不要用更換平台或根目錄繞過拒絕；詳見[選配派工 skill](delegation-skills.md)。

## 統計用量或金額未知

明確執行 `mrh usage collect` 才收集本機用量；`status`／`stats` 不自動掃描逐字稿。來源缺欄位、仍在變動或無法拆分模型時保留未知，不補零，也不把已知小計當成完整帳單。
