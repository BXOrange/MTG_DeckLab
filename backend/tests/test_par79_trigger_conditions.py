"""PAR-79 fifth increment — cast/attack *trigger-condition* recognition.

Diagnosing the 61-card SOLO residue left after PAR-79's fourth increment
found that most of it wasn't actually about `UnblockableEffect` at all: the
card's own "can't be blocked this turn" clause (or a pump-and-unblockable
compound) already parses fine — the real blocker is an unrecognized
*trigger condition* sitting in front of it (Merfolk Cave-Diver/Sahagin/
Snooping Page/Prismari Apprentice/Hraesvelgr of the First Brood/Undercover
Butler/Martha Jones/Matterbending Mage, checked individually via
`parser_probe.py card`). This batch closes the shared-grammar axes found
that way, applying handler-recipe.md's "decompose into atomic grammar
units" rule at the trigger-condition level rather than the single-clause
level PAR-78/PAR-79's earlier increments applied it at:

- **"Whenever you cast a spell with mana value N or greater, …"** —
  `effect_binder`'s `spell_mana_value_at_least` predicate already existed
  (built for PAR-60's *typed* "…instant or sorcery spell with mana value 5
  or greater…" cluster, reached through `_CAST_SPELL_TRIGGER_RE`'s own
  ``types`` slot) but had **no bare, untyped recognizer at all** — the same
  dead-primitive shape `spell_has_x`/`first_x_spell` turned out to have
  (next item). `_CAST_SPELL_TRIGGER_MV_AT_LEAST_RE` is the ``>=`` mirror of
  the already-shipped `_CAST_SPELL_TRIGGER_MV_RE` ("…or less").
- **"Whenever you cast a spell with {X} in its mana cost, …"** — same gap
  shape: `spell_has_x`/`first_x_spell` (PAR-60, Elementalist's Palette/
  Quandrix {X}-first-spell cluster) had zero segmenter regex reaching them.
  `_CAST_SPELL_TRIGGER_X_RE`/`_CAST_SPELL_TRIGGER_FIRST_X_RE`.
- **"When ~ enters and whenever you cast <cast-trigger clause>, …"** — RULE
  603.1's compound-trigger-sharing-one-body shape (`_ETB_AND_CAST_TRIGGER_RE`,
  dispatched in `segment_line` before any single-trigger regex). Rather than
  fuse a new "ETB-or-cast" condition or re-derive every cast-trigger filter a
  second time, this reconstructs each half as its own ordinary trigger line
  and re-enters `segment_line` on it — reusing the *entire* existing ETB and
  cast-trigger grammar (mana value, card type, subtype, …) rather than
  duplicating any of it. Two independent `AbilitySpec`s sharing one effects
  list (`Segment.extra_specs`, the same idiom PAR-75's Doctor/companion
  OR-of-two-conditions split uses) — RULE 603.2 fires each independently.
- **"Whenever ~ attacks the player with the most life or tied for most
  life, …"** — the RULE 603.4 ``>=`` mirror of the already-shipped
  `attacked_player_has_lowest_life` gate (PAR-32's "if no opponent has more
  life than that player" cycle), via the new
  `defender_has_most_life_predicate` (`game/binding/core.py`) and
  `_ATTACKS_DEFENDER_MOST_LIFE_RE` (`parser/oracle/segmenter.py`), mirroring
  `_ATTACKS_DEFENDER_LANDS_RE`'s own dispatch shape.

+18 cards (`parser_probe.py diff`), 0 regressed — of which only two
(Hraesvelgr of the First Brood, Matterbending Mage, Undercover Butler — the
third is a PAR-79 SOLO card too) sit on PAR-79's own "can't be blocked this
turn" search phrase; the rest (Angry Rabble, Brinelin the Moon Kraken,
Enraged Flamecaster, Etherium Spinner, Flaring Cinder, …) are the "widened
shared primitive reaches cards outside your own ticket" signal
handler-recipe.md's own decomposition rule calls out as evidence the fix
belongs at the axis, not the phrase.
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _segment(text):
    return segment_line(
        text, allow_spell_effect=False, provenance=ParserProvenance.from_dict({})
    )


def _filler_library(prefix, count=10):
    return [
        Card(id=f"{prefix}{i}", name=f"{prefix} Forest {i}",
             type_line="Basic Land — Forest")
        for i in range(count)
    ]


def _engine():
    return GameEngine.new_game(
        [("p1", "A", _filler_library("p1")), ("p2", "B", _filler_library("p2"))],
        starting_life=20, starting_hand=0,
    )


def _to_hand(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    bind_from_catalogue(obj)
    engine.state.player_by_id(controller).hand.append(obj)
    return obj


def _bf(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _reach_main(engine):
    engine.begin_turn()
    engine.state.current_step = "main1"
    engine.recompute_continuous_effects()


def _instant(name, cost, mv, x=False):
    return Card(
        id=name, name=name, type_line="Instant", is_instant=True,
        mana_cost_string=cost, converted_mana_cost=mv,
    )


def _artifact(name, cost, mv):
    return Card(
        id=name, name=name, type_line="Artifact",
        mana_cost_string=cost, converted_mana_cost=mv,
    )


# ---------------------------------------------------------------------------
# parse: mana-value-at-least cast trigger
# ---------------------------------------------------------------------------


def test_mana_value_at_least_cast_trigger_parses():
    seg = _segment("whenever you cast a spell with mana value 4 or greater, draw a card")
    assert seg.claimed
    assert seg.spec.trigger["event"] == "SPELL_CAST"
    assert seg.spec.trigger["condition"] == {"subject": "you"}
    assert seg.spec.trigger["spell_mana_value_at_least"] == 4


def test_mana_value_at_least_cast_trigger_subject_scoping():
    seg = _segment("whenever an opponent casts a spell with mana value 2 or greater, draw a card")
    assert seg.spec.trigger["condition"] == {"subject": "group", "controller": "not_you"}


# ---------------------------------------------------------------------------
# parse: {X}-in-mana-cost cast triggers
# ---------------------------------------------------------------------------


def test_x_in_mana_cost_cast_trigger_parses():
    seg = _segment("whenever you cast a spell with {x} in its mana cost, draw a card")
    assert seg.claimed
    assert seg.spec.trigger["event"] == "SPELL_CAST"
    assert seg.spec.trigger["spell_has_x"] is True


def test_first_x_spell_cast_trigger_parses():
    seg = _segment(
        "whenever you cast your first spell with {x} in its mana cost each turn, draw a card"
    )
    assert seg.claimed
    assert seg.spec.trigger["first_x_spell"] is True


# ---------------------------------------------------------------------------
# parse: "historic spell" cast trigger
# ---------------------------------------------------------------------------


def test_historic_spell_cast_trigger_parses():
    seg = _segment("whenever you cast a historic spell, draw a card")
    assert seg.claimed
    assert seg.spec.trigger["event"] == "SPELL_CAST"
    assert seg.spec.trigger["spell_is_historic"] is True


def test_historic_spell_cast_trigger_picks_up_the_once_per_turn_tail():
    seg = _segment(
        "whenever you cast a historic spell, draw a card. "
        "this ability triggers only once each turn."
    )
    assert seg.claimed
    assert seg.spec.trigger["limit"] is True


# ---------------------------------------------------------------------------
# parse: the compound ETB-and-cast trigger split
# ---------------------------------------------------------------------------


def test_etb_and_cast_trigger_splits_into_two_specs():
    seg = _segment(
        "when ~ enters and whenever you cast a noncreature spell, draw a card"
    )
    assert seg.claimed
    assert seg.spec is not None
    assert len(seg.extra_specs) == 1
    kinds = {seg.spec.trigger["event"], seg.extra_specs[0].trigger["event"]}
    assert kinds == {"ENTERS_BATTLEFIELD", "SPELL_CAST"}
    cast_spec = seg.spec if seg.spec.trigger["event"] == "SPELL_CAST" else seg.extra_specs[0]
    assert cast_spec.trigger["spell_exclude_card_types"] == ["creature"]


def test_etb_and_cast_trigger_accepts_whenever_for_the_etb_half():
    # Angel of Unity prints "whenever ~ enters and whenever …", not "when".
    seg = _segment(
        "whenever ~ enters and whenever you cast a spell with mana value 5 or greater, draw a card"
    )
    assert seg.claimed
    assert len(seg.extra_specs) == 1


def test_etb_and_cast_trigger_fails_closed_on_an_unrecognized_cast_clause():
    # "from your graveyard" has no cast-trigger recognizer — both halves
    # must be claimable, or the whole compound stays unclaimed (fail-closed),
    # not silently dropping the cast half.
    seg = _segment(
        "when ~ enters and whenever you cast a spell from your graveyard, draw a card"
    )
    assert not seg.claimed


def test_plain_etb_trigger_is_unaffected():
    seg = _segment("when ~ enters, draw a card")
    assert seg.claimed
    assert seg.spec.trigger["event"] == "ENTERS_BATTLEFIELD"
    assert not seg.extra_specs


# ---------------------------------------------------------------------------
# parse: "attacks the player with the most life or tied for most life"
# ---------------------------------------------------------------------------


def test_attacks_defender_most_life_parses():
    seg = _segment(
        "whenever ~ attacks the player with the most life or tied for most life, draw a card"
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == "ATTACKS"
    assert seg.spec.trigger["condition"] == {"subject": "self"}
    assert seg.spec.trigger["attacked_player_has_most_life"] is True


def test_plain_attacks_a_player_has_no_most_life_key():
    seg = _segment("whenever ~ attacks a player, draw a card")
    assert "attacked_player_has_most_life" not in seg.spec.trigger


# ---------------------------------------------------------------------------
# real cards
# ---------------------------------------------------------------------------


def test_real_cards_now_modeled():
    for name in [
        "Hraesvelgr of the First Brood",
        "Matterbending Mage",
        "Undercover Butler",
        "Angry Rabble",
        "Etherium Spinner",
        "Brinelin, the Moon Kraken",
        "Up the Beanstalk",
        "Jhoira, Weatherlight Captain",
    ]:
        card = _named(name)
        assert card is not None, name
        res = parse_oracle(card)
        assert res.modeled, (name, res.unclaimed)


# ---------------------------------------------------------------------------
# execute: mana-value-at-least threshold actually gates the trigger
# ---------------------------------------------------------------------------


def test_angry_rabble_only_punishes_expensive_spells():
    engine = _engine()
    _bf(engine, _named("Angry Rabble"), controller="p1")
    _reach_main(engine)
    p1 = engine.state.player_by_id("p1")
    p2 = engine.state.player_by_id("p2")

    cheap = _to_hand(engine, _instant("Cheap", "{R}", 1), controller="p1")
    p1.mana_pool.add("R", 1)
    life_before = p2.life
    engine.cast_spell(p1, cheap, targets=None)
    engine.resolve_until_stable()
    assert p2.life == life_before  # mana value 1 < 4 -> no trigger

    big = _to_hand(engine, _instant("Big", "{4}", 4), controller="p1")
    p1.mana_pool.add("C", 4)
    life_before = p2.life
    engine.cast_spell(p1, big, targets=None)
    engine.resolve_until_stable()
    assert p2.life == life_before - 1  # mana value 4 >= 4 -> triggers


# ---------------------------------------------------------------------------
# execute: {X}-in-mana-cost gates the trigger
# ---------------------------------------------------------------------------


def test_matterbending_mage_only_unblockable_off_an_x_spell():
    engine = _engine()
    mage = _bf(engine, _named("Matterbending Mage"), controller="p1")
    _reach_main(engine)
    p1 = engine.state.player_by_id("p1")

    no_x = _to_hand(engine, _instant("NoX", "{U}", 1), controller="p1")
    p1.mana_pool.add("U", 1)
    engine.cast_spell(p1, no_x, targets=None)
    engine.resolve_until_stable()
    assert not getattr(mage, "temp_unblockable", False)

    x_spell = _to_hand(engine, _instant("XSpell", "{X}{U}", 1), controller="p1")
    p1.mana_pool.add("U", 1)
    engine.cast_spell(p1, x_spell, targets=None, x=0)
    engine.resolve_until_stable()
    assert mage.temp_unblockable is True


# ---------------------------------------------------------------------------
# execute: "historic spell" gates the trigger
# ---------------------------------------------------------------------------


def test_jhoira_only_draws_off_a_historic_spell():
    engine = _engine()
    _bf(engine, _named("Jhoira, Weatherlight Captain"), controller="p1")
    _reach_main(engine)
    p1 = engine.state.player_by_id("p1")

    plain = _to_hand(engine, _instant("Plain", "{U}", 1), controller="p1")
    p1.mana_pool.add("U", 1)
    hand_before = len(p1.hand)
    engine.cast_spell(p1, plain, targets=None)
    engine.resolve_until_stable()
    assert len(p1.hand) == hand_before - 1  # not historic -> no bonus draw

    gadget = _to_hand(engine, _artifact("Gadget", "{1}", 1), controller="p1")
    p1.mana_pool.add("C", 1)
    hand_before = len(p1.hand)
    engine.cast_spell(p1, gadget, targets=None)
    engine.resolve_until_stable()
    # -1 for Gadget leaving the hand, +1 from Jhoira's historic-spell draw.
    assert len(p1.hand) == hand_before


# ---------------------------------------------------------------------------
# execute: compound ETB + cast trigger both fire off one printed line
# ---------------------------------------------------------------------------


def test_up_the_beanstalk_draws_on_etb_and_on_a_big_spell():
    engine = _engine()
    p1 = engine.state.player_by_id("p1")
    beanstalk = _to_hand(engine, _named("Up the Beanstalk"), controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("C", 1)

    hand_before = len(p1.hand)
    engine.cast_spell(p1, beanstalk, targets=None)
    engine.resolve_until_stable()
    # -1 for Up the Beanstalk leaving the hand, +1 from its own ETB draw.
    assert len(p1.hand) == hand_before

    small = _to_hand(engine, _instant("Small", "{1}", 1), controller="p1")
    p1.mana_pool.add("C", 1)
    hand_before = len(p1.hand)
    engine.cast_spell(p1, small, targets=None)
    engine.resolve_until_stable()
    assert len(p1.hand) == hand_before - 1  # mana value 1 < 5 -> no bonus draw

    big = _to_hand(engine, _instant("Big", "{5}", 5), controller="p1")
    p1.mana_pool.add("C", 5)
    hand_before = len(p1.hand)
    engine.cast_spell(p1, big, targets=None)
    engine.resolve_until_stable()
    # -1 for Big leaving the hand, +1 from Up the Beanstalk's cast trigger.
    assert len(p1.hand) == hand_before


# ---------------------------------------------------------------------------
# execute: "attacks the player with the most life" predicate
# ---------------------------------------------------------------------------


class _Ctx:
    def __init__(self, st):
        self.state = st


def _attacker_and_ability():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_life=20, starting_hand=0,
    )
    st = eng.state
    src = GameObject(
        Card(id="s", name="S", type_line="Creature", is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec
    spec = AbilitySpec(
        "triggered", effects=[EffectSpec("draw", {"count": 1})],
        trigger={"event": "ATTACKS", "condition": {"subject": "self"},
                 "attacked_player_has_most_life": True},
    )
    return eng, st, src, bind_ability(spec, src)


def test_most_life_predicate_true_for_the_sole_leader():
    eng, st, src, ab = _attacker_and_ability()
    st.player_by_id("p2").life = 30
    st.player_by_id("p3").life = 20
    ev = GameEvent(EventType.ATTACKS, player_id="p1",
                   instance_id=src.instance_id, defending_player_id="p2")
    assert ab.condition(ev, _Ctx(st)) is True


def test_most_life_predicate_true_on_a_tie():
    eng, st, src, ab = _attacker_and_ability()
    st.player_by_id("p2").life = 20
    st.player_by_id("p3").life = 20
    ev = GameEvent(EventType.ATTACKS, player_id="p1",
                   instance_id=src.instance_id, defending_player_id="p2")
    assert ab.condition(ev, _Ctx(st)) is True


def test_most_life_predicate_false_when_defender_trails():
    eng, st, src, ab = _attacker_and_ability()
    st.player_by_id("p2").life = 10
    st.player_by_id("p3").life = 20
    ev = GameEvent(EventType.ATTACKS, player_id="p1",
                   instance_id=src.instance_id, defending_player_id="p2")
    assert ab.condition(ev, _Ctx(st)) is False


# ---------------------------------------------------------------------------
# parse + execute: "if at least N mana was spent to cast it" (Sahagin)
# ---------------------------------------------------------------------------


def test_mana_spent_at_least_intervening_if_parses():
    seg = _segment(
        "whenever you cast a noncreature spell, if at least 4 mana was "
        "spent to cast it, put a +1/+1 counter on ~ and it can't be "
        "blocked this turn"
    )
    assert seg.claimed
    assert seg.spec.trigger["spell_exclude_card_types"] == ["creature"]
    assert seg.spec.trigger["spell_mana_spent_at_least"] == 4


def test_plain_noncreature_trigger_has_no_mana_spent_key():
    seg = _segment("whenever you cast a noncreature spell, draw a card")
    assert "spell_mana_spent_at_least" not in seg.spec.trigger


def test_sahagin_is_now_modeled():
    card = _named("Sahagin")
    assert card is not None
    res = parse_oracle(card)
    assert res.modeled, res.unclaimed


def test_sahagin_only_gets_the_bonus_off_an_expensive_noncreature_spell():
    engine = _engine()
    sahagin = _bf(engine, _named("Sahagin"), controller="p1")
    _reach_main(engine)
    p1 = engine.state.player_by_id("p1")

    cheap = _to_hand(engine, _instant("Cheap", "{U}", 1), controller="p1")
    p1.mana_pool.add("U", 1)
    engine.cast_spell(p1, cheap, targets=None)
    engine.resolve_until_stable()
    assert not getattr(sahagin, "temp_unblockable", False)
    assert sahagin.counters.get("+1/+1", 0) == 0

    big = _to_hand(engine, _instant("Big", "{4}", 4), controller="p1")
    p1.mana_pool.add("C", 4)
    engine.cast_spell(p1, big, targets=None)
    engine.resolve_until_stable()
    assert sahagin.temp_unblockable is True
    assert sahagin.counters.get("+1/+1", 0) == 1
