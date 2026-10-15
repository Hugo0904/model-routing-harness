# Model Routing Harness（MRH）

**Route the task, not the session.** MRH 在主 AI 準備派子任務時提供 Light／Small／Mid／Top 分級與候選 profile 建議；主 AI 保留選型決定。明確指定的模型、推理強度或專門角色優先，分類失敗則沿原宿主契約處理。主視窗模型不會被切換。

## 交給 AI 安裝

把下面這句連同 repository 來源及你要使用的宿主交給 AI：

> 請 clone 這個 repository 到新目錄，先讀 README.md，依我選的宿主執行 `./setup --host codex`（Claude Code 則選 `--host claude`），再執行 `./setup --check --json`。保留既有設定、金鑰、統計與其他 Hook，告訴我尚缺的原生信任、金鑰、模型政策或工作區設定；不要呼叫模型來測試安裝。

本分支是**尚未 push 的本機候選**；乾淨驗收可 clone 含此候選的本機 repository。遠端尚未包含這個 revision 時，不能把遠端 clone 當成已可安裝的證據。

## 最短安裝路徑

目前安裝套件範圍為 **macOS arm64**。先有你選的官方 vendor CLI；安裝器不升級它、不替你登入。選 Claude 時，寫入 profile、建置或修改原生設定前會沿既有 catalog metadata 契約核對 CLI 是否可執行與版本受支援；缺少或不支援就退出，check 則明列先決條件未滿。MRH 自帶鎖定版本的私有 Python，不需要 Homebrew、SDK 或額外 Python。缺少可用 Python 時，只會下載、核對固定官方 runtime 的大小與 SHA-256，再執行它。

```sh
git clone <repository來源> model-routing-harness
cd model-routing-harness
./setup --host codex
./setup --check --json
```

同時選兩個宿主可用 `./setup --host codex --host claude`。只選 Codex 不會修改 Claude 設定、artifact 或 interpreter。正式安裝前可先看 `./setup --host codex --dry-run --json`；dry-run 不寫入、不下載。`--check` 不初始化缺少的設定或資料庫。

`setup` 安裝的是**目前 checkout**，不執行 git pull/reset。更新 repository 到你要的 revision 後，重跑同一條 `./setup --host ...` 即可更新；相同內容重跑不會重複加入 Hook 或 skill。

```sh
./setup --host codex                 # 安裝／更新目前 checkout
./setup --check --json               # 分開讀回安裝與就緒狀態
./setup --rollback                   # 回上一個已管理、reader 相容的代
```

第一次安裝還沒有 rollback 歷史。Rollback 只切回程式與所選宿主 wiring，**不還原舊設定或統計資料**；未知或不相容的 reader 會拒絕降版。中斷後保留回執，修正原因，再以相同參數重跑。原生註冊分步完成，不宣稱多宿主一起原子切換。

## 完成設定

新 profile 預設停用，任務外送也為 false。既有 active-settings pointer、profile、統計與金鑰沿用；沒有明確指定的設定不會被重設。

1. 在 Codex 的原生 `/hooks` 介面審閱 MRH Hook；安裝器不代寫信任資料。Hook 定義改變後需要重新審閱。被你在原生介面停用的既有插件會保留停用並要求先處理該選擇。
2. 用 `mrh key set jev` 由 macOS Keychain 提示輸入金鑰；`mrh key status jev` 只顯示是否存在。也可由你自己的安全環境提供 `TYPESAFE_API_KEY`。金鑰不放進 repository 或設定檔。
3. 用 `mrh models --host codex --json`（或 `claude`）查看目前 CLI 宣告的模型、effort、來源、時間和 assurance。這份清單不是帳號可用性或付費探測。
4. 執行 `mrh ctrl`，為每個所選宿主填妥 Light／Small／Mid 的完整 model＋effort profile，選擇 Top Main 或完整 Fixed profile。依當前能力與角色限制選擇，不從模型名字推定強弱或價格。空的或無法驗證的政策不算 ready。
5. 確認允許外送的工作區後，才明確啟用。例如 `./setup --host codex --enable --workspace /absolute/approved/project`。這一步會讓該 profile 允許任務外送；請依自己的資料範圍決定。單純安裝、check 或開啟控制中心不會啟用。

`--check --json` 分開列出 installed、configured、trust、credential_present、policy_ready、workspace_ready 與 enabled/export_permitted。政策驗證只對照 CLI 宣告；帳號可用性、實際模型、最後真實派工及未取得的用量仍標成未知或未探測。安裝成功不代表分級器、子代理或節費已實跑。需要真實模型／Jev 驗證時，另外確認目的、資料與費用；歷史 smoke 的一次性授權不適用之後每次安裝。

如果 `mrh` 不在你既有的 PATH，直接用 `~/.local/bin/mrh`；安裝器不改全域 PATH。

## 可選 Codex 完整任務 packet

