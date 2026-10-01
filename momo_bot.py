#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 週年慶-週年摸彩賺$999 (10/1 - 10/3) 極速定時搶抽腳本
支援多帳號並行搶抽、ESM/Legacy配置解析、12個時段智能對齊與 Bark 推播
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

DEFAULT_EVENT_URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O7ylWmQ3frf&n=1"
DEFAULT_M_PROMO_NO = "U96100100002"
DEFAULT_DT_PROMO_NO = "D96100100001"
DEFAULT_TITLE = "週年摸彩賺$999"

# 10/1-10/3 每日 12 個開放時段 (均為 10 分整)
SLOTS = [
    (9, 10), (10, 10), (11, 10), (13, 10),
    (15, 10), (16, 10), (17, 10), (18, 10),
    (19, 10), (20, 10), (21, 10), (22, 10)
]
SCHEDULE_TIMES = [f"{h:02d}:{m:02d}" for h, m in SLOTS]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoShop"
}

RETURN_MESSAGES = {
    'OK': '成功',
    'INS': '恭喜獲得獎項！',
    'A': '您已經參加過本時段了！',
    'A_EX': '本時段或本活動參加次數已達上限！',
    'FULL': '名額已經額滿！',
    'E_CN': '名額已經額滿！',
    'L': '請重新登入會員 (Cookie 已過期或無效)',
    'D': '請於活動時間內參加活動 (時段尚未開放)',
    'NOT_USED': '尚未符合活動參加資格或時段尚未開放',
    'NOT_APP': '請在 momo APP 參加活動',
    'NOT_WEB': '請於 momo 網站指定入口參加活動',
    'ERR': '系統繁忙，請稍後再試',
    'ERROR': '系統繁忙，請稍後再試',
    'E_RATELIMIT': '系統忙線中，請稍後再試'
}

GIFT_NAMES = {
    "mo_1": "$1 mo點",
    "mo_5": "$5 mo點",
    "mo_10": "$10 mo點",
    "mo_100": "$100 mo點",
    "mo_999": "$999 mo點",
    "coupon_100": "$100折價券",
    "coupon_300": "$300折價券",
    "coupon_400": "$400折價券",
    "coupon00": "$200折價券"
}

ACTIVE_CONFIG = {
    "domain": "https://event.momoshop.com.tw",
    "url": DEFAULT_EVENT_URL,
    "m_promo_no": DEFAULT_M_PROMO_NO,
    "dt_promo_no_array": [DEFAULT_DT_PROMO_NO],
    "title": DEFAULT_TITLE
}


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
    """
    載入一至多個帳號的 Cookie。
    支援：
    1. cookie.txt 每行一個帳號 (支援 # 註解或以 --- 分隔區塊)
    2. 環境變數 MOMO_COOKIE 換行或 --- 分隔多個 Cookie
    3. 命令列 --cookie
    """
    cookies = []
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

    if "---" in raw:
        blocks = raw.split("---")
    else:
        blocks = raw.splitlines()

    for b in blocks:
        clean = b.strip()
        if not clean or clean.startswith("#"):
            continue
        # 簡易驗證是否包含 momo 憑證關鍵欄位
        if any(k in clean for k in ("LOGINSESSION", "st=", "_atrk", "isEN")):
            cookies.append(clean)

    return cookies


