# E15：可搬移的 macOS arm64 本機候選包

這個候選包讓使用者保留「MRH 加所選 vendor CLI」的操作方式，不需要另外建立 Python 環境、安裝 AI SDK／Node 或部署 bridge。MRH 自帶私有 CPython；vendor CLI 本身的安裝需求仍由該 CLI 負責。A 已親自操作並接受這份本機候選，詳見 [A 驗收](evidence/e15-a-acceptance.json)。它不是已發布、簽章／notarize 的全平台 release，也不代表 R1 或 R2／Gemini 已完成。

## 取出與操作

本機交付物位於 ignored `dist/model-routing-harness-0.3.0-macos-arm64.tar.gz`，展開目錄為同名、不含 `.tar.gz` 的資料夾。Archive／manifest 的確切 SHA256 見 [建置證據](evidence/e15-build.json) 和同目錄的 `.sha256` 檔。支援 macOS arm64；官方 metadata 的 deployment target 為 macOS 11.0，本次只驗證記錄的本機版本。

用系統 Archive Utility 或 `tar -xzf` 取出，先選一個穩定位置。進入展開目錄後：

```sh
./mrh --help
./mrh doctor
./mrh model
```

選 AI、模型、推理強度，再 review／save，沿用現有方向鍵與 Enter 操作；取消不保存 policy。Routing／task export 仍預設關閉，不會因選模型而啟用。若想在別處只輸入 `mrh`，可自行在既有、自己擁有的 PATH 目錄放一個指向這個 `mrh` 檔的 symlink；入口會解開相對／絕對 symlink。候選包沒有改本機 shell profile 或系統目錄。

設定／history 沿用外部 profile 路徑，放在 application bundle 外。`plugin prepare` 會綁定這份程式的私有 interpreter；準備前先選穩定位置。若之後搬動 application，需對同一個外部 settings path 重新 prepare，再另外核對 native registration／trust。程式不會自動改 Hook、重置 policy 或搬遷狀態。

`doctor` 中的 Claude／Gemini runtime integration 狀態仍沿用原契約；目前已支援的 Claude advertised model catalog 與 runtime Hook 採用是不同範圍。這個候選沒有新增跨 vendor routing adapter。

## Runtime 與授權來源

固定使用官方 Astral python-build-standalone release **20261009**、CPython **3.11.17**、`aarch64-apple-darwin-install_only.tar.gz`。官方 GitHub release metadata 提供的大小 **27,105,320 bytes**、SHA256 **7b6068989d9b6a0e2a883352b7d0d141ce8670a61360bf4ddabac0e046a08e10** 已核對。選 3.11 patch 以維持原 `>=3.11` 的最小相容變動；沒有複製本機 Homebrew／Framework Python。

同一 release 的 `pgo+lto-full.tar.zst` **41,284,022 bytes**、SHA256 **a9c2933a3846c44daa7168dc3ee31a6c6b254964451f113bbff1e87cfa8146af** 只作 licensing metadata／notices 來源，不執行 build scripts。Install-only 沒有 `PYTHON.json`；bundle 的 `notices/runtime/PYTHON.json` 是 full archive 原始 bytes，附 metadata hash，沒有假造或改寫其欄位。

保留官方提供的全部 **19 份** `python/licenses` 文字，另保留 runtime 原有 CPython、pip／setuptools 及 vendored packages notices。這些 Python 內附 packaging tools 不是 MRH 的外部安裝需求。原始 metadata 的 zlib 欄位列出 zlib／zlib-ng 兩種可能 notice，但這個 Darwin runtime 沒有私有 zlib-ng，metadata 的實際 link 為 system `z`，且 `otool` 證實 interpreter 連結 `/usr/lib/libz.1.dylib`；實跑 compile／runtime zlib 都是 **1.2.12**。缺少的 zlib-ng 文字被明列為「未重新散布的 metadata alternative」，沒有默默忽略缺檔或合成 notice。其他 missing notice 仍會使 build 失敗。

