from datetime import datetime, date, timedelta

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, current_user
from sqlalchemy import event, or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

from models import db, User, Case, CaseAction, CaseLink, Institution, Bureau
from overlap import run_overlap_check

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-before-demo"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///complaints.db"
db.init_app(app)

# LoginManager is the part of Flask-Login that keeps track of who is logged in.
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"  # the page people are sent to if not logged in


@login_manager.user_loader
def load_user(user_id):
    # After login, the browser keeps a small note (a "cookie") containing
    # only your user id number. On every page visit, Flask-Login calls this
    # function to turn that number back into your full User row.
    return db.session.get(User, int(user_id))


@app.before_request
def require_login():
    # This runs before EVERY page, so one rule protects the whole site.
    # Only the login page and static files (CSS, images) are open to
    # people who are not logged in.
    if request.endpoint in ("login", "static"):
        return None
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    return None


# ---------------------------------------------------------------------------
# Action history is permanent.
# These two "guards" stop ANY code from changing or deleting a CaseAction row
# once it has been saved. New rows can still be added.
# ---------------------------------------------------------------------------
@event.listens_for(CaseAction, "before_update")
def block_action_update(mapper, connection, target):
    raise RuntimeError("Case history is permanent and cannot be edited.")


@event.listens_for(CaseAction, "before_delete")
def block_action_delete(mapper, connection, target):
    raise RuntimeError("Case history is permanent and cannot be deleted.")


