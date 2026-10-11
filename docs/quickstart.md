# 啟用已驗證的本機 CLI 路徑

使用現有 E19 獨立套件與已登入、保留的同一 home，不需 Python、SDK 或 API key。普通便宜模型切換、同 Goal 的兩回 fresh classification／lifecycle，以及 Top Fixed 的較高 configured child／結果已由 A 驗收。D48 的 Top/0.99、native Main blocked、沒有 child 與同一 Luna parent 完成也已由 A 驗收。完整 R1、Desktop／原全域 home 與自主 Goal 續跑尚未完成，見 [E19 實際證據](e19-subscription-classifier.md)。目前 MRH disabled／task 外送 denied，啟用要由以下明確指令進行。Source 已按責任分層，但以下仍使用已接受的 E19 套件；新整合套件交付前不更換這個 session 的 plugin／登入。

## 在終端貼上這組入口

```sh
MRH_ROOT=/private/tmp/mrh-e19-d45-mrc5zw54
MRH_ENTRY=/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.3.0-e19-macos-arm64/mrh
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
