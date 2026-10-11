# E13-B-001：Claude CLI 模型選單已接通，無 SDK／Node 使用前提

已在 macOS 原生 **Claude Code 2.1.267** 實際取得模型清單，並接進 MRH 的 AI／模型／推理強度／保存流程。MRH runtime 只使用 Python 標準函式庫與選定的 Claude CLI；沒有 SDK import、下載、橋接程序或新增 Node 執行前提。這是本機開發候選的清單／設定支援，**不是帳號可用性、Claude 子代理委派或完整 R1／R2／R3 發布驗收**。一般使用者的最終 MRH 發行包仍須自行管理內部 runtime；目前 source／wheel／venv 不能替代這項 R3 義務。

本機 feature commit：`ce8c7293f11666214fcf55685a5b335a2ceed7ac`；含 terminal text 格式修正的 source tip：`a8d3ade3507bc0c787e3782ccfd5694968317b14`；27 個 runtime module 與 installed wheel 完全一致，見 [source identity](evidence/e13-source-identity.json)。無 push。

## 最小來源契約

實際公開 `--help` 沒有模型清單子指令，因此依 D30 使用公開 `-p --input-format stream-json --output-format stream-json` 入口的**版本限定相容接頭**。唯一傳入 frame 是 `control_request`／`initialize`；對應的成功 `control_response.response.response.models` 與官方 SDK 0.3.296 的初始化實作、型別和 `supportedModels()` 讀取位置一致。這不是宣稱穩定、正式文件化的 model-list API；未知 CLI 版本／不相容回覆會明確拒絕。

SDK 僅在專用開發暫存目錄下載、核對 tarball／source／types SHA 並閱讀初始化契約，沒有 install/lifecycle、Query 執行或原始碼 vendoring，已清理。新的直接人類授權已允許這次準備；E12R 的下載拒絕是歷史。Python urllib 的本機 CA issuer 問題改用正常驗 TLS、禁讀 curlrc 的原生 curl；沒有關閉驗證。固定 tarball SHA `e966be99b6f047d56165e2ec03822f17a49beebd48ac8efb91dab1e48bcf69a7`，source SHA `5cf6f15237f9c84e6e5b724a10180478732457168921d7aa3e02632037cce299`，types SHA `fc2866dfe2c01468edb19b1d94f26156bfacecdf1e7f1452b276ed2f8cc0b08f`，見 [開發來源與清理](evidence/e13-sdk-source.json)。

CLI SHA `a681f3008f0050029aeebcab3af51bb6a55ddeb625a3af3141a4416d43cd2558`。實際 CLI-only 回覆 0.2128 秒、EOF 收束 exit 0，沒有 SDK／Node 執行；[原始 models 與唯一輸入](evidence/e13-cli-probe.json) 保留觀測。實際 MRH backend 0.8293 秒完成 version／fresh initialize，觀測 stdin 只有 initialize，見 [來源 backend 與精確 profile](evidence/e13-source-catalog.json)。初始化中的 account／commands 等欄位不保存／使用，沒有 accountInfo 或 auth RPC。

| CLI 實際 request value | CLI 回報 resolved model | 實際 effort 選項 |
| --- | --- | --- |
| `default` | `claude-opus-5[1m]` | low／medium／high／xhigh／max |
| `opus[1m]` | `claude-opus-5[1m]` | low／medium／high／xhigh／max |
| `sonnet` | `claude-sonnet-5` | low／medium／high／xhigh／max |
| `haiku` | `claude-haiku-4-5-20251001` | 未提供；只可 inherit |

保存的是 request value，resolved model 僅是額外來源資訊，不冒充帳號／執行確認。清單依 executable SHA／實際工具版本分域、標為 tool-advertised，每次 refresh 建立新的 lifecycle，保存前重新取得清單。Codex 仍使用原 public app-server model/list；Gemini 仍明示尚未支援。Core／Jev 不知道 SDK 或此初始化 transport，沒有增加 Claude 委派接頭。

## 隔離與必要修正

沿用已接受 E12R 的相同 profile 規則（有程式比較），fresh cwd/HOME/config/cache/tmp、allowlisted 無憑證環境；`--bare`／禁用工具、skills、MCP、hooks、session persistence；deny-default、私人 Users/Data alias、Keychain service IPC、security helper、所有 network 與外部寫入限制保留。沒有 provider/model/task/user frame，也沒有真私人資料／憑證讀取。外部套件準備與禁止連外的 runtime 分開。

