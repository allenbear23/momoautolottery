# Momo 桃金日好運抽抽樂 & 天天簽到 自動化工具

針對 momo 購物網「好運抽抽樂」與「天天簽到（dailycheckin）」設計之自動化工具，支援 **GitHub Actions 雲端定時執行**、**本地 Python 腳本** 與 **瀏覽器 Tampermonkey 腳本**。

---

## 簽到活動原理 (天天簽到)
- 活動短網址：`https://momo.dm/UQUNaQ` (跳轉至 `https://ma.momoshop.com.tw/edm/dailycheckin?referral=2b4b924f6cd7a33d8279a2b80172d730`)
- **API 端點**：
  - 查詢當期簽到：`GET https://ma.momoshop.com.tw/api/campaign/game/latest`
  - 查詢個人進度：`GET https://ma.momoshop.com.tw/api/campaign/game/{missionId}/activity`
  - 執行簽到任務：`POST https://ma.momoshop.com.tw/api/campaign/game/{missionId}/play`
    - Payload: `{"task_group_seq": <日序號>, "task_seq": <任務序號>}`
- 腳本：[momo_checkin.py](file:///Users/allen/.gemini/antigravity-ide/scratch/momo_lottery/momo_checkin.py) 自動抓取當日任務清單並逐一模擬完成。

---

## 運作原理

1. **活動機制**：
   - 每日 5 個時段開放抽獎：`09:00`、`13:00`、`16:00`、`19:00`、`21:00`。
   - 每個時段內限抽 2 次。
   - 每次抽獎可能抽中金額（mo 點）或字卡（「桃」、「金」、「日」）。集齊三字可歸戶所有已累積 mo 點。

2. **API 分析**：
   - **抽獎請求**：
     - **URL**: `POST https://event.momoshop.com.tw/game/momoLottery.PROMO`
     - **Headers**:
       - `Content-Type: application/json;charset=utf-8`
       - `Origin: https://www.momoshop.com.tw`
       - `Referer: https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O8dV4oaCUPZ&n=1`
       - `Cookie: <登入憑證>`
     - **Payload (抽獎)**:
       ```json
       {
         "doAction": "lottery",
         "m_promo_no": "U96091900001",
         "dt_promo_no": "D96091900001"
       }
       ```
     - **Payload (查詢紀錄)**:
       ```json
       {
         "doAction": "qry",
         "m_promo_no": "U96091900001",
         "dt_promo_no": "D96091900001"
       }
       ```

3. **核心狀態碼說明**：
   - `OK`: 抽獎成功或查詢成功。
   - `A` / `A_EX` / `EA`: 已超過本時段抽獎次數上限。
   - `L`: 登入憑證無效或過期，需重新登入並更新 Cookie。
   - `FULL`: 名額已滿。
   - `D`: 非活動期間。

---

## 使用方式

### 方式一：GitHub Actions 自動執行（推薦）

無需保持電腦開機，由 GitHub 雲端定時觸發：

1. **設定 Secret**：
   - 前往 GitHub 儲存庫的 **Settings** -> **Secrets and variables** -> **Actions**。
   - 點擊 **New repository secret**。
   - **Name**: `MOMO_COOKIE`
   - **Value**: 貼上瀏覽器登入 momo 後的完整 Cookie 字串。
2. **排程時段**：
   - 工作流程檔案位於 `.github/workflows/momo_lottery.yml`。
   - 設定為 Cron `0 1,5,8,11,13 * * *`（對應台灣時間 UTC+8 之 `09:00`, `13:00`, `16:00`, `19:00`, `21:00`）。
3. **手動測試**：
   - 在 GitHub 頁面切換至 **Actions** 分頁，選擇「Momo Lottery Auto Draw」，點擊「Run workflow」。

---

### 方式二：本地 Python 腳本

適用於本機排程或即時測試：

```bash
# 1. 查詢目前抽獎紀錄與已累積 mo 點
python3 momo_bot.py --cookie "你的_COOKIE" --query

# 2. 立即執行本時段抽獎（自動抽 2 次）
python3 momo_bot.py --cookie "你的_COOKIE" --now

# 3. 常駐背景定時排程（於 09:00, 13:00, 16:00, 19:00, 21:00 自動執行）
python3 momo_bot.py --cookie "你的_COOKIE" --schedule
```

*註：亦可建立 `cookie.txt` 並將 Cookie 貼入該檔案，執行時即可省略 `--cookie` 參數。`cookie.txt` 已列入 `.gitignore`，不會被上傳。*

---

### 方式三：Tampermonkey 油猴腳本

適用於瀏覽器保持開啟活動頁面情境：

1. 安裝瀏覽器套件 [Tampermonkey](https://www.tampermonkey.net/)。
2. 新增腳本並匯入 `momo_tampermonkey.user.js` 內容。
3. 開啟活動頁面並保持分頁開啟，腳本將於指定時段自動點擊抽獎。

---

## 免責聲明

1. 本專案僅供程式技術研究、自動化測試與個人學習交流用途，不提供任何商業使用。
2. 本工具非 momo 購物網官方發佈，使用本工具可能存在帳號被網站風控、限制抽獎或停權等潛在風險，請使用者自行評估承擔。
3. 請勿使用本工具進行任何破壞伺服器穩定性、高頻請求或妨礙其他用戶正常權益之行為。
4. 本專案作者不對因使用或無法使用本工具所產生之任何直接或間接損失承擔任何法律與經濟責任。
