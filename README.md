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

建置與封裝見 `scripts/packaging/build_standalone.py`；封裝內含私有 Python，不需另外安裝 SDK。

```sh
B=/path/to/model-routing-harness-0.4.0-macos-arm64
$B/mrh plugin prepare --advisory --root <artifact 目錄> --settings <settings.json 路徑> --python $B/runtime/bin/python3.11
# Codex：codex plugin marketplace add <artifact 目錄> → codex plugin add model-routing-harness@model-routing-harness-local → 在 Codex 輸入 /hooks 信任
# Claude Code：先看差異，確認後再套用（會備份原檔，保留你其他 hook）
$B/mrh install claude --artifact <artifact 目錄>            # 只顯示差異
$B/mrh install claude --artifact <artifact 目錄> --apply
```

預設**停用**。用 `mrh ctrl` 開啟；開啟代表把子代理任務文字送給你選的分級器。停用：`mrh ctrl set enabled off`；移除 Claude hook：`mrh install claude --artifact … --remove --apply`。

## 現況與誠實的限制

實測（單次樣本，見 `docs/evidence/`）：Jev 三個難度樣本全部分對；Claude Code（Sonnet 主模型）被建議後改派 haiku 子代理，Top 級由主模型自己完成。**不代表主模型長期遵從率**——要看統計：`mrh ctrl` → Statistics 的 `children_following_advice`。

- 設定檔 v2；舊 v1 讀取時自動遷移，第一次用 `mrh ctrl` 存檔時才改寫。
- Codex App（桌面版）未實測；Gemini CLI 未接 Hook。
- 舊的「強制改寫」路徑與其測試仍在 repo 內但新流程不使用，見 `docs/takeover/HANDOFF.md` 的可刪清單。

## 開發

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -t .      # 5 個已知舊失敗，見 docs/takeover/PLAN.md §15
```

需求與歷史：`REQUIREMENTS.md`、`docs/MRH-001.md`、舊版 README 在 `docs/README-legacy.md`。
