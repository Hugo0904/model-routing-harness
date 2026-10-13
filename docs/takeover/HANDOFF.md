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
5. Branch：mrh-002-ctrl，最後 commit <!-- 待填 -->。

接下來請不要重做已完成項目；剩餘工作見 HANDOFF.md「未完成」段。B、C 恢復前先讀本檔。
```

## 起點（Claude 接手前）

- Codex 三個對話（督導 A `01a12262…db4a`、B `01a12265…5c9`、C `01a12b46…603`）於 2026-10-12 09:25–09:29 因額度 <7% 暫停於 D70。
- D70 方向（建議式、共用分級器、各家 Hook）已定，但 B 尚未寫任何程式；C 只完成 App probe 本機準備（`e160d2e`）。
- 分級來源被誤改為 Codex 訂閱；Jev 接頭保留但從未打過真 API。
- 日常 Codex 已註冊並信任 MRH 外掛 E24，設定 `enabled=false`。

## 本輪完成

<!-- 待填：每項寫「做了什麼＋commit＋怎麼驗證的」 -->
- P0：
- P1：
- P2：
- P3：
- P4：
- P5（L1 Jev／L2 Codex CLI／L3 Claude Code／L4 Top Main 各自結果，含是否 followed）：
- P6：

## 目前狀態

<!-- 待填 -->
| 項目 | 狀態 |
|---|---|
| 日常設定路徑 | `runtime/daily-cli/profile/settings.json`（v2） |
| enabled | |
| 分級器 | |
| 金鑰狀態 | 已設定／未設定（不得寫出金鑰） |
| Codex hooks 信任 | |
| Claude Code hook | |
| 測試 | 通過數／失敗數 |

## 怎麼用

<!-- 待填：使用者實際操作的 3–6 行指令，例如 mrh ctrl、mrh key status jev、停用方式 -->

## 未完成／已知問題

<!-- 待填：至少包含下列，若已完成就刪掉 -->
- Codex App 端尚未實測（可用同一外掛，請使用者手動試一次；原 C 的 probe 說明在 `docs/advisory-app.md`）。
- Gemini 接頭（P7）。
- 舊模組可刪候選（新路徑已不使用）：`adapters/hosts/codex_scope.py`、`fresh_cli_scope.py`、`isolated_host_export.py`、`isolated_live_hook.py`、`routing/core.py` 的 rewrite／cheaper 路徑、`routing/facts.py`；刪除前需確認無其他引用。
- P0 未修的舊測試失敗及原因：
- 主模型是否照建議挑模型的實測比例（L2/L3 只是單次樣本，不代表長期遵從率）。

## 給 Codex 的注意事項

- 不要再把分級器換掉或預設成 Codex；預設 Jev 是使用者明確要求。
- 不要恢復 `updatedInput` 強制改寫。
- 金鑰與憑證不得進入任何報告或 commit。
- 文件維持精簡；以 HANDOFF.md 與 PLAN.md 為準，不要再增加長篇治理文件。