def fetch_page(url: str, timeout: int = 8) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def fetch_promo_config(edm_url: str):
    """
    從 EDM 頁面解析活動參數，支援 ESM (it_constant.js) 與舊版 (spinRotateConfig.js)
    """
    try:
        html = fetch_page(edm_url, timeout=10)
        if not html:
            return None

        # 優先檢測 ESM 架構 (it_init.js -> it_constant.js)
        m_it = re.search(r'src=[\"\']([^\"\']*it_init\.js[^\"\']*)[\"\']', html)
        if m_it:
            it_url = m_it.group(1)
            if it_url.startswith("//"):
                it_url = "https:" + it_url
            base = it_url.rsplit('/', 1)[0]
            const_url = f"{base}/it_constant.js"
            const_js = fetch_page(const_url, timeout=10)
            if const_js:
                m_no_m = re.search(r'mno\s*:\s*[\"\']([^\"\']+)[\"\']', const_js)
                dt_no_m = re.search(r'firstDtNo\s*:\s*[\"\']([^\"\']+)[\"\']', const_js)
                api_m = re.search(r'API_BASE\s*=\s*[\"\']([^\"\']+)[\"\']', const_js)

                m_no = m_no_m.group(1) if m_no_m else DEFAULT_M_PROMO_NO
                dt_no = dt_no_m.group(1) if dt_no_m else DEFAULT_DT_PROMO_NO
                domain = api_m.group(1) if api_m else "https://event.momoshop.com.tw"

                # 解析獎項定義
                gifts = re.findall(r'(\w+)\s*:\s*\{[^}]*message\s*:\s*[\"\']([^\"\']+)[\"\']', const_js)
                for code, name in gifts:
                    GIFT_NAMES[code] = name

                title_match = re.search(r'<title>([^<]+)</title>', html)
                title = title_match.group(1).strip() if title_match else DEFAULT_TITLE

                print(f"[{datetime.now().strftime('%H:%M:%S')}] 解析 ESM 配置成功: 活動='{title}', mPromoNo={m_no}, dtPromoNo={dt_no}")
                return {
                    "domain": domain,
                    "url": edm_url,
                    "m_promo_no": m_no,
                    "dt_promo_no_array": [dt_no],
                    "title": title
                }

        # 備用檢測舊版 spinRotateConfig.js
        js_match = re.search(r'src=[\"\']([^\"\']*spinRotateConfig\.js[^\"\']*)[\"\']', html)
        if js_match:
            js_url = js_match.group(1)
            if js_url.startswith("//"):
                js_url = "https:" + js_url
            js_content = fetch_page(js_url, timeout=10)
            m = re.search(r'mPromoNo\s*:\s*[\"\']([^\"\']+)[\"\']', js_content)
            t = re.search(r'title\s*:\s*[\"\']([^\"\']+)[\"\']', js_content)
            dom = re.search(r'spinEventDomain\s*:\s*[\"\']([^\"\']+)[\"\']', js_content)
            dts = re.findall(r'[\"\'](D\d+)[\"\']', js_content)

            m_no = m.group(1) if m else DEFAULT_M_PROMO_NO
            title = t.group(1) if t else DEFAULT_TITLE
            domain = dom.group(1) if dom else "https://event.momoshop.com.tw"
            dt_list = dts if dts else [DEFAULT_DT_PROMO_NO]

            gifts = re.findall(r'giftCode\s*:\s*[\"\']([^\"\']+)[\"\'].*?giftContent\s*:\s*[\"\']([^\"\']+)[\"\']', js_content, re.DOTALL)
            for code, name in gifts:
                GIFT_NAMES[code] = name

            print(f"[{datetime.now().strftime('%H:%M:%S')}] 解析配置成功: 活動='{title}', mPromoNo={m_no}, 時段代碼數={len(dt_list)}")
            return {
                "domain": domain,
                "url": edm_url,
                "m_promo_no": m_no,
                "dt_promo_no_array": dt_list,
                "title": title
            }
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 解析配置異常: {e}")

    return None


def get_current_slot_info(now: datetime = None):
    if now is None:
        now = datetime.now()

    best_slot = None
    min_future_diff = float("inf")

    for sh, sm in SLOTS:
        slot_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        diff = (slot_dt - now).total_seconds()
        # 若在時段前 4 分鐘內或剛開搶 2 分鐘內，視為鎖定該時段
        if -120 <= diff <= 240:
            best_slot = (sh, sm)
            break
        # 尋找未來最近的時段
        if diff > 0 and diff < min_future_diff:
            min_future_diff = diff
            best_slot = (sh, sm)

    if not best_slot:
        best_slot = SLOTS[0]

    slot_hour, slot_min = best_slot
    slot_time_str = f"{slot_hour:02d}:{slot_min:02d}"
    dt_list = ACTIVE_CONFIG["dt_promo_no_array"]
    dt_promo = dt_list[0] if dt_list else DEFAULT_DT_PROMO_NO

    return slot_hour, slot_min, slot_time_str, dt_promo


