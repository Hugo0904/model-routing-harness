# Codex 日常委派原文收集

既有兩筆歷史樣本原件保留。新的授權涵蓋此 Mac 本機使用者家目錄工作區內，一般 Codex 聊天在啟用後原本就需要且已有授權的真實新委派；不限定 MRH 或 A／B／C。收集實作的 A、B 聊天排除。目標總數仍為 10；不造任務、不刻意拆分、不等其他窗口、不回填歷史、不啟動付費比較或外送。原 scope、索引與本文已先備份到獨立 collector 的 migrations 目錄。

## 原文與成功回執

1. UserPromptSubmit 保存原生 session／turn／cwd 的 owner-only 短期 context，再提醒派工者。在原本就要呼叫 `collaboration.spawn_agent` 前，將完整實際工具 JSON 經 stdin 送入本機固定版本的 `daily.py stage --context <Hook提供的路徑> --natural --safe-to-store`。完整命令由已審閱 Hook 提供；stage 核 context 已由 Hook 登錄且 session 等於環境 `CODEX_THREAD_ID`，PreToolUse 再核同一 session／turn／cwd，不猜父或子原生身分。派工者須確認是必要新任務，且沒有憑證或敏感原始資料；有敏感內容就跳過收集，不能改寫成看似安全的假原文。Regex 僅為補充篩檢。
2. 請求在派工前固定於 `/private/tmp` 下 collector 專屬、非 symlink、owner-only 的 spool，檔案 `request.json` 為 0400；context 與執行 state 也只寫該 spool，stage 不寫中央 dataset，其他專案 sandbox 不需為收集提權。成功 Post Hook 才將完全相同的 request bytes 固定複製到中央持久 `captures/<capture>/request.json`，先歸檔才計數。Canonical 正文是該持久檔案的 `#/message` 原字串，名稱對應 `#/task_name`，索引不能指向會消失的 tmp。保留完整 payload、原字串 UTF-8 bytes 與 SHA。派生純文字副本須逐字核對；副本有差異就保留瑕疵，不能自行修原件、trim、normalize、重建或用近似內容冒充。歷史第二筆有多一個 LF 的副本仍不能作比較輸入。
3. PreToolUse 只在 session、cwd、原生 call／turn 與事前 stage 唯一匹配時綁定，逐一核 task name／role／model／effort／fork；明文正文須相同。加密正文不解密，也不聲稱比對成功。沒有 stage、歧義、不匹配、失敗、取消或缺少成功原生 reference 均不計數，不 deny、不改工具輸入、不改模型或原 MRH／Canopy 保護。
4. PostToolUse 成功回執才由本機 collector 在鎖內更新中央索引。每個 capture／session+call 只計一次，續作與重試不新增樣本。加密正文標為 `parent_pre_dispatch_attestation` 與 `native_body_equality=unobservable_ciphertext`；只有真正明文相等才是 `verified_plaintext`。實際模型／effort 無可信回讀就留 null，不能拿要求值冒充實際值。
5. 到 10 筆就在最後一次成功 Post 的同次輸出提示收齊並停止收集；其他窗口不需等待或轉交。沒有自然事件時維持目前數量。任何外送、Jev 或全成本比較都尚未授權。

## 保留、安全與驗收界線

- 每個請求最多 64 KiB，最多保留 64 個 captures（包括未完成與已計入者）；到上限拒絕新增，原任務照常，不自動刪除任何原件。已失效的事前 stage 超過 24 小時不再匹配，但原件保留，需 owner 明確處置才可重開容量。
- state 的 events、bindings 各最多 256 筆；只淘汰舊執行 metadata，不刪原文或已登錄 receipt。中斷寫入僅使用一個固定暫存槽；殘留時停止該寫入供檢視，不無限產生暫存檔。備份、歷史樣本、captures 不自動刪除。
- Hook 產生的 context 只含 session／turn／cwd 等 metadata，最多 64 份、有效期 24 小時；可淘汰過期或最舊的已登錄 context，不刪 capture 原文。沒有有效 context 的回合不收集。
- 只接本機 Codex root 聊天委派。子代理 Hook 使用父 session；子代理內再委派未接入，不猜父 ID。遠端 Windows、Claude、繞過 Hook 的特殊路徑均不宣稱已接通。
- 新 Hook 必須經官方 `/hooks` 審閱並信任精確定義，否則宿主可能跳過。寫好設定、通過隔離 fixture，不等於原生啟用或跨聊天自然事件驗收。既有聊天需在下一個使用者回合取得提醒，且可能需要重新載入 Hook 配置。
- `install.py status` 讀安裝狀態；`disable`／`uninstall` 僅移除本 collector 的精確標記 handlers、停用配置，保留其他 handlers 和全部樣本、備份、固定版本程式。不要把舊 hooks.json 整份蓋回而刪掉別人的後續修改。
