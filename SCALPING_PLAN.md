# Smart Liquidity Flow Bot — خطة البناء الكاملة

## ملخص الاستراتيجية

بوت Scalping احترافي مدمج جوه البوت الحالي (MEXC Rebalancer).
يعمل بجانب الـ Rebalancing بدون تعارض.

### اسم الاستراتيجية: Smart Liquidity Flow

الفكرة: البوت يصطاد نقاط الدخول اللي الحيتان بتستخدمها —
يحدد مناطق Liquidity من الإطار الكبير (4H)،
ويتأكد من الاتجاه والـ Sweep على الإطارات الأصغر (1H, 30M, 15M)،
وبعدين ينفذ الصفقة تلقائياً على MEXC.

---

## شروط الدخول — لازم الـ 4 يتحققوا معاً

```
1. 4H  — السعر قرب منطقة Liquidity (أعلى أو أدنى نقطة آخر 20 كاندل)
2. 1H  — CVD صاعد (ضغط شراء أكبر من ضغط بيع)
3. 30M — حصل Liquidity Sweep (السعر كسر القاع وراجع فوقيه)
4. 15M — كاندل Engulfing بعد الـ Sweep (تأكيد الرجوع)
```

---

## إدارة الصفقة

```
حجم الدخول : $10 لكل صفقة
هدف 1      : +0.5%  — بيع 50% من الصفقة (تأمين ربح)
هدف 2      : أعلى نقطة 4H — بيع الـ 50% الباقية
وقف الخسارة: 0.3% تحت أدنى نقطة الـ Sweep
R/R        : 1:2 أو أكتر
```

---

## فلاتر تمنع الدخول الغلط

```
- Volume 24h أقل من $1,000,000     → تجاهل العملة
- Spread أكبر من 0.1%              → تجاهل العملة
- CVD سالب على 1H                  → لا دخول
- ما فيش Engulfing على 15M         → لا دخول
- في صفقة مفتوحة على نفس العملة   → لا دخول جديد
```

---

## العملات

- Top 100 على MEXC
- مفلترة بـ Volume و Spread تلقائياً
- البوت يفحصهم كلهم كل 15 دقيقة

---

## البنية التقنية

```
mexc-rebalancer-bot/
├── bot/
│   ├── scalping/                  ← مجلد جديد
│   │   ├── __init__.py
│   │   ├── liquidity.py           ← رصد مناطق Liquidity من 4H
│   │   ├── cvd.py                 ← حساب CVD من بيانات الـ trades
│   │   ├── sweep.py               ← كشف Liquidity Sweep على 30M
│   │   ├── entry.py               ← تأكيد الدخول على 15M (Engulfing)
│   │   ├── risk.py                ← حساب حجم الصفقة والوقف والهدف
│   │   ├── executor.py            ← تنفيذ الصفقة على MEXC
│   │   ├── monitor.py             ← مراقبة الصفقات المفتوحة
│   │   └── scanner.py             ← فحص Top 100 كل 15 دقيقة
│   ├── handlers/
│   │   └── scalping_handler.py    ← handler للتيليجرام
│   └── keyboards.py               ← إضافة زر Scalping للقائمة
├── main.py                        ← إضافة الـ handlers الجديدة
└── requirements.txt               ← إضافة pandas_ta
```

---

## تفاصيل كل ملف

### liquidity.py
```python
# المدخلات : symbol, exchange client
# المخرجات : {"high": float, "low": float, "near_zone": bool, "side": "buy"|"sell"}
# المنطق   : جلب آخر 20 كاندل 4H، تحديد أعلى وأدنى نقطة
#            لو السعر الحالي في نطاق 0.5% من القاع → near_zone=True, side="buy"
#            لو السعر الحالي في نطاق 0.5% من السقف → near_zone=True, side="sell"
```

### cvd.py
```python
# المدخلات : symbol, exchange client
# المخرجات : {"cvd": float, "trend": "up"|"down"|"neutral"}
# المنطق   : جلب آخر 100 trade على 1H
#            CVD = مجموع (buy volume) - مجموع (sell volume)
#            لو CVD موجب → trend="up"
```

### sweep.py
```python
# المدخلات : symbol, exchange client, liquidity_low
# المخرجات : {"swept": bool, "sweep_low": float, "recovered": bool}
# المنطق   : جلب آخر 10 كاندل 30M
#            لو كاندل كسر liquidity_low وأغلق فوقيه → swept=True, recovered=True
```

### entry.py
```python
# المدخلات : symbol, exchange client
# المخرجات : {"confirmed": bool, "entry_price": float}
# المنطق   : جلب آخر 3 كاندل 15M
#            لو الكاندل الأخير Bullish Engulfing → confirmed=True
```

### risk.py
```python
# المدخلات : entry_price, sweep_low, trade_size_usdt=10
# المخرجات : {"stop_loss": float, "target1": float, "target2": float, "qty": float}
# المنطق   :
#   stop_loss = sweep_low * 0.997  (0.3% تحت الـ Sweep)
#   target1   = entry_price * 1.005 (+0.5%)
#   target2   = liquidity_high      (أعلى نقطة 4H)
#   qty       = trade_size_usdt / entry_price
```

