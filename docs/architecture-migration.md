# D49：責任分群與最小搬移地圖

目前確有 33 個頂層 Python 檔；可以依五個責任群搬入子套件，保留既有物件、函式與資料契約。最大的直接風險是兩個 zip 打包器只收頂層檔案，以及舊 import／monkeypatch 路徑。這份文件完成搬移前的依賴盤點，尚未搬檔、改行為或執行測試；A 定案後才由 C 施工，再交 B 打包整合。

## 查證範圍與身分

來源基準為 `0d4d8f3b4b3db71f4a259dcf84c3af4ce2bf1b69`（D49）。C 的 exact turn `01a12c53-d786-7792-b51c-9e8e6fc02d2c` 已由規範 metadata-only helper 核為 `gpt-6.1-sol/high`；命令均在 `/Users/shawn/Code/model-routing-harness`。原 A 的 user items `01a12c50-ac0d-7ca1-bc4e-df7b471c5f4b`、`01a12c51-49c2-7aa0-9d10-3f8fa9475f25` 已透過 `read_thread` 核實，分別要求 C 分線與按責任整理結構。

只讀 `src/mrh` 的 AST imports/classes/functions、直接 tests/scripts 消費者、`mrh_build.py`、`mrh_bundle.py`、`pyproject.toml` 及必要函式。沒有讀 B 的驗收 session、live root、key 或新證據內容；開始時 B 的 driver／evidence dirty 狀態均保留。Monitor `host-check` ready，但 `host-select --mode none` 回 `current_host_turn_unavailable`；本輪是有文件交付的唯讀盤點，不建立新追蹤身分、不回退舊 context。原 MRH-001 與 A 接受責任保留。

## 建議結構與依賴方向

```text
src/mrh/
  __init__.py, __main__.py
  cli.py                         # 建議只保留既有 console/import main 入口
  routing/                       # 決策、不可變事實、分類/attempt 契約
  application/                   # 配置後執行、冪等協調、provider 組裝
  adapters/
    hosts/                       # Codex Hook、可檢查 scope、隔離出口
    providers/                   # TypeSafe HTTP、Codex 訂閱 classifier
    catalogs/                    # Codex/Claude/Gemini 公開模型清單
  infrastructure/                # 狀態、持久化、設定、安裝/封裝
  presentation/                  # CLI 命令、選單、終端呈現
```

子套件都有 `__init__.py`，避免 zip／resource 發現依賴 namespace-package 差異。不要在所有 `__init__` eager re-export 整棵 tree；保留 CLI 的懶載入，`--help`／stats 不應因搬移啟動 provider／清單探測。

實際呼叫鏈是 `presentation.cli.main → application.runtime.configured_event → adapters.hosts.codex.handle_event → application.service.process → routing.core.route`；runtime 同時組裝 settings、scope、Store 與 classifier。Classifier adapter 只接既有 `classify(task, context, recorder)`，用 `GuardedAttempts` 記 attempt；service 只呼叫 Store 的 claim/attempt/complete/stop 等介面，不知道 SQLite 細節。這些都是有用的物件／模組責任，不需要新 manager、抽象工廠或把每個純函式包成 class。

`routing` 是完整決策引擎，**不是宣稱所有內容都是純計算**：`core.route/bounded_call` 與 `attempts.GuardedAttempts` 有有限期限、thread/cancellation 協調；`cheaper`、eligibility、selected-target、cached-effect 等規則仍維持純函式。把兩者放在同一決策群是最小搬移例外，application 仍負責實際 IO 依賴組裝。為了資料夾整齊而拆改全部 route 不是本輪必要條件。

## 33 個原始檔的去向

以下新路徑都相對 `src/mrh/`。表中列出的函式／class 是實際來源；移動整個模組時符號名與實作先保持。所有相對 imports 必須依新深度重寫，不能盲目把 `from .` 改成 `from ..`。

