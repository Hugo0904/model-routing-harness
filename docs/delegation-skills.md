# 選配派工 skill

這兩份社群 skill 幫主 AI 把可完整交接、可驗收且值得委派的工作交給原生子代理。它們沒有固定模型家族、專家角色、推理強度或派工數量，也不保證每次委派都比較省。主 AI 負責授權判斷、工作分解、品質、整合與最後驗收；Jev 只依 MRH 設定提供選型建議。

`setup` 不會自動安裝。自己執行下列安裝指令就是選擇安裝；請 AI 代辦時，AI 必須先詢問，明確同意才安裝，沒有答覆就不裝。原有 Router、其他 skill 與工作流不會被覆寫。

## 安裝與移除

只執行使用中的平台，每次都必須明確指定 `--host`：

```sh
mrh skill status --host codex
mrh skill install --host codex
mrh skill remove --host codex
```

Claude Code 將 `codex` 換成 `claude`；Gemini 尚未支援，回報中文訊息與 exit 2。

| 平台 | 使用者 skill 位置 |
| --- | --- |
| Codex | `~/.agents/skills/mrh-delegation-codex/SKILL.md` |
| Claude Code | `${CLAUDE_CONFIG_DIR}/skills/mrh-delegation-claude/SKILL.md`；未設定時為 `~/.claude/skills/…` |

Codex 使用其[正式本地 skill 探索位置](https://developers.openai.com/codex/skills/#where-to-save-skills)，不把 Hook 安裝目錄當作獨立 skill 安裝位置。可用 `--skills-dir <skills絕對目錄>` 指定目的地；原 `--root` 保留為別名，同時提供卻指向不同位置會拒絕。Claude 的 `CLAUDE_CONFIG_DIR` 必須非空且為安全的絕對路徑。這些選項不會讓不支援的宿主增加能力。驗證使用隔離的假目錄，沒有修改開發者實際已安裝的 skill。

`status` 區分未安裝、最新、舊版、自改內容與無法確認所有權。相同內容重裝不重寫；不同內容預設拒絕，不自動更新或建立備份。未修改的 MRH 原件可明確移除，再安裝新版。

確定要取代或移除自改的 MRH skill 時，需同時明確提供 `--force --backup-dir <專案外備份目錄>`；只接受能以 MRH marker 及已知發行雜湊確認來源的內容。先保存 `SKILL.md`、marker 與含雜湊／原權限的復原 manifest，成功後才變更。備份不得放在 MRH 專案或將被變更的 skill 內；一般操作不產生備份。外來目錄、額外檔案與連結即使加 force 仍拒絕，其他 skill 不動。

```sh
mrh skill install --host codex --force --backup-dir /absolute/external/backup
mrh skill remove --host claude --force --backup-dir /absolute/external/backup
```

這兩行是需要保留自改內容時的明確操作範例，不是日常更新的預設步驟。復原時依 manifest 的 `original_path` 與 `files.*.mode` 還原兩份檔案，先核對保存的雜湊。安裝後如宿主尚未載入 skill，重新啟動宿主；PATH 設定成功不表示宿主已重新載入 skill。

## 兩個平台的流程

**Codex：** 有工程 Router 時，由既有 Router 決定工作單位、角色與 profile，不重複分配或分類。完整 brief 分類只在宿主能力已確認、插件明確選配 packet 且 profile 允許外送時，交給唯一的 `mrh-codex-packet` 協定處理。本 skill 不另做 prepare/query/release；結果未知不重送。詳見 [packet 協定](codex/full-task-packets.md)。

Windows 目前不支援完整任務 packet。安裝這份社群 skill 不會開啟 packet；原生普通委派依既有宿主規則進行，不宣稱已用完整 brief 分類。Windows 普通 Hook 可能只能觀測可讀標題，詳見[平台界線](compatibility.md)。

**Claude Code：** 普通 `general-purpose` 且沒有使用者或既有規則指定選型時，讓 MRH Hook 提供建議；Explore、自訂角色、明示模型或 effort 仍依原規則處理。只有明確回報「未建立子代理」的建議式拒絕，才依協定替換一次；成功、未知結果或其他拒絕都不是循環重試許可。Windows Claude 路由仍停用，skill 的存在不代表 MRH 已分類或可用模型已確認。

兩份原文與來源 manifest 隨 wheel／runtime 一起收錄。Codex 版僅萃取 custom Router 的委派、交接與驗收邏輯，沒有帶入其本機角色、治理或模型升級政策；來源 revision 與雜湊見 `src/mrh/resources/skills/delegation-sources.json`。靜態語意與本機檔案測試不等於模型實際遵循，更不等於已證明整體節省。
