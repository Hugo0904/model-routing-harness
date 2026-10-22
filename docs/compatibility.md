# 平台與版本

## 作業系統

| 環境 | 安裝範圍 | 驗證界線 |
| --- | --- | --- |
| Windows x64 | `setup.ps1`／`mrh_windows_setup.py` 原生安裝；需既有 Git、x64 CPython ≥ 3.11 及宿主 CLI。 | 安裝、Credential Manager 與 Hook 接入分開檢查；真正的 Jev 分類與子代理採用仍需各自實測。 |
| macOS Apple Silicon | 沿用 `setup`、鎖定的 Python runtime 與既有宿主接頭。 | 保留既有驗證紀錄；未以 Mac 實機重驗。 |
| macOS Intel | 沒有對應的安裝封裝。 | 沒有本版實機驗證。 |
| Windows ARM／32 位元 | 沒有對應的原生安裝流程。 | 不以 x64 的結果推論相容。 |
| Linux／WSL | 尚未提供正式安裝與驗證。 | WSL 不是 Windows 原生流程的替代方式。 |

`setup`／`mrh_setup.py` 仍處理 macOS arm64；Windows 使用獨立入口，不繞過 Mac 平台檢查。Windows runtime 取自本機 CPython，複製標準函式庫、DLL 與授權，排除 `site-packages`，以雜湊固定私有複本；不下載 Python、不執行 pip。Python 核心可執行不等於整套宿主整合已通過驗證。

## 版本來源

| 元件 | Windows | Mac 既有範圍 |
| --- | --- | --- |
| MRH | 0.4.0；版本以 [`pyproject.toml`](../pyproject.toml) 為準。 | 同左。 |
| Python | 已安裝的原生 x64 CPython ≥ 3.11；安裝時保存來源版本與檔案雜湊。 | 3.11.17，build 20261009；來源、大小與 SHA-256 固定於 [runtime lock](../packaging/macos-arm64/runtime-lock.json)。 |
| Codex CLI／原生後端 | 已觀測安裝並登入 0.163.0-alpha.10.2。 | 接頭驗證紀錄 0.162.1。 |
| Claude Code CLI | 已觀測安裝並登入 2.1.303；只確認 CLI 版本不代表有模型清單。 | 最低 2.1.296；嚴格解析 `X.Y.Z (Claude Code)` 並以數字比較。清單協定未知時可手動設定，不能當成已驗證可用。 |
| Jev | 新設定預設 `jev-latest`，可選 `jev-preview` 或固定版本。 | 相同；既有固定劇本比較使用 `jev-1.13.0`。 |
| Gemini CLI | Windows 整合不可用。 | catalog 版本 0.63.0；只有模型清單接頭，沒有 Hook／setup 支援。 |

以上 CLI 版本是特定環境的觀測或既有紀錄，不是最低版本，也不保證其他新版本相容。Mac 的 Python lock 與第三方聲明保留，Claude CLI 另有最低版本檢查；不能把 Windows 的版本觀測套用到 Mac。

Claude 最低版本檢查位於 `src/mrh/adapters/catalogs/claude_version.py`。低版提示更新，格式不明拒絕；可執行的合格 Mac CLI 不因 initialize 模型清單協定未知而阻擋 Hook 安裝。清單未知可直接輸入模型，但不保證帳號或模型可用；已宣告下架、不可選或不支援的 effort 仍拒絕。Windows 的原生插件版本契約與路由限制維持其實測範圍，不能借用 Mac 手動路徑啟用 Windows Claude。Jev 別名可能隨服務更新，固定版本才固定版本選擇；名稱不保證帳號可用性，實際回應版本會逐次記錄。

## Windows 功能邊界