| 原檔 | 建議新 home | 實際責任／物件 | 直接 callers／搬移注意 |
|---|---|---|---|
| `__init__.py` | `__init__.py` | package identity，無 class/function | 保留 `mrh.__file__`、resources 根 |
| `__main__.py` | `__main__.py` | main entry | `python -m mrh`；不改退出碼 |
| `types.py` | `routing/types.py` | Proposal/Decision/Classification/ContextSummary、safe IDs | core/facts/service/store/providers/catalogs；保留 exact class identity |
| `facts.py` | `routing/facts.py` | CallScope/Fact/TargetFacts/HostSnapshot、snapshot validation | core/host adapters/simulation；scope 反向依賴見下節 |
| `core.py` | `routing/core.py` | route、eligibility/stop/replay、ClassifierFailure、scripted/unavailable implementations | service/classifier/adapters/simulation；保留純規則與既有 duck-typed classify seam |
| `attempts.py` | `routing/attempts.py` | GuardedAttempts deadline、cancel、attempt recorder | core；adapter 接 recorder，不引進 Store |
| `faults.py` | `routing/faults.py` | category、safe warning/notice 字典與 outcome分類 | store/runtime/host/CLI；無終端 IO，作共用 outcome 契約例外 |
| `service.py` | `application/service.py` | process 冪等與 persistence failure/stop協調 | codex/simulation；保留 Store seam，不搬 SQL進此層 |
| `runtime.py` | `application/runtime.py` | configured_event、SupportedHostResolver、export/recursion gates、依賴組裝 | CLI；module-bound factory/read monkeypatch要改 |
| `classifier.py` | `application/classifier.py` | settings-selected factory、PROVIDERS；無隱式 fallback | runtime/CLI；兩個 concrete adapters保持分開 |
| `simulation.py` | `application/simulation.py` | 明示 synthetic demo facts/policy與run_demo | CLI/codex legacy candidate；不能混 livepartition |
| `codex.py` | `adapters/hosts/codex.py` | canonical_event、serialize、handle_event；Hook轉換/receipt | runtime/CLI；呼叫 application.service；保留 exact V2 matcher |
| `codex_scope.py` | `adapters/hosts/codex_scope.py` | ConfigurationScope、prepare/check/native identity | runtime/plugin/subscription/facts；pin/fingerprint/replay check不能削弱 |
| `codex_defaults.py` | `adapters/hosts/codex_defaults.py` | pin官方 advertised model/effort資料 | scope；不是帳戶availability |
| `isolated_host_export.py` | `adapters/hosts/isolated_host_export.py` | SourceTestProducer/ExportExchange、ExportError | isolated_live_hook與既有隔離測試；保留驗證來源/nonce |
| `isolated_live_hook.py` | `adapters/hosts/isolated_live_hook.py` | OwnedRegistration/LiveExchange | 直接scripts/tests；歷史隔離出口不換成正式host支援 |
| `typesafe.py` | `adapters/providers/typesafe.py` | TypesafeClassifier、HttpTransport/HttpResponse、credential resolver | factory/CLI legacy JSON；patch owner改新模組 |
| `typesafe_protocol.py` | `adapters/providers/typesafe_protocol.py` | serialize_request/parse_response、ParsedAnswer、rubric/pin | TypeSafe/subscription/schema；共用規格洩漏見下節 |
| `codex_subscription.py` | `adapters/providers/codex_subscription.py` | CodexSubscriptionClassifier、_ProcessOwner、官方auth/execstream guard | factory/runtime/schema；保留SENTINEL、MODEL、runner injection |
| `catalog.py` | `adapters/catalogs/catalog.py` | Model/Catalog、CatalogError、CodexCatalog/ToolCatalog、discover/hash | bindings/scope/subscription/plugin/selector、其他catalogs；lazycycle是factory例外 |
| `claude_catalog.py` | `adapters/catalogs/claude_catalog.py` | ClaudeCatalog、public parse/isolated CLI | ToolCatalog/Gemini sharedprofile；不順手改隔離權限 |
| `gemini_catalog.py` | `adapters/catalogs/gemini_catalog.py` | GeminiCatalog、installation/parse/acquire/isolated_install | ToolCatalog/discovery；安裝hash與cleanup保留 |
| `store.py` | `infrastructure/store.py` | Store、SQLite/claim/immutable receipts/stats | runtime/CLI；schema/table/IDs/key/history不改 |
| `owned.py` | `infrastructure/owned.py` | filesystem ownership、canonical_path/verify/locked/replace_owned | settings/bindings/plugin/scope/subscription；marker/lock/permissions不改 |
| `settings.py` | `infrastructure/settings.py` | init/read/update(CAS)/workspace_allowed | runtime/plugin/bindings/CLI/presentation；state paths與JSON不改 |
| `settings_schema.py` | `infrastructure/settings_schema.py` | pure strict parse/validation/default_settings、SettingsError | settings/runtime/selector/editor/CLI；provider常數依賴見下節 |
| `bindings.py` | `infrastructure/bindings.py` | Registry、installation/catalog與profile綁定、target_veto | selector/runtime/CLI；bind/rebind/CAS/stop狀態不改 |
| `installer.py` | `infrastructure/installer.py` | Plan、prepare/apply、SyntheticHome；legacyconfig管理 | CLI；marker、preserve/refusal、atomic behavior保留 |
| `plugin.py` | `infrastructure/plugin.py` | prepare/show、_runtime_archive、owned lifecycle、independent LAUNCHER | CLI/tests/buildproof；resource root與zip entry要修 |
| `cli.py` | `presentation/cli.py` | build_parser/main與命令組裝 | rootmain/console/tests/scripts；root `mrh.cli:main` 建議留薄入口 |
| `terminal.py` | `presentation/terminal.py` | render_stats/config/review/choices、sanitize/width | CLI/selector/editor；同可見輸出，不改視覺 |
| `model_selector.py` | `presentation/model_selector.py` | select、Cancelled/Back、鍵盤binding/catalog選擇 | CLI；不是catalog adapter，仍調Registry/settings |
| `settings_editor.py` | `presentation/settings_editor.py` | edit、Cancelled、終端policy草稿 | CLI；取消/保存/返回的既有規則保留 |

