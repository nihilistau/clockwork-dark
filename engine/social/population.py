"""
The population (v0.22.0 spec §4): lazy, seeded, never stored.

A person is a pure function of (seed, index) -- stable_rng(seed,
f"{SOCIAL_POPULATION}:{index}"), no state counter -- so whoever was met
first, the same seed always holds the same people. Only DYNAMIC state is kept
(state.social["people"][pid], T7 on). Static profiles are cached per seed in a
small LRU under a LEAF lock; a profile is generated OUTSIDE the lock (it reads
story data through cached loaders that take ordered locks), and two threads
generating the same person race harmlessly: identical results, first insert wins.

Three keys of one stream, so the filter (spec §4.2) moves only what it must:
every field but sex and name is drawn from ``...:{index}``; sex from
``...:{index}:sex`` (drawn only under ``filter.sex: any``); the name from
``...:{index}:name``, keyed by that sex. Changing the filter changes a
person's sex and name and nothing else.

Every table is ``population.yaml``'s (and the apps' ``culture`` weights are
``apps.yaml``'s); nothing here calls the model (spec §4.3).
"""

from __future__ import annotations

import string
import threading
from statistics import NormalDist
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from engine import social
from engine.game.rng import SOCIAL_POPULATION, stable_rng
from engine.locks import renew_after_fork

#: (seed, index, player-key) -> Person. Bounded; per process.
_PROFILES: "OrderedDict[tuple[int, int, str], Person]" = OrderedDict()
_PROFILES_LOCK = threading.Lock()   # a LEAF: its holder takes nothing
PROFILE_CACHE_MAX = 4096

#: What a bio or prompt template may name (`str.format_map` keys).
BIO_FIELDS: frozenset[str] = frozenset({"hobby_a", "hobby_b", "job", "a_job", "A_job", "neighbourhood"})

#: `filter.sex`'s values (spec §4.2).
FILTER_MODES: tuple[str, ...] = ("opposite", "same", "any")


@dataclass(frozen=True)
class Person:
    pid: str
    index: int
    name: str
    sex: str
    age: int
    neighbourhood: str
    job: str
    job_shape: str
    education: str
    hobbies: tuple[str, ...]
    attributes: tuple[tuple[str, str], ...]          # (key, value), sorted
    flags: tuple[str, ...]                           # the fixed facts a mechanic may gate on
    appearance: str                                  # the image subject's descriptor (§13.3)
    personality: tuple[tuple[str, int], ...]         # the five sliders, 1-5
    traits: tuple[str, ...]                          # three
    intent: str                                      # friendship | short_term | long_term | unsure
    archetype: str
    texting_style: str
    preferences: tuple[tuple[str, Any], ...]         # age_min, age_max, dealbreakers, liked_hobbies, selectivity
    chemistry: float
    voice_id: str
    bio: dict[str, str] = field(default_factory=dict)      # app -> bio (deterministic, never the model's)
    prompts: tuple[tuple[str, str], ...] = ()              # Front Porch (question, answer)
    photos: tuple[str, ...] = ()                           # photo_set ids, 2-5

    def has_flag(self, name: str) -> bool:
        return name in self.flags


# -- ids, pools ---------------------------------------------------------------


def pid_for(index: int) -> str:
    return f"p{index:04d}"


def index_of(pid: str) -> int:
    return int(pid[1:])


def _apps() -> dict[str, dict[str, Any]]:
    return social.data("apps").get("apps") or {}


def _pooled() -> list[tuple[str, dict[str, Any]]]:
    """Every app with a `pool:` row, in `apps.yaml`'s order."""
    return [(name, cfg["pool"]) for name, cfg in _apps().items() if isinstance(cfg, dict) and cfg.get("pool")]


def pool(app: str) -> range:
    cfg = (_apps().get(app) or {}).get("pool")
    if not cfg:
        raise ValueError(f"social: apps.yaml: apps.{app}.pool: no such pool")
    start = int(cfg["from"])
    return range(start, start + int(cfg["size"]))


