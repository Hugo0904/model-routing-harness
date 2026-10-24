<a id="mac-驗收交接windows-修復後的收尾"></a>

# Mac 歷史驗收與已知限制

本頁保存 2026-10-23 的 Mac 驗收與 POSIX 修正證據；這些工作已完成並接受，歷史步驟不再是待執行清單。安裝與測試入口見[安裝教學](install.md)及[開發指南](development.md)，後續採用見[驗證摘要](validation.md)，Windows 修復原由見[Windows 紀錄](windows-validation.md)。文件與原始測試結果都不產生新授權，也不要求為閱讀文件重跑驗證。

<a id="1-起點"></a>
<a id="2-windows-做了什麼已實測"></a>
<a id="3-提交清單與對-mac-的影響"></a>
<a id="4-mac-必做驗收"></a>
<a id="41-程式碼層"></a>
<a id="42-安裝"></a>
<a id="43-原生-hook-smokeclaude-與-codex-各做一次"></a>
<a id="44-claude-清單sandbox-exec"></a>
<a id="6-邊界"></a>
<a id="7-回報格式"></a>

## 本輪 Mac 驗收結果（6b0ebd8）

來源 `6b0ebd873957dd49b5a7c8315f4130a6e706f82d` 包含 Windows 修正 `0aac0c0`。本節與前輪 `ddc4e4157` 的結果分開；下表原次壓測尚未包含後續 POSIX 修正。

| 項目 | 結果與限制 |
| --- | --- |
| 指定五模組 | hook_budget 12、hook_supervisor 7、context_contract 9、advisory_runtime 10、setup 43，共 **81 PASS、0 FAIL／ERROR／SKIP**，56.793 秒。 |
| 完整 discover | 570 run＝**458 PASS、112 SKIP、0 FAIL／ERROR**，134.558 秒。各執行一次，沒有重跑舊版補基準。 |
| Mac 時限與信任 | Local／Post 1.0／1.0 秒，Codex Post 宿主 2 秒。`212b002` 前後同參數生成的 hooks.json、正式 Codex Hook 定義／雜湊／trusted 狀態相同，未要求重新信任；POSIX launcher 與 `6d10f9f` 及安裝產物相同。 |
| 更新與保全 | 安裝代 `4932cccf01e71f11244084ad`；兩宿主 configured、pending 空、金鑰存在。MRH 設定、適用範圍及全部原統計列保留，新增事件分列。Codex 非 MRH 設定語意未變；Claude 其他 Hook 有來源未知差異，只有 MRH entries 可稱相同，未回寫現值。 |
| Codex 0.163.0 | 真 Jev Light/0.84 → gpt-6-luna/high → 一次重發 → 獨立官方 child completed/OK、Post followed=1。明示 Sol 保留且無 Jev，另有獨立 child 終結證據；未指定 effort，實際為 low，不能稱繼承父層 xhigh。保留封包原生拒絕。disabled 原生仍為 **SKIP**。Post resolved_model 空值與獨立 metadata 證據分開。 |
| Claude Code 2.1.309 | 真 Jev Light/0.87 → haiku/medium → child completed/OK、Post followed=1；明示 haiku 保留且無 Jev，child completed。實際 child effort 未獨立回報。獨立 disabled profile 的原生 Pre／Post 均為 `{}`、exit 0，child completed，未建立 MRH DB。 |
| Claude 清單 | 2.1.309 實際取得 5 模型，complete、isolated-defaults；catalog 與來源雜湊一致，使用 `sandbox-exec`，無無隔離 fallback，未宣稱 syscall tracing。 |

原生樣本共 3 個 parent、5 個有獨立完成證據的 child；Jev transport **2 次**，8 筆 lifecycle 不是 8 次請求。未觀測到 Hook 逾時或重複子代理，未查費率。三個自有 fixture 根共 53 檔已清理，精確自有程序群組及 fixture 引用程序無殘留；原資料與官方 session 保留。

Codex disabled 的 SKIP 沿用當時已啟用 Mac 的例外：獨立根缺可用原生認證／信任，沒有已驗證的單次 profile 入口；未複製 OAuth、繞過信任或改正式開關。離線 `{}` 不代替這項原生證據。

