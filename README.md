# 🤖 AI Gmail Invoice Tracker & Dashboard (סוכן AI לניהול חשבוניות ודשבורד)

מערכת מבוססת בינה מלאכותית המנטרת את תיבת ה-Gmail שלך, מזהה ומנתחת באופן אוטומטי חשבוניות וקבלות חודשיות באמצעות סוכן **Google Antigravity SDK & Gemini**, שומרת את כל הנתונים ב-**Google Sheets**, ומציגה אותם ב-**Dashboard** יוקרתי ומעוצב בטכנולוגיית Glassmorphism (רקעים חצי-שקופים, צבעי ניאון ואנימציות).

המערכת מגיעה עם **מצב סימולציה (Mock Mode) מובנה** שעובד מיידית ללא הגדרות נוספות כדי שתוכל לראות את כל הזרימה, הגרפים והטבלאות מיד בתום ההפעלה!

---

## 🚀 הוראות הפעלה מהירה (Quick Start)

### 1. התקנת תלויות (Prerequisites & Installation)
ודא שמותקן אצלך Python 3.9 ומעלה במחשב.

נווט אל תיקיית הפרויקט והתקן את התלויות הנדרשות בתיקיית ה-`backend`:
```bash
cd backend
pip install -r requirements.txt
```

> [!NOTE]
> אם חבילת ה-`google-antigravity` אינה מותקנת עדיין, התקן אותה בעזרת:
> `pip install google-antigravity`
> בנוסף, ודא שהגדרת את מפתח ה-API של Gemini במשתנה הסביבה שלך:
> `export GEMINI_API_KEY="your_api_key_here"`
> (אם אין לך מפתח עדיין, תוכל לקבל מפתח בחינם כאן: https://aistudio.google.com/app/api-keys)

### 2. הרצת השרת (Run the Server)
הרצים את שרת ה-FastAPI בתיקיית `backend`:
```bash
python server.py
```
או באמצעות uvicorn ישירות:
```bash
uvicorn server:app --reload --port 8000
```

### 3. כניסה לדשבורד
פתח את הדפדפן וכנס לכתובת:
👉 **[http://localhost:8000](http://localhost:8000)**

לחץ על כפתור **"סנכרן כעת"** (Sync Now) כדי לראות את סוכן ה-AI סורק את התיבה ומייצר את הגרפים הפיננסיים המרהיבים בזמן אמת!

---

## 🗄️ הגדרת Supabase (Database Setup)

המערכת משתמשת ב-Supabase כמסד נתונים ענן ראשי. הנתונים נשמרים בטבלת `invoices` ב-PostgreSQL.

### 1. הוספת מפתחות Supabase ל-`.env`
```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service_role key from Supabase dashboard>
```
ניתן למצוא את המפתחות תחת: **Supabase Dashboard → Settings → API**.

> [!NOTE]
> השתמש במפתח `service_role` (לא `anon`) — השרת פועל בצד-שרת בלבד ולא חשוף לדפדפן.

### 2. פרויקט Supabase
פרויקט הפרודקשן: `gmail-invoice-tracker` — אזור `eu-central-1` (פרנקפורט).

---

## ⚙️ מעבר למצב אמת (Production Mode)

כדי שהסוכן יסרוק את תיבת ה-Gmail האמיתית שלך ויכתוב לגליון Google Sheets שלך, עקוב אחר הצעדים הבאים:

### 1. קבלת אישורי גישה מ-Google Cloud Console
1. היכנס אל [Google Cloud Console](https://console.cloud.google.com/).
2. צור פרויקט חדש (למשל: `Gmail Invoice Agent`).
3. תחת **API & Services** -> **Library**, חפש והפעל את:
   * **Gmail API**
   * **Google Sheets API**
4. הגדר את **OAuth Consent Screen** כמצב **External** או **Internal** והוסף את האימייל שלך כמשתמש בדיקה (Test User).
5. גש ללשונית **Credentials**, לחץ על **Create Credentials** ובחר ב-**OAuth Client ID**.
6. בחר בסוג יישום **Desktop App**, תן שם (לדוגמה `Invoice Tracker`) ולחץ על Create.
7. הורד את קובץ ה-JSON שנוצר, שנה את שמו ל-`credentials.json` והנח אותו בתיקיית **`backend/`**.

### 2. יצירת גליון Google Sheet וקישורו
1. פתח את [Google Sheets](https://sheets.google.com) וצור גיליון חדש.
2. העתק את ה-Spreadsheet ID מתוך כתובת ה-URL של הגיליון (זו מחרוזת ארוכה של תווים שנמצאת בין `/d/` לבין `/edit` בכתובת).
3. פתח את הדשבורד בדפדפן, גש ללשונית **"הגדרות סוכן"**:
   * כבה את **מצב סימולציה**.
   * הדבק את מזהה הגיליון (Sheet ID) שהעתקת.
   * לחץ על **שמור הגדרות**.

### 3. הרצה ואישור הרשאה ראשונית
לחץ על כפתור **"סנכרן כעת"** בדשבורד.
* ייפתח חלון בדפדפן המבקש ממך להתחבר לחשבון ה-Google שלך ולאשר לסוכן לקרוא מיילים ולכתוב לגיליון (Gmail Readonly ו-Sheets).
* אשר את הגישה.
* נוצר קובץ `token.json` בתיקיית `backend` המאפשר סנכרון אוטומטי בעתיד ללא צורך בהתחברות חוזרת!

---

## 🛠️ ארכיטקטורת המערכת (Tech Stack)

* **Backend**: FastAPI (Python) - שירות API מהיר ויעיל המטפל בניהול הסנכרון, שמירת ההגדרות והזרמת הנתונים.
* **AI Agent**: Google Antigravity SDK ומודל Gemini - סוכן בינה מלאכותית חכם המעבד את התוכן של המיילים, מסווג ומחלץ קבלות בעזרת Pydantic Structured Output.
* **Frontend**: HTML5 / Vanilla CSS3 / Modern JavaScript (ES6) - ממשק המעוצב בעיצוב **Glassmorphic Dark Mode** מרהיב, הכולל סינון, חיפוש, חלוקת עמודים (Pagination) וחלונות מודאל מפורטים.
* **Charts**: Chart.js - ספריה להצגת גרפים דינמיים מותאמים אישית (מגמות חודשיות ופילוח קטגוריות).
* **Database**: **Supabase (PostgreSQL)** — ענן ראשי לאחסון חשבוניות, עם גיבוי מקומי ב-`invoices.json`. Google Sheets נשמר כאפשרות סנכרון נוספת.
