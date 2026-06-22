# 🤖 AI Gmail Invoice Tracker & Dashboard (סוכן AI לניהול חשבוניות ודשבורד)

מערכת מבוססת בינה מלאכותית המנטרת את תיבת ה-Gmail שלך, מזהה ומנתחת באופן אוטומטי חשבוניות וקבלות חודשיות באמצעות **Gemini 2.5 Flash** (SDK רשמי `google-genai`), שומרת את הנתונים ב-**Supabase** ומסנכרנת ל-**Google Sheets**, ומציגה אותם ב-**Dashboard** יוקרתי ומעוצב בטכנולוגיית Glassmorphism (רקעים חצי-שקופים, צבעי ניאון ואנימציות).

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
> חילוץ הנתונים מתבצע באמצעות **Gemini 2.5 Flash** דרך ה-SDK הרשמי `google-genai`
> (מותקן מ-`requirements.txt`). ודא שהגדרת מפתח API של Gemini בקובץ `backend/.env`:
> `GEMINI_API_KEY="your_api_key_here"`
> (מפתח חינמי ניתן לקבל כאן: https://aistudio.google.com/app/api-keys)

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

כדי שהסוכן יסרוק את תיבת ה-Gmail האמיתית שלך, המערכת משתמשת ב-**OAuth 2.0 Web Application flow**.
החיבור מתבצע כולו מהדפדפן (ללא קובץ `credentials.json` וללא חלון שנפתח מהשרת), והטוקנים נשמרים
**מוצפנים ב-Supabase** — לא על הדיסק. כך החיבור עובד גם בתוך קונטיינר / בענן.

### 1. יצירת OAuth Client (סוג Web application) ב-Google Cloud Console
1. היכנס אל [Google Cloud Console](https://console.cloud.google.com/) וצור/בחר פרויקט.
2. תחת **APIs & Services → Library**, הפעל את **Gmail API** ו-**Google Sheets API**.
3. הגדר **OAuth Consent Screen** (External/Internal) והוסף את האימייל שלך כ-Test User.
4. תחת **Credentials → Create Credentials → OAuth Client ID**, בחר בסוג **Web application**.
5. תחת **Authorized redirect URIs** הוסף את הכתובת המדויקת של ה-callback, למשל:
   `http://localhost:8000/api/auth/callback` (חייב להתאים בדיוק ל-`OAUTH_REDIRECT_URI`).
6. שמור את ה-**Client ID** וה-**Client Secret**.

### 2. הגדרת משתני סביבה (`backend/.env`)
ראה דוגמה מלאה ב-[`backend/.env.example`](backend/.env.example). הערכים הנדרשים לחיבור:
```
GOOGLE_CLIENT_ID=your_oauth_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_oauth_client_secret
OAUTH_REDIRECT_URI=http://localhost:8000/api/auth/callback
SESSION_SECRET=<python -c "import secrets;print(secrets.token_urlsafe(48))">
TOKEN_ENC_KEY=<python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
```
> [!IMPORTANT]
> `TOKEN_ENC_KEY` מצפין את טוקני ה-OAuth לפני שמירתם ב-Supabase. אם תאבד אותו —
> כל החשבונות המחוברים יצטרכו חיבור מחדש. שמור אותו כסוד (לא נכנס ל-git).

### 3. הרצת המיגרציה ב-Supabase
הרץ פעם אחת את [`backend/sql/gmail_accounts.sql`](backend/sql/gmail_accounts.sql)
ב-**Supabase → SQL Editor**. הוא יוצר את טבלת `gmail_accounts` (טוקנים מוצפנים) עם RLS.

### 4. חיבור חשבון Gmail וקישור גיליון
1. גש בדשבורד ללשונית **"הגדרות סוכן"**, כבה **מצב סימולציה**, הדבק את **Sheet ID** ושמור.
2. לחץ על **"חבר חשבון Gmail"** → תופנה לדף ההסכמה של גוגל → אשר את הגישה → תוחזר
   לדשבורד והחשבון יופיע כמחובר. הטוקן נשמר מוצפן ב-Supabase ומשמש לסנכרונים הבאים.
3. לחץ על **"סנכרן כעת"** כדי לסרוק את התיבה.

---

## 🐳 הרצה בקונטיינר (Docker)

```bash
# מ-root של הפרויקט (דורש backend/.env מאוכלס)
docker-compose up --build
# פתח http://localhost:8000
```
ה-`Dockerfile` הוא multi-stage ורץ כ-non-root. ראה [`k8s/README.md`](k8s/README.md) להרצה על Kubernetes (k3s / Rancher Desktop).

---

## 🛠️ ארכיטקטורת המערכת (Tech Stack)

* **Backend**: FastAPI (Python) - שירות API מהיר ויעיל המטפל בניהול הסנכרון, שמירת ההגדרות והזרמת הנתונים.
* **AI Agent**: Gemini 2.5 Flash דרך ה-SDK הרשמי `google-genai` - מעבד את תוכן המיילים, מסווג ומחלץ קבלות בעזרת Pydantic Structured Output.
* **Frontend**: HTML5 / Vanilla CSS3 / Modern JavaScript (ES6) - ממשק המעוצב בעיצוב **Glassmorphic Dark Mode** מרהיב, הכולל סינון, חיפוש, חלוקת עמודים (Pagination) וחלונות מודאל מפורטים.
* **Charts**: Chart.js - ספריה להצגת גרפים דינמיים מותאמים אישית (מגמות חודשיות ופילוח קטגוריות).
* **Database**: **Supabase (PostgreSQL)** — ענן ראשי לאחסון חשבוניות, עם גיבוי מקומי ב-`invoices.json`. Google Sheets נשמר כאפשרות סנכרון נוספת.
