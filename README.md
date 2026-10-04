# Momo 購物網 & PChome 24h 全自動任務腳本

專為 **momo 購物網**（週年慶摸彩、天天簽到、mo 幣檢查）與 **PChome 24h**（天天簽到拿 P 幣）打造的自動化工具。支援 **多帳號並行**、**GitHub Actions 雲端定時排程**、**本地 Python 腳本** 與 **Bark 推播通知**。

---

## 🎯 支援功能

### 1. Momo 週年摸彩賺$999 (10/4 - 10/9 檔期)
- **開放時段**：每日 12 場（`09:10`、`10:10`、`11:10`、`13:10`、`15:10`、`16:10`、`17:10`、`18:10`、`19:10`、`20:10`、`21:10`、`22:10`）。
- **每人每日限搶一次智能檢查**：搶抽前自動驗證今日是否已成功，已完成者自動略過，未完成者持續搶抽直到抽中。
- **極速狙擊模式**：開抽前 3.5 秒（`XX:09:56.5`）預熱連線，前 0.2 秒（`XX:09:59.8`）扣扳機發送毫秒級 burst 連發。
- **多帳號並行**：多線程並行送出請求，多帳號同時在 `59.8s` 搶抽。
- **短網址自動還原**：支援傳入 `https://momo.dm/xxxxxx`，自動跳轉解析出真實活動代碼與獎項。

### 2. Momo 天天簽到 (dailycheckin)
- 自動抓取當日任務清單，模擬停留時間並完成任務領取 mo 點。
- 支援推薦/互助碼填寫與多帳號依序簽到。

### 3. PChome 24h 天天簽到拿 P 幣
- **換日時間**：**每日 08:00:00 重置**（名額有限，額滿截止）。
- 自動獲取當期活動、計算待簽天數的 `gift_id` 並送出簽到領取 P 幣。

### 4. PChome 24h【幸運抽籤】最高搶188P幣 (~10/31 檔期)
- **活動代碼**：`AC78080335`
- 自動取得檔期時段（如 `20:00 ~ 23:59`）與獎項清單（188P幣、88P幣、8P幣、1P幣）。
- 自動檢查抽獎上限，未抽過自動執行開獎，抽中即時發送 Bark 通知。

---

## 📁 核心檔案結構

| 檔案 | 說明 |
| :--- | :--- |
| `momo_bot.py` | Momo 週年摸彩定時搶抽腳本 (支援多帳號、狙擊、自動還原短網址) |
| `momo_checkin.py` | Momo 天天簽到任務自動化腳本 |
| `momo_coin.py` | Momo 幣與點數即將到期提醒模組 |
| `pchome_checkin.py` | PChome 24h 天天簽到自動領取 P 幣腳本 |
| `pchome_lottery.py` | PChome 24h 幸運抽籤最高搶 188P 幣腳本 (支援 AC78080335) |
| `cookie_extractor.html` | Cookie 快速提取教學與一鍵書籤產生工具 |
| `momo_tampermonkey.user.js` | Momo 瀏覽器油猴腳本 (右下角常駐一鍵複製 Cookie 懸浮按鈕) |
| `.github/workflows/` | GitHub Actions 雲端定時工作流程 |

---

## ⚙️ 快速設定（GitHub Actions 雲端自動執行）

無需電腦開機，由 GitHub 雲端自動在各時段執行：

### 1. 設定 Repository Secrets
進入 GitHub 儲存庫的 **Settings** -> **Secrets and variables** -> **Actions**，新增以下 Secret：

- **`MOMO_COOKIE`**（必填）：Momo 會員 Cookie。
  - **多帳號填寫方式**：各帳號 Cookie 之間使用 `---` 或換行分隔：
    ```text
    帳號1的完整Cookie字串
    ---
    帳號2的完整Cookie字串
    ```
- **`BARK_KEY`**（選填）：iOS Bark 推播 App 的 Key 或 URL，抽中獎項與簽到完成後將即時推播。
- **`PCHOME_COOKIE`**（選填）：PChome 會員 Cookie，多帳號亦使用 `---` 分隔。

