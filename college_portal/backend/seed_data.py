"""
Wipes and re-populates the database with dummy data so the app is usable
immediately. Run with: python seed_data.py
"""
import os
import secrets
import random
from datetime import date, timedelta, datetime

from app import app
from models import (
    db, User, SchoolClass, Subject, Homework, HomeworkStatus,
    AttendanceSession, AttendanceRecord, Announcement
)

random.seed(42)


def wipe():
    db.drop_all()
    db.create_all()


def make_user(name, email, role, password, **kwargs):
    u = User(name=name, email=email, role=role, **kwargs)
    u.set_password(password)
    db.session.add(u)
    return u


def run():
    with app.app_context():
        wipe()

        # ---------------- admin
        make_user("Farah Ansari", "admin@college.edu", "admin", "admin123", employee_id="ADM-001")

        # ---------------- teachers
        t_rao = make_user("Dr. Meera Rao", "meera.rao@college.edu", "teacher", "teach123", employee_id="EMP-101")
        t_khan = make_user("Imran Khan", "imran.khan@college.edu", "teacher", "teach123", employee_id="EMP-102")
        t_verma = make_user("Sunita Verma", "sunita.verma@college.edu", "teacher", "teach123", employee_id="EMP-103")
        db.session.flush()

        # ---------------- classes
        cs2a = SchoolClass(name="B.Sc CS - Year 2 - Section A", coordinator_id=t_rao.id)
        cs2b = SchoolClass(name="B.Sc CS - Year 2 - Section B", coordinator_id=t_khan.id)
        db.session.add_all([cs2a, cs2b])
        db.session.flush()

        # ---------------- subjects
        subjects = [
            Subject(name="Data Structures", class_id=cs2a.id, teacher_id=t_rao.id),
            Subject(name="Operating Systems", class_id=cs2a.id, teacher_id=t_khan.id),
            Subject(name="Discrete Mathematics", class_id=cs2a.id, teacher_id=t_verma.id),
            Subject(name="Database Systems", class_id=cs2b.id, teacher_id=t_khan.id),
            Subject(name="Computer Networks", class_id=cs2b.id, teacher_id=t_verma.id),
        ]
        db.session.add_all(subjects)
        db.session.flush()
        ds, os_, dm, db_sys, cn = subjects

        # ---------------- students
        names_a = [
            "Aarav Mehta", "Priya Nair", "Rohan Gupta", "Sneha Kulkarni", "Kabir Malhotra",
            "Ananya Iyer", "Vivaan Shah", "Ishita Rao", "Aditya Pillai", "Diya Chatterjee",
            "Karan Bhatt", "Meera Joshi"
        ]
        names_b = [
            "Nikhil Reddy", "Pooja Menon", "Arjun Saxena", "Tanvi Deshmukh", "Rahul Kapoor",
            "Simran Kaur", "Yash Agarwal", "Neha Bansal", "Dev Chauhan", "Riya Sen",
            "Aryan Bose", "Kavya Ramesh"
        ]

        def add_students(names, klass, roll_prefix, phone_base):
            students = []
            parent_first_names = [
                "Rajesh", "Suresh", "Anil", "Vinod", "Ramesh", "Sanjay", "Ashok", "Mahesh",
                "Dinesh", "Rakesh", "Sunita", "Kavita", "Meena", "Geeta", "Poonam", "Rekha",
                "Shobha", "Usha", "Vandana", "Nirmala", "Manoj", "Pramod", "Naresh", "Yogesh"
            ]
            for i, name in enumerate(names, start=1):
                roll = f"{roll_prefix}{i:03d}"
                email = f"{name.split()[0].lower()}.{roll.lower()}@college.edu"
                surname = name.split()[-1]
                parent_first = parent_first_names[(i * 3) % len(parent_first_names)]
                parent_name = f"{parent_first} {surname}"
                # Dummy Indian mobile numbers, digits-only with country code (wa.me-ready format)
                parent_phone = f"91{phone_base + i}"
                s = make_user(
                    name, email, "student", "student123",
                    roll_number=roll, class_id=klass.id, qr_code_value=secrets.token_hex(8),
                    parent_name=parent_name, parent_phone=parent_phone
                )
                students.append(s)
            return students

        students_a = add_students(names_a, cs2a, "CS2A", 9800000100)
        students_b = add_students(names_b, cs2b, "CS2B", 9800000200)
        db.session.flush()

        # ---------------- homework
        today = date.today()
        hw_defs = [
            (ds, "Linked List Assignment", "Implement singly & doubly linked lists with insert/delete ops.", 3),
            (ds, "Tree Traversal Problem Set", "Solve the 6 traversal problems from the shared sheet.", 7),
            (os_, "Process Scheduling Report", "Compare FCFS, SJF and Round Robin with sample data.", 5),
            (dm, "Set Theory Worksheet", "Questions 1-15 from Chapter 3.", -2),
            (db_sys, "ER Diagram Submission", "Design an ER diagram for a library system.", 4),
            (cn, "OSI Layers Quiz Prep", "Read chapters 2-3 before Friday's quiz.", 2),
        ]
        for subj, title, desc, offset_days in hw_defs:
            hw = Homework(
                subject_id=subj.id, title=title, description=desc,
                due_date=today + timedelta(days=offset_days), posted_by=subj.teacher_id
            )
            db.session.add(hw)
        db.session.flush()

        # mark a few homework items done for some students (nice realistic touch)
        for hw in Homework.query.filter(Homework.due_date < today).all():
            klass_students = students_a if hw.subject.class_id == cs2a.id else students_b
            for s in random.sample(klass_students, k=min(5, len(klass_students))):
                db.session.add(HomeworkStatus(homework_id=hw.id, student_id=s.id, done=True))

        # ---------------- attendance history (last 12 sessions per subject)
        def build_sessions(subject, klass_students, dropout_student=None):
            for day_offset in range(12, 0, -1):
                sess_date = today - timedelta(days=day_offset)
                sess = AttendanceSession(
                    subject_id=subject.id, teacher_id=subject.teacher_id, date=sess_date,
                    token=secrets.token_hex(6),
                    created_at=datetime.combine(sess_date, datetime.min.time()) + timedelta(hours=10),
                    expires_at=datetime.combine(sess_date, datetime.min.time()) + timedelta(hours=10, minutes=5),
                    is_closed=True
                )
                db.session.add(sess)
                db.session.flush()
                for s in klass_students:
                    # everyone ~88% present, one deliberately low-attendance student
                    if dropout_student and s.id == dropout_student.id:
                        present = random.random() < 0.45
                    else:
                        present = random.random() < 0.88
                    if present:
                        via = random.choices(["qr", "failsafe"], weights=[0.85, 0.15])[0]
                        db.session.add(AttendanceRecord(
                            session_id=sess.id, student_id=s.id, status="present", marked_via=via,
                            timestamp=sess.created_at + timedelta(minutes=random.randint(0, 4))
                        ))

        for subj in [ds, os_, dm]:
            build_sessions(subj, students_a, dropout_student=students_a[2])  # Rohan Gupta struggles
        for subj in [db_sys, cn]:
            build_sessions(subj, students_b, dropout_student=students_b[4])  # Rahul Kapoor struggles

        # ---------------- announcements
        db.session.add(Announcement(class_id=cs2a.id, posted_by=t_rao.id,
                                     message="Mid-semester marks will be uploaded by Friday. Please check your submissions."))
        db.session.add(Announcement(class_id=cs2b.id, posted_by=t_khan.id,
                                     message="Lab timings for next week have shifted to 2-4 PM."))

        db.session.commit()

        print("Seed complete.")
        print("\nLogin with:")
        print("  Admin    -> admin@college.edu / admin123")
        print("  Teacher  -> meera.rao@college.edu / teach123  (coordinates B.Sc CS 2A)")
        print("  Teacher  -> imran.khan@college.edu / teach123  (coordinates B.Sc CS 2B)")
        print("  Student  -> CS2A001 / student123  (roll number as login id)")
        print("  Student  -> CS2A003 / student123  (Rohan Gupta - low attendance example)")


if __name__ == "__main__":
    run()
