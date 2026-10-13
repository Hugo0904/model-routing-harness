# docs 目錄說明

| 資料夾 | 內容 |
|---|---|
| `takeover/` | 接手施工與交接：`PLAN.md`（施工依據與偏離）、`HANDOFF.md`（整體狀態）、`CODEX-HANDOFF.md`（交給 Codex 的串接任務與「改哪裡 Claude 會壞」）、`CODEX-CLEANUP.md`（交給 Codex 的舊程式碼刪除清單） |
| `codex/` | Codex 桌面 App 接入的筆記與保存點 |
| `evidence/` | 真實驗證證據，依主題分：`jev/`（分級器）、`claude/`（Claude Code）、`codex/`（Codex）、`cli/`（控制中心終端實測） |
| `references/` | 設計來源（A40 Delegation Router 參考圖） |

測試用的固定資料在 `tests/fixtures/`，不在這裡。舊階段（e2–e24）文件與證據已刪除，需要時用 `git log` 查歷史。
