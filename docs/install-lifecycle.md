# 安裝、更新與退版

Windows 的入口是 `setup.ps1`／`mrh_windows_setup.py`；macOS arm64 沿用 `setup`／`mrh_setup.py`。兩者各自處理安裝前檢查、鎖、安裝代、復原與宿主註冊。`mrh_bundle.py` 保留既有 Mac runtime、快取、封裝與授權流程。安裝器不負責呼叫分級模型，也不能證明子代理採用結果。

一般使用步驟見 [手動安裝](install.md)，平台與未支援功能見 [相容性](compatibility.md)。

## 共同原則

新設定一律停用路由，並禁止外送任務。更新保留既有設定、政策、金鑰與統計；只有明確指定啟用或範圍時才變更對應設定。退版選擇上一個相容安裝代，不還原舊資料庫或舊 profile。

程式與持久設定分開保存。安裝器檢查所有權、原生註冊與讀取相容性；遇到外來入口、不同設定指標、衝突插件來源、檔案被修改或並行寫入時，保留現場並停止，不自行覆蓋。其他插件與 Hook 必須保留，Codex 信任仍由使用者在原生 `/hooks` 確認，不直接修改其私有資料庫或信任紀錄。

## Windows 原生流程

### 入口與位置

需要本機既有的 Windows x64 CPython ≥ 3.11、Git 及所選宿主 CLI；建議 PowerShell 7。`setup.ps1` 只尋找符合條件的原生 Python，再以 `-I -B` 執行同一個 Python 安裝器。若執行原則禁止 `.ps1`，改用：

~~~powershell
python -I -B .\mrh_windows_setup.py --host codex --host claude
~~~

不調降執行原則、不使用 WSL，不下載 Python 或執行 pip。預設根目錄為 `$env:ProgramData\ModelRoutingHarness-<目前使用者 SID>`，結構如下；實際路徑以本機檢查輸出與安裝參數為準：

~~~text
ModelRoutingHarness-<SID>\
  install\
    bin\mrh.cmd
    bootstrap.py
    python-runtimes\
    host-tools\
    setup-state\
      state.json
      pending.json
      generations\
  config\
    active-settings
    profile\settings.json
    claude-profile\settings.json
~~~

`install` 與 `config` 為同層目錄，不能互相包含；設定也不能與程式重疊。安裝根目錄及其內容採目前使用者的私有保護，檢查 ACL 與 reparse point，避免其他本機使用者改寫之後會執行的程式。自訂根目錄同樣必須通過檢查，不能用較寬鬆位置繞過。

### 安裝順序

1. 解析根目錄、既有 `active-settings` 與已註冊宿主，核對所有權及衝突。
2. 將本機 CPython 的標準函式庫、DLL 與授權複製到 `python-runtimes`，排除 `site-packages`、bytecode 快取與 reparse point。記錄來源版本及每個檔案的雜湊，後續使用私有複本，不依賴原 Python 目錄持續不變。
3. 所選宿主的原生執行檔經發行者簽章檢查後，保存到受保護的 `host-tools`。Codex 一併保存 code-mode、command runner 與 Windows sandbox helper，逐一驗證簽章及雜湊。這些是已安裝 CLI 的本機複本；不下載 CLI，不複製登入憑證。
4. 鎖定安裝控制目錄，在私有暫存區建立完整安裝代；驗證應用程式、宿主產物與 manifest 後才發布。
5. 在 `pending.json` 保存操作意圖與進度，透過各宿主的原生介面註冊並讀回，保留其他插件及 Hook。
6. 再次核對設定與入口快照，才更新 `state.json`、`active-settings` 與 `mrh.cmd`。舊安裝代保留供相容退版或其他宿主引用。

Windows 用受管理的狀態檔選取目前安裝代，不使用 Mac 的 `current` 連結。不要為整理空間而刪除仍可能被宿主引用的 runtime、`host-tools` 或安裝代。

原生 Hook 透過固定的 PowerShell 指令呼叫受保護的 `bootstrap.py`，由它核對 manifest、runtime、launcher 與 binding，再選取該宿主的安裝代。指令不執行宿主可變快取中的 Python，也不調降執行原則。同一 prefix、interpreter 與 Hook 定義的一般更新可沿用信任；定義有變時仍需使用者重新審閱。

### 金鑰與啟用範圍

`mrh key set jev` 開啟 Windows 原生安全視窗；密碼欄輸入的是 Jev API 金鑰。金鑰以目前使用者身分存入本機 Credential Manager，供後續登入使用；不進入指令參數、環境變數、聊天或日誌，也不從 Mac Keychain 複製。`mrh key status jev` 只查是否存在。

