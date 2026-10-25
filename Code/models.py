from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class Bureau(db.Model):
    __tablename__ = "bureaus"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False)  # admin, officer, regional, senior
    bureau_id = db.Column(db.Integer, db.ForeignKey("bureaus.id"))
    region = db.Column(db.String(50))
    bureau = db.relationship("Bureau")


class Institution(db.Model):
    __tablename__ = "institutions"
    id = db.Column(db.String(20), primary_key=True)  # AICTE Permanent ID
    name = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    region = db.Column(db.String(50))
    cases = db.relationship("Case", backref="institution")


class Case(db.Model):
    __tablename__ = "cases"
    id = db.Column(db.String(30), primary_key=True)  # e.g. CMP-2026-0001
    institution_id = db.Column(db.String(20), db.ForeignKey("institutions.id"), nullable=False)
    category = db.Column(db.String(60))
    description = db.Column(db.Text)
    received_on = db.Column(db.Date)
    status = db.Column(db.String(30), default="Received")
    current_bureau_id = db.Column(db.Integer, db.ForeignKey("bureaus.id"))
    assigned_officer_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    last_action_summary = db.Column(db.String(200))
    last_action_on = db.Column(db.DateTime)
    next_action_required = db.Column(db.String(200))
    expected_disposal_on = db.Column(db.Date)
    is_escalated = db.Column(db.Boolean, default=False)
    overlap_flag = db.Column(db.Boolean, default=False)
    current_bureau = db.relationship("Bureau")
    officer = db.relationship("User")
    actions = db.relationship("CaseAction", backref="case", order_by="CaseAction.performed_at")


class CaseAction(db.Model):
    __tablename__ = "case_actions"
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.String(30), db.ForeignKey("cases.id"), nullable=False)
    action_type = db.Column(db.String(30))
    from_bureau_id = db.Column(db.Integer, db.ForeignKey("bureaus.id"))
    to_bureau_id = db.Column(db.Integer, db.ForeignKey("bureaus.id"))
    performed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    performed_at = db.Column(db.DateTime, default=datetime.utcnow)
    remarks = db.Column(db.Text)


class CaseLink(db.Model):
    __tablename__ = "case_links"
    id = db.Column(db.Integer, primary_key=True)
    case_a_id = db.Column(db.String(30), db.ForeignKey("cases.id"))
    case_b_id = db.Column(db.String(30), db.ForeignKey("cases.id"))
    link_type = db.Column(db.String(30))
    match_score = db.Column(db.Integer)
    reason = db.Column(db.String(250))
    review_state = db.Column(db.String(20), default="suggested")  # suggested, confirmed, dismissed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Alert(db.Model):
    __tablename__ = "alerts"
    id = db.Column(db.Integer, primary_key=True)
    alert_type = db.Column(db.String(30))
    case_id = db.Column(db.String(30), db.ForeignKey("cases.id"))
    institution_id = db.Column(db.String(20), db.ForeignKey("institutions.id"))
    target_bureau_id = db.Column(db.Integer, db.ForeignKey("bureaus.id"))
    message = db.Column(db.String(250))
    severity = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)