"""PAR-175: clause linkage across a sequence.

M1 -- "you may X. If you do, Y." behind a trigger head (RULE 608.2c outcome of an optional instruction). The
generic trigger path peels the leading "you may", which left Y's "if you do" without its antecedent; the peel now
keeps the pair as one `optional` wrapper when the peeled body cannot be read.
"""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import peel_optional

LOOT = "Whenever {subj}, you may draw a card. If you do, discard a card."


def _card(name, oracle, type_line="Creature — Wizard", **kw):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_creature=creature,
                power=1 if creature else None, toughness=1 if creature else None, **kw)


def _triggered(card):
    result = parse_oracle(card)
    assert result.coverage == MODELED, result.unclaimed
    return [s for s in result.specs if s.ability_kind == "triggered"]


@pytest.mark.parametrize("name,oracle,inner", [
    ("Test Loot", LOOT.format(subj="this creature deals combat damage to a player"), ["draw", "discard"]),
    ("Test Upkeep Exile",
     "At the beginning of your upkeep, you may exile two cards from your graveyard. If you do, put a +1/+1 counter on this creature.",
     ["exile_own_graveyard_cards", "add_counters"]),
    ("Test Tap", "When this creature enters, you may tap it. If you do, proliferate.", ["tap", "proliferate"]),
    ("Test Token", "Whenever this creature attacks, you may create a 2/2 green Wolf creature token. If you do, put a +1/+1 counter on this creature.",
     ["create_token", "add_counters"]),
    ("Test Lose", "Whenever this creature attacks, you may draw two cards. If you do, you lose 2 life.", ["draw", "lose_life"]),
])
def test_optional_pair_behind_a_trigger_is_one_optional_wrapper(name, oracle, inner):
    (trig,) = _triggered(_card(name, oracle))
    assert not trig.optional
    (wrapper,) = trig.effects
    assert wrapper.type == "optional"
    assert [e["type"] for e in wrapper.params["effects"]] == inner


def test_once_each_turn_sentence_becomes_the_trigger_limit_not_part_of_the_optional():
    oracle = LOOT.format(subj="you cast an instant or sorcery spell") + " This ability triggers only once each turn."
    (trig,) = _triggered(_card("Test Wall", oracle, "Creature — Wall"))
    assert trig.trigger["limit"] is True
    assert [e["type"] for e in trig.effects[0].params["effects"]] == ["draw", "discard"]


def test_a_readable_peeled_body_keeps_the_ability_level_optional():
    # Already claimed before PAR-175; the peel must still win so these specs do not change.
    body, optional = peel_optional("you may draw a card")
    assert (body, optional) == ("draw a card", True)
    (trig,) = _triggered(_card("Test Plain", "Whenever this creature attacks, you may draw a card."))
    assert trig.optional and [e.type for e in trig.effects] == ["draw"]


def test_an_unreadable_outcome_clause_still_fails_closed():
    result = parse_oracle(_card("Test Bad", "Whenever this creature attacks, you may draw a card. If you do, frobnicate the moon."))
    assert result.coverage != MODELED


def _engine():
    eng = GameEngine.new_game([("p1", "P1", []), ("p2", "P2", [])], starting_hand=0)
    eng.state.current_step = "main1"
    return eng


