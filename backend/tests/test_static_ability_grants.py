"""Layer-6 static grants of a *non-keyword* ability (RULE 613.7f).

Follow-up to a status-doc question: "Layer 3 (text-changing, RULE 612) and
full RULE 613.8 dependency ordering are deliberately unmodeled" is still
true, but two real cards — Tyvar Kell ("Elves you control have '{T}: Add
{B}.'") and Dionus, Elvish Archdruid ("Elves you control have '<triggered
ability>'") — need something the engine didn't have: a layer-6 ability grant
of more than a bare keyword. Both are layer 6 (ability-adding), not layer 3
(CR 612.1's "text … granted by other effects" is about literal text
substitution, not this) — see `game/continuous.py`'s module docstring.

This covers the generic mechanism (`grant_mana_ability`/
`grant_triggered_ability`, `game/continuous.py`'s layer-6 pass,
`GameState._granted_ability_cache`) via the two registered cards.
"""

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_options_for
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def elf(name, power=1, toughness=1):
    return Card(id=name, name=name, type_line="Creature — Elf", is_creature=True,
                power=power, toughness=toughness)


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def tyvar_kell():
    # `is_planeswalker` derives from `type_line`; irrelevant to the static
    # grant test either way — only its bound `static_effects` matter here.
    return Card(id="Tyvar Kell", name="Tyvar Kell", type_line="Legendary Planeswalker — Tyvar",
                loyalty=5)


def dionus():
    return Card(id="Dionus, Elvish Archdruid", name="Dionus, Elvish Archdruid",
                type_line="Legendary Creature — Elf Druid", is_creature=True,
                power=2, toughness=2)


# ---------------------------------------------------------------------------
# Tyvar Kell — grant_mana_ability (Elves you control have "{T}: Add {B}.")
# ---------------------------------------------------------------------------


def test_tyvar_kell_grants_a_mana_ability_to_elves():
    eng = make_engine()
    put(eng.state, tyvar_kell())
    an_elf = put(eng.state, elf("Llanowar Elves"))
    eng.recompute_continuous_effects()

    assert {"B": 1} in mana_options_for(an_elf)


def test_tyvar_kell_does_not_grant_mana_to_non_elves():
    eng = make_engine()
    put(eng.state, tyvar_kell())
    bear = put(eng.state, Card(id="Bear", name="Bear", type_line="Creature — Bear",
                                is_creature=True, power=2, toughness=2))
    eng.recompute_continuous_effects()

    assert mana_options_for(bear) == []


def test_tapping_an_elf_for_the_granted_mana_actually_produces_it():
    eng = make_engine()
    eng.begin_turn()
    put(eng.state, tyvar_kell())
    an_elf = put(eng.state, elf("Llanowar Elves"))
    eng.recompute_continuous_effects()

    player = eng.state.player_by_id("p1")
    produced = eng.tap_for_mana(player, an_elf)
    assert produced == {"B": 1}
    assert an_elf.tapped


def test_the_mana_grant_disappears_when_tyvar_kell_leaves():
    eng = make_engine()
    tk = put(eng.state, tyvar_kell())
    an_elf = put(eng.state, elf("Llanowar Elves"))
    eng.recompute_continuous_effects()
    assert mana_options_for(an_elf) == [{"B": 1}]

    eng.state.battlefield.remove(tk)
    eng.recompute_continuous_effects()
    assert mana_options_for(an_elf) == []


# ---------------------------------------------------------------------------
# Dionus, Elvish Archdruid — grant_triggered_ability
# ---------------------------------------------------------------------------


def test_dionus_grants_a_triggered_ability_to_elves():
    eng = make_engine()
    put(eng.state, dionus())
    an_elf = put(eng.state, elf("Fyndhorn Elder"))
    eng.recompute_continuous_effects()

    assert len(an_elf.granted_triggered_abilities) == 1


