// ==UserScript==
// @name         Momo 助手 (Cookie 快速提取 & 自動抽獎 & mo幣到期提醒)
// @namespace    http://tampermonkey.net/
// @version      1.2
// @description  在 momo 購物網提供一鍵提取 Cookie、定時抽獎與 mo 幣即將到期提醒
// @author       Antigravity
// @match        https://www.momoshop.com.tw/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    // 1. 浮動按鈕：一鍵快速提取 Cookie
    function addCookieExtractorBtn() {
        if (document.getElementById('momo_cookie_btn')) return;

        const btn = document.createElement('div');
        btn.id = 'momo_cookie_btn';
        btn.innerHTML = '📋 複製 Cookie';
        btn.title = '點擊一鍵複製當前 momo 帳號 Cookie 到剪貼簿';
        btn.style.cssText = `
            position: fixed;
            bottom: 75px;
            right: 20px;
            z-index: 999999;
            background: linear-gradient(135deg, #e11d48, #be123c);
            color: #fff;
            padding: 8px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: bold;
            box-shadow: 0 4px 12px rgba(225, 29, 72, 0.4);
            cursor: pointer;
            user-select: none;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 5px;
        `;

        btn.onmouseover = () => { btn.style.transform = 'translateY(-2px) scale(1.05)'; };
        btn.onmouseout = () => { btn.style.transform = 'translateY(0) scale(1)'; };

        btn.onclick = () => {
            const c = document.cookie;
            if (!c || (c.indexOf('LOGINSESSION') === -1 && c.indexOf('st=') === -1)) {
                showToast('⚠️ 未偵測到會員登入狀態，請先登入！', '#e11d48');
                return;
            }

            const m = c.match(/loginUser=([^;]+)/);
            const user = m ? decodeURIComponent(m[1].replace(/\+/g, ' ')).trim() : '會員';

            navigator.clipboard.writeText(c).then(() => {
                showToast(`✅ 已複製 Cookie (${user})！長度: ${c.length}`, '#059669');
            }).catch(() => {
                prompt('請手動複製以下 Cookie：', c);
            });
        };

        document.body.appendChild(btn);
    }

    // 2. 檢查今日是否有即將到期之 mo 幣 / mo 點
    function checkExpiringCoins() {
        const todayStr = new Date().toISOString().slice(0, 10).replace(/-/g, '/');
        const lastChecked = localStorage.getItem('momo_coin_last_checked');
        if (lastChecked === todayStr) {
            return;
        }

        const payload = { flag: 3156, data: { currencyType: "1" } };
        fetch('/servlet/MemberCenterServ', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: 'data=' + encodeURIComponent(JSON.stringify(payload))
        })
        .then(res => res.json())
        .then(data => {
            if (data && data.expirationAmount) {
                const expAmount = parseFloat(String(data.expirationAmount).replace(/,/g, '')) || 0;
                const expDate = data.expirationDate || '';
                if (expAmount > 0 && expDate.includes(todayStr)) {
                    showToast(`⚠️ 提醒：您有 ${data.expirationAmount} 元 momo 幣將於今日到期！`, '#d97706', 10000);
                }
            }
            localStorage.setItem('momo_coin_last_checked', todayStr);
        })
        .catch(() => {});
    }

    function showToast(msg, bg = '#e6007e', duration = 4000) {
        const toast = document.createElement('div');
        toast.innerText = msg;
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 1000000;
            padding: 12px 18px;
            background: ${bg};
            color: #fff;
            border-radius: 8px;
            font-size: 14px;
            font-weight: bold;
            box-shadow: 0 4px 14px rgba(0,0,0,0.3);
            animation: fadeIn 0.3s ease;
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), duration);
    }

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', () => {
            addCookieExtractorBtn();
            checkExpiringCoins();
        });
    } else {
        addCookieExtractorBtn();
        checkExpiringCoins();
    }
})();
