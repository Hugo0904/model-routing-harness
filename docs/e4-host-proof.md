# E4 installed-host proof

已驗證兩個已安裝執行檔的 **app-server native v1 delegation／Hook 機制**，provider 為 loopback 腳本回應。這不是真實 OpenAI／Jev、Desktop UI 或主代理自主接回工作的證據，完整 R1／S4 尚未完成。當次指派、Goal 授權阻礙與接受狀態由 [MRH-001](MRH-001.md) 管理。

| 執行檔 | 結果 | 完整命令耗時 |
|---|---|---|
| shell CLI 0.159.3 | Main／Fixed／double／explicit／low／failure 六情境通過 | 3.220s |
| Desktop bundle CLI 0.162.0-alpha.17.2 | 同六情境通過 | 2.457s |
| Desktop UI | 未操作／未驗證 | — |
| 隔離 Goal（E4 當時） | 自動審查拒絕，未執行；後續 E4G 已另補證據 | — |
| 真實模型／Jev、正式共享 home 安裝 | 未驗證／未啟用 | — |

證據在 [shell runtime](evidence/e4-shell-host.json)、[bundle runtime](evidence/e4-bundled-host.json)、[E4總表](evidence/e4-verification.json)。時間只列最後正式命令，準備／診斷／授權等待另計；原operation計時不含最後teardown，也保留在JSON。每份記錄含官方信任讀回、真 Hook input/output、native parent/child IDs／事件、loopback 收到的 model/effort，以及 synthetic/live Stats。每個版本皆有7個 proposal、6個合成分類 attempt、4個原生 fixture child；product synthetic partition 保存4筆 child receipt，live confirmed／Jev attempts均為0。Requested synthetic alias 不是 actual OpenAI model。

Main：真正 spawn 被同步 PreToolUse deny，宿主把 blocked result 送回相同 parent，後續腳本回應完成該 turn；沒有 child ID或child request。這只證明取消與腳本續行。Fixed：宿主建立 child，loopback 收到 mrh-synthetic-fixed/high，parent配置及請求維持 mrh-synthetic-parent/low。Double 在相同 session 的兩個新 call IDs 均分類；explicit不分類並保留指定alias；0.49及classifier error保留原委派，child繼承parent alias/effort。

## 隔離設定、版本來源與重現

Harness 自行建立 fresh HOME／CODEX_HOME／workspace，只傳 allowlisted環境、沒有 auth files／credential env。HTTP server 綁127.0.0.1隨機port，assert沒有Authorization header；不重用既有daemon／service。CLI官方 startup review審核 exact fixture Hook，hooks/list讀回trusted；shell版本另外用官方介面信任空暫存workspace，紀錄只在temp home。沒有dangerous bypass flag／private trust state patch。每次處理完等待所有fixture child完成、關閉stdio app-server、清除temp與server。

官方路徑：[Hooks](https://learn.chatgpt.com/docs/hooks)、[custom provider設定](https://learn.chatgpt.com/docs/config-file/config-reference)、[model catalog aliases](https://learn.chatgpt.com/docs/enterprise/roll-out-a-gateway)。初始無catalog的Fixed改寫被native host拒絕為Unknown model；[原始拒絕證據](evidence/e4-pre-catalog-refusal.json)保留。其後依官方支持的model_catalog_json使用**各安裝版本exact tag**公開catalog；hash固定在harness，版本／hash不符即拒絕。官方文件連結的來源為 [OpenAI Codex models-manager](https://github.com/openai/codex/blob/main/codex-rs/models-manager/models.json)。不是用main／不同版本替代pin。

Catalog只在暫存目錄複製成三個mrh-synthetic-* aliases，修改display/description/default effort／upgrade/availability，並明列fixture能力：tool_mode=null、multi_agent_version=v1、full Responses、不提供search。此為腳本provider自己的能力描述，不代表Sol／Astra原型號、原生v2/code-mode或upstream能力驗收。沒有patched host binary，也沒有dynamic tool假扮spawn_agent；呼叫實際host提供的namespace/native tool。

先取得對應版本的公開檔案，核對harness固定hash，再執行六情境；這個命令不含Goal：

```sh
python3 scripts/verify_host.py \
  --binary /Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex \
  --scenario core --catalog /absolute/path/to/exact-version-models.json \
  --output docs/evidence/e4-bundled-host.json
```

Shell另用其binary及rust-v0.159.3 catalog。Default scenario=core；Goal選項的當次准許狀態請讀MRH-001。此開發harness只建立其自己的temp home，不替public installer解鎖共享home寫入。

## 觀察修正與必要檢查

兩個host的PostToolUse.tool_response都是JSON字串；adapter增加<=65536 bytes解析，僅取bounded agent_id、丟棄nickname／其他正文，仍是synthetic／reported，不提升actual model／confirmed evidence。3個新測試覆蓋native字串+rewritten input+replay、malformed/oversized、Main anomaly；另覆蓋直接Hook/Store consumers。

Bounded risk review指出cleanup第二次wait逾時可未回收；已改為只處理fresh session/group leader、有界TERM→KILL→wait、changed group拒絕signal，並於未回收時保留temp home及明確failure。PTY以controlling terminal與持續drain避免退出時buffer阻塞。3個fault模型覆蓋TERM ignored、signal permission failure保留、changed group。Reviewer重核原反例已封住；真實happy-path兩host皆exit0、temp removed、server stopped。沒有宣稱真實卡住程序或permission failure曾通過。

最後 [11項聚焦檢查](evidence/e4-tests.txt) 通過，0.174s runner／0.367s wall。E3未受影響的結果沿用。一次誤用stdin runner觸發既有multiprocessing測試的 `<stdin>` 匯入錯誤（15.276s）；[診斷](evidence/e4-runner-diagnostic.txt)保留，改為可重現module runner及受影響範圍，不將它當product regression。測試指令在 [test-run](evidence/e4-test-run.json)。未再跑E1一般盤點、E3網路或整套suite。

## 下一個真實驗證的前提

A需先決定具體surface、測試工作、可用catalog與准許外送內容，取得該surface的provider／account runtime授權；正式共享home仍需D3的exclusive transaction契約。再以獨立測試home安裝／信任精確Hook、驗證主Luna不變、Fixed實際child provider identity、Main零child且真正接回原工作、同一真Goal後續新委派。模型配置、請求欄位、provider回應與主代理完成結果需各自保存，不能以本次腳本／catalog證據替代。真Jev需要啟用雙重export gate與runtime key後另驗官方回應；目前default-disabled維持不變。