Claude 在 macOS 的內部暫存預設是 `/tmp/claude-{uid}`，一般 TMPDIR 不足以改變它。依[官方環境變數文件](https://code.claude.com/docs/en/env-vars)及已安裝程式來源，以 `CLAUDE_CODE_TMPDIR` 指向 owned tmp，並使用 owned settings／MCP 檔案，不允許共享 `/tmp/claude-501` 寫入。早期拒寫紀錄保存為 [settings failure](evidence/e13-cli-settings-failure.json)、[internal temp failure](evidence/e13-cli-temp-failure.json)。最早 inline prototype 在 group signal 清理遇 EPERM，未取得可用 metadata／PID 證據，不用它證明成功或清理；後續 helper 採 EOF→wait、明確記錄 PID 與完整結果。沒有以放寬私人／網路規則修復。

另外，CLI 合法 request value 有 `[1m]`。新增只用於**模型欄位**的 balanced-context ID 驗證，涵蓋 Catalog、設定／費率、model facts／decision／receipt；聊天／proposal／來源／effort 身分仍使用原 safe_id，不能包含方括號或秘密前綴。新增實際 ID 語法的 stop／immutable-history 合成回歸，既有 D23 deny／更新指引／同呼叫鎖住規則不變。

## 已完成的最小驗證

- Luna worker 只負責 `tests/test_claude_catalog.py`。解析／dispatch／版本／selection 加 transport 的錯誤 JSON、duplicate key、超大回覆、無關 request ID、EOF、timeout、非預期 user/task frame 與 owned-child 收束。它找出 CatalogError 被 ValueError catch 覆蓋的真缺陷；修正後 16 個新檢查及 10 個 stop 檢查全通過，0.386 秒。
- 受影響 selector／設定／core／facts／store／accounting 的首次 89 檢查：87 通過，2 失敗。兩者在改動前 `3f57792`、隔離 source snapshot 的相同個別檢查也失敗：migration 測試期待 schema 2，而既有 D23 已是 3；accounting 測試期待預設畫面含完整 details，而既有 CLI 預設改為概要。沒有改測試讓它假通過，也沒有擴成全套。這兩個舊驗證缺口仍需 A 裁決，見 [基準對照](evidence/e13-baseline-failures.json)；第一次窄 archive 缺 test_typesafe／e5 fixture 的 checker 失敗也保留，不算產品失敗。
- 一次隔離離線 wheel 安裝與 installed-entry smoke，包含新模組、全部 runtime bytes 與 source SHA 比對、無 Requires-Dist／SDK／JS 檔、沒有 PYTHONPATH、source 外 cwd、無全域安裝。實際 24×56 PTY 用方向鍵／Enter 選 Claude→`opus[1m]`→low，Save→Effort→Model Back 保留草稿後保存；另一場改草稿後取消，設定及既有 MRH SQLite/key/lock 檔 bytes 相等；Haiku 保存只含 model、不捏造 effort。最後明標 synthetic 的 save-time refresh 失敗只顯示舊清單、拒絕保存，再取消，設定 bytes 相等。首次有效流程 6.491 秒；checker 的 history 檔名審查修正為實際 MRH 事件檔後重驗 6.3558 秒，輸出文字只去除 ANSI／控制分隔與列尾 padding，不宣稱截圖；格式審查修正不影響 runtime bytes 或操作結果。後者為正式 [package／readback](evidence/e13-package.json)。沒有為此重做產品畫面或既有 terminal-emulator matrix。
- 保存 Light=`opus[1m]`／low、Small=`haiku`／inherit，revision 2；enabled／export 均 false、workspaces 空，proposals／Jev attempts 均 0。原未變動的 Codex來源／宿主／包版與停止出口證據在其範圍內重用，不把這次 metadata 宣稱成正式採用。
- [cleanup](evidence/e13-cleanup.json) 確認七個**已記錄** owned groups 的精確 pgrep 都 exit 1、空 PID／stderr；記錄的 help／probe／backend／SDK／installed roots 都 absent。Package helper 每個 PTY wait/reap，backend 每個初始化 EOF/wait 並檢查 process group；沒有保留暫存 packages／圖片。最新額度已用 14%、剩 86%，未達低於 7% 暫停門檻，未使用 reset／reserve。

## A 親自操作的安全入口

在本專案以 fresh acceptance root 執行開發候選（不動既有 profile）：

```sh
mrh_acceptance_dir=$(mktemp -d /private/tmp/mrh-a-e13.XXXXXX)
PYTHONPATH=/Users/shawn/Code/model-routing-harness/src python3.11 -m mrh model light --root "$mrh_acceptance_dir/bindings" --width 56 --plain
```

選 Claude／確認 profile／模型／effort／Save 都只用方向鍵和 Enter。可選第二筆 `opus[1m]`／low，再測 Left 的兩步返回、重新選擇和 Cancel；`small` 的第四筆 Haiku 應只有 inherit。讀回該 root 的 registry／settings 與 revision／gates；結束後由 A 清理自己的 root。需要自動重現同一安裝＋PTY證據可執行 `python3.11 scripts/verify_claude_package.py`，它只在 owned temp 建立 Python venv、無 SDK、無全域效果，自行清理；其中失敗場景是明示合成，真實 retirement／account availability 仍未確認。

此入口不是最終使用者安裝指示。R3 MRH 自有 runtime 發行包、其他 OS／Claude 版本、Gemini 可靠來源與 effort／binding 契約、Claude 真實委派／同呼叫保護、完整 R1/R2／正式採用仍保留。沒有開新聊天／Goal、push、正式 Hook、其他專案變更或帳號登入。Monitor context 仍無可接續 task／可用原 native request，host-check ready、選 none，未製造身分或手寫舊 Canopy task logs。A 保留原任務驗收與下一個實作裁決。
