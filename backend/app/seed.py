"""Deterministic synthetic dataset for Hososhi.

Every row produced here is fictional and generated from a fixed seed, so the
database can be rebuilt identically on any machine with one command:
    python -m app.seed
"""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import Base, SessionLocal, engine, init_db
from app.discovery import discover_and_persist
from app.models import (
    Decision,
    Employee,
    Incident,
    Policy,
    PurchaseRequest,
    Step,
    Supplier,
    WorkflowEvent,
)

settings = get_settings()

DEPARTMENTS = ["Engineering", "Operations", "Marketing", "Finance", "HR"]
CATEGORIES = ["Hardware", "Software", "Logistics", "Facilities", "Professional Services"]

FIRST_NAMES = [
    "Nigar", "Elvin", "Kamala", "Rashad", "Aysel", "Tural", "Zeynep", "Farid",
    "Leyla", "Orxan", "Gunay", "Samir", "Nargiz", "Eldar", "Vusala", "Toghrul",
    "Aysu", "Murad", "Sevinc", "Anar", "Ilkin", "Nigar", "Rena", "Bakhtiyar",
]
LAST_NAMES = [
    "Mammadov", "Aliyev", "Huseynov", "Rahimov", "Ismayilov", "Karimov",
    "Jabbarov", "Mustafayev", "Suleymanov", "Qasimov", "Abdullayev", "Nuriev",
]

# Ordered step actions for a normal purchase request. "submit_request" is the
# trigger event and is intentionally not part of the discovered 7-step workflow.
STEP_ACTIONS = [
    "extract_fields",
    "match_supplier",
    "verify_price",
    "evaluate_policy",
    "search_decisions",
    "approve_request",
    "create_po",
]

# Median handling minutes per action, used to space timestamps realistically.
HANDLING_MINUTES = {
    "extract_fields": (4, 9),
    "match_supplier": (6, 15),
    "verify_price": (5, 14),
    "evaluate_policy": (4, 11),
    "search_decisions": (8, 22),
    "approve_request": (25, 190),
    "create_po": (6, 16),
}

APPLICATIONS = ["Procurement Portal", "Finance Ledger", "Vendor Portal", "Email Intake"]

SUPPLIER_NAMES = [
    "Caspian Hardware", "Anbar Software", "Selcan Logistics", "Baku Facilities",
    "Orbit Professional", "Delta Components", "Nizami Office", "Vega Supply",
    "Azerbaijan Tech", "Piramida Services", "Sahil Shipping", "Kuzey Trading",
    "Merkezi Systems", "Gunes Industrial",
]

POLICIES = [
    ("POL-PR-01", "Purchase requests require a named cost centre",
     "Every purchase request must specify a cost centre before it can be approved.",
     "procurement", "high"),
    ("POL-PR-02", "Suppliers must be on the approved catalogue",
     "A purchase order may only be raised for a supplier present on the approved catalogue.",
     "procurement", "high"),
    ("POL-PR-03", "Price variance threshold is 10 percent",
     "A unit price more than 10 percent above the contracted catalogue price requires written justification.",
     "procurement", "medium"),
    ("POL-PR-04", "Orders above 5,000 USD require manager approval",
     "Any purchase request whose total amount is at or above 5,000 USD requires explicit manager approval.",
     "procurement", "high"),
    ("POL-PR-05", "Competitive quotes required above 2,000 USD",
     "Requests above 2,000 USD must reference at least two supplier quotes.",
     "procurement", "medium"),
    ("POL-PR-06", "Single-source purchases require a risk tier of low",
     "A purchase from a supplier rated medium or high risk requires additional review.",
     "procurement", "high"),
    ("POL-PR-07", "Historical decisions must be checked before approval",
     "The approver must search historical decisions for comparable requests before approving.",
     "procurement", "medium"),
    ("POL-PR-08", "Split requests are prohibited",
     "A request may not be split into multiple smaller requests to avoid the approval threshold.",
     "finance", "high"),
    ("POL-PR-09", "Purchase orders must reference an approved request",
     "A purchase order cannot be created without an approved purchase request record.",
     "finance", "high"),
    ("POL-PR-10", "Currency must match the contract currency",
     "Requests must be raised in the currency of the supplier contract.",
     "procurement", "low"),
]

