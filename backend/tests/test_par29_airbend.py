"""PAR-29 — RULE 701.65 Airbend (Avatar: The Last Airbender).

"Airbend target X" = exile it; while it's exiled its owner may cast it for
a fixed {2} rather than its mana cost. Built on `ExileEffect`'s existing
`grant_owner_play_permission` (→ `GameState.exile_cast_condition`) plus a
new `owner_play_permission_cost` that stamps `GameState.
exile_cast_cost_override`, which `GameEngine.effective_cast_cost` consults
as a fixed alternative cost (like Flashback/Escape's graveyard alt cost).

Reference: models/game_state.py (`exile_cast_cost_override`), game/
effects.py (`ExileEffect.owner_play_permission_cost`), game/engine/
casting_mixin.py (`effective_cast_cost`), parser/oracle/catalogue/
handlers.py (`_airbend`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse -----------------------------------------------------------------


def test_airbend_clause_forms():
    a = match_clause("airbend target nonland permanent")
    assert a and a[0].type == "exile"
    assert a[0].params["target_kind"] == "nonland_permanent"
    assert a[0].params["grant_owner_play_permission"] is True
    assert a[0].params["owner_play_permission_cost"] == "{2}"

    b = match_clause("airbend up to 2 target creatures")
    assert b and b[0].params == {
        "target_kind": "creature", "grant_owner_play_permission": True,
        "owner_play_permission_cost": "{2}", "count": 2, "optional": True,
        # PAR-30 (Firebending residue): airbend now marks its exile so
        # `ExileEffect` fires EventType.BENT for Avatar Aang.
        "bend_kind": "airbend",
    }

    # "creature or spell" — the airbend-a-spell form (v145)
    cs = match_clause("airbend up to 1 other target creature or spell")
    assert cs and cs[0].type == "exile"
    assert cs[0].params["target_kind"] == "spell_or_creature"
    assert cs[0].params["spell_or_permanent"] is True
    assert cs[0].params["count"] == 1 and cs[0].params["optional"] is True
    # "nonland permanent or spell" isn't a real template — fail closed
    assert match_clause("airbend target nonland permanent or spell") is None


def test_airbend_qualifier_forms_v144():
    # "another target creature" — no "you control" → plain kind
    assert match_clause("airbend another target creature")[0].params["target_kind"] == "creature"
    # "target creature you control"
    assert match_clause("airbend target creature you control")[0].params["target_kind"] == (
        "creature_you_control"
    )
    # "another target creature you control" → source-excluding kind
    assert match_clause("airbend another target creature you control")[0].params["target_kind"] == (
        "other_creature_you_control"
    )
    # "another target nonland permanent you control"
    assert match_clause(
        "airbend another target nonland permanent you control"
    )[0].params["target_kind"] == "nonland_permanent_you_control"
    # "any number of other target nonland permanents you control"
    anynum = match_clause("airbend any number of other target nonland permanents you control")
    assert anynum[0].params["target_kind"] == "nonland_permanent_you_control"
    assert anynum[0].params["count"] == 10 and anynum[0].params["optional"] is True


def test_airbend_that_creature_trigger_subject_form():
    got = match_clause("airbend that creature")
    assert got == [EffectSpec("exile", {
        "target_kind": "trigger_subject",
        "grant_owner_play_permission": True,
        "owner_play_permission_cost": "{2}",
        "bend_kind": "airbend",  # PAR-30 Firebending residue — see above
    })]
    assert match_clause("airbend it") == got


def test_real_airbend_cards_modeled():
    for name, text in [
        ("Airbending Lesson", "Airbend target nonland permanent.\nDraw a card."),
        ("Whirlwind Technique", "Airbend up to two target creatures."),
        ("Airbender's Reversal", "Airbend target creature you control."),
        ("Monk Gyatso",
         "Whenever another creature you control becomes the target of a spell "
         "or ability, you may airbend that creature."),
    ]:
        tl = "Creature — Human Monk" if name == "Monk Gyatso" else "Sorcery"
        c = Card(id=name[:3], name=name, type_line=tl,
                 is_sorcery=tl == "Sorcery", is_creature=tl != "Sorcery",
                 power=2 if tl != "Sorcery" else None,
                 toughness=3 if tl != "Sorcery" else None,
                 mana_cost_string="{2}{W}", oracle_text=text)
        assert parse_oracle(c).modeled, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def test_airbend_exiles_and_grants_fixed_cost_cast_permission():
    eng, state = _engine()
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    victim = GameObject(
        Card(id="V", name="Big Bear", type_line="Creature — Bear", is_creature=True,
             power=5, toughness=5, mana_cost_string="{4}{G}{G}", converted_mana_cost=6),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    victim.controller_id = "p2"
    state.add_to_battlefield(victim)

    spell = GameObject(
        Card(id="AL", name="Airbending Lesson", type_line="Sorcery", is_sorcery=True,
             oracle_text="Airbend target nonland permanent.\nDraw a card."),
        owner_id="p1", zone=Zone.STACK,
    )
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    for eff in spell.spell_effects:
        eff.apply(eng.rules.context, [victim])

    assert victim not in state.battlefield
    assert victim in p2.exile
    # owner (p2) may cast it from exile...
    assert eng._has_conditional_exile_permission(victim, p2)
    assert not eng._has_conditional_exile_permission(victim, p1)   # not the airbender
    # ...for a fixed {2}, not its printed {4}{G}{G}
    assert state.exile_cast_cost_override.get(victim.instance_id) == "{2}"
    assert eng.effective_cast_cost(p2, victim).converted_mana_cost == 2


def test_airbend_trigger_subject_exiles_the_triggering_creature():
    eng, state = _engine()
    p1 = state.player_by_id("p1")

    gyatso = GameObject(
        Card(id="MG", name="Monk Gyatso", type_line="Creature — Human Monk",
             is_creature=True, power=2, toughness=3,
             oracle_text=("Whenever another creature you control becomes the target "
                          "of a spell or ability, you may airbend that creature.")),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    gyatso.controller_id = "p1"
    state.add_to_battlefield(gyatso)
    bind_from_catalogue(gyatso)

    ally = GameObject(
        Card(id="AL2", name="Ally", type_line="Creature — Bird", is_creature=True,
             power=1, toughness=1, mana_cost_string="{3}{W}", converted_mana_cost=4),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    ally.controller_id = "p1"
    state.add_to_battlefield(ally)

    trig = next(t for t in gyatso.triggered_abilities
                if t.trigger_event == "BECOMES_TARGET")
    # simulate the ally becoming the target: the effect reads the firing
    # event's own instance_id (ExileEffect target_kind="trigger_subject")
    eng.rules.context.trigger_event = {"instance_id": ally.instance_id}
    for eff in trig.effects:
        eff.apply(eng.rules.context, [])
    eng.rules.context.trigger_event = None

    assert ally not in state.battlefield and ally in p1.exile
    assert state.exile_cast_cost_override.get(ally.instance_id) == "{2}"


def test_airbend_a_spell_pulls_it_off_the_stack_into_exile():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.models.game.game_state import StackItem
    from mtg_analyzer.parser.oracle.spec import EffectSpec as ES

    eng, state = _engine()
    p2 = state.player_by_id("p2")

    spell = GameObject(
        Card(id="BOLT", name="Lightning Bolt", type_line="Instant", is_instant=True,
             mana_cost_string="{R}", converted_mana_cost=1),
        owner_id="p2", zone=Zone.STACK,
    )
    spell.controller_id = "p2"
    state.stack.append(StackItem(kind="spell", controller_id="p2", obj=spell, targets=[]))

    src = GameObject(Card(id="AANG", name="Aang, Swift Savior",
                          type_line="Legendary Creature", is_creature=True,
                          power=3, toughness=3), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"

    eff = build_effects([ES("exile", {
        "target_kind": "spell_or_creature", "spell_or_permanent": True,
        "grant_owner_play_permission": True, "owner_play_permission_cost": "{2}",
        "count": 1, "optional": True,
    })], src)[0]
    eff.apply(eng.rules.context, [spell])

    assert state.stack == []               # never resolves
    assert spell in p2.exile
    assert state.exile_cast_cost_override.get(spell.instance_id) == "{2}"
    assert eng.effective_cast_cost(p2, spell).converted_mana_cost == 2


def test_airbend_spell_or_creature_effect_also_handles_a_battlefield_creature():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.spec import EffectSpec as ES

    eng, state = _engine()
    p2 = state.player_by_id("p2")
    ox = GameObject(
        Card(id="OX", name="Ox", type_line="Creature — Ox", is_creature=True,
             power=4, toughness=4, mana_cost_string="{3}{G}", converted_mana_cost=4),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    ox.controller_id = "p2"
    state.add_to_battlefield(ox)
    src = GameObject(Card(id="AANG2", name="Aang, Swift Savior",
                          type_line="Legendary Creature", is_creature=True,
                          power=3, toughness=3), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"

    eff = build_effects([ES("exile", {
        "target_kind": "spell_or_creature", "spell_or_permanent": True,
        "grant_owner_play_permission": True, "owner_play_permission_cost": "{2}",
        "count": 1, "optional": True,
    })], src)[0]
    eff.apply(eng.rules.context, [ox])

    assert ox not in state.battlefield and ox in p2.exile
    assert state.exile_cast_cost_override.get(ox.instance_id) == "{2}"
