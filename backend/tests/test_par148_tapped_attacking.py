"""PAR-148 "Tapped and attacking" residue — the shared grammar pieces and what they execute:

1. an inline token's **printed name** ("… token with flying named Ballistic Boulder that's tapped and
   attacking", Fire Navy Trebuchet), its leading "tapped and attacking" ("create a tapped and attacking 1/1
   Devil token", Pugnacious Pugilist) and a **quoted triggered ability** it carries;
2. the batch attack head naming a creature subtype ("whenever 1 or more Goblins you control attack");
3. a dig whose hit enters tapped and attacking (Jet, Rebel Leader / Raph & Mikey);
4. the plural self-reference of a multi-name card ("whenever Raph & Mikey attack");
5. a returned graveyard card entering with a finality counter (RULE 122.1h).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body, segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance

from tests.test_par119_attack_batch_head import _attack, _attackers
from tests.test_par119_cast_trigger_grammar import _engine


def _segment(text):
    return segment_line(text, allow_spell_effect=True, provenance=ParserProvenance.from_dict({}))


def _permanent(state, name, types, oracle, controller="p1", **kw):
    card = Card(id=name, name=name, type_line=types, oracle_text=oracle, **kw)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# -- the token tail -------------------------------------------------------------


def test_named_token_that_is_tapped_and_attacking_then_sacrificed():
    specs = parse_effect_body(
        "create a 2/1 colorless construct artifact creature token with flying named ballistic boulder "
        "that's tapped and attacking. sacrifice that token at the beginning of the next end step."
    )
    token, delayed = specs
    assert token.params["token_name"] == "Ballistic Boulder"
    assert token.params["keywords"] == ["flying"] and token.params["is_artifact"] is True
    assert token.params["tapped"] and token.params["attacking"]
    assert delayed.type == "create_delayed_trigger"


def test_leading_tapped_and_attacking_token_with_a_quoted_death_trigger():
    (spec,) = parse_effect_body(
        'create a tapped and attacking 1/1 red devil creature token with "when ~ dies, it deals 1 damage '
        'to any target."'
    )
    assert spec.params["tapped"] and spec.params["attacking"]
    assert spec.params["oracle_text"] == "when ~ dies, it deals 1 damage to any target"


def test_a_quoted_token_ability_nothing_models_stays_unclaimed():
    assert parse_effect_body('create a 1/1 red devil creature token with "whenever ~ frobnicates, wibble."') is None


def test_the_name_capture_does_not_swallow_a_timing_clause():
    # Giant Caterpillar: the token is named Butterfly; "at the beginning of the next end step" is the timing.
    assert parse_effect_body(
        "create a 1/1 green insect creature token with flying named butterfly at the beginning of the next end step."
    ) is None


def test_devil_token_deals_damage_when_it_dies():
    engine, state = _engine()
    state.current_step = "main1"
    p2 = state.player_by_id("p2")
    maker = _permanent(
        state, "Devil Maker", "Creature — Bear",
        'Whenever ~ enters, create a 1/1 red devil creature token with "When this token dies, it deals 1 '
        'damage to any target."',
        is_creature=True, power=1, toughness=1,
    )
    engine.state.fire_event(__import__("mtg_analyzer.models.game.events", fromlist=["GameEvent"]).GameEvent(
        "ENTERS_BATTLEFIELD", instance_id=maker.instance_id, controller_id="p1", object=maker.name,
        object_types=["creature"],
    ))
    engine.resolve_until_stable()
    devil = next(o for o in state.battlefield if o.name == "Devil")
    assert devil.card.oracle_text.lower().startswith("when this token dies") or "dies" in devil.card.oracle_text
    engine.rules.destroy(devil)
    engine.resolve_until_stable()
    pc = state.pending_choice
    if pc is not None:  # a target prompt for "any target"
        option = next(o for o in pc["options"] if o.get("label") == "p2" or o.get("id") == "p2")
        engine.rules.resolve_choice(option["id"])
        engine.resolve_until_stable()
    assert p2.life == 19


# -- the batch attack head ------------------------------------------------------


def test_subtype_batch_attack_head_parses():
    seg = _segment(
        "whenever 1 or more goblins and/or orcs you control attack, draw a card."
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == "PLAYER_ATTACKED"
    assert seg.spec.trigger["condition"]["group_filter"] == {"subtypes_any": ["goblin", "orc"]}


def test_subtype_batch_attack_head_fires_only_for_a_matching_attacker():
    for attackers, expected in (
        ([("Goblin Guide", "Creature — Goblin Scout", [])], 1),
        ([("Bear", "Creature — Bear", [])], 0),
    ):
        engine, state = _engine()
        state.current_step = "main1"
        p1 = state.player_by_id("p1")
        for i in range(4):
            p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Land"),
                                         owner_id="p1", zone=Zone.LIBRARY))
        _permanent(state, "Kreat", "Creature — Goblin", (
            "Whenever 1 or more Goblins you control attack, draw a card."
        ), is_creature=True, power=2, toughness=2)
        before = len(p1.hand)
        _attack(engine, state, _attackers(state, attackers))
        assert len(p1.hand) - before == expected, attackers


# -- the dig --------------------------------------------------------------------


def test_look_at_top_cards_and_put_a_hit_tapped_and_attacking_parses():
    (spec,) = [e for s in parse_oracle(Card(
        id="Jet", name="Jet, Rebel Leader", type_line="Legendary Creature — Human Rebel", is_creature=True,
        oracle_text=(
            "Whenever Jet, Rebel Leader attacks, look at the top five cards of your library. You may put a "
            "creature card with mana value 3 or less from among them onto the battlefield tapped and "
            "attacking. Put the rest on the bottom of your library in a random order."
        ),
    )).specs for e in s.effects]
    assert spec.params["action"] == "library_to_battlefield_attacking"


def test_reveal_until_a_creature_puts_it_onto_the_battlefield_tapped_and_attacking():
    (spec,) = parse_effect_body(
        "reveal cards from the top of your library until you reveal a creature card. put that card onto "
        "the battlefield tapped and attacking and the rest on the bottom of your library in a random order."
    )
    assert spec.type == "dig_until" and spec.params["hit_destination"] == "battlefield_attacking"


def test_raph_and_mikey_dig_enters_the_hit_attacking():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = state.player_by_id("p1")
    p1.library.clear()
    hit = GameObject(Card(id="Hit", name="Hit", type_line="Creature — Bear", is_creature=True, power=3,
                          toughness=3), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(hit)
    p1.library.append(GameObject(Card(id="L", name="L", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    raph = _permanent(state, "Raph & Mikey, Troublemakers", "Legendary Creature — Mutant Ninja Turtle", (
        "Trample, haste\nWhenever Raph & Mikey attack, reveal cards from the top of your library until you "
        "reveal a creature card. Put that card onto the battlefield tapped and attacking and the rest on "
        "the bottom of your library in a random order."
    ), is_creature=True, power=4, toughness=4)
    state.current_phase = "combat"
    _attack(engine, state, [raph])
    assert hit in state.battlefield
    assert hit.attacking and hit.tapped


# -- plural self-reference ------------------------------------------------------


def test_plural_self_reference_verbs_fold_to_the_singular_grammar():
    assert normalize("Whenever Raph & Mikey attack, draw a card.", "Raph & Mikey") == "whenever ~ attacks, draw a card."
    assert normalize("Whenever Aang and Katara enter or attack, draw.", "Aang and Katara") == (
        "whenever ~ enters or attacks, draw."
    )
    # nothing else is touched
    assert normalize("Creatures you control attack each combat if able.") == (
        "creatures you control attack each combat if able."
    )


# -- finality counter -----------------------------------------------------------


def test_return_from_graveyard_with_a_finality_counter_exiles_it_when_it_would_die():
    (spec,) = parse_effect_body(
        "return target creature card from your graveyard to the battlefield with a finality counter on it."
    )
    assert spec.params["extra_counters"] == {"kind": "finality", "count": 1}
    engine, state = _engine()
    state.current_step = "main1"
    p1 = state.player_by_id("p1")
    corpse = GameObject(Card(id="Corpse", name="Corpse", type_line="Creature — Bear", is_creature=True,
                             power=2, toughness=2), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(corpse)
    spell = GameObject(Card(id="Scythe", name="Scythe", type_line="Sorcery", is_sorcery=True,
                            mana_cost_string="{B}", converted_mana_cost=1, oracle_text=(
                                "Return target creature card from your graveyard to the battlefield with a "
                                "finality counter on it.")), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 1)
    engine.cast_spell(p1, spell, targets=[corpse])
    engine.resolve_until_stable()
    assert corpse in state.battlefield and corpse.counters.get("finality") == 1
    engine.rules.destroy(corpse)
    engine.resolve_until_stable()
    assert corpse in p1.exile and corpse not in p1.graveyard


def test_look_top_dig_hit_enters_tapped_and_attacking():
    from tests.test_par144_dig_family import _answer, _card, _engine as _dig_engine, _stock

    eng, p1 = _dig_engine()
    eng.state.current_phase = "combat"
    _stock(p1, _card("Bear"), _card("Filler", "Sorcery"))
    eng.rules.inspect_top_n_choose(
        p1, count=2, action="library_to_battlefield_attacking", criteria={"type": "creature"},
        rest_destination="library_bottom_random", optional=True,
    )
    _answer(eng, {"Bear"})
    bear = next(o for o in eng.state.battlefield if o.name == "Bear")
    assert bear.tapped and bear.attacking