DECISIONS = [
    ("DEC-101", "Approved sole-source renewal of Anbar Software",
     "Continuity of the finance platform outweighed the cost of a competitive process.",
     "approved"),
    ("DEC-102", "Rejected split request from Operations",
     "Splitting a request to stay under the approval threshold breaches POL-PR-08.",
     "rejected"),
    ("DEC-103", "Raised hardware approval threshold to 5,000 USD",
     "Managers were spending disproportionate time on low-value approvals.",
     "approved"),
    ("DEC-104", "Temporarily waived price variance check for Selcan Logistics",
     "Delivery delay risk was judged higher than a 14 percent price variance.",
     "approved"),
    ("DEC-105", "Required two quotes for all logistics spend",
     "Single-quote logistics purchases showed a higher dispute rate.",
     "approved"),
    ("DEC-106", "Escalated medium risk tier suppliers to department manager",
     "Medium risk suppliers were slipping through without human review.",
     "approved"),
    ("DEC-107", "Declined Delta Components contract extension",
     "Quality incidents outweighed a 6 percent price saving.",
     "rejected"),
    ("DEC-108", "Approved supplier list expansion for Engineering",
     "Engineering could not source test hardware from the existing catalogue.",
     "approved"),
    ("DEC-109", "Deferred the office furniture replacement programme",
     "Budget was redirected to infrastructure work.",
     "deferred"),
    ("DEC-110", "Adopted a standard price comparison method",
     "Comparisons were inconsistent because some staff used list price and others used net price.",
     "approved"),
    ("DEC-111", "Rejected purchase from a supplier in a restricted country",
     "Sanctions screening flagged the supplier country.",
     "rejected"),
    ("DEC-112", "Introduced a mandatory incident search before approval",
     "Two past incidents had originated from unreviewed supplier history.",
     "approved"),
]

INCIDENTS = [
    ("INC-38", "Purchase order raised without an approved request",
     "A purchase order was created directly in the finance ledger, bypassing approval. Led to POL-PR-09.",
     "high", "POL-PR-09", "DEC-101"),
    ("INC-41", "Price variance not detected on logistics invoice",
     "A 14 percent variance was accepted without justification, matching the DEC-104 waiver.",
     "medium", "POL-PR-03", "DEC-104"),
    ("INC-44", "Duplicate purchase request submitted by the requester",
     "The same request was submitted twice and processed twice, causing duplicate payment.",
     "medium", "POL-PR-01", None),
    ("INC-47", "Supplier not present on the approved catalogue",
     "An order was raised for an unregistered supplier, contrary to POL-PR-02.",
     "high", "POL-PR-02", "DEC-108"),
]


def money(rng: random.Random, low: int, high: int, round_to: int = 50) -> float:
    raw = rng.randint(low, high)
    return float(raw - raw % round_to)


def build_people(db, rng: random.Random) -> list[Employee]:
    employees = [
        Employee(
            id="emp_manager_01",
            name="Farid Mammadov",
            role="Department Manager",
            department="Operations",
            manager_id=None,
            email="farid.mammadov@example.invalid",
        )
    ]
    for index in range(1, 25):
        department = DEPARTMENTS[index % len(DEPARTMENTS)]
        role = "Department Manager" if index <= 3 else rng.choice(
            ["Procurement Specialist", "Employee", "Employee", "Finance Analyst"]
        )
        name = f"{FIRST_NAMES[index - 1]} {LAST_NAMES[(index * 3) % len(LAST_NAMES)]}"
        employees.append(
            Employee(
                id=f"emp_{index:03d}",
                name=name,
                role=role,
                department=department,
                manager_id="emp_manager_01",
                email=f"{FIRST_NAMES[index - 1].lower()}.{index}@example.invalid",
            )
        )
    db.add_all(employees)
    db.commit()
    return employees


