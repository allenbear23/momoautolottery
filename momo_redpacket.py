#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 雙11 狂撒百萬驚喜 (紅包雨) 自動搶紅包腳本
=============================================
支援：
1. 11/1 檔期每日 18 個時段 (均為 11 分) 自動對齊
2. 多帳號並行發射、毫秒級連線預熱與狙擊
3. 自動從攻略頁或 couponRain.js 探測並動態更新 m_promo_no / dt_promo_no
4. Bark 推播中獎通知
"""

import sys
import os
import time
import json
import re
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
import concurrent.futures

# 自動載入 .env
def load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

load_dotenv()

# 攻略頁與專屬活動頁網址
DEFAULT_EDM_URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O7ylWmQ3frf&n=1"
API_URL = "https://event.momoshop.com.tw/promoMechReg.PROMO"

# 11/1 正式活動代碼 (解析自 it_constant.js)
DEFAULT_M_PROMO_NO = "U96110100003"
DEFAULT_DT_PROMO_NO = "D96110100001"

# 11/1 每日 18 個時段 (各時段 11 分)
SLOTS = [
    (0, 11),  (1, 11),
    (8, 11),  (9, 11),  (10, 11), (11, 11),
    (12, 11), (13, 11), (14, 11), (15, 11),
    (16, 11), (17, 11), (18, 11), (19, 11),
    (20, 11), (21, 11), (22, 11), (23, 11)
]
SCHEDULE_TIMES = [f"{h:02d}:{m:02d}" for h, m in SLOTS]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoShop",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O7ylWmQ3frf&n=1"
}

PRIZE_MAP = {
    "mo_999": "🧧 momo幣 $999",
    "mo_111": "🧧 momo幣 $111",
    "mo_11": "🧧 momo幣 $11",
    "mo_1": "🧧 momo幣 $1",
    "coupon_88": "🎫 88折折價券",
    "coupon_111": "🎫 $111折價券",
    "coupon_222": "🎫 $222折價券",
    "coupon00": "🎫 $111折價券"
}

RETURN_MESSAGES = {
    "INS": "恭喜中獎！",
    "FULL": "本時段名額已額滿",
    "A": "您於此時段已搶過紅包",
    "END": "本時段活動已結束",
    "D": "非活動時間或未到開搶時段",
    "L": "登入憑證逾期，請重新登入",
    "ERR": "系統繁忙，請稍後再試"
}


def send_bark_notification(title: str, body: str):
    bark_key = os.getenv("BARK_KEY", "").strip()
    if not bark_key:
        return
    try:
        url = bark_key if bark_key.startswith("http") else f"https://api.day.app/{bark_key}/"
        payload = {
            "title": title,
            "body": body,
            "group": "momo_redpacket",
            "icon": "https://picasso-frontend.momoshop.com.tw/mmp-activity/quiz-game/icon.png"
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=4)
    except Exception as e:
        print(f"推播失敗: {e}")


def get_user_display_name(cookie: str, default_idx: int = 1) -> str:
    m = re.search(r'loginUser=([^;]+)', cookie)
    if m:
        try:
            val = m.group(1).replace('+', ' ')
            name = urllib.parse.unquote(val).strip()
            if name:
                return f"帳號 {default_idx} ({name})"
        except Exception:
            pass
    return f"帳號 {default_idx}"


def load_all_cookies(cookie_arg: str = None) -> list:
    raw = ""
    if cookie_arg:
        raw = cookie_arg
    else:
        cookie_file = os.path.join(os.path.dirname(__file__), "cookie.txt")
        if os.path.exists(cookie_file):
            with open(cookie_file, "r", encoding="utf-8") as f:
                raw = f.read()
        else:
            raw = os.getenv("MOMO_COOKIE", "")

    cookies = []
    blocks = raw.split("---") if "---" in raw else raw.splitlines()
    for b in blocks:
        clean = b.strip()
        if not clean or clean.startswith("#"):
            continue
        if any(k in clean for k in ("LOGINSESSION", "st=", "_atrk", "isEN")):
            cookies.append(clean)
    return cookies


def sniff_promo_params(edm_url: str = DEFAULT_EDM_URL) -> tuple:
    """自動探測最新紅包雨的 mPromoNo 與 dtPromoNo"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在探測 momo 11/1 紅包雨活動參數...")
    try:
        req = urllib.request.Request(edm_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # 1. 優先從 it_init.js 與同層目錄之 it_constant.js 抓取正式設定檔
        m_it = re.search(r'src=[\"\']([^\"\']*it_init\.js[^\"\']*)[\"\']', html)
        if m_it:
            init_url = m_it.group(1)
            if init_url.startswith("//"):
                init_url = "https:" + init_url
            base_dir = init_url.rsplit("/", 1)[0]
            ts = init_url.split("?")[1] if "?" in init_url else ""
            it_url = f"{base_dir}/it_constant.js?{ts}" if ts else f"{base_dir}/it_constant.js"
            try:
                it_req = urllib.request.Request(it_url, headers=HEADERS)
                with urllib.request.urlopen(it_req, timeout=6) as it_resp:
                    it_code = it_resp.read().decode("utf-8", errors="ignore")
                    mno_m = re.search(r'mno\s*:\s*[\"\']([^\"\']+)[\"\']', it_code)
                    dtno_m = re.search(r'firstDtNo\s*:\s*[\"\']([^\"\']+)[\"\']', it_code)
                    if mno_m and dtno_m:
                        m_val = mno_m.group(1)
                        dt_val = dtno_m.group(1)
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 探測成功 (it_constant)！m_promo_no={m_val}, dt_promo_no={dt_val}")
                        return m_val, dt_val
            except Exception:
                pass

        # 2. 從 couponRain.js 抓取
        m_js = re.search(r'src=[\"\']([^\"\']*couponRain\.js[^\"\']*)[\"\']', html)
        if m_js:
            js_url = m_js.group(1)
            if js_url.startswith("//"):
                js_url = "https:" + js_url
            try:
                js_req = urllib.request.Request(js_url, headers=HEADERS)
                with urllib.request.urlopen(js_req, timeout=6) as js_resp:
                    js_code = js_resp.read().decode("utf-8", errors="ignore")
                    m_m = re.search(r'mPromoNo\s*:\s*[\"\']([^\"\']+)[\"\']', js_code)
                    dt_m = re.search(r'dtPromoNo\s*:\s*[\"\']([^\"\']+)[\"\']', js_code)
                    if m_m and dt_m:
                        m_val = m_m.group(1)
                        dt_val = dt_m.group(1)
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 探測成功 (couponRain)！m_promo_no={m_val}, dt_promo_no={dt_val}")
                        return m_val, dt_val
            except Exception:
                pass

        # 3. 正則比對頁面中可能的 Promo 代碼
        promo_match = re.search(r'[\"\']([UD]961101\w+)[\"\']', html)
        if promo_match:
            code = promo_match.group(1)
            m_val = "U" + code[1:]
            dt_val = "D" + code[1:]
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 頁面探測到活動代碼：{m_val} / {dt_val}")
            return m_val, dt_val
    except Exception as e:
        print(f"探測異常: {e}")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 使用預設代碼：{DEFAULT_M_PROMO_NO} / {DEFAULT_DT_PROMO_NO}")
    return DEFAULT_M_PROMO_NO, DEFAULT_DT_PROMO_NO


def send_draw_request(cookie: str, m_promo_no: str, dt_promo_no: str) -> dict:
    headers = dict(HEADERS)
    headers["Cookie"] = cookie.strip()
    headers["Content-Type"] = "application/json;charset=utf-8"

    payload = {
        "m_promo_no": m_promo_no,
        "dt_promo_no": dt_promo_no
    }
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"returnMsg": "HTTP_ERR", "code": e.code}
    except Exception as e:
        return {"returnMsg": "NET_ERR", "error": str(e)}


