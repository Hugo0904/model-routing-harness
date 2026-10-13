# Model Routing Harness（MRH）

**Route the task, not the session.** 主模型要派子代理時，MRH 先請一個便宜的「分級器」判斷這件工作多難（Light／Small／Mid／Top），再把你為該等級設定的模型清單**以建議的方式**交回主模型；由主模型自己挑、自己重派。做不到就由主模型繼續做。

```
主模型要派子代理 ─▶ Hook ─▶ 分級器（Jev／Codex 訂閱／Claude 訂閱）─▶ 等級＋信心度
      ▲                                                              │
      └──── 建議：「請改用 haiku／gpt-5.6-luna:low…，否則自己做」 ◀───┘
```

- 是**建議**，不是強制改寫。主模型沒有照做，MRH 不會再攔第二次（同一任務只建議一次）。
- 你或主模型已經明確指定模型、推理強度或專門角色 → 一律尊重，不分級。
- 分級失敗（沒額度、逾時、金鑰錯誤）→ 原呼叫照常放行，只提示一次原因。
- 不改任何廠商本體，只用各家原生 Hook。目前支援：**Codex**、**Claude Code**。Gemini CLI 只有模型清單，尚未接 Hook。

## 控制中心

所有設定都在一個地方：

```sh
mrh ctrl                     # 互動選單（方向鍵、Enter、← 返回、Esc 取消）
mrh ctrl show [--json]       # 目前設定一覽
mrh ctrl set KEY VALUE       # 腳本用；mrh ctrl keys 列出所有 KEY
mrh key status jev           # 金鑰狀態（只顯示有沒有，不顯示內容）
```

可設定：路由開關、分級器（Jev／Codex 訂閱／Claude 訂閱）與模型與逾時、四級各平台的候選模型（有序，可帶推理強度，如 `gpt-5.6-luna:low`）、Top 交回主模型（Main）或用固定清單（Fixed）、信心門檻（0.50–0.99）、生效資料夾（`/` 代表全部）。

## 分級器與費用

| 分級器 | 需要 | 費用 | 速度 |
|---|---|---|---|
| **Jev**（預設，TypeSafe） | TypeSafe API key（存 macOS Keychain） | 每百萬 input token $0.042、output 免費；一次分級約 440 token，**約 $0.02／千次** | 約 0.4 秒 |
| Codex 訂閱 | 已登入的 Codex CLI | 用訂閱額度 | 數秒 |
| Claude 訂閱 | 已登入的 Claude Code | 用訂閱額度 | 約 5–10 秒 |

Jev 回傳每一級的機率；訂閱分級的信心度是模型自評，沒有校準，兩者不等價。金鑰設定：

```sh
mrh key set jev      # 由 macOS 提示輸入，金鑰不經過 MRH、不進任何檔案
```

## 安裝（macOS arm64）

封裝內含私有 Python，不需另外安裝 SDK。安裝到固定位置（之後升級路徑不變，hook 不需重新信任）：

```sh
python3 scripts/packaging/build_standalone.py --cache build/e15-public-assets --output dist/<名稱> --archive dist/<名稱>.tar.gz
python3 scripts/packaging/install_local.py --bundle dist/<名稱> --settings <settings.json 絕對路徑>
#   → ~/.local/share/model-routing-harness/app、~/.local/bin/mrh、~/.config/model-routing-harness/active-settings
mrh plugin prepare --advisory --root <artifact 目錄> --settings <settings.json> --python ~/.local/share/model-routing-harness/app/runtime/bin/python3.11
# Codex：codex plugin marketplace add <artifact 目錄>（首次）→ codex plugin add model-routing-harness@model-routing-harness-local → Codex 內 /hooks 信任
mrh install claude --artifact <artifact 目錄>            # 只顯示差異
mrh install claude --artifact <artifact 目錄> --apply    # 套用（自動備份，保留其他 hook）
```

升級：重建封裝 → `install_local.py` → `mrh plugin prepare …`（同參數）→ `codex plugin add …`。hook 指令路徑不變，信任不失效。

預設**停用**。用 `mrh ctrl` 開啟；開啟代表把子代理任務文字送給你選的分級器。停用：`mrh ctrl set enabled off`；移除 Claude hook：`mrh install claude --artifact … --remove --apply`。

## 現況與誠實的限制

實測（單次樣本，見 `docs/evidence/`）：Jev 三個難度樣本全部分對；Claude Code（Sonnet 主模型）被建議後改派 haiku 子代理，Top 級由主模型自己完成。**不代表主模型長期遵從率**——要看統計：`mrh ctrl` → Statistics 的 `children_following_advice`。

- 設定檔 v2；舊 v1 讀取時自動遷移，第一次用 `mrh ctrl` 存檔時才改寫。
- **Codex 的限制**：Codex 0.159.3 把委派內文（`message`）加密後才交給 Hook，MRH 只能讀到主模型取的短標籤 `task_name`（如 `rename_variable`），分級依據較弱；含糊的標籤信心度低，會自動放行。Codex 主模型常帶 `agent_type: worker`，MRH 預設視同預設角色；你自訂的角色（如 `luna_worker`）一律不干預（`mrh ctrl set generic_roles.codex worker`）。
- Codex 實測 2 次，主模型收到建議後**都沒有改派建議的模型**（自己做完或回報被擋）；Claude Code 實測 1/1 有改派。尚未量到長期遵從率。
- Claude Code 的子代理 `effort` 參數需 2.1.292 以上，`haiku`／`sonnet` 別名要 2.1.293 以上才對應到 5.5 系列（Homebrew 請用 `claude-code@latest`）。
- Codex App（桌面版）未實測；Gemini CLI 未接 Hook。
- 舊的「強制改寫」路徑與其測試仍在 repo 內但新流程不使用，見 `docs/takeover/HANDOFF.md` 的可刪清單。

## 開發

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -t .      # 5 個已知舊失敗，見 docs/takeover/PLAN.md §15
```

需求與歷史：`REQUIREMENTS.md`、`docs/MRH-001.md`、舊版 README 在 `docs/README-legacy.md`。
