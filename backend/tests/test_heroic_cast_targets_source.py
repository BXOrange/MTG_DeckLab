"""RULE 702.34a's un-keyworded **Heroic** template — "Whenever you cast a
spell that targets ~, put a +1/+1 counter on ~." (Akroan Skyguard /
Battlewise Hoplite / Hero of Iroas / Wingsteed Rider / Fabled Hero /
Tenth District Legionnaire — the whole Theros + GRN + LOTR Heroic cycle).

`segmenter._CAST_SPELL_TARGETS_SOURCE_TRIGGER_RE` → a `SPELL_CAST`
triggered ability with `requires_spell_targets_source`; `casting_mixin`
stamps `target_instance_ids` (a frozenset) on the SPELL_CAST event, and
`effect_binder`'s new predicate checks the bound ability's own object is
among them.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _hero(eng, name="Wingsteed Rider"):
    o = GameObject(
        Card(id=name[:8], name=name, type_line="Creature — Pegasus Knight",
             is_creature=True, power=2, toughness=2,
             oracle_text=f"Flying\nWhenever you cast a spell that targets {name}, "
                         f"put a +1/+1 counter on {name}."),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    o.controller_id = "p1"
    o.summoning_sick = False
    bind_from_catalogue(o)
    eng.state.add_to_battlefield(o)
    return o


def _bystander(eng, controller="p1"):
    o = GameObject(Card(id="by", name="Bystander", type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2),
                   owner_id=controller, zone=Zone.BATTLEFIELD)
    o.controller_id = controller
    eng.state.add_to_battlefield(o)
    return o


def _giant_growth(eng, player="p1"):
    c = Card(id="gg", name="Giant Growth", type_line="Instant", is_instant=True,
             mana_cost_string="{G}",
             oracle_text="Target creature gets +3/+3 until end of turn.")
    o = GameObject(c, owner_id=player, zone=Zone.HAND)
    o.controller_id = player
    bind_from_catalogue(o)
    eng.state.player_by_id(player).hand.append(o)
    return o


# --- parse -----------------------------------------------------------------


def test_real_cards_modeled():
    for name, text in [
        ("Wingsteed Rider",
         "Flying\nHeroic — Whenever you cast a spell that targets Wingsteed Rider, "
         "put a +1/+1 counter on Wingsteed Rider."),
        ("Battlewise Hoplite",
         "Heroic — Whenever you cast a spell that targets Battlewise Hoplite, "
         "put a +1/+1 counter on Battlewise Hoplite, then scry 1."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Creature — Human Soldier",
                 is_creature=True, power=2, toughness=2, oracle_text=text,
                 keywords=["Heroic"])  # Scryfall lists the ability-word label here
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_counter_added_when_the_spell_targets_the_hero():
    eng = _engine()
    hero = _hero(eng)
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1})
    gg = _giant_growth(eng)

    eng.cast_spell(p1, gg, targets=[hero])
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert hero.counters.get("+1/+1") == 1


def test_no_counter_when_the_spell_targets_something_else():
    eng = _engine()
    hero = _hero(eng)
    other = _bystander(eng)
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1})
    gg = _giant_growth(eng)

    eng.cast_spell(p1, gg, targets=[other])
    assert eng.rules.put_triggers_on_stack() == 0
    assert "+1/+1" not in hero.counters
