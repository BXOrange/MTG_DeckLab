"""PAR-120 (c): "if `<condition>`, `<effect>` instead" over a targeted body.

A magnitude override is one `bind` measuring ``{"kind": "if"}``; any other
override is an `if_else` that announces a target only when both branches
announce the same one (RULE 601.2c). Addendum/Infusion paragraphs continue
the spell's previous instruction, and "Treasure mana spent to activate" /
"cast during your main phase" are stamped at payment/cast time.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle


def _engine():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    return engine, engine.state


def _creature(state, owner, name="Bear", power=2, toughness=2):
    obj = GameObject(Card(id=f"{owner}-{name}", name=name, type_line="Creature — Bear",
                          is_creature=True, power=power, toughness=toughness),
                     owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    state.add_to_battlefield(obj)
    return obj


def _spell_effect(card):
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    [ability] = [spec for spec in parsed.specs if spec.ability_kind != "keyword"]
    [effect] = ability.effects
    return effect


def _run(engine, spec, source, targets):
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    announced = effect.target_specs
    effect.apply(engine.rules.context, targets)
    return announced


GALVANIZE = Card(
    id="galvanize", name="Galvanize", type_line="Instant", is_instant=True,
    oracle_text=("Galvanize deals 3 damage to target creature. If you've drawn two or "
                 "more cards this turn, Galvanize deals 5 damage to that creature instead."))


@pytest.mark.parametrize("drawn, expected", [(0, 3), (2, 5)])
def test_galvanize_measures_its_damage_once_on_one_target(drawn, expected):
    engine, state = _engine()
    spec = _spell_effect(GALVANIZE)
    assert spec.type == "bind" and spec.params["amount"]["kind"] == "if"
    player = state.player_by_id("p1")
    for n in range(drawn):
        player.library.append(GameObject(Card(id=f"l{n}", name="Land", type_line="Land"),
                                         owner_id="p1", zone=Zone.LIBRARY))
    engine.rules.draw(player, drawn)
    source = GameObject(GALVANIZE, owner_id="p1", zone=Zone.STACK)
    source.controller_id = "p1"
    target = _creature(state, "p2", toughness=10)
    announced = _run(engine, spec, source, [target])
    assert [t.kind for t in announced] == ["creature"]
    assert target.damage_marked == expected


@pytest.mark.parametrize("main_phase, discarded", [(False, 2), (True, 4)])
def test_haunting_hymn_announces_its_player_before_the_count_is_bound(main_phase, discarded):
    engine, state = _engine()
    card = Card(id="hymn", name="Haunting Hymn", type_line="Instant", is_instant=True,
                oracle_text=("Target player discards two cards. If you cast this spell "
                             "during your main phase, that player discards four cards instead."))
    spec = _spell_effect(card)
    victim = state.player_by_id("p2")
    for n in range(5):
        victim.hand.append(GameObject(Card(id=f"c{n}", name=f"C{n}", type_line="Land"),
                                      owner_id="p2", zone=Zone.HAND))
    source = GameObject(card, owner_id="p1", zone=Zone.STACK)
    source.controller_id = "p1"
    source.cast_during_your_main_phase = main_phase
    announced = _run(engine, spec, source, [victim])
    assert [t.kind for t in announced] == ["player"]
    choice = state.pending_choice
    assert choice["action"] == "discard" and choice["player_id"] == "p2"
    assert choice["count"] == discarded


SCYTHECAT = Card(
    id="scythecat", name="Scythecat Cub", type_line="Creature — Cat", is_creature=True,
    power=2, toughness=2,
    oracle_text=("Trample\nLandfall — Whenever a land you control enters, put a +1/+1 "
                 "counter on target creature you control. If this is the second time this "
                 "ability has resolved this turn, double the number of +1/+1 counters on "
                 "that creature instead."))


def test_scythecat_cub_if_else_announces_the_shared_target():
    engine, state = _engine()
    parsed = parse_oracle(SCYTHECAT)
    assert parsed.modeled, parsed.unclaimed
    [spec] = [e for a in parsed.specs if a.ability_kind == "triggered" for e in a.effects]
    assert spec.type == "if_else"
    target = _creature(state, "p1")
    target.counters["+1/+1"] = 3
    effect = EffectRegistry.create(spec.type, spec.params)
    assert [t.kind for t in effect.target_specs] == ["creature_you_control"]


def test_if_else_with_different_branch_targets_announces_nothing():
    effect = EffectRegistry.create("if_else", {
        "condition": {"kind": "kicked", "min": 1},
        "then": [{"type": "destroy", "params": {"target_kind": "creature"}}],
        "else": [{"type": "draw", "params": {"count": 1}}],
    })
    assert effect.target_specs == []


@pytest.mark.parametrize("name, oracle", [
    ("Blood Beckoning", "Kicker {3}\nReturn target creature card from your graveyard to your "
     "hand. If this spell was kicked, instead return two target creature cards from your "
     "graveyard to your hand."),
    ("Bloodchief's Thirst", "Kicker {2}{B}\nDestroy target creature or planeswalker with mana "
     "value 2 or less. If this spell was kicked, instead destroy target creature or planeswalker."),
])
def test_override_changing_the_target_requirement_stays_unclaimed(name, oracle):
    card = Card(id=name, name=name, type_line="Sorcery", is_sorcery=True, oracle_text=oracle)
    assert not parse_oracle(card).modeled


def test_tallyman_gates_the_whole_override_on_its_first_condition():
    card = Card(id="tallyman", name="Tallyman of Nurgle", type_line="Creature — Daemon",
                is_creature=True, power=2, toughness=2,
                oracle_text=("Lifelink\nAt the beginning of your end step, if a creature died "
                             "this turn, you draw a card and you lose 1 life. If seven or more "
                             "creatures died this turn, instead you draw seven cards and you "
                             "lose 7 life."))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    [spec] = [e for a in parsed.specs if a.ability_kind == "triggered" for e in a.effects]
    assert spec.type == "if_else"
    assert spec.condition == {"kind": "creatures_died_this_turn", "min": 1}
    assert [e["type"] for e in spec.params["then"]] == ["draw", "lose_life"]
    assert [e["type"] for e in spec.params["else"]] == ["draw", "lose_life"]


def test_infusion_paragraph_keeps_its_referent_and_condition():
    card = Card(id="eff", name="Efflorescence", type_line="Instant", is_instant=True,
                oracle_text=("Put two +1/+1 counters on target creature.\nInfusion — If you "
                             "gained life this turn, that creature also gains trample and "
                             "indestructible until end of turn."))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    effects = [e for a in parsed.specs for e in a.effects]
    assert [e.type for e in effects] == ["add_counters", "pump"]
    assert effects[1].condition == {"kind": "gained_life_this_turn"}
    assert effects[1].params.get("previous_subject") is True


def test_withering_curse_destroys_instead_after_life_gain():
    engine, state = _engine()
    card = Card(id="curse", name="Withering Curse", type_line="Sorcery", is_sorcery=True,
                oracle_text=("All creatures get -2/-2 until end of turn.\nInfusion — If you "
                             "gained life this turn, destroy all creatures instead."))
    spec = _spell_effect(card)
    big = _creature(state, "p2", name="Big", power=5, toughness=5)
    source = GameObject(card, owner_id="p1", zone=Zone.STACK)
    source.controller_id = "p1"
    engine.rules.gain_life(state.player_by_id("p1"), 1)
    _run(engine, spec, source, None)
    assert big.zone == Zone.GRAVEYARD


def _jetmirs_fixer(engine, state):
    card = Card(id="fixer", name="Jetmir's Fixer", type_line="Creature — Human Rogue",
                is_creature=True, power=3, toughness=2,
                oracle_text=("{R}{G}: Jetmir's Fixer gets +1/+1 until end of turn. If mana "
                             "from a Treasure was spent to activate this ability, put a +1/+1 "
                             "counter on Jetmir's Fixer instead."))
    assert parse_oracle(card).modeled
    fixer = _creature(state, "p1", name="Jetmir's Fixer", power=3, toughness=2)
    fixer.card = card
    bind_from_catalogue(fixer)
    return fixer


@pytest.mark.parametrize("from_treasure", [False, True])
def test_jetmirs_fixer_reads_treasure_mana_spent_on_its_activation(from_treasure):
    engine, state = _engine()
    engine.begin_turn()
    state.current_step = "main1"
    fixer = _jetmirs_fixer(engine, state)
    player = state.player_by_id("p1")
    player.mana_pool.add("R", 1, source_kind="treasure" if from_treasure else None)
    player.mana_pool.add("G", 1)
    engine.activate_ability(player, fixer, 0)
    assert fixer.mana_spent_to_activate_treasure == int(from_treasure)
    engine.rules.resolve_top_of_stack()
    assert fixer.counters.get("+1/+1", 0) == int(from_treasure)


@pytest.mark.parametrize("step, expected", [("main1", True), ("upkeep", False)])
def test_addendum_flag_is_stamped_at_cast(step, expected):
    engine, state = _engine()
    engine.begin_turn()
    state.current_step = step
    card = Card(id="insight", name="Sphinx's Insight", type_line="Instant", is_instant=True,
                mana_cost_string="{2}{W}{U}",
                oracle_text=("Draw two cards.\nAddendum — If you cast this spell during your "
                             "main phase, you gain 2 life."))
    player = state.player_by_id("p1")
    for n in range(2):
        player.library.append(GameObject(Card(id=f"l{n}", name="Land", type_line="Land"),
                                         owner_id="p1", zone=Zone.LIBRARY))
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    player.hand.append(spell)
    bind_from_catalogue(spell)
    assert parse_oracle(card).modeled
    player.mana_pool.add("W", 1)
    player.mana_pool.add("U", 1)
    player.mana_pool.add("C", 2)
    engine.cast_spell(player, spell)
    assert spell.cast_during_your_main_phase is expected
    engine.rules.resolve_top_of_stack()
    assert player.life == 20 + (2 if expected else 0)


ZIMONE = Card(
    id="zimone", name="Zimone, Mystery Unraveler", type_line="Legendary Creature — Human Wizard",
    is_creature=True, power=3, toughness=3,
    oracle_text=("Landfall — Whenever a land you control enters, manifest dread if this is the "
                 "first time this ability has resolved this turn. Otherwise, you may turn a "
                 "permanent you control face up."))


def _face_down(engine, state, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.LIBRARY)
    state.player_by_id("p1").library.append(obj)
    [made] = engine.rules.manifest(state.player_by_id("p1"))
    return made


@pytest.mark.parametrize("hidden, turns_up", [
    (Card(id="ogre", name="Ogre", type_line="Creature — Ogre", is_creature=True,
          power=4, toughness=4, mana_cost_string="{3}{R}"), True),
    # RULE 701.40g: revealed, left face down.
    (Card(id="bolt", name="Bolt", type_line="Instant", is_instant=True), False),
])
def test_zimone_otherwise_turns_a_chosen_permanent_face_up(hidden, turns_up):
    parsed = parse_oracle(ZIMONE)
    assert parsed.modeled, parsed.unclaimed
    [spec] = [e for a in parsed.specs if a.ability_kind == "triggered" for e in a.effects]
    assert spec.type == "if_else"
    assert spec.params["else"] == [{"type": "turn_face_up_chosen",
                                    "params": {"optional": True, "creature_only": False}}]
    engine, state = _engine()
    made = _face_down(engine, state, hidden)
    assert made.face_down
    source = _creature(state, "p1", name="Zimone")
    effect = EffectRegistry.create("turn_face_up_chosen", {"optional": True})
    effect.source = source
    effect.apply(engine.rules.context, None)
    choice = state.pending_choice
    assert [o["instance_id"] for o in choice["options"] if "instance_id" in o] == [made.instance_id]
    engine.rules.resolve_choice(str(made.instance_id))
    assert made.face_down is (not turns_up)
    if turns_up:
        assert made.name == "Ogre"


@pytest.mark.parametrize("kicked", [False, True])
def test_colossal_growth_pumps_the_announced_creature_in_either_branch(kicked):
    engine, state = _engine()
    card = Card(id="growth", name="Colossal Growth", type_line="Instant", is_instant=True,
                oracle_text=("Kicker {R}\nTarget creature gets +3/+3 until end of turn. If this "
                             "spell was kicked, instead that creature gets +4/+4 and gains "
                             "trample and haste until end of turn."))
    spec = _spell_effect(card)
    source = GameObject(card, owner_id="p1", zone=Zone.STACK)
    source.controller_id = "p1"
    source.kicker_count = int(kicked)
    bear = _creature(state, "p1")
    announced = _run(engine, spec, source, [bear])
    assert [t.kind for t in announced] == ["creature"]
    engine.recompute_continuous_effects()
    from mtg_analyzer.game.combat import has
    assert (bear.power, bear.toughness) == ((6, 6) if kicked else (5, 5))
    assert has(bear, "trample") is kicked


@pytest.mark.parametrize("gained, zone", [(False, Zone.HAND), (True, Zone.BATTLEFIELD)])
def test_doctor_jane_foster_returns_the_announced_card_to_hand_or_battlefield(gained, zone):
    engine, state = _engine()
    card = Card(id="jane", name="Doctor Jane Foster", type_line="Legendary Creature — Human",
                is_creature=True, power=2, toughness=4,
                oracle_text=("Vigilance\nWhen Doctor Jane Foster enters, return target creature "
                             "card with mana value 3 or less from your graveyard to your hand. If "
                             "you gained life this turn, return that card to the battlefield instead."))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    [spec] = [e for a in parsed.specs if a.ability_kind == "triggered" for e in a.effects]
    player = state.player_by_id("p1")
    dead = GameObject(Card(id="bear2", name="Grizzly", type_line="Creature — Bear",
                           is_creature=True, power=2, toughness=2, mana_cost_string="{1}{G}",
                           converted_mana_cost=2),
                      owner_id="p1", zone=Zone.GRAVEYARD)
    player.graveyard.append(dead)
    if gained:
        engine.rules.gain_life(player, 1)
    source = _creature(state, "p1", name="Doctor Jane Foster")
    announced = _run(engine, spec, source, [dead])
    assert [t.kind for t in announced] == ["graveyard_creature"]
    assert dead.zone == zone
