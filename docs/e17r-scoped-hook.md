# E17R：null 分級設定與啟動覆寫保護

D38 的兩項直接使用缺陷已修正。省略與 JSON null effort 現在都採用既有 tier mapping；非 null 明示模型／effort 仍在 Jev 前略過。null 下不相容的已選 effort 仍走 D23 stop，cached replay 也不清掉 stop。完整原參數保留，成功改寫只替換允許的 model/effort。

啟動檢查改為 pin 版本的有限 allowlist。split／equals／attached config/profile/model/feature/provider/remote 覆寫及未知衝突都拒絕，包含 `--config=...`、`-cVALUE`、`--profile=...`、`-pNAME`、`--model=...`、`-mMODEL`、`--enable=...`、`--disable=...`、`--oss`、`--local-provider=...`。它不冒充完整 Codex parser；public help/parser 只在 owned HOME 中確認，沒有開 session、讀 auth 或呼叫 provider。

## 實際可用的 interactive 啟動方式

使用本候選已核的官方 native **codex-cli 0.159.3**。保持 prepare 时選定的 CODEX_HOME 和 canonical workspace：

```sh
codex --no-daemon --no-alt-screen -C /absolute/workspace
```

**需要 `--no-daemon`**，因為預設 CLI 可連到既有共享 daemon，其啟動設定不屬於這個已核範圍。先進 TUI，再照平常方式輸入 prompt／plan／Goal；不在啟動 argv 傳 initial prompt、model、profile、config 或其他未支援 options。`--cd=/absolute/workspace` 和 attached `-C/absolute/workspace` 是等價的已支援 cwd 形式。

已測的自有 native chain 使用 `codex app-server --listen stdio://`；`--listen=stdio://` 亦經 startup check 接受。這不是要求一般使用者建立 gateway。Default daemon、remote、resume/fork、Desktop 或未知版本沒有因此升格為支援；不改或替換其 Codex，也不指示 AI patch host。

## 準備、權限與撤回

正常使用仍是同一 MRH entry 和 plugin 生命周期，不需要另裝 MRH Python／SDK／bridge。以下是操作方法，B 沒有對人類正式環境執行 enable、註冊、取 key 或外送。

```sh
mrh plugin prepare --root /absolute/mrh-plugin --settings /absolute/mrh-state/settings.json --scope-workspace /absolute/workspace
mrh plugin show --root /absolute/mrh-plugin
codex --no-daemon plugin marketplace add /absolute/mrh-plugin --json
codex --no-daemon plugin add model-routing-harness@model-routing-harness-local --json
codex --no-daemon plugin list --json
```

Prepare 自動檢查 compatibility，保留 disabled/export 狀態；還須透過官方 `/hooks` review/trust。`configuration_scope` 讀回是 inspected configuration，不是當次宿主 facts，也不表示準備完成就可取 key 分級。Scope 的模式／版本／角色／managed layer／override 限制與 [E17 手冊](e17-scoped-hook.md) 相同，僅此頁的更正取代旧啟動方式。

```sh
mrh settings configure --path /absolute/mrh-state/settings.json --provider typesafe --allow-workspace /absolute/workspace --permit-task-export --policy /absolute/reviewed-policy.json
mrh settings enable --path /absolute/mrh-state/settings.json
mrh settings show --path /absolute/mrh-state/settings.json
```

`reviewed-policy.json` 是實際核對過的既有分級／rates 設定，不是編造的價格。可用 `mrh model light/small/mid/top` 以方向鍵／Enter 選模型及本範圍支援的明確 effort。普通級還須取得來源可信、相同 service/currency/unit 且各 components 可比較的真實 rates；沿用既有 `policy.rates`，不新增 cost framework。未提供真 rates 时，普通級仍是 live prerequisite；scripted fixture 的數字只能驗比較接線。Main／合法 Fixed 不要求普通級成本資料。

實際 Jev 還須在原授權範圍內安全提供既有 TypeSafe key。B 沒有讀、設定或對外驗證真 key，沒有把 workspace/export/enable 三項權限當成憑證或 provider availability。

```sh
mrh settings disable --path /absolute/mrh-state/settings.json
mrh settings configure --path /absolute/mrh-state/settings.json --deny-task-export
codex --no-daemon plugin remove model-routing-harness@model-routing-harness-local --json
```

Disable 阻止新 invocation 分類／取 key／外送；remove 只撤回本 plugin 的註冊，separate settings/history 保留。更新用同一 root/settings，不用旧 snapshot 蓋掉後續修改；其他 Hooks/native deny、主模型與 D23 仍保留。

## 驗證範圍

29 項沿原 scope/core/stop 的聚焦檢查通過（1.395 秒），包括 omitted/null 相同改寫、explicit skip、null selected effort stop／replay、split/equal/attached startup overrides、可用 local invocation 與 key/Jev 前的保護。原 7-case native runner 只重跑一次，Light 改為 null model/effort，通過完整原參數及實際子request `gpt-5.6-luna / low`；parent仍 `gpt-6.1-sol / low`。其餘有效 E17 role/privacy/failure/lifecycle 證據沿用，沒有 suite／平台／研究擴張。

Native 7 情境實耗 11.087 秒，Jev/Responses 仍明確 scripted。這證明已安裝官方 Hook 與 dispatcher 的受測設定路徑，不能代替真 Jev／provider、自主 parent 完成或正式啟用。

證據：[聚焦彙整](evidence/e17r-verification.json)、[public help](evidence/e17r-parser-help.json)、[parser forms](evidence/e17r-parser-forms.json)、[native null case](evidence/e17r-native-chain.json)、[bundle entry](evidence/e17r-bundle-entry.json)、[build](evidence/e17r-build.json)、[identities](evidence/e17r-source-identity.json)、[cleanup](evidence/e17r-cleanup.json)。A 的第一個實際操作是用修正版 bundle prepare/show 在自己的 fresh workspace 讀回，再按上面已支援的原生方式 review/trust；影響此路徑的出入交 B 修正，其他差異留 A 取捨。

原 R1/R2/R3、正式 activation/real credentials 的邊界及 A 驗收義務保留，不以 scripted PASS 宣稱整體完成。

修正版候選：`/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.3.0-e17r-macos-arm64`。Archive SHA256 `cdd8371c7d0dc91bd3658caad32f6f513cf48808be90bb37436d929c16aab60e`（26807943 bytes）；manifest SHA256 `377b9bd2d679c782791ac14d2f34e40becf3a511b67f946543a68d54ba677b63`。Source `7ad71821e4ad7edf3f23adee7708371ecc28d821`，44 source identities／31 MRH modules／2059 manifest records符合；使用後immutable且native installed/prepared runtime相同。原 E17-final 與更早 accepted candidates保留。