def _bands() -> list[tuple[tuple[str, str], range]]:
    """The overlap bands, each a THIRD range after every pool (spec §4.1), stacked in apps.yaml order."""
    pooled = _pooled()
    end = max((int(p["from"]) + int(p["size"]) for _, p in pooled), default=0)
    bands: list[tuple[tuple[str, str], range]] = []
    for name, cfg in pooled:
        other = cfg.get("overlap_with")
        size = int(cfg.get("overlap") or 0)
        if other and size > 0:
            bands.append(((name, str(other)), range(end, end + size)))
            end += size
    return bands


def overlap(app: str) -> range:
    """The band of people on `app` AND its partner app: the same band whichever of the two asks."""
    for pair, band in _bands():
        if app in pair:
            return band
    return range(0)


def apps_of(pid: str) -> tuple[str, ...]:
    index = index_of(pid)
    for name, cfg in _pooled():
        start = int(cfg["from"])
        if start <= index < start + int(cfg["size"]):
            return (name,)
    for pair, band in _bands():
        if index in band:
            return pair
    return ()


def table(name: str) -> list[dict[str, Any]]:
    """A `population.yaml` table (creation's `of_table` source); [] when absent."""
    return social.data("population").get(name) or []


# -- the filter and the cache --------------------------------------------------


def _filter_spec() -> dict[str, Any]:
    """`population.yaml`'s `filter:` mapping, read only (the shared data cache is never written)."""
    spec = social.data("population").get("filter")
    return spec if isinstance(spec, dict) else {"sex": "opposite", "age_from_discovery": True}


def _require(data: dict[str, Any], *path: str) -> Any:
    """A required `population.yaml` value; its absence is a ValueError naming the key (spec §2.1)."""
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise ValueError(f"social: population.yaml: {'.'.join(path)}: required")
        node = node[key]
    return node


def _sex_for(player: dict[str, Any], rng: Any) -> str:
    mode = str(_filter_spec().get("sex", "opposite"))
    mine = str(player.get("sex") or "female")
    if mode == "opposite":
        return "male" if mine == "female" else "female"
    if mode == "same":
        return mine
    if mode == "any":
        return rng.choice(("female", "male"))
    raise ValueError(f"social: population.yaml: filter.sex must be opposite, same or any, not {mode!r}")


def person(seed: int, index: int, player: Optional[dict[str, Any]] = None) -> Person:
    player = player or {}
    key = (int(seed), int(index), _player_key(player))
    with _PROFILES_LOCK:
        hit = _PROFILES.get(key)
        if hit is not None:
            _PROFILES.move_to_end(key)
            return hit
    made = _generate(int(seed), int(index), player)       # OUTSIDE the lock
    with _PROFILES_LOCK:
        existing = _PROFILES.setdefault(key, made)
        _PROFILES.move_to_end(key)
        while len(_PROFILES) > PROFILE_CACHE_MAX:
            _PROFILES.popitem(last=False)
    return existing


def _player_key(player: dict[str, Any]) -> str:
    """Everything a person's draw depends on beyond (seed, index): the whole FILTER included (F7)."""
    discovery = player.get("discovery") or {}
    spec = _filter_spec()
    mode = f"{spec.get('sex', 'opposite')}|{bool(spec.get('age_from_discovery', True))}"
    return f"{mode}|{player.get('sex', '')}|{discovery.get('age_min', '')}|{discovery.get('age_max', '')}"


def profile(state: Any, pid: str) -> Person:
    return person(state.rng_seed, index_of(pid), (state.social or {}).get("player") or {})


def reset_profiles() -> None:
    with _PROFILES_LOCK:
        _PROFILES.clear()


# -- draws ----------------------------------------------------------------------


