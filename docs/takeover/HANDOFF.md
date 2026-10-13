# MRH 交接摘要（Claude → Codex 督導 A／執行 B、C）

> 本檔由 Claude 執行者在 P6 填完 `<!-- 待填 -->`。完成後把「貼給 Codex 的訊息」整段貼到 Codex「Canopy 子代理分級器 督導」對話。

## 貼給 Codex 的訊息

```
MRH-001 已由 Claude 接手並完成一輪施工，請先讀
/Users/shawn/Code/model-routing-harness/docs/takeover/HANDOFF.md
（施工依據為同目錄 PLAN.md）。以下為最新基準，取代 D70 中與之衝突的部分：

1. 分級器可切換：jev（預設，TypeSafe）／codex_subscription／claude_subscription。
   10/11「用 Codex 訂閱取代 Jev」是誤解使用者問題，已更正；Codex 分級保留為可選項。
2. 路由改為建議式：PreToolUse deny + permissionDecisionReason，主模型自行重派；
   明示 model/effort/角色一律放行；同任務 10 分鐘內只建議一次。
3. 所有設定集中在 `mrh ctrl`；設定檔 v2（每級每平台候選清單、可調門檻）。
4. 金鑰只在 macOS Keychain（service model-routing-harness / account typesafe）或 TYPESAFE_API_KEY。
5. Branch：mrh-002-ctrl（見 git log 最新 commit）。

接下來請不要重做已完成項目；剩餘工作見 HANDOFF.md「未完成」段。B、C 恢復前先讀本檔。
```

## 起點（Claude 接手前）

- Codex 三個對話（督導 A `01a12262…db4a`、B `01a12265…5c9`、C `01a12b46…603`）於 2026-10-12 09:25–09:29 因額度 <7% 暫停於 D70。
- D70 方向（建議式、共用分級器、各家 Hook）已定，但 B 尚未寫任何程式；C 只完成 App probe 本機準備（`e160d2e`）。
- 分級來源被誤改為 Codex 訂閱；Jev 接頭保留但從未打過真 API。
- 日常 Codex 已註冊並信任 MRH 外掛 E24，設定 `enabled=false`。

## 本輪完成

分支 `mrh-002-ctrl`（從 `mrh-001` 開，未 push）。全部測試 333 個，仍只有 PLAN §15 列的 5 個**既有**失敗。

- **P1 設定與分級器**：設定 v2（每級每平台候選清單、分級器區塊、門檻；v1 讀取時記憶體遷移，已用你的真實 daily 設定驗證）；`mrh key`（Keychain，金鑰不進 argv／輸出／DB，有掃描測試）；分級器三選一 `jev`／`codex_subscription`／`claude_subscription`（registry）；Jev 402（沒額度）reason。
- **P2 建議引擎**：`src/mrh/advisory/`。規則順序：非子代理／未啟用／範圍外→放行不記錄；明示 model／effort／角色→放行；同任務 10 分鐘已建議→放行；分級→低於門檻放行；Top＋Main→「自己做」；Top＋Fixed／其他級→該平台候選清單（空則放行）。同一 hook call 重放不重新分級；分級失敗一律放行，同 session 同原因只提示一次。`advice.sqlite3` 不存任務文字。
- **P3 控制中心**：`mrh ctrl`（互動／`show --json`／`set KEY VALUE`／`keys`）。真 PTY 操作記錄 `docs/evidence/ctrl-pty-transcript.txt`。
- **P4 封裝**：0.4.0 封裝 `dist/model-routing-harness-0.4.0-macos-arm64`（私有 Python 3.11.17）；`mrh plugin prepare --advisory`；啟動器可由參數指定平台；`mrh install claude`（預設只顯示差異）。
- **P5 真實驗證**（單次樣本）：
  - **L1 Jev**：Light／Mid／Top 三樣本全分對（0.96／1.0／1.0），約 430 毫秒，一次 ~440 input tokens（≈$0.000018）。`docs/evidence/l1-jev.json`
  - **L3 Claude Code**（Sonnet 主模型，scratch 目錄）：Jev Light/0.91 → 主模型收到建議 → 自己重派 `model=haiku` → 子代理實際為 claude-haiku-4-5 → 記錄 `followed=1`。
  - **L4 Top**：Jev Top/1.0 → `continue_main` → 主模型自己完成，未開子代理。`docs/evidence/l3-l4-claude-code.json`
  - **L2 Codex CLI：尚未做**（需使用者同意，見下）。
