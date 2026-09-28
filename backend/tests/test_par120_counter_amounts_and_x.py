"""PAR-120 batch 3/4 residue: counter amounts, "it" after create/manifest, and X.

* "that many" / "where X is the number of counters on that creature" behind a
  leaving-counter gate read the event's RULE 400.7 snapshot
  (``trigger_event_counter``; no ``counter`` = every kind).
* "Create a token. Put N +1/+1 counters on **it**." puts them on the token —
  it used to put them on the ability's own source (Additive Evolution's 0/0
  Fractal died). Manifest now reports its permanent the same way.
* `_substitute_x` used to overwrite an ability's X sentinel for good, so a
  second activation reused the first X; a cast trigger's X is the cast spell's.
* Two costs the engine can't charge are refused, not claimed broken.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle


def _engine():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state


def _modeled(card):
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    return result


def _bf(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _bear(name="Bear", **kwargs):
    return Card(id=name.lower(), name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2, **kwargs)


# -- counter amounts behind a leaving-counter gate ---------------------------


def test_that_many_reads_the_gated_counter_kind_off_the_death_snapshot():
    card = Card(id="reyhan", name="Reyhan Test", type_line="Creature — Elf", is_creature=True,
                power=1, toughness=1,
                oracle_text=("Whenever a creature you control dies, if it had one or more +1/+1 "
                             "counters on it, you may put that many +1/+1 counters on target creature."))
    result = _modeled(card)
    [ability] = [a for a in result.specs if a.ability_kind == "triggered"]
    [bind] = ability.effects
    assert bind.type == "bind"
    assert bind.params["amount"] == {"kind": "trigger_event_counter", "counter": "+1/+1"}
    assert ability.optional

    engine, state = _engine()
    _bf(state, card)
    dying = _bf(state, _bear("Dying"))
    dying.counters.update({"+1/+1": 3, "charge": 5})  # only the gated kind is "that many"
    target = _bf(state, _bear("Target"))
    engine.rules.put_into_graveyard(dying)
    engine.resolve_until_stable()
    choice = state.pending_choice
    while choice is not None:
        if choice.get("kind") == "trigger_target":
            engine.rules.resolve_choice(str(target.instance_id))
        else:
            engine.rules.resolve_choice("yes")
        engine.resolve_until_stable()
        choice = state.pending_choice
    assert target.counters.get("+1/+1") == 3


def test_that_number_after_a_kindless_gate_counts_every_kind():
    card = Card(id="yuna", name="Yuna Test", type_line="Creature — Human", is_creature=True,
                power=1, toughness=1,
                oracle_text=("Whenever another permanent you control dies, if it had one or more "
                             "counters on it, you may put that number of +1/+1 counters on target creature."))
    [ability] = [a for a in _modeled(card).specs if a.ability_kind == "triggered"]
    assert ability.effects[0].params["amount"] == {"kind": "trigger_event_counter"}


def test_where_x_is_the_number_of_counters_it_had():
    card = Card(id="felisa", name="Felisa Test", type_line="Creature — Vampire", is_creature=True,
                power=4, toughness=3,
                oracle_text=("Whenever a nontoken creature you control dies, if it had counters on it, "
                             "create X tapped 2/1 white and black Inkling creature tokens with flying, "
                             "where X is the number of counters it had on it."))
    engine, state = _engine()
    _modeled(card)
    _bf(state, card)
    dying = _bf(state, _bear("Dying"))
    dying.counters.update({"+1/+1": 1, "oil": 2})
    engine.rules.put_into_graveyard(dying)
    engine.resolve_until_stable()
    assert sum(1 for obj in state.battlefield if obj.name == "Inkling") == 3


# -- "it" after create / manifest --------------------------------------------


def test_counters_on_it_after_create_go_on_the_token():
    card = Card(id="evo", name="Evo Test", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{1}",
                oracle_text=("Create a 0/0 green and blue Fractal creature token. "
                             "Put three +1/+1 counters on it."))
    _modeled(card)
    engine, state = _engine()
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    state.player_by_id("p1").add_to_zone(spell, Zone.HAND)
    state.player_by_id("p1").mana_pool.add_many({"C": 1})
    engine.cast_spell(state.player_by_id("p1"), spell)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    [fractal] = [obj for obj in state.battlefield if obj.name == "Fractal"]
    assert (fractal.power, fractal.toughness) == (3, 3)


def test_counters_on_it_after_a_target_go_on_the_target():
    card = Card(id="play", name="Play Test", type_line="Instant", is_instant=True,
                oracle_text="Target creature gets +2/+2 until end of turn. Put a +1/+1 counter on it.")
    effects = [e for spec in _modeled(card).specs for e in spec.effects]
    assert effects[-1].type == "add_counters"
    assert effects[-1].params.get("previous_subject") is True


def test_explicit_self_reference_after_create_stays_on_the_source():
    card = Card(id="selfref", name="Self Ref", type_line="Creature — Elf", is_creature=True,
                power=1, toughness=1,
                oracle_text=("When Self Ref enters, create a 1/1 green Elf creature token. "
                             "Put a +1/+1 counter on Self Ref."))
    effects = [e for spec in _modeled(card).specs for e in spec.effects]
    assert not effects[-1].params.get("previous_subject")


def test_counters_on_a_manifested_card():
    card = Card(id="wildcall", name="Wildcall Test", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{X}{G}{W}",
                oracle_text="Manifest the top card of your library, then put X +1/+1 counters on it.")
    _modeled(card)
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    p1.library.append(GameObject(Card(id="top", name="Top", type_line="Land", is_land=True),
                                 owner_id="p1", zone=Zone.LIBRARY))
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add_many({"G": 1, "W": 1, "C": 2})
    engine.cast_spell(p1, spell, x=2)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    [manifested] = [obj for obj in state.battlefield if obj.owner_id == "p1"]
    assert manifested.counters.get("+1/+1") == 2


def test_measured_counters_on_a_created_token():
    card = Card(id="sage", name="Sage Test", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{1}",
                oracle_text=("Create a 0/0 green and blue Fractal creature token. Put X +1/+1 "
                             "counters on it, where X is the number of lands you control."))
    _modeled(card)
    engine, state = _engine()
    for index in range(4):
        _bf(state, Card(id=f"land-{index}", name="Forest", type_line="Basic Land — Forest",
                        is_land=True))
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    state.player_by_id("p1").add_to_zone(spell, Zone.HAND)
    state.player_by_id("p1").mana_pool.add_many({"C": 1})
    engine.cast_spell(state.player_by_id("p1"), spell)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    [fractal] = [obj for obj in state.battlefield if obj.name == "Fractal"]
    assert fractal.counters.get("+1/+1") == 4


# -- X -------------------------------------------------------------------------


def test_each_activation_resolves_with_its_own_x():
    engine, state = _engine()
    source = _bf(state, Card(id="xg", name="X Gainer", type_line="Artifact",
                             oracle_text="{X}: You gain X life."))
    p1 = state.player_by_id("p1")
    for x in (3, 5):
        p1.mana_pool.add_many({"C": x})
        engine.activate_ability(p1, source, 0, x=x)
        engine.resolve_until_stable()
    assert p1.life == 28


def test_a_cast_trigger_uses_the_cast_spells_x():
    engine, state = _engine()
    _bf(state, Card(id="zax", name="Zax Test", type_line="Creature — Nightmare Hydra",
                    is_creature=True, power=2, toughness=3,
                    oracle_text=("Whenever you cast a spell with {X} in its mana cost, create a 0/0 "
                                 "green Hydra creature token, then put X +1/+1 counters on it.")))
    p1 = state.player_by_id("p1")
    for x in (3, 2):
        spell = GameObject(Card(id=f"xs{x}", name=f"X Spell {x}", type_line="Sorcery",
                                is_sorcery=True, mana_cost_string="{X}{G}",
                                oracle_text="You gain X life."),
                           owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(spell)
        p1.add_to_zone(spell, Zone.HAND)
        p1.mana_pool.add_many({"G": 1, "C": x})
        engine.cast_spell(p1, spell, x=x)
        engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    hydras = sorted(obj.power for obj in state.battlefield if obj.name == "Hydra")
    assert hydras == [2, 3]


# -- costs the engine can't charge are refused ---------------------------------


def test_variable_sacrifice_cost_is_refused():
    card = Card(id="angel", name="Leaf Test", type_line="Creature — Angel", is_creature=True,
                power=2, toughness=2,
                oracle_text="Flying\n{T}, Sacrifice X lands: Put X +1/+1 counters on this creature.")
    assert not parse_oracle(card).modeled


def test_pay_x_then_x_counters_is_refused():
    card = Card(id="hero", name="Hero Test", type_line="Creature — Human Warrior",
                is_creature=True, power=1, toughness=1,
                oracle_text=("Whenever you cast a spell that targets this creature, you may pay {X}. "
                             "If you do, put X +1/+1 counters on this creature."))
    assert not parse_oracle(card).modeled


# -- two more characteristic-defining amounts ----------------------------------


def test_differently_named_lands_count_distinct_names():
    card = Card(id="amalgam", name="Amalgam Test", type_line="Creature — Golem", is_creature=True,
                oracle_text=("Amalgam Test's power and toughness are each equal to the number of "
                             "differently named lands you control."))
    _modeled(card)
    engine, state = _engine()
    amalgam = _bf(state, card)
    for index, name in enumerate(("Forest", "Forest", "Island")):
        _bf(state, Card(id=f"land-{index}", name=name, type_line=f"Basic Land — {name}",
                        is_land=True))
    engine.recompute_continuous_effects()
    assert (amalgam.power, amalgam.toughness) == (2, 2)


def test_mana_symbols_in_permanents_costs_is_devotion():
    card = Card(id="crux", name="Crux Test", type_line="Creature — Elemental", is_creature=True,
                mana_cost_string="{5}{G}{G}{G}",
                oracle_text=("Crux Test's power and toughness are each equal to the number of green "
                             "mana symbols in the mana costs of permanents you control."))
    result = _modeled(card)
    [cda] = [e for spec in result.specs for e in spec.effects if e.type == "pt_cda"]
    assert cda.params["power_count"] == "devotion_to_green"
