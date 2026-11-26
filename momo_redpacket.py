#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 搶紅包 / 狂撒百萬驚喜 自動探索與搶點腳本
=============================================
支援：
1. 自動從活動頁、Momo 首頁 API (getMainPageV5) 及攻略/主會場頁探測最新有效活動
2. 動態解析活動期間 (MM/DD-MM/DD)、開放時段 (如 09:11~22:11) 與 API/活動代碼
3. 多帳號並行發射、Asia/Taipei 毫秒級對齊狙擊 (僅於開放場次才發射，避免空轉)
4. Bark 推播中獎通知
"""

from __future__ import annotations

import sys
import os
import time
import json
import re
import html as html_lib
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, date, timedelta, timezone
from typing import Optional
import concurrent.futures

try:
    from zoneinfo import ZoneInfo
    TAIPEI_TZ = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI_TZ = timezone(timedelta(hours=8))

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    cffi_requests = None
    HAS_CFFI = False


def taipei_now() -> datetime:
    """取得台灣標準時間 (Asia/Taipei)"""
    return datetime.now(TAIPEI_TZ)


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

# 預設入口網址與後備攻略/總覽入口
DEFAULT_EDM_URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O7Cj3Xyvxjm&n=1"
FALLBACK_HUB_URLS = [
    "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O7ylWqBgYoq&n=1",
    "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O7BpyO3uoSX&n=1",
]
MAIN_PAGE_API_URL = "https://www.momoshop.com.tw/api/moecapp/goods/getMainPageV5"
DEFAULT_API_URL = "https://event.momoshop.com.tw/promoMechReg.PROMO"

# 相容外部引用的預設時段清單 (實際執行以活動頁動態解析為主)
DEFAULT_M_PROMO_NO = "U96112300001"
DEFAULT_DT_PROMO_NO = "D96112300001"
SLOTS = [
    (10, 0), (11, 0), (12, 0),
    (14, 0), (15, 0), (16, 0),
    (17, 0), (18, 0), (20, 0),
    (21, 0),
]
SCHEDULE_TIMES = [f"{h:02d}:{m:02d}" for h, m in SLOTS]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoShop",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": DEFAULT_EDM_URL,
}

DEFAULT_PRIZE_MAP = {
    "mo_999": "🧧 momo幣 $999",
    "mo_111": "🧧 momo幣 $111",
    "mo_11": "🧧 momo幣 $11",
    "mo_1": "🧧 momo幣 $1",
    "coupon_30": "🎫 $30折價券",
    "coupon_111": "🎫 $111折價券",
    "coupon_222": "🎫 $222折價券",
    "coupon_300": "🎫 $300折價券",
    "coupon_88": "🎫 88折折價券",
    "coupon00": "🎫 $111折價券",
}

DEFAULT_RETURN_MESSAGES = {
    "INS": "恭喜中獎！",
    "FULL": "本時段名額已額滿",
    "A": "您於此時段已搶過紅包",
    "A_EX": "您今日已搶過囉！(每人每日限搶一次)",
    "END": "本時段活動已結束",
    "D": "非活動時間或未到開搶時段",
    "L": "登入憑證逾期，請重新登入",
    "E_CN": "請重新登入",
    "NOT_USED": "很抱歉，活動暫不開放",
    "NOT_APP": "請在 momo APP 參加活動",
    "NOT_WEB": "請在 momo 網頁版參加活動",
    "ERR": "系統繁忙，請稍後再試",
    "ERROR": "系統繁忙，請稍後再試",
    "E_RATELIMIT": "登記人數眾多，請稍後再試",
}

EXPIRY_PREFIX_RE = re.compile(r"(?:使用)?(?:效期|保存期限|到期|失效|截止|兌換至|兌畢|領獎)[^\n]{0,20}$")
TIME_TOKEN_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d|:\d)")


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
            "icon": "https://picasso-frontend.momoshop.com.tw/mmp-activity/quiz-game/icon.png",
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=4)
    except Exception as e:
        print(f"推播失敗: {e}")


def get_user_display_name(cookie: str, default_idx: int = 1) -> str:
    m = re.search(r"loginUser=([^;]+)", cookie)
    if m:
        try:
            val = m.group(1).replace("+", " ")
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


def fetch_page_text(url: str, timeout: int = 8, headers: dict = None) -> str:
    """透過 curl_cffi 或標準 urllib 抓取網頁與靜態 JS 資源"""
    req_headers = headers or HEADERS
    if HAS_CFFI:
        try:
            resp = cffi_requests.get(url, impersonate="chrome124", timeout=timeout, headers=req_headers, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass

    try:
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def normalize_url(raw_url: str, base_url: str = "https://www.momoshop.com.tw") -> str:
    url = html_lib.unescape(raw_url).strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urllib.parse.urljoin(base_url, url)
    return url


def normalize_edm_url(raw_url: str) -> str:
    """正規化 EDM 網址，去除行銷追蹤參數避免重複探測"""
    url = normalize_url(raw_url)
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "goodsUrl" in qs and qs["goodsUrl"]:
        return normalize_edm_url(qs["goodsUrl"][0])
    for key in ("lpn", "npn"):
        if key in qs and qs[key]:
            return f"https://www.momoshop.com.tw/edm/cmmedm.jsp?{key}={qs[key][0]}&n=1"
    return url


def resolve_momo_url(url: str, timeout: int = 8) -> str:
    """將 momo.dm / appRedirect.jsp 解析為真實活動頁網址"""
    url = normalize_url(url)
    if "momo.dm" not in url and "appRedirect.jsp" not in url:
        return url

    if HAS_CFFI:
        try:
            resp = cffi_requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=timeout, allow_redirects=True)
            if "cmmedm.jsp" in resp.url:
                return normalize_edm_url(resp.url)
            m = re.search(r"https?://www\.momoshop\.com\.tw/edm/cmmedm\.jsp\?(?:lpn|npn)=[A-Za-z0-9]+", resp.text)
            if m:
                return normalize_edm_url(m.group(0))
        except Exception:
            pass

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return normalize_edm_url(resp.geturl())
    except Exception:
        return url


def extract_visible_text(raw_html: str) -> str:
    """移除註解與 script/style，保留換行結構的可見文字"""
    clean = re.sub(r"<!--.*?-->", "\n", raw_html, flags=re.S)
    clean = re.sub(r"<script\b[^>]*>.*?</script>", "\n", clean, flags=re.S | re.I)
    clean = re.sub(r"<style\b[^>]*>.*?</style>", "\n", clean, flags=re.S | re.I)
    clean = re.sub(r"<(?:br|/p|/div|/li|/tr|/td|/th|/h[1-6])\b[^>]*>", "\n", clean, flags=re.I)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = html_lib.unescape(clean)
    lines = [re.sub(r"[ \t\r]+", " ", ln).strip() for ln in clean.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def extract_html_title(raw_html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", raw_html, flags=re.S | re.I)
    if not m:
        return ""
    return html_lib.unescape(re.sub(r"\s+", " ", m.group(1))).strip()


def _build_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date_ranges(visible_text: str, ref_date: date) -> list:
    """從頁面可見文案解析活動日期區間，回傳 [(start_date, end_date, start_pos), ...]"""
    range_re = re.compile(
        r"(?:(20\d{2})/)?(\d{1,2})/(\d{1,2})\s*(?:\([^)]{1,4}\)\s*)?[-~～至到]\s*(?:(20\d{2})/)?(?:(\d{1,2})/)?(\d{1,2})"
    )
    results = []
    seen = set()

    for m in range_re.finditer(visible_text):
        prefix = visible_text[max(0, m.start() - 25):m.start()]
        if EXPIRY_PREFIX_RE.search(prefix):
            continue

        y1_s, m1_s, d1_s, y2_s, m2_s, d2_s = m.groups()
        m1, d1 = int(m1_s), int(d1_s)
        m2 = int(m2_s) if m2_s else m1
        d2 = int(d2_s)

        if y1_s:
            y1 = int(y1_s)
        elif y2_s:
            y1 = int(y2_s) - (1 if m1 > m2 else 0)
        else:
            y1 = ref_date.year - (1 if ref_date.month <= 2 and m1 >= 11 else 0)

        if y2_s:
            y2 = int(y2_s)
        else:
            y2 = y1 + (1 if m2 < m1 else 0)

        start_d = _build_date(y1, m1, d1)
        end_d = _build_date(y2, m2, d2)
        if not start_d or not end_d or end_d < start_d:
            continue

        key = (start_d, end_d)
        if key not in seen:
            seen.add(key)
            results.append((start_d, end_d, m.start()))

    # 若無區間，檢查「活動期間 / 限定」單日日期
    if not results:
        single_re = re.compile(r"(?:(20\d{2})/)?(\d{1,2})/(\d{1,2})")
        for kw_m in re.finditer(r"(?:活動期間|限時|限定|開搶|當日)[^\n]{0,30}", visible_text):
            chunk = kw_m.group(0)
            if re.search(r"效期|到期|失效|截止", chunk):
                continue
            for dm in single_re.finditer(chunk):
                y_s, mm_s, dd_s = dm.groups()
                yy = int(y_s) if y_s else ref_date.year
                d_obj = _build_date(yy, int(mm_s), int(dd_s))
                if d_obj and (d_obj, d_obj) not in seen:
                    seen.add((d_obj, d_obj))
                    results.append((d_obj, d_obj, kw_m.start()))

    return results


def is_campaign_active_today(visible_text: str, raw_html: str, today: date) -> tuple:
    """檢查活動是否仍在有效期限內，回傳 (is_active, [(start, end), ...])"""
    if "此EDM不存在" in raw_html or len(raw_html) < 1500:
        return False, []

    ranges = parse_date_ranges(visible_text, today)
    if not ranges:
        return True, []

    plain_ranges = [(s, e) for s, e, _ in ranges]
    active = any(s <= today <= e for s, e in plain_ranges)
    return active, plain_ranges


def _extract_slot_clusters(text: str) -> list:
    """從文字段落萃取連續時段群組或具備開搶關鍵字的單一時段"""
    matches = list(TIME_TOKEN_RE.finditer(text))
    if not matches:
        return []

    filtered = []
    for m in matches:
        prefix = text[max(0, m.start() - 30):m.start()]
        if EXPIRY_PREFIX_RE.search(prefix):
            continue
        filtered.append(m)

    if not filtered:
        return []

    # 1. 優先抓取成串列出的場次時間 (例如 09:11、10:11、11:11...)
    cluster_slots = []
    current_group = [filtered[0]]
    for prev, cur in zip(filtered, filtered[1:]):
        gap = text[prev.end():cur.start()]
        if len(gap) <= 20 and re.fullmatch(r"[\s、,，/;；|｜~～\-]+", gap):
            current_group.append(cur)
        else:
            if len(current_group) >= 2:
                cluster_slots.extend(current_group)
            current_group = [cur]
    if len(current_group) >= 2:
        cluster_slots.extend(current_group)

    if cluster_slots:
        slots = {(int(m.group(1)), int(m.group(2))) for m in cluster_slots}
        return sorted(slots)

    # 2. 若僅單一場次，檢查上下文是否有開搶語意且非 23:59 截止時間
    single_slots = set()
    for m in filtered:
        h, mm = int(m.group(1)), int(m.group(2))
        if (h, mm) == (23, 59):
            continue
        ctx = text[max(0, m.start() - 35):min(len(text), m.end() + 35)]
        if re.search(r"開搶|時段|限搶|限量|整點|開抽|紅包", ctx):
            single_slots.add((h, mm))
    return sorted(single_slots)


def parse_slots_from_text(visible_text: str, today: Optional[date] = None) -> list:
    """從活動頁可見文案動態萃取開放場次 [(hour, minute), ...]"""
    if today is not None:
        ranges = parse_date_ranges(visible_text, today)
        for idx, (s_d, e_d, pos) in enumerate(ranges):
            if s_d <= today <= e_d:
                end_pos = pos + 700
                for next_s, next_e, next_pos in ranges[idx + 1:]:
                    if next_pos > pos and (next_s, next_e) != (s_d, e_d):
                        end_pos = min(end_pos, next_pos)
                        break
                section = visible_text[pos:end_pos]
                section_slots = _extract_slot_clusters(section)
                if section_slots:
                    return section_slots

    return _extract_slot_clusters(visible_text)


def _is_stale_year_code(code: str, ref_year: int) -> bool:
    m = re.match(r"^[UD](20\d{2})\d+", code)
    if m and int(m.group(1)) < ref_year:
        return True
    return False


def _parse_it_constant(it_code: str, edm_url: str, ref_year: int) -> Optional[dict]:
    mno_m = re.search(r"(?:mno|mPromoNo|m_promo_no)\s*:\s*[\"']([^\"']+)[\"']", it_code)
    dt_matches = re.findall(
        r"(?:firstDtNo|secondDtNo|dtPromoNo|dt_promo_no|dtNo)\s*:\s*[\"']([^\"']+)[\"']",
        it_code,
    )
    if not mno_m or not dt_matches:
        return None

    m_val = mno_m.group(1).strip()
    if _is_stale_year_code(m_val, ref_year):
        return None

    dt_list = list(dict.fromkeys(x.strip() for x in dt_matches if x.strip()))
    api_base_m = re.search(r"API_BASE\s*=\s*[\"']([^\"']+)[\"']", it_code)
    api_base = api_base_m.group(1).rstrip("/") if api_base_m else "https://event.momoshop.com.tw"

    prize_map = dict(DEFAULT_PRIZE_MAP)
    for code, msg in re.findall(r"(\w+)\s*:\s*\{[^{}]*?message\s*:\s*[\"']([^\"']+)[\"']", it_code, flags=re.S):
        prize_map[code] = msg

    reg_messages = dict(DEFAULT_RETURN_MESSAGES)
    reg_block_m = re.search(r"regMessage\s*=\s*\{(.*?)\};", it_code, flags=re.S)
    if reg_block_m:
        for code, msg in re.findall(r"(\w+)\s*:\s*[\"']([^\"']+)[\"']", reg_block_m.group(1)):
            reg_messages[code] = msg.replace("\n", " ").replace("\r", "").strip()

    return {
        "m_promo_no": m_val,
        "dt_promo_nos": dt_list,
        "api_url": f"{api_base}/promoMechReg.PROMO",
        "prize_map": prize_map,
        "reg_messages": reg_messages,
        "mech": "it_constant",
        "url": edm_url,
    }


def _extract_promo_config(edm_url: str, html: str, ref_year: int) -> Optional[dict]:
    """從 EDM HTML 與其引用的 JS 設定檔解析活動 API 與代碼"""
    # 1. ESM 架構: it_init.js?t=... -> 同目錄 it_constant.js?t=...
    it_matches = re.findall(r"src=[\"']([^\"']*it_init\.js[^\"']*)[\"']", html)
    for it_src in it_matches:
        init_url = normalize_url(it_src)
        base_dir = init_url.rsplit("/", 1)[0]
        ts = init_url.split("?", 1)[1] if "?" in init_url else ""
        it_url = f"{base_dir}/it_constant.js?{ts}" if ts else f"{base_dir}/it_constant.js"
        it_code = fetch_page_text(it_url, timeout=6)
        if it_code and not it_code.startswith("GIF89"):
            parsed = _parse_it_constant(it_code, edm_url, ref_year)
            if parsed:
                return parsed

    # 2. spinRotateConfig.js 架構
    spin_matches = re.findall(r"src=[\"']([^\"']*spinRotateConfig\.js[^\"']*)[\"']", html)
    for s_src in spin_matches:
        js_code = fetch_page_text(normalize_url(s_src), timeout=6)
        if js_code and not js_code.startswith("GIF89"):
            m_no = re.search(r"mPromoNo\s*:\s*[\"']([^\"']+)[\"']", js_code)
            dts = re.findall(r"[\"'](D\d+)[\"']", js_code)
            dom = re.search(r"spinEventDomain\s*:\s*[\"']([^\"']+)[\"']", js_code)
            if m_no and dts and not _is_stale_year_code(m_no.group(1), ref_year):
                base_dom = dom.group(1).rstrip("/") if dom else "https://event.momoshop.com.tw"
                prize_map = dict(DEFAULT_PRIZE_MAP)
                for g_code, g_content in re.findall(
                    r"giftCode\s*:\s*[\"']([^\"']+)[\"']\s*,\s*giftContent\s*:\s*[\"']([^\"']+)[\"']",
                    js_code,
                ):
                    icon = "🧧 " if g_code.startswith("mo_") else "🎫 "
                    prize_map[g_code] = f"{icon}{g_content}"
                btn_indices = set(re.findall(r"id=[\"'](?:m_)?promoActivity0_(\d+)[\"']", html))
                single_button_dt = (btn_indices == {"0"})
                return {
                    "m_promo_no": m_no.group(1),
                    "dt_promo_nos": list(dict.fromkeys(dts)),
                    "api_url": f"{base_dom}/promoMechReg.PROMO",
                    "prize_map": prize_map,
                    "reg_messages": dict(DEFAULT_RETURN_MESSAGES),
                    "single_button_dt": single_button_dt,
                    "mech": "spinRotateConfig",
                    "url": edm_url,
                }

    # 3. gameConfig.js 抽抽樂架構 (如桃金日好運抽抽樂 -> game/momoLottery.PROMO)
    game_matches = re.findall(r"src=[\"']([^\"']*gameConfig\.js[^\"']*)[\"']", html)
    for g_src in game_matches:
        js_code = fetch_page_text(normalize_url(g_src), timeout=6)
        if js_code and not js_code.startswith("GIF89"):
            m_no = re.search(r"mPromoNo\s*=\s*[\"']([^\"']+)[\"']", js_code)
            dt_no = re.search(r"dtPromoNo\s*=\s*[\"']([^\"']+)[\"']", js_code)
            if m_no and dt_no and not _is_stale_year_code(m_no.group(1), ref_year):
                url_m = re.search(r"mahjongGameUrl\s*=\s*[\"']([^\"']+)[\"']", js_code)
                api_url = url_m.group(1).strip() if url_m else "https://event.momoshop.com.tw/game/momoLottery.PROMO"

                prize_map = dict(DEFAULT_PRIZE_MAP)
                word_gifts = {}
                gift_block = re.search(r"giftName\s*=\s*\{(.*?)\}", js_code, flags=re.S)
                if gift_block:
                    for code, name in re.findall(r"[\"'](\w+)[\"']\s*:\s*[\"']([^\"']+)[\"']", gift_block.group(1)):
                        if code.startswith("mo_"):
                            prize_map[code] = f"🧧 ${name.replace('元', '')} mo點"
                        else:
                            prize_map[code] = f"🀄 字卡「{name}」"
                            word_gifts[code] = name

                reg_messages = dict(DEFAULT_RETURN_MESSAGES)
                msg_block = re.search(r"returnMessage\s*=\s*\{(.*?)\}", js_code, flags=re.S)
                if msg_block:
                    for code, msg in re.findall(r"[\"'](\w+)[\"']\s*:\s*[\"']([^\"']+)[\"']", msg_block.group(1)):
                        reg_messages[code] = msg.replace("\n", " ").replace("\r", "").strip()

                return {
                    "m_promo_no": m_no.group(1),
                    "dt_promo_nos": [dt_no.group(1)],
                    "api_url": api_url,
                    "prize_map": prize_map,
                    "reg_messages": reg_messages,
                    "word_gifts": word_gifts,
                    "mech": "gameConfig",
                    "url": edm_url,
                }

    # 4. 頁面內嵌或獨立設定檔 (略過過時的 2022 全站紅包雨模板 couponRain.js)
    m_inline = re.search(r"(?:m_promo_no|mPromoNo|mno)\s*[:=]\s*[\"']([A-Za-z0-9]+)[\"']", html)
    dt_inline = re.search(r"(?:dt_promo_no|dtPromoNo|firstDtNo)\s*[:=]\s*[\"']([A-Za-z0-9]+)[\"']", html)
    if m_inline and dt_inline and not _is_stale_year_code(m_inline.group(1), ref_year):
        return {
            "m_promo_no": m_inline.group(1),
            "dt_promo_nos": [dt_inline.group(1)],
            "api_url": DEFAULT_API_URL,
            "prize_map": dict(DEFAULT_PRIZE_MAP),
            "reg_messages": dict(DEFAULT_RETURN_MESSAGES),
            "mech": "inline",
            "url": edm_url,
        }

    return None


def analyze_edm_candidate(edm_url: str, require_redpacket_signals: bool = True, today: Optional[date] = None) -> Optional[dict]:
    """分析單一 EDM 頁是否為進行中的搶紅包/整點搶點數活動，並回傳完整設定與時段"""
    if today is None:
        today = taipei_now().date()

    resolved_url = resolve_momo_url(edm_url)
    html = fetch_page_text(resolved_url, timeout=8)
    if not html:
        return None

    title = extract_html_title(html)
    visible_text = extract_visible_text(html)
    is_active_today, date_ranges = is_campaign_active_today(visible_text, html, today)

    is_hub = bool(re.search(r"主會場|攻略|活動總覽", title))
    promo = _extract_promo_config(resolved_url, html, today.year)
    if not promo:
        return {
            "url": resolved_url,
            "title": title,
            "is_hub": is_hub,
            "html": html if is_hub else "",
            "is_active_today": is_active_today,
            "date_ranges": date_ranges,
            "slots": [],
            "score": -1,
            "promo": None,
        }

    slots = parse_slots_from_text(visible_text, today=today)
    head_text = visible_text[:2500]
    kw_hits = len(re.findall(r"紅包|狂撒|百萬驚喜|驚喜二選一|搶\$?999|mo點|mo幣|限量開搶|每時段", f"{title} {head_text}"))
    neg_hits = len(re.findall(r"訂閱|moPro|滿額送好禮|累積消費|刷卡滿額", title))

    score = 30
    if len(slots) >= 2:
        score += 100 + min(len(slots), 24)
    elif len(slots) == 1:
        score += 40
    score += min(kw_hits * 15, 60)
    if is_active_today and date_ranges:
        score += 30
    if not is_active_today:
        score -= 200
    if neg_hits > 0 and len(slots) == 0:
        score -= 200

    if require_redpacket_signals:
        if not is_active_today:
            return None
        if len(slots) == 0 and kw_hits < 2:
            return None
        if score <= 0:
            return None

    max_draws = 2 if promo["mech"] == "gameConfig" else 1
    draw_cnt_m = re.search(r"(?:可各?抽獎|限抽|限玩|可抽)\s*(\d+)\s*次", head_text)
    if draw_cnt_m:
        parsed_cnt = int(draw_cnt_m.group(1))
        if 1 <= parsed_cnt <= 5:
            max_draws = parsed_cnt

    return {
        "url": resolved_url,
        "title": title,
        "is_hub": is_hub,
        "html": "",
        "is_active_today": is_active_today,
        "date_ranges": date_ranges,
        "slots": slots,
        "score": score,
        "m_promo_no": promo["m_promo_no"],
        "dt_promo_nos": promo["dt_promo_nos"],
        "api_url": promo["api_url"],
        "prize_map": promo["prize_map"],
        "reg_messages": promo["reg_messages"],
        "word_gifts": promo.get("word_gifts", {}),
        "single_button_dt": promo.get("single_button_dt", False),
        "mech": promo["mech"],
        "max_draws": max_draws,
    }


def _collect_links_from_obj(obj, results: list, seen: set):
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_links_from_obj(v, results, seen)
    elif isinstance(obj, list):
        for item in obj:
            _collect_links_from_obj(item, results, seen)
    elif isinstance(obj, str) and ("cmmedm.jsp" in obj or "momo.dm" in obj):
        decoded = urllib.parse.unquote(obj)
        for m in re.finditer(r"https?://(?:www\.momoshop\.com\.tw/edm/cmmedm\.jsp\?(?:lpn|npn)=[A-Za-z0-9]+|momo\.dm/[A-Za-z0-9]+)", decoded):
            norm = normalize_edm_url(m.group(0))
            if norm not in seen:
                seen.add(norm)
                results.append(norm)


def fetch_homepage_edm_urls() -> list:
    """從 Momo 首頁 API (getMainPageV5) 取得當期所有主要活動頁連結 (高優先度看板排前)"""
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Content-Type": "application/json",
        "Origin": "https://www.momoshop.com.tw",
        "Referer": "https://www.momoshop.com.tw/main/Main.jsp",
    }
    payload = {"host": "momoshop", "data": {"custNo": ""}}
    text = ""

    if HAS_CFFI:
        try:
            resp = cffi_requests.post(MAIN_PAGE_API_URL, headers=headers, json=payload, impersonate="chrome124", timeout=10)
            if resp.status_code == 200:
                text = resp.text
        except Exception:
            pass
    if not text:
        try:
            req = urllib.request.Request(
                MAIN_PAGE_API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
        except Exception:
            return []

    try:
        data = json.loads(text)
    except Exception:
        return []

    priority_types = {"bt_7_707", "bt_7_714", "bt_7_702", "bt_7_701", "bt_7_708"}
    priority_urls, other_urls = [], []
    seen = set()

    for blk in data.get("mainInfo", []):
        bt = blk.get("blockTypeId", "")
        target = priority_urls if bt in priority_types else other_urls
        _collect_links_from_obj(blk, target, seen)

    return priority_urls + other_urls


def _extract_hub_candidate_urls(hub_html: str) -> list:
    """從主會場/攻略/總覽 EDM HTML 提取候選內頁連結 (依關鍵字權重排序，不截斷後續活動)"""
    scored = []
    seen = set()
    for m in re.finditer(r"https?://www\.momoshop\.com\.tw/edm/cmmedm\.jsp\?(?:lpn|npn)=[A-Za-z0-9]+", hub_html):
        norm = normalize_edm_url(m.group(0))
        if norm in seen:
            continue
        seen.add(norm)
        ctx = hub_html[max(0, m.start() - 120):m.end() + 500]
        w = len(re.findall(r"紅包|狂撒|驚喜|mo點|mo幣|搶|轉盤|轉轉樂|好運轉|抽獎|主會場|攻略|999", ctx))
        scored.append((w, norm))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [u for _, u in scored]


def _scan_urls_concurrently(
    urls: list,
    checked_urls: set,
    today: date,
    source_label: str,
    require_signals: bool,
    batch_size: int = 12,
) -> tuple:
    """分批並行探測候選 URL，回傳 (qualified_list, discovered_hubs)"""
    qualified = []
    discovered_hubs = []
    pending = [u for u in urls if u not in checked_urls]
    if not pending:
        return qualified, discovered_hubs

    with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as ex:
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            checked_urls.update(batch)
            for res in ex.map(lambda u: analyze_edm_candidate(u, require_redpacket_signals=False, today=today), batch):
                if not res:
                    continue
                if res.get("is_hub") and res.get("html"):
                    discovered_hubs.append(res)
                if not res.get("m_promo_no") or not res.get("is_active_today"):
                    continue
                if require_signals:
                    slots = res.get("slots", [])
                    score = res.get("score", -1)
                    if score <= 0 or (len(slots) == 0 and score < 75):
                        continue
                res["source"] = source_label
                qualified.append(res)
            if qualified:
                break

    return qualified, discovered_hubs


def discover_active_campaign(explicit_url: Optional[str] = None, allow_fallback: bool = True, today: Optional[date] = None) -> Optional[dict]:
    """
    三層自動探測進行中的紅包/轉盤/整點開搶活動：
    1. 明確指定 URL (CLI --url 或 MOMO_EVENT_URL) 與預設快速路徑 (DEFAULT_EDM_URL)
    2. Momo 首頁 getMainPageV5 動態活動看板全量並行掃描 (不分前後位置皆掃描)
    3. 首頁主會場 / 攻略頁 / 活動總覽最多 2 層展開掃描
    """
    if today is None:
        today = taipei_now().date()

    env_url = os.getenv("MOMO_EVENT_URL", "").strip()
    user_url = explicit_url or env_url
    checked_urls = set()

    # 1. 若有明確指定 URL，先探測
    if user_url:
        resolved = resolve_momo_url(user_url)
        checked_urls.add(resolved)
        cand = analyze_edm_candidate(resolved, require_redpacket_signals=False, today=today)
        if cand and cand.get("m_promo_no"):
            if cand["is_active_today"] or not allow_fallback:
                cand["source"] = "指定網址"
                return cand
            print(f"[{taipei_now().strftime('%H:%M:%S')}] ⚠️ 指定活動頁 {resolved} 已不在今日活動期 ({cand['date_ranges']})，改為自動搜尋首頁新活動...")

    # 2. 快速檢查 DEFAULT_EDM_URL
    if DEFAULT_EDM_URL not in checked_urls:
        checked_urls.add(DEFAULT_EDM_URL)
        cand = analyze_edm_candidate(DEFAULT_EDM_URL, require_redpacket_signals=True, today=today)
        if cand and cand.get("m_promo_no"):
            cand["source"] = "預設活動頁 (已驗證有效)"
            return cand

    if not allow_fallback:
        return None

    # 3. 從 Momo 首頁 API 全量掃描候選活動頁 (高優先度看板排前，但不再截斷尾端活動)
    print(f"[{taipei_now().strftime('%H:%M:%S')}] 🔍 預設活動頁未開放或已過期，正在從 Momo 首頁自動搜尋新場次與活動...")
    homepage_urls = fetch_homepage_edm_urls()
    qualified, discovered_hubs = _scan_urls_concurrently(
        homepage_urls, checked_urls, today, source_label="首頁自動探測", require_signals=True
    )
    if qualified:
        qualified.sort(key=lambda c: (c["score"], len(c["slots"])), reverse=True)
        return qualified[0]

    # 4. 展開首頁主會場 / 攻略頁 / 活動總覽 (最多 2 層，涵蓋 總覽 -> 主會場 -> 活動頁)
    hub_queue = list(discovered_hubs)
    for fb_hub in FALLBACK_HUB_URLS:
        if fb_hub not in checked_urls:
            checked_urls.add(fb_hub)
            fb_html = fetch_page_text(fb_hub, timeout=8)
            if fb_html and "此EDM不存在" not in fb_html:
                hub_queue.append({"url": fb_hub, "html": fb_html, "is_hub": True})

    for _depth in range(2):
        if not hub_queue:
            break
        child_urls = []
        seen_children = set()
        for h_res in hub_queue:
            for u in _extract_hub_candidate_urls(h_res.get("html", "")):
                if u not in checked_urls and u not in seen_children:
                    seen_children.add(u)
                    child_urls.append(u)
        if not child_urls:
            break
        qualified, next_hubs = _scan_urls_concurrently(
            child_urls[:60], checked_urls, today, source_label="攻略/會場自動探測", require_signals=True
        )
        if qualified:
            qualified.sort(key=lambda c: (c["score"], len(c["slots"])), reverse=True)
            return qualified[0]
        hub_queue = next_hubs

    return None


def find_matching_slot(
    slots: list,
    now: datetime = None,
    past_grace_sec: int = 300,
    future_window_sec: int = 3540,
    date_ranges: list = None,
) -> tuple:
    """
    找出距離當前時間最近且落在可搶等待視窗 (-5分 ~ +59分) 內的開放場次
    支援從固定排程 (如 xx:10) 自動接軌下一小時內的整點 (:00) 或任何分鐘場次
    回傳 ((hour, minute), slot_datetime, delta_seconds) 或 (None, None, None)
    """
    if not slots:
        return None, None, None
    if now is None:
        now = taipei_now()

    eligible = []
    day_offsets = [0]
    if now.hour >= 22:
        tomorrow_d = (now + timedelta(days=1)).date()
        if not date_ranges or any(s <= tomorrow_d <= e for s, e in date_ranges):
            day_offsets.append(1)

    for offset in day_offsets:
        base_dt = now + timedelta(days=offset)
        for h, m in slots:
            slot_dt = base_dt.replace(hour=h, minute=m, second=0, microsecond=0)
            delta = (slot_dt - now).total_seconds()
            if -past_grace_sec <= delta <= future_window_sec:
                eligible.append(((h, m), slot_dt, delta))

    if not eligible:
        return None, None, None

    return min(eligible, key=lambda x: abs(x[2]))


def select_dt_promo_no(campaign: dict, slot_dt: Optional[datetime] = None) -> str:
    """依鎖定場次與頁面按鈕架構選擇主要 dt_promo_no"""
    dt_list = campaign.get("dt_promo_nos") or [DEFAULT_DT_PROMO_NO]
    if campaign.get("single_button_dt"):
        return dt_list[0]
    slots = campaign.get("slots") or []
    if slot_dt is not None and len(dt_list) == len(slots) and len(dt_list) > 1:
        key = (slot_dt.hour, slot_dt.minute)
        if key in slots:
            return dt_list[slots.index(key)]
    return dt_list[0]


def select_fallback_dt_promo_no(campaign: dict, slot_dt: Optional[datetime], primary_dt: str) -> Optional[str]:
    """若主代碼回傳 D (非活動時間)，提供備援 dt_promo_no (如單按鈕轉盤改依場次索引)"""
    dt_list = campaign.get("dt_promo_nos") or []
    slots = campaign.get("slots") or []
    if len(dt_list) <= 1:
        return None
    if slot_dt is not None and len(dt_list) == len(slots):
        key = (slot_dt.hour, slot_dt.minute)
        if key in slots:
            slot_dt_no = dt_list[slots.index(key)]
            if slot_dt_no != primary_dt:
                return slot_dt_no
    if dt_list[0] != primary_dt:
        return dt_list[0]
    return None


def prewarm_connection(campaign: dict, dt_promo_no: str):
    """開搶前先預熱 event.momoshop.com.tw 的 DNS 與 TLS 連線，減少首包延遲"""
    api_url = campaign.get("api_url", DEFAULT_API_URL)
    if "momoLottery.PROMO" in api_url:
        target_url = api_url
        payload_obj = {
            "doAction": "qry",
            "m_promo_no": campaign.get("m_promo_no", DEFAULT_M_PROMO_NO),
            "dt_promo_no": dt_promo_no,
        }
    else:
        target_url = api_url.rsplit("/", 1)[0] + "/promoMechCnt.PROMO"
        payload_obj = {
            "m_promo_no": campaign.get("m_promo_no", DEFAULT_M_PROMO_NO),
            "dt_promo_no": dt_promo_no,
            "cnt_type": "1002",
        }
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Content-Type": "application/json;charset=utf-8",
        "Origin": "https://www.momoshop.com.tw",
        "Referer": campaign.get("url", DEFAULT_EDM_URL),
    }
    if HAS_CFFI:
        try:
            cffi_requests.post(target_url, headers=headers, json=payload_obj, impersonate="chrome124", timeout=4)
            return
        except Exception:
            pass
    try:
        payload = json.dumps(payload_obj).encode("utf-8")
        req = urllib.request.Request(target_url, data=payload, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def send_draw_request(cookie: str, m_promo_no: str, dt_promo_no: str, api_url: str = DEFAULT_API_URL, referer: str = DEFAULT_EDM_URL) -> dict:
    headers = dict(HEADERS)
    headers["Cookie"] = cookie.strip()
    headers["Content-Type"] = "application/json;charset=utf-8"
    headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    headers["X-Requested-With"] = "XMLHttpRequest"
    headers["Referer"] = referer or DEFAULT_EDM_URL

    payload = {
        "m_promo_no": m_promo_no,
        "dt_promo_no": dt_promo_no,
    }
    if "momoLottery.PROMO" in api_url:
        payload["doAction"] = "lottery"
    else:
        payload["gift_code"] = ""

    # 優先使用 curl_cffi 模擬 Chrome TLS 指紋，避免 Akamai 403 與 SSL handshake timeout
    if HAS_CFFI:
        last_err = None
        for imp in ("chrome124", "chrome120"):
            try:
                resp = cffi_requests.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    impersonate=imp,
                    timeout=8,
                )
                if resp.status_code == 200:
                    return resp.json()
                last_err = {"returnMsg": "HTTP_ERR", "code": resp.status_code}
                if resp.status_code != 403:
                    break
            except Exception as e:
                last_err = {"returnMsg": "NET_ERR", "error": str(e)}
        if last_err is not None:
            # 若 curl_cffi 仍遇 403/網路錯誤，再嘗試標準 urllib 作為最後備援
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(api_url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=8) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception:
                return last_err

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(api_url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"returnMsg": "HTTP_ERR", "code": e.code}
    except Exception as e:
        return {"returnMsg": "NET_ERR", "error": str(e)}


def query_game_today_summary(
    cookie: str,
    m_promo_no: str,
    dt_promo_no: str,
    api_url: str,
    referer: str,
    word_gifts: Optional[dict] = None,
    target_date: Optional[date] = None,
) -> Optional[dict]:
    """查詢桃金日/抽抽樂當日累計紀錄，自動計算當天是否集滿字卡並實際獲得 mo 點"""
    if target_date is None:
        target_date = taipei_now().date()
    today_prefix = target_date.strftime("%Y/%m/%d")
    required_words = word_gifts or {"peach": "桃", "gold": "金", "day": "日"}

    headers = dict(HEADERS)
    headers["Cookie"] = cookie.strip()
    headers["Content-Type"] = "application/json;charset=utf-8"
    headers["Referer"] = referer or DEFAULT_EDM_URL

    payload = {
        "doAction": "qry",
        "m_promo_no": m_promo_no,
        "dt_promo_no": dt_promo_no,
    }
    try:
        req = urllib.request.Request(api_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=6) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if res.get("status") != "OK":
        return None

    data = res.get("data", {})
    dates = data.get("insert_date", [])
    codes = data.get("gift_code", [])

    today_mo = 0
    collected_words = set()
    today_draws = 0

    for d_str, code in zip(dates, codes):
        if not str(d_str).startswith(today_prefix):
            continue
        today_draws += 1
        if code.startswith("mo_"):
            try:
                today_mo += int(code.split("_", 1)[1])
            except ValueError:
                pass
        elif code in required_words:
            collected_words.add(code)

    missing_labels = [lbl for k, lbl in required_words.items() if k not in collected_words]
    got_mo = len(required_words) > 0 and len(missing_labels) == 0

    return {
        "today_draws": today_draws,
        "today_mo": today_mo,
        "collected_words": [required_words[k] for k in required_words if k in collected_words],
        "missing_words": missing_labels,
        "got_mo": got_mo,
    }


def grab_redpacket_single_account(
    cookie: str,
    account_label: str,
    m_promo_no: str,
    dt_promo_no: str,
    api_url: str = DEFAULT_API_URL,
    referer: str = DEFAULT_EDM_URL,
    prize_map: dict = None,
    reg_messages: dict = None,
    max_draws: int = 1,
    slot_dt: Optional[datetime] = None,
    word_gifts: Optional[dict] = None,
    fallback_dt_promo_no: Optional[str] = None,
) -> dict:
    """單一帳號執行搶獎 (不單獨發送推播，改回傳結果由外層合併為單一訊息)"""
    is_game_api = "momoLottery.PROMO" in api_url
    msg_table = reg_messages or DEFAULT_RETURN_MESSAGES
    prizes = prize_map or DEFAULT_PRIZE_MAP

    wins = []
    notes = []
    exchanged_total = None
    active_dt = dt_promo_no

    for attempt in range(1, max(1, max_draws) + 1):
        suffix = f" (第 {attempt}/{max_draws} 次)" if max_draws > 1 else ""
        print(f"\n🚀 [{taipei_now().strftime('%H:%M:%S')}] [{account_label}] 發射抽獎請求{suffix}...")
        res = send_draw_request(cookie, m_promo_no, active_dt, api_url=api_url, referer=referer)

        status = res.get("status", "") if is_game_api else res.get("returnMsg", "")
        if not status:
            status = res.get("returnMsg") or res.get("status") or ""

        # 若剛跨整點因伺服器時鐘略慢 (尚未切換場次) 回傳 D/FULL/A，或遇網路/403 瞬斷，短延遲補射
        near_slot = slot_dt is not None and abs((taipei_now() - slot_dt).total_seconds()) < 4
        if (near_slot and status in ("D", "FULL", "A")) or status in ("NET_ERR", "HTTP_ERR", "E_RATELIMIT", "ERR"):
            retry_wait = 0.55 if status in ("D", "FULL", "A") else 0.8
            print(f"[{account_label}] 🔄 首次回應 {status}，等待 {retry_wait}s 後補射一次...")
            time.sleep(retry_wait)
            res = send_draw_request(cookie, m_promo_no, active_dt, api_url=api_url, referer=referer)
            status = res.get("status", "") if is_game_api else res.get("returnMsg", "")
            if not status:
                status = res.get("returnMsg") or res.get("status") or ""

        # 若仍回傳 D 且有備援場次代碼 (如 D...02~10)，自動切換補射一次
        if status == "D" and fallback_dt_promo_no and fallback_dt_promo_no != active_dt:
            print(f"[{account_label}] 🔄 {active_dt} 回傳 D，切換備援代碼 {fallback_dt_promo_no} 補射...")
            active_dt = fallback_dt_promo_no
            res = send_draw_request(cookie, m_promo_no, active_dt, api_url=api_url, referer=referer)
            status = res.get("status", "") if is_game_api else res.get("returnMsg", "")
            if not status:
                status = res.get("returnMsg") or res.get("status") or ""

        status_desc = msg_table.get(status, f"未知代碼 ({status})")

        if (is_game_api and status == "OK") or (not is_game_api and status == "INS"):
            if is_game_api:
                prize_obj = res.get("result", {}).get("prize", {})
                prize_key = prize_obj.get("giftCode", "") if isinstance(prize_obj, dict) else ""
                prize_name = prizes.get(prize_key, f"獎品代碼: {prize_key}")
                if res.get("prizeStatus") == "PRIZE":
                    exchanged_total = res.get("total", 0)
                    prize_name += f" (集滿 +{exchanged_total}元)"
            else:
                prize_key = res.get("prize", "")
                prize_name = prizes.get(prize_key, f"獎品代碼: {prize_key}")
            wins.append(prize_name)
            print(f"[{account_label}] 🎉 中獎{suffix}！獲得：{prize_name}")
        elif status in ("A", "A_EX", "EA", "exchanged"):
            print(f"[{account_label}] ℹ️ {status_desc}")
            if status == "exchanged":
                notes.append("今日已兌獎")
            elif not wins:
                notes.append(status_desc)
            break
        elif status == "FULL":
            print(f"[{account_label}] ⚡ {status_desc}")
            if not wins:
                notes.append(status_desc)
            break
        else:
            print(f"[{account_label}] ⚠️ 回應：{status_desc} | 回傳內容: {res}")
            if not wins:
                notes.append(status_desc)
            if status in ("D", "L", "E_CN", "NOT_USED", "NOT_APP", "NOT_WEB"):
                break

        if attempt < max_draws:
            time.sleep(0.6)

    today_summary = None
    if is_game_api:
        today_summary = query_game_today_summary(
            cookie=cookie,
            m_promo_no=m_promo_no,
            dt_promo_no=dt_promo_no,
            api_url=api_url,
            referer=referer,
            word_gifts=word_gifts,
            target_date=(slot_dt.date() if slot_dt else taipei_now().date()),
        )
        if today_summary:
            if today_summary["got_mo"]:
                print(f"[{account_label}] ✅ 今日已集滿字卡，獲得 {today_summary['today_mo']} mo點")
            else:
                miss = "、".join(today_summary["missing_words"])
                print(f"[{account_label}] ⏳ 今日未得mo (累積 {today_summary['today_mo']} 元，缺：{miss})")

    return {
        "account": account_label,
        "wins": wins,
        "notes": notes,
        "exchanged_total": exchanged_total,
        "today_summary": today_summary,
    }


def wait_until_slot_snipe(slot_dt: datetime, campaign: Optional[dict] = None, max_wait_seconds: int = 3540):
    now = taipei_now()
    diff = (slot_dt - now).total_seconds()

    if diff <= 0 or diff > max_wait_seconds:
        return

    print(f"[{now.strftime('%H:%M:%S')}] 鎖定場次 {slot_dt.strftime('%m/%d %H:%M')}，距離開搶剩 {diff:.1f} 秒，等待中...")

    # 若等待超過 2 分鐘，於開搶前 90 秒醒來重抓活動參數 (避免官方開搶前換碼)
    if diff > 120:
        sleep_sec = (slot_dt.timestamp() - 90) - time.time()
        if sleep_sec > 0:
            time.sleep(sleep_sec)
        if campaign and campaign.get("url"):
            refreshed = analyze_edm_candidate(campaign["url"], require_redpacket_signals=False, today=slot_dt.date())
            if refreshed and refreshed.get("m_promo_no"):
                campaign.update({
                    "m_promo_no": refreshed["m_promo_no"],
                    "dt_promo_nos": refreshed["dt_promo_nos"],
                    "api_url": refreshed["api_url"],
                    "prize_map": refreshed["prize_map"],
                    "reg_messages": refreshed["reg_messages"],
                    "slots": refreshed.get("slots") or campaign.get("slots", []),
                })
                print(f"[{taipei_now().strftime('%H:%M:%S')}] 🔄 開搶前確認最新活動代碼: mPromoNo={campaign['m_promo_no']}")

    rem_prewarm = (slot_dt.timestamp() - 15) - time.time()
    if rem_prewarm > 0:
        time.sleep(rem_prewarm)

    if campaign:
        dt_no = select_dt_promo_no(campaign, slot_dt)
        prewarm_connection(campaign, dt_no)

    rem_coarse = (slot_dt.timestamp() - 1.5) - time.time()
    if rem_coarse > 0:
        time.sleep(rem_coarse)

    # 對齊整點後 +0.05s 發射，避免提早到達落入上一場次的 FULL/A 狀態
    rem = (slot_dt.timestamp() + 0.05) - time.time()
    if rem > 0:
        time.sleep(rem)

    print(f"[{taipei_now().strftime('%H:%M:%S.%f')[:-3]}] 🚀 到達開搶點 (T+0.05s)，發射搶獎請求！")


def print_campaign_summary(campaign: dict):
    ranges_str = ", ".join(f"{s.strftime('%m/%d')}-{e.strftime('%m/%d')}" for s, e in campaign.get("date_ranges", [])) or "未標註日期區間"
    slots = campaign.get("slots", [])
    slots_str = ", ".join(f"{h:02d}:{m:02d}" for h, m in slots) if slots else "無固定整點列表"
    print(f"📡 活動來源: {campaign.get('source', '未知')} | 標題: {campaign.get('title', 'N/A')}")
    print(f"🔗 活動網址: {campaign.get('url')}")
    print(f"📅 活動期間: {ranges_str} (今日有效: {'是' if campaign.get('is_active_today') else '否'})")
    print(f"🕒 開放場次 ({len(slots)} 場): {slots_str}")
    print(f"🎯 活動代碼: mPromoNo={campaign.get('m_promo_no')}, dtPromoNo={','.join(campaign.get('dt_promo_nos', []))} | 每場 {campaign.get('max_draws', 1)} 次 | API={campaign.get('api_url')}")


def format_slot_notification(campaign: dict, slot_label: str, results: list) -> tuple:
    """將單一時段所有帳號的結果整合成單一通知 (title, body)；若無需推播則回傳 (None, None)"""
    is_game_api = "momoLottery.PROMO" in campaign.get("api_url", "")
    raw_title = (campaign.get("title") or "momo 搶獎").replace(" - momo購物網", "").strip()
    title = f"momo {raw_title} ({slot_label})"

    lines = []
    any_win = False
    for r in results:
        acc = r["account"]
        wins = r.get("wins", [])
        notes = r.get("notes", [])
        ts = r.get("today_summary")

        if wins:
            any_win = True
            slot_part = "、".join(wins)
        elif notes:
            slot_part = notes[0]
        else:
            slot_part = "無中獎"

        if is_game_api and ts:
            if ts["got_mo"]:
                mo_val = ts["today_mo"] or (r.get("exchanged_total") or 0)
                day_part = f"✅ 今日已得 {mo_val} mo點"
            else:
                miss = "、".join(ts["missing_words"])
                day_part = f"⏳ 今日未得mo (累積{ts['today_mo']}元，缺：{miss})"
            lines.append(f"【{acc}】{slot_part}｜{day_part}")
        elif wins:
            lines.append(f"【{acc}】{slot_part}")

    if not any_win and not (is_game_api and any(r.get("today_summary") and r["today_summary"]["got_mo"] for r in results)):
        return None, None
    if not lines:
        return None, None

    return title, "\n".join(lines)


def run_sniper_session(cookies: list, campaign: dict, slot_dt: datetime = None, wait_snipe: bool = True):
    """多帳號並行極速搶獎，並於整場結束後合併為單一推播訊息"""
    if wait_snipe and slot_dt is not None:
        wait_until_slot_snipe(slot_dt, campaign=campaign)

    m_promo_no = campaign["m_promo_no"]
    dt_promo_no = select_dt_promo_no(campaign, slot_dt)
    fallback_dt_promo_no = select_fallback_dt_promo_no(campaign, slot_dt, dt_promo_no)
    api_url = campaign.get("api_url", DEFAULT_API_URL)
    referer = campaign.get("url", DEFAULT_EDM_URL)
    prize_map = campaign.get("prize_map")
    reg_messages = campaign.get("reg_messages")
    word_gifts = campaign.get("word_gifts")
    max_draws = campaign.get("max_draws", 1)
    slot_label = slot_dt.strftime("%H:%M") if slot_dt else taipei_now().strftime("%H:%M")

    print("\n========================================================================")
    print(f"🧧 開始執行開搶任務 ({slot_label}) | 帳號數: {len(cookies)} 組 | 每帳號 {max_draws} 次")
    print(f"🎯 活動: {campaign.get('title') or m_promo_no} | mPromoNo={m_promo_no}, dtPromoNo={dt_promo_no}")
    print("========================================================================")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cookies)) as ex:
        futures = [
            ex.submit(
                grab_redpacket_single_account,
                c,
                get_user_display_name(c, idx),
                m_promo_no,
                dt_promo_no,
                api_url,
                referer,
                prize_map,
                reg_messages,
                max_draws,
                slot_dt,
                word_gifts,
                fallback_dt_promo_no,
            )
            for idx, c in enumerate(cookies, start=1)
        ]
        results = [f.result() for f in futures]

    title, body = format_slot_notification(campaign, slot_label, results)
    if title and body:
        print(f"\n📨 合併推播內容：\n{title}\n{body}")
        send_bark_notification(title, body)


def main():
    parser = argparse.ArgumentParser(description="Momo 搶紅包 / 狂撒百萬驚喜 自動探索與搶點腳本")
    parser.add_argument("--now", action="store_true", help="立即檢查並於符合場次時執行一次搶抽")
    parser.add_argument("--force", action="store_true", help="強制發射，忽略場次與日期檢查")
    parser.add_argument("--discover", action="store_true", help="僅執行活動與場次探索測試並印出結果，不實際發射")
    parser.add_argument("--dry-run", action="store_true", help="模擬執行探索與場次比對，不送出搶紅包請求")
    parser.add_argument("--m-promo", help="指定 m_promo_no")
    parser.add_argument("--dt-promo", help="指定 dt_promo_no")
    parser.add_argument("--url", help="指定活動頁或攻略頁網址 (未指定時自動從首頁與已知頁面探索)")
    parser.add_argument("--silent-if-limit", action="store_true", help="若非開放時段或已搶過則不發送推播")
    args = parser.parse_args()

    now = taipei_now()

    # 1. 手動指定代碼優先；否則自動探索最新有效活動與場次
    if args.m_promo and args.dt_promo:
        campaign = {
            "url": resolve_momo_url(args.url or DEFAULT_EDM_URL),
            "title": "手動指定活動",
            "source": "CLI 參數",
            "m_promo_no": args.m_promo,
            "dt_promo_nos": [args.dt_promo],
            "api_url": DEFAULT_API_URL,
            "prize_map": dict(DEFAULT_PRIZE_MAP),
            "reg_messages": dict(DEFAULT_RETURN_MESSAGES),
            "slots": list(SLOTS),
            "date_ranges": [],
            "is_active_today": True,
        }
    else:
        campaign = discover_active_campaign(explicit_url=args.url, allow_fallback=not args.force, today=now.date())

    if args.discover or args.dry_run:
        if not campaign:
            print("❌ 今日未發現進行中的搶紅包/整點開搶活動。")
            return
        print_campaign_summary(campaign)
        slots = campaign.get("slots", [])
        best_slot, slot_dt, delta = find_matching_slot(slots, now=now, date_ranges=campaign.get("date_ranges"))
        if best_slot:
            print(f"✅ 當前時間 ({now.strftime('%H:%M:%S')}) 命中開放場次 {slot_dt.strftime('%H:%M')} (時差 {delta:+.1f}s)")
        else:
            print(f"⏸️ 當前時間 ({now.strftime('%H:%M:%S')}) 非開放場次")
        if args.dry_run:
            cookies = load_all_cookies()
            print(f"🧪 Dry-run 完成：已載入 {len(cookies)} 組帳號 Cookie，未發送任何搶包請求。")
        return

    cookies = load_all_cookies()
    if not cookies:
        print("❌ 未偵測到有效 Cookie，請在 cookie.txt 設定憑證！")
        sys.exit(1)

    if args.now:
        if not campaign:
            print(f"ℹ️ [{now.strftime('%H:%M:%S')}] 今日 ({now.strftime('%m/%d')}) 查無進行中的搶紅包活動，略過本次執行。")
            return

        print_campaign_summary(campaign)
        slots = campaign.get("slots", [])
        if args.force:
            run_sniper_session(cookies, campaign, slot_dt=None, wait_snipe=False)
            return

        if not slots:
            run_sniper_session(cookies, campaign, slot_dt=None, wait_snipe=False)
            return

        best_slot, slot_dt, _ = find_matching_slot(slots, now=now, date_ranges=campaign.get("date_ranges"))
        if not best_slot:
            slot_strs = ", ".join(f"{h:02d}:{m:02d}" for h, m in slots)
            print(f"⏸️ [{now.strftime('%H:%M:%S')}] 目前非今日開放場次，今日場次：[{slot_strs}]，略過發射。")
            return

        run_sniper_session(cookies, campaign, slot_dt=slot_dt, wait_snipe=True)
        return

    # 常駐定時狙擊模式：每個場次前與換日時重新探索，自動接軌新檔期與新場次
    print("\n🕒 已進入 Momo 搶紅包自動探索定時狙擊模式...")
    last_refresh = 0.0

    while True:
        now = taipei_now()
        if not campaign or (time.time() - last_refresh > 1800):
            refreshed = discover_active_campaign(explicit_url=args.url, today=now.date())
            if refreshed:
                campaign = refreshed
            last_refresh = time.time()

        if not campaign or not campaign.get("slots"):
            print(f"[{now.strftime('%H:%M:%S')}] 尚未偵測到進行中的搶紅包場次，30 分鐘後重新探索...")
            time.sleep(1800)
            continue

        slots = campaign["slots"]
        target_dt = None
        for h, m in slots:
            slot_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if slot_time > now:
                target_dt = slot_time
                break

        if not target_dt:
            tomorrow = now + timedelta(days=1)
            # 若明日仍在今日活動期間內，以第一個時段為暫定目標，明日凌晨仍會重新探索
            target_dt = tomorrow.replace(hour=slots[0][0], minute=slots[0][1], second=0, microsecond=0)

        delta = (target_dt - now).total_seconds()
        print(f"[{now.strftime('%H:%M:%S')}] 活動：{campaign.get('title')} | 距下個場次 {target_dt.strftime('%m/%d %H:%M')} 尚有 {int(delta)} 秒...")

        if delta > 150:
            time.sleep(min(delta - 120, 1800))
            continue

        if delta > 15:
            # T-120s 前最後一次確認最新場次與活動參數
            refreshed = discover_active_campaign(explicit_url=args.url, today=taipei_now().date())
            if refreshed:
                campaign = refreshed
            time.sleep(max(1.0, (target_dt - taipei_now()).total_seconds() - 6))
            continue

        while True:
            cur = taipei_now()
            diff = (target_dt - cur).total_seconds()
            if diff <= 0.2:
                print(f"[{cur.strftime('%H:%M:%S.%f')[:12]}] 🎯 觸發狙擊開搶！")
                run_sniper_session(cookies, campaign, slot_dt=target_dt, wait_snipe=False)
                time.sleep(15)
                break
            time.sleep(0.05)


if __name__ == "__main__":
    main()