def get_headers(cookie: str):
    return {
        "User-Agent": HEADERS["User-Agent"],
        "Content-Type": "application/json;charset=utf-8",
        "Origin": "https://www.momoshop.com.tw",
        "Referer": ACTIVE_CONFIG["url"],
        "Cookie": cookie.strip()
    }


def send_api_request(endpoint: str, payload: dict, cookie: str):
    url = f"{ACTIVE_CONFIG['domain']}/{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=get_headers(cookie), method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        return {"returnMsg": f"HTTP_ERROR_{e.code}"}
    except Exception as e:
        return {"returnMsg": f"ERROR_{str(e)}"}


def do_query(cookie: str, account_label: str = ""):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    payload = {
        "m_promo_no": ACTIVE_CONFIG["m_promo_no"],
        "qry_type": "1003"
    }

    res = send_api_request("promoMechQry.PROMO", payload, cookie)
    label = f"【{account_label}】" if account_label else ""
    if res.get("returnMsg") == "L":
        print(f"[{now_str}] {label} 查詢失敗: 會員登入憑證失效 (Cookie 已逾期)")
        return None

    if res.get("returnMsg") != "OK":
        print(f"[{now_str}] {label} 查詢回應: {res}")
        return None

    gift_codes = res.get("gift_code", [])
    insert_dates = res.get("insert_date", [])
    records = list(zip(insert_dates, gift_codes))

    total_mo = 0
    coupons = []
    for _, code in records:
        if code.startswith("mo_"):
            try:
                total_mo += int(code.split("_")[1])
            except Exception:
                pass
        else:
            coupons.append(GIFT_NAMES.get(code, code))

    print(f"[{now_str}] {label} 【{ACTIVE_CONFIG['title']}】活動紀錄:")
    print(f"  • 今日累計摸彩次數: {len(records)} 次")
    print(f"  • 累計獲得 mo 點: {total_mo} 元")
    if coupons:
        print(f"  • 獲得折價券: {', '.join(coupons)}")
    print("  • 詳細紀錄:")
    if not records:
        print("    (今日尚無摸彩紀錄)")
    for d, c in records:
        print(f"    - {d}: {GIFT_NAMES.get(c, c)}")

    return {
        "account_label": account_label,
        "total_draws": len(records),
        "total_mo": total_mo,
        "coupons": coupons,
        "records": records
    }


