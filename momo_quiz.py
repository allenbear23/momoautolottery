#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 雙11 知識王 (10/23 - 10/31) 自動答題與賺 mo 幣腳本
支援多帳號、題庫持久化累積學習、時段預熱與精準啟動、獎勵兌換與 Bark 推播
"""

import sys
import os
import time
import json
import re
import argparse
import base64
import threading
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
import concurrent.futures
import random

DEFAULT_EVENT_URL = "https://momo.dm/BreIZI"
QUIZ_ACTIVITY_ID = "3008445a-40b4-4227-a9cc-db0bdae289a5"
API_BASE = "https://event.momoshop.com.tw"

try:
    from momo_knowledge_base import MOMO_KNOWLEDGE_CONTEXT, MOMO_COMPACT_CONTEXT
except Exception:
    MOMO_KNOWLEDGE_CONTEXT = ""
    MOMO_COMPACT_CONTEXT = ""

# 自動載入本機 .env 設定檔
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

# 10/23-10/31 每日 6 個時段 (均為 11 分)
SLOTS = [
    (10, 11),
    (12, 11),
    (14, 11),
    (18, 11),
    (20, 11),
    (22, 11)
]
SCHEDULE_TIMES = [f"{h:02d}:{m:02d}" for h, m in SLOTS]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoShop",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/edm/cmmedm.jsp?npn=1vEJn4Ny1oqt&n=1"
}

DB_FILE = os.path.join(os.path.dirname(__file__), "quiz_db.json")
DB_LOCK = threading.Lock()
CDN_JSON_URL = "https://finddog.online/momo_questions.json"
SERVER_AUTO_LEARN_URL = "https://api.9ysong.shop/callback2/api/auto-learn"


def normalize_q_text(text: str) -> str:
    """去除標點符號、括號與空白，用於容錯比對題目"""
    if not text:
        return ""
    return re.sub(r'[^\w\u4e00-\u9fa5]', '', text).lower()


def parse_target_answer(raw_ans: str) -> dict:
    """
    智慧解析題庫答案 (移植自 Chrome 擴充 v13 parseTargetAnswer)：
    - 提取指定序號 designated_index (1~4 或 A~D、選項X、選X、括號內選X)
    - 清洗備註、箭頭說明，提取括號別名與斜線多候選詞 (並保護日期格式 11/1 不被拆碎)
    """
    raw = (raw_ans or "").strip()
    designated_index = None

    # 模式 A: 英文序號 A. B. C. D.
    m_alpha = re.match(r'^([a-dA-D])[\.．、\s]+', raw)
    if m_alpha:
        designated_index = ord(m_alpha.group(1).upper()) - 64

    # 模式 B: 選項X、圖片X、圖X
    if not designated_index:
        m_opt = re.match(r'^(?:選項|圖片|圖)\s*([1-4])[\s:：\.．、]*', raw)
        if m_opt:
            designated_index = int(m_opt.group(1))

    # 模式 C: 數字序號 1~4 (排除 2.4GHz, 1.8L 等小數，且排除如「2 1 1 1 櫃」等多位數字排列)
    if not designated_index:
        m_num = re.match(r'^([1-4])([．、]|[\.](?!\d|[gG][hH][zZ])|(?:\.(?=\d{2,}|\d+[元百千萬個包瓶])))', raw)
        if m_num:
            designated_index = int(m_num.group(1))

    # 模式 D: 第1~4號
    if not designated_index:
        m_no = re.match(r'^(?:第)?([1-4])號[\s\.\、\．]*', raw)
        if m_no:
            designated_index = int(m_no.group(1))

    # 模式 E: 選1~4 (後方不接數字，排除 選390)
    if not designated_index:
        m_pick = re.match(r'^選([1-4])(?!\d)[\s\.\、\．]*', raw)
        if m_pick:
            designated_index = int(m_pick.group(1))

    # 模式 F: 括號內備註如「(看到經典款選2)」，排除「選1是錯的」與「選390」
    if not designated_index:
        m_paren = re.search(r'[\(（][^\)）]*?選\s*([1-4])(?!\d|\s*是錯)[^\)）]*?[\)）]', raw)
        if m_paren:
            designated_index = int(m_paren.group(1))

    # 清洗核心答案文字
    clean = raw
    clean = re.sub(r'^[a-dA-D][\.．、\s]+', '', clean)
    clean = re.sub(r'^(?:選項|圖片|圖)\s*[1-4][\s:：\.．、]*', '', clean)
    clean = re.sub(r'^[1-4]([．、\s]+|[\.](?!\d|[gG][hH][zZ])|(?:\.(?=\d{2,}|\d+[元百千萬個包瓶])))', '', clean)
    clean = re.sub(r'^(?:第)?[1-4]號[\s\.\、\．]*', '', clean)
    clean = re.sub(r'^選[1-4](?!\d)[\s\.\、\．]*', '', clean)

    if any(sep in clean for sep in ('→', '->', '➔')):
        parts = re.split(r'[→➔]|->', clean)
        if '關鍵字' in parts[0] or '題目' in parts[0]:
            clean = parts[1] if len(parts) > 1 and parts[1] else clean
        else:
            clean = parts[0] or clean

    aliases = []
    for p in re.findall(r'[\(（](.*?)[\)）]', clean):
        p_clean = p.strip()
        if not re.search(r'bug|錯|選|解析|題目|關鍵字|看到|圖片|瓶身|包裝|中間|朝|個', p_clean, re.I):
            if len(p_clean) >= 2:
                aliases.append(p_clean)

    clean = re.sub(r'[\(（].*?[\)）]', '', clean)
    clean = re.sub(r'[\(（][^\)）]*$', '', clean)
    clean = re.sub(r'[\)）]+$', '', clean).strip()

    candidates = []
    if clean:
        candidates.append(clean)
        if clean.endswith('元') and len(clean) > 1:
            no_yuan = clean[:-1].strip()
            if no_yuan and no_yuan not in candidates:
                candidates.append(no_yuan)
        if '/' in clean or '／' in clean:
            parts = [pt.strip() for pt in re.split(r'[/／]', clean) if pt.strip()]
            is_date_like = all(re.match(r'^\d+$', pt) for pt in parts)
            for pt in parts:
                if pt in candidates:
                    continue
                if is_date_like and re.match(r'^\d{1,2}$', pt):
                    continue
                candidates.append(pt)

    for a in aliases:
        if a not in candidates:
            candidates.append(a)

    return {
        "designated_index": designated_index,
        "clean_text": clean,
        "candidates": candidates
    }


def sync_cdn_bank() -> int:
    """從雲端 CDN (finddog.online) 同步最新題庫並合併至本機 quiz_db.json"""
    try:
        req = urllib.request.Request(
            f"{CDN_JSON_URL}?t={int(time.time() * 1000)}",
            headers={"User-Agent": HEADERS["User-Agent"]}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.getcode() != 200:
                return 0
            data = json.loads(resp.read().decode("utf-8"))
            cdn_questions = data.get("questions", [])
            if not isinstance(cdn_questions, list) or not cdn_questions:
                return 0
    except Exception:
        return 0

    with DB_LOCK:
        db = {"questions": {}}
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    db = json.load(f)
            except Exception:
                pass

        q_dict = db.setdefault("questions", {})
        by_img = {}
        by_norm_no_img = {}
        for k, v in q_dict.items():
            img = (v.get("image") or "").strip()
            img_base = os.path.basename(urllib.parse.urlsplit(img).path).lower() if img else ""
            nt = normalize_q_text(v.get("text", ""))
            if img_base:
                by_img[img_base] = k
            elif nt:
                by_norm_no_img[nt] = k

        changed = False
        for item in cdn_questions:
            q_text = (item.get("q") or "").strip()
            q_img = (item.get("q_img") or "").strip()
            ans_text = (item.get("ans") or "").strip()
            ans_img = (item.get("img_url") or "").strip()
            wrongs = item.get("wrong") or []
            wrong_imgs = item.get("wrong_imgs") or []

            q_img_base = os.path.basename(urllib.parse.urlsplit(q_img).path) if q_img else ""
            q_img_base_low = q_img_base.lower()
            nt = normalize_q_text(q_text)

            target_k = None
            if q_img_base_low and q_img_base_low in by_img:
                target_k = by_img[q_img_base_low]
            elif not q_img_base_low and nt and nt in by_norm_no_img:
                target_k = by_norm_no_img[nt]
            elif q_img_base_low and nt and nt in by_norm_no_img:
                old_k = by_norm_no_img[nt]
                if not q_dict[old_k].get("image"):
                    target_k = old_k

            if not target_k:
                target_k = f"{q_text}::img_{q_img_base}" if q_img_base else q_text
                if not target_k:
                    continue
                rec = q_dict.setdefault(target_k, {})
                changed = True
                if q_img_base_low:
                    by_img[q_img_base_low] = target_k
                elif nt:
                    by_norm_no_img[nt] = target_k
            else:
                rec = q_dict[target_k]

            if q_text and not rec.get("text"):
                rec["text"] = q_text
                changed = True
            if q_img and not rec.get("image"):
                rec["image"] = q_img
                changed = True

            if ans_text or ans_img:
                cur_corr = rec.get("correct")
                if not isinstance(cur_corr, dict):
                    cur_corr = {}
                new_text = ans_text if (ans_text and ans_text != "[圖片答案]") else cur_corr.get("text", "")
                new_img = ans_img or cur_corr.get("image", "")
                if new_text != cur_corr.get("text", "") or new_img != cur_corr.get("image", ""):
                    if new_text:
                        cur_corr["text"] = new_text
                    if new_img:
                        cur_corr["image"] = new_img
                    rec["correct"] = cur_corr
                    changed = True

            cur_wrongs = rec.setdefault("wrong", [])
            for w in wrongs:
                if w and w not in cur_wrongs and not any((isinstance(x, dict) and x.get("text") == w) for x in cur_wrongs):
                    cur_wrongs.append(w)
                    changed = True
            for wi in wrong_imgs:
                if wi:
                    wi_base = os.path.basename(urllib.parse.urlsplit(wi).path)
                    if not any((isinstance(x, dict) and os.path.basename(x.get("image", "")) == wi_base) or (isinstance(x, str) and wi_base in x) for x in cur_wrongs):
                        cur_wrongs.append({"text": "", "image": wi})
                        changed = True

        if changed:
            try:
                with open(DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        return len(q_dict)


def report_auto_learn_batch(reports: list):
    """整局結束後一次性批次上傳題庫學習紀錄至雲端伺服器"""
    if not reports:
        return
    try:
        payload = {"reports": reports, "count": len(reports), "batch": True}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SERVER_AUTO_LEARN_URL,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": HEADERS["User-Agent"]},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=4) as _:
            pass
    except Exception:
        pass


def load_quiz_db() -> dict:
    with DB_LOCK:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"questions": {}}


def save_quiz_db(db: dict):
    with DB_LOCK:
        try:
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"儲存題庫異常: {e}")


def find_db_record(question: dict, db: dict) -> tuple:
    """
    雙軌制查找題庫紀錄 (移植自 Chrome 擴充 v13 findMatchingQuestion)：
    軌道 1 (附圖題)：
      1A: 優先以題目圖片檔名/UUID 精準命中 (不受題幹文字微調影響)
      1B: 次選兼容以答案圖片欄位儲存題目圖片 UUID 之歷史紀錄
      1C: 若題目文字相同且題庫該題尚未登記圖片，自動配對升級；若已有不同圖片則絕不串題
    軌道 2 (純文字題)：
      2A: 優先匹配同樣無題目圖片之純文字題目
      2B: 次選寬鬆文字匹配
    """
    q_text = (question.get("text") or "").strip()
    q_img = (question.get("image") or "").strip()
    q_img_base = os.path.basename(urllib.parse.urlsplit(q_img).path).lower() if q_img else ""
    norm_q = normalize_q_text(q_text)

    key = get_question_key(question)
    q_dict = db.get("questions", {})

    # 0. 精確 key 直接命中
    if key in q_dict:
        return key, q_dict[key]

    # 軌道 1：題目附帶圖片
    if q_img_base:
        # 1A: 題目圖片 UUID 精準命中
        for db_k, db_v in q_dict.items():
            v_img = (db_v.get("image") or "").strip()
            v_img_base = os.path.basename(urllib.parse.urlsplit(v_img).path).lower() if v_img else ""
            if v_img_base and (v_img_base == q_img_base or v_img_base in q_img_base or q_img_base in v_img_base):
                return db_k, db_v

        # 1B: 兼容答案圖片欄位儲存題目圖片 UUID
        for db_k, db_v in q_dict.items():
            corr = db_v.get("correct")
            corr_img = (corr.get("image") or "").strip() if isinstance(corr, dict) else ""
            corr_img_base = os.path.basename(urllib.parse.urlsplit(corr_img).path).lower() if corr_img else ""
            if corr_img_base and (corr_img_base == q_img_base or corr_img_base in q_img_base or q_img_base in corr_img_base):
                return db_k, db_v

        # 1C: 題目文字相同，且題庫該項目尚未登記任何題目圖片
        if norm_q:
            for db_k, db_v in q_dict.items():
                v_img = (db_v.get("image") or "").strip()
                if not v_img:
                    v_norm = normalize_q_text(db_v.get("text", ""))
                    if v_norm and v_norm == norm_q:
                        return db_k, db_v

        return key, {}

    # 軌道 2：純文字題目
    if not q_img_base and q_text in q_dict:
        rec = q_dict[q_text]
        if not rec.get("image"):
            return q_text, rec

    if norm_q:
        # 優先匹配無題目圖片之紀錄
        for db_k, db_v in q_dict.items():
            if not (db_v.get("image") or "").strip():
                v_norm = normalize_q_text(db_v.get("text", ""))
                if v_norm and v_norm == norm_q:
                    return db_k, db_v
        # 次選寬鬆匹配
        for db_k, db_v in q_dict.items():
            v_norm = normalize_q_text(db_v.get("text", ""))
            if v_norm and v_norm == norm_q:
                return db_k, db_v

    return key, {}


def update_db_question(db_key: str, question: dict, choices: list, correct: dict = None, wrong_choice: dict = None, unverified_choice: dict = None):
    """線程安全的增量更新題庫，防止多帳號並行時覆蓋彼此記錄"""
    with DB_LOCK:
        db = {"questions": {}}
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    db = json.load(f)
            except Exception:
                pass

        q_dict = db.setdefault("questions", {})
        # 若以正規化比對已存在別名 key，優先更新已存在項 (但嚴格限制圖片必須一致)
        target_key = db_key
        norm_target = normalize_q_text(question.get("text", ""))
        q_img_base = os.path.basename(urllib.parse.urlsplit(question.get("image", "")).path) if question.get("image") else ""
        if target_key not in q_dict and norm_target:
            for k, v in q_dict.items():
                v_img_base = os.path.basename(urllib.parse.urlsplit(v.get("image", "")).path) if v.get("image") else ""
                if q_img_base or v_img_base:
                    if q_img_base != v_img_base:
                        continue
                if normalize_q_text(v.get("text", "")) == norm_target:
                    target_key = k
                    break

        rec = q_dict.setdefault(target_key, {})
        rec["text"] = question.get("text", rec.get("text", ""))
        rec["image"] = question.get("image", rec.get("image", ""))
        rec["uuid"] = question.get("uuid", rec.get("uuid", ""))
        rec["choices"] = choices or rec.get("choices", [])
        rec["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if correct:
            rec["correct"] = correct
            c_uuid = correct.get("uuid") if isinstance(correct, dict) else ""
            c_norm = normalize_q_text(correct.get("text", "") if isinstance(correct, dict) else str(correct))
            c_img_base = os.path.basename(urllib.parse.urlsplit(correct.get("image", "")).path).lower() if isinstance(correct, dict) and correct.get("image") else ""
            if "wrong" in rec:
                cleaned_wrongs = []
                for w in rec["wrong"]:
                    w_uuid = w.get("uuid", "") if isinstance(w, dict) else ""
                    w_norm = normalize_q_text(w.get("text", "") if isinstance(w, dict) else (w if isinstance(w, str) else ""))
                    w_img_base = os.path.basename(urllib.parse.urlsplit(w.get("image", "")).path).lower() if isinstance(w, dict) and w.get("image") else ""
                    if (c_uuid and w_uuid == c_uuid) or (c_norm and w_norm == c_norm) or (c_img_base and w_img_base == c_img_base):
                        continue
                    cleaned_wrongs.append(w)
                rec["wrong"] = cleaned_wrongs

        if wrong_choice:
            wrongs = rec.setdefault("wrong", [])
            w_uuid = wrong_choice.get("uuid") if isinstance(wrong_choice, dict) else wrong_choice
            w_norm = normalize_q_text(wrong_choice.get("text", "") if isinstance(wrong_choice, dict) else (wrong_choice if isinstance(wrong_choice, str) else ""))
            w_img_base = os.path.basename(urllib.parse.urlsplit(wrong_choice.get("image", "")).path).lower() if isinstance(wrong_choice, dict) and wrong_choice.get("image") else ""
            if not any((w.get("uuid") if isinstance(w, dict) else w) == w_uuid for w in wrongs):
                wrongs.append(wrong_choice)
            # 即時淘汰錯誤正解 (移植自 Chrome 擴充 v13)：若題庫原紀錄之 correct 與本次實測答錯選項相同，立即移除該錯誤 correct
            cur_corr = rec.get("correct")
            if cur_corr:
                cc_uuid = cur_corr.get("uuid", "") if isinstance(cur_corr, dict) else ""
                cc_norm = normalize_q_text(cur_corr.get("text", "") if isinstance(cur_corr, dict) else str(cur_corr))
                cc_img_base = os.path.basename(urllib.parse.urlsplit(cur_corr.get("image", "")).path).lower() if isinstance(cur_corr, dict) and cur_corr.get("image") else ""
                if (w_uuid and cc_uuid and w_uuid == cc_uuid) or (w_norm and cc_norm and w_norm == cc_norm) or (w_img_base and cc_img_base and w_img_base == cc_img_base):
                    rec.pop("correct", None)

        if unverified_choice:
            rec["unverified_choice"] = unverified_choice

        try:
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"儲存題庫異常: {e}")


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
        if any(k in clean for k in ("LOGINSESSION", "st=", "_atrk", "isEN")):
            cookies.append(clean)

    return cookies


def send_quiz_request(method: str, path: str, cookie: str, body: dict = None):
    url = f"{API_BASE}{path}"
    headers = dict(HEADERS)
    headers["Cookie"] = cookie.strip()
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.getcode(), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            return e.code, err_data
        except Exception:
            return e.code, {"code": f"HTTP_ERROR_{e.code}"}
    except Exception as e:
        return 0, {"code": "NETWORK_ERROR", "detail": str(e)}


def prewarm_connection(cookie: str):
    """預熱連線"""
    try:
        send_quiz_request("GET", f"/quiz/{QUIZ_ACTIVITY_ID}.PROMO", cookie)
    except Exception:
        pass


def get_gemini_api_keys(api_key: str = None) -> list:
    keys = []
    raw = ""
    if api_key:
        raw = api_key
    elif os.getenv("GEMINI_API_KEY"):
        raw = os.getenv("GEMINI_API_KEY", "")
    else:
        key_file = os.path.join(os.path.dirname(__file__), "gemini_key.txt")
        if os.path.exists(key_file):
            try:
                with open(key_file, "r", encoding="utf-8") as f:
                    raw = f.read()
            except Exception:
                pass

    for line in raw.replace(",", "\n").splitlines():
        k = line.strip()
        if k and not k.startswith("#") and k not in keys:
            keys.append(k)
    return keys


MODEL_RATE_LIMITED = {}


def query_gemini(question_text: str, choices: list, api_key: str = None, question_image: str = None, target_hint: str = None) -> str:
    """利用 Google Gemini API 進行即時智能判題 (支援圖文多模態、思維鏈 CoT 與題庫輔助提示)"""
    keys = get_gemini_api_keys(api_key)
    if not keys:
        return None

    def fetch_img(url):
        if not url:
            return None, "image/jpeg"
        raw_data = None
        orig_mime = "image/jpeg"
        try:
            if url.startswith("http"):
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=2.5) as r:
                    raw_data = r.read()
                    orig_mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
            elif os.path.exists(url):
                with open(url, "rb") as f:
                    raw_data = f.read()
                    orig_mime = "image/png" if url.lower().endswith(".png") else "image/jpeg"
        except Exception:
            return None, "image/jpeg"

        if not raw_data:
            return None, "image/jpeg"

        try:
            from PIL import Image
            import io
            if len(raw_data) > 60_000:
                im = Image.open(io.BytesIO(raw_data))
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.thumbnail((512, 512))
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=80)
                return buf.getvalue(), "image/jpeg"
        except Exception:
            pass
        return raw_data, orig_mime

    # 並行下載選項圖片加速
    choice_imgs = [c.get("image", "").strip() for c in choices]
    has_choice_images = any(bool(u) for u in choice_imgs)

    fetched_choice_imgs = []
    if has_choice_images:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(choices)) as ex:
            fetched_choice_imgs = list(ex.map(fetch_img, choice_imgs))
    else:
        fetched_choice_imgs = [(None, "image/jpeg")] * len(choices)

    options_list = []
    choice_image_parts = []
    for i, c in enumerate(choices):
        t = (c.get('text') or '').strip()
        img_url = (c.get('image') or '').strip()
        if not t and img_url:
            t = f"選項 {i+1} 圖片"
        options_list.append(f"{i+1}. {t}")

        c_img_data, c_mime = fetched_choice_imgs[i]
        if c_img_data:
            choice_image_parts.append({"text": f"【選項 {i+1} 圖片】："})
            choice_image_parts.append({
                "inlineData": {
                    "mimeType": c_mime,
                    "data": base64.b64encode(c_img_data).decode("utf-8")
                }
            })

    options_str = "\n".join(options_list)

    try:
        from momo_knowledge_base import MOMO_COMPACT_CONTEXT
        momo_context = MOMO_COMPACT_CONTEXT
    except Exception:
        momo_context = ""

    neg_warn = ""
    if any(neg in question_text for neg in ("沒有", "不是", "非", "何者不", "不包含", "未包含", "無")):
        neg_warn = "⚠️【重要警告：本題為反向/否定題，請選出『不包含 / 沒有』的選項！】\n\n"

    hint_str = ""
    if target_hint:
        hint_str = f"💡【題庫提示】：已知本題正確答案特徵為『{target_hint}』，請在各選項圖片中仔細比對找出對應商品！\n\n"

    if has_choice_images or question_image:
        cot_instruction = (
            "【作答規範】：\n"
            "第一行必須直接輸出明確的單一數字選項，格式為：『最終結論：選項 X』(X 為 1, 2, 3 或 4，切勿輸出佔位符)。\n"
            "第二行再用一句話說明辨識依據。"
        )
    else:
        cot_instruction = (
            "請直接輸出格式：『最終結論：選項 X』(X 為 1, 2, 3 或 4)。"
        )

    prompt = (
        f"你是一個精通台灣 momo 購物網活動與商品通識的解題專家。\n\n"
        f"{momo_context}\n"
        f"{neg_warn}"
        f"{hint_str}"
        f"【解題原則】：\n"
        f"- 若問前開行李箱：必須具有正面獨立掀開門、上掀開口或快取筆電層，非左右對開式。\n"
        f"- 若問大小/規格：直立式桌機(Tower) > 薄型小型(SFF) > 超微型(Tiny)；Pro Max/Ultra > 標準款。\n"
        f"- 若為商品附圖：請仔細辨識圖片上的商標文字、包裝印字與Logo。\n"
        f"- 若為純圖片選項：請仔細比對各選項圖片中的包裝品牌、品名與特徵。\n\n"
        f"【問題】：{question_text}\n"
        f"【選項】：\n{options_str}\n\n"
        f"{cot_instruction}"
    )

    parts = []
    if question_image:
        q_data, q_mime = fetch_img(question_image)
        if q_data:
            parts.append({"text": "【題目附圖】："})
            parts.append({
                "inlineData": {
                    "mimeType": q_mime,
                    "data": base64.b64encode(q_data).decode("utf-8")
                }
            })

    if choice_image_parts:
        parts.extend(choice_image_parts)

    parts.append({"text": prompt})

    models = [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3-flash-preview"
    ]

    now_t = time.time()
    for key in keys:
        for model in models:
            rate_key = f"{key[-8:]}_{model}"
            # 若該 Key 的該模型剛觸發 429 限流，自動跳過進入下一 Key 或下一備援模型，防止浪費 60s 倒數時間
            if now_t < MODEL_RATE_LIMITED.get(rate_key, 0):
                continue

            timeout_sec = 4.2 if (has_choice_images or question_image) else 3.0
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0.0,
                    "maxOutputTokens": 250
                }
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    candidates = result.get("candidates", [])
                    if candidates:
                        parts_list = candidates[0].get("content", {}).get("parts", [])
                        non_thought = [p.get("text", "") for p in parts_list if not p.get("thought", False)]
                        text_out = " ".join(non_thought).strip() if non_thought else " ".join(p.get("text", "") for p in parts_list).strip()
                        print(f"[{model}] 回傳內容:\n{text_out}")

                        # 1. 優先從「結論：選項 X」或「答案：X」精確提取
                        m_target = re.search(r'(?:最終結論|結論|正解|答案|故選|應選)[^\n]*?(?:選項\s*|選\s*)?([1-9])\b', text_out)
                        if m_target:
                            idx = int(m_target.group(1)) - 1
                            if 0 <= idx < len(choices):
                                print(f"[{model}] 精確結論提取選項: {idx+1}. {choices[idx].get('text') or choices[idx].get('uuid')}")
                                return choices[idx]["uuid"]

                        # 2. 次選：從倒數行提取單獨存在的編號
                        lines = [ln.strip() for ln in text_out.splitlines() if ln.strip()]
                        if lines:
                            for ln in reversed(lines[-3:]):
                                m = re.search(r'^(?:選項\s*)?([1-9])$', ln)
                                if m:
                                    idx = int(m.group(1)) - 1
                                    if 0 <= idx < len(choices):
                                        print(f"[{model}] 倒數行提取選項: {idx+1}. {choices[idx].get('text') or choices[idx].get('uuid')}")
                                        return choices[idx]["uuid"]

                        # 3. 結論行關鍵字比對（避免分析文中的干擾詞）
                        last_line = lines[-1] if lines else text_out
                        for idx, c in enumerate(choices):
                            c_t = (c.get("text") or "").strip()
                            if c_t and len(c_t) >= 2 and c_t in last_line:
                                print(f"[{model}] 結論行命中關鍵字: {c_t}")
                                return c["uuid"]

                        # 4. 全文數字提取回退
                        m_all = re.search(r'\b([1-9])\b', text_out)
                        if m_all:
                            idx = int(m_all.group(1)) - 1
                            if 0 <= idx < len(choices):
                                print(f"[{model}] 全文數字提取選項: {idx+1}. {choices[idx].get('text') or choices[idx].get('uuid')}")
                                return choices[idx]["uuid"]
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    rate_key = f"{key[-8:]}_{model}"
                    MODEL_RATE_LIMITED[rate_key] = time.time() + 75
                    print(f"[{model}] Key ...{key[-4:]} 觸發 429 限流，自動冷卻 75 秒並無縫切換下一 Key 或備援模型")
                continue
            except Exception:
                continue

    return None


def get_groq_api_key(api_key: str = None) -> str:
    if api_key:
        return api_key.strip()
    env_key = os.getenv("GROQ_API_KEY", "").strip()
    if env_key:
        return env_key
    key_file = os.path.join(os.path.dirname(__file__), "groq_key.txt")
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


GROQ_DISABLED = False


def query_groq(question_text: str, choices: list, api_key: str = None, question_image: str = None) -> str:
    """利用 Groq 進行極速 AI 解題 (文字/常識題每日 14,400 次免費，0.3s 極速回傳)"""
    global GROQ_DISABLED
    if GROQ_DISABLED:
        return None

    # 圖文題由支援多模態的 AI 處理
    if question_image or any(c.get("image") for c in choices):
        return None

    key = get_groq_api_key(api_key)
    if not key:
        return None

    options_list = [f"{i+1}. {c.get('text', '') or c.get('uuid', '')}" for i, c in enumerate(choices)]
    options_str = "\n".join(options_list)

    neg_warn = ""
    if any(neg in question_text for neg in ("沒有", "不是", "非", "何者不", "不包含", "未包含", "無")):
        neg_warn = "⚠️【重要警告：本題為反向/否定題，請選出『不包含 / 沒有』的選項！】\n\n"

    prompt = f"""請以台灣 momo 購物網活動與日常生活常見商品常識為準，判斷這道題目的正確答案。

