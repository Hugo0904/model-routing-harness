# 啟用已驗證的本機 CLI 路徑

D57 的登入隔離與白名單已納入 **E21 獨立候選**，實際 bundled entry 的 allowlist、設定／歷史保留與無 auth 拒絕檢查通過。這不表示已登錄全域 Hook 或完成日常 App 接通。下方已登入的保留環境仍使用 E20 plugin；本次沒有升級、重登入或更動該環境。

## E21 新工具入口（尚未安裝到保留環境）

```sh
MRH_E21_ENTRY=/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.3.0-e21-macos-arm64/mrh
"$MRH_E21_ENTRY" --help
```

套件自帶 private Python，不需安裝 SDK。E21 的[建置身分](evidence/e21-build.json)與[實際 packaged consumer](evidence/e21-bundle-entry.json)核對了目前 source、兩種 archive、完整 manifest 和新 allowlist 入口；沒有模型、login/status 或正式註冊／trust 呼叫。D57 的 22 項來源檢查及既有 native 結果沿用，沒有重跑。

E21 目前是可交付的工具候選，**保留 session 的已載入 Hook 仍是 E20**。不要只把下面的 `MRH_ENTRY` 換成 E21 就當 plugin 已升級；正常 daily CLI／App 還缺同一步已解析 child role／原模型的宿主契約，整體接通由 A 整合驗收。

使用已讀回成功的 E20 獨立套件與已登入、保留的同一 home，不需 Python、SDK 或 API key。普通便宜模型切換、同 Goal 的兩回 fresh classification／lifecycle，以及 Top Fixed 的較高 configured child／結果已由 A 驗收。D48 的 Top/0.99、native Main blocked、沒有 child 與同一 Luna parent 完成也已由 A 驗收。完整 R1、Desktop／原全域 home 與自主 Goal 續跑尚未完成，見 [E19 實際證據](e19-subscription-classifier.md)。目前 MRH disabled／task 外送 denied，啟用要由以下明確指令進行。Source 已按責任分層；E20 已套用同一 session 的 plugin，原 settings／revision／registry／歷史保持相同，登入沒有重建。

## 在終端貼上這組入口

```sh
MRH_ROOT=/private/tmp/mrh-e19-d45-mrc5zw54
MRH_ENTRY=/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.3.0-e20-macos-arm64/mrh
MRH_CODEX_DIR=/Users/shawn/.nvm/versions/node/v20.19.4/lib/node_modules/@openai/codex/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin
MRH_SETTINGS="$MRH_ROOT/state/settings.json"

mrh_cli() {
  env -i HOME=/Users/shawn CODEX_HOME="$MRH_ROOT/home"     PATH="$MRH_CODEX_DIR:/usr/bin:/bin:/usr/sbin:/sbin" TMPDIR="$MRH_ROOT/tmp"     LANG=en_US.UTF-8 NO_COLOR=1 TERM=xterm-256color "$MRH_ENTRY" "$@"
}
codex_cli() {
  env -i HOME="$MRH_ROOT" CODEX_HOME="$MRH_ROOT/home"     PATH="$MRH_CODEX_DIR:/usr/bin:/bin:/usr/sbin:/sbin" TMPDIR="$MRH_ROOT/tmp"     LANG=en_US.UTF-8 NO_COLOR=1 TERM=xterm-256color "$MRH_CODEX_DIR/codex" --no-daemon "$@"
}
```

MRH 工具讀取使用者的可信 CLI 安裝位置；model／settings 寫入下方明確的 owned registry／settings。實際 Codex 程序使用同一隔離 home／登入及固定的環境，不修改全域環境或正式 Codex home。已關聯的 Codex 版本為 `0.159.3`，同一 model registry 是 `$MRH_ROOT/model-bindings`，同一設定是 `$MRH_SETTINGS`。

## 選模型與確認設定

```sh
mrh_cli model light --root "$MRH_ROOT/model-bindings"
mrh_cli settings view --path "$MRH_SETTINGS" --plain
mrh_cli settings show --path "$MRH_SETTINGS"
```

將 `light` 換成 `small`、`mid`、`top`，或省略等級。↑／↓ 選 AI、模型、推理強度與 Save；← 返回並保留草稿，Esc 取消。此 registry 已綁定現有設定，不會另建一份政策；不要省略 `--root`。新清單讀取失敗可 Retry／Back／Cancel，舊清單只供顯示，確認下架才要求手動替換。Top 可選 Main 或 Fixed，Main 不更動主模型；固定模型仍受角色及相容性保護。儲存政策不會自動啟用或允許外送。

分級器固定 `gpt-6-luna / low`，使用 ChatGPT 訂閱；四級選單設定的是後續 child。0.5 以下保留原委派。信心度是模型自報，沒有校準；TypeSafe 舊設定保留且沒有自動 provider／API fallback。

## 啟用這個已準備的工作區

```sh
codex_cli login status
mrh_cli settings configure --path "$MRH_SETTINGS" --permit-task-export
mrh_cli settings enable --path "$MRH_SETTINGS"
codex_cli -C "$MRH_ROOT/work"
```