def build_suppliers(db, rng: random.Random) -> list[Supplier]:
    suppliers = []
    for index, name in enumerate(SUPPLIER_NAMES, start=1):
        suppliers.append(
            Supplier(
                id=f"sup_{index:03d}",
                name=name,
                category=CATEGORIES[index % len(CATEGORIES)],
                risk_tier=rng.choice(["low", "low", "medium", "high"]),
                contract_ref=f"CTR-{2026}-{index:04d}",
                country=rng.choice(
                    ["Azerbaijan", "Türkiye", "Germany", "UAE", "Netherlands"]
                ),
            )
        )
    db.add_all(suppliers)
    db.commit()
    return suppliers


def build_policies(db, rng: random.Random, window_start: datetime) -> list[Policy]:
    policies = [
        Policy(
            id=pid,
            title=title,
            rule=rule,
            effective_date=window_start + timedelta(days=rng.randint(-30, 30)),
            department=department,
            severity=severity,
        )
        for pid, title, rule, department, severity in POLICIES
    ]
    db.add_all(policies)
    db.commit()
    return policies


def build_decisions(db, rng: random.Random, window_start: datetime) -> list[Decision]:
    decisions = []
    for offset, (did, title, reason, outcome) in enumerate(DECISIONS):
        decisions.append(
            Decision(
                id=did,
                title=title,
                date=window_start + timedelta(days=rng.randint(5, 170)),
                reason=reason,
                participants=[f"emp_{rng.randint(1, 24):03d}" for _ in range(rng.randint(2, 4))],
                evidence=[f"POL-PR-{rng.randint(1, 10):02d}"],
                outcome=outcome,
            )
        )
    db.add_all(decisions)
    db.commit()
    return decisions


def build_incidents(db, rng: random.Random, window_start: datetime) -> list[Incident]:
    incidents = [
        Incident(
            id=iid,
            title=title,
            date=window_start + timedelta(days=rng.randint(30, 175)),
            severity=severity,
            impact=impact,
            linked_policy_id=policy_id,
            linked_decision_id=decision_id,
        )
        for iid, title, impact, severity, policy_id, decision_id in INCIDENTS
    ]
    db.add_all(incidents)
    db.commit()
    return incidents


