<div align="center">

# 🤖 MEXC Portfolio Rebalancer Bot

**بوت تيليجرام لإعادة توازن المحفظة على منصة MEXC**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?style=flat-square&logo=railway&logoColor=white)](https://railway.app)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## ✨ الميزات

| الميزة | التفاصيل |
|--------|----------|
| 🪙 **عملات متعددة** | حتى 20 عملة لكل محفظة |
| ⚖️ **طرق توزيع** | متساوٍ · حسب حجم السوق · يدوي |
| 🎯 **حد انحراف عام** | يُطبَّق تلقائياً على جميع العملات |
| ⚡ **توازن فوري** | تنفيذ يدوي بضغطة زر |
| 🔄 **توازن تلقائي** | جدولة زمنية مرنة (1 — 720 ساعة) |
| 🗂 **محافظ متعددة** | رأس مال وتوزيع مستقل لكل محفظة |
| 📋 **سجل كامل** | تتبع جميع عمليات التوازن |

---

## ⚙️ متغيرات البيئة

| المتغير | الوصف | مثال |
|---------|-------|------|
| `TELEGRAM_BOT_TOKEN` | توكن البوت من BotFather | `123456:ABC...` |
| `ALLOWED_USER_IDS` | معرف تيليجرام الخاص بك | `123456789` |
| `DATABASE_URL` | رابط PostgreSQL (للحفظ الدائم) | يُضاف تلقائياً من Railway |

---

## 🗄️ قاعدة البيانات الدائمة (PostgreSQL)

البوت يستخدم SQLite افتراضياً، لكن البيانات **تُحذف عند كل إعادة تشغيل** على Railway.
لحفظ البيانات بشكل دائم:

1. في لوحة Railway، افتح مشروعك
2. اضغط **+ New** → **Database** → **Add PostgreSQL**
3. اذهب إلى **Variables** في خدمة البوت
4. أضف `DATABASE_URL` بقيمة `DATABASE_URL` من خدمة PostgreSQL

---

## 📌 طريقة إضافة العملات

**بالرموز فقط — ثم اختر طريقة التوزيع:**
```
BTC ETH SOL USDT BNB
```

**بالنسب مباشرة:**
```
BTC=40
ETH=30
SOL=20
USDT=10
```

---

## 🚀 النشر على Railway

```bash
# 1. Fork المستودع
# 2. أنشئ مشروعاً جديداً على Railway
# 3. اربطه بالمستودع
# 4. أضف متغيرات البيئة
# 5. أضف PostgreSQL (اختياري)
```

---

<div align="center">
  <sub>Built with ❤️ using python-telegram-bot · ccxt · Railway</sub>
</div>
