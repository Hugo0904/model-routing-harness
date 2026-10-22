<div align="center">

# Model Routing Harness（MRH）

**依子任務難度，建議合適的模型與推理強度。**

[![Version](https://img.shields.io/badge/version-0.4.0-2563eb)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-macOS_Apple_Silicon_%7C_Windows_x64-111827)](docs/compatibility.md)
[![Hosts](https://img.shields.io/badge/hosts-Codex_%7C_Claude_Code-0f766e)](docs/compatibility.md)

[交給 AI 安裝](#交給-ai-安裝) · [自己安裝](#自己安裝) · [常用指令](#常用指令) · [移除](#移除) · [English](README.en.md)

</div>

## 這是什麼

主 AI（Codex 或 Claude Code）派子代理做事、卻沒有指定模型時，MRH 會先請 Jev 判斷這件事的難度（Light／Small／Mid／Top），再建議主 AI 改用你為該難度設定的模型與推理強度重新派工。簡單的事交給便宜的模型，難的事才用貴的。

- 主聊天的模型不會被換掉，最後決定權在主 AI。
- 已經指定模型、推理強度或專門角色的派工，MRH 不插手。
- 判斷失敗或信心不足時照原樣放行，不影響工作。
- 新安裝預設停用，要你同意後才會開始運作。

## 交給 AI 安裝

把下面這段貼給能操作你電腦的 AI（例如 Codex 或 Claude Code），它會照步驟裝好，需要你動手或決定的地方會停下來問你：

```text
請幫我安裝 MRH：https://github.com/Hugo0904/model-routing-harness
照 repo 裡的 docs/install.md 做，並遵守：
1. 先確認我的作業系統，以及要裝給 Codex、Claude Code 還是兩者；不確定就問我。
2. 保留我現有的設定、金鑰、統計、skill 和其他 Hook；遇到衝突或同名指令就停下來告訴我，不要覆蓋。
3. Jev 金鑰、登入和 Codex 的 Hook 信任由我自己操作，你告訴我要執行什麼就好。
4. 啟用前先問我允許哪些專案的任務內容送到 TypeSafe 分級，我同意後才啟用。
5. 完成後執行 --check --json，並在新的終端機環境、一般資料夾裡執行 mrh status，確認指令可以用。
6. 分開回報：安裝結果、mrh 指令能不能用、Hook 信任狀態、還沒做的測試。不要為了測試呼叫 Jev 或派子代理（會花錢）。
7. 最後問我要不要安裝選配派工 skill，我說要才裝。
```

## 自己安裝

**Mac（Apple Silicon）**：需要 Git，以及已登入的 Codex 或 Claude Code。安裝器會自備 Python。

```sh
git clone https://github.com/Hugo0904/model-routing-harness.git
cd model-routing-harness
./setup --host claude        # Codex 用 --host codex；兩個都要就兩個都寫
```

開一個新的終端機視窗，再繼續：

```sh
mrh key set jev              # 存入 Jev 金鑰（到 https://console.typesafe.ai/keys 建立）
mrh ctrl                     # 設定每個難度要用的模型
```

同意任務內容送到 TypeSafe 後，回到 repo 資料夾啟用並檢查：

```sh
./setup --host claude --workspace "/" --enable   # "/" 代表全部專案；也可以換成某個專案的路徑
./setup --check --json                           # pending 是空的就完成了
```

**Windows（x64）**：需要 Git 與 Python 3.11 以上（原生 x64），不需要 WSL。Codex 已有實機路由證據；Claude 的原生插件可安裝，但零權限 LPAC 模型清單尚未通過，仍保持停用。步驟見[安裝教學的 Windows 章節](docs/install.md#windows-x64)。

## 費用與資料外送

- 分級使用 TypeSafe 的 Jev API，費用記在你的 TypeSafe 帳號，和 Codex／Claude 的訂閱分開。
- 啟用後，每次派工的任務文字會送到 TypeSafe：Claude Code 送子代理的 prompt；Codex 送任務訊息，訊息加密時只送任務名稱。內容照原樣送出，MRH 不會過濾。
- 選配功能（Codex 完整任務分類、額外標題與角色、背景摘要）會送出更多內容，說明見[外送規則](docs/design.md#外送與失敗處理)。
- 隨時可以用 `mrh ctrl set enabled off` 停用。

## 常用指令

| 指令 | 用途 |
| --- | --- |
| `mrh ctrl` | 開啟設定選單（模型、信心門檻、適用專案）。 |
| `mrh status` | 查看目前狀態。 |
| `mrh stats` | 查看分級與派工統計。 |
| `mrh usage collect` | 收集子代理用量（只讀本機紀錄，不呼叫模型；換算金額只是估計，不是帳單）。 |
| `mrh usage overhead` | 攔下重派的開銷（等待時間、主模型多跑的一輪）和省下的錢並列（只讀本機紀錄，不花錢）。 |
| `mrh key status jev` | 確認 Jev 金鑰是否已存入（不顯示內容）。 |
| `mrh ctrl set enabled off` | 停用。 |
| `mrh cleanup` | 預覽可清除的暫存；加 `--apply` 才清除。不動設定與統計。 |

安裝或更新後要開新的終端機視窗，`mrh` 指令才會生效。

## 選配：讓 AI 主動分派子任務

一般使用時，主 AI 不常自己派子代理，MRH 也就很少有機會出手。想讓主 AI 當「大腦」、把範圍明確的小工作交給子代理，可以安裝這個 skill（安裝器不會自動裝）：

```sh
mrh skill install --host claude   # Codex 用 --host codex
```

查看狀態與移除方式見[選配派工 skill](docs/delegation-skills.md)。

## 更新

貼給 AI：

```text
請幫我更新 MRH（就在目前這個 repo 資料夾）。照 docs/install.md 的更新步驟做：
1. 先確認沒有未提交的修改，有就停下來問我。
2. git pull --ff-only 後，用原本的安裝參數重跑安裝。
3. 保留設定、金鑰、統計、skill 和其他 Hook；不要改外送範圍，不要重裝 skill。
4. 執行 --check --json，並在新的終端機環境、一般資料夾裡執行 mrh status。
5. 回報結果與還沒驗證的項目；不要為了測試呼叫 Jev 或派子代理。
```

自己更新：在 repo 資料夾執行 `git pull --ff-only`，再用原本的指令重跑一次 `./setup`（例如 `./setup --host claude`）。出問題可以用 `./setup --rollback` 退回上一版。新版本只在程式內容有變時才會產生；只改了文件的更新，重跑 `./setup` 會回報沒有變更。

## 移除

**Mac**：在 repo 資料夾執行：

```sh
./setup --uninstall                      # 預覽會移除什麼，不做任何變更
./setup --uninstall --yes                # 移除，保留設定與統計
./setup --uninstall --yes --purge-data   # 連設定、統計和鑰匙圈裡的 Jev 金鑰一起刪除
```

只會移除 MRH 自己建立的東西；其他 Hook、設定，以及 shell 設定檔裡的其他內容都會保留。

**Windows**：目前只有手動步驟（還沒在 Windows 實機驗證），見[移除說明](docs/install.md#移除)。

## 支援範圍

| 項目 | 說明 |
| --- | --- |
| macOS（Apple Silicon） | 支援。安裝器自備 Python 3.11。 |
| Windows（x64） | 支援。需自備 Python 3.11 以上。 |
| Linux、WSL、Intel Mac | 不支援。 |
| Codex、Claude Code | Mac Claude Code 需 2.1.296 以上；Windows Claude 路由仍待隔離清單驗證，不能視為已可用。 |
| Gemini | 尚未支援。 |

已驗證的版本與已知限制見[平台與相容性](docs/compatibility.md)。

## 更多文件

- [安裝教學](docs/install.md)：完整步驟、更新、退版與移除。
- [設定與日常操作](docs/usage.md)：模型、信心門檻、進階檔位、Jev 版本與統計。
- [疑難排解](docs/troubleshooting.md)：找不到 mrh、尚未啟用、信任與模型清單問題。
- [全部文件](docs/README.md)

## 授權

[MIT License](LICENSE)：可自由使用、修改、散布與商用，請保留授權與著作權聲明。第三方 runtime 的授權見 [LICENSES](packaging/macos-arm64/LICENSES.md)。
