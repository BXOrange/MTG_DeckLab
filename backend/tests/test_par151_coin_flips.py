"""PAR-151 — coin flips (RULE 705): "flip a coin. If you win/lose the flip, <effect>".

Axes shipped: the single flip with win and/or lose branches (sibling ``coin_won``-gated
specs, so a branch's target is announced with the spell/ability — RULE 601.2c), "flip N/X
coins" with "for each flip you win/lose", "flip a coin until you lose a flip", and the
"whenever you win/lose a coin flip" trigger heads. Every execute test drives the real
``RulesEngine.coin_flip`` (events included) with a scripted ``random_int`` so the outcome
is deterministic.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.game.targeting import effects_target_specs, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import make_engine

HEADS, TAILS = 0, 1  # `RulesEngine.coin_flip`: ``random_int(2) == 0`` is a won flip


@pytest.fixture
def script_flips(monkeypatch):
    """Script the coin: ``script_flips(HEADS, TAILS, ...)`` — each flip consumes one result."""
    real = RulesEngine.random_int
    queue: list[int] = []

    def fake(self, n):
        if n == 2 and queue:
            return queue.pop(0)
        return real(self, n)

    monkeypatch.setattr(RulesEngine, "random_int", fake)

    def feed(*results):
        queue[:] = list(results)
        return queue

    return feed


def _card(name, type_line, text, **kwargs):
    return Card(id=name, name=name, type_line=type_line, oracle_text=text, **kwargs)


def _creature_card(name, text, power=2, toughness=2, type_line="Creature — Test", **kwargs):
    return _card(name, type_line, text, is_creature=True, power=power,
                 toughness=toughness, **kwargs)


def _engine():
    eng = make_engine([_creature_card(f"Filler {i}", "") for i in range(5)],
                      [_creature_card(f"Other {i}", "") for i in range(5)], hand=0)
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _on_battlefield(eng, name, controller=None):
    return [o for o in eng.state.battlefield
            if o.name == name and (controller is None or o.controller_id == controller)]


# --- parse -------------------------------------------------------------------


def test_flip_clause_shapes():
    one = match_clause("flip a coin")[0]
    assert (one.type, one.params) == ("coin_flip", {})
    assert match_clause("flip 3 coins")[0].params == {"count": 3}
    assert match_clause("flip x coins")[0].params == {"count": "x"}
    assert match_clause("flip a coin until you lose a flip")[0].params == {"until_lose": True}
    assert match_clause("flip 3 coins until you lose a flip") is None  # not printed; fail closed
    assert match_clause("flip a coin at the beginning of the next end step") is None


def test_result_branches_are_negated_siblings():
    win, lose = parse_effect_body(
        "flip a coin. if you win the flip, draw a card. if you lose the flip, you lose 1 life"
    )[1:]
    assert win.condition == {"kind": "coin_won"}
    assert lose.condition == {"kind": "not", "condition": {"kind": "coin_won"}}
    heads, tails = parse_effect_body(
        "flip a coin. if the coin comes up heads, draw a card. if it comes up tails, you lose 1 life"
    )[1:]
    assert heads.condition == {"kind": "coin_won"}
    assert tails.condition == {"kind": "not", "condition": {"kind": "coin_won"}}


def test_otherwise_after_a_win_branch_is_its_negation():
    specs = parse_effect_body("flip a coin. if you win the flip, draw a card. otherwise, you lose 1 life")
    assert [s.type for s in specs] == ["coin_flip", "draw", "lose_life"]
    assert specs[2].condition == {"kind": "not", "condition": {"kind": "coin_won"}}


def test_for_each_flip_binds_the_flip_count_both_spellings():
    leading = parse_effect_body(
        "flip x coins. for each flip you win, create a 2/2 green sheep creature token named rabid sheep"
    )
    suffix = parse_effect_body("flip a coin until you lose a flip. put a +1/+1 counter on ~ for each flip you won")
    assert leading[1].type == suffix[1].type == "bind"
    assert leading[1].params["amount"] == {"kind": "coin_flips", "won": True}
    assert suffix[1].params["amount"] == {"kind": "coin_flips", "won": True}
    lost = parse_effect_body("flip 2 coins. for each flip you lose, you lose 1 life")
    assert lost[1].params["amount"] == {"kind": "coin_flips", "won": False}


def test_unmodeled_branch_body_keeps_the_card_unmodeled():
    card = _card("Test Gamble", "Sorcery", "Flip a coin. If you win the flip, glorble the frobnicator.",
                 is_sorcery=True)
    assert not parse_oracle(card).modeled


def test_real_cards_are_modeled():
    cases = {
        "Bottle of Suleiman": ("Artifact", "{1}, Sacrifice this artifact: Flip a coin. If you win the flip, create "
         "a 5/5 colorless Djinn artifact creature token with flying. If you lose the flip, this artifact deals 5 "
         "damage to you."),
        "Flock of Rabid Sheep": ("Sorcery", "Flip X coins. For each flip you win, create a 2/2 green Sheep creature "
         "token named Rabid Sheep."),
        "Tavern Scoundrel": ("Creature — Human Rogue", "Whenever you win a coin flip, create two Treasure tokens.\n"
         "{1}, {T}, Sacrifice another permanent: Flip a coin."),
    }
    for name, (type_line, text) in cases.items():
        flags = {"is_sorcery": True} if type_line == "Sorcery" else {}
        assert parse_oracle(_card(name, type_line, text, **flags)).modeled, name


# --- execute: single flip, win / lose branches --------------------------------


_BOTTLE = _card(
    "Bottle of Suleiman", "Artifact",
    "{1}, Sacrifice this artifact: Flip a coin. If you win the flip, create a 5/5 colorless Djinn artifact "
    "creature token with flying. If you lose the flip, this artifact deals 5 damage to you.",
)


@pytest.mark.parametrize("result,djinn,life", [(HEADS, 1, 20), (TAILS, 0, 15)])
def test_bottle_of_suleiman_branches(script_flips, result, djinn, life):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    bottle = _put(eng, _BOTTLE)
    p1.mana_pool.add_many({"C": 1})
    script_flips(result)
    eng.activate_ability(p1, bottle)
    eng.resolve_until_stable()
    assert len(_on_battlefield(eng, "Djinn")) == djinn
    assert p1.life == life


def test_flip_fires_one_coin_flip_event_per_flip(script_flips):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    bottle = _put(eng, _BOTTLE)
    p1.mana_pool.add_many({"C": 1})
    seen = []
    eng.state.subscribe(lambda e: seen.append(e.get("won")) if e.type == EventType.COIN_FLIP else None)
    script_flips(TAILS)
    eng.activate_ability(p1, bottle)
    eng.resolve_until_stable()
    assert seen == [False]


# --- execute: a branch's target is announced with the ability (RULE 601.2c) ----


_ARCHAEOLOGIST = _creature_card(
    "Goblin Archaeologist",
    "{R}, {T}: Flip a coin. If you win the flip, destroy target artifact and untap this creature. "
    "If you lose the flip, sacrifice this creature.",
    power=1, toughness=2,
)
_TRINKET = _card("Trinket", "Artifact", "")


def test_branch_target_is_announced_before_the_flip():
    eng = _engine()
    digger = _put(eng, _ARCHAEOLOGIST)
    _put(eng, _TRINKET, controller="p2")
    specs = effects_target_specs(digger.activated_abilities[0].effects)
    assert len(specs) == 1  # the win branch's artifact, announced although the flip is not yet made
    offered = legal_targets(eng.state, "p1", specs[0], source=digger)
    assert [o["name"] for o in offered] == ["Trinket"]


@pytest.mark.parametrize("result", [HEADS, TAILS])
def test_archaeologist_win_destroys_target_lose_sacrifices_self(script_flips, result):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    digger = _put(eng, _ARCHAEOLOGIST)
    trinket = _put(eng, _TRINKET, controller="p2")
    p1.mana_pool.add_many({"R": 1})
    script_flips(result)
    eng.activate_ability(p1, digger, targets=[trinket])
    eng.resolve_until_stable()
    if result == HEADS:
        assert trinket.zone == Zone.GRAVEYARD and digger.zone == Zone.BATTLEFIELD
        assert digger.tapped is False  # "and untap this creature"
    else:
        assert trinket.zone == Zone.BATTLEFIELD  # announced, never used
        assert digger.zone == Zone.GRAVEYARD


def test_activation_without_the_branch_target_is_refused():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    digger = _put(eng, _ARCHAEOLOGIST)
    p1.mana_pool.add_many({"R": 1})
    with pytest.raises(ValueError):
        eng.activate_ability(p1, digger)


_CAPTAIN = _creature_card(
    "Orcish Captain",
    "{1}: Flip a coin. If you win the flip, target Orc creature gets +2/+0 until end of turn. "
    "If you lose the flip, it gets -0/-2 until end of turn.",
)
_ORC = _creature_card("Orc Grunt", "", power=2, toughness=4, type_line="Creature — Orc")


@pytest.mark.parametrize("result,expected", [(HEADS, (4, 4)), (TAILS, (2, 2))])
def test_orcish_captain_pronoun_branch_hits_the_announced_target(script_flips, result, expected):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    captain = _put(eng, _CAPTAIN)
    orc = _put(eng, _ORC)
    p1.mana_pool.add_many({"C": 1})
    script_flips(result)
    eng.activate_ability(p1, captain, targets=[orc])
    eng.resolve_until_stable()
    assert (orc.power, orc.toughness) == expected


# --- execute: flip N / X coins, until you lose ---------------------------------


_SHEEP = _card(
    "Flock of Rabid Sheep", "Sorcery",
    "Flip X coins. For each flip you win, create a 2/2 green Sheep creature token named Rabid Sheep.",
    is_sorcery=True, mana_cost_string="{X}{R}{R}", converted_mana_cost=2,
)


def test_flock_of_rabid_sheep_makes_one_sheep_per_won_flip(script_flips):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(_SHEEP, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"R": 2, "C": 3})
    script_flips(HEADS, TAILS, HEADS)
    eng.cast_spell(p1, spell, x=3)
    eng.resolve_until_stable()
    assert len(_on_battlefield(eng, "Rabid Sheep")) == 2


_TRAPRUNNER_TEXT = (
    "Whenever this creature attacks, flip 3 coins. For each flip you win, create a 1/1 red Goblin "
    "creature token that's tapped and attacking."
)


@pytest.mark.parametrize("results,tokens", [((TAILS, TAILS, TAILS), 0), ((HEADS, TAILS, HEADS), 2)])
def test_goblin_traprunner_flips_three_coins_and_makes_a_goblin_per_win(script_flips, results, tokens):
    eng = _engine()
    runner = _put(eng, _creature_card("Goblin Traprunner", _TRAPRUNNER_TEXT, power=1, toughness=1))
    seen = []
    eng.state.subscribe(lambda e: seen.append(e.get("won")) if e.type == EventType.COIN_FLIP else None)
    script_flips(*results)
    eng.state.fire_event(GameEvent(
        EventType.ATTACKS, instance_id=runner.instance_id, player_id="p1", controller_id="p1",
    ))
    eng.resolve_until_stable()
    assert len(seen) == 3
    assert len(_on_battlefield(eng, "Goblin", "p1")) == tokens


def test_krarks_thumb_replacement_stays_unmodeled():
    thumb = _card("Krark's Thumb", "Legendary Artifact",
                  "If you would flip a coin, instead flip two coins and ignore one.")
    assert not parse_oracle(thumb).modeled


_FIRECAT = _creature_card(
    "Crazed Firecat",
    "Trample\nWhen this creature enters, flip a coin until you lose a flip. Put a +1/+1 counter on "
    "this creature for each flip you won.",
    power=3, toughness=3,
)


def test_crazed_firecat_flips_until_the_first_loss(script_flips):
    eng = _engine()
    cat = _put(eng, _FIRECAT)
    seen = []
    eng.state.subscribe(lambda e: seen.append(e.get("won")) if e.type == EventType.COIN_FLIP else None)
    script_flips(HEADS, HEADS, TAILS, HEADS)  # the trailing HEADS must never be flipped
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=cat.instance_id, controller_id="p1",
        object_types=sorted(cat.type_words),
    ))
    eng.resolve_until_stable()
    assert seen == [True, True, False]
    assert cat.counters.get("+1/+1") == 2


# --- execute: "whenever you win/lose a coin flip" ----------------------------


def test_win_a_coin_flip_trigger_fires_only_on_won_flips(script_flips):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _put(eng, _creature_card(
        "Tavern Scoundrel",
        "Whenever you win a coin flip, create two Treasure tokens.\n"
        "{1}, {T}, Sacrifice another permanent: Flip a coin.",
    ))
    script_flips(TAILS, HEADS)
    eng.rules.coin_flip(p1)
    eng.resolve_until_stable()
    assert not _on_battlefield(eng, "Treasure")
    eng.rules.coin_flip(p1)
    eng.resolve_until_stable()
    assert len(_on_battlefield(eng, "Treasure")) == 2


def test_win_trigger_ignores_the_opponents_flips(script_flips):
    eng = _engine()
    _put(eng, _creature_card("Toothy and Zndrsplt", "Whenever you win a coin flip, put a +1/+1 counter on this creature."))
    toothy = _on_battlefield(eng, "Toothy and Zndrsplt")[0]
    script_flips(HEADS)
    eng.rules.coin_flip(eng.state.player_by_id("p2"))
    eng.resolve_until_stable()
    assert not toothy.counters.get("+1/+1")


_MOLTEN_BIRTH = _card(
    "Molten Birth", "Sorcery",
    "Create two 1/1 red Elemental creature tokens, then flip a coin. If you win the flip, return Molten Birth "
    "to its owner's hand.",
    is_sorcery=True, mana_cost_string="{1}{R}{R}", converted_mana_cost=3,
)


@pytest.mark.parametrize("result,zone", [(HEADS, Zone.HAND), (TAILS, Zone.GRAVEYARD)])
def test_molten_birth_returns_itself_only_on_a_won_flip(script_flips, result, zone):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(_MOLTEN_BIRTH, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"R": 2, "C": 1})
    script_flips(result)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert len(_on_battlefield(eng, "Elemental")) == 2
    assert spell.zone == zone


_PUPPETS_VERDICT = _card(
    "Puppet's Verdict", "Sorcery",
    "Flip a coin. If you win the flip, destroy all creatures with power 2 or less. If you lose the flip, "
    "destroy all creatures with power 3 or greater.",
    is_sorcery=True, mana_cost_string="{2}{R}", converted_mana_cost=3,
)


@pytest.mark.parametrize("result,survivor", [(HEADS, "Big"), (TAILS, "Small")])
def test_puppets_verdict_destroys_the_half_the_flip_names(script_flips, result, survivor):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    small = _put(eng, _creature_card("Small", "", power=2, toughness=2))
    big = _put(eng, _creature_card("Big", "", power=4, toughness=4))
    spell = GameObject(_PUPPETS_VERDICT, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"R": 1, "C": 2})
    script_flips(result)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    alive = {o.name for o in (small, big) if o.zone == Zone.BATTLEFIELD}
    assert alive == {survivor}