表中的 root CLI 是額外薄相容入口：implementation 去 presentation，root只輸出 `main`；不是保留33份重複implementation。已知消費者的 imports改canonical路徑。是否還承諾舊 Python library imports，是 A 的一項決定；目前公開console contract明確在 `pyproject.toml`，未找到必須保留所有私有 Python 路徑的發布承諾。

## 依賴圈與真正需要決定的洩漏

AST 分別算 module-top-level imports 與包含 function-local imports 的圖；33檔的 eager graph **沒有強連通圈**。含lazy imports有兩個 SCC：`facts ↔ codex_scope`，及 `catalog ↔ claude_catalog/gemini_catalog`（Gemini另依Claude isolation helper）。這不等於當前 import失敗，也不能用套件名宣稱它們已消失。

1. **fact validation依賴具體Codex scope**：`facts.snapshot_for` lazy import `codex_scope.ConfigurationScope` 並作 `type(value) is`；`core.validated_facts` 呼叫scope.validation_reason，後者目前會跑 `check(descriptor)`，分類前、後與cached replay都有意重新核設定。單純搬檔可保留這個已知例外，但routing會反向依賴hostadapter。最小改善是把這個不可變wrapper移到routing中立契約、由Codex adapter提供既有重新驗scope方法；保留exact-type admission、configured/observed distinction與每個原revalidation時點。**A決定是否納入同次搬移**，不能藉一般Protocol／接受dict放寬事實信任，也不能只在runtime開始核一次取代後續check。
2. **設定驗證只為常數卻載入provider**：`settings_schema` import `codex_subscription.MODEL`、`typesafe_protocol.PINNED_MODEL`，subscription又importTypeSafe rubric。最小改善是新純資料 `routing/classification_spec.py` 集中同值pin／rubric，三個消費者讀該檔；adapter舊常數仍可在各自模組bind同一值。這不是新cost/routing框架、不改model/rubric。若A要求嚴格五群責任，建議納入。
3. **Gemini使用Claude命名的通用isolation policy**：`gemini_catalog` import `claude_catalog.isolation_profile`，兩者都確實使用同一macOS沙箱策略。最小改善是原函式原封搬到 `adapters/catalogs/isolation.py`，不增加抽象類或加權限；兩adapter共用。這能移除工具間不必要連動，需保留兩家的canary/cleanup限制。`catalog.ToolCatalog` lazy選 concrete catalog的圈仍可作package內composition例外，無需把factory/model/discovery全拆散。
4. **core的provider契約與synthetic helper**：現有 `ClassifierFailure/UnavailableClassifier/ScriptedClassifier` 有真正callers，保留class／錯誤reason/telemetry與`classify`介面；不為宣称domain純度新建整套繼承樹。可以先留routing.core；單獨拆errors/fakes不是此次必需。`faults` 是純字典/分类，`Store.stats`使用它不代表storage依賴terminal UI；移到routing共用outcome即可。