官方依據：[取得／執行 distributions](https://github.com/astral-sh/python-build-standalone/blob/20261009/docs/running.rst)、[archive layout／licensing metadata](https://github.com/astral-sh/python-build-standalone/blob/20261009/docs/distributions.rst) 與 [固定 release](https://github.com/astral-sh/python-build-standalone/releases/tag/20261009)。Exact asset／URL／hash／時間記錄在 [runtime lock](../packaging/macos-arm64/runtime-lock.json)。正常 MRH 使用不下載 runtime；只有 developer build 的明確 `--download` 能取得這兩份固定 HTTPS/hash-pinned 公開資產。

## 設計與驗證

入口是相對 shell launcher，執行 bundle 內的 `runtime/bin/python3.11 -I -B app/mrh.pyz`。應用 archive 包含原 28 個 MRH modules 和 package metadata，沒有 SDK、Node 或 build/downloader code；原 CLI／plugin 介面及 routing/core／Main／四級／Jev／D23／通知語意皆不變。Private `sys.executable` 能繼續支援原 `-I` 子程序，避免 frozen interpreter 的相容性問題。

Build 先檢查 fixed asset size/hash，再驗 tar 的名稱、型別、重複／大小／mode 與內部相對 links；regular files 先寫、links 最後建立，拒絕 traversal、absolute/escaping links、devices 及已有 destination。Artifact 不覆蓋既有輸出；cache 只接受此單元的 marker／固定資產，拒絕 foreign content、symlink marker、錯誤 bytes 或未核 origin。Binaries 留在 ignored build/dist，Git 只收 packager、lock、必要檢查、指南與證據。

[實際 standalone 驗證](evidence/e15-standalone.json) 從 archive 展開，使用新 owned HOME／cwd、沒有 Python／Node／uv aliases 的 PATH；再移至含空白的路徑，以同一入口跑 help／doctor，並透過 owned PATH symlink 跑短命令。記錄 `sys.executable`／prefix／stdlib／sys.path／MRH source origin 都在搬移後的 bundle，沒有 developer PYTHONPATH。CPython **3.11.17**、OpenSSL **3.5.9**、SQLite **3.53.1**；讀取系統 CA 的 context 取得 **128** 個 trust roots，沒有 provider TLS 請求。

實際 24×56 PTY 在 bundled entry 選 Claude，方向鍵／Enter 完成 `opus[1m]`／low 保存到 revision 1；再次修改後以方向鍵／Enter 取消，policy bytes 相同。另從同一 entry 取得 Codex metadata 後取消；這個純 metadata screen 使用 Escape，沒有選／保存模型。Claude **2.1.267** 的 4 個 advertised models、Codex **0.162.0-alpha.17.2** 的 8 個 advertised models 都沿原 fresh-root／無憑證／無 outbound catalog 機制取得；不是 account-confirmed availability，也沒有真模型執行。選完仍 enabled/export false、workspaces empty、Jev attempts 0。

從 bundled entry prepare plugin，artifact 的 Python path 精確為搬移後的私有 interpreter；實際執行 default-disabled launcher 得 `{}`，故意破壞自己 fixture 的 runtime 後得到有界 integrity `systemMessage`、exit 0、空 stderr。沒有 native host build、正式註冊／trust、真 key／provider 或其他專案寫入。

只跑新增 packager 的 validation/failure checks 及上述直接消費端；[檢查與清理](evidence/e15-verification.json) 記錄精確命令、結果、hash 與 owned root/groups。E13 selector/catalog 和 E14 125 checks／native warning／D23 的 MRH bytes 未改，因此沿用其語意證據，不重播整套。本單元不宣稱新 runtime 的所有 stdlib／平台 matrix 均已驗證。

## Developer 重建與 A 驗收

原始碼 build 本身仍需要 developer Python 3.11+、curl、macOS system tar/otool；使用已建好的 MRH 候選不需要另裝 Python。固定公開下載留在 MRH-owned ignored cache，以便再現；正常操作不會取得其他資產。

```sh
PYTHONDONTWRITEBYTECODE=1 python3.11 scripts/build_standalone.py --cache build/e15-public-assets --output dist/model-routing-harness-0.3.0-macos-arm64 --archive dist/model-routing-harness-0.3.0-macos-arm64.tar.gz --download
PYTHONDONTWRITEBYTECODE=1 python3.11 scripts/verify_standalone.py --archive dist/model-routing-harness-0.3.0-macos-arm64.tar.gz --output /absolute/owned/e15-check.json
```

重建需選新、尚不存在的 output/archive；不刪除或覆蓋現有 candidate。A 可核 archive／manifest hash，親自使用保留的 `dist` entry，在自己 fresh HOME／profile 操作，接受後按原授權續作；發現問題直接交 B。未發布、未 signing/notarization、未繞過 Gatekeeper；保留 R1、R2／Gemini 原義務及低於 7% 才保存暫停規則。新的可信 Monitor context 仍沒有可 resume 的原 task/native user item，已選 none，沒有造新 request/task/Goal 或改寫舊進度。