### executor.py
```python
# المدخلات : symbol, side, qty, stop_loss, target1, target2, exchange client
# المخرجات : {"order_id": str, "status": "ok"|"error", "reason": str}
# المنطق   :
#   1. market buy order بالـ qty
#   2. limit sell order عند target1 بـ 50% من الـ qty
#   3. limit sell order عند target2 بالـ 50% الباقية
#   4. stop loss order عند stop_loss بكل الـ qty
```

### monitor.py
```python
# المدخلات : قائمة الصفقات المفتوحة, exchange client
# المخرجات : تحديث حالة كل صفقة
# المنطق   :
#   كل دقيقة يفحص الصفقات المفتوحة
#   لو target1 اتحقق → يلغي الـ stop loss القديم ويحطه عند الدخول (breakeven)
#   لو target2 اتحقق → يغلق الصفقة ويبعت إشارة نجاح
#   لو stop_loss اتحقق → يبعت إشارة خسارة
```

### scanner.py
```python
# المنطق الكامل للفحص كل 15 دقيقة:
#
# 1. جلب Top 100 عملة من MEXC
# 2. فلترة بـ Volume > $1M و Spread < 0.1%
# 3. لكل عملة:
#    a. liquidity.py  → near_zone?
#    b. لو نعم: cvd.py → trend up?
#    c. لو نعم: sweep.py → swept and recovered?
#    d. لو نعم: entry.py → engulfing confirmed?
#    e. لو نعم: risk.py → حساب الأرقام
#    f. executor.py → تنفيذ + إشارة تيليجرام
```

---

## شكل إشارة التيليجرام

```
🎯 Smart Liquidity Flow

📌 BTC/USDT
⏱ التقاطع: 4H + 1H + 30M + 15M

🟢 دخول  : $94,250
🎯 هدف 1 : $94,720  (+0.5%)
🎯 هدف 2 : $95,400  (+1.2%)
🛑 وقف   : $93,970  (-0.3%)
📊 R/R   : 1:2.4

💧 Liquidity Sweep ✅
📈 CVD صاعد ✅
🕯 Engulfing 15M ✅
```

---

## التعديلات على الملفات الموجودة

### keyboards.py — إضافة زر للقائمة الرئيسية
```python
# في main_menu_kb() أضف:
[InlineKeyboardButton("⚡ Scalping Bot", callback_data="scalping:menu")]
```

### main.py — إضافة الـ handlers
```python
from bot.handlers.scalping_handler import (
    scalping_menu_callback,
    scalping_toggle_callback,
    scalping_status_callback,
)
# وإضافة الـ scheduler للـ scanner كل 15 دقيقة
```

### requirements.txt — إضافة
```
pandas_ta>=0.3.14b
```

---

## ترتيب البناء (4 مراحل)

```
المرحلة 1: البنية + جلب البيانات
  - إنشاء مجلد bot/scalping/
  - liquidity.py
  - cvd.py
  - اختبار الاتصال بـ MEXC وجلب البيانات

المرحلة 2: منطق الاستراتيجية
  - sweep.py
  - entry.py
  - risk.py
  - scanner.py (بدون تنفيذ — فقط إشارات)

المرحلة 3: التنفيذ
  - executor.py
  - monitor.py
  - ربط الـ scanner بالـ executor

المرحلة 4: التيليجرام
  - scalping_handler.py
  - تعديل keyboards.py
  - تعديل main.py
  - اختبار كامل
```

---

## الـ Prompt الجاهز لأي AI

انسخ ده وحطه في أي AI (ChatGPT / Claude / Gemini):

```
أنا عندي بوت Python اسمه mexc-rebalancer-bot.
عايز أضيف feature جديدة اسمها Smart Liquidity Flow.

الاستراتيجية:
- Top 100 عملة على MEXC
- Multi-timeframe: 4H (Liquidity Zones) + 1H (CVD) + 30M (Sweep) + 15M (Entry)
- شروط الدخول: السعر قرب Liquidity Zone + CVD صاعد + Liquidity Sweep + Engulfing
- حجم الصفقة: $10
- هدف 1: +0.5% (بيع 50%)
- هدف 2: أعلى نقطة 4H (بيع 50%)
- وقف الخسارة: 0.3% تحت الـ Sweep
- فلاتر: Volume > $1M, Spread < 0.1%

البنية المطلوبة:
bot/scalping/liquidity.py
bot/scalping/cvd.py
bot/scalping/sweep.py
bot/scalping/entry.py
bot/scalping/risk.py
bot/scalping/executor.py
bot/scalping/monitor.py
bot/scalping/scanner.py
bot/handlers/scalping_handler.py

المكتبات المستخدمة: ccxt, pandas_ta, python-telegram-bot v20
Exchange: MEXC

ابدأ بـ [اسم المرحلة] وأعطني الكود الكامل.
```

---

## ملاحظات مهمة

1. **CVD على MEXC** — مش متاح مباشرة، هنحسبه من بيانات الـ recent trades
2. **Top 100 فلترة** — لازم تتعمل كل مرة عشان العملات بتتغير
3. **صفقة واحدة لكل عملة** — البوت مش بيفتح صفقتين على نفس العملة
4. **الـ monitor** — بيشتغل كل دقيقة بالتوازي مع الـ scanner
5. **لو MEXC ما دعمتش OCO orders** — هنعمل الـ stop loss و targets يدوياً في الـ monitor

---

*الملف ده كافي تكمل منه مع أي AI في أي وقت.*
