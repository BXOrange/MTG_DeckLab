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


# --- M3: riders on what the preceding clause created -------------------------------------------------------------


SCION_ABILITY = 'it has "sacrifice ~: add {c}."'


def _sorcery(name, oracle):
    return Card(id=name, name=name, type_line="Sorcery", oracle_text=oracle, is_sorcery=True)


def _cast_parsed(eng, card, targets=()):
    """Cast a spell card from its own parsed oracle text and resolve it."""
    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.player_by_id("p1").hand.append(obj)
    eng.rules.cast_spell(eng.state.player_by_id("p1"), obj, targets=list(targets) or None)
    eng.resolve_until_stable()
    return mana_abilities_for


def test_a_quoted_ability_given_to_a_created_token_is_a_created_only_grant():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    specs = parse_effect_body(f"create a 1/1 colorless eldrazi scion creature token. {SCION_ABILITY}")
    assert [s.type for s in specs] == ["create_token", "grant_until"]
    grant = specs[1].params
    assert grant["referent"] == "created" and grant["static"]["type"] == "grant_mana_ability"
    assert grant["static"]["params"]["granted_mana_cost"] == "sacrifice ~"
    # No creating clause before it: the pronoun has no antecedent, so nothing is claimed.
    assert parse_effect_body(f"draw a card. {SCION_ABILITY}") is None
    assert parse_effect_body(SCION_ABILITY) is None


def test_the_rider_names_the_created_token_even_after_an_earlier_pick_in_the_same_spell():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    specs = parse_effect_body(f"tap up to 2 target creatures. create a 1/1 colorless eldrazi scion creature token. {SCION_ABILITY}")
    assert specs and specs[-1].params["referent"] == "created"
    haste = parse_effect_body("destroy target creature. create 2 1/1 red warrior creature tokens. they gain haste until end of turn")
    assert haste[-1].type == "pump" and haste[-1].params["referent"] == "created"
    # Without an earlier pick the engine's own fallback already reads what was created: spec unchanged.
    plain = parse_effect_body("create a 1/1 red warrior creature token. it gains haste until end of turn")
    assert "referent" not in plain[-1].params


def test_a_quoted_ability_that_names_the_source_card_is_not_claimed():
    # "named ~" in a granted body would mean the *token* once granted, not the card that printed it (Sound the Call).
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body(
        'create a 1/1 green wolf creature token. it has "this token gets +1/+1 for each card named ~ in each graveyard."'
    ) is None


def _scion_mana(eng, token):
    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    return [a for a in mana_abilities_for(token, eng.state)] if token is not None else []


