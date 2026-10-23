# Mac 驗收交接：Windows 修復後的收尾

狀態：**本輪 Mac 驗收及 POSIX 暫存檔競態的最小修正已完成；必要驗證、兩宿主套用與文件收尾均已接受，此修正沒有剩餘工作**。Git 發布與本機安裝分開核對。給 Mac 上的 Codex（或任何接手者）使用，日期：2026-10-23。這是交接用文件，不是安裝或執行的依賴。

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
| `0aac0c0` | 該提交的 `owned.verify` 在 Windows 略過列舉後消失的 SQLite `-wal`／`-shm` | `infrastructure/owned.py`（該提交僅 `os.name == 'nt'` 時生效） | 該提交不改 Mac 行為；後續本機 POSIX 修正見第 5 節及收尾結果，未包含於此提交。 |
| 其他（`6edeefb`、`8f8c7f2`、`b2e7923`、`c89245f`、`26dbb48`、`fa6ddc7`） | 只有文件 | — | 無 |

## 4. Mac 必做驗收

全部通過才算收尾。測試與實測分開回報；Windows 的結果不能當成 Mac 證據。

### 4.1 程式碼層

```bash
git pull --ff-only
git rev-parse --short HEAD          # 本輪指定 6b0ebd8；遠端更前時另核對差異
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest \
  tests.application.test_hook_budget \
  tests.infrastructure.test_hook_supervisor \
  tests.advisory.test_context_contract \
  tests.application.test_advisory_runtime \
  tests.infrastructure.test_setup
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest discover -s tests -t .
```

- 前三個模組依賴 `fcntl` 或 POSIX 路徑：`test_hook_supervisor` 在 Windows 上無法匯入；`test_hook_budget` 與 `test_context_contract` 合計 21 項中有 13 項在 Windows 上失敗，HEAD 上也以相同方式失敗。這是原交接要求 Mac 執行的原因；前輪 ddc4e4157 已有 Mac 通過紀錄（第 8 節），新版仍按本輪明確指定的驗收命令執行，不能把 Windows 失敗或舊版結果冒充本輪結果。
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

並行問題（Mac 評估與後續診斷已完成，Windows 結論獨立保留）：

