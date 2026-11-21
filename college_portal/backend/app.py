import os
import io
import base64
import hashlib
import secrets
from urllib.parse import quote
from datetime import datetime, timedelta, date
from functools import wraps

import qrcode
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from sqlalchemy import func

from models import (
    db, User, SchoolClass, Subject, Homework, HomeworkStatus,
    AttendanceSession, AttendanceRecord, Announcement, ParentMessageLog
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))
os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

app = Flask(
    __name__,
    template_folder=os.path.join(FRONTEND_DIR, "templates"),
    static_folder=os.path.join(FRONTEND_DIR, "static"),
)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "instance", "college.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

QR_SESSION_MINUTES = 5  # how long a generated attendance session stays open
QR_ROTATE_SECONDS = 18  # how often the on-screen QR code changes, so a photo of it goes stale fast
LOW_ATTENDANCE_THRESHOLD = 75


# ---------------------------------------------------------------- helpers
def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("You don't have access to that page.", "error")
                return redirect(url_for("post_login_redirect"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def qr_data_uri(text):
    """Renders `text` as a QR code and returns it as an inline base64 PNG."""
    img = qrcode.make(text, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def rotating_qr_token(attendance_session, window_offset=0):
    """
    Derives a short-lived token from the session's fixed secret + the current
    QR_ROTATE_SECONDS time window, so the QR on screen changes every ~18s
    without touching the database. A photo of an old frame stops working
    almost immediately, which is the point — it closes the "scan a friend's
    screenshot" gap that a single session-long QR has.

    window_offset lets validation accept the *previous* window too, as a
    small grace period for scan/network lag right as the code rotates.
    """
    window = int(datetime.utcnow().timestamp() // QR_ROTATE_SECONDS) + window_offset
    raw = f"{attendance_session.id}:{attendance_session.token}:{window}"
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def seconds_left_in_qr_window():
    """How many seconds until the on-screen QR next rotates."""
    now = datetime.utcnow().timestamp()
    return QR_ROTATE_SECONDS - int(now % QR_ROTATE_SECONDS)


def whatsapp_link(phone, message):
    """
    Builds a click-to-chat WhatsApp link (no API key needed — this is the
    officially supported wa.me deep link). Opens WhatsApp Web/app with the
    message pre-filled; the teacher still taps Send themselves.
    For true unattended auto-sending (no click required) see whatsapp_setup.md.
    """
    clean_phone = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"https://wa.me/{clean_phone}?text={quote(message)}"


def student_pending_homework(student):
    """Overdue, not-yet-marked-done homework items for a student."""
    subject_ids = [s.id for s in Subject.query.filter_by(class_id=student.class_id).all()]
    if not subject_ids:
        return []
    done_ids = {hs.homework_id for hs in HomeworkStatus.query.filter_by(student_id=student.id, done=True).all()}
    overdue = Homework.query.filter(
        Homework.subject_id.in_(subject_ids), Homework.due_date <= date.today()
    ).all()
    return [hw for hw in overdue if hw.id not in done_ids]


def build_parent_message(student, teacher, kind):
    school_name = "ITM GIDA, Gorakhpur"
    if kind == "attendance":
        overall_pct, _ = student_attendance_stats(student)
        pct_text = f"{overall_pct}%" if overall_pct is not None else "not yet available"
        return (
            f"Dear Parent/Guardian, this is {teacher.name} from {student.student_class.name}, "
            f"{school_name}. {student.name}'s current attendance is {pct_text}, which is below "
            f"the required {LOW_ATTENDANCE_THRESHOLD}%. Please encourage regular attendance. Thank you."
        )
    if kind == "homework":
        pending = student_pending_homework(student)
        if pending:
            titles = ", ".join(hw.title for hw in pending[:3])
            return (
                f"Dear Parent/Guardian, this is {teacher.name} from {student.student_class.name}, "
                f"{school_name}. {student.name} has {len(pending)} pending assignment(s), including "
                f"\"{titles}\". Kindly follow up at home. Thank you."
            )
        return (
            f"Dear Parent/Guardian, this is {teacher.name} from {student.student_class.name}, "
            f"{school_name}. {student.name} is up to date with homework submissions. Thank you."
        )
    return f"Dear Parent/Guardian, this is {teacher.name} from {school_name} regarding {student.name}. "


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db.session.get(User, uid)


def student_attendance_stats(student):
    """Returns overall % and a per-subject breakdown for a student."""
    subjects = Subject.query.filter_by(class_id=student.class_id).all()
    breakdown = []
    total_sessions = 0
    total_present = 0
    for subj in subjects:
        sessions = AttendanceSession.query.filter_by(subject_id=subj.id).all()
        held = len(sessions)
        present = AttendanceRecord.query.filter(
            AttendanceRecord.student_id == student.id,
            AttendanceRecord.session_id.in_([s.id for s in sessions]) if sessions else False,
            AttendanceRecord.status == "present"
        ).count() if sessions else 0
        pct = round((present / held) * 100, 1) if held else None
        breakdown.append({
            "subject": subj.name,
            "held": held,
            "present": present,
            "pct": pct
        })
        total_sessions += held
        total_present += present
    overall = round((total_present / total_sessions) * 100, 1) if total_sessions else None
    return overall, breakdown


def class_attendance_report(school_class):
    """Per-student attendance % for every student in a class (all subjects combined)."""
    subject_ids = [s.id for s in school_class.subjects]
    all_sessions = AttendanceSession.query.filter(AttendanceSession.subject_id.in_(subject_ids)).all() if subject_ids else []
    session_ids = [s.id for s in all_sessions]
    rows = []
    for student in school_class.students:
        present = AttendanceRecord.query.filter(
            AttendanceRecord.student_id == student.id,
            AttendanceRecord.session_id.in_(session_ids) if session_ids else False,
            AttendanceRecord.status == "present"
        ).count() if session_ids else 0
        held = len(session_ids)
        pct = round((present / held) * 100, 1) if held else None
        rows.append({"student": student, "present": present, "held": held, "pct": pct})
    return rows


# ---------------------------------------------------------------- auth
@app.route("/", methods=["GET"])
def index():
    if "user_id" in session:
        return redirect(url_for("post_login_redirect"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(
            (func.lower(User.email) == identifier) | (func.lower(User.roll_number) == identifier) | (func.lower(User.employee_id) == identifier)
        ).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            session["role"] = user.role
            session["name"] = user.name
            return redirect(url_for("post_login_redirect"))
        flash("Those details don't match our records. Double check and try again.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/after-login")
def post_login_redirect():
    role = session.get("role")
    if role == "student":
        return redirect(url_for("student_dashboard"))
    if role == "teacher":
        return redirect(url_for("teacher_dashboard"))
    if role == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("login"))


# ============================================================= STUDENT
@app.route("/student/dashboard")
@login_required("student")
def student_dashboard():
    user = current_user()
    overall_pct, breakdown = student_attendance_stats(user)
    subject_ids = [s.id for s in Subject.query.filter_by(class_id=user.class_id).all()]
    upcoming_hw = Homework.query.filter(
        Homework.subject_id.in_(subject_ids), Homework.due_date >= date.today()
    ).order_by(Homework.due_date.asc()).limit(4).all() if subject_ids else []
    announcements = Announcement.query.filter_by(class_id=user.class_id).order_by(Announcement.posted_at.desc()).limit(3).all()
    return render_template(
        "student/dashboard.html", user=user, overall_pct=overall_pct,
        breakdown=breakdown, upcoming_hw=upcoming_hw, announcements=announcements,
        threshold=LOW_ATTENDANCE_THRESHOLD
    )


@app.route("/student/homework")
@login_required("student")
def student_homework():
    user = current_user()
    subject_ids = [s.id for s in Subject.query.filter_by(class_id=user.class_id).all()]
    items = Homework.query.filter(Homework.subject_id.in_(subject_ids)).order_by(Homework.due_date.asc()).all() if subject_ids else []
    statuses = {hs.homework_id: hs.done for hs in HomeworkStatus.query.filter_by(student_id=user.id).all()}
    return render_template("student/homework.html", user=user, items=items, statuses=statuses, today=date.today())


@app.route("/student/homework/<int:hw_id>/toggle", methods=["POST"])
@login_required("student")
def toggle_homework(hw_id):
    user = current_user()
    hs = HomeworkStatus.query.filter_by(homework_id=hw_id, student_id=user.id).first()
    if not hs:
        hs = HomeworkStatus(homework_id=hw_id, student_id=user.id, done=True)
        db.session.add(hs)
    else:
        hs.done = not hs.done
    db.session.commit()
    return redirect(url_for("student_homework"))


@app.route("/student/attendance")
@login_required("student")
def student_attendance():
    user = current_user()
    overall_pct, breakdown = student_attendance_stats(user)
    records = AttendanceRecord.query.filter_by(student_id=user.id).order_by(AttendanceRecord.timestamp.desc()).limit(30).all()
    return render_template(
        "student/attendance.html", user=user, overall_pct=overall_pct,
        breakdown=breakdown, records=records, threshold=LOW_ATTENDANCE_THRESHOLD
    )


@app.route("/student/scan")
@login_required("student")
def student_scan():
    user = current_user()
    return render_template("student/scan.html", user=user)


@app.route("/student/scan/submit", methods=["POST"])
@login_required("student")
def student_scan_submit():
    """Called by the camera JS after it decodes a session QR payload: `session_id:token`."""
    user = current_user()
    payload = request.json.get("payload", "") if request.is_json else request.form.get("payload", "")
    try:
        sid_str, token = payload.split(":", 1)
        sid = int(sid_str)
    except (ValueError, AttributeError):
        return jsonify({"ok": False, "message": "That QR doesn't look right. Ask your teacher to regenerate it."})

    sess = db.session.get(AttendanceSession, sid)
    if not sess or token not in (rotating_qr_token(sess, 0), rotating_qr_token(sess, -1)):
        return jsonify({"ok": False, "message": "That code just refreshed on screen — rescan the current one."})
    if sess.is_closed or datetime.utcnow() > sess.expires_at:
        return jsonify({"ok": False, "message": "This QR has expired. Ask your teacher for a fresh one, or use the failsafe."})
    if sess.subject.class_id != user.class_id:
        return jsonify({"ok": False, "message": "This session isn't for your class."})

    existing = AttendanceRecord.query.filter_by(session_id=sid, student_id=user.id).first()
    if existing:
        return jsonify({"ok": False, "message": "You're already marked present for this session."})

    record = AttendanceRecord(session_id=sid, student_id=user.id, status="present", marked_via="qr")
    db.session.add(record)
    db.session.commit()
    return jsonify({"ok": True, "message": f"Marked present for {sess.subject.name}."})


@app.route("/student/profile")
@login_required("student")
def student_profile():
    user = current_user()
    qr_image = qr_data_uri(user.qr_code_value)
    return render_template("student/profile.html", user=user, qr_image=qr_image)


# ============================================================= TEACHER
@app.route("/teacher/dashboard")
@login_required("teacher")
def teacher_dashboard():
    user = current_user()
    coordinated = SchoolClass.query.filter_by(coordinator_id=user.id).all()
    taught_subjects = Subject.query.filter_by(teacher_id=user.id).all()
    return render_template("teacher/dashboard.html", user=user, coordinated=coordinated, taught_subjects=taught_subjects)


@app.route("/teacher/class/<int:class_id>/report")
@login_required("teacher")
def teacher_class_report(class_id):
    user = current_user()
    school_class = db.session.get(SchoolClass, class_id)
    if not school_class or school_class.coordinator_id != user.id:
        flash("You can only view reports for classes you coordinate.", "error")
        return redirect(url_for("teacher_dashboard"))
    rows = class_attendance_report(school_class)
    return render_template("teacher/class_report.html", user=user, school_class=school_class, rows=rows, threshold=LOW_ATTENDANCE_THRESHOLD)


@app.route("/teacher/class/<int:class_id>/students")
@login_required("teacher")
def teacher_students(class_id):
    user = current_user()
    school_class = db.session.get(SchoolClass, class_id)
    if not school_class or school_class.coordinator_id != user.id:
        flash("You can only manage classes you coordinate.", "error")
        return redirect(url_for("teacher_dashboard"))
    return render_template("teacher/students.html", user=user, school_class=school_class)


@app.route("/teacher/class/<int:class_id>/students/add", methods=["GET", "POST"])
@login_required("teacher")
def teacher_add_student(class_id):
    user = current_user()
    school_class = db.session.get(SchoolClass, class_id)
    if not school_class or school_class.coordinator_id != user.id:
        flash("You can only manage classes you coordinate.", "error")
        return redirect(url_for("teacher_dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        roll = request.form.get("roll_number", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip() or "student123"
        parent_name = request.form.get("parent_name", "").strip()
        parent_phone = "".join(ch for ch in request.form.get("parent_phone", "") if ch.isdigit())
        if User.query.filter((User.email == email) | (User.roll_number == roll)).first():
            flash("A student with that roll number or email already exists.", "error")
        else:
            student = User(
                name=name, email=email, role="student", roll_number=roll,
                class_id=class_id, qr_code_value=secrets.token_hex(8),
                parent_name=parent_name or None, parent_phone=parent_phone or None
            )
            student.set_password(password)
            db.session.add(student)
            db.session.commit()
            flash(f"{name} added to {school_class.name}.", "success")
            return redirect(url_for("teacher_students", class_id=class_id))
    return render_template("teacher/add_student.html", user=user, school_class=school_class)


@app.route("/teacher/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required("teacher")
def teacher_edit_student(student_id):
    user = current_user()
    student = db.session.get(User, student_id)
    if not student or student.role != "student" or student.student_class.coordinator_id != user.id:
        flash("You can only edit students in classes you coordinate.", "error")
        return redirect(url_for("teacher_dashboard"))
    if request.method == "POST":
        student.name = request.form.get("name", "").strip()
        student.email = request.form.get("email", "").strip().lower()
        student.roll_number = request.form.get("roll_number", "").strip()
        student.parent_name = request.form.get("parent_name", "").strip() or None
        student.parent_phone = "".join(ch for ch in request.form.get("parent_phone", "") if ch.isdigit()) or None
        db.session.commit()
        flash("Student details updated.", "success")
        return redirect(url_for("teacher_students", class_id=student.class_id))
    return render_template("teacher/edit_student.html", user=user, student=student)


@app.route("/teacher/students/<int:student_id>/delete", methods=["POST"])
@login_required("teacher")
def teacher_delete_student(student_id):
    user = current_user()
    student = db.session.get(User, student_id)
    if not student or student.role != "student" or student.student_class.coordinator_id != user.id:
        flash("You can only remove students in classes you coordinate.", "error")
        return redirect(url_for("teacher_dashboard"))
    class_id = student.class_id
    HomeworkStatus.query.filter_by(student_id=student.id).delete()
    AttendanceRecord.query.filter_by(student_id=student.id).delete()
    db.session.delete(student)
    db.session.commit()
    flash("Student removed.", "success")
    return redirect(url_for("teacher_students", class_id=class_id))


@app.route("/teacher/generate-qr", methods=["GET", "POST"])
@login_required("teacher")
def teacher_generate_qr():
    user = current_user()
    subjects = Subject.query.filter_by(teacher_id=user.id).all()
    active_session = None
    if request.method == "POST":
        subject_id = int(request.form.get("subject_id"))
        subject = db.session.get(Subject, subject_id)
        if not subject or subject.teacher_id != user.id:
            flash("You don't teach that subject.", "error")
            return redirect(url_for("teacher_generate_qr"))
        token = secrets.token_hex(6)
        new_session = AttendanceSession(
            subject_id=subject_id, teacher_id=user.id, date=date.today(),
            token=token, expires_at=datetime.utcnow() + timedelta(minutes=QR_SESSION_MINUTES)
        )
        db.session.add(new_session)
        db.session.commit()
        return redirect(url_for("teacher_generate_qr", session_id=new_session.id))

    session_id = request.args.get("session_id", type=int)
    qr_image = None
    if session_id:
        active_session = db.session.get(AttendanceSession, session_id)
        if active_session and active_session.teacher_id != user.id:
            active_session = None
        if active_session:
            qr_image = qr_data_uri(f"{active_session.id}:{rotating_qr_token(active_session)}")
    return render_template(
        "teacher/generate_qr.html", user=user, subjects=subjects,
        active_session=active_session, qr_image=qr_image, qr_minutes=QR_SESSION_MINUTES,
        rotate_seconds=QR_ROTATE_SECONDS
    )


@app.route("/teacher/session/<int:session_id>/close", methods=["POST"])
@login_required("teacher")
def teacher_close_session(session_id):
    user = current_user()
    sess = db.session.get(AttendanceSession, session_id)
    if sess and sess.teacher_id == user.id:
        sess.is_closed = True
        db.session.commit()
    return redirect(url_for("teacher_generate_qr"))


@app.route("/teacher/session/<int:session_id>/live-count")
@login_required("teacher")
def teacher_session_live_count(session_id):
    user = current_user()
    sess = db.session.get(AttendanceSession, session_id)
    if not sess or sess.teacher_id != user.id:
        return jsonify({"ok": False})
    count = AttendanceRecord.query.filter_by(session_id=session_id).count()
    total = len(sess.subject.school_class.students)
    expired = datetime.utcnow() > sess.expires_at or sess.is_closed
    response = {"ok": True, "count": count, "total": total, "expired": expired}
    if not expired:
        # Refresh the on-screen QR to the current rotation window each poll,
        # so the browser always shows a code that's actually still valid.
        response["qr_image"] = qr_data_uri(f"{sess.id}:{rotating_qr_token(sess)}")
        response["seconds_left"] = seconds_left_in_qr_window()
    return jsonify(response)


@app.route("/teacher/failsafe", methods=["GET"])
@login_required("teacher")
def teacher_failsafe():
    user = current_user()
    subjects = Subject.query.filter_by(teacher_id=user.id).all()
    open_sessions = AttendanceSession.query.filter_by(teacher_id=user.id, is_closed=False).filter(
        AttendanceSession.expires_at >= datetime.utcnow() - timedelta(hours=2)
    ).order_by(AttendanceSession.created_at.desc()).all()
    return render_template("teacher/failsafe_scan.html", user=user, subjects=subjects, open_sessions=open_sessions)


@app.route("/teacher/failsafe/submit", methods=["POST"])
@login_required("teacher")
def teacher_failsafe_submit():
    """Marks attendance from a student's personal ID QR (or manually typed roll number)."""
    user = current_user()
    session_id = request.form.get("session_id", type=int) or (request.json.get("session_id") if request.is_json else None)
    qr_value = request.form.get("qr_value") or (request.json.get("qr_value") if request.is_json else None)
    roll_number = request.form.get("roll_number") or (request.json.get("roll_number") if request.is_json else None)

    sess = db.session.get(AttendanceSession, int(session_id)) if session_id else None
    if not sess or sess.teacher_id != user.id:
        return jsonify({"ok": False, "message": "Select a valid session first."})

    student = None
    if qr_value:
        student = User.query.filter_by(qr_code_value=qr_value, role="student").first()
    elif roll_number:
        student = User.query.filter_by(roll_number=roll_number.strip(), role="student").first()

    if not student:
        return jsonify({"ok": False, "message": "No student found for that ID."})
    if student.class_id != sess.subject.class_id:
        return jsonify({"ok": False, "message": f"{student.name} isn't in this class."})

    existing = AttendanceRecord.query.filter_by(session_id=sess.id, student_id=student.id).first()
    if existing:
        return jsonify({"ok": False, "message": f"{student.name} is already marked present."})

    record = AttendanceRecord(session_id=sess.id, student_id=student.id, status="present", marked_via="failsafe")
    db.session.add(record)
    db.session.commit()
    return jsonify({"ok": True, "message": f"{student.name} marked present (failsafe)."})


@app.route("/teacher/homework", methods=["GET", "POST"])
@login_required("teacher")
def teacher_homework():
    user = current_user()
    subjects = Subject.query.filter_by(teacher_id=user.id).all()
    if request.method == "POST":
        subject_id = int(request.form.get("subject_id"))
        subject = db.session.get(Subject, subject_id)
        if not subject or subject.teacher_id != user.id:
            flash("You don't teach that subject.", "error")
        else:
            hw = Homework(
                subject_id=subject_id,
                title=request.form.get("title", "").strip(),
                description=request.form.get("description", "").strip(),
                due_date=datetime.strptime(request.form.get("due_date"), "%Y-%m-%d").date(),
                posted_by=user.id
            )
            db.session.add(hw)
            db.session.commit()
            flash("Homework posted.", "success")
        return redirect(url_for("teacher_homework"))
    subject_ids = [s.id for s in subjects]
    posted = Homework.query.filter(Homework.subject_id.in_(subject_ids)).order_by(Homework.posted_at.desc()).all() if subject_ids else []
    return render_template("teacher/homework.html", user=user, subjects=subjects, posted=posted)


@app.route("/teacher/announce", methods=["POST"])
@login_required("teacher")
def teacher_announce():
    user = current_user()
    class_id = request.form.get("class_id", type=int)
    school_class = db.session.get(SchoolClass, class_id)
    if not school_class or school_class.coordinator_id != user.id:
        flash("You can only post to classes you coordinate.", "error")
    else:
        db.session.add(Announcement(class_id=class_id, posted_by=user.id, message=request.form.get("message", "").strip()))
        db.session.commit()
        flash("Announcement posted.", "success")
    return redirect(url_for("teacher_class_report", class_id=class_id))


@app.route("/teacher/message-parents")
@login_required("teacher")
def teacher_message_parents():
    user = current_user()
    coordinated = SchoolClass.query.filter_by(coordinator_id=user.id).all()
    if not coordinated:
        return render_template("teacher/message_parents.html", user=user, coordinated=[], school_class=None, rows=[], recent=[])

    class_id = request.args.get("class_id", type=int) or coordinated[0].id
    school_class = db.session.get(SchoolClass, class_id)
    if not school_class or school_class.coordinator_id != user.id:
        flash("You can only message parents of classes you coordinate.", "error")
        return redirect(url_for("teacher_message_parents"))

    rows = []
    for student in sorted(school_class.students, key=lambda s: s.roll_number or ""):
        overall_pct, _ = student_attendance_stats(student)
        pending = student_pending_homework(student)
        low_attendance = overall_pct is not None and overall_pct < LOW_ATTENDANCE_THRESHOLD
        rows.append({
            "student": student,
            "pct": overall_pct,
            "pending_count": len(pending),
            "low_attendance": low_attendance,
            "attendance_link": whatsapp_link(student.parent_phone, build_parent_message(student, user, "attendance")),
            "homework_link": whatsapp_link(student.parent_phone, build_parent_message(student, user, "homework")),
            "has_phone": bool(student.parent_phone),
        })

    recent = ParentMessageLog.query.filter(
        ParentMessageLog.student_id.in_([s.id for s in school_class.students])
    ).order_by(ParentMessageLog.sent_at.desc()).limit(10).all() if school_class.students else []

    return render_template(
        "teacher/message_parents.html", user=user, coordinated=coordinated,
        school_class=school_class, rows=rows, recent=recent, threshold=LOW_ATTENDANCE_THRESHOLD
    )


@app.route("/teacher/message-parents/log", methods=["POST"])
@login_required("teacher")
def teacher_message_parents_log():
    """Called via JS right before a wa.me link opens, so we keep a record of what was sent."""
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    student = db.session.get(User, data.get("student_id"))
    if not student or student.role != "student" or student.student_class.coordinator_id != user.id:
        return jsonify({"ok": False}), 403
    db.session.add(ParentMessageLog(
        student_id=student.id, sent_by=user.id,
        category=data.get("category", "custom"), message=data.get("message", "")
    ))
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/teacher/message-parents/custom", methods=["POST"])
@login_required("teacher")
def teacher_message_parents_custom():
    """Builds wa.me links for a free-text broadcast to every parent in a class."""
    user = current_user()
    class_id = request.form.get("class_id", type=int)
    school_class = db.session.get(SchoolClass, class_id)
    if not school_class or school_class.coordinator_id != user.id:
        flash("You can only message parents of classes you coordinate.", "error")
        return redirect(url_for("teacher_message_parents"))
    text = request.form.get("message", "").strip()
    if not text:
        flash("Write a message first.", "error")
        return redirect(url_for("teacher_message_parents", class_id=class_id))

    full_text = f"Dear Parent/Guardian, this is {user.name} from {school_class.name}, ITM GIDA, Gorakhpur. {text}"
    links = []
    for student in school_class.students:
        if student.parent_phone:
            links.append({"student": student, "link": whatsapp_link(student.parent_phone, full_text), "message": full_text})
    return render_template("teacher/message_parents_broadcast.html", user=user, school_class=school_class, links=links)


# ============================================================== ADMIN
@app.route("/admin/dashboard")
@login_required("admin")
def admin_dashboard():
    total_students = User.query.filter_by(role="student").count()
    total_teachers = User.query.filter_by(role="teacher").count()
    total_classes = SchoolClass.query.count()
    total_sessions_today = AttendanceSession.query.filter(AttendanceSession.date == date.today()).count()
    classes = SchoolClass.query.all()
    class_rows = []
    for c in classes:
        rows = class_attendance_report(c)
        valid = [r["pct"] for r in rows if r["pct"] is not None]
        avg = round(sum(valid) / len(valid), 1) if valid else None
        class_rows.append({"school_class": c, "avg_pct": avg, "student_count": len(c.students)})
    return render_template(
        "admin/dashboard.html", total_students=total_students, total_teachers=total_teachers,
        total_classes=total_classes, total_sessions_today=total_sessions_today, class_rows=class_rows
    )


@app.route("/admin/users")
@login_required("admin")
def admin_users():
    role_filter = request.args.get("role", "all")
    query = User.query
    if role_filter in ("student", "teacher", "admin"):
        query = query.filter_by(role=role_filter)
    users = query.order_by(User.role, User.name).all()
    return render_template("admin/users.html", users=users, role_filter=role_filter)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required("admin")
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if user and user.role != "admin":
        if user.role == "student":
            HomeworkStatus.query.filter_by(student_id=user.id).delete()
            AttendanceRecord.query.filter_by(student_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
        flash("User removed.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/classes", methods=["GET", "POST"])
@login_required("admin")
def admin_classes():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        coordinator_id = request.form.get("coordinator_id", type=int)
        db.session.add(SchoolClass(name=name, coordinator_id=coordinator_id or None))
        db.session.commit()
        flash("Class created.", "success")
        return redirect(url_for("admin_classes"))
    classes = SchoolClass.query.all()
    teachers = User.query.filter_by(role="teacher").all()
    return render_template("admin/classes.html", classes=classes, teachers=teachers)


@app.route("/admin/classes/<int:class_id>/coordinator", methods=["POST"])
@login_required("admin")
def admin_set_coordinator(class_id):
    school_class = db.session.get(SchoolClass, class_id)
    coordinator_id = request.form.get("coordinator_id", type=int)
    if school_class:
        school_class.coordinator_id = coordinator_id or None
        db.session.commit()
        flash("Coordinator updated.", "success")
    return redirect(url_for("admin_classes"))


@app.route("/admin/reports")
@login_required("admin")
def admin_reports():
    classes = SchoolClass.query.all()
    data = {c.id: class_attendance_report(c) for c in classes}
    return render_template("admin/reports.html", classes=classes, data=data, threshold=LOW_ATTENDANCE_THRESHOLD)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