def grab_redpacket_single_account(cookie: str, account_label: str, m_promo_no: str, dt_promo_no: str):
    """單一帳號執行搶紅包"""
    print(f"\n🚀 [{datetime.now().strftime('%H:%M:%S')}] [{account_label}] 發射搶紅包請求...")
    res = send_draw_request(cookie, m_promo_no, dt_promo_no)

    status = res.get("returnMsg", "")
    prize_key = res.get("prize", "")
    status_desc = RETURN_MESSAGES.get(status, f"未知代碼 ({status})")

    if status == "INS":
        prize_name = PRIZE_MAP.get(prize_key, f"獎品代碼: {prize_key}")
        msg = f"🎉 搶到紅包！獲得：{prize_name}"
        print(f"[{account_label}] {msg}")
        send_bark_notification("momo 雙11 搶紅包成功！", f"【{account_label}】{msg}")
    elif status == "A":
        print(f"[{account_label}] ℹ️ {status_desc}")
    elif status == "FULL":
        print(f"[{account_label}] ⚡ {status_desc}")
    else:
        print(f"[{account_label}] ⚠️ 回應：{status_desc} | 回傳內容: {res}")


def run_sniper_session(cookies: list, m_promo_no: str, dt_promo_no: str):
    """多帳號並行極速搶紅包"""
    print(f"\n========================================================================")
    print(f"🧧 開始執行 11/1 搶紅包任務 | 帳號數: {len(cookies)} 組")
    print(f"🎯 活動代碼: mPromoNo={m_promo_no}, dtPromoNo={dt_promo_no}")
    print(f"========================================================================")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cookies)) as ex:
        futures = [
            ex.submit(grab_redpacket_single_account, c, get_user_display_name(c, idx), m_promo_no, dt_promo_no)
            for idx, c in enumerate(cookies, start=1)
        ]
        concurrent.futures.wait(futures)


