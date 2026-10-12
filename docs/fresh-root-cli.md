# 日常 CLI 的有限接入

此接入使用現有 ChatGPT 登入與官方 Codex CLI 0.159.3。準備 profile 不代表已有有效 session：只有原生 `SessionStart` 的 `startup`，連同實際 CLI 程序、出生時間、執行檔、home 與設定來源驗證成功，才提供 `fresh-root-cli-configuration` 保證。它是有官方來源依據的設定保證；目前模型取自當次 Hook，未宣稱直接讀到子代理 resolver。

用 standalone 的 `mrh plugin prepare --root <獨立 artifact 目錄> --settings <獨立 settings.json> --scope-contract fresh-root-cli --scope-workspace <起始工作區> --codex-binary <官方原生執行檔>` 明確選用。省略此新選項時，既有 pinned 契約維持原樣。使用 normal `CODEX_HOME`，由官方 `plugin marketplace add`、`plugin add` 及啟動時 Hook review 安裝／信任，只新增 MRH；準備結果列出原生指令。信任 review 修改設定後，請關閉該 session，再開全新的 CLI。

日常開啟方式為 `codex --no-daemon --no-alt-screen -C <絕對工作區>`。不加啟動模型、profile、config 或其他未知參數；進入 session 後才輸入任務。此設定只分類符合條件的普通委派，明確指定模型／推理強度或特殊角色會照原值執行。設定允許清單在每次新委派前重讀；`roots: ["/"]` 代表本機所有能確認 cwd 的檔案工作區，空清單代表全部停用。

沿用 E20 的四級選擇，未重新推定使用者偏好：

| 級別 | 目前選擇 |
|---|---|
| Light | gpt-5.6-luna / low |
| Small | gpt-5.6-luna / low |
| Mid | gpt-5.6-luna / low |
| Top | Main，留在原主代理 |

用 `mrh settings show --path <settings.json>` 讀回完整值；`mrh settings view --path <settings.json>` 查看畫面。既有四級方向鍵／Enter 編輯器可用 `mrh model <light|small|mid|top> --root <此 profile 的 model-bindings>`，第一次以 `--bind --associate-settings <settings.json>` 綁定，依畫面選用 Codex。也可保留完整 policy 後，用既有 `settings configure --policy <policy.json>` 更新；不得只為測試路由而刪除保護值或修改階級。

沿用的成本表目前只有 gpt-6.1-sol 和 gpt-5.6-luna。若當次主模型不在成本表，較便宜子代理的比較會保留原委派並顯示 `cost_unknown`；這不表示分類器沒執行，也不表示已節省額度。模型清單支援與帳號實際可用性分開處理。

設定或角色檔案必須早於 CLI 出生，且每次委派與決策前再次驗證。檢查涵蓋 inode/device/ctime、內容、無 symlink、遞迴角色目錄／引用、名稱 trim、目錄成員及缺失路徑；搬入舊目錄、改完再還原或移除後重建均不能在同一 session 重新建立基準。必要祖先或缺失路徑的變更也可能保守失效，需重新開 CLI。一般 project MCP 設定可接受；未知 layer、provider/catalog、default-role/default-child override 則保留原委派。

resume/fork/compact/clear、exec、daemon、App/app-server、巢狀 session、外來執行檔／home／PID 或無法確認的來源不提供此保證。SessionStart 不呼叫分類器、不建立模型嘗試統計。App 的日常接入仍待完成。

停用方法：`mrh settings disable --path <settings.json>`。移除只有 `codex plugin remove model-routing-harness@model-routing-harness-local --json`；獨立的 profile、證據及其他 Hook 保留，不還原整個 home、不登出。
