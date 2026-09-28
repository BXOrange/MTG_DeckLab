"""PAR-120: intervening counter conditions use the departing object's snapshot."""

import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle


def test_angelic_sleuth_uses_last_known_counters_on_departing_other_permanent():
    card = Card(id="angelic-sleuth", name="Angelic Sleuth",
                type_line="Creature — Angel Advisor", is_creature=True,
                oracle_text=("Flying\nWhenever another permanent you control leaves the battlefield, "
                             "if it had counters on it, investigate."))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    trigger = next(ability.trigger for ability in parsed.specs if ability.ability_kind == "triggered")
    assert trigger["event_counter_gate"] == {"min": 1}

    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    bind_from_catalogue(source)

    plain = GameObject(Card(id="plain", name="Plain", type_line="Creature", is_creature=True),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(plain)
    engine.rules.put_into_graveyard(plain)
    assert engine.rules.put_triggers_on_stack() == 0

    marked = GameObject(Card(id="marked", name="Marked", type_line="Creature", is_creature=True),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    marked.counters["+1/+1"] = 1
    state.add_to_battlefield(marked)
    engine.rules.put_into_graveyard(marked)
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    assert any(obj.name == "Clue" for obj in state.battlefield)


def test_counter_gate_normalizes_threshold_and_absence():
    for phrase, expected in (
        ("one or more counters", {"min": 1}),
        ("no time counters", {"kind": "time", "max": 0}),
        ("a +1/+1 counter", {"kind": "+1/+1", "min": 1}),
    ):
        card = Card(id=f"gate-{phrase}", name="Gate", type_line="Creature", is_creature=True,
                    oracle_text=f"When this creature dies, if it had {phrase} on it, draw a card.")
        parsed = parse_oracle(card)
        assert parsed.modeled, (phrase, parsed.unclaimed)
        trigger = next(ability.trigger for ability in parsed.specs if ability.ability_kind == "triggered")
        assert trigger["event_counter_gate"] == expected


def test_iron_apprentice_passes_every_counter_kind_from_death_snapshot():
    card = Card(id="iron-apprentice", name="Iron Apprentice",
                type_line="Artifact Creature — Construct", is_creature=True,
                oracle_text=("This creature enters with a +1/+1 counter on it.\n"
                             "When this creature dies, if it had counters on it, "
                             "put those counters on target creature you control."))
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    target = GameObject(Card(id="target", name="Target", type_line="Creature", is_creature=True),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    state.add_to_battlefield(target)
    bind_from_catalogue(source)
    source.counters["+1/+1"] = 2
    source.counters["shield"] = 1
    engine.rules.put_into_graveyard(source)
    assert engine.rules.put_triggers_on_stack() == 1
    choice = state.pending_choice
    assert choice["kind"] == "trigger_target"
    engine.rules.resolve_choice(str(target.instance_id))
    engine.rules.resolve_top_of_stack()
    assert target.counters["+1/+1"] == 2
    assert target.counters["shield"] == 1


def test_dying_counter_gate_copies_the_departed_object():
    card = Card(id="chronozoa", name="Chronozoa", type_line="Creature — Illusion",
                is_creature=True, power=3, toughness=3,
                oracle_text="When this creature dies, if it had no time counters on it, create two tokens that are copies of it.")
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    bind_from_catalogue(source)
    engine.rules.put_into_graveyard(source)
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    copies = [obj for obj in state.battlefield if obj.name == "Chronozoa"]
    assert len(copies) == 2 and all(obj.is_token for obj in copies)


def test_mass_counter_effect_filters_creatures_with_counters():
    card = Card(id="slurrk", name="Slurrk, All-Ingesting", type_line="Legendary Creature — Ooze",
                is_creature=True, power=0, toughness=0,
                oracle_text=("Slurrk enters with five +1/+1 counters on it.\n"
                             "Whenever Slurrk or another creature you control dies, if it had a +1/+1 counter on it, "
                             "put a +1/+1 counter on each creature you control that has a +1/+1 counter on it.\n"
                             "Partner"))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    [spec] = [effect for ability in parsed.specs for effect in ability.effects
              if effect.type == "add_counters"]
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    marked = GameObject(Card(id="marked", name="Marked", type_line="Creature", is_creature=True),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    plain = GameObject(Card(id="plain", name="Plain", type_line="Creature", is_creature=True),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    marked.counters["+1/+1"] = 1
    state.add_to_battlefield(marked)
    state.add_to_battlefield(plain)
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    effect.apply(engine.rules.context)
    assert marked.counters["+1/+1"] == 2
    assert plain.counters.get("+1/+1", 0) == 0


def test_returned_creature_permanently_loses_its_abilities():
    card = Card(id="wretch", name="Retched Wretch", type_line="Creature — Zombie",
                is_creature=True, power=3, toughness=3,
                oracle_text=("When this creature dies, if it had a -1/-1 counter on it, "
                             "return it to the battlefield under its owner's control "
                             "and it loses all abilities."))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.counters["-1/-1"] = 1
    state.add_to_battlefield(source)
    bind_from_catalogue(source)
    engine.rules.put_into_graveyard(source)
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    engine.recompute_continuous_effects()
    assert source.zone == Zone.BATTLEFIELD
    assert source.loses_all_abilities
    source.counters["-1/-1"] = 1
    engine.rules.put_into_graveyard(source)
    assert engine.rules.put_triggers_on_stack() == 0


def test_death_counter_branches_between_return_and_exile():
    card = Card(id="phoenix", name="Bogardan Phoenix", type_line="Creature — Phoenix",
                is_creature=True, power=3, toughness=3,
                oracle_text=("Flying\nWhen this creature dies, exile it if it had a death "
                             "counter on it. Otherwise, return it to the battlefield "
                             "under your control and put a death counter on it."))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    bind_from_catalogue(source)
    engine.rules.put_into_graveyard(source)
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    assert source.zone == Zone.BATTLEFIELD
    assert source.counters.get("death") == 1
    engine.rules.put_into_graveyard(source)
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    assert source.zone == Zone.EXILE


def test_departed_sources_counters_go_on_its_created_token():
    card = Card(id="augmenter", name="Ambitious Augmenter", type_line="Creature — Human",
                is_creature=True, power=2, toughness=2,
                oracle_text=("When this creature dies, if it had one or more counters on it, "
                             "create a 0/0 green and blue Fractal creature token, then "
                             "put this creature's counters on that token."))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.counters.update({"+1/+1": 2, "shield": 1})
    state.add_to_battlefield(source)
    bind_from_catalogue(source)
    engine.rules.put_into_graveyard(source)
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    [fractal] = [obj for obj in state.battlefield if obj.name == "Fractal"]
    assert fractal.counters == {"+1/+1": 2, "shield": 1}


def test_destroyed_targets_counter_is_measured_before_it_leaves():
    card = Card(id="rite", name="Rite of the Serpent", type_line="Sorcery",
                is_sorcery=True,
                oracle_text=("Destroy target creature. If that creature had a +1/+1 "
                             "counter on it, create a 1/1 green Snake creature token."))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    [spec] = parsed.specs[0].effects
    assert spec.type == "bind"
    for marked in (False, True):
        engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                     starting_life=20, starting_hand=0)
        state = engine.state
        source = GameObject(card, owner_id="p1", zone=Zone.STACK)
        source.controller_id = "p1"
        target = GameObject(Card(id="bear", name="Bear", type_line="Creature — Bear",
                                 is_creature=True, power=2, toughness=2),
                            owner_id="p2", zone=Zone.BATTLEFIELD)
        if marked:
            target.counters["+1/+1"] = 1
        state.add_to_battlefield(target)
        effect = EffectRegistry.create(spec.type, spec.params)
        effect.source = source
        assert [target_spec.kind for target_spec in effect.target_specs] == ["creature"]
        effect.apply(engine.rules.context, [target])
        assert target.zone == Zone.GRAVEYARD
        assert sum(obj.name == "Snake" for obj in state.battlefield) == int(marked)


OCHRE_JELLY = Card(
    id="ochre-jelly", name="Ochre Jelly", type_line="Creature — Ooze", is_creature=True,
    power=0, toughness=0,
    oracle_text=("Trample\nOchre Jelly enters with X +1/+1 counters on it.\nSplit — When Ochre "
                 "Jelly dies, if it had two or more +1/+1 counters on it, create a token that's a "
                 "copy of it at the beginning of the next end step. The token enters with half "
                 "that many +1/+1 counters on it, rounded down."))


def _drain(engine):
    while engine.rules.put_triggers_on_stack() or engine.state.stack:
        engine.rules.resolve_top_of_stack()


@pytest.mark.parametrize("counters, token_counters", [(5, 2), (1, None)])
def test_ochre_jelly_splits_into_a_delayed_copy_with_half_its_counters(counters, token_counters):
    parsed = parse_oracle(OCHRE_JELLY)
    assert parsed.modeled, parsed.unclaimed
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    jelly = GameObject(OCHRE_JELLY, owner_id="p1", zone=Zone.BATTLEFIELD)
    jelly.controller_id = "p1"
    jelly.counters["+1/+1"] = counters
    state.add_to_battlefield(jelly)
    bind_from_catalogue(jelly)
    engine.rules.put_into_graveyard(jelly)
    _drain(engine)
    # RULE 603.7: nothing yet — the copy waits for the next end step.
    assert not any(obj.is_token for obj in state.battlefield)
    engine._fire_delayed_triggers("end")
    _drain(engine)
    tokens = [obj for obj in state.battlefield if obj.is_token]
    if token_counters is None:
        assert tokens == []
        return
    [token] = tokens
    engine.recompute_continuous_effects()
    assert token.name == "Ochre Jelly"
    assert token.counters.get("+1/+1") == token_counters
    assert (token.power, token.toughness) == (token_counters, token_counters)