完成金鑰、模型政策與原生信任後，操作員可明確選用 `--all-workspaces --enable`，表示同意所有本機磁碟及支援 UNC 路徑的專案任務送往 Jev。持久設定保存為 `allowed_workspaces: ["*"]`；有效同意與設定未變時，不因切換專案逐一重新授權。這個範圍只決定哪些任務可供 MRH 分類，不放寬宿主原有的檔案系統權限。

有限範圍改用一個或多個 `--workspace`，與 `--all-workspaces` 互斥。Windows 只接受有效的絕對本機／支援 UNC 路徑；Mac 的 `/` 語意不套用到 Windows。

Windows 的 Codex 主 profile 位於 `config\profile\settings.json`，原生 Claude 插件使用獨立的 `config\claude-profile\settings.json`；CLI 預設使用安裝狀態指向的主設定。兩宿主一起選用時，範圍可同步保存，但 `--enable` 只啟用通過條件的 Codex 主 profile；Claude 仍停用並禁止外送。檢查需保留 Claude 的 `disabled_pending_windows_catalog`，不能用主 profile 的就緒值代替。

Windows Claude 模型清單、訂閱分級器、Codex packets 與 Gemini 仍有明確的不可用邊界。安裝／Hook 註冊成功不代表可以啟用完整 Claude 路由，詳見 [相容性](compatibility.md)。

## macOS arm64 既有流程

### 安裝順序與保存方式

1. 解析指定根目錄與既有設定指標；拒絕不同指標、外來 bin 入口、未知設定所有者、不支援平台／宿主，或原生插件名稱／來源衝突。
2. Claude 使用既有 catalog discovery 與版本 metadata 契約，要求可用且受支援的 CLI。`--claude-cli` 與 `--codex-cli` 提供明確指定入口；只選 Codex 時不探測或執行 Claude。設定合併不能代替可用宿主證據。
3. 鎖定有所有權標記的 `setup-state/`，重查可變目標。在私有 staging 建立完整 manifest，使用最終安裝代路徑準備所選宿主產物；只有明確選用 packets 才加入選配 skill。再次驗證後，整個安裝代一併更名發布。
4. 在 `journal.json` 保存階段與意圖。Codex 使用官方命令註冊；Claude 只合併 MRH Hook，並用快照比較防止並行覆寫，不為例行安裝新增備份。各宿主完成後都讀回。
5. 比較 CLI、`current` 與設定指標快照，所選宿主完成註冊後才提交新狀態，並保留先前安裝代。

控制目錄與嚴格的設定目錄分離。目前及前一代的 manifest 保存 reader 相容資訊；未知或不相容的 reader 會被拒絕。舊 `app/` 保持原樣，穩定的 bin 入口透過 `current/` 指向獨立新代；未選宿主不重新接線，因此 Codex 更新不會改寫仍被 Claude 引用的 interpreter 或產物。安裝器不自動回收舊代。

### Codex 指令穩定性與原生信任

Codex Hook 使用 `<prefix>/current/runtime/bin/python3.11` 與不變的 `${PLUGIN_ROOT}/launcher.py`。只有 Codex `hooks.json` 採用穩定 interpreter 路徑；launcher 的 binding 仍保存自身安裝代的 interpreter 與 runtime。更新或退版時，一併切換原生註冊與 `current`。

相同 prefix 與 Hook 定義產生相同 Hook 指令，單純更換安裝代不會改變信任指令。從早期絕對安裝代指令遷移時，需在 `/hooks` 審閱 PreToolUse 與 PostToolUse。後續修改指令、matcher、timeout 或 prefix，或退回舊方案的安裝代，仍可能需要重審；不改寫保留的舊代來略過審閱。

原生註冊先於 `current` 原子切換。短暫過渡期間，新 launcher 可由相容的前代 Python 啟動，再依不可變 binding 執行自己的 runtime；完成後，interpreter 入口與已註冊 launcher 都選到預期安裝代。

Codex 專用產物發布 `.codex-plugin/plugin.json`，以頂層 `hooks` 宣告 Hook。既有 Codex CLI 0.162.1 會由 portable 根目錄 `plugin.json` 讀 skill，卻不讀其 OpenAI extension 的 Hook；預設檔案探索也有相同限制。相容 manifest 才會讓 `plugin/read` 與 `/hooks` 看見兩個 Hook。不要同時發布兩份 manifest，portable 版本優先時會遮住相容 Hook。轉換由 setup 的 Codex adapter 負責，portable plugin 產生流程與未選的 Claude 產物不變。

