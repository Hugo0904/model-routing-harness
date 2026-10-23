# Mac 驗收交接：Windows 修復後的收尾

狀態：**Windows 已完成，待 Mac 驗收**。給 Mac 上的 Codex（或任何接手者）使用，目標是用 Mac 自己的證據完成收尾。日期：2026-10-23。這是交接用文件，不是安裝或執行的依賴。

本文是交接參考，不代表授權。push、啟用外送或修改宿主信任，都需要使用者在當下明確同意。

## 1. 起點

- Repo：`https://github.com/Hugo0904/model-routing-harness`，分支 `main`。
- Windows 交付版本：程式碼 `0aac0c0`（含其後只改文件的提交）。`9d50280` 之前的 12 個提交已 push（`6d10f9f..9d50280`，快轉），其後的提交（見第 3 節）以 `git log` 為準；若尚未在 `origin/main`，請向使用者確認 Windows 端是否已 push。
- Mac 先執行 `git pull --ff-only`，確認包含 `0aac0c0`（`git merge-base --is-ancestor 0aac0c0 HEAD`）。遠端若已前進，以實際 HEAD 為準，並另外說明差異。
- Windows 端的原始工作紀錄與證據檔只在 Windows 機器上，Mac 拿不到。需要的事實都已整理在本文；完整的 Windows 驗證紀錄見 [windows-validation.md](windows-validation.md)。

## 2. Windows 做了什麼（已實測）

Windows 10 Enterprise LTSC 19044 x64、Claude Code 2.1.303、Codex 0.163.0-alpha.10.2。

1. **Hook 啟動逾時**：原本啟動兩次 Python，耗掉 1 秒預算。改成在同一個程序內執行 gate（Job 綁定後才執行目標），並延後匯入 engine 與 packet 模組。
2. **Claude 模型清單**：原本在零 capabilities 的 LPAC 內，initialize 會在 `WSAStartup` 10107 失敗。
   - 原因：Claude 2.1.303 是 Bun 1.4.4 編譯，內含 libuv；libuv 的 `uv_loop_init` 一定會初始化 Winsock。Winsock 要讀 `HKLM\...\WinSock2\Parameters`，而這把鍵的 ACL 只開放給 BU、ALL APPLICATION PACKAGES 與 `registryRead`。
   - 使用者決定：維持 LPAC，只加 `registryRead` 一個 capability。
   - 實作：capability 白名單只允許 `registryRead`；行程恢復前，token 的 capability 清單必須和要求的完全一致；只有 initialize 帶 `registryRead`，`--version` 維持零。
   - 結果：取得 5 個模型（default、opus、fable、sonnet、haiku，各支援 low～max 五級 effort）。網路、私人登錄檔、外部檔案仍被擋，19 項原生測試通過。
3. **Claude 路由已啟用**：使用者已同意所有本機磁碟與 UNC 的 Claude 任務內容送往 Jev。
   - 政策：Light `haiku:max`、Small `sonnet:high`、Mid `opus:xhigh`、Top 交回 Main。
   - 真實委派驗證過：Light、Small、Mid 的建議→重發→子代理完成→Post 記錄 followed=1；Top 攔下並由主模型處理；明示模型保留；具名角色（Explore）保留；低信心（低於 0.5 門檻）保留原呼叫；Post 失敗注入（鎖住記錄庫）時原子代理照常完成、不重複委派。
4. **Hook 時限（只限 Windows，使用者分兩次同意）**：
   - PreToolUse 第一階段（等 child 回報政策前）：1.0 → 2.5 秒。
   - 本機政策的 PreToolUse（明示模型／強度、具名角色等）：1.0 → 2.5 秒。
   - PostToolUse：1.0 → 2.0 秒。
   - Windows Claude 外掛 `hooks.json` 的 Post 宿主逾時：2 → 5 秒。原因是 supervisor 的期限從 PowerShell 與 bootstrap 跑完才起算，那段約 1～1.5 秒，宿主若仍是 2 秒會先把 Hook 殺掉。
   - 驗證：全新 Claude 工作階段同時 6 組委派，0 逾時，6/6 Post 記錄。
   - Codex 真實委派（並行 4 個 `spawn_agent`）：4/4 完成，5 個 Pre、4 個 Post 都有記錄，0 逾時。
5. **`setup.ps1`**：Windows PowerShell 5.1 會剝掉傳給原生程式的雙引號，Python 探測因此誤報。改為只用單引號。
6. **清理**：刪除兩個前幾輪遺留的 `mrh.catalog.diagnostic.*` AppContainer profile（使用者同意，API 讀回已不存在）。暫用的 TinyCC 與測試 payload 已刪除，並保存了雜湊清單。

保全：Claude 與 Codex 的 MRH 設定檔都和重裝前逐位元組相同，Jev 金鑰仍在，舊的未提交檔案沒有變動。

