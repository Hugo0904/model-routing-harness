# Model Routing Harness

可離線安裝的 Python 3.11+ 路由核心與終端工具，MRH-001 **E6 本機候選 0.3.0**。已有自有 plugin bundle、公開設定與既有 TypeSafe `jev-1.13.0` factory 接線，預設關閉；E5 的兩版原生 CLI 隔離安裝證據仍適用安裝機制。E6 改用同一次委派的各項事實，分別判斷 Main／Fixed／一般路由資格；新版封裝只做離線入口回放。正式宿主仍缺必要事實契約，因此實際路由尚未就緒；真 API、正式 Hook 與主代理自主交回仍未驗證。完整基準與接受紀錄在 [REQUIREMENTS.md](REQUIREMENTS.md)、[docs/MRH-001.md](docs/MRH-001.md)。

## 使用

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

`demo` 明確使用合成分級，冪等且不呼叫 provider。普通 stats 排除合成資料；重複查詢不記錄事件。TTY 有顏色與組成條；`--plain`／`NO_COLOR` 可停用，JSON 不含裝飾。預設 DB 是 `~/.local/state/model-routing-harness/events.sqlite3`；測試／demo 建議顯式指定暫存 DB。help／doctor／預覽不建立 DB、不探查網路或憑證。

## Hook 與安裝界線

`mrh hook` 讀 stdin JSON、只輸出 Hook JSON，預設 `{}` 原樣放行。`--candidate --db ...` 可記錄委派，CLI 仍不啟用 TypeSafe，沒有有效分級就不改寫原呼叫。隔離合成需另加 `--simulate-tier Top --simulate-confidence 0.9`、`--candidate` 與明確 `--db`；不是正式 Jev 請求。

TypeSafe 的固定 HTTPS API、雙重啟用／task 外送權限與 runtime credential resolver 見 [資料契約](docs/contracts.md)。[完整公開設定](examples/settings-disabled.json) 不含 key，載入不讀憑證；E5 的 `settings` 指令與 `hook --settings` 共用同一 reader／factory，再加 operator 指定的 workspace 範圍。政策不等於已驗證宿主能力。普通 tier 成本使用原委派解析後的 model/effort；未知就保留。Jev reported tokens/model 與 child actual model 分開，價格只標為估算。

新路徑與安裝／停用指南見 [E5 證據與設定](docs/e5-settings-plugin-proof.md)。`mrh plugin prepare` 只準備 fresh 或可驗證的 MRH 自有 bundle；native registration／trust 要另以原生 CLI／UI 完成，不能把 prepared 視為 installed。正式 resolver 只讀 Hook 提供的 model／cwd／correlation metadata，角色保護等必要事實保持 unknown，記 `missing_role_protection` 並保留原呼叫；不讀 key 或呼叫 Jev。[E6 事實與支援邊界](docs/e6-action-facts-proof.md) 列出精確版本缺口。

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
| Codex Hook JSON、Main deny／Fixed rewrite | 已於兩個安裝版app-server，以native v1＋腳本provider驗取消／改寫；Desktop UI／真型號／自主接回未驗證 |
| 安裝與停用 | 舊共享 hooks.json apply／disable 維持拒寫；新自有 bundle 可準備，兩版 stable native CLI 安裝／trust／移除僅在隔離 home 驗證；正式 home 未修改 |
| TypeSafe Jev 接頭與公開設定 | default-off settings→既有真 factory→HTTP 替身驗證；雙 gate／workspace 範圍與自有 disable 可用；正式 Main／Fixed／一般路由缺同次委派事實而未支援，真 API 未驗證 |
| 後續真 Goal 委派 | 兩個安裝版 app-server 的同一隔離 Goal 跨兩個 harness 發起回合均重新分級；自主 Goal 續跑未驗證 |
| Claude Code、Gemini CLI | 未支援，只有盤點與接頭差異文件 |
| Canopy／Monitor | 選配契約與合成例；未串接、未修改既有專案 |
| Jev tokens／估算 | 可保存有效 usage；E3 只有 synthetic；未知保持 null，匹配版本才估算 |
| child tokens／cost／quota／實測節省 | 不可取得；不從次數或模型名推算 |

政策、收據與 v2 統計見 [資料契約](docs/contracts.md)、[合成設定](examples/synthetic-policy.json)、[合成統計](examples/synthetic-stats.json)、[含 Jev 離線 transport 的合成統計](examples/synthetic-provider-stats.json)。這些統計是 MRH 格式，TypeSafe wire 格式另依官方 API。

## 驗證

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/verify_package.py --evidence-prefix e3
```

前者驗證核心→Hook→SQLite→CLI/JSON、TypeSafe fake transport、deadline/lifecycle/migration 與 fixture 安裝。後者在暫存 venv 離線安裝，驗證兩個 entrypoints、新 telemetry JSON 一致與 80／28 欄輸出後清除 runtime。結果見 [E3 證據](docs/evidence/e3-verification.json)，[80 欄](docs/evidence/e3-terminal-80.txt)／[28 欄](docs/evidence/e3-terminal-28.txt)。E1 [盤點](docs/capabilities.md) 與 [E2 證據](docs/evidence/e2-verification.json) 保留為歷史證據，不能當真 API／宿主驗收。

後續 [E4 installed-host證據](docs/e4-host-proof.md) 與 [E4G Goal 證據](docs/e4g-goal-and-plugin-proof.md) 區分 shell 與 Desktop-bundled runtime，均沒有正式啟用。[E5](docs/e5-settings-plugin-proof.md) 已補上兩版的隔離 native plugin／installed entry／第三方 Hook 共存證據與 34 項聚焦檢查；設定接線用 true factory＋合成 HTTP/context，正式 host resolution 仍缺契約。沒有重跑既有 Goal、全部核心或真 provider 測試。歷史審查拒絕與完整 R1 接受狀態保留在任務記錄。

[E5R 記錄修正](docs/e5r-accounting-proof.md) 讓通過原 gate 的 explicit／unknown preserve 也留下 proposal／outcome，Post 不再查新的 host 能力即可關聯收據；分類、key 與 HTTP 仍為零。新版 archive 回放證據與 E5 舊 native-installed hash 分開，未重跑原生 lifecycle 或 Goal。

[E6](docs/e6-action-facts-proof.md) 移除整份 configuration_known 門檻：Main 只需角色未受保護與可 deny；Fixed 另需 rewrite、目標模型及有效 effort 相容；一般等級另需原委派基準與保守成本資料。沒有任何可合法執行的分支時，先保留並略過 context／Jev／key／HTTP。只有程序內可信 adapter 或明確 synthetic fixture 可建立 typed facts；設定與任務內容無法自報 known。兩個安裝版本的公開契約缺口已確認並停止搜尋，完整 R1 仍未完成。