def build_requests_and_events(
    db,
    rng: random.Random,
    employees: list[Employee],
    suppliers: list[Supplier],
    window_start: datetime,
) -> None:
    requesters = [e for e in employees if e.id != "emp_manager_01"]
    requests: list[PurchaseRequest] = []
    events: list[WorkflowEvent] = []
    event_counter = 0

    def add_event(
        timestamp: datetime,
        employee_id: str | None,
        action: str,
        entity: str,
        entity_id: str,
        request_id: str,
        metadata: dict,
    ) -> None:
        nonlocal event_counter
        event_counter += 1
        events.append(
            WorkflowEvent(
                id=f"evt_{event_counter:05d}",
                timestamp=timestamp,
                employee_id=employee_id,
                application=metadata.pop("application", "Procurement Portal"),
                action=action,
                entity=entity,
                entity_id=entity_id,
                request_id=request_id,
                metadata_json=metadata,
            )
        )

    def build_sequence(
        request: PurchaseRequest,
        start: datetime,
        supplier: Supplier | None,
        omit: set[str] | None = None,
        noise_action: str | None = None,
    ) -> None:
        omit = omit or set()
        specialist = next(
            (e for e in employees if e.role == "Procurement Specialist"),
            requesters[0],
        )
        cursor = start
        add_event(
            cursor,
            request.employee_id,
            "submit_request",
            "purchase_request",
            request.id,
            request.id,
            {
                "application": "Procurement Portal",
                "amount": request.amount,
                "item_count": len(request.items or []),
                "supplier_supplied": supplier is not None,
            },
        )

        entity_map = {
            "extract_fields": "extraction",
            "match_supplier": "supplier_match",
            "verify_price": "price_check",
            "evaluate_policy": "policy_check",
            "search_decisions": "decision_search",
            "approve_request": "approval",
            "create_po": "purchase_order",
        }

        for action in STEP_ACTIONS:
            low, high = HANDLING_MINUTES[action]
            cursor = cursor + timedelta(minutes=rng.randint(low, high))
            if action in omit:
                continue

            if noise_action and action == noise_action:
                # Duplicate action within the same sequence: discovery must consolidate it.
                add_event(
                    cursor,
                    specialist.id,
                    action,
                    entity_map[action],
                    request.id,
                    request.id,
                    {"application": "Procurement Portal", "retry": True, "attempt": 2},
                )
                cursor = cursor + timedelta(minutes=rng.randint(2, 6))
                add_event(
                    cursor,
                    specialist.id,
                    action,
                    entity_map[action],
                    request.id,
                    request.id,
                    {"application": "Procurement Portal", "retry": True, "attempt": 3},
                )
                continue

            if action == "match_supplier" and supplier is not None:
                add_event(
                    cursor,
                    specialist.id,
                    action,
                    entity_map[action],
                    supplier.id,
                    request.id,
                    {
                        "application": "Vendor Portal",
                        "matched_supplier_id": supplier.id,
                        "match_confidence": round(rng.uniform(0.72, 0.99), 3),
                    },
                )
            elif action == "verify_price":
                catalogue = round(
                    request.amount / max(len(request.items or [1]), 1) * rng.uniform(0.88, 1.02), 2
                )
                # The unusual_price scenario must actually breach POL-PR-03 (10 percent),
                # otherwise the seeded scenario does not represent what it claims.
                variance_range = (1.22, 1.45) if request.scenario_tag == "unusual_price" else (0.95, 1.09)
                requested = round(catalogue * rng.uniform(*variance_range), 2)
                add_event(
                    cursor,
                    specialist.id,
                    action,
                    entity_map[action],
                    request.id,
                    request.id,
                    {
                        "application": "Finance Ledger",
                        "requested_unit_price": requested,
                        "catalogue_unit_price": catalogue,
                        "variance_percent": round((requested / catalogue - 1) * 100, 2),
                    },
                )
            elif action == "evaluate_policy":
                add_event(
                    cursor,
                    specialist.id,
                    action,
                    entity_map[action],
                    request.id,
                    request.id,
                    {
                        "application": "Procurement Portal",
                        "policies_evaluated": ["POL-PR-02", "POL-PR-04", "POL-PR-07"],
                        "violations": [],
                    },
                )
            elif action == "search_decisions":
                add_event(
                    cursor,
                    specialist.id,
                    action,
                    entity_map[action],
                    request.id,
                    request.id,
                    {
                        "application": "Procurement Portal",
                        "hits": rng.randint(1, 6),
                        "decision_ids": [f"DEC-{rng.randint(101, 112)}"],
                    },
                )
            elif action == "approve_request":
                add_event(
                    cursor,
                    "emp_manager_01",
                    action,
                    entity_map[action],
                    request.id,
                    request.id,
                    {
                        "application": "Email Intake",
                        "decision": "approve" if request.status == "approved" else "reject",
                        "approver_id": "emp_manager_01",
                    },
                )
            elif action == "create_po":
                # A rejected request never reaches PO creation in the observed data.
                if request.status != "approved":
                    break
                add_event(
                    cursor,
                    specialist.id,
                    action,
                    entity_map[action],
                    f"po_hist_{request.id}",
                    request.id,
                    {"application": "Finance Ledger", "amount": request.amount},
                )
            else:
                add_event(
                    cursor,
                    specialist.id,
                    action,
                    entity_map[action],
                    request.id,
                    request.id,
                    {"application": "Procurement Portal"},
                )

    # Scenarios for TEST-002..TEST-007. Tags are stored on the request row.
    scenarios = [
        ("duplicate_request", "submit same request twice"),
        ("missing_supplier", "supplier cannot be identified"),
        ("unusual_price", "unit price far above catalogue"),
        ("missing_information", "cost centre and quantity incomplete"),
        ("conflicting_policies", "price waiver conflicts with approval rule"),
        ("ambiguous_decision", "historical search returns contradictory guidance"),
    ]

    total_requests = 42
    for index in range(total_requests):
        requester = requesters[index % len(requesters)]
        supplier = suppliers[index % len(suppliers)] if rng.random() > 0.12 else None
        amount = money(rng, 300, 14000)
        item_count = rng.randint(1, 6)
        status = "approved" if rng.random() > 0.18 else "rejected"
        day_offset = int((index / total_requests) * 180) + rng.randint(0, 2)
        start = window_start + timedelta(days=day_offset, hours=rng.randint(8, 17))

        scenario_tag = scenarios[index % len(scenarios)][0] if index < 12 else None

        omit: set[str] = set()
        noise_action = None
        if scenario_tag == "missing_supplier":
            # Resolve the scenario before the row is built, so the request itself
            # carries no supplier rather than only its event sequence lacking one.
            supplier = None
            omit.add("match_supplier")
            omit.add("create_po")

        request = PurchaseRequest(
            id=f"pr_{index + 1:04d}",
            employee_id=requester.id,
            department=requester.department,
            items=[
                {
                    "description": f"{rng.choice(CATEGORIES)} item {n + 1}",
                    "quantity": rng.randint(1, 20),
                    "unit_price": round(amount / max(item_count, 1), 2),
                }
                for n in range(item_count)
            ],
            supplier_id=supplier.id if supplier else None,
            amount=amount,
            currency="USD",
            status=status,
            created_at=start,
            scenario_tag=scenario_tag,
        )
        requests.append(request)

        if scenario_tag == "unusual_price":
            omit.add("create_po")
        elif scenario_tag == "unusual_price":
            omit.add("create_po")
        elif scenario_tag == "missing_information":
            omit.add("extract_fields")
            omit.add("create_po")
        elif scenario_tag == "conflicting_policies":
            omit.add("create_po")
        elif scenario_tag == "ambiguous_decision":
            omit.add("create_po")
        elif scenario_tag == "duplicate_request":
            noise_action = "verify_price"
            omit.add("create_po")

        db.add(request)
        db.commit()
        build_sequence(request, start, supplier, omit=omit, noise_action=noise_action)

        if scenario_tag == "duplicate_request":
            db.add(
                PurchaseRequest(
                    id=f"{request.id}_dup",
                    employee_id=requester.id,
                    department=requester.department,
                    items=request.items,
                    supplier_id=request.supplier_id,
                    amount=request.amount,
                    currency="USD",
                    status="submitted",
                    created_at=start + timedelta(minutes=rng.randint(10, 90)),
                    scenario_tag="duplicate_of_" + request.id,
                )
            )

    db.add_all(events)
    db.commit()