原次 POSIX 壓測使用未改 launcher/runtime、獨立設定與 SQLite，4 個 Hook worker＋1 個 writer；4.172 秒完成 **36 個 Hook（20 Pre／16 Post）與 1,090 次 SQLite 開關**。35 個回 `{}`，1 個 Pre 回報 settings unavailable、缺一筆 Pre 記錄，首次故障後停止；沒有 provider 或額外受控刪檔。原 supervisor 未暴露內層堆疊，不能把訊息當成已捕捉 FileNotFoundError，也不能推算日常故障率。

### POSIX 後續根因診斷

| 階段 | 直接證據及界線 |
| --- | --- |
| 原始 runtime 的隔離例外觀測 | 0.773 秒、8 個 Hook／187 次 SQLite 開關，捕捉 Post 的完整鏈：`owned.verify` 對 `advice.sqlite3-wal` 的 `lstat` 收到 FileNotFoundError（errno 2）→ `settings_v2._location` 包成 settings_unowned → runtime 顯示 settings_unavailable。原工具繼續，但合成 advice／child receipt 為 4／3；沒有設定內容損壞證據。 |
| 第一版只容忍 FileNotFoundError | 回歸通過並套用 Mac，原自然驗收仍出現一次 settings_unavailable，未接受為完整修復。全域觀測確認 28 次檔案不存在已放行，卻未捕捉目標故障，且影響時間，不能代替自然驗收。 |
| 只在設定讀取例外時觀測 | `lstat` 成功讀到側檔的 regular-file metadata、owner 正確，但 `st_nlink == 0`，被判為 unsafe_owned_file，再變成 settings_unavailable。這是另一種已消失狀態。 |

上述沒有手動刪側檔、provider 或真實子代理；正式設定、資料、程式與安裝未由診斷變更。它們證明隔離 runtime 的機制，不是原 launcher 全鏈的未改重現，也不是原次 Pre 的事後堆疊；原次精確內因未記錄。觀測會影響排程，不能拿小樣本估正式故障率。

### POSIX 最小修正與收尾結果

產品只修改 `owned.verify`：精確四種、原已允許的 SQLite `-wal`／`-shm` 側檔消失時可略過；若 POSIX 尚讀得到 metadata，只容忍 regular、owner 正確、連結數 0 的同名側檔。主檔、陌生檔案、非 regular、錯誤 owner、連結數大於 1 及其他錯誤仍拒絕。schema、設定 API、launcher、時限、Hook 信任及 Windows ACL 未改。

| 項目 | 最終結果 |
| --- | --- |
| 受影響回歸 | `tests.infrastructure.test_owned_sidecars` 同組 **6 項修前紅、修後綠**；四種側檔的 ENOENT／連結數 0 與安全負向保護。 |
| 本機套用 | 兩宿主安裝代 `1e33d5b63efdd39756afe1ea`；兩份 runtime、app archive、Codex 原生快取與來源一致。owned.py SHA-256：`c174da36fbd53a37d4d7b2469c770e425384fc42b905c219375bcd87823ff6c7`。建立時 HEAD 為 `6b0ebd8`，修正尚未提交，不能說該舊提交已含新碼。 |
| 自然驗收 | 未加 trace／函式包裝／人工刪檔，4 worker＋1 writer，3.365 秒完成 **44 個 Hook（24 Pre／20 Post）與 1,090 次 SQLite 開關**；44 個 `{}`，0 故障／逾時／writer 錯誤。每個 worker 完成 5 組 Pre／Post 後達標停止；4 個在途 Pre 收完未再排 Post，advice／children 24／20 不是漏記。 |
| 保全 | MRH 設定、適用範圍、7 張表的全部原列與金鑰存在狀態保留。兩 launcher、Codex Hook 定義／trusted、Mac 1／1 秒及 Codex 宿主 2 秒不變。Claude 私有 Hook JSON 僅安裝代 Python 路徑變動，不能稱 bytes 全同；最終正式 Claude 設定前後相同。不同中間基準曾有非 MRH SessionStart／UserPromptSubmit 變動，來源未知，MRH entries 不變，現值保留。 |

此修正、必要驗證與本機套用已接受，沒有新增待辦。自然驗收沒有 provider 或真實子代理；不受影響的五模組、discover、原生派工及清單證據沿用，未擴成全平台驗證。16 個 fixture 檔與執行目錄、44 個 launcher 程序均已清理；必要失敗／成功證據與原資料保留。這是原工作量驗收，不是正式故障率估計。

## 5. 未決項目與已解決項目

