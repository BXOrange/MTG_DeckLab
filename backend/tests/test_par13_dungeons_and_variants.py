"""PAR-13 (2026-08-04): dungeon room, plane and scheme effect bodies.

The RULE 309 dungeon engine and all four room graphs were already built;
what was missing was ordinary effect-body grammar for 9 of the 30 cached
rooms (`game/dungeons.py`'s `room_effect_specs`, fail-closed exactly like a
card's own oracle text). This batch closes 8 of the 9, via six pieces, none
of which needed a new *targeting* primitive:

* `PumpEffect.target_count`/`grant_until`'s new P/T-delta static route
  (`_pump_until`) and its "can't attack/block until `<duration>`" sibling
  (`_cant_attack_or_block_until`, riding the same synthetic `grant_keyword`
  flag the permanent-static family already uses) — Fungi Cavern/Twisted
  Caverns, plus real cards (A-Binding Geist, Hag of Inner Weakness, Mouth
  of the Storm via the widened `creatures your opponents control`/
  `creatures you don't control` group phrasing).
* A mandatory compound cost effect (`discard` + three `choose_objects`
  sacrifices) for Oubliette's "Discard a card and sacrifice a creature, an
  artifact, and a land." — no new primitive, just three existing ones
  combined by a whole-clause handler (avoiding the generic `" and "`
  connector split, which would also split the sacrifice's own internal
  list).
* A legendary named token (`CreateTokenEffect.legendary`/
  `synthesize_token_card`'s new param, `Card.is_legendary` set directly)
  for Cradle of the Death God's "Create The Atropal, a legendary 4/4 black
  God Horror creature token with deathtouch."
* `ImpulsiveDrawEffect`'s first oracle-text route (it previously existed
  hand-authored-only, Light Up the Stage) for Runestone Caverns' "Exile the
  top two cards of your library. You may play them." — also closes
  Bonehoard Dracosaur/Painter's Studio's own duration variants.
* A new one-shot `DrawRevealCastOneFreeEffect` + `RulesEngine.
  _request_choose_objects`'s new `"cast_free"` action (a hand-zone pick,
  unlike every existing action) for Mad Wizard's Lair's "Draw three cards
  and reveal them. You may cast one of them without paying its mana cost."
* A new mass-interactive primitive, `RulesEngine.
  _request_each_player_pay_or` (RULE 101.4 APNAP, chained off the existing
  single-player `_request_pay_cost_then`) for Veils of Fear/Sandfall Cell's
  "Each player loses N life unless they `<pay cost>`." — Sandfall Cell's
  own "sacrifice a creature, artifact, or land of their choice" cost also
  needed a new compound `ActivationCost.sacrifice` value
  (`creature_artifact_or_land`), since the plain single-word sacrifice
  grammar can't express an OR of three types.

Throne of the Dead Three ("Reveal the top ten cards of your library. Put a
creature card from among them onto the battlefield with three +1/+1
counters on it. It gains hexproof until your next turn. Then shuffle.")
stays UNMODELED on purpose: a "reveal top N, choose one matching a filter,
place it with counters, shuffle the rest back" primitive would be
genuinely new engine work for a shape no other cached card needs (0 real
non-dungeon siblings) — a documented residual gap, not a half-implementation.

Planechase/Archenemy plane/scheme card *text* (the ticket's other named
area) remains overwhelmingly unmodeled (13/309 measured this batch) but was
never this ticket's own scope to close — CLAUDE.md already frames it as
"PAR-12 work with a known card list", re-confirmed rather than newly
regressed.

Reference: mtg_analyzer/game/dungeons.py, mtg_analyzer/game/effects/core.py,
mtg_analyzer/game/rules/misc_mixin.py (`_request_each_player_pay_or`),
mtg_analyzer/game/costs.py, mtg_analyzer/services/token_database.py,
mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.dungeons import all_dungeons, room_effect_specs
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import HANDLERS, match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _engine():
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(4)]
    return GameEngine.new_game([("p1", "Alice", cards), ("p2", "Bob", list(cards))],
                                starting_life=20, starting_hand=0)


def _creature(name, power=2, toughness=2, owner="p1"):
    card = Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=power, toughness=toughness)
    return GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)


# ---------------------------------------------------------------------------
# Dungeon rooms: 29/30 now bind (was 21/30) — the actual PAR-13 deliverable
# ---------------------------------------------------------------------------


def test_dungeon_room_coverage_is_29_of_30():
    total = 0
    modeled = 0
    unmodeled_names = []
    for dungeon in all_dungeons():
        for room in dungeon.rooms:
            total += 1
            specs = parse_effect_body(normalize(room.effect_text))
            if specs:
                modeled += 1
            else:
                unmodeled_names.append(room.name)
    assert total == 30
    assert modeled == 29
    assert unmodeled_names == ["Throne of the Dead Three"]


def test_veils_of_fear_and_sandfall_cell_now_bind():
    tomb = next(d for d in all_dungeons() if d.name == "Tomb of Annihilation")
    veils = next(r for r in tomb.rooms if r.name == "Veils of Fear")
    sandfall = next(r for r in tomb.rooms if r.name == "Sandfall Cell")
    assert room_effect_specs(veils)
    assert room_effect_specs(sandfall)


def test_oubliette_room_produces_four_effects():
    tomb = next(d for d in all_dungeons() if d.name == "Tomb of Annihilation")
    room = next(r for r in tomb.rooms if r.name == "Oubliette")
    specs = room_effect_specs(room)
    assert [s["type"] for s in specs] == [
        "discard", "choose_objects", "choose_objects", "choose_objects",
    ]


def test_cradle_of_the_death_god_room_is_a_legendary_token():
    tomb = next(d for d in all_dungeons() if d.name == "Tomb of Annihilation")
    room = next(r for r in tomb.rooms if r.name == "Cradle of the Death God")
    (spec,) = room_effect_specs(room)
    assert spec["type"] == "create_token"
    assert spec["params"]["legendary"] is True
    assert spec["params"]["token_name"] == "The Atropal"


# ---------------------------------------------------------------------------
# PARSER: grant_until's new P/T + can't-attack/block routes
# ---------------------------------------------------------------------------


def test_pump_until_your_next_turn_is_recognized():
    (spec,) = match_clause("target creature gets -4/-0 until your next turn")
    assert spec.type == "grant_until"
    assert spec.params == {
        "static": {"type": "anthem", "params": {"power": -4, "toughness": 0}},
        "duration": "your_next_turn", "target_kind": "creature",
    }


def test_pump_until_group_phrasing_your_opponents_control():
    # PAR-120: "creatures your opponents control" now reaches the shared
    # grammar's structured selector; "you don't control" below stays the
    # retired named string (the grammar has no negation reading).
    (spec,) = match_clause(
        "creatures your opponents control get -3/-0 until your next turn"
    )
    assert spec.params["target_kind"] is None
    assert spec.params["static"]["params"]["affects"] == {
        "zone": "battlefield", "of": "opponents", "filter": {"card_type": "creature"},
    }


def test_pump_until_group_phrasing_you_dont_control():
    (spec,) = match_clause("creatures you don't control get -2/-0 until your next turn")
    assert spec.params["static"]["params"]["affects"] == "creatures_opponents_control"


def test_cant_attack_until_your_next_turn_is_recognized():
    (spec,) = match_clause("target creature can't attack until your next turn")
    assert spec.type == "grant_until"
    assert spec.params == {
        "static": {"type": "grant_keyword", "params": {"keywords": ["cant_attack"]}},
        "duration": "your_next_turn", "target_kind": "creature",
    }


def test_cant_block_until_end_of_combat_is_recognized():
    (spec,) = match_clause("target creature can't block until end of combat")
    assert spec.params["static"]["params"]["keywords"] == ["cant_block"]


def test_a_binding_geist_is_fully_modeled():
    card = Card(
        id="A-Binding Geist", name="A-Binding Geist", type_line="Creature — Spirit",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever this creature attacks, target creature an opponent "
                    "controls gets -2/-0 until your next turn.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_mouth_of_the_storm_is_fully_modeled():
    card = Card(
        id="Mouth of the Storm", name="Mouth of the Storm", type_line="Creature — Dragon",
        is_creature=True, power=3, toughness=3,
        oracle_text="Flying\nWhen this creature enters, creatures your opponents "
                    "control get -3/-0 until your next turn.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# ---------------------------------------------------------------------------
# ENGINE: grant_until P/T + can't-attack actually land and outlast cleanup
# ---------------------------------------------------------------------------


def test_pump_until_next_turn_end_to_end_survives_end_of_turn_cleanup():
    card = Card(
        id="Test Fungi Cavern", name="Test Fungi Cavern", type_line="Instant",
        is_instant=True, mana_cost_string="{R}", converted_mana_cost=1,
        oracle_text="Target creature gets -4/-0 until your next turn.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    bear = _creature("Weakened Bear", power=4, toughness=4, owner="p2")
    eng.state.add_to_battlefield(bear)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1})

    eng.cast_spell(p1, obj, targets=[bear])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert bear.power == 0

    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert bear.power == 0  # RULE 514.2's ordinary EOT sweep doesn't touch this


def test_cant_attack_until_next_turn_end_to_end():
    card = Card(
        id="Test Twisted Caverns", name="Test Twisted Caverns", type_line="Instant",
        is_instant=True, mana_cost_string="{U}", converted_mana_cost=1,
        oracle_text="Target creature can't attack until your next turn.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    bear = _creature("Grounded Bear", owner="p2")
    bear.summoning_sick = False
    eng.state.add_to_battlefield(bear)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 1})

    eng.cast_spell(p1, obj, targets=[bear])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert "cant_attack" in bear.granted_keywords


# ---------------------------------------------------------------------------
# ENGINE: Oubliette-shaped compound discard+sacrifice
# ---------------------------------------------------------------------------


def test_discard_and_sacrifice_triple_end_to_end():
    specs = match_clause(
        "discard a card and sacrifice a creature, an artifact, and a land"
    )
    assert [s.type for s in specs] == ["discard", "choose_objects", "choose_objects", "choose_objects"]

    eng = _engine()
    p1 = eng.state.players[0]
    card = Card(
        id="Test Oubliette Effect", name="Test Oubliette Effect", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{1}{B}", converted_mana_cost=2,
        oracle_text="Discard a card and sacrifice a creature, an artifact, and a land.",
    )
    result = parse_oracle(card)
    assert result.modeled
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    hand_filler = GameObject(Card(id="Filler", name="Filler", type_line="Instant"),
                              owner_id="p1", zone=Zone.HAND)
    p1.hand.extend([obj, hand_filler])

    creature = _creature("Punished Bear", owner="p1")
    artifact = GameObject(Card(id="Trinket", name="Trinket", type_line="Artifact"),
                           owner_id="p1", zone=Zone.BATTLEFIELD)
    land = GameObject(Card(id="Plain Land", name="Plain Land", type_line="Land",
                            is_land=True), owner_id="p1", zone=Zone.BATTLEFIELD)
    for perm in (creature, artifact, land):
        eng.state.add_to_battlefield(perm)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "C": 1})

    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    assert hand_filler not in p1.hand
    assert creature not in eng.state.battlefield
    assert artifact not in eng.state.battlefield
    assert land not in eng.state.battlefield


# ---------------------------------------------------------------------------
# PARSER + ENGINE: named legendary token
# ---------------------------------------------------------------------------


def test_create_named_legendary_token_is_recognized():
    (spec,) = match_clause(
        "create the atropal, a legendary 4/4 black god horror creature token with deathtouch"
    )
    assert spec.type == "create_token"
    assert spec.params["token_name"] == "The Atropal"
    assert spec.params["legendary"] is True
    assert spec.params["power"] == 4 and spec.params["toughness"] == 4
    assert spec.params["colors"] == ["B"]
    assert spec.params["subtypes"] == ["God", "Horror"]
    assert spec.params["keywords"] == ["deathtouch"]


def test_create_named_legendary_token_end_to_end():
    card = Card(
        id="Test Cradle", name="Test Cradle", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{3}{B}", converted_mana_cost=4,
        oracle_text="Create The Atropal, a legendary 4/4 black God Horror creature "
                    "token with deathtouch.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "C": 3})

    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    tokens = [o for o in eng.state.battlefield if o.name == "The Atropal"]
    assert len(tokens) == 1
    token = tokens[0]
    assert token.card.is_legendary is True
    assert token.card.type_line.startswith("Token")
    assert token.power == 4 and token.toughness == 4
    assert "deathtouch" in token.granted_keywords or "deathtouch" in (token.card.keywords or [])


# ---------------------------------------------------------------------------
# PARSER + ENGINE: impulsive draw's first oracle-text route
# ---------------------------------------------------------------------------


def test_exile_top_play_bare_form_is_recognized():
    (spec,) = match_clause("exile the top 2 cards of your library. you may play them")
    assert spec.type == "impulsive_draw"
    assert spec.params == {"count": 2, "same_turn_only": False}


def test_exile_top_play_this_turn_variant():
    (spec,) = match_clause(
        "exile the top 2 cards of your library. you may play them this turn"
    )
    assert spec.params["same_turn_only"] is True


def test_bonehoard_dracosaur_first_sentence_recognized():
    (spec,) = match_clause(
        "exile the top 2 cards of your library. you may play them this turn"
    )
    assert spec.type == "impulsive_draw"


def test_runestone_caverns_end_to_end_exiles_with_play_permission():
    card = Card(
        id="Test Runestone Caverns", name="Test Runestone Caverns", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{1}{U}", converted_mana_cost=2,
        oracle_text="Exile the top 2 cards of your library. You may play them.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    library_before = len(p1.library)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 1, "C": 1})

    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    assert len(p1.library) == library_before - 2
    exiled = [o for o in p1.exile if o.instance_id in eng.state.temp_play_permissions]
    assert len(exiled) == 2


# ---------------------------------------------------------------------------
# PARSER + ENGINE: draw/reveal/cast-one-free
# ---------------------------------------------------------------------------


def test_draw_reveal_cast_free_is_recognized():
    (spec,) = match_clause(
        "draw 3 cards and reveal them. you may cast 1 of them without paying its mana cost"
    )
    assert spec.type == "draw_reveal_cast_one_free"
    assert spec.params == {"count": 3}


def test_mad_wizards_lair_is_fully_modeled():
    card = Card(
        id="Mad Wizard's Lair Test", name="Mad Wizard's Lair Test", type_line="Sorcery",
        is_sorcery=True,
        oracle_text="Draw three cards and reveal them. You may cast one of them "
                    "without paying its mana cost.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_draw_reveal_cast_one_free_end_to_end_offers_a_choice():
    card = Card(
        id="Test Mad Wizard", name="Test Mad Wizard", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{2}{U}", converted_mana_cost=3,
        oracle_text="Draw three cards and reveal them. You may cast one of them "
                    "without paying its mana cost.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    # A castable, free-to-resolve library so whichever card is drawn can
    # actually go on the stack and resolve when chosen.
    lib_cards = []
    for i in range(5):
        lib_obj = GameObject(
            Card(id=f"Lib{i}", name=f"Lib{i}", type_line="Sorcery", is_sorcery=True,
                 oracle_text="You gain 1 life."),
            owner_id="p1", zone=Zone.LIBRARY,
        )
        bind_from_catalogue(lib_obj)
        lib_cards.append(lib_obj)
    p1.library.extend(lib_cards)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 1, "C": 2})
    hand_before = len(p1.hand)

    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    assert len(p1.hand) == hand_before - 1 + 3  # the caster's own card left, 3 drawn
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "choose_objects"
    assert choice["action"] == "cast_free"
    life_before = p1.life
    picked_id = int(choice["options"][0]["instance_id"])
    eng.resolve_pending_choice(str(picked_id))
    eng.resolve_until_stable()
    assert p1.life == life_before + 1  # the freely cast "gain 1 life" resolved


# ---------------------------------------------------------------------------
# PARSER + ENGINE: the each-player mass "unless" primitive
# ---------------------------------------------------------------------------


def test_each_player_lose_life_unless_discard_is_recognized():
    (spec,) = match_clause("each player loses 2 life unless they discard a card")
    assert spec.type == "each_player_pay_or"
    assert spec.params == {
        "cost": "discard a card",
        "effects": [{"type": "lose_life", "params": {"amount": 2, "target_kind": "player"}}],
    }


def test_each_player_lose_life_unless_sacrifice_choice_is_recognized():
    (spec,) = match_clause(
        "each player loses 2 life unless they sacrifice a creature, artifact, or "
        "land of their choice"
    )
    assert spec.params["cost"] == "sacrifice a creature, artifact, or land of their choice"


def test_veils_of_fear_is_fully_modeled_as_a_standalone_card():
    card = Card(
        id="Veils of Fear Test", name="Veils of Fear Test", type_line="Sorcery",
        is_sorcery=True,
        oracle_text="Each player loses 2 life unless they discard a card.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_sandfall_cell_is_fully_modeled_as_a_standalone_card():
    card = Card(
        id="Sandfall Cell Test", name="Sandfall Cell Test", type_line="Sorcery",
        is_sorcery=True,
        oracle_text="Each player loses 2 life unless they sacrifice a creature, "
                    "artifact, or land of their choice.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_each_player_pay_or_end_to_end_sequences_both_players():
    card = Card(
        id="Test Veils of Fear", name="Test Veils of Fear", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{1}{B}", converted_mana_cost=2,
        oracle_text="Each player loses 2 life unless they discard a card.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1, p2 = eng.state.players[0], eng.state.players[1]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    # p1 has a spare card to discard; p2 has none — p2 must lose life outright.
    filler = GameObject(Card(id="Filler2", name="Filler2", type_line="Instant"),
                         owner_id="p1", zone=Zone.HAND)
    p1.hand.append(filler)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "C": 1})

    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    # p1 (active, asked first) can pay — a real choice is open for them.
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    assert choice["player_id"] == "p1"
    p1_life_before, p2_life_before = p1.life, p2.life
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()

    # p1 paid (discarded), so no life lost; p2 had nothing to discard, so
    # the sweep resolved p2's leg synchronously straight to the life loss.
    assert filler not in p1.hand
    assert p1.life == p1_life_before
    assert p2.life == p2_life_before - 2
    assert eng.state.pending_choice is None


def test_each_player_pay_or_declining_loses_the_life():
    card = Card(
        id="Test Veils of Fear 2", name="Test Veils of Fear 2", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{1}{B}", converted_mana_cost=2,
        oracle_text="Each player loses 2 life unless they discard a card.",
    )
    eng = _engine()
    p1, p2 = eng.state.players[0], eng.state.players[1]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    filler = GameObject(Card(id="Filler3", name="Filler3", type_line="Instant"),
                         owner_id="p1", zone=Zone.HAND)
    p1.hand.append(filler)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "C": 1})

    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    p1_life_before = p1.life
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()

    assert filler in p1.hand  # never discarded
    assert p1.life == p1_life_before - 2
    assert p2.life == 20 - 2


# ---------------------------------------------------------------------------
# ENGINE: the compound "creature, artifact, or land" sacrifice cost
# ---------------------------------------------------------------------------


def test_sandfall_cell_sacrifice_cost_end_to_end():
    from mtg_analyzer.game.costs import parse_activation_cost

    cost = parse_activation_cost("Sacrifice a creature, artifact, or land of their choice")
    assert cost.sacrifice == "creature_artifact_or_land"

    card = Card(
        id="Test Sandfall Cell", name="Test Sandfall Cell", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{1}{B}", converted_mana_cost=2,
        oracle_text="Each player loses 2 life unless they sacrifice a creature, "
                    "artifact, or land of their choice.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1, p2 = eng.state.players[0], eng.state.players[1]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    land = GameObject(Card(id="Sac Land", name="Sac Land", type_line="Land", is_land=True),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(land)
    # p2 has no creature/artifact/land at all — can't pay, loses life outright.

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "C": 1})

    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    assert choice["player_id"] == "p1"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()

    assert land not in eng.state.battlefield
    assert p1.life == 20  # paid, no life lost
    assert p2.life == 18  # couldn't pay — no permanents at all