def main() -> None:
    rng = random.Random(settings.dataset_seed)
    window_start = datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc)

    Base.metadata.drop_all(bind=engine)
    init_db()

    with SessionLocal() as db:
        for model in (
            WorkflowEvent,
            Decision,
            Incident,
            Policy,
            PurchaseRequest,
            Supplier,
            Employee,
        ):
            db.execute(delete(model))
        db.commit()

        employees = build_people(db, rng)
        suppliers = build_suppliers(db, rng)
        build_policies(db, rng, window_start)
        build_decisions(db, rng, window_start)
        build_incidents(db, rng, window_start)
        build_requests_and_events(db, rng, employees, suppliers, window_start)

        workflow = discover_and_persist(db)

        from sqlalchemy import func, select

        event_count = db.scalar(select(func.count()).select_from(WorkflowEvent))
        step_count = db.scalar(select(func.count()).select_from(Step))
        request_count = db.scalar(select(func.count()).select_from(PurchaseRequest))

    print("Seed complete (synthetic data, fixed seed).")
    print(f"  seed              : {settings.dataset_seed}")
    print(f"  purchase requests : {request_count}")
    print(f"  workflow events   : {event_count}")
    print(f"  workflows         : 1 ({workflow.id})")
    print(f"  steps discovered  : {step_count}")
    print(f"  confidence        : {workflow.confidence}")
    print(f"  date range        : {workflow.date_range}")


if __name__ == "__main__":
    main()