- **P6**：README 改為使用者導向（舊版在 `docs/README-legacy.md`）、REQUIREMENTS 加 2026-10-13 修正段、PLAN §16 偏離紀錄。

## 目前狀態

| 項目 | 狀態 |
|---|---|
| 日常設定 | `runtime/daily-cli/profile/settings.json` 仍是 **v1、停用（enabled=false）**，provider 仍是 codex_subscription；備份 `runtime/daily-cli/settings.v1.bak.json`。尚未改成 Jev（等 Codex 刷新後再遷移，見下） |
| 日常產物 | `runtime/daily-cli/artifact` 已用 0.4.0 advisory 重新準備（舊的 E24 備份在 `artifact.e24.bak`）。**Codex 已安裝的外掛副本仍是舊 E24**，需 `codex plugin add model-routing-harness@model-routing-harness-local` 刷新並在 Codex `/hooks` 重新信任 |
| Codex hooks 信任 | 舊 E24 的雜湊仍有效；新產物變更後需重新信任 |
| Claude Code hook | **未套用**。`mrh install claude --artifact <repo>/runtime/daily-cli/artifact` 可先看差異 |
| 金鑰 | Keychain 已設定（`mrh key status jev`） |
| 分級費用 | 估計 ≈ $0.02／千次（Jev） |

## 怎麼用

```sh
B=/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.4.0-macos-arm64
S=/Users/shawn/Code/model-routing-harness/runtime/daily-cli/profile/settings.json
$B/mrh ctrl --settings $S              # 控制中心（設 MRH_SETTINGS 或安裝指標檔後可省略 --settings）
$B/mrh ctrl --settings $S show
```

## 未完成／已知問題

1. **L2 Codex CLI 實測**：流程已備妥——刷新外掛、`/hooks` 信任後，在 scratch 目錄用暫時縮小的 allowlist 跑 `codex exec`，只影響該目錄，跑完還原。
2. **日常設定遷移到 v2＋provider 改 Jev**：必須在 Codex 外掛刷新**之後**做（舊 E24 執行期只認 v1，遇到 v2 會在每次委派顯示警告）。已開啟的舊 Codex 對話需重開。
3. **Codex App（桌面版）**：同一外掛理論上可用，未實測（原 C 的 probe：`docs/advisory-app.md`）。
4. **Gemini**：只有模型清單，沒有 Hook 接頭（P7 未做）。
5. 控制中心沒有「宿主接入」畫面。
6. **主模型遵從率未知**：L3／L4 各 1 次；請看統計的 `children_following_advice` 累積。
7. 舊模組可刪候選（新路徑不使用，刪前需確認無其他引用）：`adapters/hosts/codex_scope.py`、`fresh_cli_scope.py`、`isolated_host_export.py`、`isolated_live_hook.py`、`routing/core.py` 的 rewrite／cheaper 路徑、`routing/facts.py`、`application/runtime.py`、`infrastructure/installer.py`，以及相關舊測試與 5 個過時失敗（PLAN §15）。
8. 已知 UX：主模型看到的訊息是「hook blocked」+ 建議文字，Claude 會自行說明「a hook blocked the subagent call」，功能正常但措辭偏嚴厲。

## 給 Codex 的注意事項

- 不要再把分級器換掉或預設成 Codex；預設 Jev 是使用者明確要求。
- 不要恢復 `updatedInput` 強制改寫。
- 金鑰與憑證不得進入任何報告或 commit。
- 文件維持精簡；以 HANDOFF.md 與 PLAN.md 為準，不要再增加長篇治理文件。
