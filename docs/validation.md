# 驗證摘要

本頁整理 0.4.0 的已完成驗證及其限制，不包含個人路徑、聊天識別碼或原始宿主輸出。這些結果是指定版本與情境的觀測，不是持續運行的 CI 狀態或對所有安裝環境的保證。

## 已驗證範圍

| 項目 | 結果與範圍 |
| --- | --- |
| 核心與控制中心 | 分級政策、明示選型保護、設定保存／取消、統計與 JSON 契約有相應離線測試。 |
| macOS arm64 安裝 | 私有 Python、安裝檢查、更新／回退、原設定保全與宿主接頭有隔離及本機消費者證據。 |
| Codex 原生流程 | 限定 Pre/Post 故障通知後繼續工作、同 Goal 自動後續委派及 Fixed 父子結果已驗證；這組路由補驗使用合成分級。 |
| Codex Desktop | 既有桌面版本十個有效試次有八次採用建議，兩次低信心保留原路徑，全部完成。這不是新版 UI 的全面回歸。 |
| Claude Code | 真派工、Main、明示模型／內建角色保護、Jev 401 後繼續與限定 Pre/Post 故障通知已有驗證；實際 child effort 未獨立回報。 |
| 背景摘要與 metadata | 專案內介面與合成範例已驗證；沒有安裝外部記憶 producer 或 Monitor UI／資料庫整合。 |

宿主、安裝平台與版本限制見 [相容性](compatibility.md)。測試 fixture 經去識別化，用於驗證資料形狀與處理規則，不能作為新的真實執行證據。

## 2026-10-24 雙模式與 packets 正式採用（程式 `670272f`）

Mac 與 Windows 的既有個人安裝均已完成 `--dev --codex-packets` 更新及讀回。兩宿主的 CLI／Hook、manifest、PEP 660 descriptor／純路徑 PTH、開發來源與獨立 `runtime_root` 綁定一致；Codex 信任與 packets 保留，沒有待恢復交易。設定、外部白名單、非 MRH 宿主設定語意、PATH、憑證存在狀態與舊安裝歷史保留；SQLite schema 及全部原資料列與重數完整保存。這是既有資料保全，不宣稱資料庫 bytes 或總列數完全相同。本次未重跑 provider、真實委派或既有通過測試。

Windows 另有一次未插樁、完整合法普通事件的開發 Hook 標記精確成功（0.438 秒）；開發來源移走後 CLI exit 2 並明確回報來源不可用，切到一般模式且來源仍移走時 help exit 0。原 bootstrap／Job／2.5 秒期限未變。正式採用使用符合來源安全檢查的既有 checkout；共用可寫副本不是開發來源，其修改不會自動同步。

歷史分批 77 個唯一 ID 保留為 75 PASS、1 FAIL、1 預期 SKIP，並非同一輪套件全過。原不完整事件案例的 FAIL 原因未定；插樁觀測成功及五次失敗限定捕捉未重現都只作診斷，不增加原生 PASS，也不證明 fixture 錯誤、產品存在已確認缺陷或已修好。正常使用的合法事件、模式尾段及實際正式採用依各自直接證據驗收；完整限制見 [Windows 驗證紀錄](windows-validation.md)。