def _weighted(rng: Any, rows: Sequence[Any], key: str = "weight") -> Any:
    """One row, by its `key` weight (1 when a row has none)."""
    rows = list(rows)
    weights = [float(row.get(key, 1)) if isinstance(row, dict) else 1.0 for row in rows]
    return rng.choices(rows, weights=weights, k=1)[0]


def _weighted_ids(rng: Any, weights: dict[str, Any]) -> str:
    """One id of a {id: weight} mapping, in its declared order."""
    ids = list(weights)
    return rng.choices(ids, weights=[float(weights[i]) for i in ids], k=1)[0]


def _sample(rng: Any, rows: Sequence[Any], k: int, key: str = "weight") -> list[Any]:
    """`k` distinct rows, weighted, without replacement."""
    left = list(rows)
    picked: list[Any] = []
    for _ in range(min(k, len(left))):
        row = _weighted(rng, left, key)
        picked.append(row)
        left.remove(row)
    return picked


def _labels(rows: Sequence[dict[str, Any]]) -> dict[str, str]:
    return {str(row["id"]): str(row.get("label", row["id"])) for row in rows}


def _age(rng: Any, data: dict[str, Any], app: str, player: dict[str, Any]) -> int:
    dist = _require(data, "ages", app)
    floor_, ceiling = int(_require(data, "age_bounds", "min")), int(_require(data, "age_bounds", "max"))
    lo, hi = floor_, ceiling
    discovery = player.get("discovery") or {}
    if _filter_spec().get("age_from_discovery", True) and discovery:
        spill = float(_require(data, "age_spill"))
        lo = max(floor_, round(int(discovery.get("age_min", floor_)) * (1.0 - spill)))
        hi = min(ceiling, round(int(discovery.get("age_max", ceiling)) * (1.0 + spill)))
        hi = max(hi, lo)
    # A normal TRUNCATED to [lo, hi] by one uniform draw through its CDF: no
    # pile-up at the bounds, and always exactly one draw from the stream.
    normal = NormalDist(float(dist["mean"]), max(0.1, float(dist["sd"])))
    a, b = normal.cdf(lo - 0.5), normal.cdf(hi + 0.5)
    u = rng.uniform(a, b)
    drawn = normal.inv_cdf(min(max(u, 1e-12), 1.0 - 1e-12)) if b > a else float(dist["mean"])
    return max(lo, min(hi, int(round(drawn))))


def _job(rng: Any, data: dict[str, Any]) -> tuple[str, str, str]:
    row = _weighted(rng, data["jobs"])
    education = rng.choice(list(row.get("education") or ["school"]))
    return str(row["id"]), str(row["shape"]), str(education)


def _hobbies(rng: Any, data: dict[str, Any]) -> tuple[str, ...]:
    count = rng.randint(2, 6)
    return tuple(str(row["id"]) for row in _sample(rng, data["hobbies"], count))


def _attributes(rng: Any, data: dict[str, Any], job: str) -> dict[str, str]:
    """The creation attribute set (spec §3.1): one weighted row of each attribute table, plus the job."""
    out = {name: str(_weighted(rng, data[name])["id"]) for name in data.get("attribute_tables") or ()}
    out["job"] = job
    return out


def _flags(rng: Any, data: dict[str, Any], attributes: dict[str, str]) -> tuple[str, ...]:
    """Each `flags:` row a Bernoulli; `has_kids` and the `kids` attribute agree."""
    held = tuple(name for name, p in (data.get("flags") or {}).items() if rng.random() < float(p))
    if "kids" in attributes:
        if "has_kids" in held:
            attributes["kids"] = "have"
        elif attributes["kids"] == "have":
            attributes["kids"] = "unsure"
    return held


def _appearance(rng: Any, data: dict[str, Any], attributes: dict[str, str]) -> str:
    """The image subject's descriptor: the drawn attributes' labels, then one row of each `appearance` table."""
    looks = [_labels(data.get(name) or []).get(attributes.get(name, ""), "") for name in ("height", "build", "hair", "style")]
    tables = data.get("appearance") or {}
    extra = [str(_weighted(rng, tables[name]).get("label", "")) for name in tables]
    return ", ".join(part for part in (*looks, *extra) if part)