### Bootstrap 與授權

shell 入口可使用既有 Python ≥ 3.11；否則僅在 macOS arm64 取得 `runtime-lock.json` 固定的官方 runtime，先檢查大小與雜湊，再解壓執行同一安裝器。它不執行遠端 shell、不覆寫 HOME／CODEX_HOME，也不安裝供應商 CLI。指定根目錄可用於隔離 fixture，不能把 fixture 結果當作一般帳號的原生安裝。Mac bundle 未簽章，也未經 notarization。

既有公開 runtime 聲明與 metadata 以雜湊鎖定的來源快照隨附，保留原始 archive provenance 與 runtime binary 相依證明，見 [Mac runtime 授權](../packaging/macos-arm64/LICENSES.md)。消費端建置不需額外 zstd／otool 來交付這些聲明。Windows 則保留來源 Python 的 `LICENSE.txt` 與隨附聲明，並在安裝代保留 Python 與 MRH 授權。

## 失敗與復原

跨宿主沒有單一原子交易，原生註冊可能先於 CLI 入口切換完成。Windows 的 `pending.json`、Mac 的 `journal.json` 保存意圖、目標安裝代與已完成步驟；同一來源及原參數重跑可核對已完成但未收到確認的操作。

不同待處理意圖、外來 marketplace 來源、非預期指標、被改寫的 manifest 或 bin 入口都會保留為衝突。先處理實際原因，再重跑原指令；不要刪除狀態檔來強行繼續。Mac 的 Claude 合併只變更 MRH 自己的 Hook，保留其他設定與 Hook，不為例行安裝或移除新增備份；既有歷史備份仍保留，不拿來覆蓋後續編輯。原生插件若已停用，也不會被安裝器默默重新啟用。

Mac runtime 的 bytecode 是可變快取。完整性比較只排除 runtime 內、能對應 manifest 所記錄一般 `.py` 檔案的一般 `.pyc`，包含 `__pycache__` 與舊式相鄰快取；新增、改寫、刪除這類快取不影響檢查、更新或退版。無原始碼 bytecode、符號連結、`__pycache__` 中其他檔案、Python 原始碼、binary 及宿主產物仍受檢查。新舊 manifest 都沿用此規則，不重寫已保存內容與 digest，也不需要變更權限、修復快取、刪檔或下載。bytecode 內容不屬於這項比較；`-B` 防止寫入，不會禁止讀取既有快取。Windows 私有 runtime 則依其自身 manifest 核對已複製的檔案。

## 移除

