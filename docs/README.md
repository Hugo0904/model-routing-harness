# MRH 文件

依你要完成的事情選擇入口。安裝與基本操作從 [README](../README.md) 開始。

## 使用與維護

| 文件 | 內容 |
| --- | --- |
| [手動安裝](install.md) | 從 clone、Jev 金鑰、模型選擇到啟用與更新。 |
| [選配派工 skill](delegation-skills.md) | Codex／Claude 的安裝、狀態與移除，以及平台能力界線。 |
| [設定與日常操作](usage.md) | 模型選擇、信心門檻、進階檔位、統計與用量。 |
| [平台與版本](compatibility.md) | macOS 安裝範圍、Windows 狀態、宿主版本與已知限制。 |
| [疑難排解](troubleshooting.md) | 尚未啟用、模型清單失敗、信任、更新與回退。 |
| [安裝生命週期](install-lifecycle.md) | 安裝器的儲存、更新、資料保全與恢復設計。 |
| [驗證摘要](validation.md) | 已測範圍、固定劇本比較與結果的適用限制。 |

## 開發與接入

| 文件 | 內容 |
| --- | --- |
| [專案理念](../PHILOSOPHY.md) | 開發、設計與驗收的原則，以及目標、實作與證據的區別。 |
| [開發指南](development.md) | 原始碼位置、離線測試、fixture 與驗證工具的使用界線。 |
| [產品設計](design.md) | 任務分級、明示選型保護、回退與統計原則。 |
| [新增宿主](host-extension.md) | adapter、安裝流程與原生事件契約。 |
| [Mac 驗收交接](mac-handoff.md) | Windows 修復後的 Mac 驗收項目、結果與仍由 Windows 處理的未決事項。 |
| [Codex 完整任務 packet](codex/full-task-packets.md) | 明確選配的完整 brief 分類協定。 |
| [Packet skill](codex/packet-skill.md) | 單一協定 owner、打包與啟用範圍。 |
| [本機樣本收集器](codex/daily-collection.md) | 獨立、明確選配的收集工具。 |
| [背景摘要契約](contracts/context-v1.md) | 受信任應用程式提供核准摘要的介面。 |
| [Metadata 快照契約](contracts/monitor-v1.md) | 唯讀統計出口，含 [Schema](contracts/monitor-v1.schema.json) 與 [合成範例](contracts/monitor-v1.synthetic.json)。 |

測試用資料放在 [`tests/fixtures`](../tests/fixtures/README.md)。公開文件只保留可使用的契約與驗證摘要；個人環境、原始宿主輸出及內部交接資料不作為安裝依賴。