## 3. 提交清單與對 Mac 的影響

| 提交 | 內容 | 改到的共用檔（Mac 也會載入） | Mac 影響 |
| --- | --- | --- | --- |
| `6a90435` | Windows LPAC 清單、各宿主分開的就緒判斷 | `adapters/catalogs/claude_catalog.py`、`adapters/catalogs/catalog.py` | Mac 的 `sandbox-exec` 清單路徑（`isolated_cli`、`_models`）理論上沒改，但同一個檔案有重構，**需驗 Mac Claude 清單** |
| `27edf8f` | Hook 同程序 gate、延後匯入 | `application/advisory_runtime.py`、`adapters/hosts/advisory_hosts.py`、`adapters/hosts/codex_packets.py`、`infrastructure/plugin.py`（2 行） | runtime 匯入時機改變，Codex 封包 marker 移到 host envelope（保留原 `marked`／`PREFIXES` alias），**需做 Mac 原生 Hook smoke** |
| `0983c1f` | LPAC 加 `registryRead` | `claude_catalog.py` 只改 Windows 分支 | 預期沒有 |
| `dc71528` | Pre 第一階段 2.5 秒 | `plugin.py` 的 `_windows_launcher()` 轉換 | POSIX 的 `LAUNCHER` 文字沒變，**需確認位元組相同** |
| `8a2fcee` | 本機 Pre 2.5 秒、Post 2.0 秒 | `advisory/hook_budget.py`（`LOCAL_SECONDS`／`POST_SECONDS` 依 `sys.platform` 取值）、`plugin.py`（Windows 轉換）、`tests/application/test_hook_budget.py`（斷言改依平台） | Mac 數值應仍為 1.0 秒，**需跑測試確認** |
| `9d50280` | `setup.ps1` | 只有 Windows | 無 |
| `212b002` | Codex 外掛 `hooks.json` 的 Post 宿主逾時：Windows 5 秒 | `infrastructure/plugin.py`（新增 `codex_hook_timeout(event, windows=None)`） | 非 Windows 回傳 2，產生的 `hooks.json` 應與改動前位元組相同；**請確認 Mac 的 Codex Hook 沒有因此要求重新信任** |
| `0aac0c0` | `owned.verify` 在 Windows 略過列舉後消失的 SQLite `-wal`／`-shm` | `infrastructure/owned.py`（共用，僅 `os.name == 'nt'` 時生效） | Mac 行為不變；POSIX 同樣的競態見第 5 節「新發現」 |
| 其他（`6edeefb`、`8f8c7f2`、`b2e7923`、`c89245f`、`26dbb48`、`fa6ddc7`） | 只有文件 | — | 無 |

## 4. Mac 必做驗收

全部通過才算收尾。測試與實測分開回報；Windows 的結果不能當成 Mac 證據。

### 4.1 程式碼層

```bash
git pull --ff-only
git rev-parse --short HEAD          # 預期 9d50280
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest \
  tests.application.test_hook_budget \
  tests.infrastructure.test_hook_supervisor \
  tests.advisory.test_context_contract \
  tests.application.test_advisory_runtime \
  tests.infrastructure.test_setup
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest discover -s tests -t .
```

- 前三個模組依賴 `fcntl` 或 POSIX 路徑：`test_hook_supervisor` 在 Windows 上無法匯入；`test_hook_budget` 與 `test_context_contract` 合計 21 項中有 13 項在 Windows 上失敗，HEAD 上也以相同方式失敗。所以這三個模組在這次改動後**沒有任何有效的執行結果**，必須在 Mac 上跑。
- 確認 Mac 的時限沒變：`python3 -c "import sys;sys.path.insert(0,'src');from mrh.advisory import hook_budget as h;print(h.LOCAL_SECONDS,h.POST_SECONDS)"` 應輸出 `1.0 1.0`。
- 確認 POSIX launcher 沒變：已安裝的 `launcher.py` 應與 `mrh.infrastructure.plugin.LAUNCHER` 位元組相同（路徑看 `./setup --check --json`）。

### 4.2 安裝

`./setup --host claude --host codex`（依 Mac 現有安裝的宿主而定），再跑 `./setup --check --json`。確認 generation 完整性為 verified、各宿主的 routing 狀態，以及 `pending` 為空。程式有變，所以會產生新的安裝代。安裝前後請比對 MRH 設定、統計與金鑰狀態（只看雜湊與是否設定，不讀出金鑰）。

### 4.3 原生 Hook smoke（Claude 與 Codex 各做一次）

用最小、不含敏感資料的合成任務（例如「只回覆 OK，不用任何工具」）：

