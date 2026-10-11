# E17：可檢查設定範圍內的外部 Hook 分級

這個候選不修改或替換 Codex App／CLI，也不要求主代理先叫分級工具。官方 pending spawn 進入 plugin 的 PreToolUse 後，MRH 檢查範圍、呼叫既有 Jev adapter，再依原四級表回傳完整 updatedInput 或中性保留。Top Main 使用原生 deny/reason，指示同一父代理接續尚未執行的子任務。

本機集中原生鏈已通過 7 個情境，9.259 秒；40 項受影響檢查通過，1.097 秒。Jev 與 Responses 都是明確 scripted，尚未代表真 Jev／真模型或正式啟用。一般安裝與這些未驗證邊界分開呈現，原 R1 分母與 A 驗收責任保留。

## 最短使用方式

候選目錄：`/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.3.0-e17-final-macos-arm64`。選定穩定目錄後，用它的 `mrh`，或自行放一個指向該 entry 的 PATH symlink；不需要另外安裝 MRH Python／SDK／bridge。

以下是產品操作方法；B 沒有對人類正式環境執行註冊、外送或啟用。

```sh
mrh plugin prepare --root /absolute/mrh-plugin --settings /absolute/mrh-state/settings.json --scope-workspace /absolute/workspace
mrh plugin show --root /absolute/mrh-plugin
codex plugin marketplace add /absolute/mrh-plugin --json
codex plugin add model-routing-harness@model-routing-harness-local --json
codex plugin list --json
```

Prepare 自動找已安裝的官方 native CLI，也可明確指定 `--codex-binary`。它先實際檢查支援範圍，預設停用、禁止外送；不改主模型、不開 Hook trust。透過原生 `/hooks` review/trust 後才可能執行。`show` 的 `configuration_scope.assurance` 是 `inspected-configuration`；registration/trust/activation 保持未驗證，不能把這個輸出當成整體 ready。

模型仍使用既有 `mrh model light/small/mid/top` 的方向鍵／Enter 選擇。這個初始 scope 的改寫要求表中明確選定可支援的 effort；無法確認的 inherit 分支保留原呼叫。一般級另外需要相同服務／單位／幣別、來源明確的配置成本向量；比較的是配置的各項單位成本，不保證總帳單或每次模型成功。成本未知只保留該普通級，Main／合法 Fixed 分支仍能使用。

正式外送前另須在 MRH settings 明確允許這個 workspace、task export，配置既有 TypeSafe provider 的憑證，再 enable。這些是原來的權限界線；B 沒有讀真憑證、對外測試或代為開啟。

```sh
mrh settings disable --path /absolute/mrh-state/settings.json
codex plugin remove model-routing-harness@model-routing-harness-local --json
```

Disable 後新 invocation 不分類、取 key 或外送；已開始的既有 invocation 仍依原 deadline 邊界處理。Remove 只撤回本 plugin 的原生註冊；separate settings／history 保留，不用舊 snapshot 蓋掉後續使用者變更。升級使用同一 prepare/root/settings，保留模型表及 enabled/export 狀態；無效 scope 拒絕更新，既有資料不被重置。

## 精確初始範圍

目前只 pin 官方 macOS arm64 native CLI `codex-cli 0.159.3`，SHA256 `4d210f7c5a18fd0386434df23b5bdbb8c0e7257d3e8a2b30b0769c8bbe99a878`，固定 CODEX_HOME／canonical workspace，local CLI 或 app-server stdio。未知版本、其他 binary、foreign workspace／home、可偵測的 config 變動均保留並可見。其他 Desktop／版本不默認取得支援，也不提供 patch host 的安裝方法。

範圍檢查讀相關公開 config/defaults、generic role 定義及選定 catalog；額外 project/system/managed layers、profiles、default role override 都拒絕這個初始範圍。Special/custom agent types 及明示非 null child model/effort 在 Jev 前略過。省略或 null 不會單靠名字變成 eligible，而須通過實際 scope 檢查。可偵測的 selected provider/defaults/catalog 變更使 scope 失效。無法由 Hook 觀察的 session/turn/dynamic role overrides 明確在契約外，不聲稱已驗證。

執行時從公開程序資訊及 `proc_pidpath` 核對原生執行身分，再驗 binary/config/catalog；分類後及 cached effect 重播也重核 configuration。版本與公開設定所得 assurance 使用獨立 `ConfigurationScope` 與 `Fact.basis=configuration`，不標成當次 observed host facts。父模型/cwd 的合法 Hook metadata 仍是 observed；advertised request syntax 不代表帳戶 availability。角色、成本、effectiveness、remote success 的證據邊界不互換。

