"""PAR-117 (group-subject residue) — the "attacks **you**" defending-player
scope on a RULE 603.1 group-subject condition: "whenever a creature attacks
you, its controller loses 1 life." (Hissing Miasma).

The bare group-subject shape closed at PARSER_VERSION 415; the colour and
power qualifiers closed at 419/420. This is the sibling axis the same
residue bullet named next — confirmed via direct `_trigger_condition()`
calls returning ``None`` for "attacks you" even though every other axis on
this same shape already worked.

No new engine primitive: the ATTACKS event already carries a
``defending_player_id`` (`RulesEngine.declare_attackers`/`misc_mixin.py`),
already read by `attacked_player_lowest_life_predicate`'s trigger-level gate
(MEC-28) — this only reads the same field through a second, independent
path: `effect_binder._build_group_ok`'s new ``attacks_you`` key, checked
against this ability's own controller.

MacCready, Lamplight Mayor's own power-**and**-attacks-you-qualified second
ability now parses correctly (both axes combine on the same acting object
without any special-casing — `_GROUP_SUBJECT_RE`'s qualifiers are
independent optional groups), but the card as a whole stays UNMODELED: its
*first* ability ("…attacks, it gains skulk until end of turn") needs a
different referent — a group-subject *self* grant ("it" meaning the acting
object, not "its controller") — that no existing row reads yet. Confirmed
via `parser_probe.py card`, not attempted here.

A much larger sibling shape was found sizing this axis and is deliberately
**not** attempted here: "whenever a creature attacks you **or a
planeswalker you control**" (RULE 506.4c's full defending-permanent
spelling — Blood Reckoning, Isperia Supreme Judge, Revenge of Ravens, …,
12 SOLO cards via `parser_probe.py blocked
"whenever an? .*creature.* attacks you"`). That needs a real new engine
surface first: `RulesEngine.declare_attackers`'s ATTACKS event only ever
stamps a *player* id into `defending_player_id` (a planeswalker-kind
`combat_defender` spec carries `instance_id`, not `id`, so the field is
already `None` for those attacks, not a latent bug) — reading "a
planeswalker you control" needs the defender's own controller resolved off
`combat_defender`'s `instance_id`, which no event field carries today. See
`BACKLOG.md`'s PAR-117 entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.player import Player
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


def _creature(name, controller="p2"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
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


def _attack(state, obj, defending_player_id):
    obj.attacking = True
    state.fire_event(
        GameEvent(
            EventType.ATTACKS, attacker=obj.name, player_id=obj.controller_id,
            instance_id=obj.instance_id, object_types=sorted(obj.type_words),
            defending_player_id=defending_player_id,
        )
    )


# ---------------------------------------------------------------------------
# PARSER: the condition dict itself
# ---------------------------------------------------------------------------


def test_attacks_you_condition():
    assert _trigger_condition("a creature attacks you") == {
        "subject": "group", "type": "creature", "controller": "any",
        "other": False, "attacks_you": True,
    }


def test_power_and_attacks_you_combine():
    assert _trigger_condition("a creature with power 4 or greater attacks you") == {
        "subject": "group", "type": "creature", "controller": "any",
        "other": False, "min_power": 4, "attacks_you": True,
    }


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_hissing_miasma_becomes_modeled():
    result = parse_oracle(_db().get_card("Hissing Miasma"))
    assert result.modeled, result.unclaimed


def test_maccready_becomes_modeled_when_its_group_subject_gains_skulk():
    result = parse_oracle(_db().get_card("MacCready, Lamplight Mayor"))
    assert result.modeled, result.unclaimed


# ---------------------------------------------------------------------------
# ENGINE: only fires when the defending player is this ability's controller
# ---------------------------------------------------------------------------


def test_hissing_miasma_fires_when_the_attacker_targets_its_controller():
    eng, state, p1, p2 = _engine()
    src = _source("Hissing Miasma", controller="p1")
    state.add_to_battlefield(src)
    attacker = _creature("Bear", controller="p2")
    state.add_to_battlefield(attacker)
    _attack(state, attacker, defending_player_id="p1")

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert p2.life == 19  # the attacking creature's own controller lost the life


def test_hissing_miasma_does_not_fire_when_attacking_someone_else():
    eng, state, p1, p2 = _engine()
    state.players.append(Player(id="p3", name="Carol", life=20))
    src = _source("Hissing Miasma", controller="p1")
    state.add_to_battlefield(src)
    attacker = _creature("Bear", controller="p2")
    state.add_to_battlefield(attacker)
    _attack(state, attacker, defending_player_id="p3")

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0
