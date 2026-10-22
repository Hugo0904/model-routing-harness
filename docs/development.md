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

Windows 的驗證分開記錄私有 runtime／檔案完整性、原生插件與 Hook 註冊、信任、金鑰狀態、模型政策、Jev 回應及子代理採用。`--check --json` 不呼叫 provider；CLI 已登入或模型 metadata 可讀，也不能補成後兩項成功。Claude 模型清單、訂閱分級器、Codex packets、Gemini 的 Windows 不可用狀態須保留，不能以 Mac 歷史結果填補；本次沒有 Mac 實機重驗。

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
