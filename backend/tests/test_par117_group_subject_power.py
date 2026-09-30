"""PAR-117 (group-subject residue) — a power qualifier on the RULE 603.1
group-subject condition: "whenever a creature with power `<n>` or
`<less/greater>` `<verb>`" (Kavu Lair — "…enters, its controller draws a
card."; Marketwatch Phantom — "another creature you control with power 2 or
less enters, this creature gains flying until end of turn.").

The bare group-subject shape closed at PARSER_VERSION 415 (Poisonbelly
Ogre); the colour-qualifier axis closed at PARSER_VERSION 419
(`test_par117_group_subject_color.py`). This is the sibling axis the same
residue bullet named next — confirmed via direct `_trigger_condition()`
calls returning ``None`` for the power-qualified phrasing even though the
bare shape already worked.

No new engine primitive: a "with power `<n>` or `<less/greater>`" fragment
already exists in several one-shot handlers (target filters, damage
filters); this reuses the same regex shape as a qualifier on `_GROUP_
SUBJECT_RE`'s own acting object. `effect_binder._build_group_ok` gained
`min_power`/`max_power` keys read **live** off the board
(`state.find_object(event_instance).power`) rather than snapshotted onto
the event — unlike the colour axis's DIES-shaped cards, every verb this
filter can appear on (ENTERS_BATTLEFIELD, ATTACKS) keeps the acting object
on the battlefield when the trigger condition is checked, so no RULE 400.7
snapshot is needed.

`parser_probe.py diff`: +17 (far more than the 15-card search phrase this
axis was sized against — the regex widening is general, so it also
unblocked several bonus cards using the same "with power `<n>` or
`<less/greater>` `<verb>`" shape with a payoff outside the original search:
Garruk's Packleader, Inspiring Commander, Marketwatch Phantom, Mentor of
the Meek, Neighborhood Guardian, Outcaster Trailblazer, Paleoloth, Snarling
Gorehound, Vicious Clown), 0 regressed. Six cards sharing the original
search phrase stay UNMODELED on their own separate, unrelated clause —
confirmed via `parser_probe.py card`, none attempted here:

- Cavalcade of Calamity / Raid Bombardment: "~ deals 1 damage to the player
  or planeswalker **that creature is attacking**" — a RULE 506.4 referent
  (the acting attacker's own current attack target) no damage effect reads
  yet.
- Life Finds a Way: "…enters, **populate**." — RULE 701.24's populate
  keyword action, unrelated to this trigger.
- MacCready, Lamplight Mayor: its power-qualified ENTERS-shaped ability
  isn't this card's blocker at all — both of its triggers are ATTACKS-
  shaped, and its second one needs the still-open "attacks **you**"
  defending-player axis (this same PAR-117 residue bullet, Hissing
  Miasma's own entry) as well as this power qualifier; fixing only one axis
  can't close a card that needs both.
- Subira, Tulzidi Caravanner: a granted delayed triggered ability
  ("until end of turn, whenever …") from an activated ability's cost line —
  a different activation/delayed-trigger grammar, not a group-subject gap.
- Where Ancients Tread: "you may have ~ deal 5 damage to any target" — an
  unrecognized "you may have `<name>` `<effect>`" wrapper on a resolving
  spell/ability, distinct from the already-shipped mid-body "you may
  `<effect>`" optional node.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
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


def _creature(name, power, toughness=4, controller="p2"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness),
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


def _enter(state, obj):
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
            controller_id=obj.controller_id, object_types=sorted(obj.type_words),
        )
    )


# ---------------------------------------------------------------------------
# PARSER: the condition dict itself
# ---------------------------------------------------------------------------


def test_min_power_condition():
    assert _trigger_condition("a creature with power 4 or greater enters") == {
        "subject": "group", "type": "creature", "controller": "any",
        "other": False, "min_power": 4,
    }


def test_max_power_condition():
    assert _trigger_condition(
        "another creature you control with power 2 or less enters"
    ) == {
        "subject": "group", "type": "creature", "controller": "you",
        "other": True, "max_power": 2,
    }


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Elemental Bond", "Godtracker of Jund", "Kavu Lair",
        "Kiora, Behemoth Beckoner", "Kronch Wrangler", "Mighty Emergence",
        "Temur Ascendancy", "Territorial Boar", "Marketwatch Phantom",
        "Mentor of the Meek",
        "Life Finds a Way",  # head: PAR-119's composed object head; body: populate
        "Subira, Tulzidi Caravanner",  # ENG-47: "until end of turn, whenever …" as a body sentence
        "Where Ancients Tread",  # PAR-130: optional "have it deal" normalization
        "Cavalcade of Calamity", "Raid Bombardment",  # PAR-123: "the player or planeswalker it's attacking"
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: min_power ("or greater") — Kavu Lair
# ---------------------------------------------------------------------------


def test_kavu_lair_fires_off_a_big_creature_entering():
    eng, state, p1, p2 = _engine()
    p2.library.append(GameObject(
        Card(id="pl0", name="L0", type_line="Plains", is_land=True),
        owner_id="p2", zone=Zone.LIBRARY,
    ))
    src = _source("Kavu Lair")
    state.add_to_battlefield(src)
    big = _creature("Big Bear", power=4, controller="p2")
    state.add_to_battlefield(big)
    _enter(state, big)

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert len(p2.hand) == 1


def test_kavu_lair_does_not_fire_off_a_small_creature_entering():
    eng, state, p1, p2 = _engine()
    src = _source("Kavu Lair")
    state.add_to_battlefield(src)
    small = _creature("Small Bear", power=3, controller="p2")
    state.add_to_battlefield(small)
    _enter(state, small)

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0


# ---------------------------------------------------------------------------
# ENGINE: max_power ("or less") — Marketwatch Phantom
# ---------------------------------------------------------------------------


def test_marketwatch_phantom_fires_off_a_small_creature_entering():
    eng, state, p1, p2 = _engine()
    src = _source("Marketwatch Phantom", controller="p1")
    state.add_to_battlefield(src)
    small = _creature("Small Bear", power=2, controller="p1")
    state.add_to_battlefield(small)
    _enter(state, small)

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1


def test_marketwatch_phantom_does_not_fire_off_a_big_creature_entering():
    eng, state, p1, p2 = _engine()
    src = _source("Marketwatch Phantom", controller="p1")
    state.add_to_battlefield(src)
    big = _creature("Big Bear", power=3, controller="p1")
    state.add_to_battlefield(big)
    _enter(state, big)

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0
