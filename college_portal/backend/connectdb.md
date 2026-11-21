# Connecting this project to MySQL

By default the app uses a local SQLite file (`instance/college.db`) so it
runs immediately with zero setup. When you're ready to move to a real
MySQL database (for a production deployment, or just because you prefer
it), here's exactly what to change.

Nothing in the templates, routes, or logic needs to change — only the
database connection string and one driver install, because the app
already goes through SQLAlchemy.

---

## 1. Install the MySQL driver

```bash
pip install mysqlclient
```

If `mysqlclient` gives you trouble building on Windows, use the pure-Python
alternative instead:

```bash
pip install pymysql
```

(and see the note at the bottom about adjusting the connection string prefix
if you go this route)

## 2. Create the database and a user

In MySQL (via the `mysql` CLI, MySQL Workbench, or phpMyAdmin):

```sql
CREATE DATABASE college_portal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'college_app'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON college_portal.* TO 'college_app'@'localhost';
FLUSH PRIVILEGES;
```

## 3. Update the connection string in `app.py`

Find this line near the top of `app.py`:

```python
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "instance", "college.db")
```

Replace it with:

```python
app.config["SQLALCHEMY_DATABASE_URI"] = (
    "mysql://college_app:choose-a-strong-password@localhost/college_portal"
)
```

**Better practice — don't hardcode the password.** Read it from an
environment variable instead:

```python
import os
db_user = os.environ.get("DB_USER", "college_app")
db_pass = os.environ.get("DB_PASS", "")
db_host = os.environ.get("DB_HOST", "localhost")
db_name = os.environ.get("DB_NAME", "college_portal")

app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql://{db_user}:{db_pass}@{db_host}/{db_name}"
```

Then before running the app:

```bash
export DB_USER=college_app
export DB_PASS=choose-a-strong-password
export DB_HOST=localhost
export DB_NAME=college_portal
```

(On Windows / PowerShell, use `$env:DB_PASS = "..."` instead of `export`.)

If you installed `pymysql` instead of `mysqlclient`, the URI prefix changes
slightly, and you need two extra lines at the very top of `app.py`:

```python
import pymysql
pymysql.install_as_MySQLdb()
```

and the URI becomes `mysql+pymysql://...` instead of `mysql://...`.

## 4. Create the tables

The table definitions already exist in `models.py` — nothing to rewrite.
Just run the seed script once against the new database:

```bash
python seed_data.py
```

This will create every table (`users`, `classes`, `subjects`, `homework`,
`homework_status`, `attendance_sessions`, `attendance_records`,
`announcements`) directly in MySQL and fill them with the same dummy data
you saw in SQLite. If you don't want the dummy data and only want the empty
schema, open `seed_data.py` and comment out everything below the `wipe()`
call, then run it — that leaves you with clean tables and only the schema.

## 5. Run the app as usual

```bash
python app.py
```

Everything else — the login logic, attendance QR generation, homework
routes — reads and writes through SQLAlchemy models, so it works
identically whether the underlying database is SQLite or MySQL.

---

## Notes on going to production

A few things worth doing before this is used for real students, beyond
just swapping the database:

- **Change `SECRET_KEY`.** It's currently a hardcoded placeholder in
  `app.py`. Set it via an environment variable and use a long random value
  (`python -c "import secrets; print(secrets.token_hex(32))"`).
- **Don't use the Flask dev server.** Run it behind `gunicorn` or `waitress`
  and a real web server (nginx) in front of it.
- **Turn `debug=False`** in the `app.run(...)` call at the bottom of
  `app.py` — debug mode exposes a live Python console on error pages.
- **Use HTTPS** in production so login credentials and session cookies
  aren't sent in plaintext, especially since students will be using this
  over campus/mobile Wi-Fi.
- **Back up the database regularly** — attendance records are the kind of
  data that's painful to lose.
