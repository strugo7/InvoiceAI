# 🔐 דוח ביקורת אבטחה — InvoiceAI

**תאריך:** 2026-06-13
**ענף:** `dev`
**היקף:** שלוש בדיקות — סודות מקודדים (hardcoded), שימוש ב-`secrets` מול `random`, וחולשות בספריות צד-שלישי (Trivy).

---

## תקציר מנהלים

| # | בדיקה | תוצאה | פעולה |
|---|--------|--------|--------|
| 1 | סודות מקודדים בקוד | ✅ נקי | לא נדרשה (אזהרה אחת קלה — ראה למטה) |
| 2 | `secrets` מול `random` | ✅ תקין | לא נדרש שינוי (השימוש אינו רגיש-אבטחה) |
| 3 | חולשות בספריות (Trivy) | 🔴 5 חולשות → ✅ 0 | עודכן `requirements.txt` |

**שורה תחתונה:** הקוד עבר מ-5 חולשות ידועות (3×HIGH, 2×MEDIUM) ל-**0 חולשות**. אין סודות מקודדים בקוד. השימוש ב-`random` תקין בהקשרו.

---

## בדיקה 1 — סודות מקודדים (Hardcoded Secrets)

### מה עשיתי
1. סריקת `grep` בכל קבצי `.py`, `.js`, `.json`, `.html`, `.env*` אחר תבניות סוד (`api_key`, `secret`, `password`, `token`, `client_secret`, `private_key`, `bearer`).
2. סריקת תבניות מפתחות אמיתיים: `AIza…` (Google), `sk-…` (OpenAI), `ghp_…` (GitHub), `eyJ…` (JWT).
3. סריקת `trivy fs --scanners secret` על תיקיית `backend/`.
4. בדיקה אילו קבצים רגישים *נעקבים* על-ידי git (`git ls-files`, `git check-ignore`).

### ממצאים
- **אין שום מפתח/סוד מקודד בתוך קוד המקור.** כל הגישה לסודות נעשית נכון דרך משתני סביבה, למשל:
  - `backend/agent.py:608` → `genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))`