## 打包、入口與硬編碼消費者

| 消費者／來源 symbol | 現況與搬移影響 | 最小調整 |
|---|---|---|
| `mrh_build.py::build_wheel` | `(src/mrh).rglob('*.py')`，相對src保留完整路徑 | 已可收子套件；沿RECORD/metadata，不另寫backend |
| `src/mrh/plugin.py::_runtime_archive` | `resources.files('mrh').iterdir()`只收頂層py | 對Traversable遞迴，保存`mrh/<完整相對路徑>`，包括子package `__init__`；不能假設filesystem Path或以 `.name`壓平 |
| `mrh_bundle.py::application_archive` | `(ROOT/'src/mrh').glob('*.py')`＋`p.name`，同樣漏子package | 遞迴rglob並保存src相對路徑；保留metadata、固定ziptimestamp與排序 |
| `scripts/build_standalone.py` | import root `mrh_bundle.build`；`parents[1]`取得repo | 若脚本位置不搬則不用變；B由既有cache重建一次新候選 |
| `pyproject.toml [project.scripts]`、root `__main__.py`、兩zip的`__main__.py` | 都指 `mrh.cli:main` | 建議同一root薄入口保留，內部指presentation.main；不改命令/參數 |
| `plugin.LAUNCHER`與`binding.json` | `runtime.pyz hook --settings`，並校驗runtimehash；LAUNCHER依自己`__file__`找binding | 這是安裝artifact路径，**不用因source分層搬launcher/runtime/binding**；保留independent failurenotice |
| `tests/test_bundle.py::test_application_archive_has_metadata_and_all_mrh_modules_without_sdk_or_build_runtime` | 目前只assert `mrh/cli.py`等，不能證明nested全收 | 在這個既有實質package check加遞迴source→zip parity，沒有逐檔新增簡單test |
| `tests/test_fault_notices.py::InstalledLauncherFaultTests...` | broken-runtime fixture以排除`mrh/runtime.py`、`mrh/faults.py`制造import失敗 | 改canonical zipmember，否則搬移後不再造成原故障，可能falsepass |
| `scripts/verify_configured_package.py` | hashes已rglob；assert `mrh/settings_editor.py`為舊member | 換presentationmember；installed root仍以`mrh.__file__`parent計算完整suffix |
| `scripts/verify_claude_package.py` | sourcehashes `.glob('*.py')`、舊module`__file__` | 改rglob/relative path；canonicalclaude module identity；不能因平放消失而少驗來源 |
| `scripts/verify_model_package.py` | hashes已rglob，identity code import舊selector/bindings/catalog | 更新embedded Python string imports；完整relative suffix保留 |
| `scripts/verify_standalone.py` | `/app/mrh.pyz/mrh/` identity仍可保留；有舊`mrh.catalog` imports | rootpackage identity不改，改embedded catalog import即可 |
| `scripts/verify_subscription_bundle.py` | 從實際zip列`mrh/`py並對source；既有Store、Types、Plugin、Subscription等embedded imports | recursive completeness需對照全部source集合，更新imports；可沿無modelguard/CAS/legacyhistory檢查 |
| `scripts/verify_scoped_host.py`、`verify_plugin_host.py`、`verify_accounting_package.py`及其bootstrap字串 | `from mrh.cli/plugin/core/...`、zipruntime CLI與installedhash | canonicalimports同步；artifactname/hash policy不變，不改scripted證據身分 |