一般安裝預設打包版本；開發模式、獨立 runtime、來源安全與切換復原見[開發指南](development.md#本機開發安裝--dev)。後續純文件 commit 不改程式指紋；文件 HEAD 與已安裝程式 `670272f` 以相同程式／產物 bytes 對應，無須為顯示 HEAD 不同重新安裝或測試。

## 2026-10-23 Mac 本輪收尾（6b0ebd8）

本輪已採用 `6b0ebd8`，五模組 81 PASS，discover 458 PASS／112 SKIP／0 FAIL／ERROR；兩宿主原生一般委派、明示選型保護、Codex 保留封包及 Claude 隔離清單通過。Mac 時限不變，Codex Hook 定義與信任前後相同。Codex 明示模型案例本輪已有獨立 child 終結證據；disabled 依原交接例外維持 SKIP。所有原 MRH 資料保留，Claude 非 MRH Hook 有來源未知差異，不宣稱整份設定完全相同。

指定 POSIX 原次自然壓測完成：4 個 Hook worker＋1 個 SQLite writer，36 個 Hook／1,090 次 SQLite 開關中有 1 次 settings unavailable，首次觀測後停止。原次沒有內層例外堆疊；後續隔離診斷直接確認暫存檔消失會呈現 `FileNotFoundError` 或 POSIX `st_nlink == 0`，兩者都曾被誤判成設定不可信。這些新診斷不是原次的事後堆疊，也不代表日常故障率。原交接分項結果見 [本輪 Mac 驗收結果](mac-handoff.md#本輪-mac-驗收結果6b0ebd8)。

### 同日 POSIX 最小修正收尾

只修改 `owned.verify`：四個已允許的 SQLite `-wal`／`-shm` 檔案消失時可略過；POSIX 若仍讀得到 metadata，也只容忍 regular、owner 正確且連結數為 0 的同名暫存檔。主檔、陌生檔案、不安全連結、錯誤 owner 及其他錯誤仍拒絕，Windows ACL 檢查不變。

| 必要條件 | 最終結果 |
| --- | --- |
| 受影響回歸 | `tests.infrastructure.test_owned_sidecars` 共 6 項，新增連結數 0 的四種正向子案例修前失敗、修後全過；其他檔案與安全負向保護通過。 |
| 實際套用 | Claude 與 Codex 已採用安裝代 `1e33d5b63efdd39756afe1ea`；兩份 runtime、應用程式 archive 及 Codex 原生快取中的修正與工作目錄一致。 |
| 原工作量自然驗收 | 未加 trace 或函式包裝，4 個 worker＋1 個 SQLite writer，3.365 秒完成 44 個 Hook／1,090 次 SQLite 開關，44 個 `{}`、0 故障／逾時；每個 worker 完成 5 組 Pre／Post，達標即停。 |
| 保全與清理 | 原 MRH 設定、7 張表的原資料列、金鑰存在狀態、Hook 信任與時限保留；自有 fixture 與程序已清理，原證據及備份保留。 |

本次沒有真實 provider 呼叫或子代理；不受影響的五模組、完整 discover、原生委派與清單驗證沿用，沒有重跑或改算成本次結果。修正接續 `6b0ebd8`；該提交本身不包含修正，實際安裝以以下證據記錄的來源雜湊為準。此問題的修正、必要驗證、本機套用與文件已完成，沒有新增待辦；既有平台與原生驗證界線維持。細節見[修正與收尾結果](mac-handoff.md#posix-最小修正與收尾結果)。

## 2026-10-23 Mac 前輪驗收（ddc4e4157）

Windows 程式碼 `9d50280` 加上交接文件的 `ddc4e4157`，已在 macOS arm64 更新安裝並完成限定驗收。這組結果取代「Windows 修復後尚無 Mac 重驗」的舊狀態，較早失敗與各批證據仍保留。詳見 [Mac 驗收紀錄](mac-handoff.md)。

| 項目 | 結果與限制 |
| --- | --- |
| 指定五模組 | hook_budget 12、hook_supervisor 7、context_contract 9、advisory_runtime 10、setup 43，共 **81 PASS、0 FAIL／ERROR／SKIP**，46.271 秒。 |
| 完整 discover | 568 run = **458 PASS、110 SKIP、0 FAIL／ERROR**，91.487 秒；SKIP 不計 PASS。沒有失敗案例，未另跑舊版本來補基準數字。 |
| Mac Hook 時限與 launcher | LOCAL_SECONDS／POST_SECONDS 仍為 1.0；POSIX launcher 與 `6d10f9f` 及兩宿主安裝產物逐位元組相同。 |
| 正式安裝 | 新安裝代來源為 `ddc4e4157`；兩宿主 configured、Codex trusted、pending 為空，金鑰仍存在。保留既有 packets 選配。 |
| Codex 0.163.0 一般委派 | 真 Jev Light/0.77 → 建議 `gpt-6-luna/high` → 一次重發 → 官方 child completed/OK；實際模型與強度另由 child metadata 核對，Post followed=1，Post resolved_model 本身仍為 null。 |
| Codex 保護與停用 | explicit_model 保留且不呼叫 Jev；該 child 終結僅 parent 回報，未取得獨立 child 身分。reserved packet 被原生拒絕。disabled 原生依既有已啟用 Mac 例外列 **SKIP**，不以離線測試冒充原生 `{}`。 |
| Claude Code 2.1.309 一般與明示委派 | 真 Jev Light/0.87 → haiku/medium → 一次重發 → child completed/OK；Post resolved `claude-haiku-5-5`、followed=1。明示 haiku 保留且無 Jev，另一 child 同樣 completed/OK。requested effort 與獨立實際 effort 仍分開。 |
| Claude 停用 | 獨立臨時 profile、單次宿主設定；真實原生 Pre／Post 均回 `{}`、exit 0，child completed/OK，沒有建立臨時 MRH 統計 DB。 |
| Claude 清單 | 初期 2.1.296 的實際命令取得 5 模型；最終 2.1.309 政策查詢來源仍為 isolated-defaults。安裝版 catalog 與來源一致，Mac 路徑使用 `sandbox-exec`；沒有無隔離 fallback，未宣稱外部 syscall tracing。 |

本包 Jev 真實 transport 共 **3 次**：Codex 2 次（包含初次低信心保留的請求）、Claude 1 次。12 筆 lifecycle 狀態不是 12 次請求。初次 Codex 一般委派因 runner 的 ephemeral parent 缺 rollout 而失敗；保留該結果，只修 runner 並補原失敗案例一次，沒有重跑已通過的明示模型或 packet 情境。沒有觀測到 MRH Hook 逾時或重複成功委派，四個自有 CLI 程序群組均已退出。

MRH 設定、Claude 設定、適用範圍、原統計資料列與金鑰保留。整份 Codex `config.toml` 不能稱完全相同：除預期的新 marketplace 來源，另觀測非 MRH `service_tier` 從 `default` 變成 `priority`，寫入者與確切改動時間未知；保留目前值，不歸因或回寫。這項差異不是已證明的分級故障，也不自動增加工程待辦。原始證據、備份與官方 session 保留，自有臨時材料已清理。

Mac 本包已由督導接受，以上 SKIP 與證據邊界一併保留；不代表 Windows 後續事項或所有平台已完成驗證。後續 Windows 的 Codex Post 5 秒與 Small／Mid 並行已完成驗證；目前已解決事項、POSIX 競態評估與保留限制見 [Mac 交接第 5 節](mac-handoff.md#5-未決項目與已解決項目)。本節 ddc4e4157 證據不代替新版 6b0ebd8 的驗收結果。

## 安裝與移除的補充驗證

- **Mac 安裝與 shell**：在隔離的 HOME 內用真的 zsh／bash 登入與互動 shell 驗證：PATH 衝突與保留原檔、同一安裝代的 PATH 修復、skill 位置與覆寫前的復原副本、原子更新的成功與失敗清理，共 9 項直接案例。安裝器判斷「新 shell 是否就緒」時檢查持久的啟動檔，不以目前程序繼承到的 PATH 為準；這一點有 4 項直接案例。
- **Mac 移除（`./setup --uninstall`）**：離線單元測試涵蓋預覽不寫入、保留其他 Hook 與設定、被改過的 shell 區塊不動、可重跑、原生註冊失敗後續跑、`--purge-data`，以及不跟隨符號連結。另在隔離 HOME 用真實安裝產生的安裝代做過一次完整往返：Claude Code 的 `settings.json` 與 `.zshrc` 在移除後與安裝前逐位元組相同。Codex 部分只用假的 CLI fixture 驗證，沒有對真實的 Codex 執行；鑰匙圈操作在測試中以替身取代。
- **Windows**：`0007b77` 的六個 Windows 模組共 68 個案例，首次 51 項通過、17 項因 runner 未隔離真實模型清單查詢而失敗；補上清單不可用的替身後，只重測原 17 項，全部通過，0 錯誤、0 略過。產品程式與測試斷言未更動，原次 51 項結果沿用。另有較早的 5 項選定案例，其中 4 項通過、1 項因無法建立 symlink 而略過；該略過案例仍不能算通過。來源、案例與限制見 [Windows 驗證紀錄](windows-validation.md)。Windows 沒有 `--uninstall`，手動移除步驟未經實機驗證。

本節安裝／移除的隔離案例沒有呼叫 Jev 或子代理；它們不能代替上節的真實派工證據，也不代表所有真帳號環境。

Windows 測試的清單隔離後續已納入正式測試檔；原 17 項安裝案例及加強後的來源指紋案例另經原生 Windows 差異驗證，18 項全部通過，0 失敗／錯誤／略過。此次不涵蓋同期新增的分析資料與 `mrh status` 功能。

## 名稱與完整描述比較

使用十個固定模擬劇本，比較只提供名稱與提供完整任務描述的 Jev 分級。兩組維持相同四級規則與 0.65 信心門檻，名稱在前、全文在後，實際回應版本均為 `jev-1.13.0`。

合計 21 次請求：20 份成功解析、1 份原格式失敗。首次完成九組有效配對；一次恢復取得第五組名稱結果後，共有十組有效配對。原格式失敗仍計入請求數，沒有透過正規化機率或修改 parser 隱藏失敗。

| 固定案例群組／輸入 | 有效配對 | 高信心相符 | 低估 | 高估 | 低信心回退 |
| --- | --- | --- | --- | --- | --- |
| 1–8 名稱 | 8 | 1 | 0 | 0 | 7 |
| 1–8 全文 | 8 | 5 | 1 | 0 | 2 |
| 同名 9–10 名稱 | 2 | 0 | 1 | 1 | 0 |
| 同名 9–10 全文 | 2 | 2 | 0 | 0 | 0 |
| 全體名稱 | 10 | 1 | 1 | 1 | 7 |
| 全體全文 | 10 | 7 | 1 | 0 | 2 |

同名的「修登入問題」包含簡單文字修正及跨系統撤銷設計，名稱本身未表達這個差別；完整描述在這兩例符合事前參考。全文仍有低估及低信心回退，沒有保證必然較好。

參考標記是事前建立的主觀、非盲標記。這是固定文字比較，不是自然工作分布、實際子代理品質或普遍準確率的評估；也不能證明 packet 自然採用、宿主加密訊息與另存 brief 獨立相等，或實際帳單節省。

## 如何驗證修改

原始碼的直接測試入口與安全邊界見 [開發指南](development.md)。修改文件不需要呼叫分級器；修改功能時，選擇直接受影響的測試。涉及真宿主註冊、任務外送或付費請求的驗證需要另行確認其作用範圍。