1. **並行 Hook 的設定讀取競態，已完成本機修正**：`owned.verify` 列出設定資料夾後逐一 `lstat`，SQLite 暫存檔消失可能呈現 `FileNotFoundError` 或 POSIX 連結數 0，兩者曾被誤判成 `settings_unowned`，最後顯示「settings unavailable」。最小修正已處理精確四種暫存檔的這兩個狀態，其餘安全檢查保留，並通過必要回歸、兩宿主套用及原工作量自然驗收。Windows 原有修正為 `0aac0c0`（私有複本壓力測試修正前約 0.24%、修正後 0 次）；這些數字不是 Mac 或日常故障率，本輪也未重跑 Windows。詳見[收尾結果](#posix-最小修正與收尾結果)。

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

## 本輪 Mac 驗收結果（6b0ebd8）

2026-10-23 已完成本輪原交接要求的執行與證據覆核；來源為 `6b0ebd873957dd49b5a7c8315f4130a6e706f82d`，包含 `0aac0c0`。下表及原次壓測是當時版本的紀錄，後續 POSIX 修正另列於收尾結果，不改寫原始失敗或略過，也不宣稱所有情境零故障。

| 項目 | 結果與界線 |
| --- | --- |
| 4.1 測試 | 五模組 81 PASS（12／7／9／10／43），56.793 秒；discover 570 項＝458 PASS、112 SKIP、0 FAIL／ERROR，134.558 秒。各執行一次；沒有失敗案例，不重跑舊版基準。 |
| Mac 時限、定義與信任 | LOCAL_SECONDS／POST_SECONDS 仍為 1.0／1.0，Codex Post 仍為 2 秒；212b002 前後同參數生成的 hooks.json、正式 Codex hooks.json 前後均逐位元組相同。原生兩個 Hook 的定義、雜湊與 trusted 狀態相同，沒有要求重新信任。POSIX launcher 與 6d10f9f 及安裝產物相同。 |
| 4.2 更新與保全 | 安裝代 `4932cccf01e71f11244084ad`，兩宿主 configured、pending 為空、金鑰存在。MRH 設定、適用範圍及所有原統計資料列保留，新增本包事件分列。Codex 非 MRH 設定語意未變；Claude 其他 Hook 有來源未知差異，整份設定不可標完全保全，MRH entries 相同，現值未回寫。 |
| 4.3 Codex | 0.163.0：一般委派 Light/0.84 → gpt-6-luna/high → 一次重發 → 獨立官方 child completed/OK、Post followed=1。明示 Sol 保留、無 Jev，child 也有獨立終結證據；未指定 effort，實際為 low，不能稱繼承父層 xhigh。保留封包原生拒絕；disabled 依 4.3.1 例外仍為 SKIP，不算 PASS。Post resolved_model 空值仍與獨立 metadata 證據分開。 |
| 4.3 Claude | 2.1.309：一般委派 Light/0.87 → haiku/medium → child completed/OK、Post followed=1；明示 haiku 保留且無 Jev，child completed。實際 child effort 未獨立回報。獨立 disabled profile 的原生 Pre／Post 均為 {}、exit 0，child completed，未建立 MRH DB。 |
| 4.4 Claude 清單 | 2.1.309 實際取得 5 模型，complete、isolated-defaults；安裝 catalog 與來源雜湊一致，使用 sandbox-exec，無無隔離 fallback。未宣稱 syscall tracing。 |
| 清理 | 自有三個 fixture 根共 53 檔清理，精確自有程序群組與 fixture 引用程序均無殘留；原資料、官方 session、必要證據、備份及具名 stash 保留。 |

本輪原生一般／明示派工未觀測到 Hook 逾時或重複子代理；共 3 個 native parent、5 個有獨立完成證據的 child，Jev transport **2 次**，8 筆 lifecycle 不是 8 次請求。沒有查費率。

**原次 POSIX 自然壓測觀測到問題，當時尚未修正。** 未修改的本輪 launcher/runtime，在獨立設定與 SQLite 資料庫上使用 4 個 Hook worker 加 1 個 SQLite 開關 writer。4.172 秒內完成 36 個 Hook（20 Pre／16 Post）及 1,090 次 SQLite 開關；35 個回 {}，1 個 Pre 回報 settings unavailable，對應缺一筆 Pre 記錄，首次故障後即停止。壓測沒有呼叫 provider，沒有執行額外受控消失案例。這是刻意壓力樣本，不能推算日常故障率；真實 supervisor 未暴露內層例外，故不能把可見訊息當成已直接捕捉 FileNotFoundError 堆疊。

上述原次評估沒有修改產品。後續最小修正依使用者授權完成，保留 owner、marker、符號／硬連結、未知檔案及其他檔案消失的拒絕條件；來源與兩個 Mac 宿主的實際套用均已核對。原驗收中不受影響的有效測試沿用。

### POSIX 後續根因診斷

一次帶例外觀測的隔離 runtime 診斷，使用原始未改的 runtime 與自然 SQLite 開關流程，0.773 秒內完成 8 個 Hook、187 次 SQLite 開關，捕捉到一個 Post 的完整例外鏈：`owned.verify` 對 `advice.sqlite3-wal` 執行 `lstat` 時收到 `FileNotFoundError`（errno 2），同一例外被 `settings_v2._location` 包成 `settings_unowned`，再由 `advisory_runtime` 顯示 `settings_unavailable`。當次原工具繼續執行，但合成 child receipt 少一筆（4 筆 advice、3 筆 child receipt）。沒有設定內容損壞的證據。

這項診斷沒有手動刪除暫存檔、沒有 provider 呼叫或真實子代理，正式設定、資料、程式與安裝未變。它證明了故障機制，但不是原 launcher 全鏈的未改重現，也不是前一次 Pre 的事後堆疊；前一次精確內因仍未記錄。觀測會影響排程，不能用 8 次中 1 次估計正式發生率。

第一版最小修正只容忍上述 `FileNotFoundError`，已通過相應回歸並套用到 Mac，但原自然驗收仍出現一次 `settings_unavailable`，因此未接受為完整修復。後續帶全域例外觀測的診斷確認 28 次檔案不存在已被正確放行，卻未捕捉目標故障，且觀測影響了執行時間；這批結果不能代替自然驗收。

改用只在設定讀取例外時留紀錄的隔離觀測後，同一問題的另一個狀態已直接確認：`lstat` 成功回傳 `advice.sqlite3-wal` 的 regular-file 資訊，owner 正確，但 `st_nlink` 已是 0，因而被判成 `unsafe_owned_file`，再轉成 `settings_unavailable`。最終修正同時處理這兩種已消失狀態；只有精確四種、已允許、regular 且 owner 正確的 SQLite 暫存檔可接受連結數 0。其他檔案、非 regular、錯誤 owner、連結數大於 1 及其他錯誤仍拒絕。

### POSIX 最小修正與收尾結果

此修正已完成並接受，沒有新增技術剩餘項目。產品只改 `owned.verify` 的側檔判斷；未改 schema、設定 API、launcher、時限、Hook 信任或 Windows ACL。新增回歸集中在 `tests.infrastructure.test_owned_sidecars`，同一組 6 項修前紅、修後綠，涵蓋四種側檔的 ENOENT／連結數 0 與受影響的安全負向保護。

Mac 兩宿主已更新到安裝代 `1e33d5b63efdd39756afe1ea`。兩份 runtime、app archive 與 Codex 原生快取中的修正皆與工作目錄一致；修正來源 `owned.py` SHA-256 為 `c174da36fbd53a37d4d7b2469c770e425384fc42b905c219375bcd87823ff6c7`。該次安裝建立時 Git HEAD 為 `6b0ebd8`，修正當時尚未提交；後續 Git 提交不改變已安裝的程式 bytes，不能把安裝 manifest 的來源提交欄位當成該舊提交已包含新碼。

最後一次自然驗收使用與新安裝逐位元組相同的隔離 launcher/runtime，沒有 trace、設定讀取包裝、人工刪檔、provider 呼叫或真實子代理。4 個 worker＋1 個 SQLite writer 在 3.365 秒完成 44 個 Hook（24 Pre／20 Post）及 1,090 次 SQLite 開關，44 個均回 `{}`，沒有設定不可用、其他故障、逾時或 writer 錯誤。每個 worker 已完成 5 組 Pre／Post，達原定工作量即停；4 個在途 Pre 收完後沒有再安排 Post，所以合成 advice／children 為 24／20，並非已執行 Post 漏記。這是原定工作量的驗收，不是正式故障率估計。

正式 MRH 設定、適用範圍、7 張表的全部原資料列及金鑰存在狀態保留。兩個 launcher、Codex Hook 定義與 trusted 狀態不變，Mac 內部 Local／Post 仍為 1／1 秒、Codex Post 宿主時限仍為 2 秒。Claude 私有產物的 Hook JSON 只有安裝代的 Python 路徑變動，不能稱原始 bytes 全同；最終更新前後的正式 Claude 設定完整相同。中途不同基準之間曾有非 MRH 的 SessionStart／UserPromptSubmit 變動，來源未知，MRH entries 不變，現況保留，不把它新增為本修正待辦。

本輪 16 個自有 fixture 檔及執行目錄已清理，44 個 launcher 程序均已回收；必要失敗與成功證據、原資料、備份、前代及 stash 保留。不受影響的既有測試與原生證據沿用，沒有重跑完整套件或擴大平台驗證。

文件已整合；Git 發布不重開已完成的產品驗證。第 5 節的 Windows 已解決事項與其餘限制繼續保留，不重新開啟已完成驗證。

## 8. 前輪 Mac 驗收紀錄（僅 ddc4e4157）

以下是本地原修改保留的前輪紀錄。前輪由 `6d10f9f` 快轉至 `ddc4e4157`，相對程式碼 `9d50280` 只多交接文件，該包已被接受。**以下通過／SKIP 與設定觀測只屬 ddc4e4157，不證明本輪 6b0ebd8 已通過**；本輪仍以第 4 節和保存的新 HEAD 交接原件驗收。舊第 5 節的 Windows 未決狀態已被本頁新第 5 節取代，沒有用舊事實覆蓋新結果。

本次已按以下項目完成驗收。Codex 停用原生依原 4.3.1 的已啟用 Mac 例外列 SKIP，未算 PASS；整份 Codex 設定亦有來源未知差異，不能稱完全保全。測試與實測分開回報，Windows 結果不當成 Mac 證據。以下指令保留供重現；有效結果不因整理文件再跑。

### 前輪 4.1 程式碼層

指定五模組依序為 12、7、9、10、43 PASS，共 **81 PASS、0 FAIL／ERROR／SKIP**，46.271 秒。完整 discover 為 **568 run：458 PASS、110 SKIP、0 FAIL／ERROR**，91.487 秒。沒有失敗案例，沒有另跑 `6d10f9f` 來補造基準結果。Mac LOCAL_SECONDS／POST_SECONDS 都是 1.0；兩宿主已安裝 launcher 與目前 POSIX LAUNCHER、`6d10f9f` 的常數逐位元組相同。

```bash
git pull --ff-only
git rev-parse --short HEAD          # 本次驗收 ddc4e4157；程式碼為 9d50280
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest \
  tests.application.test_hook_budget \
  tests.infrastructure.test_hook_supervisor \
  tests.advisory.test_context_contract \
  tests.application.test_advisory_runtime \
  tests.infrastructure.test_setup
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest discover -s tests -t .
```

- 原交接的前三個模組依賴 `fcntl` 或 POSIX 路徑：`test_hook_supervisor` 在 Windows 上無法匯入；`test_hook_budget` 與 `test_context_contract` 合計 21 項中有 13 項在 Windows 上失敗，當時 HEAD 也相同。這是要求補 Mac 驗證的原因；現在三個模組已有上述 Mac 通過結果，Windows 的歷史失敗仍保留。
- 確認 Mac 的時限沒變：`python3 -c "import sys;sys.path.insert(0,'src');from mrh.advisory import hook_budget as h;print(h.LOCAL_SECONDS,h.POST_SECONDS)"` 應輸出 `1.0 1.0`。
- 確認 POSIX launcher 沒變：已安裝的 `launcher.py` 應與 `mrh.infrastructure.plugin.LAUNCHER` 位元組相同（路徑看 `./setup --check --json`）。

### 前輪 4.2 安裝

`./setup --host claude --host codex`（依 Mac 現有安裝的宿主而定），再跑 `./setup --check --json`。確認 generation 完整性為 verified、各宿主的 routing 狀態，以及 `pending` 為空。程式有變，所以會產生新的安裝代。安裝前後請比對 MRH 設定、統計與金鑰狀態（只看雜湊與是否設定，不讀出金鑰）。

本次更新保留既有 `--codex-packets` 選配，新安裝代來源為 `ddc4e4157`；完整性驗證通過。最終檢查為兩宿主 configured、Codex trusted、pending 為空、金鑰仍存在。MRH 設定、Claude 設定、適用範圍及所有原統計資料列保留，合成驗證新增的記錄另行計數，沒有刪除舊資料。

整份 Codex `config.toml` 不是 byte-equal：MRH marketplace 來源更新為新安裝代屬預期；另有非 MRH `service_tier` 從 `default` 變成 `priority`，寫入者與確切改動時點未知。保留目前值，不歸因安裝器，也不回寫或作為已證明的分級故障。

### 前輪 4.3 原生 Hook smoke（Claude 與 Codex 分項）

用最小、不含敏感資料的合成任務（例如「只回覆 OK，不用任何工具」）：

1. 停用的 profile：Pre 與 Post 都回 `{}`。若 Mac 已啟用，可以只用一份臨時停用的 profile 驗，或說明為何跳過；**不要為了測試改動使用者正式的啟用狀態而不還原**。
2. 啟用後的一般委派：Pre 給出建議並攔下原委派 → 依建議重發 → 子代理完成 → Post 記錄 followed=1。
3. 明示模型委派：Pre 保留原呼叫（`explicit_model`），不呼叫 Jev。
4. Codex 保留封包：被拒絕或照原有方式處理（Windows 不支援封包，這一項只能在 Mac 驗）。
5. 確認沒有逾時、重複委派或孤兒程序。

本次結果：

| 情境 | Codex CLI 0.163.0 | Claude Code 2.1.309 |
| --- | --- | --- |
| 停用 | **SKIP**：依第 1 點例外接受；獨立設定根缺可用原生認證／信任，沒有已驗證的單次 profile 入口。未複製 OAuth、繞信任或改正式開關。 | 真原生 Pre／Post 都回 `{}`、exit 0，child completed/OK，臨時 profile 未建立 MRH DB。 |
| 一般委派 | 真 Jev Light/0.77 → `gpt-6-luna/high` → 一次重發 → 官方 child completed/OK；實際 profile 另行核對，Post followed=1，Post resolved_model 仍 null。 | 真 Jev Light/0.87 → haiku/medium → 一次重發 → child completed/OK；Post resolved `claude-haiku-5-5`、followed=1。 |
| 明示模型 | explicit_model 保護通過，無 Jev；Post 有 child 記錄，但該 child 終結僅 parent 回報，未取得獨立 child 身分。 | 明示 haiku 保留、無 Jev；child completed/OK。實際 child effort 未獨立回報，不與 requested effort 混同。 |
| 保留封包 | 原生拒絕 `packet_marker_invalid`，未建 child 或重試。 | 不適用。 |

本包共 3 次 Jev transport（Codex 2、Claude 1），包含首次低信心的真請求；狀態生命週期的 12 筆記錄不當成 12 次請求。初次 Codex 一般委派因 runner 的 ephemeral parent 缺 rollout 而失敗，保留失敗，只修 runner 並補該案例一次；已通過的明示模型與 packet 不重跑。沒有觀測到 MRH Hook 逾時或重複成功委派；四個自有 CLI 程序群組均已退出，自有臨時材料已清理，官方 session、原件及備份保留。

讀回只用唯讀方式，不輸出任務內容：

```bash
sqlite3 "file:<設定目錄>/advice.sqlite3?mode=ro" \
  "select action,reason,tier,confidence from advice order by rowid desc limit 5;
   select requested_model,requested_effort,resolved_model,followed from children order by rowid desc limit 5;"
```

### 前輪 4.4 Claude 清單（`sandbox-exec`）

`mrh models --host claude --json`，確認是在 `sandbox-exec` 隔離下取得清單，沒有退回無隔離。這條路徑沒改過，但 `claude_catalog.py` 有重構。

本次實際命令取得 5 模型，初期 CLI 版本為 2.1.296。兩次原生派工 init 均回報 2.1.309，最終安裝檢查的清單驗證亦為 2.1.309、isolated-defaults。安裝版 catalog 與來源一致，Mac 路徑使用 `sandbox-exec`，沒有無隔離 fallback。這是命令成功及不可變程式路徑證據，不宣稱做過外部 syscall tracing。
