from mtg_analyzer.models.game.game_object import Zone
import pytest


@pytest.mark.parametrize("owner", ["p1", "p2"])
def test_burn_away_exiles_the_death_controllers_graveyard_not_the_owner(owner):
    from tests.support.deck_batch import game, card, filler, cast
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    engine = game()
    spell = card(engine, "Burn Away", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    own = filler(engine, "Our old card", zone=Zone.GRAVEYARD)
    other = filler(engine, "Their old card", player="p2", zone=Zone.GRAVEYARD)
    victim = filler(engine, "Victim", player=owner, power=1, toughness=5)
    victim.controller_id = "p2"
    cast(engine, spell, targets=[victim])
    assert other.zone == Zone.EXILE
    assert own.zone == spell.zone == Zone.GRAVEYARD
    assert victim.zone == (Zone.EXILE if owner == "p2" else Zone.GRAVEYARD)


def test_burn_away_surviving_target_does_not_immediately_exile_a_graveyard():
    from tests.support.deck_batch import game, card, filler, cast

    engine = game()
    spell = card(engine, "Burn Away", zone=Zone.HAND)
    other = filler(engine, "Their old card", player="p2", zone=Zone.GRAVEYARD)
    victim = filler(engine, "Victim", player="p2", power=1, toughness=8)
    cast(engine, spell, targets=[victim])
    assert victim.zone == Zone.BATTLEFIELD and other.zone == Zone.GRAVEYARD
    engine.rules.destroy(victim)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert victim.zone == other.zone == Zone.EXILE

def test_graveyard_exile_can_read_a_death_controller_without_targeting_the_player():
    from tests.support.deck_batch import game, filler
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.models.game.events import GameEvent, EventType
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    engine = game()
    own = filler(engine, "Our card", zone=Zone.GRAVEYARD)
    other = filler(engine, "Their card", player="p2", zone=Zone.GRAVEYARD)
    source = filler(engine, "Source", type_line="Instant", zone=Zone.GRAVEYARD)
    effect = build_effects([EffectSpec("exile_target_graveyard", {"player_from_trigger_event": True})], source)[0]
    assert effect.target_spec is None
    context = GameContext(engine.state, engine.rules)
    context.trigger_event = GameEvent(EventType.DIES, controller_id="p2", owner_id="p1")
    effect.apply(context)
    assert other.zone == Zone.EXILE and own.zone == Zone.GRAVEYARD


def test_event_scoped_graveyard_exile_without_a_controller_does_not_exile_our_graveyard():
    from tests.support.deck_batch import game, filler
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    engine = game()
    own = filler(engine, "Our card", zone=Zone.GRAVEYARD)
    effect = build_effects([EffectSpec("exile_target_graveyard", {"player_from_trigger_event": True})], own)[0]
    effect.apply(GameContext(engine.state, engine.rules))
    assert own.zone == Zone.GRAVEYARD