- כל הסודות האמיתיים יושבים בקבצים ייעודיים שמוחרגים ב-`.gitignore` ואינם נעקבים על-ידי git:
  - `backend/.env` (מכיל `GEMINI_API_KEY`, `SUPABASE_SERVICE_KEY`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`, `TOKEN_ENC_KEY`) — **IGNORED** ✅
  - `backend/credentials.json` (OAuth client) — **IGNORED** ✅
  - `backend/token_*.json` (טוקני OAuth לכל חשבון) — **IGNORED** ✅
- `trivy` סרק את `.env` ולא זיהה דליפת סוד בפורמט מוכר (0 secrets).

### ⚠️ אזהרה קלה אחת (אינפורמטיבית)
הקובץ `backend/config.json` **כן נעקב על-ידי git** ומכיל את `sheet_id`:
```json
{ "use_mock": false, "sheet_id": "1xpu5s8rBWAk__dOLeFPZl28LSZSzrNuxPEBOhBAZXEM" }
```
זהו מזהה Google Sheet ולא סוד קריפטוגרפי, ולכן אין סיכון חמור. עם זאת זהו מזהה משאב ספציפי לסביבה — מומלץ לשקול להעבירו ל-`.env` / משתנה סביבה כדי לא לכבול את הקוד למסמך מסוים. **לא שיניתי זאת ללא אישורך** כי זה עלול לשבור התנהגות קיימת.

---

## בדיקה 2 — שימוש ב-`secrets` במקום `random`

### מה עשיתי
1. `grep` לכל שימושי `random` ו-`secrets` בקוד.
2. בדיקת ההקשר של כל שימוש כדי לקבוע אם הוא **רגיש-אבטחה** (יצירת טוקנים, סיסמאות, מזהי סשן, מלחי הצפנה) או לא.
3. חיפוש שגרות יצירת-מפתחות אחרות: `token_hex`, `token_urlsafe`, `uuid4`, `os.urandom`, `Fernet`.

### ממצאים
השימוש היחיד ב-`random` נמצא ב-[backend/agent.py:94-121](backend/agent.py#L94-L121), והוא משמש **אך ורק ליצירת נתוני דמה (mock invoices)**:
```python
import random
random.seed(42 + month_offset)  # דטרמיניסטי אך מגוון
selected_services = random.sample(monthly_services, k=random.randint(6, 9))
amount = round(random.uniform(...), 2)
```

### מסקנה — אין צורך בשינוי
- הקשר זה **אינו רגיש-אבטחה**: מדובר בנתוני הדגמה בלבד.
- השימוש כאן **מכוון להיות דטרמיניסטי** (`random.seed(42)`) כדי לייצר נתונים יציבים וניתנים לשחזור.
- ספריית `secrets` נועדה ל-CSPRNG (טוקנים/סיסמאות) ו**אינה תומכת ב-seeding** — החלפה כאן הייתה *פוגעת* בדטרמיניזם הנדרש ושגויה הנדסית.
- חשוב: לא נמצאה שום יצירה של טוקן/סוד/סשן באמצעות `random` בהקשר אבטחתי. (`SESSION_SECRET` ו-`TOKEN_ENC_KEY` קיימים ב-`.env` אך עדיין אינם מחווטים בקוד — אם/כאשר ייווצרו בתוכנית, יש להשתמש ב-`secrets.token_urlsafe()` / `secrets.token_hex()`.)

> **המלצה לעתיד:** אם תוסיף בעתיד יצירת טוקני סשן, מלחים, או קודי אימות — חובה להשתמש ב-`secrets`, לא ב-`random`.

---

## בדיקה 3 — חולשות בספריות צד-שלישי (Trivy)

### מה עשיתי
1. `trivy fs --scanners vuln backend/requirements.txt` בכל רמות החומרה.
2. בדיקת גרסאות התיקון מול PyPI.
3. אימות תאימות מול FastAPI 0.110 לפני העדכון.
4. סריקה חוזרת לאימות.

### ממצאים — 5 חולשות לפני התיקון

| ספרייה | CVE | חומרה | גרסה מותקנת | תוקן ב |
|--------|-----|--------|--------------|--------|
| `python-multipart` | CVE-2024-53981 | HIGH | 0.0.9 | 0.0.18 |
| `python-multipart` | CVE-2026-24486 | HIGH | 0.0.9 | 0.0.22 |
| `python-multipart` | CVE-2026-42561 | HIGH | 0.0.9 | 0.0.27 |
| `python-multipart` | CVE-2026-40347 | MEDIUM | 0.0.9 | 0.0.26 |
| `python-dotenv` | CVE-2026-28684 | MEDIUM | 1.0.1 | 1.2.2 |

**תיאורי החולשות:**
- `python-multipart` — DoS דרך גבול `multipart/form-data` מעוות, כתיבת קבצים שרירותית דרך path traversal, ו-DoS נוסף מבקשות מעוצבות. רלוונטי ישירות כי FastAPI משתמש בו לפענוח טפסים/העלאות.
- `python-dotenv` — דריסת קובץ שרירותית דרך מעקב אחר symbolic link.

### התיקון
עודכן [backend/requirements.txt](backend/requirements.txt):
```diff
- python-multipart==0.0.9
- python-dotenv==1.0.1
+ python-multipart==0.0.32   # מכסה את כל 4 ה-CVEs (סף 0.0.27)
+ python-dotenv==1.2.2       # מתקן CVE-2026-28684
```
- בחרתי ב-`python-multipart==0.0.32` (האחרונה ב-PyPI) — מעל סף התיקון הגבוה ביותר (0.0.27).
- בחרתי ב-`python-dotenv==1.2.2` (האחרונה = גרסת התיקון).

### אימות
1. **תאימות:** FastAPI 0.110.0 דורש `python-multipart>=0.0.7` — הגרסה 0.0.32 עומדת בכך. אין מגבלה על `python-dotenv`. ✅
2. **סריקה חוזרת** לאחר העדכון:
```
┌──────────────────┬──────┬─────────────────┐
│ requirements.txt │ pip  │        0        │   ← 0 חולשות
└──────────────────┴──────┴─────────────────┘
```

> **שלב הבא בסביבת ההרצה:** יש להתקין מחדש את התלויות כדי שהתיקון ייכנס לתוקף בפועל:
> ```bash
> cd backend && .venv/bin/python -m pip install -r requirements.txt
> ```
> (העדכון בקובץ מבטיח תיקון מכאן והלאה; הסביבה הקיימת עדיין מריצה את הגרסאות הישנות עד התקנה מחדש.)

---

## סיכום פעולות שבוצעו

1. ✅ סרקתי את כל בסיס הקוד אחר סודות מקודדים — **נקי**; הסודות מנוהלים נכון דרך env ומוחרגים מ-git.
2. ✅ אימתתי שאין שימוש לא-בטוח ב-`random` בהקשר אבטחתי — השימוש היחיד הוא נתוני דמה דטרמיניסטיים, ולכן `random` הוא הבחירה הנכונה.
3. ✅ תיקנתי את כל 5 החולשות שזוהו על-ידי Trivy ע"י עדכון `requirements.txt`, ואימתתי בסריקה חוזרת שהתוצאה היא 0 חולשות.

---

## פעולות המשך שבוצעו (לאחר אישור)

### א. תיקוף — התקנת התלויות המעודכנות בפועל
- ה-venv לא הכיל `pip` כלל → בוצע bootstrap דרך `python -m ensurepip`.
- הורצה `pip install -r requirements.txt`:
  - `python-multipart` **0.0.9 → 0.0.32** (הוסרה הגרסה הפגיעה).
  - `python-dotenv` **1.0.1 → 1.2.2** (הוסרה הגרסה הפגיעה).
- אימות: `pip show` מאשר את הגרסאות החדשות; Trivy על הסביבה = **0 חולשות**.

### ב. העברת `sheet_id` מ-`config.json` ל-`.env`
כדי שמזהה ה-Google Sheet לא יישב יותר בקובץ הנעקב ב-git:
1. נוסף `SHEET_ID=…` ל-[backend/.env](backend/.env) (מוחרג ב-git) ו-placeholder ל-[backend/.env.example](backend/.env.example).
2. הוסר `sheet_id` מ-[backend/config.json](backend/config.json) (נשאר רק `use_mock`).
3. עודכן [backend/server.py](backend/server.py):
   - `load_config()` קורא את `sheet_id` מ-`os.environ["SHEET_ID"]`.
   - `save_config()` שומר רק `use_mock` לקובץ הנעקב.
   - `update_settings()` (POST /api/settings) כותב עדכוני `sheet_id` חזרה ל-`.env` דרך `dotenv.set_key` — כך שמסך ההגדרות נשאר פעיל לחלוטין, אך הערך לעולם לא נכנס ל-git.
4. **אימות:** טסט אוטומטי וידא ש-(א) הערך נטען מ-env, (ב) שמירה מה-UI נכתבת ל-`.env` ולא ל-`config.json`. `git grep` מאשר שמזהה ה-Sheet אינו קיים יותר באף קובץ נעקב. ✅

## המלצות לעתיד
- בכל יצירת טוקן/סוד/מלח — השתמש ב-`secrets` (`secrets.token_urlsafe()`), לעולם לא ב-`random`.
- מומלץ לבצע **rotation** למפתחות שהיו בקובץ `.env` אם הוא אי-פעם נחשף, ולהריץ סריקת Trivy תקופתית (למשל ב-CI).
