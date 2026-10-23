# 開發指南

## 原始碼位置

| 路徑 | 責任 |
| --- | --- |
| `src/mrh/advisory/` | 任務分級、候選政策、建議與統計。 |
| `src/mrh/adapters/hosts/` | 各宿主原生事件與回覆格式。 |
| `src/mrh/adapters/catalogs/` | 模型清單與版本驗證。 |
| `src/mrh/adapters/providers/` | 分級來源接頭。 |
| `src/mrh/adapters/platforms/` | Windows 原生檔案／ACL、程序、私有 Python 與 Credential Manager 接頭。 |
| `src/mrh/presentation/` | CLI 與互動控制中心。 |
| `mrh_setup.py`、`mrh_bundle.py` | 安裝生命週期與 macOS arm64 封裝。 |
| `setup.ps1`、`mrh_windows_setup.py` | Windows 原生 x64 安裝、註冊、更新、檢查與退版。 |
| `tests/` | 離線單元與隔離測試。 |
| `scripts/verification/` | 需依各腳本用途明確執行的驗證工具。 |

原始碼需要 Python 3.11 以上。作業系統與宿主相容性仍以 [平台表](compatibility.md) 為準，不因 wheel 使用 pure-Python 標籤就宣稱跨平台支援。

Windows 使用本機既有 x64 CPython 建立私有 runtime，保留標準函式庫、DLL 與授權，排除 `site-packages`；不加入 Python 下載或 pip 安裝。Mac 的 3.11.17 runtime lock、第三方聲明與 Claude catalog metadata 驗證保留；Claude CLI 最低版本與 catalog 清單是否已確認分開處理，各平台接頭不能互相代替驗證。

## 本機開發安裝（`--dev`）

只改文件不會產生新版本：安裝版本只由會裝進去的程式內容決定，與 git commit 無關，重跑 `./setup` 會回報沒有變更。程式有改時，一般安裝仍要重跑 `./setup` 才會生效。

自己開發時可使用 `--dev`，兩平台的候選都保留打包入口，再載入同一份來源：

~~~sh
./setup --host claude --host codex --dev --codex-packets
~~~

Windows 在 PowerShell 使用 `.\setup.ps1 --host codex --host claude --dev --codex-packets`。不需要 packets 時省略該選項；仍只選實際使用的宿主。