def prewarm_connection():
    """在時段前預先建立 TLS/SSL 連線與 DNS 快取，消除首發握手延遲"""
    try:
        payload = json.dumps({"m_promo_no": ACTIVE_CONFIG["m_promo_no"], "cnt_type": "1004"}).encode("utf-8")
        req = urllib.request.Request(
            f"{ACTIVE_CONFIG['domain']}/promoMechCnt.PROMO",
            data=payload,
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Content-Type": "application/json;charset=utf-8"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def do_draw(cookie: str, dt_promo: str):
    payload = {
        "m_promo_no": ACTIVE_CONFIG["m_promo_no"],
        "dt_promo_no": dt_promo
    }
    return send_api_request("promoMechReg.PROMO", payload, cookie)


def run_sniper_burst(cookie: str, dt_promo: str, max_burst: int = 8, account_label: str = ""):
    """
    毫秒級極速連發搶抽
    """
    prefix = f"[{account_label}] " if account_label else ""
    last_res = {}
    for shot in range(1, max_burst + 1):
        shot_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        res = do_draw(cookie, dt_promo)
        last_res = res
        return_msg = res.get("returnMsg", "")
        prize_code = res.get("prize", "")
        msg_text = RETURN_MESSAGES.get(return_msg, return_msg)
        print(f"[{shot_time}] {prefix}第 {shot} 發搶抽結果: {return_msg} ({msg_text})")

        if return_msg == "INS":
            gift_name = GIFT_NAMES.get(prize_code, prize_code)
            print(f"🎉 {prefix}搶抽成功！獲得: {gift_name}")
            return res, f"🎉 抽中：{gift_name}"
        elif return_msg in ("A", "A_EX"):
            print(f"{prefix}本時段已摸彩過。")
            return res, "本時段已摸彩過"
        elif return_msg in ("FULL", "E_CN"):
            print(f"{prefix}本時段名額已額滿。")
            return res, "本時段名額已額滿"
        elif return_msg == "L":
            print(f"⚠️ {prefix}Cookie 已失效，請重新登入更新。")
            return res, "⚠️ Cookie 已失效"
        elif return_msg in ("D", "NOT_USED"):
            time.sleep(0.15)
        else:
            time.sleep(0.2)

    return last_res, RETURN_MESSAGES.get(last_res.get("returnMsg", ""), last_res.get("returnMsg", ""))


def wait_until_slot_snipe(slot_hour: int, slot_minute: int, max_wait_seconds: int = 240):
    now = datetime.now()
    target_time = now.replace(hour=slot_hour, minute=slot_minute, second=0, microsecond=0)
    diff = (target_time - now).total_seconds()

    if diff <= 0:
        return

    if diff > max_wait_seconds:
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 鎖定時段 {slot_hour:02d}:{slot_minute:02d}，距離開抽剩 {diff:.1f} 秒，啟動狙擊倒數...")

    # 等待至剩 3.5 秒時預熱 TLS
    if diff > 3.5:
        time.sleep(diff - 3.5)

    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 剩餘 3.5 秒，預熱 TLS/SSL 連線...")
    prewarm_connection()

    # 倒數至前 0.2 秒搶先扣扳機
    target_snipe = target_time.timestamp() - 0.2
    rem = target_snipe - time.time()
    if rem > 0:
        time.sleep(rem)

    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🚀 到達開搶觸發點 (T-0.2s)，啟動多帳號極速連發！")


def run_session_draws(cookies: list, slot_hour: int = None, slot_minute: int = None, dt_promo_arg: str = None, silent_if_limit: bool = False, wait_snipe: bool = True):
    if slot_hour is not None and slot_minute is not None and dt_promo_arg:
        target_hour = slot_hour
        target_min = slot_minute
        dt_promo = dt_promo_arg
        slot_time_str = f"{target_hour:02d}:{target_min:02d}"
    else:
        target_hour, target_min, slot_time_str, dt_promo = get_current_slot_info()

    if wait_snipe:
        wait_until_slot_snipe(target_hour, target_min)

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now_str}] 目標時段: {slot_time_str}，共 {len(cookies)} 個帳號，發動搶抽...")

    # 多帳號並行發射
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(cookies))) as executor:
        future_to_info = {
            executor.submit(run_sniper_burst, cookie, dt_promo, 8, get_user_display_name(cookie, idx)): (idx, cookie)
            for idx, cookie in enumerate(cookies, 1)
        }
        for fut in concurrent.futures.as_completed(future_to_info):
            idx, cookie = future_to_info[fut]
            name = get_user_display_name(cookie, idx)
            try:
                res, desc = fut.result()
                results[idx] = (name, cookie, res, desc)
            except Exception as e:
                results[idx] = (name, cookie, {}, f"異常: {e}")

    # 彙整中獎與統計資訊
    time.sleep(1)
    report_sections = []
    has_meaningful_result = False

    for idx in sorted(results.keys()):
        name, cookie, res, desc = results[idx]
        summary = do_query(cookie, account_label=name)
        sec = [f"👤 {name}：{desc}"]
        if summary:
            sec.append(f"  • 累計 mo 點: {summary['total_mo']} 元 (摸彩 {summary['total_draws']} 次)")
            if summary["coupons"]:
                sec.append(f"  • 折價券: {len(summary['coupons'])} 張")
        report_sections.append("\n".join(sec))

        if desc not in ("本時段已摸彩過", "活動尚未開放或非開放時段"):
            has_meaningful_result = True

    if silent_if_limit and not has_meaningful_result:
        print("所有帳號均已摸彩過或非開放時段，略過推播。")
        return

    # 發送 Bark 通知
    try:
        from notifier import send_bark
        body_text = f"【時段 {slot_time_str} 摸彩報告】\n\n" + "\n\n".join(report_sections)
        send_bark(f"momo 週年摸彩結果 ({slot_time_str})", body_text.strip())
    except Exception as e:
        print(f"發送推播通知異常: {e}")


