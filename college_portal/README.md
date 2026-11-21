# ITM GIDA, Gorakhpur — College Portal

Built for Institute of Technology & Management (ITM), GIDA, Gorakhpur.

A QR-based attendance and homework portal with three roles: **student**,
**teacher**, and **admin**. Built with Flask + SQLAlchemy (SQLite by
default) and plain HTML/CSS/JS — no frontend framework, no build step.

## What's in here

**Students** can:
- Log in with their roll number and password
- See homework/assignments with due dates, and check them off as done
- See their attendance percentage overall and per-subject, with a warning
  once it drops below 75%
- Scan a teacher's QR code with their camera to mark themselves present
- Fall back to a personal ID QR code (in their profile) if their camera or
  the classroom QR won't cooperate — a teacher can scan *that* instead
- See recent announcements from their class coordinator

**Teachers** can:
- See the classes they coordinate and the subjects they teach
- View a full attendance report for classes they coordinate, sorted
  low-to-high so struggling students are easy to spot
- Add, edit, and remove students in their coordinated classes
- Generate a time-limited attendance QR for a class session (auto-expires
  after 5 minutes, with a live count of who's scanned in)
- Use the failsafe scanner — camera-scan a student's ID QR, or type their
  roll number in by hand — for students who can't scan the session QR
- Upload homework/assignments per subject
- Post announcements to a class they coordinate
- Message a parent directly on WhatsApp with one tap — pre-written
  attendance or homework alerts, or a custom broadcast to the whole class
  (see "About the WhatsApp messaging" below)

**Admins** can:
- See portal-wide stats (student/teacher/class counts, sessions run today)
- View and remove any user account
- Create classes and assign which teacher coordinates each one
- View attendance reports across every class in the college

## Running it locally

```bash
cd college_portal/backend
pip install -r requirements.txt
python seed_data.py   # creates instance/college.db and fills it with demo data
python app.py
```

Then open **http://127.0.0.1:5000** and sign in with any of the demo
accounts below.

| Role    | Login              | Password   |
|---------|---------------------|------------|
| Admin   | admin@college.edu   | admin123   |
| Teacher | meera.rao@college.edu | teach123 |
| Teacher | imran.khan@college.edu | teach123 |
| Student | CS2A001             | student123 |
| Student | CS2A003 (low attendance example — Rohan Gupta) | student123 |

Full name/roll number list for every seeded student is in `seed_data.py`.

## About the WhatsApp messaging

The teacher "Message parents" page uses WhatsApp's free **click-to-chat**
links (`wa.me/<number>?text=...`) — no account, API key, or approval process
needed. The app writes the message (attendance %, pending homework, or a
custom broadcast), and tapping the button opens WhatsApp Web or the
WhatsApp app with everything pre-filled; the teacher just hits send.

Every send is logged to a `parent_message_log` table so there's a record of
what was sent and when — visible in the "Recently sent" panel on that page.

This is a deliberate default: it needs zero setup and works the moment you
run the app. If you want messages to go out **without a teacher tapping
Send** — truly automatic, e.g. triggered the moment attendance closes below
75% — that requires WhatsApp's Business Cloud API through Meta, which needs
a verified business account. See **`whatsapp_setup.md`** for exactly how to
wire that in without changing anything else about the app.

## About the QR scanning

The camera scanning (both the student "scan attendance" page and the
teacher "failsafe scan" page) uses the open-source `html5-qrcode` library
loaded from a CDN — no native app or extra install needed, it just asks
the browser for camera permission. It needs to run over `https://` or
`localhost` for most browsers to allow camera access, which `127.0.0.1`
satisfies for local testing.

A generated session QR encodes `session_id:token` and rotates automatically
every 18 seconds (`QR_ROTATE_SECONDS` in `app.py`) — the code on screen
changes on its own, so a photo or screenshot of it stops working almost
immediately, closing the "scan a friend's screen" gap a static QR has. The
underlying session itself stays open for 5 minutes (configurable via
`QR_SESSION_MINUTES`), so latecomers can still scan the newest code within
that window. A student's personal ID QR still doesn't expire, since it's a
backup, not a one-time pass.

## Moving off SQLite

This starts on SQLite so it runs with zero setup. See **`connectdb.md`**
for the exact steps to point it at a real MySQL database instead — it's a
config change, not a rewrite, since everything goes through SQLAlchemy
models.

## Sending WhatsApp messages to parents

See **`whatsapp_setup.md`** — covers the click-to-chat approach the app
ships with, and how to upgrade to fully automatic sending via the WhatsApp
Business Cloud API.

## Project layout

```
college_portal/
  backend/
    app.py              routes for all three portals
    models.py           SQLAlchemy models
    seed_data.py        wipes + repopulates the demo database
    requirements.txt
    instance/           SQLite database
    connectdb.md        MySQL migration guide
    whatsapp_setup.md   WhatsApp integration guide
  frontend/
    static/
      css/style.css     the one stylesheet, no framework
      js/scanner.js     shared camera-scanning helper
    templates/
      base.html, login.html
      student/          dashboard, homework, attendance, scan, profile
      teacher/          dashboard, class report, student mgmt, QR
                        generation, failsafe scan, homework
      admin/            dashboard, users, classes, reports
  README.md
```

## A few implementation notes

- Passwords are hashed with Werkzeug's `generate_password_hash` — never
  stored in plaintext, including in the dummy data (seed script sets real
  hashes, the plaintext passwords above are just what you type at login).
- A student only ever sees their own class's subjects, homework, and
  attendance — enforced server-side, not just hidden in the UI.
- A teacher can only manage/report on classes they actually coordinate —
  also enforced server-side (see the `login_required` + ownership checks
  in `app.py`), not just a UI restriction.
- Attendance percentage math lives in `student_attendance_stats()` and
  `class_attendance_report()` in `app.py` — both compute from raw
  `AttendanceRecord` rows rather than a cached counter, so there's one
  source of truth.
