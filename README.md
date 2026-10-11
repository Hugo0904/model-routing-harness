# Model Routing Harness

子代理任務分級器與終端工具，現有獨立套件為 **E19／0.3.0**。使用 Codex ChatGPT 訂閱分級，不要求 API key；舊 TypeSafe profile 保留。A 已驗收原生普通切換、Fixed 較高 configured child／結果與同 Goal 跨回合重新分級；A 也已接受 Luna parent 的真 Top Main 拒絕、無 child 與同 parent 完成。完整 R1、Desktop／正式全域採用與自主 Goal 續跑保持未驗證。

Mac arm64 可直接執行：

```sh
/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.3.0-e19-macos-arm64/mrh --help
```

[啟用與停用的精確指令](docs/quickstart.md)使用已登入保留的 `/private/tmp/mrh-e19-d45-mrc5zw54` home、同一 `state/settings.json` 與 model registry。套件自帶 Python，不需安裝 SDK。MRH 目前 disabled／外送 denied；普通模型、Top Main／Fixed 可用方向鍵與 Enter 設定，保存前核對最新清單，取消保留舊政策。設定保存不會自動啟用路由。

[本次真實證據與限制](docs/e19-subscription-classifier.md)分清 CLI usage、configured model、provider identity、Main／Fixed／Goal 與剩餘義務。模型清單支援不等於 Claude／Gemini 路由已接通。完整需求與 A 接受紀錄維持在 [REQUIREMENTS.md](REQUIREMENTS.md)、[docs/MRH-001.md](docs/MRH-001.md)。以下開發與歷史證據保留其原本來源，不視為新版真實驗收。

## 直接執行視覺 Demo

不需安裝套件，使用本機 Python 3.11+：

```sh
/Users/shawn/Code/model-routing-harness/demo --color --width 120
```

畫面依使用者參考圖重做為石墨灰／紫色的終端儀表板，含四段流程、tier 表格、組成條與用量面板。窄視窗改用直向排列；`--details` 保留完整紀錄，`--json` 維持原始資料。`demo` 未指定 `--db` 時自動建立並清除暫存資料庫，不寫入正式統計、不呼叫模型或 API。一般使用可省略 `--color`／`--width` 讓終端自動選擇。

[120 欄實際終端截圖](docs/evidence/cli-demo-wide.jpg) · [56 欄實際終端截圖](docs/evidence/cli-demo-narrow.jpg) · [驗證與限制](docs/cli-visual-proof.md)。截圖為真實 PTY 輸出在 xterm.js 的呈現；不是 macOS Terminal 截圖。終端字型與真彩色支援會影響外觀。

## 使用

E7 另提供[隔離 Codex source 匯出實驗](docs/e7-host-export-proof.md)：以固定版本的實際 resolver 產生唯讀委派事實，再接入 MRH 合成回放。Patch、來源版本與重現方法均留在本專案；已安裝的 Codex 與正式 resolver 沒有啟用這個入口，完整 R1 仍未完成。

安裝到自行選擇的虛擬環境；不需要 build dependency 或 provider 憑證：

```sh
python3 -m venv /private/tmp/mrh-venv
/private/tmp/mrh-venv/bin/python -m pip install --no-index --no-deps --no-build-isolation /Users/shawn/Code/model-routing-harness
/private/tmp/mrh-venv/bin/mrh doctor --plain
```

同一介面也可用 `python -m mrh`，開發時使用 `PYTHONPATH=src python3 -m mrh`。

```sh
mrh demo --db /private/tmp/mrh-demo.sqlite3 --json
mrh stats --db /private/tmp/mrh-demo.sqlite3 --synthetic --plain
mrh stats --db /private/tmp/mrh-demo.sqlite3 --json
mrh status --db /private/tmp/mrh-demo.sqlite3 --synthetic --width 28
```

`demo` 明確使用合成分級，冪等且不呼叫 provider。普通 stats 排除合成資料；重複查詢不記錄事件。TTY 有顏色與組成條；`--plain`／`NO_COLOR` 可停用，JSON 不含裝飾。一般指令的預設 DB 是 `~/.local/state/model-routing-harness/events.sqlite3`；demo 未指定 `--db` 時使用自動清除的暫存 DB。help／doctor／預覽不建立 DB、不探查網路或憑證。