普通 Codex Hook 可能只取得 `task_name`，完整 `message` 由宿主加密。可選 packet 協定讓父 AI 在派工前保存完整 brief，由 Hook 綁定原生回合後分類。**這個能力仍待比較評估，不是一般安裝的預設或正式採用結論。**

```sh
./setup --host codex --codex-packets
```

只有這個明確選項會提供 packet artifact 與自足的 `mrh-codex-packet` skill。更新既有 packet 安裝時保留相同選項；普通安裝不會默默開啟或取代它。若已安裝 Router bridge，同一任務只能有一個 packet 協定 owner，不能分類兩次。原文保護、Top Main、未知結果與清理規則見[完整協定](docs/codex/full-task-packets.md)及[skill 邊界](docs/codex/packet-skill.md)。沒有獨立外送許可時不呼叫分級器。

## 日常操作與資料

```sh
mrh ctrl                          # 互動設定；取消不保存
mrh ctrl show --json              # 公開設定
mrh status --json                 # 唯讀狀態／Monitor 出口
mrh stats                        # 分級、回退、派工與已觀測採用
mrh stats reset --hours 24        # 預覽，確認後才刪統計（另有 --today、--days N、--all）
mrh ctrl set enabled off          # 停用路由
```

預設 CLI 是 `~/.local/bin/mrh`；安裝代位於 `~/.local/share/model-routing-harness/setup-state/generations/`，`current` 指向啟用的代。新 profile 位於 `~/.config/model-routing-harness/profile/`，與 `advice.sqlite3` 都獨立於 clone／程式代。有既有 active-settings pointer 時沿用它；若舊 pointer 指向 clone 內的 profile，更新不會擅自搬移，刪除該舊 clone 前仍須另行遷移資料。

舊的 `app/` 目錄會保留作為既有 interpreter／Claude 命令的錨點，不會為更新 Codex 而替換共享 runtime。所選宿主的新 wiring 指向完整、獨立的代；未選宿主保持原樣。隔離驗證可明確指定 `--prefix`、`--config-root`、`--bin-dir`、`--cache-root`、`--settings`、`--codex-cli`、`--claude-cli` 或 `--claude-settings`，不必改 HOME/CODEX_HOME；CLI override 的來源會明列，並沿相同 metadata 檢查，不代表真正 vendor／帳號驗收。更多恢復細節見[安裝生命週期](docs/install-lifecycle.md)。舊 `install_local.py` 入口已停止危險的共享 app 替換，請用 `setup`。

本機維護注意事項：目前 Claude hook 的 Python 是 `/Users/shawn/.local/share/model-routing-harness/app/runtime/bin/python3.11`，launcher 是 `/Users/shawn/Code/model-routing-harness/runtime/daily-cli/artifact/plugins/model-routing-harness/launcher.py claude`。這個舊 `app/` 不在 `setup-state/generations/` 管理範圍內。任何 setup 清理、rollback、Codex-only 更新或 runtime 清理，都不能刪除或移動上述 `app/` 與 `runtime/daily-cli/`；Python 不存在時 hook 根本無法啟動，MRH 的 fail-open 也無法處理。日後若要讓 Claude 改用 generation 管理，必須先提出遷移方案，包含 `~/.claude/settings.json` 的修改方式，經使用者同意後才執行。

## 支援與證據邊界

| Surface | 此候選的安裝邊界 | 實際派工驗收 |
|---|---|---|
| Codex CLI | 官方 marketplace/plugin 命令；隔離生命週期與公開 consumer 驗證 | 沿用既有 packet／核心證據，本輪不啟動付費模型 |
| Codex Desktop App | 同一官方插件；仍需原生信任審閱 | 此候選的新 App 畫面／派工驗收尚未完成 |
| Claude Code CLI | 選配 CLI 先決條件與設定合併 | 本候選只驗隔離 fixture；現用 Claude 設定保留與實機驗收尚未完成 |
| Claude Desktop Code | 同宿主接頭的預定 surface；不含 Chat／Cowork | 尚未另做本候選實機驗收 |

Gemini 僅有既有 catalog，沒有 Hook 或 setup adapter。加入宿主需要明確註冊、安裝 adapter 與原生證據；見[最小擴充點](docs/host-extension.md)。不會靠放一個檔案就自動支援第三家。

MRH 提供建議與可追溯統計，沒有證據時不宣稱實際模型、節省費用或帳號額度。Canopy 背景與 Monitor 顯示皆為選配，安裝器不依賴它們、不讀私人記憶或 Monitor DB。

## 開發

直接驗證安裝路徑：

```sh
PYTHONPATH=src python3 -B -m unittest tests.infrastructure.test_setup tests.infrastructure.test_bundle tests.infrastructure.test_advisory_plugin tests.infrastructure.test_owned_plugin
```

只對變動影響到的保證補必要檢查。需要整個 repository gate 時可用 `PYTHONPATH=src python3 -B -m unittest discover -s tests -t .`；涉及真實 provider 的腳本須另有當次授權。本機候選不是已發布、簽署或 notarize 的多平台版本，repository 也未因此取得新的公開散布授權。
