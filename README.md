# Momo 購物網 全自動任務腳本

專為 **momo 購物網**（雙11知識王答題、週年慶摸彩、天天簽到、mo 幣檢查）打造的自動化工具。支援 **多帳號並行**、**GitHub Actions 雲端定時排程**、**本地 Python 腳本** 與 **Bark 推播通知**。

---

## 🎯 支援功能

### 1. Momo 雙11 知識王自動答題 (10/23 - 10/31 檔期)
- **開放時段**：每日 6 場（`10:11`、`12:11`、`14:11`、`18:11`、`20:11`、`22:11`）。
- **萬筆即時題庫**：本地快取與雲端同步機制，高命中率秒答。
- **Google Gemini AI 智慧解題**：支援多模態圖文辨識，未知題目自動推理並反向學習記錄至題庫。
- **自動兌換 50 mo 點**：達到 600 分門檻全自動送出兌換。

### 2. Momo 好運轉轉樂
- **每人每時段限轉一次**：搶抽前智能驗證該帳號「當前時段」是否已轉過，已完成者自動略過。
- **極速狙擊模式**：開抽前 3.5 秒（`XX:59:56.5`）預熱連線，前 0.2 秒（`XX:59:59.8`）扣扳機發送毫秒級 burst 連發。
- **多帳號並行**：多線程並行送出請求，多帳號同時搶抽。
- **短網址自動還原**：支援傳入 `https://momo.dm/xxxxxx`，自動跳轉解析出真實活動代碼與獎項。

### 3. Momo 天天簽到 (dailycheckin)
- 自動抓取當日任務清單，模擬停留時間並完成任務領取 mo 點。
- 支援推薦/互助碼填寫與多帳號依序簽到。

### 4. Momo 幣與點數即將到期檢查
- 自動查詢會員帳戶可用 mo 幣、即將到期點數，並於到期前發出推播提醒。

---

## 📁 核心檔案結構

| 檔案 | 說明 |
| :--- | :--- |
| `momo_quiz.py` | Momo 雙11 知識王自動答題與自動兌換腳本 (支援 AI、多帳號並行) |
| `momo_bot.py` | Momo 週年摸彩定時搶抽腳本 (支援多帳號、狙擊、自動還原短網址) |
| `momo_checkin.py` | Momo 天天簽到任務自動化腳本 |
| `momo_coin.py` | Momo 幣與點數即將到期提醒模組 |
| `feebee_checkin.py` | 飛比價格 (Feebee) 天天簽到腳本 |
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
- **`GEMINI_API_KEY`**（選填）：Google Gemini API Key，用於題庫未命中時進行多模態 AI 即時解題。
- **`FEEBEE_COOKIE`**（選填）：飛比價格簽到 Cookie。

### 2. 定時觸發設定
- **Momo 知識王、轉轉樂與簽到**：由 [cron-job.org](https://cron-job.org) 或 GitHub Actions 排程定時觸發執行。

---

## 💻 本地端指令操作

### Momo 雙11 知識王
```bash
# 立即執行一次答題 (支援自動兌換)
python3 momo_quiz.py --now --auto-claim
```

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

### Momo 幣餘額與到期檢查
```bash
python3 momo_coin.py
```

---

## 🍪 提取 Cookie 方式

Momo 登入憑證包含 `HttpOnly` 欄位（如 `LOGINSESSION`），無法透過一般 JavaScript 讀取，提取方式如下：

1. 登入 momo 購物網網頁。
2. 按 `F12`（Mac: `Cmd + Option + I`）開啟開發者工具。
3. 切換至 **Network（網路）** 頁籤並重新整理（`F5` 或 `Cmd + R`）。
4. 點選任一請求（如 `cmmedm.jsp`），在右側 **Headers** 的 **Request Headers（請求標頭）** 找到 **`Cookie`**。
5. 右鍵點擊 **Copy value（複製值）**，貼入 `cookie.txt` 或 GitHub Secrets。
*(亦可點開專案內 `cookie_extractor.html` 使用一鍵書籤快速提取)*

---

## ⚠️ 免責聲明與法律規範 (Disclaimer)

1. **僅供技術研究與個人學習**：本專案僅供程式語言學習、網路自動化測試及個人研究使用，開發者不鼓勵或提倡任何可能違反第三方平台服務條款之行為。
2. **服務條款與平台規範**：使用本工具前，請詳閱並嚴格遵守富邦媒體科技股份有限公司 momo 購物網之會員服務條款、使用者守則及活動辦法。使用者須自行確認使用行為之合法性與合規性。
3. **使用者自負風險**：本專案依「現狀（AS IS）」提供，不提供任何形式之明示或暗示擔保。因使用本工具可能導致之帳號異常、暫停使用、點數註銷、封鎖 IP 或任何衍生損失，使用者應自行評估並承擔全部風險與法律責任，本專案作者與貢獻者概不承擔任何直接、間接、附隨或衍生性賠償責任。
4. **禁止商業圖利與惡意破壞**：嚴禁將本專案用於任何商業營利、轉售、高頻惡意阻斷服務（DoS/DDoS）、擾亂目標伺服器正常運作或侵害他人權益之行為。若因不當使用致生民事、刑事或行政責任，由使用者全權負責。
5. **商標與智慧財產權宣告**：本專案中所提及之公司名稱、商標、標章及活動名稱（如「momo」），其智慧財產權均屬其原權利人所有。本專案非官方釋出，與上述公司無任何官方關聯、合作、代言或授權關係。
6. **隱私與憑證安全**：Cookie、Token、API Key 等個人敏感認證資訊應妥善保管，切勿上傳至公開儲存庫（Public Repository）。使用者因私密金鑰洩漏衍生之資安問題與損失，須自行負責。