## Hook 與安裝界線

`mrh hook` 讀 stdin JSON、只輸出 Hook JSON，預設 `{}` 原樣放行。`--candidate --db ...` 可記錄委派，CLI 仍不啟用 TypeSafe，沒有有效分級就不改寫原呼叫。隔離合成需另加 `--simulate-tier Top --simulate-confidence 0.9`、`--candidate` 與明確 `--db`；不是正式 Jev 請求。

TypeSafe 的固定 HTTPS API、雙重啟用／task 外送權限與 runtime credential resolver 見 [資料契約](docs/contracts.md)。[完整公開設定](examples/settings-disabled.json) 不含 key，載入不讀憑證；E5 的 `settings` 指令與 `hook --settings` 共用同一 reader／factory，再加 operator 指定的 workspace 範圍。政策不等於已驗證宿主能力。普通 tier 成本使用原委派解析後的 model/effort；未知就保留。Jev reported tokens/model 與 child actual model 分開，價格只標為估算。

新路徑與安裝／停用指南見 [E5 證據與設定](docs/e5-settings-plugin-proof.md)。`mrh plugin prepare` 只準備 fresh 或可驗證的 MRH 自有 bundle；native registration／trust 要另以原生 CLI／UI 完成，不能把 prepared 視為 installed。未準備 configuration scope 的舊 resolver 只讀 Hook 提供的 metadata，必要事實 unknown 時保留原呼叫；已驗證的 pinned CLI 入口另外使用 E17R/E19 scope binding，不把 configuration assurance 說成同 call 的直接觀察。[E6 事實與支援邊界](docs/e6-action-facts-proof.md) 列出精確版本缺口。

```sh
mrh config --home /absolute/explicit-codex-home --command /absolute/path/to/mrh
mrh config --home /absolute/explicit-codex-home --command /absolute/path/to/mrh --action disable
```

這些是零寫入預覽，不顯示其他工具的命令內容。**公開 `--apply` 安裝與停用目前一律拒寫**，回 `exclusive_target_unverified`／非零 exit。尚無保護共享設定免受非合作編輯器覆寫的宿主交易契約；額外 hash／MRH lock 不能取代它。沒有 force／unsafe，不改信任、安全權限或主模型。

只有開發／測試 `SyntheticHome()` helper 能自行建立並持有 private TemporaryDirectory、在 fixture 內套用／停用候選。它不接受既有 home；同 helper 的合作呼叫全程序列化，非合作 writer race 仍是限制反例。TOML hooks、ownership 歧義、格式錯誤、symlink 或來源變更皆拒絕。這是舊共享 hooks.json 路徑的限制；新自有 bundle／native CLI 路徑的隔離證據與正式 readiness 邊界見 E5。

## 支援狀態

| 項目 | 目前證據 |
|---|---|
| 共用核心、信心度／顯式模型／Top 政策、冪等紀錄、CLI/JSON | 已實作；E6 每個分支的最小事實及負例經合成 core／公開入口驗證 |
| Codex Hook／native 控制 | ordinary／Fixed 的 configured child／結果已由 A 驗收；D48 真 Main Top/0.99 native blocked／no-child／同 Luna parent 完成已由 A 驗收。E17R 保護證據沿用，Desktop／自主排程未驗證 |
| 安裝與停用 | 舊共享 hooks.json apply／disable 維持拒寫；新自有 bundle 可準備，兩版 stable native CLI 安裝／trust／移除僅在隔離 home 驗證；正式 home 未修改 |
| 分級來源與公開設定 | 新設定使用 Codex 訂閱；真 ordinary 切換與 Goal fresh classification 已觀察。舊 TypeSafe factory／HTTP 替身及 settings 保留，真 Jev API 未驗證，沒有自動 fallback |
| 後續真 Goal 委派 | D47 同一官方 Goal 的兩個 harness 回合各有新訂閱分級與完成結果，Goal 完成及 clear 讀回；自主排程未驗證。原 E4G 腳本 lifecycle 證據保留 |
| Claude Code | macOS 2.1.267 的 CLI 宣告模型／推理選單已驗收，無 SDK 使用前提；路由接頭與帳號可用性未驗證，詳見 [E13](docs/e13-claude-catalog.md) |
| Gemini CLI | macOS 0.63.0 的 CLI 宣告模型清單與 inherit 選單已驗收；支援同一設定的 CLI 更新確認，帳號可用性及路由接頭未驗證，詳見 [E16](docs/e16-gemini-catalog.md)／[E16R](docs/e16r-cli-update.md) |
| Canopy／Monitor | 選配契約與合成例；未串接、未修改既有專案 |
| Jev tokens／估算 | 可保存有效 usage；E3 只有 synthetic；未知保持 null，匹配版本才估算 |
| native usage／cost／quota／節省 | 本次公開 native／classifier usage 可得部分已保存；未知費用、quota、provider 身分與節省不從模型名推算 |

