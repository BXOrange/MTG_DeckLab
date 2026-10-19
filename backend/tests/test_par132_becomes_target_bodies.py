"""PAR-132 -- bodies under a becomes-the-target head: "counter that spell or ability" (Glyph Keeper) and "that spell
or ability's controller sacrifices a land of their choice" (Lava Runner). RULE 701.5, 115, 603.1."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle

GLYPH = ("Whenever ~ becomes the target of a spell or ability for the first time each turn, counter that spell or "
         "ability.")
RUNNER = "Whenever ~ becomes the target of a spell or ability, that spell or ability's controller sacrifices a land of their choice."


def _game():
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Creature", is_creature=True, power=1, toughness=1)
              for i in range(30)]
    eng = GameEngine.new_game([("p1", "Alice", list(filler)), ("p2", "Bob", list(filler))], starting_life=20,
                              starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    return eng, eng.state


def _put(eng, card: Card, owner: str, zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id(owner).hand.append(obj)
    return obj


def _creature(name: str, text: str) -> Card:
    return Card(id=name[:6], name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=4,
                oracle_text=text)


def _shock(name: str) -> Card:
    return Card(id=name[:6], name=name, type_line="Instant", is_instant=True, oracle_text=f"{name} deals 1 damage to "
                "target creature.", mana_cost_string="{0}", converted_mana_cost=0)


def _cast_at(eng, state, spell, target, caster="p2"):
    # An instant is legal on the opponent's own main phase only through priority; give it as the active player's
    # opponent via the engine's direct cast, which is what the MEC-19 tests do too.
    eng.cast_spell(state.player_by_id(caster), spell, targets=[target])
    eng.resolve_until_stable()


def test_parse_is_head_gated():
    assert parse_oracle(_creature("Keeper", GLYPH)).coverage != UNMODELED
    assert parse_oracle(_creature("Runner", RUNNER)).coverage != UNMODELED
    assert parse_oracle(_creature("Elsewhere", "Whenever ~ attacks, counter that spell or ability.")).coverage == UNMODELED


def test_first_targeting_spell_is_countered_the_second_is_not():
    eng, st = _game()
    keeper = _put(eng, _creature("Keeper", GLYPH), "p1")
    first = _put(eng, _shock("Shock A"), "p2", Zone.HAND)
    second = _put(eng, _shock("Shock B"), "p2", Zone.HAND)
    _cast_at(eng, st, first, keeper)
    assert keeper.damage_marked == 0 and first.zone == Zone.GRAVEYARD  # countered: never resolved
    _cast_at(eng, st, second, keeper)
    assert keeper.damage_marked == 1  # RULE 603.2: only the first time each turn


def _ping_with(keeper_text: str) -> int:
    eng, st = _game()
    keeper = _put(eng, _creature("Keeper", keeper_text), "p2")
    pinger = _creature("Pinger", "When ~ enters, ~ deals 1 damage to target creature.")
    pinger.mana_cost_string, pinger.converted_mana_cost = "{0}", 0
    obj = _put(eng, pinger, "p1", Zone.HAND)
    st.player_by_id("p1").mana_pool.add_many({"C": 2})
    eng.cast_spell(st.player_by_id("p1"), obj)
    eng.resolve_until_stable()
    while st.pending_choice is not None:
        options = [o for o in st.pending_choice["options"] if o["id"] != "decline"]
        pick = next((o for o in options if o.get("instance_id") == keeper.instance_id), options[0])
        eng.rules.resolve_choice(str(pick["id"]))
        eng.resolve_until_stable()
    return keeper.damage_marked


def test_targeting_triggered_ability_is_countered_too():
    assert _ping_with("") == 1  # control: without the counter the ETB trigger does its damage
    assert _ping_with(GLYPH) == 0


def test_controller_of_the_targeting_spell_sacrifices_a_land():
    eng, st = _game()
    runner = _put(eng, _creature("Runner", RUNNER), "p1")
    for i in range(2):
        _put(eng, Card(id=f"l{i}", name=f"Swamp{i}", type_line="Basic Land — Swamp", is_land=True), "p2")
    shock = _put(eng, _shock("Shock C"), "p2", Zone.HAND)
    _cast_at(eng, st, shock, runner)
    while st.pending_choice is not None:
        eng.rules.resolve_choice(str(st.pending_choice["options"][0]["id"]))
        eng.resolve_until_stable()
    assert sum(1 for o in st.battlefield if o.is_land and o.controller_id == "p2") == 1
    assert sum(1 for o in st.battlefield if o.is_land and o.controller_id == "p1") == 0
