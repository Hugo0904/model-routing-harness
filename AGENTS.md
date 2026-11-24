# MRH 維護規範

開發方式、目錄責任與測試指令見 [docs/development.md](docs/development.md)，這裡不重複。

- **推送前在本機跑發佈檢查，結果要是 0 項**：`python3 -B scripts/release_check.py`。GitHub Actions（`.github/workflows/release-check.yml`）在 push 與 pull request 時跑同一支，但只回報、不擋；直接進 `main` 時它是推上去之後才跑，所以本機這一道要確實跑。
- **`plugins/mrh/` 是凍結的。** Codex 對 Hook 的信任涵蓋整個資料夾：改任何一個檔、多一個空資料夾或 `.DS_Store`、只調版本號，都會讓所有 Codex 使用者的 MRH Hook 停到他們重新審查為止，而且推上預設分支就生效，不必等發版。非改不可時三件事一起做：調外掛版本（兩份清單與 `.claude-plugin/marketplace.json`）、用 `python3 -B scripts/release_check.py --write-plugin-lock` 更新 `packaging/plugin-lock.json`、在變更說明寫「Codex 使用者要重新信任」。外掛版本和程式版本（`pyproject.toml`）是分開的兩個號碼。
- **不提交個人內容**：個人路徑、帳號名、email、SSH 形式的 GitHub 位址、金鑰、原始宿主紀錄都不進版控。確實該留的命中（第三方授權原文、去識別化 fixture 的佔位路徑）逐筆登記在 `scripts/release_check_allow.json` 並寫原因，不整檔或整個資料夾放行。
