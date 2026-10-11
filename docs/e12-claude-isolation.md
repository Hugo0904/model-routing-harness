# E12-B-001：Claude metadata probe 的隔離前置尚未通過

依 D27 使用固定 Claude Code 2.1.267 與預定官方 SDK 0.3.296。**沒有啟動實際 Claude／SDK probe**，沒有取得 ModelInfo，也沒有驗證兩者 runtime 相容性或認證需求。先做的 inert Node 隔離檢查未成功；這是此環境下的前置缺口，不是 Claude 沒有模型清單 API 的證據。

已保存最小重現 helper `scripts/verify_claude_catalog.py`。它先檢查 pinned CLI SHA，建立專用 cwd/HOME/config/cache/tmp 與 allowlisted env；沒有 real/fake credential，沒有 accountInfo、user prompt、project/user settingSources、MCP、plugins 或 hooks。準備區只允許固定官方 SDK tarball，RAM 驗 SHA後只提取 sdk.mjs，無 npm install/lifecycle/optional-native。實際 runtime 僅在所有 inert canary 通過後才可能啟動；本次未走到下載／提取或實際 query 分支。

## 已執行的兩個前置結果

1. `PYTHONDONTWRITEBYTECODE=1 python3.11 scripts/verify_claude_catalog.py --inert-only`，預設工具 launcher：`sandbox-exec: sandbox_apply: Operation not permitted`，exit 71，0.1695秒；Node 未執行。這沒有證明 profile 內的安全限制。
2. 同一 inert command 經工具權限審查允許（只調整外層 launcher，內層仍 deny-default／no-network／no-mach-lookup／no-security-helper／root-only-write）：Node `/opt/homebrew/Cellar/node/24.1.0/bin/node` 在任何 canary 回報前以 **SIGABRT（exit -6）** 結束，0.7543秒，stdout／stderr均空。sandbox_apply 的外層限制排除後，仍未能建立可用的受限 Node runtime；不能宣稱 canary 通過。

第二次實際 profile 的核心是 deny default；只允許 process/sysctl/signal、公開 OS／Homebrew runtime／指定 native CLI／owned-root read，以及 owned-root write；明確禁止 synthetic private-canary read、security helper 執行、所有 mach lookup 與所有 network。它原本允許 `/System` subtree。最後語意審查把重現 helper 收緊為 `/System/Library`／Applications／DriverKit 並明確禁止 `/Users` 及其 Data-volume alias；**這個更嚴格版本未再執行**，不能把先前結果當成新版通過。沒有做多版本／多 profile 嘗試，沒有放寬私人資料或 IPC／網路限制。

canary 原定只使用 synthetic 非憑證檔案與 TEST-NET socket，確認 own-root write 成功、私人 canary read／outside write／`security help` spawn／network connect 被 EPERM/EACCES 拒絕；不讀真實登入或 Keychain。Node 在這些檢查前中止，所以實際驗證值為**未知**，而非真。SDK Query 的零訊息 AsyncIterable 與15秒 response bound僅為未執行的準備程式，沒有用空字串或任務輸出假裝 metadata。

## 已確認的身份／清理

- CLI SHA-256：`a681f3008f0050029aeebcab3af51bb6a55ddeb625a3af3141a4416d43cd2558`，與 E11 固定 native 相同。
- SDK 預定 tarball SHA-256：`e966be99b6f047d56165e2ec03822f17a49beebd48ac8efb91dab1e48bcf69a7`，重用 E11 公開包證據；本次沒有載入 SDK。
- owned roots `/private/tmp/mrh-e12-edi7jbjq` 與 `/private/tmp/mrh-e12-ir91a9bz` 都已刪除且讀回 absent；各自 inert process group 74218／76178已收束，沒有 actual SDK／Claude child。暫存 package／model metadata／圖片皆未產生。canary outside-write file 未建立。
- process-group 精確讀回使用 `/usr/bin/pgrep -g <owned group> .`；預設 launcher 的 sysmond 不可用並非程序殘留證據。經工具審查允許後，兩組均 exit 1、PID清單空、stderr空，確認沒有成員。
- 原 E10R 產品 bytes、A 的既有證據與 preview保留；無 adapter/core修改、版本切換、全域 install／Hook、provider/model call、私人狀態讀取、其他project變更、Goal或push。

缺的是**能讓 inert Node 正常啟動，同時可強制阻止 user-private／Keychain／outbound 的受限 runtime 契約與直接證據**。SIGABRT 沒有公開原因；本次不猜成 auth、CLI／SDK版本不相容或某個 Mach service，也不以 proxy 代替 OS 保證。依 D27 的 isolation-failure停止条件，返回此具體缺口；A 決定下一個可行隔離方法或必要的有界來源診斷，不能直接啟用 adapter、放寬限制或把兩 AI 的原 R2要求刪除。Gemini未再探測，仍保留 E11 的 session/auth／effort／binding缺口。

本輪只做準備程式與兩個無害前置嘗試、語意／diff審查及清理；沒有 broad tests/builds或實際 SDK metadata結果。