def _personality(rng: Any, data: dict[str, Any]) -> tuple[tuple[tuple[str, int], ...], tuple[str, ...]]:
    sliders = tuple((str(name), rng.randint(1, 5)) for name in data["personality"])
    traits = tuple(str(row["id"]) for row in _sample(rng, data["traits"], 3))
    return sliders, traits


def _culture(rng: Any, app: str) -> tuple[str, str]:
    culture = (_apps().get(app) or {}).get("culture") or {}
    return _weighted_ids(rng, culture["intent_weights"]), _weighted_ids(rng, culture["archetype_weights"])


def _preferences(rng: Any, data: dict[str, Any], age: int) -> tuple[tuple[str, Any], ...]:
    spec = _require(data, "preferences")
    below = _require(data, "preferences", "age_below")
    above = _require(data, "preferences", "age_above")
    floor_ = int(_require(data, "age_bounds", "min"))
    age_min = max(floor_, age - rng.randint(int(below[0]), int(below[1])))
    age_max = age + rng.randint(int(above[0]), int(above[1]))
    pool_ = [str(d) for d in spec.get("dealbreakers") or []]
    low, high = _require(data, "preferences", "dealbreaker_count")
    dealbreakers = tuple(sorted(rng.sample(pool_, min(rng.randint(int(low), int(high)), len(pool_)))))
    liked = tuple(str(row["id"]) for row in _sample(rng, data["hobbies"], rng.randint(1, 3)))
    sel = _require(data, "preferences", "selectivity")
    selectivity = round(max(0.0, min(1.0, rng.gauss(float(sel["mean"]), float(sel["sd"])))), 3)
    return (("age_max", age_max), ("age_min", age_min), ("dealbreakers", dealbreakers),
            ("liked_hobbies", liked), ("selectivity", selectivity))


def in_sentence(label: str) -> str:
    """A label as it reads mid-sentence: "Sea swimming" -> "sea swimming", but "HR manager" and "PhD student" kept."""
    word = label.split(" ", 1)[0]
    return label if any(c.isupper() for c in word[1:]) else label[:1].lower() + label[1:]


def template_words(data: dict[str, Any], hobbies: tuple[str, ...], job: str, neighbourhood: str) -> dict[str, str]:
    hobby = _labels(data["hobbies"])
    job_words = in_sentence(_labels(data["jobs"]).get(job, job))
    row = next((r for r in data["jobs"] if r.get("id") == job), {})
    article = str(row.get("article") or ("an" if job_words[:1].lower() in "aeiou" else "a"))
    a_job = f"{article} {job_words}"
    return {
        "a_job": a_job,
        "A_job": a_job[:1].upper() + a_job[1:],
        "hobby_a": in_sentence(hobby.get(hobbies[0], hobbies[0])),
        "hobby_b": in_sentence(hobby.get(hobbies[1], hobbies[1])) if len(hobbies) > 1 else "",
        "job": job_words,
        "neighbourhood": _labels(data["neighbourhoods"]).get(neighbourhood, neighbourhood),
    }


def _bios(rng: Any, data: dict[str, Any], apps: tuple[str, ...], style: str, words: dict[str, str]) -> dict[str, str]:
    """One template per app, distinct while the style's bank lasts."""
    bank = list((data.get("bios") or {}).get(style) or [])
    if not bank:
        return {app: "" for app in apps}
    picked = rng.sample(bank, len(apps)) if len(bank) >= len(apps) else [rng.choice(bank) for _ in apps]
    return {app: str(text).format_map(words) for app, text in zip(apps, picked)}


