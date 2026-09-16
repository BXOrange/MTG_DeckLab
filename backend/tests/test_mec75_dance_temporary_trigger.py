"""MEC-75 — Subterfuge's temporary, parameterized combat trigger."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _card(name, type_line, *, power=None, toughness=None, oracle_text=""):
    return Card(
        id=name, name=name, type_line=type_line,
        is_creature="Creature" in type_line, power=power, toughness=toughness,
        oracle_text=oracle_text,
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def _put(eng, card, controller="p1", bind=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    if bind:
        bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _resolve_event(eng, event):
    eng.state.fire_event(event)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()


def test_subterfuge_grants_a_real_combat_damage_draw_trigger_until_cleanup():
    eng = _engine()
    subterfuge = _put(
        eng,
        _card(
            "Subterfuge", "Creature — Elemental Incarnation", power=5, toughness=5,
            oracle_text=("When this creature enters, target creature gains flying and "
                         "\"Whenever this creature deals combat damage to a player, "
                         "draw that many cards\" until end of turn."),
        ),
        bind=True,
    )
    target = _put(eng, _card("Target", "Creature — Elemental", power=3, toughness=3))
    player = eng.state.player_by_id("p1")
    for n in range(5):
        player.library.append(GameObject(_card(f"Draw {n}", "Sorcery"), "p1", Zone.LIBRARY))

    # Resolve the ETB through its normal target-selection path.
    _resolve_event(eng, GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=subterfuge.instance_id,
        controller_id="p1", object_types=["creature"],
    ))
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(target.instance_id)
    eng.resolve_until_stable()

    assert "flying" in target.granted_keywords
    assert len(target.granted_triggered_abilities) == 1

    # The grant belongs to this target only, ignores noncombat damage, and
    # reads the actual amount of this combat-damage event.
    _resolve_event(eng, GameEvent(
        EventType.DAMAGE, source_id=target.instance_id, amount=2, combat=False, is_player=True,
    ))
    assert len(player.hand) == 0
    _resolve_event(eng, GameEvent(
        EventType.DAMAGE, source_id=target.instance_id, amount=3, combat=True, is_player=True,
    ))
    assert len(player.hand) == 3

    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert "flying" not in target.granted_keywords
    assert target.granted_triggered_abilities == []


def test_subterfuge_catalogue_keeps_the_event_amount_parameter():
    card = _card("Subterfuge", "Creature — Elemental Incarnation")
    (etb,) = specs_for(card)
    grant = etb.effects[0]
    trigger = grant.params["extra_statics"][0]["params"]
    assert trigger["trigger_event"] == EventType.DAMAGE
    assert trigger["grant_effects"][0]["params"]["count_from_trigger_event"] == "amount"