本次實際 V2 canonical Hook 名稱是 `collaborationspawn_agent`。Plugin 只匹配這個精確名稱及既有 `spawn_agent`，內部正規化不改原 argument object。所有原參數保留，只有 model/effort 改写。V2 `task_name` 被保留為 public reported task reference，不偽造 UUID／actual model；真實／confirmed 模型記錄仍維持其原證據要求。

普通故障與 scope 失效只回 systemMessage 加中性保留，不 force allow；其他 Hook/native deny 不被繞過。D23 使用者選定目標停止是獨立原政策，不清 stored stop，不因回復正常或設定更新自動恢復舊呼叫。後續 provider 失敗不由 MRH 另外建立 fallback task。

## A 的第一個實際驗收操作

先用上面候選的 prepare/show 在**自有 fresh CODEX_HOME/workspace**讀回 scope、停用狀態與模型設定保留；再在同一個自有 root 透過官方 plugin commands 與 `/hooks` 信任。可直接重播已集中好的 fixture：

```sh
python3.11 scripts/verify_scoped_host.py --binary /absolute/official-native-codex --catalog build/e17-public/models.json --output /absolute/e17-a-native.json
```

這個 fixture 只在 owned fresh HOME/workspace 註冊，使用未改的 official stock model metadata、scripted Jev／loopback Responses；沒有 host facts injection。它測 generic Light 完整參數與实际子請求 `gpt-5.6-luna / low`、Main zero-child/native parent return、explicit model/effort、special role、Jev failure 與 config invalidation。Parent 保持 `gpt-6.1-sol / low`；沒有 session/turn model-effort override、SDK/binary 修改、aliases 或 v1 metadata 降級。Native parent received、scripted parent completed 與真正自主完成是不同主張。

Scope inspection/normal prepared launcher 使用同一 runtime bytes；fixture 的 enabled 分類只注入 scripted transport/key，仍走 production config inspector。它透過官方 trust review 執行自有測試 Hook，不能當作已啟用人類的正式 Hook。

證據：[native chain](evidence/e17-final-native-chain.json)、[bundled entry](evidence/e17-final-bundle-entry.json)、[build](evidence/e17-final-build.json)、[verification](evidence/e17-verification.json)、[source identities](evidence/e17-source-identity.json)、[cleanup](evidence/e17-cleanup.json)。範圍內的設定/更新/停用及 independent broken-runtime notice 延續原生命週期；沒有新 daemon、第二套 state store、派工器或平台矩陣。

### 直接修正與未升格的證據

早期 fixture 沿用舊 synthetic 歡迎詞、legacy namespace advertisement 與 ps comm 路徑假設，均不能證明 stock V2 工作。修正後讓真實 dispatcher 接受／拒絕公開 V2 呼叫，實際觀測 exact canonical 名稱，產品採 narrow matcher；kernel process image identity 修正後才通過完整鏈。[名稱診斷](evidence/e17-canonical-name-diagnostic.json) 與 [未成功的 scope 輪次](evidence/e17-native-chain.failure.json) 保留，不算 PASS。沒有因此改官方 model metadata、binary 或放寬 configuration assurance。

沿用 E4/E5 未變的原生控制/registration/trust/co-deny/removal語意、E14 warnings 和 D23 stop；本輪只重驗直接受影響的一條鏈及 package entry。正式啟用、真 Jev／provider、自主 parent continuation與其他未測版本/模式仍由 A 在原授權界線內驗收，不以本機 scripted PASS 宣稱完整 R1 完成。

最終 archive SHA256：`9d2a1fd26c50ae1d1f0dca31864a9ac7f303e77964f1ffeee8720231e2a99be8`（26808298 bytes）；manifest SHA256：`303442d2113d64cfc7f78fadc938beecf311c3f1e88e465f77a3b4d4e21f6e8a`。初稿入口缺少 bytecode 禁寫，已在全部 Python hand-off 補上 `-B`；最終包操作後 2059 manifest records 完全不變，native installed runtime 與 packaged prepared runtime hash 相同。[bytecode 診斷](evidence/e17-bytecode-diagnostic.json) 不算成功候選；原 accepted E15/E16/E16R 保留。