{MOMO_COMPACT_CONTEXT}

{neg_warn}【題目】：{question_text}
【選項清單】：
{options_str}

【作答規則】：
1. 請先寫一句簡短分析各選項。
2. 最後一行請務必輸出：『最終結論：選項 X』(X 為 1, 2, 3 或 4)。"""

    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3.8-27b"]
    url = "https://api.groq.com/openai/v1/chat/completions"

    for model in models:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 120
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                text_out = res["choices"][0]["message"]["content"].strip()
                m_target = re.search(r'(?:最終結論|結論|正解|答案|應選|故選)[^\n]*?(?:選項\s*|選\s*)?([1-9])\b', text_out)
                if m_target:
                    idx = int(m_target.group(1)) - 1
                    if 0 <= idx < len(choices):
                        print(f"[Groq AI ({model})] 結論解析選項: {idx+1}. {choices[idx].get('text')}")
                        return choices[idx]["uuid"]

                # 提取末行結論的關鍵字或數字，避免分析文本中提及錯誤選項被誤判
                last_line = text_out.strip().splitlines()[-1] if text_out.strip() else ""
                m_last = re.search(r'\b([1-9])\b', last_line)
                if m_last:
                    idx = int(m_last.group(1)) - 1
                    if 0 <= idx < len(choices):
                        print(f"[Groq AI ({model})] 末行數字解析選項: {idx+1}. {choices[idx].get('text')}")
                        return choices[idx]["uuid"]

                for idx, c in enumerate(choices):
                    c_text = (c.get("text") or "").strip()
                    if c_text and c_text in last_line:
                        print(f"[Groq AI ({model})] 末行命中關鍵字: {c_text}")
                        return c["uuid"]

                m = re.search(r'\b([1-9])\b', text_out)
                if m:
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(choices):
                        print(f"[Groq AI ({model})] 全文首個數字選項為: {idx+1}. {choices[idx].get('text')}")
                        return choices[idx]["uuid"]
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403):
                GROQ_DISABLED = True
                break
            continue
        except Exception:
            continue

    return None

def get_openrouter_api_key(api_key: str = None) -> str:
    if api_key:
        return api_key.strip()
    env_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if env_key:
        return env_key
    key_file = os.path.join(os.path.dirname(__file__), "openrouter_key.txt")
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


OPENROUTER_DISABLED = False


def query_openrouter(question_text: str, choices: list, api_key: str = None, question_image: str = None) -> str:
    """利用 OpenRouter 免費多模態模型進行智能解題 (支援題目附圖與型C純圖片選項)"""
    global OPENROUTER_DISABLED
    if OPENROUTER_DISABLED:
        return None

    key = get_openrouter_api_key(api_key)
    if not key:
        return None

    has_choice_images = any(bool(c.get("image")) for c in choices)
    has_image = bool(question_image or has_choice_images)

    options_list = []
    choice_image_items = []
    for i, c in enumerate(choices):
        t = (c.get('text') or '').strip()
        img_url = (c.get('image') or '').strip()
        if not t and img_url:
            t = f"圖片選項 {i+1}"
        options_list.append(f"{i+1}. {t or c.get('uuid', '')}")

        if img_url:
            try:
                c_img_data = None
                c_mime = "image/jpeg"
                if img_url.startswith("http"):
                    req_img = urllib.request.Request(img_url, headers=HEADERS)
                    with urllib.request.urlopen(req_img, timeout=3) as img_resp:
                        c_img_data = img_resp.read()
                        c_mime = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                elif os.path.exists(img_url):
                    with open(img_url, "rb") as f:
                        c_img_data = f.read()
                        if img_url.lower().endswith(".png"):
                            c_mime = "image/png"
                if c_img_data:
                    c_b64 = base64.b64encode(c_img_data).decode("utf-8")
                    choice_image_items.append({"type": "text", "text": f"【選項 {i+1} 圖片】："})
                    choice_image_items.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{c_mime};base64,{c_b64}"}
                    })
            except Exception:
                pass

    options_str = "\n".join(options_list)

    try:
        from momo_knowledge_base import MOMO_COMPACT_CONTEXT
        context_str = f"\n{MOMO_COMPACT_CONTEXT}\n"
    except Exception:
        context_str = ""

    prompt = (
        f"題目：{question_text}\n"
        f"選項：\n{options_str}\n\n"
        f"參考提示：\n- momo雙11活動代言人為 SUPER JUNIOR-83z。\n- 若為商品分類，書桌/椅子/床屬於家具寢飾居家生活館。\n"
        f"請直接輸出唯一正確的選項編號數字 (例如只輸出 1 或 2 或 3 或 4)："
    )

    content_items = []
    if question_image:
        try:
            img_data = None
            mime = "image/jpeg"
            if question_image.startswith("http"):
                req_img = urllib.request.Request(question_image, headers=HEADERS)
                with urllib.request.urlopen(req_img, timeout=4) as img_resp:
                    img_data = img_resp.read()
                    mime = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
            elif os.path.exists(question_image):
                with open(question_image, "rb") as f:
                    img_data = f.read()
                    if question_image.lower().endswith(".png"):
                        mime = "image/png"
            if img_data:
                b64_data = base64.b64encode(img_data).decode("utf-8")
                content_items.append({"type": "text", "text": "【題目附圖】："})
                content_items.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64_data}"}
                })
        except Exception:
            pass

    if choice_image_items:
        content_items.extend(choice_image_items)

    content_items.append({"type": "text", "text": prompt})

    models = [
        "dots-studio/dots-3-note-preview:free",
        "nvidia/nemotron-3.5-super-vl:free"
    ]
    max_tokens = 120
    req_timeout = 3.2

    url = "https://openrouter.ai/api/v1/chat/completions"

    for model in models:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content_items}],
            "temperature": 0.0,
            "max_tokens": max_tokens
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/allenbear23/momoautolottery",
                "X-Title": "momo quiz bot"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                choice = res.get("choices", [{}])[0]
                msg = choice.get("message", {})
                text_out = (msg.get("content") or "").strip()
                reasoning = (msg.get("reasoning") or "").strip()

                # 1. 優先由 content 提取明確數字
                if text_out:
                    m = re.search(r'\b([1-9])\b', text_out)
                    if m:
                        idx = int(m.group(1)) - 1
                        if 0 <= idx < len(choices):
                            print(f"[OpenRouter AI ({model})] content 解析選項為: {idx+1}. {choices[idx].get('text') or choices[idx].get('uuid')}")
                            return choices[idx]["uuid"]

                    for c in choices:
                        if c.get("text") and c.get("text") in text_out:
                            print(f"[OpenRouter AI ({model})] content 命中關鍵字: {c.get('text')}")
                            return c["uuid"]

                # 2. 由 reasoning 深入分析提取
                if reasoning:
                    tail = reasoning[-300:] if len(reasoning) > 300 else reasoning
                    matches = re.findall(r'(?:答案(?:是|為|應為)?|正確答案(?:是|為)?|故選|因此選|應選|選擇|correct option is|answer is|the answer is|choice is)\s*([1-9])\b', tail, re.IGNORECASE)
                    if matches:
                        idx = int(matches[-1]) - 1
                        if 0 <= idx < len(choices):
                            print(f"[OpenRouter AI ({model})] reasoning 結論命中選項: {idx+1}. {choices[idx].get('text') or choices[idx].get('uuid')}")
                            return choices[idx]["uuid"]

                    # 針對純圖片選項：比對各 Image i 分析區塊與題幹關鍵詞
                    if has_choice_images:
                        q_keywords = [w for w in re.split(r'[^\w]+', question_text) if len(w) >= 2 and w not in ('下列', '哪一個', '哪項', '何者', '圖片', '商品', '屬於', '這是')]
                        best_img_idx = -1
                        max_img_score = 0
                        for i in range(len(choices)):
                            num = i + 1
                            pattern = rf'(?:Image|Option|選項|圖片)\s*{num}\b(.*?)(?=(?:Image|Option|選項|圖片)\s*\d\b|$)'
                            match = re.search(pattern, reasoning, re.DOTALL | re.IGNORECASE)
                            if match:
                                block = match.group(1).lower()
                                score = 0
                                for kw in q_keywords:
                                    if kw.lower() in block:
                                        score += 3
                                if 'desk' in block and '書桌' in question_text:
                                    score += 3
                                if 'pillow' in block and '枕頭' in question_text:
                                    score += 3
                                if score > max_img_score:
                                    max_img_score = score
                                    best_img_idx = i
                        if best_img_idx >= 0 and max_img_score >= 3:
                            print(f"[OpenRouter AI ({model})] 圖片區塊關鍵詞命中: {choices[best_img_idx].get('uuid')}")
                            return choices[best_img_idx]["uuid"]

                    best_c = None
                    best_score = 0
                    synonyms = {
                        "家具": ["furniture", "desk", "chair", "table", "bed", "書桌", "椅子", "桌子"],
                        "3C": ["computer", "laptop", "electronic", "phone", "電腦", "手機"],
                        "清潔": ["cleaning", "detergent", "tissue", "衛生紙", "洗衣"],
                        "時尚": ["fashion", "clothes", "clothing", "apparel", "衣服", "洋裝"],
                        "食品": ["food", "snack", "drink", "零食", "飲料"],
                        "美妝": ["beauty", "cosmetic", "skincare", "保養", "彩妝"]
                    }
                    for c in choices:
                        t = (c.get("text") or "").strip()
                        if not t:
                            continue
                        score = 0
                        if t in reasoning:
                            score += len(t) * 2
                        words = [w for w in re.split(r'[/、\s]', t) if len(w) >= 2]
                        for w in words:
                            if w in reasoning:
                                score += len(w)
                        for k, syns in synonyms.items():
                            if k in t:
                                for syn in syns:
                                    if syn in reasoning.lower():
                                        score += 2
                        if score > best_score:
                            best_score = score
                            best_c = c

                    if best_c and best_score >= 2:
                        print(f"[OpenRouter AI ({model})] reasoning 語意比對命中: {best_c.get('text')}")
                        return best_c["uuid"]

                    m_num = re.findall(r'\b([1-9])\b', tail)
                    if m_num:
                        idx = int(m_num[-1]) - 1
                        if 0 <= idx < len(choices):
                            print(f"[OpenRouter AI ({model})] reasoning 尾端數字命中: {idx+1}. {choices[idx].get('text') or choices[idx].get('uuid')}")
                            return choices[idx]["uuid"]
        except urllib.error.HTTPError as e:
            if e.code in (401, 402, 429):
                OPENROUTER_DISABLED = True
                break
            continue
        except Exception:
            continue

    return None


def search_best_choice(question_text: str, choices: list, known_wrong: list) -> str:
    """利用關鍵字搜尋比對最佳選項"""
    filtered_choices = [c for c in choices if c.get("uuid", "") not in known_wrong and c.get("text", "") not in known_wrong]
    if not filtered_choices:
        filtered_choices = choices

    if len(filtered_choices) == 1:
        return filtered_choices[0].get("uuid") or filtered_choices[0].get("text", "")

    # 嘗試 Wikipedia 搜尋比對
    try:
        clean_q = re.sub(r'[^\w\s]', ' ', question_text).strip()
        url = 'https://zh.wikipedia.org/w/api.php?action=query&list=search&srsearch=' + urllib.parse.quote(clean_q) + '&format=json'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            snippet = ' '.join(item['snippet'] for item in data.get('query', {}).get('search', []))
            best_choice = None
            max_cnt = -1
            for c in filtered_choices:
                t = c.get('text', '')
                if t:
                    cnt = snippet.count(t)
                    if cnt > max_cnt:
                        max_cnt = cnt
                        best_choice = c.get('uuid') or t
            if max_cnt > 0 and best_choice:
                return best_choice
    except Exception:
        pass

    # 預設回傳第一個合法選項
    return filtered_choices[0].get("uuid") or filtered_choices[0].get("text", "")


def get_question_key(question: dict) -> str:
    """產生題目唯一鍵值，若有圖片則結合圖片檔名以防同名題目覆蓋"""
    q_text = (question.get("text") or "").strip()
    q_img = (question.get("image") or "").strip()
    q_uuid = (question.get("uuid") or "").strip()
    if q_img:
        img_name = os.path.basename(urllib.parse.urlsplit(q_img).path)
        return f"{q_text}::img_{img_name}" if q_text else f"img_{img_name}"
    return q_text or q_uuid


def select_answer(question: dict, choices: list, db: dict, gemini_key: str = None, groq_key: str = None, openrouter_key: str = None) -> str:
    q_text = question.get("text", "").strip()
    key, record = find_db_record(question, db)

    correct_val = record.get("correct")
    wrong_vals = list(record.get("wrong", []))
    target_hint = None

    raw_target_text = ""
    target_uuid = ""
    target_img = ""
    if correct_val:
        target_uuid = correct_val.get("uuid", "") if isinstance(correct_val, dict) else ""
        raw_target_text = correct_val.get("text", "") if isinstance(correct_val, dict) else (correct_val if isinstance(correct_val, str) else "")
        target_img = correct_val.get("image", "") if isinstance(correct_val, dict) else ""

    parsed = parse_target_answer(raw_target_text)
    designated_index = parsed["designated_index"]
    clean_target = parsed["clean_text"]
    candidates = parsed["candidates"]
    target_hint = clean_target or raw_target_text
    target_img_base = os.path.basename(urllib.parse.urlsplit(target_img).path).lower() if target_img else ""

    # 雙向防護 (移植自 Chrome 擴充 v13)：若正解候選詞或答案圖片誤存於 wrong 清單中，先從 wrong 剔除，防止誤殺正解
    norm_cands = {normalize_q_text(cnd) for cnd in candidates if normalize_q_text(cnd)}

    def is_wrong(c):
        c_uuid = c.get("uuid", "")
        c_text = (c.get("text") or "").strip()
        norm_c = normalize_q_text(c_text)
        c_img = (c.get("image") or "").strip()
        c_img_base = os.path.basename(urllib.parse.urlsplit(c_img).path).lower() if c_img else ""

        # 若該選項本身等於已知正解候選詞或正解圖片，絕不可判定為錯誤
        if norm_c and norm_c in norm_cands:
            return False
        if target_img_base and c_img_base and (c_img_base == target_img_base or target_img_base in c_img_base):
            return False

        for w in wrong_vals:
            w_uuid = w.get("uuid") if isinstance(w, dict) else ""
            raw_w_text = w.get("text") if isinstance(w, dict) else (w if isinstance(w, str) else "")
            clean_w = re.sub(r'[\(（]?選項\s*\d+[\)）]?', '', raw_w_text or "").strip()
            norm_w = normalize_q_text(clean_w)
            w_img = w.get("image", "") if isinstance(w, dict) else ""
            w_img_base = os.path.basename(urllib.parse.urlsplit(w_img).path).lower() if w_img else ""

            if c_uuid and w_uuid and c_uuid == w_uuid:
                return True
            if c_text and clean_w and c_text == clean_w:
                return True
            if not w_uuid and norm_w and norm_c and norm_c == norm_w:
                return True
            if c_img_base and w_img_base and (c_img_base == w_img_base or w_img_base in c_img_base):
                return True
        return False

    # 策略 1: 題庫註明指定序號 (例如「3．紅色 (bug題，選1是錯的)」、「選項4：4G」)
    if designated_index and 1 <= designated_index <= len(choices):
        cand = choices[designated_index - 1]
        if not is_wrong(cand):
            print(f"[題庫指定序號命中] 直接鎖定第 {designated_index} 個選項: {cand.get('text') or cand.get('uuid')}")
            return cand["uuid"]

    # 策略 2: 命中題庫已知正確答案 (分兩階段：2A 100%精準相等優先 -> 2B 安全子字串次選)
    if correct_val:
        is_date_answer = any(re.match(r'^\d+[\/月日]\d+', cnd) for cnd in candidates)

        # 策略 2A: 100% 精準完全相等比對 (防止 momoBOOK 被 momoBOOKS 截胡)
        for c in choices:
            if is_wrong(c):
                continue
            c_uuid = c.get("uuid", "")
            c_text = (c.get("text") or "").strip()
            c_img = (c.get("image") or "").strip()
            c_img_base = os.path.basename(urllib.parse.urlsplit(c_img).path).lower() if c_img else ""

            if c_uuid and target_uuid and c_uuid == target_uuid:
                print(f"[題庫精準命中] UUID 匹配: {c_text or c_uuid}")
                return c_uuid

            if target_img_base and c_img_base and (c_img_base == target_img_base or target_img_base in c_img_base):
                print(f"[題庫圖片命中] 選擇正解圖片: {c_img_base}")
                return c_uuid

            if c_text and candidates:
                for cand in candidates:
                    if is_date_answer:
                        if re.sub(r'\s+', '', c_text).lower() == re.sub(r'\s+', '', cand).lower():
                            print(f"[題庫日期精準命中] 選擇: {c_text}")
                            return c_uuid
                    else:
                        norm_c = normalize_q_text(c_text)
                        norm_cand = normalize_q_text(cand)
                        if norm_c and norm_cand and norm_c == norm_cand:
                            print(f"[題庫精準命中] 選擇已確認之正確答案: {c_text}")
                            return c_uuid

        # 策略 2B: 安全子字串比對 (僅在無任何選項完全相等且非日期格式時啟動)
        if not is_date_answer and candidates:
            for c in choices:
                if is_wrong(c):
                    continue
                c_uuid = c.get("uuid", "")
                c_text = (c.get("text") or "").strip()
                norm_c = normalize_q_text(c_text)
                if not norm_c or norm_c.isdigit() or len(norm_c) < 3:
                    continue
                for cand in candidates:
                    norm_cand = normalize_q_text(cand)
                    if not norm_cand or norm_cand.isdigit() or len(norm_cand) < 3:
                        continue
                    if norm_cand in norm_c or norm_c in norm_cand:
                        print(f"[題庫模糊命中] 選擇候選答案: {c_text}")
                        return c_uuid

    # 策略 3: 已知錯誤排除法
    candidate_choices = [c for c in choices if not is_wrong(c)]
    if not candidate_choices:
        candidate_choices = choices

    if len(candidate_choices) == 1:
        print(f"[排除法] 已排除其他錯誤選項，選取唯一剩餘選項: {candidate_choices[0].get('text') or candidate_choices[0]['uuid']}")
        return candidate_choices[0]["uuid"]

    has_img = bool(question.get("image") or any(c.get("image") for c in candidate_choices))

    # 4. 優先呼叫 Google Gemini AI 全面解題
    gemini_choice_id = query_gemini(q_text, candidate_choices, gemini_key, question.get("image"), target_hint=target_hint)
    if gemini_choice_id:
        return gemini_choice_id

    # 5. 次之呼叫 Groq AI 備援 (純文字題)
    if not has_img:
        groq_choice_id = query_groq(q_text, candidate_choices, groq_key)
        if groq_choice_id:
            return groq_choice_id

    # 6. 次之呼叫 OpenRouter AI 備援 (支援題目圖文與型C純圖片選項)
    openrouter_choice_id = query_openrouter(q_text, candidate_choices, openrouter_key, question.get("image"))
    if openrouter_choice_id:
        return openrouter_choice_id

    # 7. 搜尋比對或排除法回退
    return search_best_choice(q_text, candidate_choices, wrong_vals)


def run_quiz_session(cookie: str, account_label: str = "", auto_claim: bool = False, gemini_key: str = None, groq_key: str = None, openrouter_key: str = None):
    prefix = f"[{account_label}] " if account_label else ""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1. 檢查紀錄與今日是否已兌換
    status, rec = send_quiz_request("GET", f"/quiz/record/{QUIZ_ACTIVITY_ID}.PROMO", cookie)
    today_str = datetime.now().strftime('%Y-%m-%d')
    has_claimed_today = False
    current_points = 0

    if status == 200:
        prize_records = rec.get("prizeRecords", [])
        for pr in prize_records:
            pr_date = pr.get("date") or pr.get("insertDate", "")
            if pr_date.startswith(today_str):
                has_claimed_today = True
                break
        point_records = rec.get("pointRecords", [])
        for p in point_records:
            p_date = p.get("date") or p.get("insertDate", "")
            if p_date.startswith(today_str):
                pts = p.get("earnedPoint") if p.get("earnedPoint") is not None else p.get("point", 0)
                current_points += pts

    display_points = current_points * 10
    print(f"[{now_str}] {prefix}今日累計積分: {display_points} 分 (後端 {current_points} 分)，今日已兌換: {has_claimed_today}")

    if has_claimed_today:
        print(f"{prefix}今日獎勵已兌換，略過本日答題。")
        return {
            "account_label": account_label,
            "correct_count": 0,
            "total_points": display_points,
            "status": "今日已兌換",
            "prize_claimed": None
        }

    # 2. 開始遊戲
    status, start_res = send_quiz_request("POST", f"/quiz/start/{QUIZ_ACTIVITY_ID}.PROMO", cookie)
    if status != 200:
        err_code = start_res.get("code", "")
        err_msg = start_res.get("detail", start_res.get("title", str(start_res)))
        if err_code == "ALREADY_STARTED":
            print(f"{prefix}本時段限玩 1 次，已經參加過囉！")
            return {"account_label": account_label, "correct_count": 0, "total_points": display_points, "status": "本時段已玩過", "prize_claimed": None}
        elif err_code in ("NOT_IN_PERIOD", "ACTIVITY_NOT_IN_PROGRESS"):
            print(f"{prefix}非開放時段或活動未開始: {err_msg}")
            return {"account_label": account_label, "correct_count": 0, "total_points": display_points, "status": "非開放時段", "prize_claimed": None}
        else:
            print(f"{prefix}開始遊戲失敗: {err_code} ({err_msg})")
            return {"account_label": account_label, "correct_count": 0, "total_points": display_points, "status": f"錯誤: {err_code}", "prize_claimed": None}

    print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix}🚀 成功進入知識王遊戲！限時 60 秒...")

    correct_count = 0
    start_time = time.time()
    round_reports_buffer = []

    # 3. 循環答題
    while time.time() - start_time < 58:
        status, q_data = send_quiz_request("GET", f"/quiz/question/{QUIZ_ACTIVITY_ID}.PROMO", cookie)
        if status != 200:
            print(f"{prefix}取題結束: {q_data.get('code')}")
            break

        question = q_data.get("question", {})
        choices = q_data.get("choices", [])
        q_text = question.get("text", "")
        q_img = question.get("image", "")
        q_uuid = question.get("uuid", "")
        db_key = get_question_key(question)

        if not choices:
            break

        # 只要取題成功，在 AI 思考前即刻線程安全持久化至題庫
        update_db_question(db_key, question, choices)
        db = load_quiz_db()

        q_start_t = time.time()
        selected_choice_id = select_answer(question, choices, db, gemini_key=gemini_key, groq_key=groq_key, openrouter_key=openrouter_key)
        selected_choice_obj = next((c for c in choices if c["uuid"] == selected_choice_id), choices[0])
        choice_text = selected_choice_obj.get("text", "") or selected_choice_obj.get("uuid", "")
        choice_obj = {
            "uuid": selected_choice_obj.get("uuid", ""),
            "text": selected_choice_obj.get("text", ""),
            "image": selected_choice_obj.get("image", "")
        }

        # 擬真極速抖動延遲 (移植自 Chrome 擴充 v13：基準 0.5s ± 0.2s 抖動 + 0.18~0.28s 確認延遲 ≈ 0.65~1.05s)
        q_elapsed = time.time() - q_start_t
        target_human_delay = max(0.48, 0.5 + random.uniform(-0.2, 0.2)) + random.uniform(0.18, 0.28)
        if q_elapsed < target_human_delay:
            time.sleep(target_human_delay - q_elapsed)

        img_log = f" [附圖: {q_img}]" if q_img else ""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix}第 {correct_count+1} 題: {q_text}{img_log} ➔ 選擇: {choice_text}")

        # 送出答案
        ans_body = {
            "activityId": QUIZ_ACTIVITY_ID,
            "questionId": q_uuid,
            "answerId": selected_choice_id
        }
        ans_status, ans_res = send_quiz_request("POST", "/quiz/answer.PROMO", cookie, ans_body)
        if ans_status != 200:
            print(f"{prefix}提交答案異常 ({ans_res.get('code', ans_status)})，題目已存入題庫供手動判定。")
            update_db_question(db_key, question, choices, unverified_choice=choice_obj)
            break

        is_correct = ans_res.get("isCorrect", False)

        if is_correct:
            correct_count += 1
            elapsed = time.time() - start_time
            print(f"🎉 {prefix}第 {correct_count} 題答對！(+10 分，已用時 {elapsed:.1f}s)")
            update_db_question(db_key, question, choices, correct=choice_obj)
            other_wrongs = [c for c in choices if c.get("uuid") != selected_choice_id]
            round_reports_buffer.append({
                "question": q_text,
                "questionImage": q_img,
                "answer": choice_obj["text"] or ("[圖片答案]" if choice_obj["image"] else ""),
                "answerImage": choice_obj["image"],
                "wrongOptions": [c.get("text", "").strip() for c in other_wrongs if c.get("text", "").strip()],
                "wrongImages": [c.get("image", "").strip() for c in other_wrongs if c.get("image", "").strip()],
                "allChoices": choices,
                "isCorrect": True,
                "submittedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "client": "momo-evolution-extension-v2"
            })
            if correct_count % 10 == 0:
                print(f"{prefix}🌟 累計已達 {correct_count} 題答對！繼續答題爭取更高分與新題庫記錄...")
            time.sleep(0.05)
        else:
            print(f"❌ {prefix}回答錯誤，本場時段結束。")
            update_db_question(db_key, question, choices, wrong_choice=choice_obj)
            round_reports_buffer.append({
                "question": q_text,
                "questionImage": q_img,
                "answer": "",
                "answerImage": "",
                "wrongOptions": [choice_obj["text"]] if choice_obj["text"] else [],
                "wrongImages": [choice_obj["image"]] if choice_obj["image"] else [],
                "allChoices": choices,
                "isCorrect": False,
                "submittedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "client": "momo-evolution-extension-v2"
            })
            break

    # 整局結束一次性批次上傳題庫學習紀錄
    if round_reports_buffer:
        threading.Thread(target=report_auto_learn_batch, args=(round_reports_buffer,), daemon=True).start()

    total_display_points = (current_points + correct_count) * 10
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix}🏁 答題結束！本場答對: {correct_count} 題，累計積分: {total_display_points} 分")

    # 4. 判斷兌換門檻 (達 50 mo 門檻 >= 600 分，或當日最後一場 >= 22 點且達基本兌換門檻 >= 300 分)
    prize_claimed = None
    can_claim_50mo = (total_display_points >= 600)
    now_hour = datetime.now().hour
    is_last_slot = (now_hour >= 22)
    should_claim = can_claim_50mo or (is_last_slot and total_display_points >= 300)

    if auto_claim and not has_claimed_today:
        if should_claim:
            target_prize = "50 mo點" if can_claim_50mo else "當前最高獎勵"
            print(f"{prefix}滿足兌換門檻 ({total_display_points}分，目標: {target_prize})，發動兌換獎勵...")
            claim_status, claim_res = send_quiz_request("POST", "/quiz/claim.PROMO", cookie, {"activityId": QUIZ_ACTIVITY_ID})
            if claim_status == 200:
                prize_name = claim_res.get("prize", {}).get("displayName", "獎項")
                prize_claimed = prize_name
                print(f"🎁 {prefix}兌換成功！獲得: {prize_name}")
            else:
                print(f"{prefix}兌換回應: {claim_res}")
    elif not auto_claim:
        if can_claim_50mo:
            print(f"{prefix}已達 50 mo 兌換門檻 ({total_display_points} 分)，因 auto_claim 未開啟未自動發動。")
        else:
            print(f"{prefix}已依設定關閉自動兌換，保留積分供手動兌換。")

    return {
        "account_label": account_label,
        "correct_count": correct_count,
        "total_points": total_display_points,
        "status": f"答對 {correct_count} 題",
        "prize_claimed": prize_claimed
    }


def get_current_slot_info(now: datetime = None):
    if now is None:
        now = datetime.now()

    best_slot = None
    min_future_diff = float("inf")

    for sh, sm in SLOTS:
        slot_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        diff = (slot_dt - now).total_seconds()
        # 開跑前 4 分鐘到開跑後 1 小時內鎖定
        if -3600 <= diff <= 240:
            best_slot = (sh, sm)
            break
        if diff > 0 and diff < min_future_diff:
            min_future_diff = diff
            best_slot = (sh, sm)

    if not best_slot:
        best_slot = SLOTS[0]

    slot_hour, slot_min = best_slot
    slot_time_str = f"{slot_hour:02d}:{slot_min:02d}"
    return slot_hour, slot_min, slot_time_str


def wait_until_slot_snipe(slot_hour: int, slot_minute: int, cookies: list, max_wait_seconds: int = 240):
    now = datetime.now()
    target_time = now.replace(hour=slot_hour, minute=slot_minute, second=0, microsecond=0)
    diff = (target_time - now).total_seconds()

    if diff <= 0 or diff > max_wait_seconds:
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 鎖定時段 {slot_hour:02d}:{slot_minute:02d}，距離開答剩 {diff:.1f} 秒，倒數中...")

    if diff > 3.5:
        time.sleep(diff - 3.5)

    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 剩餘 3.5 秒，預熱連線...")
    for c in cookies:
        prewarm_connection(c)

    rem = (target_time.timestamp() - 0.2) - time.time()
    if rem > 0:
        time.sleep(rem)

    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🚀 到達開搶點 (T-0.2s)，啟動答題流程！")


def run_session(cookies: list, slot_hour: int = None, slot_minute: int = None, silent_if_limit: bool = False, wait_snipe: bool = True, auto_claim: bool = False, gemini_key: str = None, groq_key: str = None, openrouter_key: str = None):
    if slot_hour is not None and slot_minute is not None:
        target_hour = slot_hour
        target_min = slot_minute
        slot_time_str = f"{target_hour:02d}:{target_min:02d}"
    else:
        target_hour, target_min, slot_time_str = get_current_slot_info()

    # 開跑前先同步雲端 CDN 最新題庫
    total_db = sync_cdn_bank()
    if total_db:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📚 已同步雲端最新題庫，當前共 {total_db} 題")

    if wait_snipe:
        wait_until_slot_snipe(target_hour, target_min, cookies)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 目標時段: {slot_time_str}，多帳號並行答題中...")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(cookies))) as executor:
        future_to_idx = {
            executor.submit(run_quiz_session, c, get_user_display_name(c, idx), auto_claim, gemini_key, groq_key, openrouter_key): idx
            for idx, c in enumerate(cookies, 1)
        }
        for fut in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                print(f"[帳號 {idx}] 執行異常: {e}")
                results.append({"account_label": f"帳號 {idx}", "status": f"異常: {e}"})

    # 推播彙整
    report_lines = []
    has_meaningful = False
    for r in results:
        label = r.get("account_label", "")
        status = r.get("status", "")
        cnt = r.get("correct_count", 0)
        session_pts = cnt * 10
        pts = r.get("total_points", 0)
        claimed = r.get("prize_claimed")
        line = f"👤 {label}：{status} (+{session_pts}分) | 今日累計: {pts}分"
        if claimed:
            line += f" ➔ 🎁 成功領取: {claimed}"
        report_lines.append(line)
        if "答對" in status or "異常" in status or claimed:
            has_meaningful = True

    if silent_if_limit and not has_meaningful:
        print("所有帳號均已兌換、非開放時段或已答題過，略過推播。")
        return

    try:
        from notifier import send_bark
        body = f"【雙11 momo知識王 ({slot_time_str}) 報告】\n\n" + "\n".join(report_lines)
        send_bark(f"momo 知識王結果 ({slot_time_str})", body.strip())
    except Exception as e:
        print(f"推播通知異常: {e}")


def main():
    parser = argparse.ArgumentParser(description="Momo 雙11知識王自動答題搶 mo 幣")
    parser.add_argument("--cookie", help="Cookie 字串")
    parser.add_argument("--gemini-key", help="Google Gemini API Key")
    parser.add_argument("--groq-key", help="Groq API Key (gsk_...)")
    parser.add_argument("--openrouter-key", help="OpenRouter API Key (sk-or-v1-...)")
    parser.add_argument("--now", action="store_true", help="立即執行搶答流程")
    parser.add_argument("--force", action="store_true", help="強制立即執行（無視時段窗口與開搶倒數）")
    parser.add_argument("--test-demo", action="store_true", help="執行示範題 AI 讀題測試")
    parser.add_argument("--query", action="store_true", help="查詢今日積分與兌換狀態")
    parser.add_argument("--silent-if-limit", action="store_true", help="略過重複推播")
    parser.add_argument("--auto-claim", dest="auto_claim", action="store_true", default=True, help="若滿足門檻是否自動發動兌獎 (預設開啟)")
    parser.add_argument("--no-auto-claim", dest="auto_claim", action="store_false", help="關閉自動兌換")
    args = parser.parse_args()

    gemini_keys = get_gemini_api_keys(args.gemini_key)
    gemini_key = gemini_keys[0] if gemini_keys else ""
    groq_key = get_groq_api_key(args.groq_key)
    openrouter_key = get_openrouter_api_key(args.openrouter_key)

    if args.test_demo:
        demo_img = "/Users/allen/.gemini/antigravity-ide/brain/3b9f5804-fd76-44a9-bd44-dbde2ae057ec/.tempmediaStorage/media_1792682302310.png"
        if not os.path.exists(demo_img):
            demo_img = "https://img1.momoshop.com.tw/ecm/img/online/10/007/04/648/images/game_start.gif?t=1792670445872"

        demo_questions = [
            {
                "title": "示範題 1（圖文題：書桌與電腦椅）",
                "text": "圖中商品屬於哪一個館別？",
                "image": demo_img,
                "choices": [
                    {"uuid": "choice_1", "text": "3C家電館"},
                    {"uuid": "choice_2", "text": "日用清潔館"},
                    {"uuid": "choice_3", "text": "流行時尚館"},
                    {"uuid": "choice_4", "text": "家具寢飾/居家生活館"}
                ]
            },
            {
                "title": "示範題 2（活動常識題：代言人）",
                "text": "下列何者是本次活動的主視覺代言人？",
                "image": None,
                "choices": [
                    {"uuid": "c1", "text": "SUPER JUNIOR-83z"},
                    {"uuid": "c2", "text": "五月天"},
                    {"uuid": "c3", "text": "告五人"},
                    {"uuid": "c4", "text": "蔡依林"}
                ]
            },
            {
                "title": "示範題 3（型 C 純圖片選項題：四選一找書桌）",
                "text": "下列哪一個商品是書桌？",
                "image": None,
                "choices": [
                    {"uuid": "img_c1", "text": "", "image": demo_img},
                    {"uuid": "img_c2", "text": "", "image": "https://picasso-frontend.momoshop.com.tw/mmp-activity/quiz-game/11544f47-d23d-4ebf-92ac-7281cfdbf952.png"}
                ]
            }
        ]

        for dq in demo_questions:
            print(f"\n=== 【{dq['title']}】 ===")
            print(f"題目：{dq['text']}")
            if dq['image']:
                print(f"附圖：{dq['image']}")
            print("選項：")
            for i, c in enumerate(dq['choices'], 1):
                print(f"  {i}. {c['text']}")

            ans_id = select_answer(dq, dq['choices'], {"questions": {}}, gemini_key=gemini_key, groq_key=groq_key, openrouter_key=openrouter_key)
            ans_obj = next((c for c in dq['choices'] if c['uuid'] == ans_id), None)
            if ans_obj:
                print(f"🎯 判定答案：{ans_obj['text']} (UUID: {ans_id})")
            else:
                print("❌ 未能成功解析答案。")
            time.sleep(1.0)
        return

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("錯誤: 未找到有效 Cookie。")
        sys.exit(1)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 成功載入 {len(cookies)} 個會員帳號憑證：")
    for i, c in enumerate(cookies, 1):
        print(f"  • {get_user_display_name(c, i)}")
    if groq_key:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ 已啟用 Groq 高速 AI 解題引擎 (每日 14,400 次免費額度)")
    if openrouter_key:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 👁️ 已啟用 OpenRouter 免費多模態視覺解題引擎 (Nemotron VL / Gemma 4)")
    if gemini_keys:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 已啟用 Google Gemini AI 解題引擎 (載入 {len(gemini_keys)} 組 Key)")

    if args.query:
        today_str = datetime.now().strftime('%Y-%m-%d')
        for i, c in enumerate(cookies, 1):
            name = get_user_display_name(c, i)
            status, rec = send_quiz_request("GET", f"/quiz/record/{QUIZ_ACTIVITY_ID}.PROMO", c)
            if status == 200:
                today_pts = 0
                for p in rec.get("pointRecords", []):
                    p_date = p.get("date") or p.get("insertDate", "")
                    if p_date.startswith(today_str):
                        today_pts += (p.get("earnedPoint") if p.get("earnedPoint") is not None else p.get("point", 0)) * 10
                print(f"【{name}】今日累計積分: {today_pts} 分 | 詳細紀錄: {rec}")
            else:
                print(f"【{name}】查詢失敗: {rec}")
    elif args.now:
        now = datetime.now()
        sh, sm, slot_str = get_current_slot_info(now)
        slot_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        diff = (slot_dt - now).total_seconds()
        if args.force or (-3600 <= diff <= 240):
            wait_snipe = (not args.force) and (0 < diff <= 240)
            run_session(cookies, slot_hour=sh, slot_minute=sm, silent_if_limit=args.silent_if_limit, wait_snipe=wait_snipe, auto_claim=args.auto_claim, gemini_key=gemini_key, groq_key=groq_key, openrouter_key=openrouter_key)
        else:
            print(f"[{now.strftime('%H:%M:%S')}] 目前非活動時段窗口（距離最近時段 {slot_str} 尚有 {diff/60:.1f} 分鐘），略過執行。")


if __name__ == "__main__":
    main()
