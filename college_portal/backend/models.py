"""
Database models for the College Portal.

Kept deliberately simple (SQLite via SQLAlchemy) so it is easy to read,
seed with dummy data, and later re-point at MySQL. See connectdb.md for
the migration steps.
"""
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    """A single account. role decides which portal they land on."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # student | teacher | admin

    # student-only fields
    roll_number = db.Column(db.String(30), unique=True, nullable=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=True)
    qr_code_value = db.Column(db.String(64), unique=True, nullable=True)  # failsafe ID QR
    parent_name = db.Column(db.String(120), nullable=True)
    parent_phone = db.Column(db.String(20), nullable=True)  # digits with country code, e.g. 91XXXXXXXXXX

    # teacher-only fields
    employee_id = db.Column(db.String(30), unique=True, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    student_class = db.relationship("SchoolClass", foreign_keys=[class_id], back_populates="students")

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)


class SchoolClass(db.Model):
    """A section/batch of students, e.g. 'BSc CS - Year 2 - A'."""
    __tablename__ = "classes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    coordinator_id = db.Column(db.Integer, db.ForeignKey("users.id", use_alter=True, name="fk_class_coordinator"), nullable=True)

    coordinator = db.relationship("User", foreign_keys=[coordinator_id])
    students = db.relationship("User", foreign_keys=[User.class_id], back_populates="student_class")
    subjects = db.relationship("Subject", back_populates="school_class")


class Subject(db.Model):
    """A subject taught to one class by one teacher."""
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    school_class = db.relationship("SchoolClass", back_populates="subjects")
    teacher = db.relationship("User", foreign_keys=[teacher_id])


class Homework(db.Model):
    __tablename__ = "homework"

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.Date, nullable=False)
    posted_at = db.Column(db.DateTime, default=datetime.utcnow)
    posted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    subject = db.relationship("Subject")


class HomeworkStatus(db.Model):
    """Per-student 'done / not done' tracking for a homework item."""
    __tablename__ = "homework_status"

    id = db.Column(db.Integer, primary_key=True)
    homework_id = db.Column(db.Integer, db.ForeignKey("homework.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    done = db.Column(db.Boolean, default=False)

    __table_args__ = (db.UniqueConstraint("homework_id", "student_id"),)


class AttendanceSession(db.Model):
    """One class period for which a QR was generated."""
    __tablename__ = "attendance_sessions"

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_closed = db.Column(db.Boolean, default=False)

    subject = db.relationship("Subject")


class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(10), default="present")  # present | absent
    marked_via = db.Column(db.String(10), default="qr")  # qr | failsafe | manual
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("session_id", "student_id"),)

    session = db.relationship("AttendanceSession")
    student = db.relationship("User")


class Announcement(db.Model):
    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False)
    posted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    posted_at = db.Column(db.DateTime, default=datetime.utcnow)


class ParentMessageLog(db.Model):
    """Record of WhatsApp messages a teacher has sent to a parent (for audit/history)."""
    __tablename__ = "parent_message_log"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    sent_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # attendance | homework | custom
    message = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("User", foreign_keys=[student_id])
    teacher = db.relationship("User", foreign_keys=[sent_by])
