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
6. Codex 0.159.3 對 Hook 隱藏委派內文（message 為密文），只能用 task_name 分級；舊 L2 兩次沒改派。B 接管的新文案候選在隔離 CLI 10/10 改派到實際 gpt-5.6-luna/low，Claude smoke 9/9；詳見 CODEX-HANDOFF.md 與 docs/evidence/codex/l2-codex-advice-20261013.json。桌面 App／日常 Codex 接受仍待 A、C。

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
- **P3 控制中心**：`mrh ctrl`（互動／`show --json`／`set KEY VALUE`／`keys`）。真 PTY 操作記錄 `docs/evidence/cli/ctrl-pty-transcript.txt`。
- **P4 封裝**：0.4.0 封裝 `dist/model-routing-harness-0.4.0-macos-arm64`（私有 Python 3.11.17）；`mrh plugin prepare --advisory`；啟動器可由參數指定平台；`mrh install claude`（預設只顯示差異）。
- **P5 真實驗證**（單次樣本）：
  - **L1 Jev**：Light／Mid／Top 三樣本全分對（0.96／1.0／1.0），約 430 毫秒，一次 ~440 input tokens（≈$0.000018）。`docs/evidence/jev/l1-jev.json`
  - **L3 Claude Code**（Sonnet 主模型，scratch 目錄）：Jev Light/0.91 → 主模型收到建議 → 自己重派 `model=haiku` → 子代理實際為 claude-haiku-4-5 → 記錄 `followed=1`。
  - **L4 Top**：Jev Top/1.0 → `continue_main` → 主模型自己完成，未開子代理。`docs/evidence/claude/l3-l4-claude-code.json`
  - **L2 Codex CLI**（`docs/evidence/codex/l2-codex-cli.json`）：外掛已刷新為 0.4.0 並由使用者信任。Hook 真的觸發、Jev 真分級、deny 建議送達 Codex 主模型。**發現三件事**：①Codex 0.159.3 交給 Hook 的 `message` 是**密文**（Fernet），任何模型／multi-agent 設定都一樣，只有 `task_name`（主模型取的短標籤）、`model`、`cwd` 可讀 → 改用 `task_name` 分級（Jev 對 slug：改名類 Light 0.85–0.97、調查類 Mid 0.99、設計類 Top 0.65，含糊的自動低於門檻放行）；②主模型幾乎每次帶 `agent_type: "worker"` → 新增可設定的「視為預設的角色」（Codex 預設 `worker`，你自訂的 `luna_worker` 等仍受保護）；③**兩次有建議的跑法，Codex 主模型都沒有照建議改派**（一次回報被擋、一次自己做完），Claude Code 則 1/1 照做。單次樣本，遵從率未知。
- **P6**：README 改為使用者導向（舊版在 `docs/README-legacy.md`）、REQUIREMENTS 加 2026-10-13 修正段、PLAN §16 偏離紀錄。

## 目前狀態

| 項目 | 狀態 |
|---|---|
| 日常設定 | `runtime/daily-cli/profile/settings.json` 已是 **v2、provider=jev、停用（enabled=false）**，allowlist 檔已還原為 `/`；v1 備份 `runtime/daily-cli/settings.v1.bak.json` |
| 日常產物 | `runtime/daily-cli/artifact` 為 0.4.0 advisory（舊 E24 備份在 `artifact.e24.bak`）；**Codex 外掛副本已刷新**（`codex plugin add …`，config.toml 備份 `runtime/daily-cli/codex-config.before-refresh.toml`）。更新程式後重建封裝、重新 prepare、再 `codex plugin add` 即可，只要 hooks.json 不變，信任不失效 |
| Codex hooks 信任 | 2026-10-13 改指向固定安裝路徑後需**再信任一次**（之後升級不需要） |
| Claude Code hook | **已套用**（2026-10-13，使用者同意）：`~/.claude/settings.json` 新增 Pre／PostToolUse（matcher `Agent|Task`），備份 `~/.claude/settings.json.mrh-bak-20261013-151613`；其餘設定與原有 hook 未動。路由停用中，hook 回 `{}`。移除：`mrh install claude --artifact <artifact> --remove --apply` |
| 金鑰 | Keychain 已設定（`mrh key status jev`） |
| 分級費用 | 估計 ≈ $0.02／千次（Jev） |

## 怎麼用

安裝在固定位置 `~/.local/share/model-routing-harness/app`，指令 `~/.local/bin/mrh`，設定指標 `~/.config/model-routing-harness/active-settings`（指向日常設定），所以直接 `mrh ctrl` 即可。兩邊 hook 都指向這個固定的 Python；升級流程見 README。

