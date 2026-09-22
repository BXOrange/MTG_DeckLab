"""PAR-120 — "that player" as an alternate spelling of the existing
"its controller"/"that creature's controller" referent family, plus the
one shape that needed a genuinely different referent instead.

`_CONTROLLER_REFERENT` (`catalogue/handlers.py`) widened to accept "that
player" alongside its two existing phrasings, resolving through the same
unchanged `{"of": "previous_target", "as": "controller"}` operand
(`effect_operands._derive`) under every subject mode that already dispatches
"its controller" (`previous_subject_only`, `group_subject_only`,
`attached_subject_only`) — no new referent, no new engine surface. `_derive`
already disambiguates the two antecedent shapes this pronoun can follow: a
referent that already resolved to a `Player` (a preceding "target player"/
"target opponent" clause) is returned as-is rather than looked up by
`.controller_id`, and a referent that is a `GameObject` (an exiled/dying/
destroyed permanent) has its `.controller_id`/`.owner_id` read the same way
"its controller" always has. `MillEffect`'s own `"previous_subject_
controller"` selector (`effects/stack.py`) needed the identical passthrough
added by hand, since it doesn't go through `effect_operands` at all.

One sibling shape needed real new grammar, not just a wider phrase table:
"whenever a creature attacks 1 of your opponents, that player loses N
life." (Calculating Lich) is a RULE 603.1 group-subject trigger where "that
player" is *not* the group subject's controller (the attacking creature's
controller can be either player) — it's RULE 506.4's defending player, a
distinct ATTACKS-event field. Reusing the generic group-subject "its
controller" dispatch here would have silently read the wrong side of the
attack, so this shape is caught by its own narrow regex
(`segmenter._ATTACKS_OPPONENT_THAT_PLAYER_LIFE_RE`) before the generic
dispatch ever sees it, emitting a new `{"of": "attacked_player"}` referent
(`effect_conditions.subject_of`, reading the ATTACKS event's own
`defending_player_id`) instead. The trigger condition itself gained a new
`attacks_opponent` qualifier (`_GROUP_SUBJECT_RE`, `_build_group_ok`) —
*any* living opponent of the ability's controller, distinct from the
existing `attacks_you`'s one fixed player — which also reaches sibling
cards paying no attention to "that player" at all (Genestealer Locus: "…
attacks 1 of your opponents, it gets +0/+1…").

`parser_probe.py diff` (cumulative with the referent-state/cast-provenance
slice in `test_par120_referent_state.py`): +22, 0 regressed.
"""

from __future__ import annotations

import re

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.handlers import _CONTROLLER_REFERENT
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _trigger_condition, parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

_PREVIOUS_TARGET_CONTROLLER = {"of": "previous_target", "as": "controller"}


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _spec_source(name, controller="p1", zone=Zone.STACK):
    src = GameObject(_db().get_card(name), owner_id=controller, zone=zone)
    src.controller_id = controller
    bind_from_catalogue(src)
    return src


def _spell_effect_spec(src):
    for spec in parse_oracle(src.card).specs:
        if spec.effects:
            return spec.effects
    raise AssertionError(f"no effect-bearing spec for {src.card.name}")


def _run(eng, src, specs, targets=None):
    effs = build_effects(specs, src)
    _apply_effects_partitioned(effs, eng.rules.context, targets, None, source=src)


# ---------------------------------------------------------------------------
# PARSER: "that player" reaches the unchanged controller-referent dispatch
# ---------------------------------------------------------------------------


def test_that_player_is_a_third_spelling_of_the_controller_referent():
    pattern = re.compile(_CONTROLLER_REFERENT)
    assert pattern.fullmatch("its controller")
    assert pattern.fullmatch("that creature's controller")
    assert pattern.fullmatch("that player")
    assert not pattern.fullmatch("that players")


