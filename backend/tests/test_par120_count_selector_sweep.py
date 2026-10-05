"""PAR-120 batch 6: "the number of `<word>` you control" goes through the shared
count grammar.

Four emitters (`subgrammars.devotion_selector`'s single-word branch, the "for each
`<word>` you control" token count, "loses life equal to the number of `<word>`
you control", and Eriette's hand-authored drain) built
``creatures_you_control_of_type_<word>`` from whatever word was printed. That
selector counts *creatures* with that subtype, so a land type (Beacon of
Creation's Forests), a card type (Nomads' Assembly's creatures, Avenger of
Zendikar's lands), a non-creature subtype (Basilisk Gate's Gates, Eriette's
Auras) or an irregular plural (Lys Alana Scarblade's "Elves" → ``elve``) always
counted 0 — MODELED, and doing nothing. `parse_count_phrase` reads the word
instead and refuses one it doesn't know.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.subgrammars import subtype_count_selector


def _engine():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state


def _bf(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _land(name, subtype):
    return Card(id=name.lower(), name=name, type_line=f"Basic Land — {subtype}", is_land=True)


def _creature(name, subtype="Bear"):
    return Card(id=name.lower(), name=name, type_line=f"Creature — {subtype}", is_creature=True,
                power=2, toughness=2)


def _effect(card, effect_type):
    """The first `effect_type` spec the parser claims for ``card``, live."""
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    for ability in result.specs:
        for spec in ability.effects:
            if spec.type == effect_type:
                return EffectRegistry.create(spec.type, spec.params), spec
    raise AssertionError(f"no {effect_type} spec in {card.name}")


def _tokens(state, owner="p1"):
    return [o for o in state.battlefield if getattr(o, "is_token", False) and o.controller_id == owner]


@pytest.mark.parametrize("word, expected", [
    ("forests", {"subtype": "forest"}),
    ("lands", {"card_type": "land"}),
    ("elves", {"subtype": "elf"}),
    ("gates", {"subtype": "gate"}),
    ("auras", {"subtype": "aura"}),
    ("shrines", {"subtype": "shrine"}),
])
def test_subtype_count_selector_reads_the_word(word, expected):
    assert subtype_count_selector(word) == {"zone": "battlefield", "of": "you", "filter": expected}


def test_unknown_word_is_refused_not_guessed_as_a_creature_type():
    assert subtype_count_selector("xyzzies") is None


def test_beacon_of_creation_counts_forests():
    card = Card(id="beacon", name="Beacon of Creation", type_line="Sorcery", is_sorcery=True,
                oracle_text=("Create a 1/1 green Insect creature token for each Forest you control. "
                             "Shuffle Beacon of Creation into its owner's library."))
    engine, state = _engine()
    for n in range(3):
        _bf(state, _land(f"Forest{n}", "Forest"))
    _bf(state, _land("Island", "Island"))
    source = GameObject(card, owner_id="p1", zone=Zone.STACK)
    source.controller_id = "p1"
    effect, _ = _effect(card, "create_token")
    effect.source = source
    effect.apply(engine.rules.context)
    assert len(_tokens(state)) == 3


def test_nomads_assembly_counts_creatures_not_creature_typed_creatures():
    card = Card(id="nomads", name="Nomads' Assembly", type_line="Sorcery", is_sorcery=True,
                oracle_text="Create a 1/1 white Kor Soldier creature token for each creature you control.")
    engine, state = _engine()
    _bf(state, _creature("Bear1"))
    _bf(state, _creature("Bear2"))
    _bf(state, _creature("Theirs"), owner="p2")
    source = GameObject(card, owner_id="p1", zone=Zone.STACK)
    source.controller_id = "p1"
    effect, _ = _effect(card, "create_token")
    effect.source = source
    effect.apply(engine.rules.context)
    assert len(_tokens(state)) == 2


def test_lys_alana_scarblade_reads_the_irregular_plural():
    card = Card(id="lys", name="Lys Alana Scarblade", type_line="Creature — Elf Assassin",
                is_creature=True, power=1, toughness=1,
                oracle_text=("{T}, Discard an Elf card: Target creature gets -X/-X until end of turn, "
                             "where X is the number of Elves you control."))
    engine, state = _engine()
    source = _bf(state, card)
    _bf(state, _creature("Elf2", "Elf Warrior"))
    victim = _bf(state, Card(id="big", name="Big", type_line="Creature — Giant", is_creature=True,
                             power=5, toughness=5), owner="p2")
    effect, _ = _effect(card, "pump")
    effect.source = source
    effect.apply(engine.rules.context, targets=[victim])
    engine.recompute_continuous_effects()
    assert victim.toughness == 3  # two Elves you control


def test_malakir_bloodwitch_drain_counts_vampires():
    card = Card(id="malakir", name="Malakir Bloodwitch", type_line="Creature — Vampire Shaman",
                is_creature=True, power=3, toughness=4,
                oracle_text=("When this creature enters, each opponent loses life equal to the "
                             "number of Vampires you control."))
    engine, state = _engine()
    source = _bf(state, card)
    _bf(state, _creature("Vamp2", "Vampire"))
    effect, spec = _effect(card, "lose_life")
    assert spec.params["amount_from_count_selector"]["filter"] == {"subtype": "vampire"}
    effect.source = source
    effect.apply(engine.rules.context)
    assert state.players[1].life == 18


def test_basilisk_gate_counts_gates_which_are_lands():
    card = Card(id="gate", name="Basilisk Gate", type_line="Land — Gate", is_land=True,
                oracle_text=("{2}, {T}: Target creature gets +X/+X until end of turn, where X is "
                             "the number of Gates you control. Activate only as a sorcery."))
    engine, state = _engine()
    source = _bf(state, card)
    _bf(state, _land("Gate2", "Gate"))
    bear = _bf(state, _creature("Bear"))
    effect, _ = _effect(card, "pump")
    effect.source = source
    effect.apply(engine.rules.context, targets=[bear])
    engine.recompute_continuous_effects()
    assert bear.power == 4


# -- "<A> and <B>, where X is …": one X for the whole sentence ----------------


def test_tendrils_of_corruption_deals_and_gains_the_same_x():
    """The connector split used to hand the where-X tail to "you gain X life" alone,
    leaving the damage's X as the spell's unpaid X (0)."""
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    card = Card(id="tendrils", name="Tendrils of Corruption", type_line="Instant", is_instant=True,
                mana_cost_string="{3}{B}",
                oracle_text=("Tendrils of Corruption deals X damage to target creature and you gain "
                             "X life, where X is the number of Swamps you control."))
    [ability] = parse_oracle(card).specs
    [bind] = ability.effects
    assert bind.type == "bind"
    assert [e["type"] for e in bind.params["effects"]] == ["damage", "gain_life"]

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    for n in range(3):
        _bf(state, _land(f"Swamp{n}", "Swamp"))
    victim = _bf(state, Card(id="big", name="Big", type_line="Creature — Giant", is_creature=True,
                             power=5, toughness=5), owner="p2")
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add_many({"B": 1, "C": 3})
    engine.cast_spell(p1, spell, targets=[victim])
    engine.resolve_until_stable()
    assert victim.damage_marked == 3
    assert p1.life == 23


def test_a_later_effect_measured_after_an_earlier_one_is_not_shared():
    """Anim Pakal: the counter goes on first and X counts it — one up-front
    measurement would be off by one, so the sentence keeps its sequenced reading."""
    card = Card(id="anim", name="Anim Test", type_line="Creature — Gnome", is_creature=True,
                power=1, toughness=1,
                oracle_text=("Whenever you attack with one or more non-Gnome creatures, put a +1/+1 "
                             "counter on Anim Test, then create X 1/1 colorless Gnome artifact creature "
                             "tokens that are tapped and attacking, where X is the number of +1/+1 "
                             "counters on Anim Test."))
    [ability] = [a for a in parse_oracle(card).specs if a.ability_kind == "triggered"]
    assert [e.type for e in ability.effects] == ["add_counters", "bind"]


# -- MEC-84's left-the-battlefield history, reachable from the parser ---------


def test_kutzils_flanker_counts_creatures_that_left_under_your_control():
    """`creatures_that_left_battlefield_this_turn` was built for this card and never
    reached by any parse; the "for each" phrase now names it."""
    card = Card(id="kutzil", name="Kutzil's Flanker", type_line="Creature — Cat Warrior",
                is_creature=True, power=3, toughness=1,
                oracle_text=("Flash\nWhen this creature enters, choose one —\n"
                             "• Put a +1/+1 counter on this creature for each creature that left "
                             "the battlefield under your control this turn.\n"
                             "• You gain 2 life and scry 2.\n"
                             "• Exile target player's graveyard."))
    [trigger] = [a for a in parse_oracle(card).specs if a.ability_kind == "triggered"]
    [bind] = trigger.modes["options"][0]
    assert bind.params["amount"]["selector"] == "creatures_that_left_battlefield_this_turn"

    engine, state = _engine()
    flanker = _bf(state, card)
    for n in range(2):
        engine.rules.put_into_graveyard(_bf(state, _creature(f"Gone{n}")))
    engine.rules.put_into_graveyard(_bf(state, _creature("Theirs"), owner="p2"))
    effect = EffectRegistry.create(bind.type, bind.params)
    effect.source = flanker
    effect.apply(engine.rules.context)
    assert flanker.counters.get("+1/+1") == 2


# -- "noncreature, nonland": two stacked negations are one conjunction --------


def test_noncreature_nonland_graveyard_count_is_a_conjunction():
    """Xande, Dark Mage. The retired table row existed because the shared grammar
    once read the comma as an OR (every card matched); it now excludes both."""
    from mtg_analyzer.game import continuous
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs

    [spec] = static_effect_specs("~ gets +1/+1 for each noncreature, nonland card in your graveyard")
    selector = spec.params["power_count"]
    _, state = _engine()
    graveyard = state.player_by_id("p1").graveyard
    for card in (_creature("Dead"), _land("Forest", "Forest"),
                 Card(id="bolt", name="Bolt", type_line="Instant", is_instant=True),
                 Card(id="rock", name="Rock", type_line="Artifact")):
        graveyard.append(GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD))
    assert continuous.count_selector(state, "p1", selector) == 2