@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    # Already logged in? No need to see the login page again.
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        # Passwords are stored "hashed" (scrambled so they can't be read back).
        # check_password_hash scrambles what was typed and compares the result.
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))

        flash("Wrong email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    # Placeholder page for now.
    return render_template("dashboard.html")


def parse_date(text):
    # Turns text like "2026-03-15" (what the date boxes send) into a real date.
    # If the text is empty or wrong, we return None and simply ignore it.
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


@app.route("/cases")
def cases():
    # 1. Read what the person typed or picked in the filter form.
    #    These come from the address bar, e.g. /cases?status=Received&page=2
    f = {
        "institution": request.args.get("institution", "").strip(),
        "institution_id": request.args.get("institution_id", "").strip(),
        "case_id": request.args.get("case_id", "").strip(),
        "bureau": request.args.get("bureau", "").strip(),
        "region": request.args.get("region", "").strip(),
        "category": request.args.get("category", "").strip(),
        "status": request.args.get("status", "").strip(),
        "date_from": request.args.get("date_from", "").strip(),
        "date_to": request.args.get("date_to", "").strip(),
    }
    page = request.args.get("page", 1, type=int)

    # 2. Start with ALL cases, joined with their institution
    #    (a "join" glues each case to its institution row so we can
    #    search by the institution's name, ID and region).
    query = Case.query.join(Institution)

    # 3. Narrow the list down, one filter at a time, only if it was filled in.
    #    ilike means "contains this text, ignoring capital letters".
    if f["institution"]:
        query = query.filter(Institution.name.ilike(f"%{f['institution']}%"))
    if f["institution_id"]:
        query = query.filter(Institution.id.ilike(f"%{f['institution_id']}%"))
    if f["case_id"]:
        query = query.filter(Case.id.ilike(f"%{f['case_id']}%"))
    if f["bureau"].isdigit():
        query = query.filter(Case.current_bureau_id == int(f["bureau"]))
    if f["region"]:
        query = query.filter(Institution.region == f["region"])
    if f["category"]:
        query = query.filter(Case.category == f["category"])
    if f["status"]:
        query = query.filter(Case.status == f["status"])

    date_from = parse_date(f["date_from"])
    date_to = parse_date(f["date_to"])
    if date_from:
        query = query.filter(Case.received_on >= date_from)
    if date_to:
        query = query.filter(Case.received_on <= date_to)

    # 4. Newest cases first, then cut the list into pages of 20.
    pagination = query.order_by(Case.received_on.desc(), Case.id).paginate(
        page=page, per_page=20, error_out=False
    )

    # 5. Fill the dropdown boxes with the real values found in the database.
    bureaus = Bureau.query.order_by(Bureau.name).all()
    regions = [
        row[0]
        for row in db.session.query(Institution.region)
        .filter(Institution.region.isnot(None))
        .distinct()
        .order_by(Institution.region)
    ]
    categories = [
        row[0]
        for row in db.session.query(Case.category)
        .filter(Case.category.isnot(None))
        .distinct()
        .order_by(Case.category)
    ]
    statuses = [
        row[0]
        for row in db.session.query(Case.status)
        .filter(Case.status.isnot(None))
        .distinct()
        .order_by(Case.status)
    ]

    # 6. Only the filters that were actually filled in. The page-number links
    #    use these so that going to page 2 keeps your filters.
    active_filters = {key: value for key, value in f.items() if value}

    return render_template(
        "cases.html",
        pagination=pagination,
        f=f,
        active_filters=active_filters,
        bureaus=bureaus,
        regions=regions,
        categories=categories,
        statuses=statuses,
    )


# ---------------------------------------------------------------------------
# CASE DETAIL PAGE
# ---------------------------------------------------------------------------

# The statuses offered in the "change status" box. Any status that already
# exists in your database is added to this list automatically.
DEFAULT_STATUSES = ["Received", "Under Review", "Action Taken", "Pending Information", "Closed"]


def status_choices():
    in_database = [
        row[0]
        for row in db.session.query(Case.status).filter(Case.status.isnot(None)).distinct()
    ]
    return sorted(set(DEFAULT_STATUSES) | set(in_database))


def add_action(case, action_type, summary, remarks=None, from_bureau_id=None, to_bureau_id=None):
    # Every form uses this one helper, so every change is recorded the same way:
    #   1. a NEW row in the history (who, when, from/to bureau, remarks)
    #   2. the case's "last action" fields are refreshed
    # It does not save anything by itself; the caller saves with db.session.commit().
    now = datetime.utcnow()
    db.session.add(
        CaseAction(
            case_id=case.id,
            action_type=action_type,
            from_bureau_id=from_bureau_id,
            to_bureau_id=to_bureau_id,
            performed_by=current_user.id,
            performed_at=now,
            remarks=remarks or None,
        )
    )
    case.last_action_summary = summary[:200]  # the column holds at most 200 characters
    case.last_action_on = now


@app.route("/cases/<case_id>")
def case_detail(case_id):
    # If there is no case with this ID, Flask shows a "Not Found" page.
    case = db.get_or_404(Case, case_id)

    # Find links where this case is on either side, ignoring dismissed ones.
    links = (
        CaseLink.query.filter(
            or_(CaseLink.case_a_id == case.id, CaseLink.case_b_id == case.id),
            CaseLink.review_state != "dismissed",
        )
        .order_by(CaseLink.match_score.desc())
        .all()
    )

    # For each link, pick out the OTHER case (the one that isn't this page's case).
    linked_cases = []
    for link in links:
        other_id = link.case_b_id if link.case_a_id == case.id else link.case_a_id
        other = db.session.get(Case, other_id)
        if other:
            linked_cases.append({"link": link, "case": other})

    # The history table only stores id numbers for people and bureaus.
    # These lookups turn an id number into a name for display.
    bureau_names = {b.id: b.name for b in Bureau.query.all()}
    user_names = {u.id: u.name for u in User.query.all()}

    return render_template(
        "case_detail.html",
        case=case,
        linked_cases=linked_cases,
        bureaus=Bureau.query.order_by(Bureau.name).all(),
        bureau_names=bureau_names,
        user_names=user_names,
        statuses=status_choices(),
    )


@app.route("/cases/<case_id>/remark", methods=["POST"])
def add_remark(case_id):
    case = db.get_or_404(Case, case_id)
    remark = request.form.get("remarks", "").strip()

    if not remark:
        flash("Please type a remark first.", "danger")
        return redirect(url_for("case_detail", case_id=case.id))

    add_action(case, "Remark", f"Remark added: {remark}", remarks=remark)
    db.session.commit()
    flash("Remark added.", "success")
    return redirect(url_for("case_detail", case_id=case.id))


@app.route("/cases/<case_id>/status", methods=["POST"])
def change_status(case_id):
    case = db.get_or_404(Case, case_id)
    new_status = request.form.get("status", "").strip()
    remark = request.form.get("remarks", "").strip()

    if new_status not in status_choices():
        flash("Please choose a status from the list.", "danger")
        return redirect(url_for("case_detail", case_id=case.id))
    if new_status == case.status:
        flash("The case already has that status.", "info")
        return redirect(url_for("case_detail", case_id=case.id))

    old_status = case.status or "none"
    case.status = new_status
    add_action(
        case,
        "Status change",
        f"Status changed from {old_status} to {new_status}",
        remarks=remark,
    )
    db.session.commit()
    flash(f"Status changed to {new_status}.", "success")
    return redirect(url_for("case_detail", case_id=case.id))


@app.route("/cases/<case_id>/transfer", methods=["POST"])
def transfer_case(case_id):
    case = db.get_or_404(Case, case_id)
    to_id = request.form.get("to_bureau", "").strip()
    remark = request.form.get("remarks", "").strip()

    new_bureau = db.session.get(Bureau, int(to_id)) if to_id.isdigit() else None
    if new_bureau is None:
        flash("Please choose a Bureau / Cell to transfer to.", "danger")
        return redirect(url_for("case_detail", case_id=case.id))
    if new_bureau.id == case.current_bureau_id:
        flash("The case is already with that Bureau / Cell.", "info")
        return redirect(url_for("case_detail", case_id=case.id))

    old_bureau_id = case.current_bureau_id
    old_bureau_name = case.current_bureau.name if case.current_bureau else "none"

    case.current_bureau_id = new_bureau.id
    add_action(
        case,
        "Transfer",
        f"Transferred from {old_bureau_name} to {new_bureau.name}",
        remarks=remark,
        from_bureau_id=old_bureau_id,
        to_bureau_id=new_bureau.id,
    )
    db.session.commit()  # the transfer is saved first, so it is never lost

    # Now look for overlapping cases. This is done AFTER saving, so even if
    # the overlap check has a problem, the transfer itself is safe.
    try:
        run_overlap_check(case)
        db.session.commit()
        flash(f"Case transferred to {new_bureau.name}. Overlap check done.", "success")
    except Exception as error:
        db.session.rollback()
        flash(
            f"Case transferred to {new_bureau.name}, but the overlap check failed: {error}",
            "warning",
        )

    return redirect(url_for("case_detail", case_id=case.id))


@app.route("/cases/<case_id>/escalate", methods=["POST"])
def escalate_case(case_id):
    case = db.get_or_404(Case, case_id)
    remark = request.form.get("remarks", "").strip()

    if case.is_escalated:
        flash("This case is already escalated.", "info")
        return redirect(url_for("case_detail", case_id=case.id))
    if not remark:
        flash("Please give a reason for escalating.", "danger")
        return redirect(url_for("case_detail", case_id=case.id))

    case.is_escalated = True
    add_action(case, "Escalation", f"Escalated: {remark}", remarks=remark)
    db.session.commit()
    flash("Case escalated.", "success")
    return redirect(url_for("case_detail", case_id=case.id))


# ---------------------------------------------------------------------------
# NEW CASE PAGE
# ---------------------------------------------------------------------------

# How many days each category is given before the case should be disposed of.
CATEGORY_DAYS = {
    "Fee": 30,
    "Faculty": 45,
    "Infrastructure": 45,
    "Approval": 60,
    "Other": 30,
}


def next_case_id(year):
    # Case IDs look like CMP-2026-0001. We find the highest number already
    # used this year and add 1. The ":04d" part pads the number with zeros
    # so it always has 4 digits (7 becomes 0007).
    prefix = f"CMP-{year}-"
    last = (
        Case.query.filter(Case.id.like(f"{prefix}%"))
        .order_by(Case.id.desc())
        .first()
    )
    number = 1
    if last:
        try:
            number = int(last.id.rsplit("-", 1)[1]) + 1
        except ValueError:
            number = Case.query.filter(Case.id.like(f"{prefix}%")).count() + 1
    return f"{prefix}{number:04d}"


@app.route("/cases/new", methods=["GET", "POST"])
def new_case():
    institutions = Institution.query.order_by(Institution.name).all()
    bureaus = Bureau.query.order_by(Bureau.name).all()

    # What the boxes on the form start with. On a first visit they are empty
    # (the date starts as today). After a mistake, they keep what you typed.
    form = {
        "institution_id": "",
        "category": "",
        "description": "",
        "received_on": date.today().isoformat(),
        "bureau": "",
    }

    if request.method == "POST":
        for key in form:
            form[key] = request.form.get(key, "").strip()

        institution = db.session.get(Institution, form["institution_id"]) if form["institution_id"] else None
        received_on = parse_date(form["received_on"])

        # The case goes to the logged-in officer's own Bureau / Cell.
        # If this account has no Bureau (an admin, for example), the form
        # shows a dropdown and we use the one that was chosen.
        if current_user.bureau_id:
            bureau_id = current_user.bureau_id
        elif form["bureau"].isdigit() and db.session.get(Bureau, int(form["bureau"])):
            bureau_id = int(form["bureau"])
        else:
            bureau_id = None

        # Check everything and stop at the first problem.
        problem = None
        if institution is None:
            problem = "Please choose an institution."
        elif form["category"] not in CATEGORY_DAYS:
            problem = "Please choose a category."
        elif not form["description"]:
            problem = "Please describe the complaint."
        elif received_on is None:
            problem = "Please enter a valid received date."
        elif received_on > date.today():
            problem = "The received date cannot be in the future."
        elif bureau_id is None:
            problem = "Please choose a Bureau / Cell."

        if problem:
            flash(problem, "danger")
            return render_template(
                "case_new.html",
                form=form,
                institutions=institutions,
                bureaus=bureaus,
                category_days=CATEGORY_DAYS,
            )

        # Build the new case. We try up to 3 times, in case two people
        # save at the same moment and both pick the same number.
        expected_disposal_on = received_on + timedelta(days=CATEGORY_DAYS[form["category"]])
        case = None
        for _ in range(3):
            candidate = Case(
                id=next_case_id(datetime.utcnow().year),
                institution_id=institution.id,
                category=form["category"],
                description=form["description"],
                received_on=received_on,
                status="Received",
                current_bureau_id=bureau_id,
                expected_disposal_on=expected_disposal_on,
                is_escalated=False,
                overlap_flag=False,
            )
            db.session.add(candidate)
            try:
                db.session.flush()  # sends it to the database to check the ID is free
            except IntegrityError:
                db.session.rollback()
                continue
            case = candidate
            break

        if case is None:
            flash("Could not create the case. Please press Save again.", "danger")
            return render_template(
                "case_new.html",
                form=form,
                institutions=institutions,
                bureaus=bureaus,
                category_days=CATEGORY_DAYS,
            )

        # First line of the case history: "Received", with the Bureau it went to.
        add_action(
            case,
            "Received",
            "Case received and registered",
            remarks="Case registered.",
            to_bureau_id=bureau_id,
        )
        db.session.commit()  # the case is saved first, so it is never lost

        # Now look for overlapping cases (same idea as after a transfer).
        try:
            run_overlap_check(case)
            db.session.commit()
            flash(f"Case {case.id} created. Overlap check done.", "success")
        except Exception as error:
            db.session.rollback()
            flash(
                f"Case {case.id} created, but the overlap check failed: {error}",
                "warning",
            )

        return redirect(url_for("case_detail", case_id=case.id))

    return render_template(
        "case_new.html",
        form=form,
        institutions=institutions,
        bureaus=bureaus,
        category_days=CATEGORY_DAYS,
    )


if __name__ == "__main__":
    app.run(debug=True)