同檔 monkeypatch必須改**實際查詢符號的owner**，不是只改import這一行：例如 `mrh.runtime.classifier_from_config/read`（settings runtime、fault、subscription gate）；`mrh.plugin._runtime_archive`（ownedplugin）；`mrh.core.bounded_call`（TypeSafe）；`mrh.codex_scope.BINARY_SHA256/_native_parent/prepare/subprocess.run`；`mrh.typesafe.environment_credential/HttpTransport/TypesafeClassifier/ssl/http`；`mrh.catalog.discover/executable_hash`、Claude/Geminiacquire/process helpers。`test_cli`的builtins importguard與module `_default_db` patches必須作用於 `presentation.cli`，不能patch只re-export的root facade。class-object patch跟著canonicalimport保持同一class，不生成第二份實作。

## scripts/tests 分類建議與搬移順序

先完成productionsource與imports，再考慮物理搬scripts/tests；本輪提出分類而非指定歷史證據大搬家。若A採同次分類，先處理以下真依賴，不能直接增加一層資料夾：

- `scripts/build_standalone.py → scripts/packaging/`；`verify_package/standalone/*_package/*_bundle → scripts/verification/packaging/`；`verify_host/plugin_host/scoped_host/live_hook/fault_host/source_export、run_subscription_acceptance → scripts/verification/hosts/`；catalog/isolation/CLIprobes → `scripts/verification/catalogs/`；selector/navigation/editor/faultdisplay fixtures → `scripts/verification/terminal/`；歷史 `e8_hook_bootstrap.py/e19_input_observer.py` 只標歷史fixture，保持原證據引用，不復活已撤回observer。
- 脚本群中 `from verify_host import Rpc/...`、`from verify_plugin_host import BOOTSTRAP`、faultdisplay→navigation，以及多處 `Path(__file__).parents[1]` 是實際位置契約；搬位置會破repo-root與兄弟import。最小方案保留既有scripts外部路徑作薄入口，canonicalhelpers逐群搬；或本次只分類source，脚本物理搬移另在A同一完整方案定案。不要為它另建通用runner框架。
- tests依用途可分 `routing`（core/action_facts/e3facts/operator_stop）、`application`（integration/settings_runtime/accounting/subscription/gates）、`adapters`（scope/hostreceipt/catalogs/typesafe/protocol/isolated）、`infrastructure`（store/settings/schema/ownedplugin/installer/rebind/bundle）、`presentation`（CLI/configtable/selector/terminal/faultdisplay）。hostgoal/cleanup是既有驗收driver的infra生命週期測試。`test_fault_notices`跨runtime/store/installedlauncher，應整檔放applicationintegration，不按函式切一堆測試檔。
- tests新增子目錄需明確`__init__.py`或既有discover設定配合；`unittest discover -s tests`不保證遞迴無package目錄。保留class/methodnames，修改imports/patches與有效discovery。不重命名大量 `docs/evidence` 或改寫舊來源hash；舊accepted包保留，變更後candidate有自己的新manifest。