1. 停用的 profile：Pre 與 Post 都回 `{}`。若 Mac 已啟用，可以只用一份臨時停用的 profile 驗，或說明為何跳過；**不要為了測試改動使用者正式的啟用狀態而不還原**。
2. 啟用後的一般委派：Pre 給出建議並攔下原委派 → 依建議重發 → 子代理完成 → Post 記錄 followed=1。
3. 明示模型委派：Pre 保留原呼叫（`explicit_model`），不呼叫 Jev。
4. Codex 保留封包：被拒絕或照原有方式處理（Windows 不支援封包，這一項只能在 Mac 驗）。
5. 確認沒有逾時、重複委派或孤兒程序。

讀回只用唯讀方式，不輸出任務內容：

```bash
sqlite3 "file:<設定目錄>/advice.sqlite3?mode=ro" \
  "select action,reason,tier,confidence from advice order by rowid desc limit 5;
   select requested_model,requested_effort,resolved_model,followed from children order by rowid desc limit 5;"
```

### 4.4 Claude 清單（`sandbox-exec`）

`mrh models --host claude --json`，確認是在 `sandbox-exec` 隔離下取得清單，沒有退回無隔離。這條路徑沒改過，但 `claude_catalog.py` 有重構。

## 5. 未決項目與已解決項目

已解決（Windows，2026-10-23，使用者在 Codex 原生 `/hooks` 信任後驗證）：

- **Codex Post 宿主逾時**：改為 Windows 5 秒（`212b002`），Mac 仍為 2 秒。信任後 `trust: trusted`、路由 ready；真實 `codex exec` 並行 4 個 `spawn_agent`，4 個 Pre 與 4 個 Post 全部有記錄。
- **Small／Mid 並行**：全新 Claude 工作階段並行 3 Small ＋ 3 Mid，5 個建議（Small 0.68／0.69、Mid 0.75×3）→ 重發 5/5 → Post 5/5 記錄、followed=1。

新發現（需 Mac 評估，不要代替 Windows 結論）：

1. **並行 Hook 的設定讀取競態**：`owned.verify` 走訪設定資料夾並逐一 `lstat`，並行的 Hook 讓 SQLite 刪除 `-wal`／`-shm`，列舉與檢查之間檔案消失會變成 `settings_unowned`，使用者看到「settings unavailable」且該次 Pre 沒有任何記錄。Windows 已修（`0aac0c0`，私有複本壓力測試修正前約 0.24%、修正後 0 次）。**POSIX 的同一段程式（`os.name != 'nt'` 分支的 `path.lstat()`）理論上有同樣的競態，這次刻意沒改**；Mac 可以先用多個並行 Hook 加 SQLite 開關壓力確認是否可重現，再決定是否採用相同修正（拿掉 `os.name == 'nt'` 條件即可，`test_platform` 的 `test_owned_directory_check_tolerates_sqlite_sidecars_vanishing_but_nothing_else` 可改寫成 POSIX 版）。

仍未決（不擋 Mac 收尾）：

2. Windows 的 `.codex/config.toml` 有幾個非 MRH 的鍵（`model`、`model_reasoning_effort`、`service_tier`）和 10 月 22 日的備份不同。安裝器不會寫這些鍵，Codex 當時也在執行，所以判斷是 Codex 自己改的，但無法證明改動時間。之後的比對只有 MRH 自己的信任雜湊與 marketplace 指標有變。
3. 已開著的 Claude 工作階段（Windows）要重開或重新載入外掛，才會用到新的 Post 宿主逾時 5 秒；新工作階段已實測載入。
4. 並行驗證只用合成的小任務；Codex 並行這次的 Jev 判斷都低於 0.5 門檻（全部保留原呼叫），建議→重發→Post 關聯在稍早一次 Codex 執行（Post 定義變更前）已驗過。
## 6. 邊界

- 不要 push、發布或改動其他機器，除非使用者當下明確同意。
- 不要放寬 Mac 的 `sandbox-exec` 隔離、不要寫死模型清單、不要偽造初始化成功。
- 不要改 Mac 的時限數值；這次的放寬只限 Windows。
- 保留使用者的設定、統計、金鑰、其他插件與既有的未提交修改。
- 新失敗先找原因，不要靠刪檢查或加大時限讓它通過。

## 7. 回報格式

逐項列出「通過／未通過／受阻」並附證據：

- 4.1 程式碼層：各模組的通過與失敗數；分辨 Mac 既有失敗與本次改動造成的失敗（對照 `6d10f9f`）。
- 4.2 安裝：generation、commit、完整性、各宿主就緒狀態，以及設定、統計、金鑰的保全結果。
- 4.3 Hook smoke：Claude 與 Codex 各情境的 advice／children 讀回。
- 4.4 Claude 清單。
- Git 狀態、是否 push、安裝代 ID。
- 第 5 節的未決項目原樣保留，除非使用者另有指示。
