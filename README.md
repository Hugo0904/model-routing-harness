# Model Routing Harness

可離線安裝的 Python 3.11+ 路由核心與終端工具，MRH-001 **E2 本機候選**。真實 Jev API 尚未取得；沒有網路請求、正式 Hook 啟用或已驗證的主代理交回。完整基準與接受紀錄在 [REQUIREMENTS.md](REQUIREMENTS.md)、[docs/MRH-001.md](docs/MRH-001.md)。

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

`mrh hook` 讀 stdin JSON、只輸出 Hook JSON，預設 `{}` 原樣放行。`--candidate --db ...` 可記錄委派，但 production classifier 不可用，沒有有效分級就不改寫原呼叫。隔離合成需另加 `--simulate-tier Top --simulate-confidence 0.9`、`--candidate` 與明確 `--db`；不是正式 Jev 請求。

```sh
mrh config --home /absolute/explicit-codex-home --command /absolute/path/to/mrh
mrh config --home /absolute/explicit-codex-home --command /absolute/path/to/mrh --action disable
```

這些是零寫入預覽，不顯示其他工具的命令內容。**公開 `--apply` 安裝與停用目前一律拒寫**，回 `exclusive_target_unverified`／非零 exit。尚無保護共享設定免受非合作編輯器覆寫的宿主交易契約；額外 hash／MRH lock 不能取代它。沒有 force／unsafe，不改信任、安全權限或主模型。

只有開發／測試 `SyntheticHome()` helper 能自行建立並持有 private TemporaryDirectory、在 fixture 內套用／停用候選。它不接受既有 home；同 helper 的合作呼叫全程序列化，非合作 writer race 仍是限制反例。TOML hooks、ownership 歧義、格式錯誤、symlink 或來源變更皆拒絕。真正 S4 安裝／停用仍未完成。

## 支援狀態

| 項目 | E2 結果 |
|---|---|
| 共用核心、信心度／顯式模型／Top 政策、冪等紀錄、CLI/JSON | 已實作，隔離本機驗證 |
| Codex Hook JSON、Main deny／Fixed rewrite | 候選序列化已測；真實宿主／主代理續作／型號未驗證 |
| 安裝預覽 | 可用；共享 home 安裝／停用拒寫，未支援 |
| 真 Jev、後續真 Goal 委派 | 不可用／未驗證 |
| Claude Code、Gemini CLI | 未支援，只有盤點與接頭差異文件 |
| Canopy／Monitor | 選配契約與合成例；未串接、未修改既有專案 |
| tokens／cost／quota／實測節省 | 不可取得；不從次數或模型名推算 |

API、政策、收據與統計出口見 [資料契約](docs/contracts.md)、[合成設定](examples/synthetic-policy.json)、[合成統計](examples/synthetic-stats.json)。這是本專案內部格式，不是 Jev 的已知 API。

## 驗證

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/verify_package.py
```

前者驗證 E2 核心→Hook 候選→SQLite→CLI/JSON 與 fixture 安裝鏈。後者在暫存 venv 離線安裝，驗證 entrypoints、JSON 一致與 80／28 欄終端輸出後清除 runtime。結果見 [E2 證據](docs/evidence/e2-verification.json)，[80 欄](docs/evidence/e2-terminal-80.txt)／[28 欄](docs/evidence/e2-terminal-28.txt) 可供人工檢視。E1 來源仍在 [能力盤點](docs/capabilities.md)。
