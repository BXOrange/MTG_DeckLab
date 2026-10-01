"""PAR-99: "Spells `<you|your opponents>` cast that target `<X>` cost {N} more/less (or an additional N life)
to cast" (RULE 601.2f, after 601.2c's targets) — Kasmina, Esior, Monastery Siege's Dragons, Terror of the Peaks,
Elderwood Scion.

`cost_reduction` gained `if_targets` (an OR-list `continuous._spell_targets_hit` reads against the caster's chosen
targets, scoped to the *static's* controller) and `life` (`continuous.cast_life_tax_for`, paid by
`GameEngine._pay_cast_life_tax`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

KASMINA = "Spells your opponents cast that target a creature or planeswalker you control cost {2} more to cast."
ESIOR = "Spells your opponents cast that target 1 or more commanders you control cost {3} more to cast."
TERROR = "Spells your opponents cast that target this creature cost an additional 3 life to cast."
SCION = "Spells you cast that target this creature cost {2} less to cast."
SIEGE = (
    "As this enchantment enters, choose Khans or Dragons.\n"
    "• Khans — At the beginning of your upkeep, draw a card.\n"
    "• Dragons — Spells your opponents cast that target you or a permanent you control cost {2} more to cast."
)


def _tax(text):
    return static_effect_specs(text.rstrip(".").lower().replace("this creature", "~"))


# --- parse -----------------------------------------------------------------


def test_each_target_slot_parses_to_the_right_spec():
    assert _tax(KASMINA) == [EffectSpec("cost_reduction", {
        "affects": "opponents_spells", "generic": 2, "increase": True,
        "if_targets": [
            {"permanent": True, "card_type": "creature", "controller": "source_controller"},
            {"permanent": True, "card_type": "planeswalker", "controller": "source_controller"},
        ],
    })]
    assert _tax(ESIOR)[0].params["if_targets"] == [
        {"permanent": True, "is_commander": True, "controller": "source_controller"}
    ]
    assert _tax(TERROR) == [EffectSpec("cost_reduction", {
        "affects": "opponents_spells", "generic": 0, "life": 3, "increase": True, "targets_source": True,
    })]
    assert _tax(SCION) == [EffectSpec("cost_reduction", {
        "generic": 2, "increase": False, "targets_source": True,
    })]
    assert _tax("spells your opponents cast that target you or a permanent you control cost {2} more to cast")[
        0].params["if_targets"] == [
        {"player": "controller"}, {"permanent": True, "controller": "source_controller"},
    ]


@pytest.mark.parametrize("text", [
    # a target kind outside the vocabulary
    "spells your opponents cast that target a merfolk you control cost {2} more to cast",
    "spells your opponents cast that target enchanted creature cost {3} less to cast",
    # a bare "a permanent" names nothing in particular
    "spells your opponents cast that target a permanent cost {2} more to cast",
    # "target you" is only a player, never "a creature you"
    "spells your opponents cast that target a creature you cost {2} more to cast",
])
def test_unknown_target_slots_are_not_claimed(text):
    assert static_effect_specs(text) is None


@pytest.mark.parametrize("name, text", [
    ("Kasmina, Enigmatic Mentor", KASMINA),
    ("Esior, Wardwing Familiar", ESIOR),
    ("Terror of the Peaks", "Flying\n" + TERROR),
    ("Elderwood Scion", "Flying, lifelink\n" + SCION),
    ("Monastery Siege", SIEGE),
])
def test_real_cards_are_modeled(name, text):
    card = Card(id=name, name=name, type_line="Creature — Dragon" if name != "Monastery Siege" else "Enchantment",
                oracle_text=text, is_creature=name != "Monastery Siege")
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed


# --- execute ---------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    return eng, eng.state


def _put(state, name, type_line, oracle="", controller="p1", **flags):
    creature = "Creature" in type_line
    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_creature=creature,
             is_land="Land" in type_line, power=2 if creature else None, toughness=2 if creature else None),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    for key, value in flags.items():
        setattr(obj, key, value)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _bolt(state, caster="p2"):
    obj = GameObject(
        Card(id="bolt", name="Bolt", type_line="Instant", is_instant=True, mana_cost_string="{R}",
             converted_mana_cost=1, oracle_text="Bolt deals 3 damage to any target."),
        owner_id=caster, zone=Zone.HAND,
    )
    obj.controller_id = caster
    bind_from_catalogue(obj)
    state.player_by_id(caster).hand.append(obj)
    return obj


def _mv(eng, caster, spell, targets):
    return eng.effective_cast_cost(eng.state.player_by_id(caster), spell, targets=targets).converted_mana_cost


def test_kasmina_taxes_only_spells_aimed_at_its_controllers_creatures_and_planeswalkers():
    eng, state = _engine()
    _put(state, "Kasmina", "Legendary Planeswalker — Kasmina", KASMINA)
    mine = _put(state, "Bear", "Creature — Bear")
    theirs = _put(state, "Ogre", "Creature — Ogre", controller="p2")
    land = _put(state, "Island", "Basic Land — Island")
    bolt = _bolt(state)
    eng.recompute_continuous_effects()

    assert _mv(eng, "p2", bolt, [mine]) == 3        # {2}{R}
    assert _mv(eng, "p2", bolt, [theirs]) == 1      # their own creature
    assert _mv(eng, "p2", bolt, [land]) == 1        # not a creature or planeswalker
    assert _mv(eng, "p2", bolt, [state.player_by_id("p1")]) == 1   # a player
    assert _mv(eng, "p2", bolt, None) == 1          # offer-time probe: no targets yet
    own = _bolt(state, caster="p1")
    assert _mv(eng, "p1", own, [mine]) == 1         # the controller's own spells are spared


def test_a_spell_on_the_stack_is_not_a_permanent_you_control():
    eng, state = _engine()
    _put(state, "Kasmina", "Legendary Planeswalker — Kasmina", KASMINA)
    creature_spell = GameObject(
        Card(id="cs", name="Cub", type_line="Creature — Bear", is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.STACK)
    creature_spell.controller_id = "p1"
    bolt = _bolt(state)
    eng.recompute_continuous_effects()
    assert _mv(eng, "p2", bolt, [creature_spell]) == 1


def test_esior_taxes_only_commanders():
    eng, state = _engine()
    _put(state, "Esior", "Legendary Creature — Dragon", ESIOR)
    commander = _put(state, "Boss", "Legendary Creature — Human", is_commander=True)
    plain = _put(state, "Bear", "Creature — Bear")
    bolt = _bolt(state)
    eng.recompute_continuous_effects()
    assert _mv(eng, "p2", bolt, [commander]) == 4   # {3}{R}
    assert _mv(eng, "p2", bolt, [plain]) == 1
    assert _mv(eng, "p2", bolt, [plain, commander]) == 4   # "1 or more"


def test_monastery_siege_dragons_taxes_you_and_your_permanents_only_under_its_label():
    for chosen, taxed in (("dragons", True), ("khans", False)):
        eng, state = _engine()
        _put(state, "Monastery Siege", "Enchantment", SIEGE, chosen_mode=chosen)
        mine = _put(state, "Bear", "Creature — Bear")
        theirs = _put(state, "Ogre", "Creature — Ogre", controller="p2")
        bolt = _bolt(state)
        eng.recompute_continuous_effects()
        expect = 3 if taxed else 1
        assert _mv(eng, "p2", bolt, [state.player_by_id("p1")]) == expect   # "you"
        assert _mv(eng, "p2", bolt, [mine]) == expect                       # "a permanent you control"
        assert _mv(eng, "p2", bolt, [theirs]) == 1                          # never their own


def test_elderwood_scion_discounts_its_controllers_spells_that_target_it():
    eng, state = _engine()
    scion = _put(state, "Elderwood Scion", "Creature — Elemental", SCION)
    other = _put(state, "Bear", "Creature — Bear")
    spell = GameObject(
        Card(id="pump", name="Pump", type_line="Instant", is_instant=True, mana_cost_string="{2}{G}",
             converted_mana_cost=3, oracle_text="Target creature gets +2/+2 until end of turn."),
        owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    state.player_by_id("p1").hand.append(spell)
    eng.recompute_continuous_effects()
    assert _mv(eng, "p1", spell, [scion]) == 1      # {G}
    assert _mv(eng, "p1", spell, [other]) == 3
    assert _mv(eng, "p2", _bolt(state), [scion]) == 1   # an opponent's spell is not discounted


def _terror(state):
    return _put(state, "Terror of the Peaks", "Creature — Dragon", TERROR)


def test_terror_charges_life_when_an_opponents_spell_targets_it():
    eng, state = _engine()
    terror = _terror(state)
    other = _put(state, "Bear", "Creature — Bear")
    bolt = _bolt(state)
    p2 = state.player_by_id("p2")
    eng.recompute_continuous_effects()
    p2.mana_pool.add_many({"R": 1})

    assert eng.can_cast(p2, bolt, targets=[terror])
    eng.cast_spell(p2, bolt, targets=[terror])
    assert p2.life == 17                             # the additional cost, paid on casting
    assert _mv(eng, "p2", bolt, [terror]) == 1       # life, not mana

    other_bolt = _bolt(state)
    p2.mana_pool.add_many({"R": 1})
    eng.cast_spell(p2, other_bolt, targets=[other])
    assert p2.life == 17                             # not aimed at Terror: free of the tax


def test_terror_blocks_a_cast_the_caster_cannot_pay_life_for():
    eng, state = _engine()
    terror = _terror(state)
    bolt = _bolt(state)
    p2 = state.player_by_id("p2")
    p2.life = 2
    p2.mana_pool.add_many({"R": 1})
    eng.recompute_continuous_effects()
    assert not eng.can_cast(p2, bolt, targets=[terror])
    assert eng.can_cast(p2, bolt, targets=[state.player_by_id("p1")])


def test_terror_spares_its_own_controllers_spells():
    eng, state = _engine()
    terror = _terror(state)
    bolt = _bolt(state, caster="p1")
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"R": 1})
    eng.recompute_continuous_effects()
    eng.cast_spell(p1, bolt, targets=[terror])
    assert p1.life == 20