政策、收據與 v2 統計見 [資料契約](docs/contracts.md)、[合成設定](examples/synthetic-policy.json)、[合成統計](examples/synthetic-stats.json)、[含 Jev 離線 transport 的合成統計](examples/synthetic-provider-stats.json)。這些統計是 MRH 格式，TypeSafe wire 格式另依官方 API。

## 開發結構與驗證

程式依責任分成 `routing`、`application`、`adapters`、`infrastructure`、`presentation`，測試與開發腳本也按用途放在子目錄。命令入口仍是 `mrh`／`python -m mrh`；root `mrh.cli:main` 保留，內部 imports 使用新套件路徑。對照見[結構搬移與打包交接](docs/architecture-migration.md)。現有啟用指令仍指已接受的 E19 套件，直到 B 交付整合後的新版本；登入、session 與設定不需重建。

依變更選必要 case；以下是開發工具入口，不代表每次都要跑整個 suite 或重做歷史驗收：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
python3 scripts/verification/packaging/verify_package.py --evidence-prefix local-migration-check
```

前者驗證核心→Hook→SQLite→CLI/JSON、TypeSafe fake transport、deadline/lifecycle/migration 與 fixture 安裝。後者在暫存 venv 離線安裝，驗證兩個 entrypoints、新 telemetry JSON 一致與 80／28 欄輸出後清除 runtime。另選新 evidence prefix，避免覆蓋歷史成果。原結果見 [E3 證據](docs/evidence/e3-verification.json)，[80 欄](docs/evidence/e3-terminal-80.txt)／[28 欄](docs/evidence/e3-terminal-28.txt)。E1 [盤點](docs/capabilities.md) 與 [E2 證據](docs/evidence/e2-verification.json) 保留為歷史證據，不能當真 API／宿主驗收。

後續 [E4 installed-host證據](docs/e4-host-proof.md) 與 [E4G Goal 證據](docs/e4g-goal-and-plugin-proof.md) 區分 shell 與 Desktop-bundled runtime，均沒有正式啟用。[E5](docs/e5-settings-plugin-proof.md) 已補上兩版的隔離 native plugin／installed entry／第三方 Hook 共存證據與 34 項聚焦檢查；設定接線用 true factory＋合成 HTTP/context，正式 host resolution 仍缺契約。沒有重跑既有 Goal、全部核心或真 provider 測試。歷史審查拒絕與完整 R1 接受狀態保留在任務記錄。

[E5R 記錄修正](docs/e5r-accounting-proof.md) 讓通過原 gate 的 explicit／unknown preserve 也留下 proposal／outcome，Post 不再查新的 host 能力即可關聯收據；分類、key 與 HTTP 仍為零。新版 archive 回放證據與 E5 舊 native-installed hash 分開，未重跑原生 lifecycle 或 Goal。

[E6](docs/e6-action-facts-proof.md) 移除整份 configuration_known 門檻：Main 只需角色未受保護與可 deny；Fixed 另需 rewrite、目標模型及有效 effort 相容；一般等級另需原委派基準與保守成本資料。沒有任何可合法執行的分支時，先保留並略過 context／Jev／key／HTTP。只有程序內可信 adapter 或明確 synthetic fixture 可建立 typed facts；設定與任務內容無法自報 known。兩個安裝版本的公開契約缺口已確認並停止搜尋，完整 R1 仍未完成。
