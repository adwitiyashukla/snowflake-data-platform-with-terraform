import random
import uuid
from datetime import datetime, timedelta

PLANS = [("free", 0, 55), ("starter", 2900, 25), ("growth", 9900, 15), ("scale", 29900, 5)]
PLAN_PRICE = {name: price for name, price, _ in PLANS}
PLAN_ORDER = [name for name, _, _ in PLANS]
PLAN_USERS = {"free": 3, "starter": 8, "growth": 25, "scale": 80}
PLAN_ACTIVE = {"free": 0.25, "starter": 0.6, "growth": 0.85, "scale": 0.95}

COUNTRIES = [
    ("US", 45, -5),
    ("GB", 10, 0),
    ("DE", 8, 1),
    ("CA", 7, -5),
    ("IN", 8, 5),
    ("FR", 5, 1),
    ("AU", 5, 10),
    ("BR", 4, -3),
    ("NL", 3, 1),
    ("SE", 2, 1),
    ("ES", 3, 1),
]
PAGES = ["/", "/boards", "/docs", "/inbox", "/reports", "/settings", "/search", "/billing"]
FEATURES = ["boards", "docs", "search", "export", "automations", "api", "reports", "comments"]
DEVICES = [("desktop", 70), ("mobile", 25), ("tablet", 5)]
USER_AGENTS = {
    "desktop": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0",
    ],
    "mobile": [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) Mobile/15E148",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/128.0 Mobile",
    ],
    "tablet": ["Mozilla/5.0 (iPad; CPU OS 17_6 like Mac OS X) Mobile/15E148"],
}
FIRST_NAMES = [
    "Aarav",
    "Mia",
    "Noah",
    "Priya",
    "Liam",
    "Sofia",
    "Ethan",
    "Zara",
    "Lucas",
    "Emma",
    "Kai",
    "Ana",
    "Omar",
    "Lena",
    "Rohan",
    "Chloe",
    "Felix",
    "Nina",
    "Diego",
    "Ava",
]
LAST_NAMES = [
    "Shukla",
    "Garcia",
    "Muller",
    "Smith",
    "Patel",
    "Nguyen",
    "Silva",
    "Kim",
    "Rossi",
    "Brown",
    "Larsen",
    "Dubois",
    "Novak",
    "Okafor",
    "Tanaka",
    "Jones",
    "Costa",
    "Meyer",
    "Khan",
    "Lee",
]
DOMAIN_WORDS = [
    "north",
    "pixel",
    "quill",
    "harbor",
    "atlas",
    "ember",
    "lumen",
    "orbit",
    "vale",
    "moss",
]
LOCALES = {
    "US": "en-US",
    "GB": "en-GB",
    "DE": "de-DE",
    "CA": "en-CA",
    "IN": "en-IN",
    "FR": "fr-FR",
    "AU": "en-AU",
    "BR": "pt-BR",
    "NL": "nl-NL",
    "SE": "sv-SE",
    "ES": "es-ES",
}


def weighted(rng, options):
    total = sum(weight for _, weight in options)
    pick = rng.uniform(0, total)
    for value, weight in options:
        pick -= weight
        if pick <= 0:
            return value
    return options[-1][0]


def new_id(rng):
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


