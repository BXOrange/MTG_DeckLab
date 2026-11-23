"""RULE 608.2d: variable payments and their resolution-local referents."""
import re
from collections.abc import Callable

from ..spec import EffectSpec

PAID_AMOUNT = "$paid"
PAID_BY_PLAYER = "$paid_by_player"

_SCOPE = {
    "you": "you", "each player": "apnap",
    "starting with you, each player": "starting_with_you",
    "each player starting with you": "starting_with_you",
}
_PAYMENT = re.compile(
    r"(?P<scope>starting with you, each player|each player starting with you|each player|you) may "
    r"(?:pay any amount of (?P<resource>mana|life|\{e\})|(?P<discard>discard any number of cards))"
)
_ENERGY_PREFIX = re.compile(r"(?P<target>choose target spell\. )?(?P<gain>you get (?:x \{e\}|(?:\{e\})+)), then ")
_TOTAL = re.compile(r"(?P<effect>.+), where x is the total amount of (?P<resource>mana|life|\{e\}) paid this way")
_PER_PLAYER = re.compile(r"(each player creates .+) for each 1 life they paid this way")
_WIPE = re.compile(
    r"destroy each (?P<types>(?:artifact|creature|enchantment)(?:, (?:artifact|creature|enchantment))*"
    r"(?:,? and (?:artifact|creature|enchantment))?) with mana value less than or equal to the amount of \{e\} paid this way"
)
_REPEAT_LIFE = "repeat this process until no 1 pays life. "


def _total_payoff(effect, parse_clause):
    if effect == "each player draws x cards":
        return EffectSpec("draw", {"count": PAID_AMOUNT, "selector": "each_player"})
    if effect == "each player mills x cards":
        return EffectSpec("mill", {"count": PAID_AMOUNT, "selector": "each_player"})
    if re.fullmatch(r"~ gets \+x/\+0 until end of turn", effect):
        return EffectSpec("pump", {"power": PAID_AMOUNT})
    if effect.startswith("each player creates x "):
        return _token_payoff(effect.replace("creates x ", "creates 1 ", 1), parse_clause, "count", PAID_AMOUNT)
    return None


def _token_payoff(text, parse_clause, key, value):
    specs = parse_clause(text)
    # Shared entry uses the plain token definition; leave token riders to their own grammar.
    fields = {"count", "power", "toughness", "colors", "subtypes", "keywords", "token_name", "creators"}
    if (specs and len(specs) == 1 and specs[0].type == "create_token"
            and specs[0].params.get("creators") == "each_player" and specs[0].params.keys() <= fields):
        return EffectSpec("create_token", {**specs[0].params, key: value, "simultaneous_creators": True})
    return None


def amount_payment_specs(
    body: str, parse_clause: Callable[[str], list[EffectSpec] | None],
) -> list[EffectSpec] | None:
    head, _, payoff = body.strip().rstrip(".").partition(". ")
    if not payoff and head.startswith("discard any number of cards, then "):
        head, payoff = head.split(", then ", 1)
    prefix = _ENERGY_PREFIX.match(body.strip())
    target = prefix and prefix["target"]
    if target:
        head, _, payoff = body.strip()[len(target):].rstrip(".").partition(". ")
    if prefix:
        head = head.removeprefix(prefix["gain"] + ", then ")
    if head == "discard any number of cards":
        head = "you may " + head
    payment = _PAYMENT.fullmatch(head)
    if not payment:
        return None
    resource = payment["resource"] or "discard"
    repeat = resource == "life" and payoff.startswith(_REPEAT_LIFE)
    if repeat:
        payoff = payoff.removeprefix(_REPEAT_LIFE)
    total = _TOTAL.fullmatch(payoff)
    per_player = _PER_PLAYER.fullmatch(payoff)
    wipe = _WIPE.fullmatch(payoff)
    result = None
    if total and resource == total["resource"] and not target:
        result = _total_payoff(total["effect"], parse_clause)
    elif resource in {"life", "discard"} and not target and payment["scope"] == "you" and payoff in {
        "draw that many cards", "if you do, draw that many cards",
    }:
        result = EffectSpec("draw", {"count": PAID_AMOUNT})
    elif per_player and resource == "life" and not target:
        result = _token_payoff(per_player[1], parse_clause, "counts_by_player", PAID_BY_PLAYER)
    elif wipe and resource == "{e}" and not target:
        types = re.findall(r"artifact|creature|enchantment", wipe["types"])
        result = EffectSpec("destroy", {
            "group": {"zone": "battlefield", "of": "any", "filter": {"card_type_any": types}},
            "filter": {"max_mana_value": PAID_AMOUNT},
        })
    elif target and resource == "{e}" and payoff == "counter that spell unless its controller pays {1} for each {e} paid this way":
        result = EffectSpec("counter_unless_pay", {"target_kind": "spell", "unless_pays_generic": PAID_AMOUNT})
    if result is None and payoff:
        return None
    if (repeat or prefix) and result is None:
        return None
    specs = []
    if prefix:
        if resource != "{e}":
            return None
        gain = prefix["gain"]
        specs.append(EffectSpec("add_player_counters", {
            "kind": "energy", "amount": "x" if gain.startswith("you get x") else gain.count("{e}"),
        }))
    specs.append(EffectSpec("amount_payment", {
        "resource": "energy" if resource == "{e}" else resource,
        "scope": _SCOPE[payment["scope"]], "repeat": repeat,
        "effects": [result.to_dict()] if result is not None else [],
    }))
    return specs
