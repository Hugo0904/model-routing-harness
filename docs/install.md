# 手動安裝

選擇下方對應的系統流程。先安裝並登入要使用的 Codex CLI／Claude Code CLI；MRH 不會替你安裝宿主或搬移另一台電腦的登入與金鑰。各平台限制見 [相容性](compatibility.md)。

## Windows x64

需要 Git，以及已安裝、可執行的 **Windows 原生 x64 CPython 3.11 以上**（含 `LICENSE.txt`）。建議使用 PowerShell 7。這個流程不使用 WSL、pip，也不下載 Python；安裝器會把本機 Python 的標準函式庫、DLL 與授權複製成私有 runtime，不帶入 `site-packages`。

### 1. 下載並安裝

在 PowerShell 切到你想放原始碼的資料夾，執行：

~~~powershell
git clone https://github.com/Hugo0904/model-routing-harness.git
cd model-routing-harness
~~~

依你使用的工具，選一條執行；**新安裝一律預設停用**：

~~~powershell
.\setup.ps1 --host codex
.\setup.ps1 --host claude
.\setup.ps1 --host codex --host claude
~~~

Windows Codex 與 Claude 均已有原生路由驗證；Claude 的 LPAC initialize 使用單一 `registryRead` capability，並以獨立 profile 驗證清單、政策、金鑰與外送同意。新安裝預設停用，完成各宿主條件後才明確啟用。若 PowerShell 執行原則擋住 `.ps1`，直接使用同一個 Python 安裝器，不必修改執行原則：

~~~powershell
python -I -B .\mrh_windows_setup.py --host codex --host claude
~~~

後續的 `--check`、`--enable`、`--rollback` 也可用相同方式執行；`--host` 沿用你選擇的工具。

預設根目錄是 `$env:ProgramData\ModelRoutingHarness-<目前 Windows 使用者 SID>`，其中 `install` 放程式，旁邊的 `config` 放持久設定。以下絕對入口只用於診斷安裝位置，不代表一般命令已可用，也不需把個人 SID 寫進指令：