class Simulation:
    def __init__(self, seed, start_date, days, orgs, duplicate_rate, schema_v2_from_day):
        self.rng = random.Random(seed)
        self.start = datetime(start_date.year, start_date.month, start_date.day)
        self.days = days
        self.duplicate_rate = duplicate_rate
        self.schema_v2_from_day = schema_v2_from_day
        self.user_seq = 0
        self.pending_duplicates = []
        self.orgs = [self.make_org(i) for i in range(orgs)]

    def make_org(self, index):
        rng = self.rng
        plan = weighted(rng, [(name, weight) for name, _, weight in PLANS])
        country, _, offset = COUNTRIES[
            weighted(rng, [(i, w) for i, (_, w, _) in enumerate(COUNTRIES)])
        ]
        domain = f"{rng.choice(DOMAIN_WORDS)}{rng.choice(DOMAIN_WORDS)}{rng.randrange(10, 99)}.com"
        if rng.random() < 0.6:
            created = self.start + timedelta(seconds=rng.randrange(0, 3600))
        else:
            created = self.start + timedelta(seconds=rng.randrange(0, self.days * 86400))
        org = {
            "org_id": f"org_{index:05d}",
            "plan": plan,
            "country": country,
            "tz_offset": offset,
            "domain": domain,
            "created": created,
            "billing_day": rng.randrange(1, 29),
            "users": [],
            "announced": False,
        }
        seats = max(1, int(rng.expovariate(1 / PLAN_USERS[plan])) + 1)
        for _ in range(min(seats, 200)):
            org["users"].append(self.make_user(org, created))
        return org

    def make_user(self, org, joined):
        rng = self.rng
        self.user_seq += 1
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        device = weighted(rng, DEVICES)
        return {
            "user_id": f"usr_{self.user_seq:07d}",
            "email": f"{first.lower()}.{last.lower()}{self.user_seq % 1000}@{org['domain']}",
            "name": f"{first} {last}",
            "ip": ".".join(str(rng.randrange(1, 254)) for _ in range(4)),
            "device": device,
            "user_agent": rng.choice(USER_AGENTS[device]),
            "joined": joined,
            "announced": False,
        }

    def event(self, org, user, event_type, ts, properties, day_index):
        version = 2 if day_index >= self.schema_v2_from_day else 1
        context = {
            "ip": user["ip"] if user else None,
            "user_agent": user["user_agent"] if user else None,
            "device": user["device"] if user else None,
            "country": org["country"],
        }
        if version == 2:
            context["locale"] = LOCALES[org["country"]]
        return {
            "event_id": new_id(self.rng),
            "event_type": event_type,
            "event_ts": iso(ts),
            "schema_version": version,
            "org_id": org["org_id"],
            "user_id": user["user_id"] if user else None,
            "session_id": None,
            "properties": properties,
            "context": context,
            "user": {"email": user["email"], "name": user["name"]} if user else None,
        }

    def local_business_time(self, org, day_start):
        rng = self.rng
        hour = min(23, max(0, int(rng.gauss(13, 3)) - org["tz_offset"]))
        return day_start + timedelta(
            hours=hour, minutes=rng.randrange(0, 60), seconds=rng.randrange(0, 60)
        )

    def session(self, org, user, day_start, day_index):
        rng = self.rng
        ts = self.local_business_time(org, day_start)
        session_id = new_id(rng)
        events = [
            self.event(
                org,
                user,
                "login",
                ts,
                {"method": rng.choice(["password", "sso", "magic_link"])},
                day_index,
            )
        ]
        for _ in range(rng.randrange(3, 16)):
            ts += timedelta(seconds=rng.randrange(5, 300), milliseconds=rng.randrange(0, 1000))
            if rng.random() < 0.55:
                events.append(
                    self.event(org, user, "page_view", ts, {"page": rng.choice(PAGES)}, day_index)
                )
            else:
                feature = rng.choice(FEATURES)
                props = {"feature": feature, "duration_ms": rng.randrange(200, 20000)}
                events.append(self.event(org, user, "feature_used", ts, props, day_index))
        if rng.random() < 0.05:
            ts += timedelta(seconds=rng.randrange(5, 120))
            events.append(
                self.event(
                    org, user, "invite_sent", ts, {"invites": rng.randrange(1, 5)}, day_index
                )
            )
        if rng.random() < 0.08:
            ts += timedelta(seconds=rng.randrange(5, 120))
            props = {"format": rng.choice(["csv", "pdf", "xlsx"]), "rows": rng.randrange(10, 50000)}
            events.append(self.event(org, user, "export_created", ts, props, day_index))
        for item in events:
            item["session_id"] = session_id
        return events

    def business_events(self, org, day, day_start, day_index):
        rng = self.rng
        events = []
        plan = org["plan"]
        if not org["announced"] and org["created"] <= day_start + timedelta(days=1):
            props = {"plan": plan, "amount_cents": PLAN_PRICE[plan], "seats": len(org["users"])}
            events.append(self.event(org, None, "org_created", org["created"], props, day_index))
            org["announced"] = True
        for user in org["users"]:
            if not user["announced"] and user["joined"] <= day_start + timedelta(days=1):
                events.append(self.event(org, user, "signup", user["joined"], {}, day_index))
                user["announced"] = True
        if not org["announced"]:
            return events
        ts = self.local_business_time(org, day_start)
        if plan != "free" and day.day == org["billing_day"]:
            if rng.random() < 0.96:
                props = {"amount_cents": PLAN_PRICE[plan], "currency": "USD", "plan": plan}
                events.append(self.event(org, None, "payment_succeeded", ts, props, day_index))
            else:
                props = {
                    "amount_cents": PLAN_PRICE[plan],
                    "currency": "USD",
                    "plan": plan,
                    "reason": rng.choice(["card_declined", "insufficient_funds", "expired_card"]),
                }
                events.append(self.event(org, None, "payment_failed", ts, props, day_index))
        roll = rng.random()
        index = PLAN_ORDER.index(plan)
        if plan == "free" and roll < 0.004:
            org["plan"] = "starter"
            props = {
                "plan": "starter",
                "previous_plan": "free",
                "amount_cents": PLAN_PRICE["starter"],
            }
            events.append(self.event(org, None, "subscription_started", ts, props, day_index))
        elif plan != "free" and roll < 0.003 and index < len(PLAN_ORDER) - 1:
            new_plan = PLAN_ORDER[index + 1]
            org["plan"] = new_plan
            props = {"plan": new_plan, "previous_plan": plan, "amount_cents": PLAN_PRICE[new_plan]}
            events.append(self.event(org, None, "subscription_upgraded", ts, props, day_index))
        elif plan != "free" and roll < 0.0045:
            org["plan"] = "free"
            props = {"plan": "free", "previous_plan": plan, "amount_cents": 0}
            events.append(self.event(org, None, "subscription_cancelled", ts, props, day_index))
        if rng.random() < 0.01 and org["users"]:
            user = rng.choice(org["users"])
            props = {
                "priority": rng.choice(["low", "normal", "high"]),
                "channel": rng.choice(["email", "chat"]),
            }
            events.append(self.event(org, user, "support_ticket_opened", ts, props, day_index))
        if plan != "free" and rng.random() < 0.02:
            org["users"].append(self.make_user(org, ts))
        return events

    def day_events(self, day_index):
        rng = self.rng
        day_start = self.start + timedelta(days=day_index)
        weekend = day_start.weekday() >= 5
        events = []
        for org in self.orgs:
            events.extend(self.business_events(org, day_start.date(), day_start, day_index))
            if not org["announced"]:
                continue
            active = PLAN_ACTIVE[org["plan"]] * (0.4 if weekend else 1.0)
            if rng.random() > active:
                continue
            for user in org["users"]:
                if not user["announced"]:
                    continue
                if rng.random() > (0.2 if weekend else 0.5):
                    continue
                for _ in range(rng.randrange(1, 4)):
                    events.extend(self.session(org, user, day_start, day_index))
        events.sort(key=lambda item: item["event_ts"])
        late = self.pending_duplicates
        self.pending_duplicates = [
            dict(item) for item in events if rng.random() < self.duplicate_rate
        ]
        if late:
            positions = sorted(rng.randrange(0, len(events) + 1) for _ in late)
            for offset, (position, item) in enumerate(zip(positions, late, strict=True)):
                events.insert(position + offset, item)
        return events

    def files(self, events_per_file, prefix):
        for day_index in range(self.days):
            events = self.day_events(day_index)
            day = (self.start + timedelta(days=day_index)).date()
            for part, offset in enumerate(range(0, len(events), events_per_file)):
                key = f"{prefix}dt={day.isoformat()}/part-{part:05d}.ndjson.gz"
                yield key, events[offset : offset + events_per_file]