Mac 的 `./setup --uninstall` 沿用安裝時的所有權檢查，只移除能確認是 MRH 自己建立的項目；步驟與使用方式見[安裝指南](install.md#移除)。規則如下：

- 預設只預覽，不變更任何東西、不下載、不連網；加 `--yes` 才執行。設定、統計資料庫與 Jev 金鑰預設保留，只有 `--purge-data` 才刪除，且只在其他項目都已移除時才刪。
- 順序固定：宿主註冊（Claude Hook、Codex 外掛與 marketplace）→ 選配 skill → shell PATH 區塊 → 命令入口與 `current` 連結 → 安裝代與狀態。宿主註冊有任何一項不能移除（不是 MRH 建立的 Hook、設定檔無法解析、Codex CLI 找不到、原生註冊被別處改過）就停在該處，其他項目都不動，程式本體因此仍在，Hook 不會指向已刪除的路徑。
- Claude 只移除經 artifact 綁定確認屬於這份設定的 MRH Hook，其餘 Hook 與設定保留，不建立備份。Codex 只走原生 `plugin remove`／`plugin marketplace remove`，不直接編輯 `config.toml` 或信任紀錄。
- 啟動檔只移除與安裝程式寫入內容完全相同的區塊；被改過、重複或指向別的 bin 目錄的區塊保留並回報。登入 shell 以外的啟動檔若無法安全讀取（例如符號連結）會略過。
- 只刪除預期的名稱：安裝代必須有 MRH 擁有者記錄，`setup-state` 內有未知檔案就整個保留；不跟隨連結。設定資料夾必須是 MRH 建立且內容全在已知清單內才會刪除。舊版 `app`、他人建立的 `mrh`、專案內 `runtime/` 不動。
- 每步以讀回確認，失敗保留現場並回報原因；不建立備份、快照或垃圾桶。移除可重跑，已完成的項目不會再動。
- Windows 沒有對應的 `--uninstall`；文件只提供手動步驟，且未經 Windows 實機驗證。

## 檢查與驗證界線

`--check` 與 `--dry-run` 不建立 MRH 設定、資料庫或安裝根目錄，後者也不下載。原生 metadata 查詢可能有宿主 CLI 自己的執行行為，但不是 provider／模型呼叫。Codex 政策就緒依公開 CLI 宣告；Mac Claude 合格 CLI 的 catalog 未知時可保留手動選型並標明未確認，不因此列為政策 pending。CLI 不可用、已宣告不支援的模型／effort 與 Windows Claude 停用界線仍保留；兩者都不代表帳號有實際使用權。缺金鑰、外送同意、信任、模型政策或實測證據，都需如實保留待辦。

Python 驗證一律帶 `-B`；由 Python console script 啟動的子程序，另設 `PYTHONDONTWRITEBYTECODE=1`。每個 Python 子程序仍需明確帶 `-B`，尤其 `-I`／`-E` 會忽略 Python 環境設定。測試範例見 [開發指南](development.md)。

MIT、Python 及實驗接頭各自的 LICENSE／NOTICE 都必須保留，不因平台新增或重新封裝而移除。


## PATH、專案暫存與選配 skill

安裝器依平台處理使用者 PATH。Windows 沿用 HKCU 使用者 PATH，不改 System PATH；Mac 依帳號登入 shell 選 zsh／bash 啟動檔，尊重已匯出的 `ZDOTDIR`。不依賴終端品牌、不改寫整份啟動檔；可辨認的 MRH 區塊重跑不重複，保留原文與權限。Mac 只有所需持久啟動檔已有有效 MRH 區塊時才不改檔，繼承到的目前 PATH 不作為新 shell 就緒的證據；衝突、不安全檔案與未知 shell 明確拒絕。既有程序的環境不會被刷新。`command_path` 的設定判定與一般目錄實際執行命令分開，Hook 固定入口與金鑰安全儲存維持原契約。shell 啟動順序參考 [zsh Files](https://zsh.sourceforge.io/Doc/Release/Files.html) 與 [Bash startup files](https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html)。

專案運作需保留的暫存紀錄、Codex brief 與可重建 Jev 快取，分別使用固定專案根下的 `runtime/tmp/mrh/`、`runtime/cache/mrh/`；安裝代與 plugin binding 記錄專案根，CLI 不隨 cwd 換根。這些根不可用就明確失敗，不回退至系統 tmp 或家目錄。開發、測試與安裝的短期檔案可使用合適位置；原子更新檔放在目標旁，安裝代 staging 放在發布目錄所在的檔案系統，避免跨磁碟更名。用完清理自己建立的中介檔，必要失敗證據與復原 journal 保留。更名失敗保留原件，不以直接覆寫代替。

Windows bootstrap 在完整性驗證後，由 CLI 目前安裝代或該宿主實際選用的安裝代取得根綁定，覆蓋呼叫端的 `MRH_PROJECT_ROOT`。移到另一份 checkout 會形成不同的來源身分；不改寫舊安裝代。退回沒有根欄位的舊代時，保留舊代自己的行為。`--check` 的 `project_root` 及各宿主同名欄位分開回報 `bound`、`legacy_unbound` 或 `not_ready`；根缺失、不安全或無法使用時，明確保留未就緒狀態。

`mrh cleanup` 預覽，`--apply` 或控制中心的明確 Reset 動作清除可丟棄資料，不建立備份／快照／垃圾桶。既有共用鎖讓正在使用的安裝快取可略過；新建或變更的項目也可略過。必要 receipt／派工身分、DB、profile、金鑰、實驗與收集器資料、正式報表、使用中的程式／rollback／journal 全部排除。舊散落資料不自動遷移或清除，細節見[日常操作](usage.md#清除可丟棄暫存)。

兩平台社群 skill 隨套件提供原文，兩個安裝器只提供對應宿主的建議指令，不自動安裝；管理入口為 `mrh skill status/install/remove --host codex|claude`。支援 `--skills-dir` 與原 `--root` 別名，Claude 尊重 `CLAUDE_CONFIG_DIR`。不同內容不默默覆寫；明確取代自改的 MRH skill 需 `--force --backup-dir`，先保存可復原副本。無法確認來源、額外內容或連結仍拒絕，不修改既有 Router；詳見[選配派工 skill](delegation-skills.md)。

安裝與更新的完成條件包含一般目錄中解析並實際執行 `mrh status`，不只執行絕對入口。PATH、既有程序環境與同名衝突的核對見[安裝指南](install.md)。