### 2. 定時觸發設定
- **Momo 摸彩與簽到**：由 [cron-job.org](https://cron-job.org) 於各時段前 1 分鐘（`09:09`、`10:09` ... `22:09`）觸發 GitHub Actions API。
- **PChome 簽到**：由 GitHub Actions Cron 自動於每日早上 `08:00`（UTC `00:00`）觸發執行。

---

## 💻 本地端指令操作

### Momo 週年摸彩
```bash
# 1. 查詢各帳號今日摸彩與 mo 點紀錄
python3 momo_bot.py --query

# 2. 立即執行一次搶抽（時段前 4 分鐘內自動啟動 T-0.2s 狙擊連發）
python3 momo_bot.py --now

# 3. 指定活動短網址執行
python3 momo_bot.py --url "https://momo.dm/vIvvQf" --now
```

### Momo 天天簽到
```bash
python3 momo_checkin.py
```

### PChome 24h 天天簽到
```bash
python3 pchome_checkin.py
```

### PChome 24h 幸運抽籤
```bash
# 1. 查詢活動檔期與個人中獎紀錄
python3 pchome_lottery.py --query

# 2. 執行抽籤（支援多帳號，若已達上限自動略過）
python3 pchome_lottery.py
```

---


## 🍪 提取 Cookie 方式

Momo 與 PChome 的登入憑證包含 `HttpOnly` 欄位（如 `LOGINSESSION`、`ECC`），無法透過一般 JavaScript 讀取，提取方式如下：

1. 登入購物網網頁。
2. 按 `F12`（Mac: `Cmd + Option + I`）開啟開發者工具。
3. 切換至 **Network（網路）** 頁籤並重新整理（`F5` 或 `Cmd + R`）。
4. 點選任一請求（如 `cmmedm.jsp`），在右側 **Headers** 的 **Request Headers（請求標頭）** 找到 **`Cookie`**。
5. 右鍵點擊 **Copy value（複製值）**，貼入 `cookie.txt` 或 GitHub Secrets。

---

## ⚠️ 免責聲明與法律規範 (Disclaimer)

1. **僅供技術研究與個人學習**：本專案僅供程式語言學習、網路自動化測試及個人研究使用，開發者不鼓勵或提倡任何可能違反第三方平台服務條款之行為。
2. **服務條款與平台規範**：使用本工具前，請詳閱並嚴格遵守目標平台（包括但不限於富邦媒體科技股份有限公司 momo 購物網、網路家庭國際資訊股份有限公司 PChome 24h 等）之會員服務條款、使用者守則及活動辦法。使用者須自行確認使用行為之合法性與合規性。
3. **使用者自負風險**：本專案依「現狀（AS IS）」提供，不提供任何形式之明示或暗示擔保。因使用本工具可能導致之帳號異常、暫停使用、點數註銷、封鎖 IP 或任何衍生損失，使用者應自行評估並承擔全部風險與法律責任，本專案作者與貢獻者概不承擔任何直接、間接、附隨或衍生性賠償責任。
4. **禁止商業圖利與惡意破壞**：嚴禁將本專案用於任何商業營利、轉售、高頻惡意阻斷服務（DoS/DDoS）、擾亂目標伺服器正常運作或侵害他人權益之行為。若因不當使用致生民事、刑事或行政責任，由使用者全權負責。
5. **商標與智慧財產權宣告**：本專案中所提及之公司名稱、商標、標章及活動名稱（如「momo」、「PChome」等），其智慧財產權均屬其各原權利人所有。本專案非官方釋出，與上述各公司無任何官方關聯、合作、代言或授權關係。
6. **隱私與憑證安全**：Cookie、Token、API Key 等個人敏感認證資訊應妥善保管，切勿上傳至公開儲存庫（Public Repository）。使用者因私密金鑰洩漏衍生之資安問題與損失，須自行負責。

---

## 📄 授權條款 (License)

本專案採用 [MIT License](LICENSE) 釋出。