官方 status 應顯示 ChatGPT。這個空白 workspace 已綁定 scope、安裝並信任原兩個 MRH Hook；目前 parent 為 `gpt-6.1-sol / low`、Top Main、普通各級為 Luna／low。進入官方互動 CLI 後才輸入工作，不在啟動命令加 prompt、`-m`／`-c`／profile 或 turn model overrides；那超出目前 Hook 可核對的 scope。原 sandbox／approval 規則保留，這些指令沒有提高檔案寫入權限。單純詢問不會分級；只有新的、沒有明示模型／effort且角色未受保護的委派才進分級器。已停止的原提案不會自行重啟。

## 查結果與停用

```sh
mrh_cli status --settings "$MRH_SETTINGS" --plain --details
mrh_cli stats --settings "$MRH_SETTINGS" --json --details
mrh_cli settings disable --path "$MRH_SETTINGS"
mrh_cli settings configure --path "$MRH_SETTINGS" --deny-task-export
mrh_cli settings show --path "$MRH_SETTINGS"
```

設定與統計使用同一 profile。ordinary／Main／Fixed request、故障保留和 operator stop 分開列；requested model、native configured model 與 provider-confirmed identity 不混用。public CLI／native usage 可保存時另列，未知費用／quota 保持 null。停用與禁止外送不會刪除登入、session 或歷史；現在的保留環境也不在交接或單批結束時清理。

## 換到另一個明確選定的 workspace

以下是操作說明，本次沒有替其他 workspace 啟用。將路徑換成你已明確選定的專案，先停止該 home 的原生程序並停用／禁止外送：

```sh
MRH_WORKSPACE=/absolute/explicitly-chosen-workspace
mrh_cli settings disable --path "$MRH_SETTINGS"
mrh_cli settings configure --path "$MRH_SETTINGS" --deny-task-export
mrh_cli plugin prepare --root "$MRH_ROOT/plugin" --settings "$MRH_SETTINGS"   --scope-workspace "$MRH_WORKSPACE" --codex-binary "$MRH_CODEX_DIR/codex"
codex_cli plugin add model-routing-harness@model-routing-harness-local --json
mrh_cli settings configure --path "$MRH_SETTINGS" --clear-workspaces --allow-workspace "$MRH_WORKSPACE"
codex_cli -C "$MRH_WORKSPACE"
```

先完成官方 workspace／Hook trust review，再用前面的 permit／enable 指令並重開同 workspace CLI。原 home／登入沿用，不複製憑證或另建登入。prepare 會檢查版本、模型／effort、工作區和額外設定；若拒絕，維持停用並處理它指出的確切 scope 缺口，不改檢查或繞過保護。更動 owned home 的父模型／effort 後也要重新 prepare、官方 refresh／trust；更換 CLI 版本不代表路由已支援，新版本須另經版本驗證。不要把 Desktop、全域正式 home 或其他 AI 的模型清單支持當作本路徑已接通。

本機 source／venv 開發入口、合成 demo 與歷史驗證仍見 README 和 E3／E4G；實際使用以上獨立入口即可。


## E21 白名單設定入口（尚未接到日常 Hook）

專案已建立 `workspace-allowlist.local.json`；使用者後續已將 roots 改為 `/`，此現有設定保留，不回填 Code。它涵蓋本 Mac 所有 filesystem-backed cwd，不增加權限、不涵蓋其他 host 或缺失 cwd；完整說明見[白名單備註](workspace-allowlist.md)。該檔已被 Git 忽略，初始化不覆蓋既有檔案。可編輯嚴格 JSON：

```json
{"schema_version": 1, "roots": ["/absolute/canonical/workspace"]}
```

root 必須是唯一的絕對 canonical 路徑；空 roots 表示全部不准入。可攜範例為 [workspace-allowlist.json](../examples/workspace-allowlist.json)，預設空清單。E21 已驗證以下入口：

```sh
"$MRH_E21_ENTRY" settings configure --path /absolute/owned-profile/settings.json --workspace-allowlist-file /absolute/path/workspace-allowlist.local.json
"$MRH_E21_ENTRY" settings configure --path /absolute/owned-profile/settings.json --clear-workspace-allowlist-file
```

請替換範例路徑；只供 A 完成宿主接法後選取正確 owned profile，**本次不對保留的 E20 設定執行**。設定檔沒有新欄位時沿用 `allowed_workspaces`；明確選取檔案後以檔案為準，清除後才回到 legacy roots。檔案每次新 PreToolUse 重讀；缺失、格式錯誤或讀取失敗會警告並保留原呼叫，不退回較寬舊清單，也不建立新的事件記錄。已准入的 Post 收據仍可關聯，白名單後續編輯不會觸發重分級；disabled／外送 denied 仍保留原停用語義。

classifier 使用乾淨臨時 home，只為已確認 File 模式建立單一 auth 檔案引用。MRH 不讀／複製／輸出憑證；官方 CLI 可能依原有刷新機制寫回同一原檔。MRH 以自有跨程序鎖串行自己的 classifier，等待受 deadline／取消控制，並在取消時先結束自己的程序再清除引用與 scratch。它不協調其他 Codex 程序，也不自動切換 keyring、重登入或移除原 AGENTS。

日常 CLI／App 的已解析 child role／原模型資料來源仍未接通。因此本節不表示全域 Hook 已登錄、四級已替你設定，或完整日常路由已驗收。E21 已包含這份基礎 source，但保留的 E20 plugin 沒有更換。