最小施工順序：A定scope例外／入口相容／scripts/tests物理位置 → B完成D48並停止可衝突施工 → C移source、修imports/patches與兩zipcollection直接consumer，保持磁碟schema/UI/Hookbehavior → C做A選定無providerchecks與差異讀回 → B用既有pin/cache打新候選、做無model入口/manifest/readback → A接受。C/B不能同時改packagingconsumer；建議C修收檔邏輯，B只在C交付後build/integrate。

## 建議最少的既有驗證（本輪未執行）

選擇只依實際變更，不以測試數量或總suite作成果。若只移路徑且保留已驗semantics，不重跑已成功真Jev／subscription／native model／Main／Fixed／Goal。必要consumer閉環是sourceimport → appzip/runtimezip → sameCLI/Hook → same settings/Store；A定最終runlist。

| 必要主張／何時需要 | 已有適當check |
|---|---|
| 兩zip包含全部子套件、入口能從無repo cwd載入、prepare/update保留設定 | `BundleTests.test_application_archive_has_metadata_and_all_mrh_modules_without_sdk_or_build_runtime`補nestedparity；`OwnedPluginTests.test_preparation_repeat_and_updated_code_preserve_settings_and_standalone_default_off`；B新bundle跑既有`verify_subscription_bundle.inspect`一次，覆蓋實際private runtime/guard/CAS/legacyhistory |
| factory/Hook鏈沒有因imports失效、disabled/export/recursion還在同時點 | `SubscriptionTests.test_runtime_pre_spawn_gates_recursion_disabled_export_explicit_role`；`SettingsRuntimeTests.test_public_hook_uses_real_factory_and_parser_main_fixed_receipt_disable`，皆isolated runner/transport，不是真模型 |
| 如果移中立scopewrapper，exact-type/configured信任與分類後/replay重核不能改 | `ScopeTests.test_configuration_basis_cannot_be_promoted_to_observed_host_snapshot`、`test_configuration_changed_during_classifier_and_cached_replay_is_neutral`；`ActionFactTests.test_foreign_scope_malformed_or_unlabelled_production_dict_never_routes`。不因搬移額外重跑全部scope/parsermatrix |
| disk schema／IDs／CAS／legacyhistory不變 | `SubscriptionTests.test_provider_switch_preserves_permissions_policy_history_and_cas` 與 `StoreTests.test_replay_cached_and_conflict_pending_do_not_reclassify`；若B packagecheck已覆蓋相同未改資料流，可沿用、不再重複sourcecheck |
| fixture真的仍模拟brokenruntime而非因舊member名falsepass | `InstalledLauncherFaultTests.test_installed_launcher_integrity_and_runtime_load_faults_preserve_safe_call`，在修member後必要一次 |

這些現成check已能覆蓋關鍵搬移故障；只增強既有archiveparity缺口，沒有每filetest或新matrix。若A選scripts/tests物理移動，再增加一次有效discovery/入口解析的直接確認，不能用「沒找到test而空跑」當pass。UI未改則沿既有Terminal證據；若意外改呈現，才重開受影響畫面。

## 交 A 定案的三件事

1. 採以上五群與rootCLI薄入口？建議只保留已知命令入口，不留31個implementation/shim平放；已知repoconsumers全部改canonical imports。若A需保留額外Pythonlibrary路徑，明列真正外部契約後再加相容。
2. 同次是否納入中立scopewrapper、純classification_spec、共用catalogisolation三個最小責任修正？建議納入後兩項；scopewrapper涉及admission/revalidation seam，A需定準確契約，或明示暫留具體lazy依賴例外。核心route不全面拆解、Store/classifier/serviceinterfaces保留。
3. scripts/tests是否此次物理分群？source分群必做；物理搬其餘位置會追加真repo-root/discovery/兄弟importconsumer，建議A把這部分明列一次完整migration範圍，B打包在C交付後才開始。歷史證據/acceptedartifact不搬不重跑。

本輪完整地圖已交付；這是缺失依賴事實的準備單位，不取代人類已要求的後續結構實作。原功能未驗義務、B的同環境restore與A整體接受均維持。