def test_that_player_loses_life_under_previous_subject():
    assert parse_effect_body(
        "that player loses 1 life", previous_subject=True,
    ) == [EffectSpec("lose_life", {"amount": 1, "player": _PREVIOUS_TARGET_CONTROLLER})]


def test_that_player_gains_life_under_group_subject_reads_the_entering_controller():
    # Group mode dispatches through a *different* builder than previous-
    # subject mode (`_group_its_controller_gains_life`), always naming
    # ``entering``'s controller rather than `previous_target`'s.
    assert parse_effect_body(
        "that player gains 2 life", group_subject=True,
    ) == [EffectSpec("gain_life", {
        "amount": 2, "player": {"of": "entering", "as": "controller"},
    })]


# ---------------------------------------------------------------------------
# PARSER: the "attacks 1 of your opponents" condition + its own referent
# ---------------------------------------------------------------------------


def test_attacks_opponent_condition():
    assert _trigger_condition("a creature attacks 1 of your opponents") == {
        "subject": "group", "type": "creature", "controller": "any",
        "other": False, "attacks_opponent": True,
    }


def test_calculating_lich_reads_the_defending_player_not_the_attackers_controller():
    card = _db().get_card("Calculating Lich")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    effects = [s for s in result.specs if s.effects][0].effects
    assert effects == [EffectSpec("lose_life", {
        "amount": 1, "player": {"of": "attacked_player"},
    })]


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Carrion Locust", "Massacre Wurm", "Assault Intercessor", "Fell Specter",
        "Liliana's Caress", "Raiders' Wake", "Genestealer Locus",
        "Sword of Body and Mind", "Nightshade Harvester", "Polluted Bonds",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def _graveyard_card(state, name, types="Creature — Bear", is_creature=True, owner="p2"):
    card = Card(id=name, name=name, type_line=types, is_creature=is_creature,
                power=1 if is_creature else None, toughness=1 if is_creature else None)
    obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
    state.player_by_id(owner).graveyard.append(obj)
    return obj


def test_carrion_locust_drains_the_graveyards_owner_off_an_object_referent():
    eng, state, p1, p2 = _engine()
    victim = _graveyard_card(state, "Dead Bear")
    src = _spec_source("Carrion Locust", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(src)

    specs = _spell_effect_spec(src)
    life = p2.life
    _run(eng, src, specs, targets=[victim])

    assert p2.life == life - 1  # the exiled card's owner, read via .controller_id


def _creature(state, name, controller="p2"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_massacre_wurm_group_subject_reads_the_dying_creatures_own_controller():
    eng, state, p1, p2 = _engine()
    src = _spec_source("Massacre Wurm", controller="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(src)
    victim = _creature(state, "Doomed Bear", controller="p2")

    state.fire_event(GameEvent(
        EventType.DIES, object=victim.name, controller_id="p2",
        instance_id=victim.instance_id, object_types=["creature"],
    ))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert p2.life == 18  # -2/-2 to all + the "its controller loses 2 life" clause


def _attack(state, obj, defending_player_id):
    obj.attacking = True
    state.fire_event(GameEvent(
        EventType.ATTACKS, attacker=obj.name, player_id=obj.controller_id,
        instance_id=obj.instance_id, object_types=sorted(obj.type_words),
        defending_player_id=defending_player_id,
    ))


def test_calculating_lich_drains_the_defender_regardless_of_who_controls_the_attacker():
    eng, state, p1, p2 = _engine()
    state.players.append(Player(id="p3", name="Carol", life=20))
    src = _spec_source("Calculating Lich", controller="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(src)
    # The attacker is p1's OWN creature — "that player" must still be the
    # defender (p3), never the attacker's controller (p1) or this ability's
    # own controller (also p1), which the generic "its controller" dispatch
    # would have wrongly read had this shape reused it.
    attacker = _creature(state, "Raider", controller="p1")
    _attack(state, attacker, defending_player_id="p3")

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    p3 = state.player_by_id("p3")
    assert p3.life == 19
    assert p1.life == 20
