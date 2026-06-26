"""Synthetic B2B customer master data for Brunnstein.

About 150 customers across four sales channels: a handful of named (fictional)
regional retail chains, plus Faker-generated gastronomy, wholesalers and
convenience accounts. Weighted towards southern Germany, where Brunnstein
sells most. Webshop B2C consumers are not part of this master table.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from uuid import uuid4

from faker import Faker

from data.erp.models import Customer, CustomerChannel

# Southern states carry more weight: that is Brunnstein's home market.
_REGIONS: list[tuple[str, int]] = [
    ("Bayern", 30),
    ("Baden-Württemberg", 25),
    ("Hessen", 10),
    ("Rheinland-Pfalz", 8),
    ("Nordrhein-Westfalen", 9),
    ("Sachsen", 5),
    ("Niedersachsen", 5),
    ("Berlin", 4),
    ("Thüringen", 3),
    ("Saarland", 1),
]

# Named regional retail chains (fictional). The rest of the book is generated.
_RETAIL_CHAINS: list[str] = [
    "Südmarkt Lebensmittel GmbH",
    "Alpenkauf Handels AG",
    "Frischeck Märkte GmbH",
    "Donau-Markt eG",
    "Tölzer Konsum eG",
    "Bayern Vollsortiment GmbH",
    "Schwarzwald Lebensmittel KG",
    "Allgäu Frische GmbH",
    "NahKauf Süd GmbH",
    "Genussmarkt Bodensee AG",
]

_GASTRO_SUFFIXES = [
    "Gastronomie GmbH",
    "Wirtshaus",
    "Hotelbetriebe GmbH",
    "Brauereigaststätten GmbH",
    "Eventcatering GmbH",
]
_WHOLESALE_SUFFIXES = ["Getränkegroßhandel GmbH", "Getränke-Logistik GmbH", "Cash & Carry GmbH"]
_CONVENIENCE_SUFFIXES = ["Tankstellenbetrieb GmbH", "Kiosk & Shop GmbH", "Bahnhofsmarkt GmbH"]

_CREDIT_LIMIT_BY_CHANNEL: dict[CustomerChannel, tuple[int, int]] = {
    CustomerChannel.retail_chain: (200_000, 800_000),
    CustomerChannel.gastronomy: (5_000, 40_000),
    CustomerChannel.wholesaler: (100_000, 500_000),
    CustomerChannel.convenience: (10_000, 60_000),
}

_PAYMENT_TERMS_BY_CHANNEL: dict[CustomerChannel, int] = {
    CustomerChannel.retail_chain: 45,
    CustomerChannel.gastronomy: 14,
    CustomerChannel.wholesaler: 30,
    CustomerChannel.convenience: 14,
}

# Target mix for ~150 accounts.
_CHANNEL_COUNTS: list[tuple[CustomerChannel, int]] = [
    (CustomerChannel.retail_chain, 20),
    (CustomerChannel.gastronomy, 85),
    (CustomerChannel.wholesaler, 20),
    (CustomerChannel.convenience, 25),
]

_INACTIVE_RATE = 0.06


def _vat_id(rng: random.Random) -> str:
    return "DE" + "".join(str(rng.randint(0, 9)) for _ in range(9))


def _region(rng: random.Random) -> str:
    names = [r for r, _ in _REGIONS]
    weights = [w for _, w in _REGIONS]
    return rng.choices(names, weights=weights, k=1)[0]


def _name(
    channel: CustomerChannel, faker: Faker, rng: random.Random, used_chains: list[str]
) -> str:
    if channel == CustomerChannel.retail_chain and used_chains:
        return used_chains.pop()
    place = faker.city()
    if channel == CustomerChannel.gastronomy:
        return f"{faker.last_name()} {rng.choice(_GASTRO_SUFFIXES)}"
    if channel == CustomerChannel.wholesaler:
        return f"{place} {rng.choice(_WHOLESALE_SUFFIXES)}"
    if channel == CustomerChannel.convenience:
        return f"{place} {rng.choice(_CONVENIENCE_SUFFIXES)}"
    return f"{place} Märkte GmbH"


def generate_customers(seed: int = 42) -> list[Customer]:
    faker = Faker("de_DE")
    Faker.seed(seed)
    rng = random.Random(seed)

    # Expand the channel mix into one entry per account, then shuffle so
    # customer numbers are not grouped by channel.
    channels: list[CustomerChannel] = []
    for channel, count in _CHANNEL_COUNTS:
        channels.extend([channel] * count)
    rng.shuffle(channels)

    chains = list(_RETAIL_CHAINS)
    rng.shuffle(chains)

    earliest = date(2014, 1, 1)
    span_days = (date(2024, 6, 1) - earliest).days

    customers: list[Customer] = []
    for i, channel in enumerate(channels, start=1):
        lo, hi = _CREDIT_LIMIT_BY_CHANNEL[channel]
        customers.append(
            Customer(
                id=uuid4(),
                customer_number=f"C-{100000 + i}",
                name=_name(channel, faker, rng, chains),
                channel=channel,
                region=_region(rng),
                street=faker.street_address(),
                postal_code=faker.postcode(),
                city=faker.city(),
                country="DE",
                vat_id=_vat_id(rng),
                payment_terms_days=_PAYMENT_TERMS_BY_CHANNEL[channel],
                credit_limit_eur=rng.randrange(lo, hi, 1000),
                active=rng.random() > _INACTIVE_RATE,
                onboarded_date=earliest + timedelta(days=rng.randint(0, span_days)),
            )
        )
    return customers
