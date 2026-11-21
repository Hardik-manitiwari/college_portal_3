CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  roll_number TEXT UNIQUE,
  class_id INTEGER,
  qr_code_value TEXT UNIQUE,
  parent_name TEXT,
  parent_phone TEXT,
  employee_id TEXT UNIQUE,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS classes (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  coordinator_id INTEGER
);

CREATE TABLE IF NOT EXISTS subjects (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  class_id INTEGER NOT NULL,
  teacher_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS homework (
  id INTEGER PRIMARY KEY,
  subject_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  due_date TEXT NOT NULL,
  posted_at TEXT,
  posted_by INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS homework_status (
  id INTEGER PRIMARY KEY,
  homework_id INTEGER NOT NULL,
  student_id INTEGER NOT NULL,
  done INTEGER DEFAULT 0,
  UNIQUE(homework_id, student_id)
);

CREATE TABLE IF NOT EXISTS attendance_sessions (
  id INTEGER PRIMARY KEY,
  subject_id INTEGER NOT NULL,
  teacher_id INTEGER NOT NULL,
  date TEXT,
  token TEXT NOT NULL UNIQUE,
  created_at TEXT,
  expires_at TEXT NOT NULL,
  is_closed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS attendance_records (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL,
  student_id INTEGER NOT NULL,
  status TEXT DEFAULT 'present',
  marked_via TEXT DEFAULT 'qr',
  timestamp TEXT,
  UNIQUE(session_id, student_id)
);

CREATE TABLE IF NOT EXISTS announcements (
  id INTEGER PRIMARY KEY,
  class_id INTEGER NOT NULL,
  posted_by INTEGER NOT NULL,
  message TEXT NOT NULL,
  posted_at TEXT
);

CREATE TABLE IF NOT EXISTS parent_message_log (
  id INTEGER PRIMARY KEY,
  student_id INTEGER NOT NULL,
  sent_by INTEGER NOT NULL,
  category TEXT NOT NULL,
  message TEXT NOT NULL,
  sent_at TEXT
);