- CLI 與 Hook 在下次啟動時讀取來源 `src/`；一般程式修改存檔即可生效，已在執行的程序不熱更新。
- 兩種模式都保留打包 bootstrap，安裝／檢查時核對安裝代。Hook 啟動前驗證 runtime 與 PEP 660 連結雜湊，CLI 經打包入口檢查連結及來源安全性；Windows bootstrap 另核對啟動檔與 manifest。Windows 保留 site-free `_pth`，不載入全域 site-packages，也不執行任意 `.pth` 程式。
- 來源必須由目前使用者控制、不可供其他人改寫，且不經符號連結／reparse point；來源不可用時 CLI 明確失敗，Hook 保留原呼叫並通知。可變來源本身不宣稱是 immutable artifact。
- 安裝程式、建置後端、`execution.py`、`owned.py`、`plugin.py` 或平台 bootstrap 相依改變，仍需重跑同一安裝命令；換 checkout 也需重跑。來源指紋區分這些 bootstrap 與日常 mutable 來源。
- `--check --json` 的 `execution_mode`、`source`、`runtime_root` 顯示綁定。一般模式不含 dev 來源，刪除來源不影響打包程式；舊 profile／外部白名單原本引用的檔案仍須保留。
- 要回到一般安裝，不帶 `--dev` 重跑。兩種模式都可保留 `--codex-packets`，不與 `--rollback`／`--uninstall` 同時指定 dev。設定、金鑰、統計及原指標不遷移、不重設。
- 切換前完成舊 packet。新協議以根鎖互斥 prepare 與切換；不保證舊版在途程序或程序退出後的 admission。遇到 `installation_recovery` 先用原參數恢復，再做新 packet，詳見[失敗與復原](install-lifecycle.md#失敗與復原)。

雙模式與 Windows packets 的正式原生驗收仍待完成，不把本機隔離測試當成已部署。標準 Python frontend 可使用離線 `pip install -e . --no-deps --no-build-isolation`（需已有支援 PEP 660 的 pip）；這只安裝套件，不替代宿主安裝器或修改 Hook。

## 測試

在 repository 根目錄執行。測試 guard 使用假 HOME 並阻擋 TypeSafe 網路，也會為整次測試自建一個私有、解析過符號連結的暫存目錄（`tests/__init__.py`），不論 `TMPDIR` 設成什麼都能跑；macOS 預設的 `/var/folders/...` 經過符號連結，MRH 的所有權檢查會拒絕，所以測試不直接使用它。執行直接受影響的測試，例如：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest tests.application.test_advisory_runtime
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest tests.infrastructure.test_setup
```

Windows 的直接受影響測試在 PowerShell 執行；依變更選擇其中一個模組：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = 'src'
python -B -m unittest tests.windows.test_platform
python -B -m unittest tests.windows.test_setup
```

`-I` 會忽略 `PYTHONPATH`，因此上述原始碼測試不使用 `-I`；已安裝入口與安裝器依自己的隔離契約使用 `-I -B`。驗證命令與各 Python 子程序都需帶 `-B`，不要把 bytecode 寫入受完整性檢查的產物。

Claude Windows catalog 的直接測試是 `tests.windows.test_claude_catalog`、`tests.windows.test_claude_routing` 及 `tests.adapters.test_claude_catalog.ClaudeInitializeParserTests`。原生隔離案例另用 `tests.windows.test_lpac`，需要先把 `lpac_payload.c` 編成私有的 x64 測試 exe；未提供 payload 的案例會明確略過，不能算原生隔離通過。

可使用已核對來源及雜湊的 TinyCC 0.9.27 x64；不安裝到系統或加入 PATH，保留工具原有授權。`$scratch` 請指向私有、可刪除的測試目錄：

```powershell
python -B tests/windows/build_lpac_payload.py --cc 'C:\Tools\tcc\tcc.exe' --output "$scratch\lpac_payload.exe"
$env:MRH_LPAC_TEST_HELPER_EXE = "$scratch\lpac_payload.exe"
python -B -m unittest tests.windows.test_lpac
```

payload 不連結 CRT，只匯入 kernel32，按測試模式觀察合成檔案、程序及無資料的 TCP 連線；不含任務、登入或憑證。builder 保留 relocation、啟用 ASLR／NX，避免舊式 PE 被 LPAC 拒絕。正式接頭每次建立新 profile、只繼承指定管線，先核對 AppContainer、capabilities 與要求完全一致（預設零；唯一白名單項目為 `registryRead`）、低完整性、package SID、ALL APPLICATION PACKAGES 拒絕、映像及 Job，才解除懸停。未知或清理失敗均拒絕清單；capability 名稱為封閉白名單，未列名稱在建立 profile 前即拒絕。設計依據為 [Microsoft LPAC 啟動流程](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)。

需要整體離線回歸時：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest discover -s tests -t .
```

部分測試使用 macOS／POSIX 的程序、PTY 或 sandbox 能力。文件修改檢查語意、連結與相容性說明即可；fixture 修改則驗證資料形狀及直接讀取它的 consumer。

Windows 範圍設定另需保留兩種語意：`--all-workspaces` 保存 `allowed_workspaces: ["*"]`，涵蓋所有本機磁碟與支援的 UNC 專案路徑；一個或多個 `--workspace` 只涵蓋有效的絕對路徑，兩者互斥。使用隔離 fixture 驗證路徑判斷，不為測試改動真帳號的外送範圍；Mac `/` 的既有語意保持不變。

## Fixture 與原始驗證資料

[`tests/fixtures`](../tests/fixtures/README.md) 的去識別化資料只供離線回放。保留事件格式、關聯與測試需要的模型欄位；不得把它當成可執行命令、真帳號資料或新的宿主驗證結果。

驗證腳本產生的原始輸出應放在被 Git 忽略的 `runtime/`，不要提交個人路徑、session、聊天內容、金鑰或原始宿主日誌。第三方授權與 runtime provenance 原件另依其既有授權保留。

`scripts/verification/` 不是可無差別批次執行的測試套件。執行前先讀腳本：有些需要指定的 bundle、原生 CLI、帳號、宿主註冊或外部請求。離線單元測試不能替代真宿主採用；反過來也不必為文件整理重新呼叫模型。

Windows 的驗證分開記錄私有 runtime／檔案完整性、原生插件與 Hook 註冊、信任、金鑰狀態、模型政策、Jev 回應及子代理採用。`--check --json` 不呼叫 provider；CLI 已登入或模型 metadata 可讀，也不能補成後兩項成功。Claude 清單沿用其 LPAC 驗證；Windows 訂閱分級器與 Gemini 仍不可用。新增雙模式及 packets 的 Windows 原生驗收須獨立補齊，不能以 Mac 隔離結果或普通委派歷史填補。

## 開發用 CLI 探測

Gemini 探測工具需要明確指定公開 CLI 套件目錄與 Node 執行檔，不依賴維護者電腦上的安裝路徑：

```sh
python3 -B scripts/verification/catalogs/probe_gemini_acp.py --help
python3 -B scripts/verification/catalogs/verify_gemini_entry.py --help
```

實際執行需提供 `--gemini-package`、`--node` 及 `--output`；第二個工具另需 `--bundle`。輸出請放在忽略的 `runtime/verification/`。這些工具涉及本機 CLI 的隔離執行，不會在一般套件安裝時自動執行。

## 擴充與授權

變更原生接頭前先讀 [新增宿主](host-extension.md)；新增資料出口需保留 [metadata 契約](contracts/monitor-v1.md) 的身分、未知值與快照語意。

MRH 採用 [MIT License](../LICENSE)。Python runtime 各有自己的 LICENSE／NOTICE，散布時須保留其授權聲明。Windows 私有 runtime 保留來源 Python 的 `LICENSE.txt`，安裝代另保留 MRH 與 Python 授權；不要移除 [Mac runtime 聲明](../packaging/macos-arm64/LICENSES.md) 或既有 provenance。