def main():
    parser = argparse.ArgumentParser(description="Momo 雙11 狂撒百萬驚喜 (紅包雨) 自動搶紅包腳本")
    parser.add_argument("--now", action="store_true", help="立即執行一次搶抽")
    parser.add_argument("--m-promo", help="指定 m_promo_no")
    parser.add_argument("--dt-promo", help="指定 dt_promo_no")
    parser.add_argument("--url", default=DEFAULT_EDM_URL, help="指定活動頁或攻略頁網址")
    parser.add_argument("--silent-if-limit", action="store_true", help="若非開放時段或已搶過則不發送推播")
    args = parser.parse_args()

    cookies = load_all_cookies()
    if not cookies:
        print("❌ 未偵測到有效 Cookie，請在 cookie.txt 設定憑證！")
        sys.exit(1)

    # 取得或探測活動代碼
    if args.m_promo and args.dt_promo:
        m_promo = args.m_promo
        dt_promo = args.dt_promo
    else:
        m_promo, dt_promo = sniff_promo_params(args.url)

    if args.now:
        run_sniper_session(cookies, m_promo, dt_promo)
        return

    # 常駐定時狙擊模式 (監聽 18 個時段)
    print(f"\n🕒 已進入 11/1 紅包雨定時狙擊監控模式...")
    print(f"📅 每日 18 個開搶時段：{', '.join(SCHEDULE_TIMES)}")

    while True:
        now = datetime.now()
        # 尋找下一個最近時段
        target_dt = None
        for h, m in SLOTS:
            slot_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if slot_time > now:
                target_dt = slot_time
                break

        if not target_dt:
            # 今日時段已過，目標定在明日第一個時段 00:11
            import datetime as dt
            tomorrow = now + dt.timedelta(days=1)
            target_dt = tomorrow.replace(hour=SLOTS[0][0], minute=SLOTS[0][1], second=0, microsecond=0)

        delta = (target_dt - now).total_seconds()
        print(f"[{now.strftime('%H:%M:%S')}] 距下個開搶時段 {target_dt.strftime('%H:%M')} 尚有 {int(delta)} 秒...")

        # 若超過 10 秒，先睡眠
        if delta > 10:
            time.sleep(delta - 6)
            continue

        # 倒數 5 秒內，高頻對齊時間並於 T-0.2 秒扣扳機
        while True:
            cur = datetime.now()
            diff = (target_dt - cur).total_seconds()
            if diff <= 0.2:
                print(f"[{cur.strftime('%H:%M:%S.%f')[:12]}] 🎯 觸發狙擊開搶！")
                run_sniper_session(cookies, m_promo, dt_promo)
                time.sleep(15)  # 避免同秒重複觸發
                break
            time.sleep(0.05)


if __name__ == "__main__":
    main()
