# GitHub 同名重建草案（尚未執行）

原意是由擁有者刪除舊 repository、建立同名空 repository，確認後才由乾淨候選作一般首次 push。先前對既有 repository 改寫 main 的方式，沒有完成這個步驟。本次只準備可審閱方案與唯讀盤點，不刪除、不重建、不 push，也不改寫本機 main 歷史。

## 先保留什麼

保留目前工作樹、未提交修改、原始證據與既有完整備份；不因重建再複製一份完整備份。僅把備份之後新增的必要原件、來源變更及驗收回執補存到原備份的增量目錄，列明路徑與雜湊。正式 profile、資料庫、金鑰安全儲存與已安裝 runtime 不刪除、不上傳。

2026-10-22 唯讀 API 盤點：public、預設分支 main、非 fork，fork 計數 0；issues、PR、releases、tags、webhooks、deploy keys、Actions secrets／variables、environments 及 rulesets 均回空。Actions 啟用。列表最多第一頁 100 筆，不能將截斷結果當完整盤點。此處空集合沒有截斷問題。

同日補充 GET 讀回：main protection 為 HTTP 404，訊息明確為 `Branch not protected`，因此目前 main 沒有分支保護；協作者 1、團隊 0，不公開個人身分。Pages 為 HTTP 404 `Not Found`，保留這個結果，不據此推論其他功能或資料不存在。`/installation` 為 HTTP 401 `A JSON web token could not be decoded`，未取得有效的 App 驗證結果，不能當作沒有 GitHub Apps 整合。

wiki 的唯讀 refs 查詢回 exit 128 `Repository not found`，本次未取到 wiki refs，不能當成已備份 wiki。尚未取得有效的 Apps 設定清單；未登入的 Settings 頁面回 404 也不能證明沒有整合。

未知項目仍需在刪除前由已登入的擁有者確認：wiki 實際頁面及保留方式、Pages 的完整狀態、GitHub Apps 整合，以及需要保留的個別權限與其他設定。API 無法讀回的項目不當成不存在；不要輸出 secret 值、hook URL 或其他敏感設定。這些未核實項目不阻擋文件與候選準備，但需要在實際刪除前處理。私人盤點回執留本機，不納入公開候選。

## 人工操作與後續發布

1. A 審閱候選內容與差異驗證，使用者確認刪除會失去的 repository 資料及哪些項目要重建。未知設定若仍需保留，先完成可復原盤點。
2. 候選只含正式公開檔案與必要授權聲明，排除 runtime、紀錄、證據、備份、憑證及個人路徑。以本機一般 commit 保留本次修正供審閱；此時不先改寫 main 或製造另一份正式根歷史。
3. 使用者在 GitHub 刪除 `Hugo0904/model-routing-harness`，再建立同名、相同公開性的**空** repository，不初始化 README、LICENSE 或 `.gitignore`。這是實際刪除，需在看到本草案及保留清單後明確確認並操作。
4. 使用者確認空 repository 已建立，並核准穩定候選的內容／tree 與正常首次 push。屆時才產生單一無父 commit 的公開根，author／committer 為 `Hugo0904 <12891599+Hugo0904@users.noreply.github.com>`，只將 main 以一般 push 發布；不恢復舊 refs、tags 或備份 branches。
5. 讀回新 repository identity、remote refs、main 父數與 tree，核對核准候選；恢復使用者確認的必要設定。發布、Mac／Windows 採用與 A 接受各自記錄，不能以 push 成功代替採用或驗收。

依 [GitHub 刪除 repository 說明](https://docs.github.com/en/repositories/creating-and-managing-repositories/deleting-a-repository)，刪除 public repository 不會刪除它的 public forks，部分資料／權限也會失去。因此先確認需要保留的 repository 資料；目前 fork 計數 0 不能保證沒有其他人的 clone。

依 [GitHub 敏感資料移除說明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)，舊 clone、fork 或快取引用仍可能保存舊內容。重建不能保證所有舊 SHA、快取或第三方副本消失，也不表示 GitHub Support 已清除任何資料。本草案不聯絡 Support、不宣稱全面抹除。

## Mac／Windows 舊 clone 如何遷移

兩台機器先保留各自 dirty checkout、未推送 commit 與必要本機資料，保持原件及現有安裝可復原。新公開根核准發布後，clone 到另一個乾淨目錄，核對 remote main 的 commit／tree。不要把舊歷史 merge、pull 或 push 回新 repository。

必要但尚未發布的修改，以審閱過的檔案差異逐項移植到新 clone，重新檢查公開內容；不恢復 `.git`、runtime、憑證或整份舊工作樹。已安裝版本若仍綁舊 checkout，沿原安裝參數從新 clone 更新並核對實際專案根、Hook、PATH 及資料保留，採用成功前不刪舊 checkout。這些未來採用步驟要在重建已確認後執行，本次不預先重裝或重跑舊驗證。
