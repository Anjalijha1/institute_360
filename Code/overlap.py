import re
from rapidfuzz import fuzz
from models import db, Case, CaseLink, Alert

ABBREVIATIONS = {"inst": "institute", "tech": "technology", "engg": "engineering",
                 "univ": "university", "coll": "college", "mgmt": "management"}
OPEN_STATUSES = ["Received", "Under Process", "Pending", "Transferred", "Escalated"]


def clean_name(name):
    name = re.sub(r"[^\w\s]", "", name.lower())  # remove dots, commas, etc.
    words = [ABBREVIATIONS.get(w, w) for w in name.split() if w != "the"]
    return " ".join(words)


def find_overlaps(case):
    """Return a list of (other_case, score, reason) for one case."""
    results = []
    if case.status not in OPEN_STATUSES:
        return results
    others = Case.query.filter(
        Case.id != case.id,
        Case.status.in_(OPEN_STATUSES),
        Case.current_bureau_id != case.current_bureau_id,
    ).all()
    for other in others:
        if other.institution_id == case.institution_id:
            results.append((other, 100, "Same Institution ID, different Bureaus/Cells"))
            continue
        a, b = case.institution, other.institution
        similarity = fuzz.token_set_ratio(clean_name(a.name), clean_name(b.name))
        if similarity >= 90 and a.city == b.city:
            score = 70 + int((similarity - 90) * 1.5)
            results.append((other, score, f"Similar institution names ({similarity}% match), same city"))
    return results


def run_overlap_check(case):
    for other, score, reason in find_overlaps(case):
        first, second = sorted([case.id, other.id])
        if CaseLink.query.filter_by(case_a_id=first, case_b_id=second).first():
            continue  # already linked (or dismissed by an officer)
        db.session.add(CaseLink(
            case_a_id=first, case_b_id=second, link_type="auto_overlap",
            match_score=score, reason=reason,
            review_state="confirmed" if score >= 90 else "suggested"))
        case.overlap_flag = True
        other.overlap_flag = True
        for c in (case, other):
            db.session.add(Alert(
                alert_type="overlap", case_id=c.id, institution_id=c.institution_id,
                target_bureau_id=c.current_bureau_id,
                message="Potential Overlapping Cases – Coordination Required",
                severity="high" if score >= 90 else "medium"))
    db.session.commit()