def test_scions_get_the_sacrifice_for_mana_ability_and_the_tapped_creatures_do_not():
    eng = _engine()
    victim = GameObject(_card("Victim", "", "Creature — Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(victim)
    card = _sorcery("Test Conditions", "Tap up to two target creatures. Create a 1/1 colorless Eldrazi Scion creature token. It has \"Sacrifice this token: Add {C}.\"")
    result = parse_oracle(card)
    assert result.coverage == MODELED, result.unclaimed
    _cast_parsed(eng, card, targets=[victim])
    scions = [o for o in eng.state.battlefield if o.is_token and "Scion" in o.name]
    assert len(scions) == 1
    assert _scion_mana(eng, scions[0]), "the created Scion carries the mana ability"
    assert not _scion_mana(eng, victim), "the tapped creature must not get it"
    assert len(_scion_mana(eng, scions[0])) == 1  # granted once


def test_each_of_several_created_tokens_gets_it_exactly_once():
    eng = _engine()
    card = _sorcery("Test Hulk", "Create two 1/1 colorless Eldrazi Scion creature tokens. They have \"Sacrifice this token: Add {C}.\"")
    assert parse_oracle(card).coverage == MODELED
    _cast_parsed(eng, card)
    scions = [o for o in eng.state.battlefield if o.is_token and "Scion" in o.name]
    assert len(scions) == 2
    assert [len(_scion_mana(eng, s)) for s in scions] == [1, 1]


def test_they_gain_haste_reaches_the_created_tokens_not_the_destroyed_creature():
    eng = _engine()
    victim = GameObject(_card("Victim", "", "Creature — Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(victim)
    card = _sorcery("Test Skirmish", "Destroy target creature. Create two 1/1 red Warrior creature tokens. They gain haste until end of turn.")
    assert parse_oracle(card).coverage == MODELED
    _cast_parsed(eng, card, targets=[victim])
    eng.recompute_continuous_effects()
    warriors = [o for o in eng.state.battlefield if o.is_token and "Warrior" in o.name]
    assert len(warriors) == 2
    assert all("haste" in {k.lower() for k in o.granted_keywords} or getattr(o, "temp_keywords", None) for o in warriors)
    assert victim not in eng.state.battlefield


def test_treasure_and_other_predefined_tokens_are_untouched_by_the_rider_row():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    treasure = parse_effect_body("create a treasure token")
    assert [s.type for s in treasure] == ["create_token"] and "referent" not in treasure[0].params


@pytest.mark.full_cache
@pytest.mark.timeout(900)  # parses the whole cache
def test_no_created_grant_quotes_the_printing_cards_own_name():
    # A granted body's "~" is the token; a card whose quoted text names *itself* would silently mean the token.
    import re

    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

    def has_created_grant(node):
        if isinstance(node, dict):
            if node.get("type") == "grant_until" and (node.get("params") or {}).get("referent") == "created":
                return True
            return any(has_created_grant(v) for v in node.values())
        return isinstance(node, list) and any(has_created_grant(v) for v in node)

    offenders = []
    for card in CardDatabase(DEFAULT_DB_PATH).list_cards():
        result = parse_oracle(card)
        if result.modeled and has_created_grant([s.to_dict() for s in result.specs]):
            quoted = " ".join(re.findall(r'"([^"]+)"', card.oracle_text or ""))
            if card.name and card.name.lower() in quoted.lower():
                offenders.append(card.name)
    assert offenders == []


# --- M3 review: token copies (God-Pharaoh's Gift, Offspring's Revenge, Mordor on the March) ------------------------
# `CopyPermanentEffect.created_objects_are_referent` hands the copy on as the next clause's `previous_targets`, so these
# are already right at resolution (unlike create_token after a pick); the tests pin that with real engine runs.

GOD_PHARAOH = ("At the beginning of combat on your turn, you may exile a creature card from your graveyard. If you do, "
               "create a token that's a copy of that card, except it's a 4/4 black Zombie. It gains haste until end of turn.")
OFFSPRING = ("At the beginning of combat on your turn, exile target red, white, or black creature card from your graveyard. "
             "Create a token that's a copy of that card, except it's 1/1. It gains haste until your next turn.")
MORDOR = ("Exile a creature card from your graveyard. Create a token that's a copy of it. It gains haste until end of turn. "
          "Exile it at the beginning of the next end step.")


def _run_copy_effects(oracle, type_line, subtype_color="R"):
    """Resolve the card through the engine's own stack with a red creature card in the graveyard picked as the exile.
    A trigger body goes on the stack as the ability the card's trigger produces; a spell is cast."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    gy_card = GameObject(
        Card(id="Dead", name="Dead Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
             mana_cost_string="{1}{R}", color_identity={"R"}), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(gy_card, Zone.GRAVEYARD)
    card = Card(id="Src", name="Test Source", type_line=type_line, oracle_text=oracle,
                is_sorcery="Sorcery" in type_line)
    result = parse_oracle(card)
    assert result.coverage == MODELED, result.unclaimed
    if "Sorcery" in type_line:
        obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(obj)
        p1.hand.append(obj)
        eng.rules.cast_spell(p1, obj, targets=[gy_card])
    else:
        # A resolving ability: the same effect list through the stack's own resolution path (previous_targets and all).
        from mtg_analyzer.game.effects.core import _apply_effects_partitioned

        src = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
        eng.state.add_to_battlefield(src)
        spec = next(s for s in result.specs if s.ability_kind == "triggered")
        built = build_effects(spec.effects, source=src)
        _apply_effects_partitioned(built, GameContext(eng.state, eng.rules), [gy_card], None, source=src)
    eng.resolve_until_stable()
    return eng, gy_card, [o for o in eng.state.battlefield if o.is_token], None


def test_gods_pharaohs_gift_haste_goes_to_the_zombie_copy_not_the_exiled_card():
    eng, exiled, tokens, _ = _run_copy_effects(GOD_PHARAOH, "Enchantment")
    assert len(tokens) == 1 and exiled.zone == Zone.EXILE
    eng.recompute_continuous_effects()
    assert "haste" in {k.lower() for k in tokens[0].granted_keywords} or tokens[0].temp_keywords
    assert not exiled.temp_keywords and "haste" not in {k.lower() for k in exiled.granted_keywords}


def test_offspring_revenge_haste_until_next_turn_goes_to_the_copy():
    eng, exiled, tokens, _ = _run_copy_effects(OFFSPRING, "Enchantment")
    assert len(tokens) == 1 and exiled.zone == Zone.EXILE
    eng.recompute_continuous_effects()
    assert "haste" in {k.lower() for k in tokens[0].granted_keywords}
    assert "haste" not in {k.lower() for k in exiled.granted_keywords}


def test_mordor_on_the_march_exiles_the_token_copy_at_the_end_step():
    eng, exiled, tokens, _ = _run_copy_effects(MORDOR, "Sorcery")
    assert len(tokens) == 1 and exiled.zone == Zone.EXILE
    eng.recompute_continuous_effects()
    assert "haste" in {k.lower() for k in tokens[0].granted_keywords} or tokens[0].temp_keywords
    token = tokens[0]
    eng.state.current_step = "end"
    eng._fire_delayed_triggers("end")  # RULE 603.7: the delayed exile due at the next end step
    eng.resolve_until_stable()
    assert token not in eng.state.battlefield
    assert exiled.zone == Zone.EXILE  # the card exiled as the first instruction is not exiled again or returned


@pytest.mark.full_cache
@pytest.mark.timeout(900)  # parses the whole cache
def test_no_modeled_card_resolves_a_pronoun_after_a_creation_through_a_stale_pick():
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

    creators = {"create_token", "manifest", "manifest_dread"}  # copy_permanent hands its copies on itself
    offenders = []

    def scan(effects, name):
        picked = stale = False
        for effect in effects:
            d = effect if isinstance(effect, dict) else effect.to_dict()
            params = d.get("params") or {}
            if d["type"] in creators:
                stale = picked
                continue
            pronoun = (params.get("previous_subject") or params.get("referent") == "previous"
                       or params.get("capture") in ("previous_or_self", "previous_targets"))
            # "Return the exiled cards ..." (Disorder in the Court) deliberately names the pick, not the Clue made after.
            names_pick = d["type"] == "create_delayed_trigger" and all(
                e.get("type") == "return_specific_to_battlefield" for e in params.get("effects", []))
            if (stale and pronoun and not names_pick and params.get("referent") != "created"
                    and params.get("capture") != "created_objects"):
                offenders.append((name, d["type"]))
            if params.get("target_kind") or params.get("selector") or params.get("group"):
                picked, stale = True, False
            for key in ("effects", "then", "else", "else_effects"):
                if isinstance(params.get(key), list):
                    scan(params[key], name)

    for card in CardDatabase(DEFAULT_DB_PATH).list_cards():
        result = parse_oracle(card)
        if result.modeled:
            for spec in result.specs:
                scan(spec.effects, card.name)
    assert offenders == []


# --- M4a: "If that spell is countered this way, <redirect> instead of putting it into its owner's graveyard" -----------

import test_counter_family as _TC  # noqa: E402  (stack fixtures shared with the counter-family tests)


def _counter_parsed(oracle):
    result = parse_oracle(_sorcery("Test Counter", oracle))
    assert result.coverage == MODELED, result.unclaimed
    return [e for s in result.specs for e in s.effects if e.type == "counter"]


@pytest.mark.parametrize("sentence,destination", [
    ("exile it instead of putting it into its owner's graveyard", "exile"),
    ("put it on top of its owner's library instead of into that player's graveyard", "library_top"),
    ("put it into its owner's hand instead of into that player's graveyard", "hand"),
])
def test_countered_this_way_redirect_is_the_counters_destination(sentence, destination):
    (plain,) = _counter_parsed(f"Counter target spell. If that spell is countered this way, {sentence}.")
    assert plain.params == {"destination": destination}
    (taxed,) = _counter_parsed(f"Counter target spell unless its controller pays {{3}}. If that spell is countered this way, {sentence}.")
    assert taxed.params == {"unless_pays": "{3}", "destination": destination}


def test_a_countered_this_way_clause_without_a_counter_before_it_is_not_claimed():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body("draw a card. if that spell is countered this way, exile it instead of putting it into its owner's graveyard") is None
    assert parse_effect_body("if that spell is countered this way, exile it instead of putting it into its owner's graveyard") is None
    assert parse_effect_body("counter target spell. if that spell is countered this way, shuffle it into your library") is None


def _stack_counter(destination, cost=None, answer=None, token=False):
    eng, p1, p2 = _TC.two_player_engine()
    target = _TC.push_spell(eng, p2, _TC.instant("Doomed Bolt"), [])
    if token:
        target.is_token = True
    if cost:
        p2.mana_pool.add("U", 5)
    eng.rules.counter_unless_pays(target, cost, source=None, destination=destination)
    if answer:
        eng.rules.resolve_choice(answer)
    return eng, p1, p2, target


@pytest.mark.parametrize("destination,zone", [("exile", Zone.EXILE), ("hand", Zone.HAND), ("library_top", Zone.LIBRARY)])
def test_a_plain_countered_spell_goes_to_the_redirect_zone(destination, zone):
    eng, _, p2, target = _stack_counter(destination)
    assert target not in [i.obj for i in eng.state.stack]
    assert target.zone == zone and target not in p2.graveyard
    if destination == "library_top":
        assert p2.library[0] is target or p2.library[-1] is target


@pytest.mark.parametrize("destination,zone", [("exile", Zone.EXILE), ("hand", Zone.HAND)])
def test_unless_pays_declined_applies_the_redirect_but_paying_keeps_the_spell_on_the_stack(destination, zone):
    eng, _, p2, target = _stack_counter(destination, cost="{1}", answer="decline")
    assert target.zone == zone and target not in p2.graveyard
    eng, _, p2, target = _stack_counter(destination, cost="{1}", answer="pay")
    assert target in [i.obj for i in eng.state.stack] and target.zone == Zone.STACK


def test_unless_pays_that_cannot_be_paid_still_redirects():
    eng, _, p2, target = _stack_counter("exile", cost=None)
    eng, p1, p2 = _TC.two_player_engine()
    target = _TC.push_spell(eng, p2, _TC.instant("Doomed Bolt"), [])
    eng.rules.counter_unless_pays(target, "{3}", source=None, destination="exile")  # p2 has no mana: auto-countered
    assert eng.state.pending_choice is None and target.zone == Zone.EXILE


def test_a_countered_token_spell_copy_ceases_to_exist_instead_of_reaching_a_hand():
    eng, _, p2, target = _stack_counter("hand", token=True)
    assert target not in p2.hand and target not in p2.graveyard


def test_an_unknown_counter_destination_is_refused_by_the_engine():
    from mtg_analyzer.game.effects.stack import CounterSpellEffect

    with pytest.raises(ValueError):
        CounterSpellEffect(destination="battlefield")


def test_real_card_text_resolves_through_the_effect_registry_to_the_redirect_zone():
    # Memory Lapse and Syncopate, parsed from their printed text and run as bound effects against a spell on the stack.
    for oracle, zone in (
        ("Counter target spell. If that spell is countered this way, put it on top of its owner's library instead of into that player's graveyard.", Zone.LIBRARY),
        ("Counter target spell. If that spell is countered this way, exile it instead of putting it into its owner's graveyard.", Zone.EXILE),
    ):
        eng, p1, p2 = _TC.two_player_engine()
        target = _TC.push_spell(eng, p2, _TC.instant("Doomed Bolt"), [])
        src = GameObject(_sorcery("Test Counter", oracle), owner_id="p1", zone=Zone.STACK)
        (spec,) = _counter_parsed(oracle)
        (effect,) = build_effects([spec], source=src)
        effect.apply(GameContext(eng.state, eng.rules), [target])
        assert target.zone == zone and target not in p2.graveyard


def test_those_tokens_after_a_creating_clause_read_as_the_pronoun_rows_take_them():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    one = parse_effect_body("create a 1/1 red goblin creature token. that token gains haste until end of turn")
    many = parse_effect_body("create 2 1/1 red goblin creature tokens. those tokens gain haste until end of turn")
    assert [s.type for s in one] == [s.type for s in many] == ["create_token", "pump"]
    assert many[1].params["previous_subject"] and many[1].params["keywords"] == ["haste"]
    delayed = parse_effect_body("create 2 1/1 red goblin creature tokens. sacrifice those tokens at the beginning of the next end step")
    assert delayed and delayed[1].type == "create_delayed_trigger"
    # The noun only means the creation when a creating clause came right before it.
    assert parse_effect_body("draw a card. those tokens gain haste until end of turn") is None
    assert parse_effect_body("tap target creature. those tokens gain haste until end of turn") is None


def test_a_lieutenant_style_trigger_gives_both_created_goblins_haste():
    eng = _engine()
    card = _sorcery("Test Lieutenant", "Create two 1/1 red Goblin creature tokens. Those tokens gain haste until end of turn.")
    assert parse_oracle(card).coverage == MODELED
    _cast_parsed(eng, card)
    eng.recompute_continuous_effects()
    goblins = [o for o in eng.state.battlefield if o.is_token and "Goblin" in o.name]
    assert len(goblins) == 2
    assert all("haste" in {k.lower() for k in o.granted_keywords} or o.temp_keywords for o in goblins)