def _prompts(rng: Any, data: dict[str, Any], apps: tuple[str, ...], hobbies: tuple[str, ...],
             words: dict[str, str]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for app in apps:
        bank = list((data.get("prompts") or {}).get(app) or [])
        for row in rng.sample(bank, min(3, len(bank))):
            by_hobby = row.get("a_by_hobby") or {}
            answers = [a for h in hobbies for a in by_hobby.get(h, [])] or list(row.get("a_any") or [])
            out.append((str(row["q"]), str(rng.choice(answers)).format_map(words) if answers else ""))
    return tuple(out)


def voices_of(sex: str) -> list[str]:
    """The ids of `tts.voices` (config, rule 5) tagged with ``sex``, in order."""
    from engine.config import get_config

    voices = get_config().get("tts.voices") or []
    return [str(v["id"]) for v in voices if isinstance(v, dict) and v.get("id") and str(v.get("sex") or "") == sex]


def _voice_for(sex: str, rng: Any) -> str:
    """One voice of the person's sex from `tts.voices`; "" when the list has none of it (the transcript tile)."""
    pool = voices_of(sex)
    return str(rng.choice(pool)) if pool else ""


def _generate(seed: int, index: int, player: dict[str, Any]) -> Person:
    """Every field of one person, in ONE FIXED ORDER (a new field is drawn last, on its own key)."""
    data = social.data("population")
    rng = stable_rng(seed, f"{SOCIAL_POPULATION}:{index}")
    pid = pid_for(index)
    apps = apps_of(pid)
    if not apps:
        raise ValueError(f"social: {pid} is in no app's pool or overlap band (apps.yaml `pool:`)")
    app = apps[0]
    age = _age(rng, data, app, player)
    neighbourhood = str(_weighted(rng, data["neighbourhoods"])["id"])
    job, job_shape, education = _job(rng, data)
    hobbies = _hobbies(rng, data)
    attributes = _attributes(rng, data, job)
    flags = _flags(rng, data, attributes)
    appearance = _appearance(rng, data, attributes)
    personality, traits = _personality(rng, data)
    intent, archetype = _culture(rng, app)
    texting_style = str(_weighted(rng, data["texting_styles"])["id"])
    preferences = _preferences(rng, data, age)
    low, high = (social.data("apps").get("matching") or {}).get("chemistry", (-0.15, 0.15))
    chemistry = round(rng.uniform(float(low), float(high)), 4)
    words = template_words(data, hobbies, job, neighbourhood)
    bio = _bios(rng, data, apps, texting_style, words)
    prompts = _prompts(rng, data, tuple(a for a in apps if a in (data.get("prompts") or {})), hobbies, words)
    photos = tuple(str(row["id"]) for row in _sample(rng, data["photo_set"], rng.randint(2, 5)))
    # Drawn after the filter, each on its own key: changing the filter moves these two only (§4.2)
    # -- and the voice below, which is of the person's sex.
    sex = _sex_for(player, stable_rng(seed, f"{SOCIAL_POPULATION}:{index}:sex"))
    name = str(stable_rng(seed, f"{SOCIAL_POPULATION}:{index}:name").choice(list(data["names"][sex])))
    # v0.22.0 T21: drawn LAST, on its own key, so adding it moved no earlier field.
    voice_id = _voice_for(sex, stable_rng(seed, f"{SOCIAL_POPULATION}:{index}:voice"))
    return Person(
        pid=pid, index=index, name=name, sex=sex, age=age, neighbourhood=neighbourhood,
        job=job, job_shape=job_shape, education=education, hobbies=hobbies,
        attributes=tuple(sorted(attributes.items())), flags=flags, appearance=appearance,
        personality=personality, traits=traits, intent=intent, archetype=archetype,
        texting_style=texting_style, preferences=preferences, chemistry=chemistry,
        voice_id=voice_id,
        bio=bio, prompts=prompts, photos=photos,
    )


def template_fields(text: str) -> set[str]:
    """The `{names}` a bio or prompt template uses (the validator's check)."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


renew_after_fork(globals(), _PROFILES_LOCK=threading.Lock)