~~~powershell
$mrhBase = Join-Path $env:ProgramData ('ModelRoutingHarness-' + [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
$mrh = Join-Path $mrhBase 'install\bin\mrh.cmd'
& $mrh status --json
~~~

若安裝時自訂路徑，診斷入口是該目錄下的 `bin\mrh.cmd`。**完工還必須通過一般目錄的命令檢查**：

~~~powershell
Get-Command mrh -All
Push-Location $env:USERPROFILE
try { mrh status } finally { Pop-Location }
~~~

使用 cmd 時可用：

~~~bat
pushd %USERPROFILE%
where mrh
mrh status
popd
~~~

安裝器會將自己的 `bin` 加入目前使用者 PATH，保留其他項目與型別，只合併 MRH 自己的重複項目，不修改系統 PATH 或 shell 設定檔。偵測到其他 `mrh` 命令時會保留衝突並停止，不覆蓋其他工具。

`--check --json` 的 `command_path` 分別回報 `user_path_registered`、`future_terminal_ready` 與 `current_process_ready`。前兩項表示使用者 PATH 與新終端的命令查找條件已滿足；`execution_probe_performed: false` 表示這份報告沒有實際執行命令，仍須完成上述一般目錄的 `mrh status` 檢查。確認解析到本次安裝的入口，而非其他 alias、函式或同名程式。

使用者 PATH 與已開啟程序持有的環境不同。若終端或啟動它的編輯器仍持有安裝前的環境，需完整關閉並重新開啟該程序，再做上述檢查；從舊父程序開新分頁未必取得新環境。安裝器的通知不會改寫既有 shell 環境，不以絕對路徑成功冒稱一般命令已完成。這些規則適用於各種終端，沒有品牌專屬設定。

下方操作繼續使用 `mrh`；`setup.ps1` 相關指令仍回到原始碼目錄執行。Codex 使用者還需到原生 `/hooks` 介面審閱並信任 MRH Hook；安裝器不會代替你確認。

### 2. 安全設定 Jev 金鑰

Jev 負責判斷任務難度。到 [TypeSafe 官方控制台](https://console.typesafe.ai/keys) 建立 API 金鑰，確認帳號可呼叫 API，再執行：

~~~powershell
mrh key set jev
mrh key status jev
~~~

第一條會開啟 Windows 原生安全視窗：**在密碼欄輸入 Jev API 金鑰，不是 Windows 登入密碼**。金鑰存入目前使用者的 Windows Credential Manager，保留於本機供後續登入使用；不會從 Mac 複製金鑰。第二條只顯示是否已設定，不顯示金鑰。

不要把金鑰放進指令參數、環境變數、日誌或聊天。新安裝已預設使用 `jev-latest`，需要明確重設時可執行：

~~~powershell
mrh ctrl set classifier.provider jev
mrh ctrl set classifier.model jev-latest
~~~

`jev-latest` 會跟隨正式版更新；固定版本與費用說明見 [日常操作](usage.md)。Jev 費用依 TypeSafe 帳號計算，與 Codex／Claude 訂閱分開。

### 3. 設定模型

~~~powershell
mrh models --host codex --json
mrh ctrl
~~~

在「各難度要用的模型」選 Codex，分別設定 Light、Small、Mid；從宿主已確認的模型清單選模型與推理強度，再儲存。在「Top 難度怎麼處理」選 **Main**，把最難任務交回主 AI；若選 Fixed，還要設定 Top 候選。

也可用 `mrh ctrl set tiers.Light.codex '模型ID:推理強度'` 直接設定，將模型 ID 與強度換成清單中的值；Small、Mid 的寫法相同。`mrh ctrl set top_mode Main` 可指定 Top 交回主 AI。手動輸入成功只代表設定已保存，不能替代模型清單驗證或帳號實際使用權。其他共用設定見 [日常操作](usage.md)，Windows 資料位置以本頁為準。

Claude 使用另一份 MRH 設定，不能在 Codex 的設定頁代填：

~~~powershell
$claudeProfile = Join-Path $mrhBase 'config\claude-profile\settings.json'
mrh models --host claude --json
mrh ctrl --settings $claudeProfile
~~~

只有第一條清單查詢成功後，才從回傳清單設定 Claude 的 Light、Small、Mid；不要硬填清單或刪除版本／隔離檢查。Windows 上 Claude 的 initialize 在 LPAC 內只附 `registryRead` 一個 capability（libuv 初始化 Winsock 所需，網路仍被拒）；版本探測仍是零 capabilities。若清單失敗，應停在這一步，保留 profile 停用，不增加其他 capability、修改系統 ACL 或強制打開開關。

### 4. 明確啟用全部專案

**啟用全部專案，代表同意所有本機磁碟及支援的 UNC 路徑下，專案任務內容都可送往 Jev 分類。** 這是持久的全域範圍設定，不限於 MRH 原始碼資料夾；同意與設定未變時，切換專案不需逐一重新授權。

確認金鑰已保存、Codex 模型政策已通過驗證、Hook 已信任，並同意上述外送範圍後，依安裝工具選一條：

~~~powershell
.\setup.ps1 --host codex --all-workspaces --enable
~~~

若只允許指定專案，改用完整路徑；可重複 `--workspace`，但不能與 `--all-workspaces` 同時使用：

~~~powershell
.\setup.ps1 --host codex --workspace 'C:\Projects\Example' --enable
~~~

Windows 的全部專案設定不使用 Mac 的 `/`，也不增加宿主原有的檔案系統權限。上述指令只啟用選定的 Codex profile。Claude 自己的清單、政策與金鑰都通過時，可使用 `--host claude --all-workspaces --enable`；兩個宿主都驗證完成才一起指定。安裝器會分別驗證及更新選定 profile，不會因 Codex 已就緒就啟用 Claude。Windows 10 LTSC 19044／Claude 2.1.303 已用上述方式取得 LPAC 清單，完成啟用與 Light／Small／Mid 真實子代理驗證（見 [Windows 驗證紀錄](windows-validation.md) 與 [交接摘要](mac-handoff.md)）；啟用 Claude 同樣需要你明確同意任務內容送往 Jev。

更新指定專案的範圍時，需列出所有要保留的專案。Windows 目前不提供訂閱分級器或 Gemini 整合。Codex 完整任務封包（`--codex-packets`）已接入本候選，原生驗收狀態見[相容性](compatibility.md)。

### 5. 檢查狀態

~~~powershell
.\setup.ps1 --check --json
~~~

以輸出的路徑與各欄位判斷下一步，不要只看指令成功或 `status: installed`：

| 檢查內容 | 如何判斷 |
| --- | --- |
| `installed`、`generation_integrity`、`idempotent` | 程式入口、檔案完整性及宿主註冊是否一致。 |
| `hosts` 中的 `registration`、`trust` | Hook 是否已註冊；Codex 信任仍需原生 `/hooks` 確認。 |
| `key_present`、`policy_ready` | 金鑰是否存在、模型政策是否可驗證。Claude catalog 不可用時不能視為就緒。 |
| `enabled`、`workspace_ready`、`export_permitted` | 是否已明確啟用、設定全部或指定專案，並允許外送任務。 |
| `routing`、`pending` | 彙整選定宿主尚缺的條件；Claude 另看 `hosts.claude.routing`、`catalog.verified`、`policy_ready` 與 `enabled`。新 profile 或條件未齊時維持 disabled，通過本機驗證並明確啟用後才可就緒；不把早期 catalog 失敗狀態當成所有 Windows 安裝的現況。 |

檢查不會呼叫 Jev 或派工，`provider_probe_performed: false` 就是未做分級服務實測。安裝、登入與設定完成不代表已驗證金鑰額度、Jev 回應或子代理採用；這些結果需另有實測證據。

## Mac Apple Silicon（M 系列）

需要 Git 與已安裝並登入的 Codex CLI／Claude Code CLI。Mac 安裝器會處理自己的 Python，不需另外安裝 Python 或 Jev SDK；沿用的 runtime 與宿主相容性見 [相容性](compatibility.md)。

### 1. 下載並安裝

~~~sh
git clone https://github.com/Hugo0904/model-routing-harness.git
cd model-routing-harness
~~~

依使用的工具選一條：

~~~sh
./setup --host codex
./setup --host claude
./setup --host codex --host claude
~~~

`setup` 指令在原始碼目錄執行。安裝器依目前使用者帳號的登入 shell 自動設定 PATH，預設入口為 `~/.local/bin/mrh`；會檢查持久啟動檔，已有有效 MRH 區塊就不重複加入。只在目前 shell 執行過 `export PATH`，仍需補齊持久設定，不能據此宣稱新 shell 已就緒。zsh 使用 `.zprofile` 與 `.zshrc`，尊重已匯出的 `ZDOTDIR`；bash 使用第一個既有的 `.bash_profile`／`.bash_login`／`.profile`（都沒有時建立 `.bash_profile`），以及 `.bashrc`。只加入可辨認、可重複執行的 MRH 區塊，保留原內容與權限。未知 shell、無法確定的動態 `ZDOTDIR`、不安全連結、自改區塊或同名入口衝突會保留原件並明確停止，不猜位置或覆寫。

開啟新的登入或互動 shell，從一般目錄驗證：

~~~sh
command -v mrh
(cd "$HOME" && mrh status)
~~~

`--check --json` 的 `command_path` 分開回報設定是否就緒、目前程序能否解析，以及 `execution_probe_performed`。設定就緒不代表已執行上述命令；既有程序也不會被刷新。`~/.local/bin/mrh` 只供入口診斷，不能代替一般命令檢查；若解析到其他工具，先解決衝突。Hook 使用固定入口，不依賴互動 shell 載入 PATH；金鑰仍在 Keychain。Codex 使用者需在原生 `/hooks` 介面審閱並信任 MRH Hook。

### 2. 設定 Jev 與模型

到 [TypeSafe 官方控制台](https://console.typesafe.ai/keys) 建立 API 金鑰，再執行：

~~~sh
mrh key set jev
mrh key status jev
mrh ctrl
~~~

金鑰由 macOS 提示輸入並存入 Keychain，不貼給 AI、不寫進檔案或指令。新安裝預設 `jev-latest`；需要明確設定時使用：

~~~sh
mrh ctrl set classifier.provider jev
mrh ctrl set classifier.model jev-latest
~~~

在 `mrh ctrl` 的「各難度要用的模型」選 Codex 或 Claude Code，分別設定 Light、Small、Mid；兩者都有安裝就各設一遍。模型與推理強度優先從已確認的宿主清單選取。Mac Claude CLI 須為 2.1.296 或更新，版本格式不明則拒絕；合格 CLI 的新版模型清單若無法取得，可用「直接輸入模型」或 `mrh ctrl set tiers.Light.claude "模型ID:推理強度"` 手動保存，Small、Mid 同理。這只表示手動設定，不代表模型或帳號已驗證；已確認下架／不支援的模型或 effort 不能新增。CLI 不可用仍需先處理。Windows Claude 必須通過自己的 LPAC 清單與獨立 profile 驗證，不套用此手動例外。Top 建議先選 Main；選 Fixed 時需補齊 Top 模型。信心門檻與進階檔位可先保留預設。

### 3. 啟用並檢查

Mac 的 `--workspace "/"` 代表全部專案。確認同意全部專案的任務內容送往 Jev 後，依使用工具選一條：

~~~sh
./setup --host codex --workspace "/" --enable
./setup --host claude --workspace "/" --enable
./setup --host codex --host claude --workspace "/" --enable
~~~

若只允許指定範圍，把 `/` 換成專案完整路徑；多個範圍可重複加上 `--workspace`，既有設定需列出所有要保留的範圍。最後執行：

~~~sh
./setup --check --json
~~~

若 `pending` 有內容，依項目補齊：`credential_present` 是金鑰；`policy_ready` 是模型政策；`workspace_ready`、`enabled`、`export_permitted` 是範圍與啟用；`native_trust_or_unverified` 需回到 Codex `/hooks`。安裝或宿主設定問題見 [疑難排解](troubleshooting.md)。這項檢查不呼叫 Jev 或派工，不能驗證餘額或模型實際使用權。2026-10-23 已完成修復後的 Mac 安裝與限定原生驗收，個別 SKIP、版本及證據界線見 [驗證摘要](validation.md)；不需為閱讀或整理文件再跑一輪。

## 更新、退版與停用

先確認原本 clone 的資料夾沒有需要保留的未提交修改或來源衝突，再執行 `git pull --ff-only`，重跑同一條安裝指令；`--host` 與自訂路徑沿用原選擇：

| 操作 | Windows PowerShell | Mac 終端機 |
| --- | --- | --- |
| 更新範例（Codex） | `.\setup.ps1 --host codex` | `./setup --host codex` |
| 更新範例（Claude） | `.\setup.ps1 --host claude` | `./setup --host claude` |
| 更新範例（兩者） | `.\setup.ps1 --host codex --host claude` | `./setup --host codex --host claude` |
| 檢查 | `.\setup.ps1 --check --json` | `./setup --check --json` |
| 退回上一個相容安裝代 | `.\setup.ps1 --rollback` | `./setup --rollback` |
| 只停用路由 | `mrh ctrl set enabled off` | `mrh ctrl set enabled off` |
| 移除 MRH，保留設定與統計 | 手動，見[移除](#移除) | `./setup --uninstall`（預覽）、`./setup --uninstall --yes` |
| 連同設定、統計與金鑰一併刪除 | 手動，見[移除](#移除) | `./setup --uninstall --yes --purge-data` |

相同來源與參數可重複執行。更新會保留設定、金鑰與統計；有本機程式修改時先處理 Git 提示，不要直接覆蓋。第一次安裝沒有可退回的版本；退版保留目前設定、統計與金鑰，不還原舊資料。

若選用 [Codex 完整任務分類](codex/packet-skill.md)，安裝、啟用與更新時都要保留 `--codex-packets`。兩平台候選均允許與 `--dev` 併用；一般使用預設為打包版本，開發模式及 Windows packets 的原生驗收狀態分開記錄。切換前先完成舊 packet，待恢復交易應先用原參數恢復，再開始新的 prepare／query／release。更多細節見 [安裝生命週期](install-lifecycle.md)。


## 移除

### Mac：`./setup --uninstall`

在原本 clone 的資料夾執行。不加 `--yes` 只預覽：列出會移除、會保留與無法處理的項目，不變更任何東西。

~~~sh
./setup --uninstall                    # 預覽
./setup --uninstall --yes              # 移除 MRH，保留設定與統計
./setup --uninstall --yes --purge-data # 另外刪除設定、統計資料庫與鑰匙圈裡的 Jev 金鑰
~~~

`--host codex`／`--host claude` 可限定只處理一個宿主；沒指定時處理已安裝的宿主。`--json` 輸出機器可讀的結果。移除不需要網路，也不會呼叫 Jev。

會移除（只限能確認是 MRH 自己建立的項目）：

| 項目 | 做法 |
| --- | --- |
| Claude Code Hook | 只拿掉 `~/.claude/settings.json` 裡 MRH 的 PreToolUse／PostToolUse 項目；其他 Hook 與設定保留。 |
| Codex 外掛 | 用 Codex 原生 `plugin remove` 與 `plugin marketplace remove`；Codex 自己的 `config.toml` 與信任紀錄不由 MRH 直接修改。 |
| 選配派工 skill | 內容與發行版相同的才移除；自己改過的保留，並印出帶備份的移除指令。 |
| shell 的 PATH 區塊 | 拿掉 `~/.zprofile`、`~/.zshrc`（及 bash 對應檔）裡 MRH 標記的區塊；區塊被改過就保留並回報 `mrh_shell_block_modified`。只剩該區塊的檔案會一併刪除。 |
| 命令入口與安裝代 | `~/.local/bin/mrh` 符號連結、`current` 連結，以及 `~/.local/share/model-routing-harness/setup-state`（安裝代、狀態、紀錄）。 |

預設保留（`--purge-data` 才刪）：設定與指標（`~/.config/model-routing-harness/`）、統計資料庫（在設定資料夾內）、鑰匙圈裡的 Jev 金鑰。設定資料夾必須完全是 MRH 建立的內容才會刪；有其他檔案就整個保留並回報。舊版 `app` 目錄、別人建立的 `mrh` 命令與專案資料夾內的 `runtime/` 都不是安裝程式建立的，一律不動；專案內暫存可用 `mrh cleanup --apply` 清除，或直接刪掉這份 clone。

只要有任何宿主註冊無法移除（例如 Hook 不是 MRH 建立的、Codex CLI 找不到），就不會變更其他項目，也不會刪除資料；處理回報的原因後重跑同一個指令，已移除的項目不會再動。移除過程失敗時狀態可續跑。移除完成後再執行一次：若 PATH 上有 Python 3.11 以上會回報沒有東西可移除；沒有時，因安裝的 runtime 已移除，`./setup` 會回報找不到 Python（`status: unknown`），同樣表示沒有東西可移除，且不會下載。

Claude 的 settings.json 若原本不是 2 空白縮排的格式，移除時會改寫成該格式，內容與順序不變；安裝時也是這樣處理。

### 無法執行 `--uninstall` 時：手動移除（Mac）

例如已刪掉 `~/.local/share/model-routing-harness`、或找不到 Python 3.11。依序：

1. 需要 `mrh` 才能做的先做：`mrh skill remove --host claude`、`mrh skill remove --host codex`、`mrh key delete jev`（刪金鑰）。
2. Claude：編輯 `~/.claude/settings.json`，刪掉 `hooks.PreToolUse` 與 `hooks.PostToolUse` 裡 command 含 `model-routing-harness`、以 ` claude` 結尾的項目，其他內容不動。
3. Codex：`codex plugin remove model-routing-harness@model-routing-harness-local`，再 `codex plugin marketplace remove model-routing-harness-local`。
4. 刪掉 `~/.zprofile`、`~/.zshrc`（或 bash 的對應檔）中 `# >>> model-routing-harness PATH >>>` 到 `# <<< model-routing-harness PATH <<<` 之間的內容。
5. 刪掉 `~/.local/bin/mrh`（確認是指向 `model-routing-harness/current/mrh` 的符號連結）與 `~/.local/share/model-routing-harness/current`、`~/.local/share/model-routing-harness/setup-state`。
6. 不再需要設定與統計時才刪 `~/.config/model-routing-harness/`。

### Windows：手動移除（尚未經 Windows 實機驗證）

Windows 安裝器目前沒有 `--uninstall`。以下是依安裝內容整理的步驟，**未在 Windows 實機驗證過**，執行時請對照 `--check --json` 顯示的實際路徑；發現與實際不符請先停下。

1. 先停用路由：`mrh ctrl set enabled off`。
2. 有安裝選配派工 skill 時，先執行 `mrh skill remove --host codex`／`--host claude`。只有確定不再保留 Jev 金鑰時，才另外執行 `mrh key delete jev`；要保留設定與金鑰供日後重裝使用，就略過刪除金鑰。
3. Codex：`codex plugin remove model-routing-harness@model-routing-harness-local`，再 `codex plugin marketplace remove model-routing-harness-local`。
4. Claude Code：`claude plugin uninstall model-routing-harness@model-routing-harness-local --scope user --keep-data`，再 `claude plugin marketplace remove model-routing-harness-local --scope user`。
5. 從使用者環境變數的 `Path` 拿掉 `...\install\bin`（安裝器加到使用者 PATH 的項目），關掉並重開終端與編輯器。
6. 確認已安裝宿主的 MRH 插件、marketplace 與 Hook 都已移除後，才刪除 `install`。預設保留旁邊的 `config`，其中有設定與統計；確定不再需要這些資料時，才刪除整個 `$env:ProgramData\ModelRoutingHarness-<SID>`。資料夾刪除不會代替步驟 2 的 Credential Manager 金鑰刪除。

## AI 代辦的安裝與更新完工條件

可複製的提示詞在 [README](../README.md)。AI 應先辨識 OS、宿主與原安裝參數，依上面選 Codex、Claude 或兩者的原生入口；完成設定、金鑰輸入引導、必要原生信任與明確外送同意。更新保留設定、統計、實驗資料、金鑰與其他 Hook，不默默改適用範圍或 provider。

兩種操作都要完成 `--check --json`、從一般資料夾解析命令並執行 `mrh status`。安裝器自動處理支援的 PATH，確認不重複、不覆蓋其他項目，同名衝突具體回報；既有程序需要重開時如實說明。安裝、命令可用、Hook 信任與模型實測分開回報，不能為了安裝驗收擅自呼叫付費模型。

安裝器只印出對應宿主的[選配派工 skill](delegation-skills.md) 指令，不會安裝。AI 代辦時必須詢問，只在明確同意後執行；無答覆不裝。更新不自動覆寫已安裝的 skill，自改內容保留。安裝 skill 後可能需重新啟動宿主以載入，這與 PATH 刷新是不同步驟。新平台尚未支援的項目仍維持停用，不能為追求全綠略過能力檢查。

新安裝的暫存與 Jev 快取使用安裝代綁定的 `runtime_root`，一般模式不依賴原始碼目錄；Mac 預設為 `~/Library/Caches/model-routing-harness`，Windows 為私有 ProgramData／SID 根下的 `runtime`。開發模式仍需保留其來源；舊 profile 或外部工作區白名單若明確引用 checkout，該資料相依仍須保留，更新不會自動搬移。開發、測試及安裝用的短期中介檔可放在合適位置，原子發布檔放在目標旁，用完清理。可丟棄資料用 `mrh cleanup` 預覽、`mrh cleanup --apply` 清除，規則見[日常操作](usage.md#清除可丟棄暫存)。不要用此命令清理 profile、統計、收集器或安裝 journal。
