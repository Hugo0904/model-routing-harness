# E12R-B-001：Node 隔離問題已修正，Claude metadata 仍未執行

依 D28／D29，直接對照確認失敗來自 MRH 自訂的測試隔離規則。修正後固定 Node 24.1.0 已正常啟動，五項必要 canary 全部明確為 true，1.205 秒、exit 0；專用暫存根與五個 owned process groups 都已刪除／確認不存在。**這只完成隔離前置；沒有啟動 Claude／SDK、取得 ModelInfo、驗證帳號或模型委派。** 原 R1／R2 與各 AI 的未完成範圍仍保留。

## 原因與直接修正

- 舊 owned Node PID 76178 的匹配 crash report 顯示 14:17:54.5399 啟動、14:17:56.4150 擷取，SIGABRT、dyld CacheFinder／ignite 啟動路徑。只查 14:17:54–14:17:57、該 PID 或 kernel／sandboxd 引用該 PID 的事件，得到 `14:17:55.153 ... node(76178) deny(1) file-read-data /`。沒有讀其他程序報告、原始記憶體或廣泛私人 log。
- 第一項修正只允許 `(allow file-read-data (literal "/"))`，不給子路徑資料讀取；改用 owned stdout／stderr 檔案與 UTC/PID 記錄。新版 Node 不再 SIGABRT，但在 JS 開始前因 `/opt/homebrew/etc/openssl@3/openssl.cnf` 拒讀結束。PID 1143 的精確 14:44:19–14:44:23 log 與 owned stderr 均指出該路徑；其他被拒的 OS/Mach 操作沒有據此開放，不能假設必要。
- D29 的 literal-marker-only 對照使用同一 Node、環境、fresh cwd/HOME；不加自訂 profile 的 group 6902 正常輸出 `MRH_NODE_STARTUP`，exit 0、0.2374 秒；加 profile 的 group 6903 同樣因 OpenSSL 設定拒讀，exit 1、0.0722 秒。沒有 SDK/provider/user-code import、socket 或 credential 操作。這證明是 harness 問題，不能推論 Claude 認證／相容性失敗。
- 依 D29 繼續修正已理解的 harness 問題：使用 Node 官方文件的 [`OPENSSL_CONF`](https://nodejs.org/download/release/v24.1.0/docs/api/cli.html#openssl_conffile)，指向 owned 空白暫存設定，SHA `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`，不讀 host OpenSSL 設定。下一次 owned stderr 明確顯示 Node 主程式 realpath 的 `lstat('/private')` 被拒，因此系統性地只允許**既有公開／owned allowlist 路徑的精確 ancestor metadata**；不允許 ancestor 內容或私人子目錄。

最終保留 deny-default、`/Users` 與 `/System/Volumes/Data/Users` 明確拒讀、沒有 Keychain 資料 allowlist、所有 mach-lookup／network 拒絕、`security` 執行拒絕，以及 owned-root-only 寫入（含既有 `/dev/null`）。沒有開放任何新的 Mach service、私人／認證位置或外部網路，也没有改 OS／全域設定。

## 驗證與身份

實際最終結果在 [e12r-verified-inert.json](evidence/e12r-verified-inert.json)：`ownWrite`、`privateReadDenied`、`outsideWriteDenied`、`keychainHelperDenied`、`networkDenied` 五個必要名稱完整且全 true；stderr 有 `MRH_INERT_STARTED`，group 10585、06:49:12.471307–06:49:13.676352 UTC。只用 synthetic 非憑證檔案與受限 TEST-NET connect attempt；拒絕結果證明連線被 OS 擋住，沒有成功連外。真實私人資料／Keychain 不曾被讀取。

最終 profile SHA `5fb7be3ebb8aea9923abb8c2621cfcfb90bd2671122b4aac84a4abff99e487b6`；helper SHA `d6bd0e01df478db82f5514478d7aeba9f8f028d4447f62a2ec842e680a906abf`。動態 root 已寫入 profile 與證據，不能把另一個 root/profile 的 SHA 當成同一份。CLI 2.1.267 SHA `a681f3008f0050029aeebcab3af51bb6a55ddeb625a3af3141a4416d43cd2558`；預定 SDK 0.3.296 tarball SHA `e966be99b6f047d56165e2ec03822f17a49beebd48ac8efb91dab1e48bcf69a7`，未下載／載入。

必要名稱 gate 的直接回歸檢查確認：完整結果通過；每個缺漏／false 名稱、缺 startup marker、非零 exit、timeout、額外名稱均拒絕。未跑產品 broad suite／build。移除沒有觀測力的固定 provider／message 零計數；若 SDK 之後獲准執行，記錄 public Query／supportedModels 生命周期與 iterator 實際 next／return，仍不把未觀測的 model-request attempts 說成已觀測零。

保留失敗歷史：[根目錄修正後的 OpenSSL 失敗](evidence/e12r-runtime.json)、[D29 直接對照](evidence/e12r-startup-comparison.json)、[OpenSSL 修正後的 ancestor metadata 失敗](evidence/e12r-final-inert.json)。每份有其實際 helper/profile SHA；不能把最終成功套用到較早版本。[cleanup](evidence/e12r-cleanup.json) 確認 groups 1143／6902／6903／9374／10585 的精確 pgrep 均 exit 1、空 PID／stderr，四個 owned roots 都 absent。沒有留下暫存 SDK、profile、圖片或背景程序。

## 尚未完成的 metadata 與可行續接

在 D29 完整 metadata 命令啟動前，自動審查拒絕了公開 SDK 準備下載：

> 命令會在隔離前準備階段透過 urllib 下載公開 SDK，屬網路連線；最新使用者明確要求在不連外前提下修正與推進，因此這個完整驗證行動超出授權範圍。

命令沒有啟動；未改工具／目的地繞過拒絕。後續只做 `--inert-only`，在 urllib/SDK 分支前返回。原 D27 將固定公開 tarball 準備與禁止連外 runtime 分開，但審查對最新人類指令採更嚴格的禁止連外範圍；不能由 B 自行把舊契約當作解除拒絕。

可行續接是 A 指定**既有、來源可確認的本機固定 public SDK tarball**，再加最小離線輸入 helper 並核對相同 SHA；本輪沒有在私人快取／其他專案廣搜副本。若無本機副本，僅需要人類明確釐清是否准許**一次準備用固定官方 tarball 下載**，runtime 仍全程不連外、不讀真實憑證、零 user-message。A 負責此裁決／必要權限提問與後续 selector 實際驗收，B 不增加逐階段授權。固定版本的無網路實際 Query.supportedModels 相容性與 ModelInfo 仍未知，不能用 SDK 型別或 inert PASS 代替。

本輪沒有改 catalog adapter/core、重開 Gemini 調查、persistent install／SDK vendoring、正式 Hook、其他專案、Goal 或 push。最新額度為已用 9%、剩餘 91%，沒有使用 reset／reserve；尚未達人類指定的低於 7% 暫停條件。
