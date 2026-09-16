"""PAR-117 (group-subject residue) — a colour qualifier on the RULE 603.1
group-subject condition: "whenever a **green** creature dies" (Bereavement),
"whenever another **white** creature you control enters" (the RTR "Denizen"
cycle — Court Street/Foundry Street/Sage's Row/Shadow Alley Denizen), "…a
**green** creature you control enters" (Ivy Lane Denizen, Sylvan Anthem),
"…a **black** creature you control dies" (Teysa, Orzhov Scion), "…a
**white** creature you control attacks" (Linden, the Steadfast Queen).

The bare group-subject shape (no qualifier) closed at PARSER_VERSION 415
(Poisonbelly Ogre, `test_par117_group_subject_controller.py`); this residue
sub-bullet listed the qualifier itself as the blocker, confirmed via direct
`_trigger_condition()` calls returning ``None`` for every colour-qualified
phrasing. A single new ``color`` key on `_GROUP_SUBJECT_RE`/`_group_subject_
condition` (segmenter.py) and `effect_binder._build_group_ok` (binding/
core.py) — a WUBRG letter, checked the same "event snapshot, live-board
fallback" way `tword`/`want_nonland` already are. RULE 400.7 means a DIES-
shaped condition (Bereavement, Teysa) needs the colour snapshotted onto the
firing event, since a live re-lookup after the object has left the
battlefield finds nothing — added alongside the already-snapshotted
``object_types``/``subtypes`` in the DIES event's one firing site
(`damage_death_mixin.py`). An ENTERS_BATTLEFIELD/ATTACKS-shaped condition
(every other card here) needs no snapshot at all: the acting object is still
on the battlefield when the trigger condition is checked, so the existing
live-lookup fallback (`state.find_object(event_instance).colors`) already
covers it.

`parser_probe.py diff`: +9 on this sub-bullet alone (Bereavement, Court
Street Denizen, Foundry Street Denizen, Ivy Lane Denizen, Linden, the
Steadfast Queen, Sage's Row Denizen, Shadow Alley Denizen, Sylvan Anthem,
Teysa, Orzhov Scion), 0 regressed. Two cards sharing the same search phrase
stay UNMODELED on their own unrelated gap, confirmed via `parser_probe.py
card` — the colour condition itself now parses and fires correctly on both,
just gated behind a separate unclaimed clause: Dire Undercurrents ("you may
have target player draw a card" — a distinct effect-body shape, not a
referent or condition gap) and Yorvo, Lord of Garenbrig ("if that creature's
power is greater than ~'s power" — a comparative condition on the entering
creature's own power vs. the source's, unrelated to this ticket). Justice
("whenever a red creature **or spell** deals damage, …") is a different
trigger family entirely (`_DAMAGE_TRIGGER_RE`, a creature-or-spell compound
subject) and was not attempted here.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle, UNMODELED
from mtg_analyzer.parser.oracle.segmenter import _trigger_condition
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _creature(name, color_identity, power=2, toughness=2, controller="p2"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness, color_identity=color_identity),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def _source(name, controller="p1"):
    src = GameObject(_db().get_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    src.controller_id = controller
    src.summoning_sick = False
    bind_from_catalogue(src)
    return src


# ---------------------------------------------------------------------------
# PARSER: the condition dict itself
# ---------------------------------------------------------------------------


def test_bare_color_condition():
    assert _trigger_condition("a green creature dies") == {
        "subject": "group", "type": "creature", "controller": "any",
        "other": False, "color": "G",
    }


def test_another_color_you_control_condition():
    assert _trigger_condition("another white creature you control enters") == {
        "subject": "group", "type": "creature", "controller": "you",
        "other": True, "color": "W",
    }


def test_no_color_word_leaves_color_key_absent():
    assert _trigger_condition("another creature you control enters") == {
        "subject": "group", "type": "creature", "controller": "you", "other": True,
    }


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Bereavement", "Court Street Denizen", "Foundry Street Denizen",
        "Ivy Lane Denizen", "Linden, the Steadfast Queen", "Sage's Row Denizen",
        "Shadow Alley Denizen", "Sylvan Anthem", "Teysa, Orzhov Scion",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


def test_dire_undercurrents_and_yorvo_stay_unmodeled_on_unrelated_gaps():
    for name in ("Dire Undercurrents", "Yorvo, Lord of Garenbrig"):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.coverage is UNMODELED


# ---------------------------------------------------------------------------
# ENGINE: DIES-shaped — the colour must be snapshotted (RULE 400.7)
# ---------------------------------------------------------------------------


def test_bereavement_fires_off_a_green_creature_dying():
    eng, state, p1, p2 = _engine()
    hand_card = GameObject(
        Card(id="c1", name="C1", type_line="Sorcery", is_sorcery=True),
        owner_id="p2", zone=Zone.HAND,
    )
    p2.add_to_zone(hand_card, Zone.HAND)
    src = _source("Bereavement")
    state.add_to_battlefield(src)
    victim = _creature("Verdant Bear", {"G"})
    state.add_to_battlefield(victim)

    eng.rules.destroy(victim)
    placed = eng.rules.put_triggers_on_stack()

    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert len(p2.hand) == 0  # discarded its one card


def test_bereavement_does_not_fire_off_a_non_green_creature_dying():
    eng, state, p1, p2 = _engine()
    hand_card = GameObject(
        Card(id="c1", name="C1", type_line="Sorcery", is_sorcery=True),
        owner_id="p2", zone=Zone.HAND,
    )
    p2.add_to_zone(hand_card, Zone.HAND)
    src = _source("Bereavement")
    state.add_to_battlefield(src)
    victim = _creature("Crimson Bear", {"R"})
    state.add_to_battlefield(victim)

    eng.rules.destroy(victim)
    placed = eng.rules.put_triggers_on_stack()

    assert placed == 0
    assert len(p2.hand) == 1  # the gate stayed closed — nothing discarded


# ---------------------------------------------------------------------------
# ENGINE: ENTERS-shaped — the live-board fallback (no snapshot needed)
# ---------------------------------------------------------------------------


def test_ivy_lane_denizen_fires_off_another_green_creature_entering():
    eng, state, p1, p2 = _engine()
    src = _source("Ivy Lane Denizen", controller="p2")
    state.add_to_battlefield(src)
    newcomer = _creature("Verdant Bear", {"G"}, controller="p2")
    state.add_to_battlefield(newcomer)
    from mtg_analyzer.models.game.events import EventType, GameEvent
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=newcomer.instance_id,
            controller_id="p2", object_types=sorted(newcomer.type_words),
        )
    )

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1


def test_ivy_lane_denizen_does_not_fire_off_a_non_green_creature_entering():
    eng, state, p1, p2 = _engine()
    src = _source("Ivy Lane Denizen", controller="p2")
    state.add_to_battlefield(src)
    newcomer = _creature("Crimson Bear", {"R"}, controller="p2")
    state.add_to_battlefield(newcomer)
    from mtg_analyzer.models.game.events import EventType, GameEvent
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=newcomer.instance_id,
            controller_id="p2", object_types=sorted(newcomer.type_words),
        )
    )

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0
