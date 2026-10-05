"""PAR-31 — "you get an emblem with '<ability>'" inner-body coverage.

Slice 2 (Jace, Unraveler of Secrets' −8 emblem): "Whenever an opponent
casts their first spell each turn, counter that spell." — "first" (n=1)
added to `segmenter._CAST_SPELL_ORDINAL_WORDS`, and the
`_CAST_SPELL_TRIGGER_NTH_RE` consumer gained a "counter that spell" /
"counter it" body via `_counter_triggering_spell_effects`
(`CounterSpellEffect.target_from_trigger_event`).

Slice 1: the multi-permanent-type keyword grant that Elspeth,
Knight-Errant's −8 emblem carries — "Artifacts, creatures, enchantments,
and lands you control have indestructible." — plus its standing-static
cousins (Fountain Watch, Spiritual Asylum). A `grant_keyword` scoped to
`permanents_you_control` narrowed by the `card_type` *list*
`continuous.affected_objects` already ORs (Grand Abolisher-shaped).
`static_handlers._MULTI_PERMANENT_TYPE_GRANT_RE`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

from tests.support.game import creature, make_engine, obj_on_battlefield


# --- parse -------------------------------------------------------------


def test_multi_type_grant_parses_as_card_type_list():
    assert static_effect_specs(
        "artifacts, creatures, enchantments, and lands you control have indestructible"
    ) == [
        EffectSpec("grant_keyword", {
            "keywords": ["indestructible"],
            "affects": "permanents_you_control",
            "card_type": ["artifact", "creature", "enchantment", "land"],
        })
    ]
    # two-word list, "X and Y" with no comma
    assert static_effect_specs(
        "artifacts and enchantments you control have shroud"
    )[0].params["card_type"] == ["artifact", "enchantment"]


def test_single_type_grant_untouched():
    # A one-word scope still routes through the PAR-3 permanent-type path
    # (a bare `card_type` string / dedicated selector), never this handler.
    specs = static_effect_specs("artifacts you control have hexproof")
    assert specs[0].params["affects"] == "artifacts_you_control"
    assert "card_type" not in specs[0].params or isinstance(
        specs[0].params.get("card_type"), str
    )
    # A creature scope stays a creature scope.
    assert static_effect_specs("creatures you control have flying")[0].params[
        "affects"
    ] == "creatures_you_control"


def test_unrecognised_word_in_list_fails_closed():
    assert static_effect_specs(
        "artifacts and goblins you control have haste"
    ) in (None, [])


# --- execute ---------------------------------------------------------


def test_grant_only_hits_your_permanents_of_listed_types():
    eng = make_engine([creature("mine")], [creature("theirs")])
    state = eng.state
    lord = obj_on_battlefield(
        state, eng,
        Card(id="fw", name="Fountain Watch", type_line="Enchantment",
             oracle_text="Artifacts and enchantments you control have shroud."),
        controller="p1",
    )
    bind_from_catalogue(lord)

    my_artifact = obj_on_battlefield(
        state, eng,
        Card(id="a1", name="My Rock", type_line="Artifact"),
        controller="p1",
    )
    my_creature = obj_on_battlefield(state, eng, creature("My Bear"), controller="p1")
    their_artifact = obj_on_battlefield(
        state, eng,
        Card(id="a2", name="Their Rock", type_line="Artifact"),
        controller="p2",
    )
    eng.recompute_continuous_effects()

    assert "shroud" in my_artifact.granted_keywords
    assert "shroud" in lord.granted_keywords  # the enchantment grants to itself
    assert "shroud" not in my_creature.granted_keywords  # creature not in the list
    assert "shroud" not in their_artifact.granted_keywords  # not yours


# --- end to end -----------------------------------------------------


def test_real_cards_modeled():
    cases = [
        ("Elspeth, Knight-Errant", "Legendary Planeswalker — Elspeth",
         "+1: Create a 1/1 white Soldier creature token.\n"
         "+1: Target creature gets +3/+3 and gains flying until end of turn.\n"
         "−8: You get an emblem with \"Artifacts, creatures, enchantments, and "
         "lands you control have indestructible.\""),
        ("Fountain Watch", "Enchantment",
         "Artifacts and enchantments you control have shroud."),
        ("Spiritual Asylum", "Enchantment",
         "Creatures and lands you control have shroud.\n"
         "When a creature you control attacks, sacrifice Spiritual Asylum."),
    ]
    for name, tl, text in cases:
        c = Card(id=name[:3], name=name, type_line=tl, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- slice 2: Jace, Unraveler emblem — counter the opponent's first spell ---


def _sorcery(name, text):
    return Card(id=name, name=name, type_line="Sorcery", oracle_text=text,
                mana_cost_string="{1}{U}", converted_mana_cost=2, is_sorcery=True)


def test_jace_emblem_body_parses_to_nth_cast_counter_trigger():
    c = Card(id="jus", name="Jace, Unraveler of Secrets",
             type_line="Legendary Planeswalker — Jace",
             oracle_text=(
                 "+1: Scry 1, then draw a card.\n"
                 "−2: Return target creature to its owner's hand.\n"
                 "−8: You get an emblem with \"Whenever an opponent casts their "
                 "first spell each turn, counter that spell.\""))
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, r.unclaimed
    emblem = next(e for s in r.specs for e in s.effects if e.type == "create_emblem")
    inner = emblem.params["ability"]
    assert inner["ability_kind"] == "triggered"
    assert inner["trigger"]["event"] == "SPELL_CAST"
    assert inner["trigger"]["is_nth_spell_cast_this_turn"] == 1
    assert inner["trigger"]["condition"]["controller"] == "not_you"
    assert inner["effects"][0]["type"] == "counter"
    assert inner["effects"][0]["params"]["target_from_trigger_event"] == "instance_id"


def test_first_spell_ordinal_also_covers_untargeted_bodies():
    # "Whenever you cast your first spell each turn, add {R}{R}." (Rodeo
    # Pyromancers) — the ordinal-word addition, not the counter body.
    c = Card(id="rp", name="Rodeo Pyromancers", type_line="Creature — Devil",
             is_creature=True, power=2, toughness=2,
             oracle_text="Whenever you cast your first spell each turn, add {R}{R}.")
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, r.unclaimed


def test_jace_emblem_counters_opponents_first_spell_only():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")

    emblem_src = _sorcery(
        "Jace Ultimate Shaped",
        "You get an emblem with \"Whenever an opponent casts their first "
        "spell each turn, counter that spell.\"")
    r = parse_oracle(emblem_src)
    assert r.modeled, r.unclaimed
    src_obj = GameObject(emblem_src, owner_id="p1", zone=Zone.HAND)
    attach_to_object(src_obj, r.specs)
    p1.hand.append(src_obj)
    p1.mana_pool.add_many({"U": 5})
    state.active_player_index = state.players.index(p1)
    state.current_step = "main1"
    eng.cast_spell(p1, src_obj)
    eng.resolve_until_stable()
    assert len(p1.emblems) == 1

    # p2 casts their first spell this turn — the emblem trigger counters it.
    spell = Card(id="bolt", name="Zap", type_line="Sorcery", is_sorcery=True,
                 mana_cost_string="{R}", converted_mana_cost=1,
                 oracle_text="Zap deals 3 damage to any target.")
    sp_obj = GameObject(spell, owner_id="p2", zone=Zone.HAND)
    attach_to_object(sp_obj, parse_oracle(spell).specs)
    p2.hand.append(sp_obj)
    p2.mana_pool.add_many({"R": 3})
    state.active_player_index = state.players.index(p2)
    state.current_step = "main1"
    eng.cast_spell(p2, sp_obj)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()  # emblem trigger resolves → counter
    eng.resolve_until_stable()

    assert sp_obj not in [o for o in state.stack]
    assert sp_obj in p2.graveyard