def run_sniper_mode(cookies: list):
    """常駐狙擊模式：鎖定今日下一個即將到來的時段並精準搶抽"""
    now = datetime.now()
    next_hour = None
    next_min = None
    next_dt = None

    for sh, sm in SLOTS:
        target = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        if (target - now).total_seconds() > 0:
            next_hour = sh
            next_min = sm
            next_dt = ACTIVE_CONFIG["dt_promo_no_array"][0]
            break

    if next_hour is None:
        print("今日所有時段已過，請於明日再啟動。")
        return

    diff_sec = (now.replace(hour=next_hour, minute=next_min, second=0, microsecond=0) - now).total_seconds()
    mins = int(diff_sec // 60)
    secs = int(diff_sec % 60)
    print(f"==================================================")
    print(f"🎯 啟動極速狙擊模式！(支援 {len(cookies)} 個帳號並行)")
    print(f"目標時段: {next_hour:02d}:{next_min:02d} (代碼: {next_dt})")
    print(f"倒數時間: 約 {mins} 分 {secs} 秒")
    print(f"策略: 時段前 3.5 秒預熱連線 ➔ T-0.2 秒多帳號並行出擊 ➔ 200ms 高頻連發")
    print(f"==================================================")

    wait_until_slot_snipe(next_hour, next_min, max_wait_seconds=86400)
    run_session_draws(cookies, slot_hour=next_hour, slot_minute=next_min, dt_promo_arg=next_dt, wait_snipe=False)


def run_scheduler(cookies: list, event_url: str):
    print(f"定時摸彩服務已啟動 (帳號數: {len(cookies)})。每日開放時段: {', '.join(SCHEDULE_TIMES)}")
    last_triggered_key = ""

    while True:
        now = datetime.now()
        current_hm = now.strftime("%H:%M")
        current_key = now.strftime("%Y-%m-%d_%H:%M")

        if current_hm in SCHEDULE_TIMES and current_key != last_triggered_key:
            last_triggered_key = current_key
            run_session_draws(cookies, wait_snipe=False)
            try:
                from momo_checkin import run_daily_checkin
                for c in cookies:
                    run_daily_checkin(c)
            except Exception as e:
                print(f"執行天天簽到異常: {e}")

        time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description="Momo 週年摸彩賺$999極速多帳號搶抽腳本")
    parser.add_argument("--cookie", help="Momo 網站 Cookie 字串 (多帳號可用換行或 --- 分隔)")
    parser.add_argument("--url", help="活動 EDM 網址 (預設週年慶週年摸彩賺$999)")
    parser.add_argument("--now", action="store_true", help="立即發送一次搶抽連發流程")
    parser.add_argument("--sniper", action="store_true", help="精準倒數鎖定下個開放時段，於前 0.2 秒搶先出擊")
    parser.add_argument("--query", action="store_true", help="查詢當前摸彩中獎紀錄與 mo 點")
    parser.add_argument("--schedule", action="store_true", help="啟動 12 個時段的本機定時輪詢")
    parser.add_argument("--silent-if-limit", action="store_true", help="若所有帳號均已無額度或非開放時段則略過推播")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("錯誤: 未找到有效 Cookie。請將 Cookie 寫入 cookie.txt 或使用 --cookie。")
        sys.exit(1)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 成功載入 {len(cookies)} 個會員帳號憑證：")
    for i, c in enumerate(cookies, 1):
        print(f"  • {get_user_display_name(c, i)}")

    edm_url = args.url or os.getenv("MOMO_EVENT_URL") or DEFAULT_EVENT_URL
    parsed = fetch_promo_config(edm_url)
    if parsed:
        ACTIVE_CONFIG.update(parsed)

    if args.query:
        for i, c in enumerate(cookies, 1):
            do_query(c, account_label=get_user_display_name(c, i))
    elif args.sniper:
        run_sniper_mode(cookies)
    elif args.now:
        now = datetime.now()
        sh, sm, _, _ = get_current_slot_info(now)
        diff = (now.replace(hour=sh, minute=sm, second=0, microsecond=0) - now).total_seconds()
        wait_snipe = (0 < diff <= 240)
        run_session_draws(cookies, slot_hour=sh, slot_minute=sm, silent_if_limit=args.silent_if_limit, wait_snipe=wait_snipe)
    else:
        run_scheduler(cookies, edm_url)


if __name__ == "__main__":
    main()