def test_a_tap_cost_on_the_elf_triggers_dionus_untap_and_counter():
    eng = make_engine()
    eng.begin_turn()  # p1's turn
    put(eng.state, dionus())
    an_elf = put(eng.state, elf("Fyndhorn Elder"))
    eng.recompute_continuous_effects()

    eng.rules.set_tapped(an_elf, True)
    eng.resolve_until_stable()

    assert not an_elf.tapped  # untapped again
    assert an_elf.plus_one_counters == 1


def test_the_granted_trigger_is_once_per_turn():
    eng = make_engine()
    eng.begin_turn()
    put(eng.state, dionus())
    an_elf = put(eng.state, elf("Fyndhorn Elder"))
    eng.recompute_continuous_effects()

    eng.rules.set_tapped(an_elf, True)
    eng.resolve_until_stable()
    assert an_elf.plus_one_counters == 1

    # Tap it again this same turn — the ability doesn't fire a second time
    # (RULE 603.2), so it just stays tapped with no extra counter.
    eng.rules.set_tapped(an_elf, True)
    eng.resolve_until_stable()
    assert an_elf.tapped
    assert an_elf.plus_one_counters == 1


def test_the_granted_trigger_resets_next_turn():
    eng = make_engine()
    eng.begin_turn()
    put(eng.state, dionus())
    an_elf = put(eng.state, elf("Fyndhorn Elder"))
    eng.recompute_continuous_effects()

    eng.rules.set_tapped(an_elf, True)
    eng.resolve_until_stable()
    assert an_elf.plus_one_counters == 1

    eng.begin_turn()  # p2's turn
    eng.begin_turn()  # back to p1
    eng.rules.set_tapped(an_elf, True)
    eng.resolve_until_stable()
    assert an_elf.plus_one_counters == 2


def test_tapping_one_elf_does_not_untap_a_different_elf():
    # The scoping fix this mechanism needed: each Elf gets its own granted
    # ability instance, not one shared trigger that reacts to *any* Elf.
    eng = make_engine()
    eng.begin_turn()
    put(eng.state, dionus())
    elf_a = put(eng.state, elf("Elf A"))
    elf_b = put(eng.state, elf("Elf B"))
    eng.recompute_continuous_effects()

    eng.rules.set_tapped(elf_a, True)
    eng.resolve_until_stable()

    assert not elf_a.tapped  # its own grant untapped it
    assert elf_a.plus_one_counters == 1
    assert not elf_b.tapped  # never tapped
    assert elf_b.plus_one_counters == 0


def test_the_trigger_grant_disappears_when_dionus_leaves():
    eng = make_engine()
    eng.begin_turn()
    d = put(eng.state, dionus())
    an_elf = put(eng.state, elf("Fyndhorn Elder"))
    eng.recompute_continuous_effects()
    assert len(an_elf.granted_triggered_abilities) == 1
    # Dionus's own text has no "other" qualifier — it grants to itself too
    # (it's an Elf), so both it and the other Elf are cached relationships.
    assert len(d.granted_triggered_abilities) == 1
    assert len(eng.state._granted_ability_cache) == 2

    eng.state.battlefield.remove(d)
    eng.recompute_continuous_effects()

    assert an_elf.granted_triggered_abilities == []
    assert eng.state._granted_ability_cache == {}

    # And behaviourally: tapping it now does nothing extra.
    eng.rules.set_tapped(an_elf, True)
    eng.resolve_until_stable()
    assert an_elf.tapped
    assert an_elf.plus_one_counters == 0


def test_the_grant_only_fires_during_the_controllers_turn():
    eng = make_engine()
    put(eng.state, dionus())
    an_elf = put(eng.state, elf("Fyndhorn Elder"))
    eng.recompute_continuous_effects()

    eng.begin_turn()  # p1's turn 1
    eng.begin_turn()  # p2's turn — an_elf's controller (p1) doesn't have priority-turn
    eng.rules.set_tapped(an_elf, True)
    eng.resolve_until_stable()

    assert an_elf.tapped  # not p1's turn — Dionus's grant didn't fire
    assert an_elf.plus_one_counters == 0