def _run_trigger_body(eng, card, answer, *, library=4, graveyard=0):
    """Resolve the card's (single) triggered ability body as if it had triggered, answering the yes/no."""
    p1 = eng.state.player_by_id("p1")
    for i in range(library):
        p1.add_to_zone(GameObject(_card(f"Lib{i}", "", "Creature — Bear"), owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    for i in range(graveyard):
        p1.add_to_zone(GameObject(_card(f"Gy{i}", "", "Creature — Bear"), owner_id="p1", zone=Zone.GRAVEYARD), Zone.GRAVEYARD)
    src = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(src)
    eng.state.add_to_battlefield(src)
    (trig,) = _triggered(card)
    for effect in build_effects(trig.effects, source=src):
        effect.apply(GameContext(eng.state, eng.rules))
    assert eng.state.pending_choice["kind"] == "composite_optional"
    eng.rules.resolve_choice(answer)
    eng.resolve_until_stable()
    return src, p1


def test_loot_yes_draws_then_discards_and_no_does_neither():
    card = lambda: _card("Test Loot", LOOT.format(subj="this creature deals combat damage to a player"))
    eng = _engine()
    _, p1 = _run_trigger_body(eng, card(), "yes")
    assert len(p1.graveyard) == 1 and len(p1.hand) == 0  # drew 1, discarded the only card in hand
    eng = _engine()
    _, p1 = _run_trigger_body(eng, card(), "decline")
    assert not p1.graveyard and not p1.hand


def test_if_you_do_follow_up_only_happens_after_the_optional_part_was_done():
    oracle = "At the beginning of your upkeep, you may exile two cards from your graveyard. If you do, put a +1/+1 counter on this creature."
    eng = _engine()
    src, p1 = _run_trigger_body(eng, _card("Test Upkeep Exile", oracle), "yes", graveyard=2)
    assert not p1.graveyard and src.counters.get("+1/+1") == 1
    eng = _engine()
    src, p1 = _run_trigger_body(eng, _card("Test Upkeep Exile", oracle), "decline", graveyard=2)
    assert len(p1.graveyard) == 2 and not src.counters.get("+1/+1")


def test_tap_it_then_proliferate_taps_the_source():
    eng = _engine()
    src, _ = _run_trigger_body(eng, _card("Test Tap", "When this creature enters, you may tap it. If you do, proliferate."), "yes")
    assert src.tapped


# --- RULE 608.2c: "if you do" means the antecedent was actually performed ---------------------------------------


def test_loot_with_an_empty_library_draws_nothing_so_discards_nothing():
    card = _card("Test Loot", LOOT.format(subj="this creature deals combat damage to a player"))
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    keep = GameObject(_card("Kept", "", "Creature — Bear"), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(keep)
    _, p1 = _run_trigger_body(eng, card, "yes", library=0)
    assert keep in p1.hand and not p1.graveyard


def test_exile_two_from_graveyard_is_not_offered_with_only_one_card():
    oracle = "At the beginning of your upkeep, you may exile two cards from your graveyard. If you do, put a +1/+1 counter on this creature."
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p1.add_to_zone(GameObject(_card("Gy0", "", "Creature — Bear"), owner_id="p1", zone=Zone.GRAVEYARD), Zone.GRAVEYARD)
    src = GameObject(_card("Test Sculptor", oracle), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(src)
    eng.state.add_to_battlefield(src)
    (trig,) = _triggered(src.card)
    for effect in build_effects(trig.effects, source=src):
        effect.apply(GameContext(eng.state, eng.rules))
    assert eng.state.pending_choice is None
    assert len(p1.graveyard) == 1 and not src.counters.get("+1/+1")


def test_tapping_an_already_tapped_source_is_not_doing_it():
    card = _card("Test Tap", "When this creature enters, you may tap it. If you do, you gain 3 life.")
    eng = _engine()
    src = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(src)
    eng.state.add_to_battlefield(src)
    src.tapped = True
    (trig,) = _triggered(card)
    life = eng.state.player_by_id("p1").life
    for effect in build_effects(trig.effects, source=src):
        effect.apply(GameContext(eng.state, eng.rules))
    eng.rules.resolve_choice("yes")
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == life


def test_exile_it_from_graveyard_exiles_that_card_and_a_card_that_left_is_not_exiled():
    oracle = ("When this creature dies, you may exile it. If you do, search your library for an enchantment card, "
              "put that card onto the battlefield, then shuffle.")
    for left in (False, True):
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        p1.add_to_zone(GameObject(_card("Aura", "", "Enchantment"), owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
        rector = GameObject(_card("Test Rector", oracle), owner_id="p1", zone=Zone.GRAVEYARD)
        p1.add_to_zone(rector, Zone.GRAVEYARD)
        bind_from_catalogue(rector)
        (trig,) = _triggered(rector.card)
        if left:
            p1.graveyard.remove(rector)  # shuffled away in response
        for effect in build_effects(trig.effects, source=rector):
            effect.apply(GameContext(eng.state, eng.rules))
        if eng.state.pending_choice:
            eng.rules.resolve_choice("yes")
        while eng.state.pending_choice:
            pc = eng.state.pending_choice
            eng.rules.resolve_choice(pc["options"][0].get("id") or pc["options"][0].get("instance_id"))
        found = [o for o in eng.state.battlefield if o.name == "Aura"]
        if left:
            assert not found and rector not in eng.state.player_by_id("p1").exile
        else:
            assert found and rector in p1.exile and rector not in p1.graveyard


def _creature_on_bf(eng, name, **kw):
    o = GameObject(_card(name, "", "Creature — Citizen"), owner_id="p1", zone=Zone.BATTLEFIELD)
    o.summoning_sick = False
    eng.state.add_to_battlefield(o)
    return o


def _run_attack_trigger(eng, oracle, allies, answer="yes"):
    src = GameObject(_card("Test Attacker", oracle), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(src)
    eng.state.add_to_battlefield(src)
    others = [_creature_on_bf(eng, f"Ally{i}") for i in range(allies)]
    (trig,) = _triggered(src.card)
    for effect in build_effects(trig.effects, source=src):
        effect.apply(GameContext(eng.state, eng.rules))
    asked = []
    while eng.state.pending_choice:
        pc = eng.state.pending_choice
        asked.append(pc["kind"])
        eng.rules.resolve_choice(answer if pc["kind"] == "composite_optional"
                                 else pc["options"][0].get("id") or pc["options"][0].get("instance_id"))
        eng.resolve_until_stable()
    return src, others, asked


TAP_TWO = "Whenever this creature attacks, you may tap two other untapped creatures you control. If you do, this creature can't be blocked this turn."


def test_tap_two_creatures_needs_two_to_tap_and_unblockable_follows_only_then():
    src, others, asked = _run_attack_trigger(_engine(), TAP_TWO, allies=1)
    assert not asked and not others[0].tapped and not src.temp_unblockable  # one creature cannot do it: not even offered
    src, others, asked = _run_attack_trigger(_engine(), TAP_TWO, allies=2)
    assert all(o.tapped for o in others) and src.temp_unblockable


def test_returning_a_creature_to_hand_is_followed_only_when_a_creature_could_be_returned():
    oracle = ("Whenever this creature attacks, you may tap another untapped creature you control. "
              "If you do, this creature can't be blocked this turn.")
    src, others, asked = _run_attack_trigger(_engine(), oracle, allies=0)
    assert not asked and not src.temp_unblockable


def test_sacrifice_it_then_follow_up_only_after_the_sacrifice():
    oracle = "Whenever this creature attacks, you may sacrifice it. If you do, you gain 4 life."
    eng = _engine()
    life = eng.state.player_by_id("p1").life
    src, _, _ = _run_attack_trigger(eng, oracle, allies=0)
    assert src not in eng.state.battlefield and eng.state.player_by_id("p1").life == life + 4


def test_pre_existing_tap_it_row_also_gets_the_outcome_test():
    # Previously MODELED shape (Academy Loremaster / Force Away family): draw with an empty library, then discard.
    card = _card("Test Force", "Whenever this creature attacks, if you control a creature with power 4 or greater, "
                 "you may draw a card. If you do, discard a card.")
    result = parse_oracle(card)
    if result.coverage == MODELED:  # intervening-if shapes keep the same wrapper
        (trig,) = [s for s in result.specs if s.ability_kind == "triggered"]
        assert trig.effects[0].params.get("if_you_do_from") == 1


# --- M2: the referent environment and the "if you do" antecedent allowlist ---------------------------------------


def test_previous_subject_and_selector_are_views_of_the_referent_environment():
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import (
        SELECTOR, SELECTOR_REFERENT, TARGET, TARGET_REFERENT, ClauseReading,
    )

    assert ClauseReading(previous_subject=True).referents == (TARGET_REFERENT,)
    assert ClauseReading(previous_selector=True).referents == (SELECTOR_REFERENT,)
    both = ClauseReading(referents=(TARGET_REFERENT, SELECTOR_REFERENT))
    assert both.previous_subject and both.previous_selector
    # Changing a view re-derives the environment; narrowing keeps only the asked kinds.
    assert both.but(previous_subject=False).referents == (SELECTOR_REFERENT,)
    assert both.referents_of(TARGET) == (TARGET_REFERENT,) and both.referents_of(SELECTOR) == (SELECTOR_REFERENT,)
    assert both.satisfies(ClauseReading(previous_subject=True)) and not ClauseReading().satisfies(both)


def test_a_sequence_hands_each_clause_what_the_clauses_before_it_produced():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body, produces

    chose = parse_effect_body("tap target creature")
    assert [r.kind for r in produces(chose)] == ["target"]
    group = parse_effect_body("untap all creatures you control")
    assert [r.kind for r in produces(group)] == ["selector"]
    assert produces(parse_effect_body("draw a card")) == ()
    # "it" reads what the previous clause chose; with no antecedent the pronoun stays unclaimed.
    assert parse_effect_body("tap target creature. it gains haste until end of turn") is not None
    assert parse_effect_body("draw a card. it gains haste until end of turn") is None


def test_antecedent_allowlist_matches_the_engine_view_and_refuses_unobservable_types():
    from mtg_analyzer.game.effects.composition import ALWAYS_DONE_ANTECEDENTS
    from mtg_analyzer.parser.oracle.spec import IF_YOU_DO_ANTECEDENT_TYPES, if_you_do_antecedent_ok

    assert ALWAYS_DONE_ANTECEDENTS <= IF_YOU_DO_ANTECEDENT_TYPES
    assert if_you_do_antecedent_ok([{"type": "draw", "params": {}}])
    assert if_you_do_antecedent_ok([{"type": "bind", "params": {"effects": [{"type": "draw", "params": {}}]}}])
    assert not if_you_do_antecedent_ok([{"type": "bind", "params": {"effects": [{"type": "add_mana", "params": {}}]}}])
    assert not if_you_do_antecedent_ok([{"type": "gain_life", "params": {}}])
    # An antecedent the fingerprint cannot see (life gain is observed, a player counter is not) fails closed.
    bad = parse_oracle(_card("Test Energy", "Whenever this creature attacks, you may get {E}{E}. If you do, draw a card."))
    assert bad.coverage != MODELED


@pytest.mark.full_cache
@pytest.mark.timeout(900)  # parses the whole cache
def test_every_emitted_if_you_do_antecedent_is_in_the_allowlist():
    from mtg_analyzer.parser.oracle.spec import if_you_do_antecedent_ok
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

    def walk(node, name, out):
        if isinstance(node, dict):
            params = node.get("params") if isinstance(node.get("params"), dict) else None
            if node.get("type") == "optional" and params and "if_you_do_from" in params:
                out.append((name, params["effects"][: params["if_you_do_from"]]))
            for value in node.values():
                walk(value, name, out)
        elif isinstance(node, list):
            for value in node:
                walk(value, name, out)

    antecedents = []
    for card in CardDatabase(DEFAULT_DB_PATH).list_cards():
        result = parse_oracle(card)
        if result.modeled:
            walk([s.to_dict() for s in result.specs], card.name, antecedents)
    assert antecedents
    assert [name for name, x in antecedents if not if_you_do_antecedent_ok(x)] == []