Windows 的 Post 宿主 5 秒、Small／Mid 並行與 `0aac0c0` 的 SQLite 側檔修正已驗證，詳見[Windows 紀錄](windows-validation.md)。Windows 修前約 0.24%／修後 0 次屬私有壓力樣本，不是 Mac 或日常故障率；本次 Mac 未重跑 Windows。

保留的限制：Windows 非 MRH 的 model、model_reasoning_effort、service_tier 與 10 月 22 日備份不同；安裝器不寫這些鍵，當時 Codex 也在執行，但寫入者與時間未證實。後續讀回只有 MRH 信任雜湊及 marketplace 指標變動。舊 Claude 工作階段須重新載入外掛才用到 5 秒 Post，新工作階段已驗；並行樣本是合成小任務，該次 Codex Jev 都低於 0.5、保留原呼叫，建議→重發→Post 關聯屬稍早另一次證據。這些限制不阻擋已接受的 Mac 收尾。

Mac `sandbox-exec`、1／1 秒時限及原有安全拒絕維持；Windows 的放寬不轉用到 Mac。已接受結果不代表其他平台通過，文件不能授權外送、改信任或發布。

## 8. 前輪 Mac 驗收紀錄（僅 ddc4e4157）

<a id="前輪-41-程式碼層"></a>
<a id="前輪-42-安裝"></a>
<a id="前輪-43-原生-hook-smokeclaude-與-codex-分項"></a>
<a id="前輪-44-claude-清單sandbox-exec"></a>


前輪由 `6d10f9f` 快轉到 `ddc4e4157`，相對 Windows 程式 `9d50280` 僅多交接文件；該包已接受，不能代替後輪 `6b0ebd8`。

| 項目 | 前輪結果與限制 |
| --- | --- |
| 測試 | 同五模組 12／7／9／10／43＝**81 PASS**，46.271 秒；discover **568 run＝458 PASS、110 SKIP、0 FAIL／ERROR**，91.487 秒。未重跑舊版造基準。前三個模組有 fcntl／POSIX 假設：supervisor 在 Windows 無法匯入，另外兩模組 21 項中 13 項在當時 HEAD 同樣失敗，這是補 Mac 證據的原因。 |
| 安裝 | 來源 ddc4e4157，完整性 verified，兩宿主 configured、Codex trusted、pending 空、金鑰存在，保留 packets。MRH 設定、Claude 設定、範圍及原統計列保留，新增合成列另計。Mac Local／Post 1.0，POSIX launcher 與 6d10f9f 及兩宿主產物相同。 |
| Codex 0.163.0 | 真 Jev Light/0.77 → gpt-6-luna/high → 一次重發 → 官方 child completed/OK、Post followed=1；模型／強度由獨立 metadata 核對，Post resolved_model 仍 null。明示模型保留且無 Jev，但該 child 終結僅 parent 回報，無獨立 child 身分；保留封包原生拒絕，disabled 原生 **SKIP**。 |
| Claude Code 2.1.309 | 真 Jev Light/0.87 → haiku/medium → child completed/OK、Post resolved claude-haiku-5-5、followed=1。明示 haiku 保留且無 Jev，另一 child completed；實際 child effort 未獨立回報。單次宿主設定的獨立 disabled profile，原生 Pre／Post `{}`、exit 0、child completed，未建立 MRH DB。 |
| Claude 清單 | 初期 2.1.296 命令取得 5 模型；兩次原生 init 與最終清單為 2.1.309、isolated-defaults。安裝 catalog 與來源相同，使用 sandbox-exec，無無隔離 fallback；未做外部 syscall tracing。 |

本包 Jev 真實 transport **3 次**（Codex 2，含初次低信心；Claude 1），12 筆 lifecycle 不是 12 次請求。初次 Codex 一般委派因 runner 的 ephemeral parent 缺 rollout 而失敗，保留原失敗，只修 runner 並補該案例一次；未重跑已過的明示／packet。未觀測 MRH Hook 逾時或重複成功委派，四個 CLI 程序群組已退出。

整份 Codex config.toml 不相同：除預期 marketplace 來源，service_tier 由 default 變 priority，寫入者及確切時間未知；未歸因、回寫或當成已證明分級故障。這項前輪觀測與後輪 Claude 非 MRH Hook 差異分開，不能泛稱全部宿主設定完全保全。