```sh
B=/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.4.0-macos-arm64
S=/Users/shawn/Code/model-routing-harness/runtime/daily-cli/profile/settings.json
mrh ctrl          # 控制中心
mrh ctrl show     # 目前設定
```

## 2026-10-13 晚間更新：Claude Code 升級與 effort

- Claude Code 由 stable 2.1.287 換成 `claude-code@latest` cask（2.1.296；先 `brew uninstall --cask claude-code` 再 `brew install --cask claude-code@latest`，兩者衝突）。`~/.claude` 設定未動。
- 2.1.296 實測：子代理 `haiku` → `claude-haiku-5-5`、`sonnet` → `claude-sonnet-5-5`（2.1.287 的 `haiku` 是 Haiku 4.5）；Agent 工具新增 `effort` 參數，建議文字已帶出 `effort=…`，主模型自選 effort 視為明示。實測：Light/0.91 → 主模型改派 haiku＋effort=medium → 子代理 claude-haiku-5-5 → followed=1。
- 使用者設定（Claude）：Light `haiku:medium`、Small `haiku:xhigh`、Mid `sonnet:medium`；Codex 三級仍為 `gpt-5.6-luna:low`；Top 為 Main。路由仍停用。

## 2026-10-13 夜間更新：CLI 畫面

- 控制中心、`mrh key`、錯誤訊息、統計全為中文；設定一覽改成難度表。
- 新增 `mrh ctrl dashboard`（參考 A40 Delegation Router 版面：圓角卡片、流程四格、難度表含 Claude 官方價、分段比例條、進度條）。使用者要求畫面**一律以 CLI 為主**（無 UI 環境查看），網頁報表 `mrh ctrl report` 只是選用預覽。
- Claude 真實環境測試（真實安裝的 hook）：輕量→改派 Haiku 5.5＋effort、平行 3 個、互動模式（fork 開啟）、Explore 不干預、中文、金鑰錯誤不擋工作且通知顯示給使用者；`scripts/verification/claude_smoke.py` 9/9。
- 已部署最新程式（hooks.json 不變）。給 Codex 的交接：`CODEX-HANDOFF.md`。

## 未完成／已知問題

1. **Codex CLI 候選已驗證，尚待整體接受**：新文案明確要求以 `fork_turns=none` 重派。10 次有效隔離試跑均由真 Jev 建議並改派到原生讀回的 `gpt-5.6-luna / low`，且任務完成；全部 12 次啟動與兩次前置試跑均有記錄。證據：`docs/evidence/codex/l2-codex-advice-20261013.json`。不據此宣稱日常遵從率或省錢幅度。
2. **日常設定已啟用**：最新讀回為 `enabled=true / provider=jev`，早期停用記錄是歷史狀態。正常 Codex registry／trust 與 App 的最後讀回由 C 負責；B 未更動日常設定。Codex 仍只看得到 `task_name`。
3. **Codex App（桌面版）**：同一外掛理論上可用，未實測（原 C 的 probe：`docs/codex/advisory-app.md`）。
4. **Gemini**：只有模型清單，沒有 Hook 接頭（P7 未做）。
5. 控制中心沒有「宿主接入」畫面。
6. **遵從率的適用範圍**：本候選的簡單文字 Light 任務為 10/10，其他任務、等級與日常／App 遵從率仍未知；DB `children_following_advice` 本身不能證明實際子模型。
7. 舊模組可刪候選（新路徑不使用，刪前需確認無其他引用）：`adapters/hosts/codex_scope.py`、`fresh_cli_scope.py`、`isolated_host_export.py`、`isolated_live_hook.py`、`routing/core.py` 的 rewrite／cheaper 路徑、`routing/facts.py`、`application/runtime.py`、`infrastructure/installer.py`，以及相關舊測試與 5 個過時失敗（PLAN §15）。
8. 已知 UX：主模型看到的訊息是「hook blocked」+ 建議文字，Claude 會自行說明「a hook blocked the subagent call」，功能正常但措辭偏嚴厲。

## 給 Codex 的注意事項

- 不要再把分級器換掉或預設成 Codex；預設 Jev 是使用者明確要求。
- 不要恢復 `updatedInput` 強制改寫。
- 金鑰與憑證不得進入任何報告或 commit。
- 文件維持精簡；以 HANDOFF.md 與 PLAN.md 為準，不要再增加長篇治理文件。
