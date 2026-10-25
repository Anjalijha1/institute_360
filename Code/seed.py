import random
from datetime import date, datetime, time, timedelta

from faker import Faker
from werkzeug.security import generate_password_hash

from app import app
from models import db, Bureau, User, Institution, Case, CaseAction, CaseLink, Alert
from overlap import run_overlap_check

fake = Faker("en_IN")
random.seed(42)

BUREAUS = [
    ("RB", "Regulation Bureau"),
    ("PGRC", "Public Grievance Redressal Cell"),
    ("APB", "Approval Bureau (example)"),
    ("ACB", "Academic Bureau (example)"),
    ("FIN", "Finance Bureau (example)"),
]
CATEGORIES = {"Fee or refund": 30, "Faculty": 45, "Infrastructure": 45,
              "Approval or affiliation": 60, "Other": 30}
STATUSES = ["Received", "Under Process", "Pending", "Transferred", "Escalated", "Disposed"]
REGIONS = ["North", "South", "East", "West", "Central"]
KINDS = ["Institute of Technology", "College of Engineering",
         "Institute of Management", "College of Pharmacy"]

case_counter = 0


def make_case(inst, bureau, officer, category, status, received):
    global case_counter
    case_counter += 1
    when = datetime.combine(received, time(10, 0))
    last = min(when + timedelta(days=random.randint(0, 20)), datetime.now())
    case = Case(
        id=f"CMP-2026-{case_counter:04d}", institution_id=inst.id, category=category,
        description=fake.sentence(nb_words=14), received_on=received, status=status,
        current_bureau_id=bureau.id, assigned_officer_id=officer.id,
        last_action_summary=f"Case {status.lower()}", last_action_on=last,
        next_action_required="None" if status == "Disposed" else "Review and update",
        expected_disposal_on=received + timedelta(days=CATEGORIES[category]),
        is_escalated=(status == "Escalated"))
    db.session.add(case)
    db.session.add(CaseAction(case_id=case.id, action_type="received", to_bureau_id=bureau.id,
                              performed_by=officer.id, performed_at=when,
                              remarks="Complaint received"))
    if status == "Disposed":
        db.session.add(CaseAction(case_id=case.id, action_type="disposed",
                                  performed_by=officer.id, performed_at=last,
                                  remarks="Case closed"))
    return case


with app.app_context():
    db.drop_all()
    db.create_all()

    bureaus = [Bureau(code=c, name=n) for c, n in BUREAUS]
    db.session.add_all(bureaus)
    db.session.commit()
    by_code = {b.code: b for b in bureaus}

    pw = generate_password_hash("demo123")
    staff = [
        User(name="Admin", email="admin@demo.com", password_hash=pw, role="admin"),
        User(name="Senior Official", email="senior@demo.com", password_hash=pw, role="senior"),
        User(name="Regional Officer", email="regional@demo.com", password_hash=pw,
             role="regional", region="North"),
    ]
    officers = {}
    for b in bureaus:
        officers[b.id] = []
        for i in (1, 2):
            u = User(name=f"{b.code} Officer {i}", email=f"{b.code.lower()}{i}@demo.com",
                     password_hash=pw, role="officer", bureau_id=b.id)
            officers[b.id].append(u)
            staff.append(u)
    db.session.add_all(staff)
    db.session.commit()

    def pick_officer(b):
        return random.choice(officers[b.id])

    institutions = [
        Institution(id=f"1-{1000000 + i * 7919}",
                    name=f"{fake.last_name()} {random.choice(KINDS)}",
                    city=fake.city(), state=fake.state(), region=random.choice(REGIONS))
        for i in range(28)
    ]
    greenfield = Institution(id="1-9000003", name="Greenfield College of Engineering",
                             city="Jaipur", state="Rajasthan", region="West")
    abc1 = Institution(id="1-9000001", name="ABC Institute of Technology",
                       city="Lucknow", state="Uttar Pradesh", region="North")
    abc2 = Institution(id="1-9000002", name="A.B.C. Inst. of Tech.",
                       city="Lucknow", state="Uttar Pradesh", region="North")
    db.session.add_all(institutions + [greenfield, abc1, abc2])
    db.session.commit()

    # Each normal institution is handled by ONE home bureau, so overlaps only come from our planted demo cases.
    home = {inst.id: random.choice(bureaus) for inst in institutions}
    for _ in range(200):
        inst = random.choice(institutions)
        bureau = home[inst.id]
        make_case(inst, bureau, pick_officer(bureau), random.choice(list(CATEGORIES)),
                  random.choices(STATUSES, weights=[10, 30, 15, 10, 5, 30])[0],
                  date.today() - timedelta(days=random.randint(1, 150)))

    def recent():
        return date.today() - timedelta(days=random.randint(3, 20))

    rb, pgrc = by_code["RB"], by_code["PGRC"]
    make_case(greenfield, pgrc, pick_officer(pgrc), "Faculty", "Under Process", recent())
    make_case(greenfield, rb, pick_officer(rb), "Approval or affiliation", "Under Process", recent())
    make_case(abc1, rb, pick_officer(rb), "Infrastructure", "Under Process", recent())
    make_case(abc2, pgrc, pick_officer(pgrc), "Fee or refund", "Received", recent())
    db.session.commit()

    for case in Case.query.all():
        run_overlap_check(case)

    print("Cases:", Case.query.count())
    print("Overlap links:", CaseLink.query.count(), "(expected 2)")
    print("Alerts:", Alert.query.count(), "(expected 4)")