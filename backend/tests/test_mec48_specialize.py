"""MEC-48 — the Specialize digital keyword (Alchemy Horizons: Baldur's Gate).

"Specialize {cost}" = "{cost}, Discard a card: this permanent specializes.
Activate only as a sorcery." An Arena-only keyword with no paper CR; its five
per-colour specialized faces aren't in this repo's Scryfall seed, so the
engine models the *activation* + the `SPECIALIZED` event only — a persistent
`GameObject.is_specialized` designation, no characteristic swap (documented
simplification).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state


def _put(st, card, pid="p1", zone=Zone.BATTLEFIELD):
    o = GameObject(card, owner_id=pid, zone=zone)
    o.controller_id = pid
    if zone == Zone.BATTLEFIELD:
        st.add_to_battlefield(o)
    return o


def _specializer(st, pid="p1", extra_text=""):
    txt = "Specialize {2}"
    if extra_text:
        txt += "\n" + extra_text
    o = _put(st, Card(
        id="GALE", name="Gale, Conduit of the Arcane",
        type_line="Legendary Creature — Human Wizard",
        is_creature=True, power=2, toughness=3, mana_cost_string="{3}{U}",
        oracle_text=txt, keywords=["Specialize"],
    ), pid)
    o.summoning_sick = False
    bind_from_catalogue(o)
    return o


# --- parser recognition ---------------------------------------------------


def test_bare_specialize_line_is_modeled():
    card = Card(id="x", name="Rasaad, Monk of Selûne",
                type_line="Legendary Creature — Human Monk", is_creature=True,
                power=2, toughness=3, oracle_text="Specialize {5}",
                keywords=["Specialize"])
    assert parse_oracle(card).modeled is True


def test_specialize_line_with_a_trailing_rider_stays_unmodeled():
    # "Specialize {2}. Activate only if a player has 13 or less life." — the
    # rider is real rules text, not reminder text; fail closed rather than
    # let the keyword line greedily claim it.
    card = Card(id="x", name="Shadowheart, Sharran Cleric",
                type_line="Legendary Creature — Human Cleric", is_creature=True,
                power=2, toughness=3,
                oracle_text="Specialize {2}. Activate only if a player has 13 or less life.",
                keywords=["Specialize"])
    assert parse_oracle(card).modeled is False


def test_specializes_is_a_recognized_trigger_verb():
    card = Card(id="x", name="Klement, Death Acolyte",
                type_line="Legendary Creature — Human Cleric", is_creature=True,
                power=2, toughness=2,
                oracle_text="When this creature specializes, create two 2/2 black Zombie creature tokens.")
    res = parse_oracle(card)
    assert res.modeled is True
    kinds = [e.type for a in res.specs for e in a.effects]
    assert "create_token" in kinds


# --- engine behaviour ---------------------------------------------------


def test_specialize_is_an_offered_sorcery_speed_activated_ability():
    eng, st = _engine()
    gale = _specializer(st)
    p1 = st.player_by_id("p1")
    p1.mana_pool.add_many({"U": 3})
    # needs a card in hand to discard as the additional cost
    p1.hand.append(_put(st, Card(id="h1", name="Filler", type_line="Instant"), "p1", Zone.HAND))

    ability = gale.activated_abilities[0]
    assert ability.cost.discard == 1
    assert ability.cost.sorcery_speed_only is True
    assert eng.can_activate(p1, gale, ability)


def test_activating_specialize_sets_the_flag_and_fires_the_event():
    eng, st = _engine()
    gale = _specializer(st)
    p1 = st.player_by_id("p1")
    p1.mana_pool.add_many({"U": 3})
    p1.hand.append(_put(st, Card(id="h1", name="Filler", type_line="Instant"), "p1", Zone.HAND))

    eng.activate_ability(p1, gale, 0)
    eng.resolve_until_stable()

    assert gale.is_specialized is True
    fired = [e for e in st.event_log if e.type == EventType.SPECIALIZED]
    assert [e.get("instance_id") for e in fired] == [gale.instance_id]


def test_specialize_cannot_be_activated_at_instant_speed():
    eng, st = _engine()
    st.current_step = "upkeep"
    gale = _specializer(st)
    p1 = st.player_by_id("p1")
    p1.mana_pool.add_many({"U": 3})
    p1.hand.append(_put(st, Card(id="h1", name="Filler", type_line="Instant"), "p1", Zone.HAND))

    assert not eng.can_activate(p1, gale, gale.activated_abilities[0])


def test_leaving_the_battlefield_clears_the_specialized_flag():
    eng, st = _engine()
    gale = _specializer(st)
    gale.is_specialized = True
    gale.specialized_color = "U"
    gale.reset_as_new_object()
    assert gale.is_specialized is False
    assert gale.specialized_color is None
