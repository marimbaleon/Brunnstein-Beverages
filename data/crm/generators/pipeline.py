"""Generate the CRM pipeline: leads, opportunities and sales activities.

Leads are worked by the sales reps in HR (employees in a sales org unit).
Opportunities chase either a converted lead (new logo) or an existing B2B
customer (expansion); their stage drives a win probability and a close date.
Activities (calls, visits, e-mails, meetings) are logged mostly against
opportunities, with some pure lead or account touches.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from faker import Faker

from data.crm.models import (
    ActivityType,
    Lead,
    LeadSource,
    LeadStatus,
    Opportunity,
    OpportunityStage,
    SalesActivity,
)
from data.erp.models import Customer

_REGIONS = [
    "Bayern", "Baden-Württemberg", "Hessen", "Rheinland-Pfalz",
    "Nordrhein-Westfalen", "Sachsen", "Niedersachsen", "Berlin",
]
_CHANNELS = ["retail_chain", "gastronomy", "wholesaler", "convenience"]
_COMPANY_SUFFIX = [
    "Getränke GmbH", "Gastronomie GmbH", "Handels AG", "Märkte GmbH",
    "Konsum eG", "Hotelbetriebe GmbH", "Cash & Carry GmbH",
]

_SOURCE_WEIGHTS = [
    (LeadSource.web_form, 26), (LeadSource.trade_fair, 22), (LeadSource.referral, 18),
    (LeadSource.cold_call, 20), (LeadSource.inbound_call, 14),
]
_STAGE_PROB = {
    OpportunityStage.prospecting: 10,
    OpportunityStage.qualification: 25,
    OpportunityStage.proposal: 50,
    OpportunityStage.negotiation: 75,
    OpportunityStage.won: 100,
    OpportunityStage.lost: 0,
}
_OPEN_STAGES = [
    OpportunityStage.prospecting, OpportunityStage.qualification,
    OpportunityStage.proposal, OpportunityStage.negotiation,
]
_ACTIVITY_SUBJECTS = {
    ActivityType.call: ["Erstkontakt telefonisch", "Rückruf zu Angebot", "Bedarf geklärt"],
    ActivityType.visit: ["Vor-Ort-Termin", "Sortimentsberatung", "Jahresgespräch"],
    ActivityType.email: ["Angebot versendet", "Konditionen nachgereicht", "Follow-up"],
    ActivityType.meeting: ["Verhandlungstermin", "Listungsgespräch", "Kick-off"],
}


def _date_in(rng: random.Random, start: date, end: date) -> date:
    span = max((end - start).days, 1)
    return start + timedelta(days=rng.randint(0, span))


def generate_leads(
    sales_employees: list,
    year_range: tuple[int, int],
    today: date,
    n: int,
    seed: int,
) -> list[Lead]:
    faker = Faker("de_DE")
    Faker.seed(seed)
    rng = random.Random(seed + 41)
    sources = [s for s, _ in _SOURCE_WEIGHTS]
    weights = [w for _, w in _SOURCE_WEIGHTS]
    start = date(year_range[0], 1, 1)

    leads: list[Lead] = []
    for i in range(1, n + 1):
        created = _date_in(rng, start, today)
        status = rng.choices(
            [LeadStatus.converted, LeadStatus.qualified, LeadStatus.lost, LeadStatus.new],
            weights=[28, 30, 27, 15], k=1,
        )[0]
        leads.append(Lead(
            id=uuid4(),
            lead_number=f"LD-{created.year}-{i:05d}",
            company_name=f"{faker.city()} {rng.choice(_COMPANY_SUFFIX)}",
            contact_name=faker.name(),
            email=faker.company_email(),
            region=rng.choice(_REGIONS),
            channel_hint=rng.choice(_CHANNELS),
            source=rng.choices(sources, weights=weights, k=1)[0],
            status=status,
            created_date=created,
            owner_employee_id=rng.choice(sales_employees).id,
            estimated_annual_volume_eur=Decimal(rng.randrange(10_000, 400_000, 5_000)),
        ))
    return leads


def generate_opportunities(
    leads: list[Lead],
    customers: list[Customer],
    sales_employees: list,
    today: date,
    seed: int,
) -> list[Opportunity]:
    rng = random.Random(seed + 43)
    opps: list[Opportunity] = []
    counter: dict[int, int] = defaultdict(int)

    def add(title, lead_id, customer_id, owner_id, created):
        # Closed (won/lost) for older opportunities; open for recent ones.
        age = (today - created).days
        if age > 90:
            stage = rng.choices([OpportunityStage.won, OpportunityStage.lost],
                                weights=[58, 42], k=1)[0]
        else:
            stage = rng.choice(_OPEN_STAGES)
        closed = None
        if stage in (OpportunityStage.won, OpportunityStage.lost):
            closed = created + timedelta(days=rng.randint(20, 120))
            if closed > today:
                closed = today
        year = created.year
        counter[year] += 1
        opps.append(Opportunity(
            id=uuid4(),
            opportunity_number=f"OP-{year}-{counter[year]:05d}",
            title=title,
            lead_id=lead_id,
            customer_id=customer_id,
            owner_employee_id=owner_id,
            stage=stage,
            amount_eur=Decimal(rng.randrange(8_000, 250_000, 1_000)),
            probability_pct=_STAGE_PROB[stage],
            created_date=created,
            expected_close_date=created + timedelta(days=rng.randint(30, 150)),
            closed_date=closed,
        ))

    # New-logo opportunities from qualified/converted leads.
    for lead in leads:
        if lead.status in (LeadStatus.qualified, LeadStatus.converted):
            created = lead.created_date + timedelta(days=rng.randint(3, 40))
            if created <= today:
                add(f"Neukunde {lead.company_name}", lead.id, None,
                    lead.owner_employee_id, created)

    # Expansion opportunities on a sample of existing customers.
    for customer in customers:
        if rng.random() < 0.18:
            created = _date_in(rng, date(today.year - 2, 1, 1), today)
            add(f"Ausbau {customer.name}", None, customer.id,
                rng.choice(sales_employees).id, created)

    return opps


def generate_activities(
    opportunities: list[Opportunity],
    leads: list[Lead],
    sales_employees: list,
    today: date,
    seed: int,
) -> list[SalesActivity]:
    rng = random.Random(seed + 45)
    types = list(_ACTIVITY_SUBJECTS)
    activities: list[SalesActivity] = []
    counter: dict[int, int] = defaultdict(int)

    def add(atype, subject, day, owner_id, customer_id, lead_id, opp_id):
        year = day.year
        counter[year] += 1
        activities.append(SalesActivity(
            id=uuid4(),
            activity_number=f"AC-{year}-{counter[year]:06d}",
            type=atype,
            subject=subject,
            activity_date=day,
            owner_employee_id=owner_id,
            customer_id=customer_id,
            lead_id=lead_id,
            opportunity_id=opp_id,
        ))

    # Several activities per opportunity across its life.
    for opp in opportunities:
        end = opp.closed_date or today
        for _ in range(rng.randint(2, 6)):
            day = _date_in(rng, opp.created_date, max(end, opp.created_date))
            atype = rng.choice(types)
            add(atype, rng.choice(_ACTIVITY_SUBJECTS[atype]), day,
                opp.owner_employee_id, opp.customer_id, opp.lead_id, opp.id)

    # A few standalone touches on leads that never became opportunities.
    for lead in leads:
        if lead.status == LeadStatus.new and rng.random() < 0.4:
            atype = rng.choice(types)
            add(atype, rng.choice(_ACTIVITY_SUBJECTS[atype]),
                _date_in(rng, lead.created_date, today),
                lead.owner_employee_id, None, lead.id, None)

    activities.sort(key=lambda a: a.activity_date)
    return activities
