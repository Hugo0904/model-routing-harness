# Hook 直接記錄

`mrh ctrl diagnostics on|off|status|clear` 用法維持不變，新安裝預設關閉。開啟後由原本 Hook 在失敗時直接嘗試寫一筆診斷；沒有收集器、UDP、常駐程序或登入啟動，不另外啟動 CMD／Python／執行緒。

```sh
mrh ctrl diagnostics on
mrh ctrl diagnostics status --json
mrh ctrl diagnostics off
mrh ctrl diagnostics clear
```

狀態顯示 `mode: direct`、開關及兩個完整檔案路徑。`resident: false` 與未註冊的 `login` 表示本版不建立常駐或登入項；舊版尚未完成移除時會明確標示 `migration_required`，不假裝已移除。`ready` 只表示設定及預建記錄檔通過檢查，不是服務健康狀態，也不保證每筆寫入成功。控制獨立於路由 settings，無須 provider 或 DB。

## 兩個最新錯誤檔

日誌根沿用 `locations.runtime_root()/diagnostics/hook-observation`，以 status 的路徑為準，不依賴 cwd，不回退系統 tmp。Codex 寫 `latest-codex.json`，Claude 寫 `latest-claude.json`；每檔固定最多 512 bytes，新的錯誤覆寫舊的，同一平台的父子也可能互蓋。沒有 ring、queue、輪替、補送、重試或背景工作。

on 只預建這兩個私有 owned 檔。Hook 沿既有 stage／白名單序列化與 stderr 隱私 guard，在失敗時讀取有上限的設定，核對 private owner／ACL、marker、no-follow、regular file／hardlink／大小，然後僅嘗試一次從檔案起點覆寫固定長度資料。不建立檔案、不等鎖、不截斷或追加。檔案失蹤、無權、忙碌、不安全、短寫或其他錯誤都放棄當次診斷，保留原 Hook stdout、rc、deadline 與清理行為。

紀錄只有時間、版本、平台及既有 `stage`、內建 exception class、整數或 null 的 `winerror`／`child_rc`、受限 `elapsed_ms`。不記輸入、輸出正文、任務名稱、例外訊息／堆疊、環境、憑證或路徑。尾端空白只是固定檔案大小，正常資料仍是 JSON。

直接磁碟 I/O 不能承諾絕對零阻塞。父子或同時 Hook 互相覆寫、產生壞紀錄、漏記都可接受；不為防止遺失增加鎖、程序或重試。需要時讓診斷多開幾天收集即可，不能把這兩個檔當完整事件帳本。

## 舊版與保留

v1 enabled 或 off 配置都會在正常 after_install／on／off 移轉時，先沿原有 native identity／owned metadata 的 remove 移除舊 LaunchAgent／Scheduled Task，再存成 direct 配置。移除程式只保留 inspect/remove，沒有 install/start、提權或任意 PID kill；Windows 的必要移除查詢不另開視窗。未知 ownership 或移除失敗會保留資料並回報，不繞過平台政策。

既有 `events-*.jsonl`、設定、統計、keys、packet、備份與驗收證據不刪除。off 只關閉記錄並處理舊登入殘留；可重入。clear 須先 off，而且只清空這兩個新記錄檔，舊 events 日誌和其他檔案仍保留。正常升級沿用 direct 開關；Mac 原卸載入口先執行 off，Windows 不另建卸載框架。

本次只驗證改變的寫檔／開關／移除邊界，沿用已通過的 stage、隱私與 Hook guard 證據，不重跑舊路由／故障矩陣、provider 或 DB 測試。Windows 原生採用由原執行者另行讀回，Mac 檔案測試不能當成 Windows native PASS。歷史 editable Hook `{}` 根因仍未知，不列為本次額外調查。
