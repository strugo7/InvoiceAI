# InvoiceAI — ארכיטקטורה במסגרת BDAT

מ‑POC מקומי למערכת ענן מאובטחת — **B**usiness · **D**ata · **A**pplication · **T**echnology.
מצב נוכחי לאחר סבב קונטיינריזציה, מעבר OAuth ל‑Web flow, והקשחת אבטחה ובקרת API.

---

## מסגרת BDAT — איך קוראים את המערכת

- **B — Business** — הערך, התהליך העסקי וה‑KPI.
- **D — Data** — ישויות, אחסון, אבטחת מידע ואיכות נתונים.
- **A — Application** — רכיבים, שירותים וממשקים.
- **T — Technology** — סביבת ריצה, תשתית ופריסה.

כל שכבה נשענת על זו שמתחתיה: הטכנולוגיה משרתת את האפליקציה, שמנהלת את הנתונים, שמגשימים את הצורך העסקי.

---

## B — Business Architecture

- **הבעיה:** מנויי SaaS/AI מתרבים ומפוזרים בתיבות מייל → אין ראות מרוכזת על ההוצאות.
- **בעלי עניין:** בעל העסק / פונקציית הפיננסים (CFO) ועובדים שמנויים על כלים.
- **התהליך העסקי:**
  1. מנוי חדש → חשבונית מגיעה למייל.
  2. סריקה אוטומטית ב‑20 לחודש (APScheduler) + כפתור **Sync** ידני.
  3. חילוץ וסיווג בעזרת AI.
  4. דשבורד + דוח PDF חודשי שנשלח במייל.
- **KPI:** ראות תקציב בזמן אמת · אפס כלים "רפאים" שלא בשימוש · דיוק חילוץ גבוה.
- **בידול:** תמיכת עברית/RTL ורב‑מטבעיות (₪ / $ / €).

---

## D — Data Architecture

- **ישות הליבה — `InvoiceDetail` (Pydantic):** `service_name`, `amount`, `currency`, `category`, `date`, `invoice_id`, `subscription_period`.
- **אחסון:** Supabase PostgreSQL — טבלת `invoices` + טבלת `gmail_accounts` (חדשה); גיבוי מקומי `invoices.json`.
- **אבטחת מידע (שופר):** טוקני ה‑OAuth מאוחסנים **מוצפנים ב‑Fernet** בטבלת `gmail_accounts`, עם **RLS** שמתיר גישה ל‑service‑role בלבד — הטוקנים כבר לא נשמרים כקבצים על הדיסק.
- **איכות נתונים:**
  - **דה‑דופ על `email_id`** (מזהה הודעת Gmail) — `upsert` ב‑Supabase + סינון בין ריצות, כך שאותו מייל לא מעובד ולא מחויב פעמיים מול Gemini.
  - **שער אנטי‑הזיה:** קבלה רק עם `confidence` מעל סף ו‑`source_quote` שמצוטט מילה‑במילה מהמקור.

---

## A — Application Architecture

- **Backend (FastAPI):** `/api/sync`, `/api/invoices`, `/api/auth/login`, `/api/auth/callback`, `/api/reports`.
- **Agent:** Gmail API → **Gemini 2.5 Flash** (`google-genai`, structured output) → Supabase / Google Sheets.
- **חדש:** `oauth_flow.py` + `token_store.py` — OAuth Web flow ואחסון טוקנים מוצפן.
- **שירותים נוספים:** `scheduler.py` (APScheduler, יום 20) · `report_generator.py` (fpdf2 + RTL עברית) · `mailer.py` (שליחת מייל דרך Gmail).
- **Frontend:** דשבורד glassmorphic ב‑Vanilla JS + Chart.js.
- **אמינות (חדש):** נעילת concurrency על סריקה (409) · rate‑limit (slowapi) · retry/backoff · תקרות סריקה.

---

## T — Technology Architecture

- **Runtime:** Python 3.12 · FastAPI / uvicorn.
- **AI:** Gemini 2.5 Flash (SDK רשמי `google-genai`).
- **Data:** Supabase (PostgreSQL).
- **קונטיינריזציה (חדש):** Docker multi‑stage (non‑root, tini) + `docker-compose`.
- **תזמור (חדש):** Kubernetes — `deployment` / `service` / `kustomization` / תבנית `secret`.
- **סודות:** משתני סביבה · `.env` (gitignored) · K8s Secret שנוצר מ‑env‑file.
- **שרשרת אספקה:** gitleaks · Opengrep rules · CycloneDX SBOM · תיקוני CVE · GitFlow‑lite (dev → main ב‑PR).

---

## מה שיפרנו בסבב הזה — תיקוף

| תחום | לפני | אחרי (עכשיו) |
|------|------|-------------|
| **OAuth** | Desktop app + `credentials.json` + `run_local_server` — לא רץ בקונטיינר | **Web OAuth flow** מבוסס env, רץ headless בענן |
| **אחסון טוקנים** | `token_*.json` על הדיסק (plaintext) | **מוצפן Fernet ב‑Supabase** + RLS |
| **פריסה** | הרצה מקומית בלבד | **Docker + Kubernetes** |
| **בקרת API** | סריקה וקריאות לא חסומות | **90 יום / 300 מיילים**, נעילת concurrency (409), rate‑limit, retry/backoff |
| **סודות/אבטחה** | סיכון לסודות בקוד | env + gitleaks + SBOM + Opengrep · `sheet_id` הועבר ל‑env |

---

## אבטחה ואמינות — מבט מקרוב

- **הצפנה במנוחה:** Fernet (AES‑128‑CBC + HMAC); המפתח מסופק רק כסוד ריצה, לא נכנס ל‑git.
- **OAuth Web:** פרמטר `state` נגד CSRF נשמר ב‑session cookie חתום; redirect URI מוגדר במפורש ב‑Google Cloud.
- **בקרת עומס:** rate‑limit לפי IP · נעילה שמונעת סריקות כפולות/מקבילות · backoff על 429/5xx.
- **הקשחה:** קונטיינר non‑root · RLS על הטבלאות · סריקות gitleaks/Opengrep · SBOM לרכיבים.

---

## צעדים הבאים (Roadmap)

- הפרדת ה‑Scheduler לשירות / Kubernetes CronJob נפרד.
- מעבר סודות ל‑GCP Secret Manager / External Secrets.
- ריבוי משתמשים והרשאות (multi‑tenant).
- ניטור מלא: logs · metrics · alerts, ו‑CI/CD מקצה לקצה.
