"""PAR-74: "Spirit or Arcane spell" cast-trigger filter (Kamigawa) — and the
whole tail of unrelated small gaps it turned out to require.

The ticket's own diagnosis (a missing OR-of-two-subtypes cast-trigger
filter, "the same shape as an existing filtered cast trigger") was stale:
`_CAST_SPELL_SUBTYPE_WORDS`/the ``"arcane"`` special case already recognized
"spirit or arcane spell" (PAR-52+58, `segmenter.py`). What actually blocked
all 15 SOLO cards was that each one's *effect body* was a distinct,
previously-unclaimed family:

* `_CAST_SPELL_TRIGGER_RE`'s dispatch never passed ``self_subject=True`` the
  way its untyped sibling (`_CAST_SPELL_TRIGGER_PLAIN_RE`) already did — a
  bare "~" in a typed/color/subtype cast trigger's body (Kami of the Painted
  Road, Jade Idol, Orbweaver Kumo, and 22 cache-wide siblings) failed
  closed for no reason tied to this ticket at all.
* `handlers._token_keywords`/`_split_keywords_with_parametric` never
  resolved a landwalk *variant* slug ("forestwalk") the way `static_
  handlers._flag_keywords` already did for the static-grant family —
  Orbweaver Kumo's "~ gains forestwalk until end of turn." (+22 more cards).
* `_GROUP`'s selector list had "other creatures you control" (plural) and
  "each creature you control" (distributive) but not their combination,
  "each other creature you control" (Kodama of the South Tree, Zhang He).
* No parser family at all recognized RULE 613.4d's resolve-time "becomes a
  N/M [`<type>`] creature until end of turn" animation (self or target) —
  the engine primitive (`grant_until` wrapping a layer-4 `type_change`,
  Incubator's/Hedge Whisperer's own shape) already existed (Jade Idol,
  Soilshaper, Hydroform, Kamahl, Fist of Krosa, +more).
* "tap or untap target permanent" had a handler; "target **creature**"
  (Teller of Tales) didn't.
* "target opponent exiles a card from their hand" (Kyoki, Sanity's Eclipse)
  needed a genuinely new small primitive — `ExileHandCardEffect`/
  `RulesEngine.exile_hand_choice`, the exile-zone sibling of `discard_
  choice`.
* "an Aura card with enchant creature" (Tallowisp) needed `_SEARCH_CRITERIA`
  widened for an enchantment *subtype* (`card_query`'s ``type`` substring
  match already handles "Aura" correctly once offered).
* "reveal the top N, put all land cards into hand, the rest to the bottom in
  any order" (Elder Pine of Jukai) is `InspectTopChooseEffect` with
  ``max_picks`` set to the full inspected count — RULE 601.2c's "all" is a
  forced pick, not a real choice, so `_request_choose_objects` auto-resolves
  it (the general PAR-72 "look at the top X … put N …" row's own idiom).
* "that spell's mana value" (PAR-71's established referent) needed three
  new plumbing points: `DestroyEffect.filter["mana_value_from_trigger_
  event"]` (Celestial Kirin's mass wipe), `DiscardEffect.filter[...]`
  (Infernal Kirin's mass discard, `RulesEngine.discard_matching`), and
  `TargetSpec.exact_mana_value` (Skyfire Kirin's RULE 115 target bound,
  `GainControlUntilEndOfTurnEffect`) — the *exact-match* sibling of
  `TargetSpec.max_mana_value`'s existing ceiling.
* "counter target spirit or arcane spell" (Hisoka's Defiance) needed
  `TargetSpec.spell_filter["subtype_any"]` — `resolve_spell_filter`'s
  ``card_types`` key is a fixed main-type lookup, not a subtype substring
  match.
* "You may sacrifice/exile ~. If you do, `<effect>`." — `_SACRIFICE_THEN_
  WHEN_YOU_DO_RE` only matched the "When you do," connector; "If you do,"
  collapses the exact same way once the outer "you may" is already peeled
  (Dreamcatcher). The exile-zone sibling (`_EXILE_SELF_THEN_DELAYED_
  RETURN_RE`, Hikari, Twilight Guardian) reuses `ExileEffect(remember=True)`
  + `ReturnLinkedExileEffect` via a RULE 603.7 `create_delayed_trigger`.

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-74 entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _hand(player, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


# ---------------------------------------------------------------------------
# Real cards from the ticket: full MODELED verdict
# ---------------------------------------------------------------------------


def test_all_fifteen_solo_cards_now_modeled():
    for name, text in {
        "Celestial Kirin": (
            "Flying\nWhenever you cast a Spirit or Arcane spell, destroy "
            "all permanents with that spell's mana value."
        ),
        "Dreamcatcher": (
            "Whenever you cast a Spirit or Arcane spell, you may sacrifice "
            "this creature. If you do, draw a card."
        ),
        "Elder Pine of Jukai": (
            "Whenever you cast a Spirit or Arcane spell, reveal the top "
            "3 cards of your library. Put all land cards revealed this way "
            "into your hand and the rest on the bottom of your library in "
            "any order."
        ),
        "Hikari, Twilight Guardian": (
            "Whenever you cast a Spirit or Arcane spell, you may exile "
            "this creature. If you do, return it to the battlefield under "
            "its owner's control at the beginning of the next end step."
        ),
        "Hisoka's Defiance": "Counter target Spirit or Arcane spell.",
        "Infernal Kirin": (
            "Whenever you cast a Spirit or Arcane spell, target player "
            "reveals their hand and discards all cards with that spell's "
            "mana value."
        ),
        "Jade Idol": (
            "Whenever you cast a Spirit or Arcane spell, this artifact "
            "becomes a 4/4 Spirit artifact creature until end of turn."
        ),
        "Kami of the Painted Road": (
            "Whenever you cast a Spirit or Arcane spell, this creature "
            "gains protection from the color of your choice until end of "
            "turn."
        ),
        "Kodama of the South Tree": (
            "Whenever you cast a Spirit or Arcane spell, each other "
            "creature you control gets +1/+1 and gains trample until end "
            "of turn."
        ),
        "Kyoki, Sanity's Eclipse": (
            "Whenever you cast a Spirit or Arcane spell, target opponent "
            "exiles a card from their hand."
        ),
        "Orbweaver Kumo": (
            "Whenever you cast a Spirit or Arcane spell, this creature "
            "gains forestwalk until end of turn."
        ),
        "Skyfire Kirin": (
            "Whenever you cast a Spirit or Arcane spell, you may gain "
            "control of target creature with that spell's mana value "
            "until end of turn."
        ),
        "Soilshaper": (
            "Whenever you cast a Spirit or Arcane spell, target land "
            "becomes a 3/3 creature until end of turn. It's still a land."
        ),
        "Tallowisp": (
            "Whenever you cast a Spirit or Arcane spell, you may search "
            "your library for an Aura card with enchant creature, reveal "
            "it, put it into your hand, then shuffle."
        ),
        "Teller of Tales": (
            "Whenever you cast a Spirit or Arcane spell, you may tap or "
            "untap target creature."
        ),
    }.items():
        if name == "Jade Idol":
            type_line = "Artifact"
        elif name == "Hisoka's Defiance":
            type_line = "Instant"
        else:
            type_line = "Creature — Spirit"
        card = _card(name, type_line=type_line, oracle_text=text)
        result = parse_oracle(card)
        assert result.modeled, f"{name} stayed UNMODELED: {result.unclaimed}"


# ---------------------------------------------------------------------------
# PARSER: the missing self_subject on the typed cast-trigger dispatch
# ---------------------------------------------------------------------------


def test_typed_cast_trigger_self_subject_reference_now_reaches_self_only_rows():
    # Any self_subject_only row (here, the "protection from a color of
    # choice" grant) is only offered when the caller passes self_subject.
    assert parse_effect_body(
        "~ gains protection from the color of your choice until end of turn",
        self_subject=True,
    ) == [EffectSpec("grant_protection", {"target_kind": None})]


def test_typed_cast_trigger_subtype_color_branches_still_work():
    # Widening the shared row must not disturb its sibling color/type
    # branches.
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance

    prov = ParserProvenance(source="test", version=1)
    seg = segment_line(
        "whenever you cast an elf spell, draw a card.",
        allow_spell_effect=False, provenance=prov,
    )
    assert seg.claimed and seg.spec.trigger["spell_filter"] == {"subtype": "elf"}


# ---------------------------------------------------------------------------
# PARSER: landwalk variant as a temporary pump-grant keyword
# ---------------------------------------------------------------------------


def test_forestwalk_grant_until_end_of_turn():
    assert parse_effect_body("~ gains forestwalk until end of turn", self_subject=True) == [
        EffectSpec("pump", {"keywords": ["forestwalk"]})
    ]


def test_bare_landwalk_still_fails_closed():
    # RULE 702.14's own bare "landwalk" (no land type) stays unclaimed —
    # same discipline `static_handlers._flag_keywords` already applies.
    assert parse_effect_body("~ gains landwalk until end of turn", self_subject=True) is None


# ---------------------------------------------------------------------------
# PARSER: "each other creature you control" pump group
# ---------------------------------------------------------------------------


def test_each_other_creature_you_control_pump_group():
    assert parse_effect_body(
        "each other creature you control gets +1/+1 and gains trample until end of turn",
        self_subject=True,
    ) == [EffectSpec("pump", {
        "power": 1, "toughness": 1, "keywords": ["trample"],
        "selector": "other_creatures_you_control",
    })]


# ---------------------------------------------------------------------------
# PARSER + ENGINE: resolve-time "becomes a N/M creature" animation
# ---------------------------------------------------------------------------


def test_animate_self_with_subtype_and_type_qualifiers():
    assert parse_effect_body(
        "~ becomes a 4/4 spirit artifact creature until end of turn", self_subject=True,
    ) == [EffectSpec("grant_until", {
        "duration": "end_of_turn", "target_kind": None,
        "static": {
            "type": "type_change",
            "params": {
                "add_types": ["creature", "artifact"], "power": 4, "toughness": 4,
                "add_subtypes": ["Spirit"],
            },
        },
    })]


def test_animate_target_land_with_reminder_tail():
    assert parse_effect_body(
        "target land becomes a 3/3 creature until end of turn. It's still a land."
    ) == [EffectSpec("grant_until", {
        "duration": "end_of_turn", "target_kind": "land",
        "static": {"type": "type_change", "params": {"add_types": ["creature"], "power": 3, "toughness": 3}},
    })]


def test_animate_target_land_executes_and_becomes_attackable_creature():
    eng, state, p1, p2 = _engine()
    land = _bf(state, _card(
        "Test Land", type_line="Land",
        oracle_text="{T}: Target land becomes a 3/3 creature until end of turn. It's still a land.",
    ))
    eng.recompute_continuous_effects()
    assert not land.is_creature

    eng.activate_ability(p1, land, 0, targets=[land])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert land.is_creature
    assert land.power == 3 and land.toughness == 3
    assert "land" in land.type_words


# ---------------------------------------------------------------------------
# PARSER: "tap or untap target creature"
# ---------------------------------------------------------------------------


def test_tap_or_untap_target_creature():
    assert parse_effect_body("tap or untap target creature") == [
        EffectSpec("tap", {"target_kind": "creature", "choose_tap_or_untap": True})
    ]


# ---------------------------------------------------------------------------
# PARSER + ENGINE: exile a card from target player's hand
# ---------------------------------------------------------------------------


def test_exile_hand_card_parse():
    assert parse_effect_body("target opponent exiles a card from their hand") == [
        EffectSpec("exile_hand_card", {"count": 1, "target_kind": "player"})
    ]


def test_exile_hand_card_executes_and_moves_the_card_to_exile():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Kyoki", is_creature=True,
        oracle_text=(
            "Whenever you cast a spell, target opponent exiles a card "
            "from their hand."
        ),
    ))
    only_card = _hand(p2, _card("Only Card", "Sorcery", cost="{1}", cmc=1), controller="p2")
    spell = _hand(p1, _card("Test Spell", "Sorcery", cost="{1}", cmc=1))

    p1.mana_pool.add_many({"C": 1})
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    assert state.pending_choice is not None and state.pending_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice("p2")
    eng.resolve_until_stable()

    assert only_card not in p2.hand
    assert any(o.instance_id == only_card.instance_id for o in p2.exile)


# ---------------------------------------------------------------------------
# PARSER: "an Aura card with enchant creature" search criteria
# ---------------------------------------------------------------------------


def test_search_aura_card_with_enchant_creature():
    assert parse_effect_body(
        "search your library for an aura card with enchant creature, "
        "reveal it, put it into your hand, then shuffle",
        self_subject=True,
    ) == [EffectSpec("search", {"criteria": {"type": "Aura"}, "destination": "hand"})]


# ---------------------------------------------------------------------------
# PARSER: "reveal the top N, put all land cards into hand, rest to bottom"
# ---------------------------------------------------------------------------


def test_reveal_top_all_land_cards_to_hand():
    assert parse_effect_body(
        "reveal the top 3 cards of your library. put all land cards "
        "revealed this way into your hand and the rest on the bottom of "
        "your library in any order",
        self_subject=True,
    ) == [EffectSpec("inspect_top_choose", {
        "count": 3, "action": "library_to_hand", "filter": {"is_land": True},
        "max_picks": 3, "rest_destination": "library_bottom_random",
    })]


def test_reveal_top_all_land_cards_executes_and_takes_every_land():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Elder Pine", is_creature=True,
        oracle_text=(
            "Whenever you cast a spell, reveal the top 3 cards of your "
            "library. Put all land cards revealed this way into your "
            "hand and the rest on the bottom of your library in any order."
        ),
    ))
    top_to_bottom = [
        _card("Filler A"), _card("Test Forest", "Land"), _card("Filler B"),
    ]
    for c in reversed(top_to_bottom):
        p1.library.append(GameObject(c, owner_id="p1", zone=Zone.LIBRARY))
    spell = _hand(p1, _card("Test Spell", "Sorcery", cost="{1}", cmc=1))

    p1.mana_pool.add_many({"C": 1})
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert any(o.name == "Test Forest" for o in p1.hand)
    assert not any(o.name == "Filler A" for o in p1.hand)
    assert not any(o.name == "Filler B" for o in p1.hand)


# ---------------------------------------------------------------------------
# PARSER + ENGINE: "that spell's mana value" — mass destroy/discard filters
# and the RULE 115 exact-match target bound
# ---------------------------------------------------------------------------


def test_destroy_all_with_that_spells_mana_value_parses():
    assert parse_effect_body(
        "destroy all permanents with that spell's mana value", self_subject=True,
    ) == [EffectSpec("destroy", {
        "selector": "all_permanents", "filter": {"mana_value_from_trigger_event": True},
    })]


def test_destroy_all_with_that_spells_mana_value_executes():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Celestial Kirin", is_creature=True,
        oracle_text=(
            "Whenever you cast a spell, destroy all permanents with that "
            "spell's mana value."
        ),
    ))
    matching = _bf(state, _card("Matching MV", cmc=4, oracle_text=""))
    nonmatching = _bf(state, _card("Nonmatching MV", cmc=3, oracle_text=""))
    spell = _hand(p1, _card("Test Spell", "Sorcery", cost="{2}{G}{G}", cmc=4))

    p1.mana_pool.add_many({"C": 2, "G": 2})
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert matching not in state.battlefield
    assert nonmatching in state.battlefield


def test_discard_all_with_that_spells_mana_value_parses():
    assert parse_effect_body(
        "target player reveals their hand and discards all cards with "
        "that spell's mana value", self_subject=True,
    ) == [EffectSpec("discard", {
        "target_kind": "player", "filter": {"mana_value_from_trigger_event": True},
    })]


def test_discard_all_with_that_spells_mana_value_executes():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Infernal Kirin", is_creature=True,
        oracle_text=(
            "Whenever you cast a spell, target player reveals their hand "
            "and discards all cards with that spell's mana value."
        ),
    ))
    matching = _hand(p2, _card("Matching MV", "Sorcery", cost="{4}", cmc=4), controller="p2")
    nonmatching = _hand(p2, _card("Nonmatching MV", "Sorcery", cost="{3}", cmc=3), controller="p2")
    spell = _hand(p1, _card("Test Spell", "Sorcery", cost="{2}{G}{G}", cmc=4))

    p1.mana_pool.add_many({"C": 2, "G": 2})
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    assert state.pending_choice is not None and state.pending_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice("p2")
    eng.resolve_until_stable()

    assert matching not in p2.hand and matching in p2.graveyard
    assert nonmatching in p2.hand


def test_gain_control_with_that_spells_mana_value_parses():
    assert parse_effect_body(
        "gain control of target creature with that spell's mana value until end of turn"
    ) == [EffectSpec("gain_control_until_eot", {
        "target_kind": "creature", "exact_mana_value": "trigger_spell_mana_value",
    })]


def test_gain_control_with_that_spells_mana_value_only_offers_exact_match():
    from mtg_analyzer.game import targeting
    from mtg_analyzer.game.effects.exile_control import GainControlUntilEndOfTurnEffect

    eng, state, p1, p2 = _engine()
    matching = _bf(state, _card("Matching MV", is_creature=True, cmc=4), controller="p2")
    nonmatching = _bf(state, _card("Nonmatching MV", is_creature=True, cmc=3), controller="p2")

    spec = GainControlUntilEndOfTurnEffect(
        exact_mana_value="trigger_spell_mana_value",
    ).target_spec
    opts = targeting.legal_targets(state, "p1", spec, trigger_event={"mana_value": 4})
    ids = {o["instance_id"] for o in opts}
    assert matching.instance_id in ids
    assert nonmatching.instance_id not in ids


# ---------------------------------------------------------------------------
# PARSER + ENGINE: "counter target spirit or arcane spell" subtype filter
# ---------------------------------------------------------------------------


def test_counter_subtype_any_parses():
    assert parse_effect_body("counter target spirit or arcane spell") == [
        EffectSpec("counter", {"subtype_any": ["spirit", "arcane"]})
    ]


def test_counter_subtype_any_only_targets_matching_spells():
    from mtg_analyzer.game import targeting
    from mtg_analyzer.game.effects.core import CounterSpellEffect
    from mtg_analyzer.models.game.game_state import StackItem

    eng, state, p1, p2 = _engine()
    matching = _card("Matching Spirit", "Creature — Spirit", cost="{1}{W}", cmc=2, is_creature=True)
    nonmatching = _card("Nonmatching Zombie", "Creature — Zombie", cost="{1}{B}", cmc=2, is_creature=True)
    for card in (matching, nonmatching):
        obj = GameObject(card, owner_id="p2", zone=Zone.STACK)
        item = StackItem(kind="spell", controller_id="p2", obj=obj, description=card.name, effects=[])
        state.stack.append(item)

    spec = CounterSpellEffect(subtype_any=["spirit", "arcane"]).target_spec
    opts = targeting.legal_targets(state, "p1", spec)
    assert {o["name"] for o in opts} == {"Matching Spirit"}


# ---------------------------------------------------------------------------
# PARSER + ENGINE: "You may sacrifice/exile ~. If you do, <effect>."
# ---------------------------------------------------------------------------


def test_sacrifice_self_if_you_do_draw_collapses_to_a_plain_sequence():
    assert parse_effect_body("sacrifice ~. if you do, draw a card.", self_subject=True) == [
        EffectSpec("sacrifice_self", {}), EffectSpec("draw", {"count": 1}),
    ]


def test_dreamcatcher_shaped_card_sacrifices_and_draws():
    eng, state, p1, p2 = _engine()
    dreamcatcher = _bf(state, _card(
        "Test Dreamcatcher", is_creature=True,
        oracle_text=(
            "Whenever you cast a spell, you may sacrifice this creature. "
            "If you do, draw a card."
        ),
    ))
    p1.library.append(GameObject(_card("Filler"), owner_id="p1", zone=Zone.LIBRARY))
    spell = _hand(p1, _card("Test Spell", "Sorcery", cost="{1}", cmc=1))

    p1.mana_pool.add_many({"C": 1})
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    assert state.pending_choice is not None and state.pending_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice("do")
    eng.resolve_until_stable()

    assert dreamcatcher not in state.battlefield
    assert any(o.name == "Filler" for o in p1.hand)


def test_exile_self_if_you_do_delayed_return_parses():
    assert parse_effect_body(
        "exile ~. if you do, return it to the battlefield under its "
        "owner's control at the beginning of the next end step",
        self_subject=True,
    ) == [
        EffectSpec("exile", {"target_kind": None, "remember": True}),
        EffectSpec("create_delayed_trigger", {
            "step": "end", "scope": "any",
            "effects": [{"type": "return_linked_exile", "params": {"destination": "battlefield"}}],
        }),
    ]


def test_hikari_shaped_card_exiles_then_returns_at_next_end_step():
    eng, state, p1, p2 = _engine()
    hikari = _bf(state, _card(
        "Test Hikari", is_creature=True,
        oracle_text=(
            "Whenever you cast a spell, you may exile this creature. If "
            "you do, return it to the battlefield under its owner's "
            "control at the beginning of the next end step."
        ),
    ))
    spell = _hand(p1, _card("Test Spell", "Sorcery", cost="{1}", cmc=1))

    p1.mana_pool.add_many({"C": 1})
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    assert state.pending_choice is not None and state.pending_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice("do")
    eng.resolve_until_stable()

    assert hikari in p1.exile
    assert state.delayed_triggers

    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()

    assert hikari in state.battlefield