| 功能 | 目前範圍 |
| --- | --- |
| 安裝、更新、退版 | 原生 x64 入口、私有 runtime、世代完整性檢查與持久設定保留；以 `--check --json` 回報本機結果。 |
| 全部專案範圍 | 明確選用 `--all-workspaces` 後，以持久設定涵蓋所有本機磁碟及支援的 UNC 專案路徑；可改用有限的 `--workspace`，兩者互斥。這不增加宿主檔案系統權限。 |
| Codex 插件與 Hook | 透過原生介面註冊並讀回；信任仍需使用者在 `/hooks` 確認。模型政策需通過公開 catalog 驗證才可啟用。 |
| Claude 插件與 Hook | 使用 Windows 原生註冊接頭及獨立的 `config\claude-profile\settings.json`，保留其他插件與 Hook。每個宿主分開驗證模型政策、金鑰、範圍與開關。 |
| Claude 模型清單 | 已加入零 capabilities LPAC 接頭，先在懸停狀態核對 token、映像與 Job，再只送 initialize。Windows 10 LTSC 19044／Claude 2.1.303 可讀版本，但 initialize 在 Winsock 啟動失敗，清單尚未通過，路由保持停用。 |
| Jev 金鑰 | 目前使用者的 Windows Credential Manager，本機持久保存；原生視窗密碼欄輸入 Jev 金鑰。 |
| Jev 實際分類 | Windows 驗證時已由安全儲存的金鑰完成中文合成任務分類，回應為 `jev-1.13.0`；安裝器本身不呼叫 provider。 |
| 真宿主子代理採用 | 原生 Codex 合成任務已驗證：Jev 分為 Small，MRH 建議 `gpt-6.1-sol / high`，重新委派後子代理 session 記錄相同模型與強度，並完成任務。 |
| Codex／Claude 訂閱分級器 | Windows 不可用。 |
| Codex 完整任務封包 | Windows 不支援 `--codex-packets`。 |
| Gemini | Windows 不可用，不能視為可路由宿主。 |

目前 Codex 原生委派的 `message` 可能是加密內容；Hook 依既有契約退回以可讀的 `task_name` 分級。這不能當作完整任務內容已經送入分類的證據。UNC 已完成路徑規則測試，本次沒有可用的真實網路分享供實機驗證。

新安裝預設停用、禁止外送任務。全部專案的外送同意與設定持續有效時，不因切換專案重新要求個別授權。Windows 內部以 `allowed_workspaces: ["*"]` 表示全部；Mac 仍用 `/`，Windows 不把 `/` 視為全機範圍。

`enabled` 是每份 profile 的開關。Windows 將 Codex 主 profile 與 Claude profile 分開。`--enable` 只驗證及更新選定宿主的 profile；任一清單或政策未通過就拒絕啟用，不借用另一個宿主的結果。`--check --json` 的 `hosts.<宿主>` 分別回報 `catalog.verified`、`policy_ready`、`enabled` 與 `routing`，頂層彙整這次選定的宿主。CLI metadata 的 `isolated_initialize` 只代表有接頭，不能代替 `catalog.verified: true`。安裝、信任、清單、provider 回應與實際子代理採用仍是不同證據。

## Mac 既有宿主範圍

| 宿主 | 既有範圍 | 尚不能推論 |
| --- | --- | --- |
| Codex CLI／官方原生後端 | 插件與 Hook 接入、信任／設定保全、限定故障通知、同 Goal 後續委派與 Fixed 父子結果。 | 所有版本或所有日常委派都會採用建議；部分路由驗證使用合成分級。 |
| Codex Desktop App | 官方插件接頭；既有桌面版本有實際派工觀測。 | 最新 Desktop UI 與所有情境已重新驗證。 |
| Claude Code CLI | 安裝設定合併、明示選型保護、實際派工與限定故障通知。 | 宿主未回報的子代理實際推理強度。 |
| Claude Desktop Code | 預定使用同宿主接頭。 | 本版未另做實機驗證；不含 Chat／Cowork。 |

Windows 結果見 [Windows 驗證紀錄](windows-validation.md)。Mac 歷史結果見 [驗證摘要](validation.md)，不把它當作 Windows 驗證。安裝步驟見 [手動安裝](install.md)。
