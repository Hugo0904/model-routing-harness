<div align="center">

# Model Routing Harness（MRH）

**依子任務難度，建議合適的模型與推理強度。**

[![Version](https://img.shields.io/badge/version-0.4.0-2563eb)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Installer](https://img.shields.io/badge/installer-Windows_x64_%7C_macOS_arm64-111827)](docs/compatibility.md)
[![Python](https://img.shields.io/badge/macOS_Python-3.11.17-3776AB)](packaging/macos-arm64/runtime-lock.json)
[![Hosts](https://img.shields.io/badge/hosts-Codex_%7C_Claude_Code-0f766e)](docs/compatibility.md)

[交給 AI 安裝](#交給-ai-安裝) · [手動安裝](docs/install.md) · [常用指令](#常用指令) · [文件](docs/README.md)

</div>

## 交給 AI 安裝

把下面這段貼給能操作你電腦的 AI，例如 Codex 或 Claude Code：

```text
請依 repo 的 docs/install.md 幫我安裝 https://github.com/Hugo0904/model-routing-harness 。先辨識作業系統、Codex／Claude Code／兩者，以及允許任務外送的範圍；保留既有設定、金鑰、統計、skill 和其他 Hook。金鑰、登入與原生信任由我操作，取得外送同意後才啟用支援的宿主。安裝器自動處理支援的使用者 PATH，不覆蓋其他 PATH 項目或同名命令；說明既有程序需要如何取得新環境。最後依平台執行 --check --json，並切到一般資料夾確認命令解析後實際執行 mrh status。分開回報安裝、命令可用性、Hook 信任與未做的實測，未支援功能保持停用。MRH 完成後詢問我是否安裝對應平台的選配派工 skill，明確同意才裝，沒有答覆就不裝。
```

提供 **Windows x64 原生安裝器**與 **macOS Apple Silicon（M 系列）安裝流程**。Windows 的安裝／Hook 接入與真正的 Jev 分類、子代理採用是不同驗證；Claude 模型清單等限制見 [相容性](docs/compatibility.md)。登入、金鑰輸入和原生信任確認仍需你操作。

## 交給 AI 更新

```text
請依目前 checkout 的 docs/install.md 更新 MRH。先辨識系統、已安裝的宿主與安裝參數，保留未提交修改、設定、金鑰、統計、實驗資料、既有 skill 及其他 Hook；有來源或同名命令衝突就具體回報，不覆蓋。確認工作樹可更新後取得更新、重跑原安裝入口，依指南完成 --check --json，從一般資料夾確認命令解析並執行 mrh status。安裝器自動處理支援的使用者 PATH，確認更新不重複加入；既有終端或啟動它的應用程式仍持有舊環境時，說明需要重開的程序。不要為更新重裝派工 skill、改原外送範圍或額外呼叫模型；分開回報已完成與尚未驗證的項目。
```

## 手動安裝

從下載程式、取得 Jev 金鑰，到選模型與啟用工作區，照著 [手動安裝教學](docs/install.md) 操作。Windows 需先有 Git 與原生 x64 Python 3.11 以上；Mac 安裝器會處理自己的 Python。兩者都不需要 Jev SDK 或 WSL。

## 可以做什麼

- 用 Jev 將子任務分成 Light／Small／Mid／Top，建議對應模型與推理強度。
- 用 `mrh ctrl` 調整各級模型、信心門檻與適用資料夾；Top 可交回主 AI 處理。
- 查看分級、派工、已觀測採用與用量統計。
- 更新時保留設定、金鑰與統計；支援退回上一個相容版本。

主 AI 保留最後決定權，主聊天的模型不會被切換。你明確指定的模型與角色優先。新安裝預設停用，完成設定並允許外送任務後才啟用。

## 版本與相容性

| 元件 | 版本與範圍 |
| --- | --- |
| MRH | 0.4.0，採 MIT 授權。 |
| Windows Python | 使用本機既有的原生 x64 CPython ≥ 3.11，複製為私有 runtime 並檢查雜湊；不下載 Python。 |
| Mac 內附 Python | 3.11.17，沿用既有 arm64 runtime lock。 |
| Windows 宿主觀測 | Codex 0.163.0-alpha.10.2、Claude Code 2.1.303；已安裝／登入不等於路由實測完成。 |
| Mac 宿主既有驗證 | Codex 0.162.1、Claude Code 2.1.296；Claude 最低 2.1.296，新版清單未知可手動設定，未以 Mac 實機重驗。 |
| Jev | 預設 `jev-latest`，可改用預覽版或固定版本。 |

完整範圍見 [平台與相容性](docs/compatibility.md)。Gemini 目前只有模型清單接頭，尚不支援安裝與自動路由。

## 常用指令

| 指令 | 用途 |
| --- | --- |
| `mrh ctrl` | 開啟設定選單。 |
| `mrh key status jev` | 確認 Jev 金鑰是否已設定，不顯示內容。 |
| `mrh status --json` | 查看目前狀態。 |
| `mrh stats` | 查看統計。 |
| `mrh usage collect` | 收集本機子代理用量，不呼叫模型。 |
| `mrh ctrl set enabled off` | 停用路由。 |
| `mrh cleanup` / `mrh cleanup --apply` | 預覽／清除可丟棄暫存與快取，不動設定、統計與實驗資料。 |
| `mrh skill status --host codex` | 查看選配派工 skill；Claude 改用 `--host claude`。 |

安裝器自動處理支援的使用者 PATH，不依賴特定終端品牌。安裝與更新最後都要在取得新環境的程序中，從一般資料夾確認 `mrh status` 可直接執行。絕對路徑只供排查，不代替這項檢查，詳見[安裝教學](docs/install.md)。用量換算不是帳單，也不代表已證明節省費用。

## 選配派工 skill

需要 AI 主動分配合適子任務時，可自行選擇安裝；`setup` 不會自動安裝，也不改你的既有 Router 或其他 skill：

```sh
mrh skill install --host codex
mrh skill install --host claude
```

只執行自己選用的平台；查看、更新與移除規則見[選配派工 skill](docs/delegation-skills.md)。Windows 不支援 Codex 完整任務 packet，安裝社群 skill 不會增加該能力。

## 進一步設定

- [設定與日常操作](docs/usage.md)：模型、信心門檻、進階檔位、Jev 版本與統計。
- [Codex 完整任務分類](docs/codex/packet-skill.md)：讓分類使用完整任務內容，需明確選配。
- [疑難排解](docs/troubleshooting.md)：尚未啟用、信任與模型清單問題。
- [驗證摘要](docs/validation.md) · [開發指南](docs/development.md) · [全部文件](docs/README.md)

## 授權

本專案採用 [MIT License](LICENSE)，允許使用、修改、散布與商用，須保留授權及著作權聲明。Mac 第三方 runtime 的授權見 [LICENSES](packaging/macos-arm64/LICENSES.md)；Windows 私有 runtime 保留來源 Python 的 `LICENSE.txt` 與隨附聲明。
