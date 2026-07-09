"""Token creation, and the RULE 704.5d "ceases to exist" lifecycle.

The rules-critical behaviour (emphasised in the roadmap): a token that leaves
the battlefield *does* reach its destination zone briefly — so its
leaves-the-battlefield / dies triggers fire — and is then removed from the game
as a state-based action (RULE 704.5d), never to return (RULE 111.7-8). Exile
and destruction both funnel through that SBA.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.services.token_database import synthesize_token_card


def land():
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


def make_engine():
    eng = GameEngine.new_game([("p1", "Alice", [land()] * 10)], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def soldier():
    return synthesize_token_card("Soldier", power=1, toughness=1, colors=["W"], subtypes=["Soldier"])


def events_of(eng, event_type):
    seen = []
    eng.state.subscribe(lambda e: seen.append(e) if e.type == event_type else None)
    return seen


# -- Creation ---------------------------------------------------------------


def test_create_token_puts_it_on_battlefield_flagged():
    eng = make_engine()
    enters = events_of(eng, EventType.ENTERS_BATTLEFIELD)
    (tok,) = eng.rules.create_token("p1", soldier(), 1)
    assert tok in eng.state.battlefield
    assert tok.is_token is True
    assert tok.summoning_sick is True  # RULE 302.6
    assert tok.controller_id == "p1" and tok.owner_id == "p1"
    assert enters and enters[-1].get("is_token") is True


def test_create_multiple_tokens():
    eng = make_engine()
    toks = eng.rules.create_token("p1", soldier(), 3)
    assert len(toks) == 3
    assert sum(1 for o in eng.state.battlefield if o.is_token) == 3


def test_token_keyword_is_bound_and_seen_by_combat():
    from mtg_analyzer.game import combat

    eng = make_engine()
    drake = synthesize_token_card("Drake", power=2, toughness=2, colors=["U"], keywords=["flying"])
    (tok,) = eng.rules.create_token("p1", drake, 1)
    assert combat.has_flying(tok) is True


# -- Ceasing to exist (RULE 704.5d) -----------------------------------------


def test_dead_token_fires_dies_then_ceases_to_exist():
    eng = make_engine()
    dies = events_of(eng, EventType.DIES)
    (tok,) = eng.rules.create_token("p1", soldier(), 1)
    tok.damage_marked = 1  # toughness 1 → lethal
    eng.rules.check_state_based_actions()
    # It reached the graveyard long enough to fire DIES (the trigger window)…
    assert dies and any(e.get("object") == tok.name for e in dies)
    # …then RULE 704.5d removed it from the game entirely.
    p1 = eng.state.player_by_id("p1")
    assert tok not in p1.graveyard
    assert tok not in eng.state.battlefield
    assert not _anywhere(eng, tok)


def test_exiled_token_ceases_to_exist():
    eng = make_engine()
    (tok,) = eng.rules.create_token("p1", soldier(), 1)
    eng.rules.exile(tok)
    eng.rules.check_state_based_actions()
    p1 = eng.state.player_by_id("p1")
    assert tok not in p1.exile
    assert not _anywhere(eng, tok)


def test_destroyed_token_ceases_to_exist():
    eng = make_engine()
    (tok,) = eng.rules.create_token("p1", soldier(), 1)
    eng.rules.destroy(tok)
    eng.rules.check_state_based_actions()
    assert not _anywhere(eng, tok)


def test_token_cannot_return_from_graveyard():
    # Once it has ceased to exist it is gone — a graveyard-return effect finds
    # nothing (RULE 111.8: a token that has left the battlefield can't move on).
    eng = make_engine()
    (tok,) = eng.rules.create_token("p1", soldier(), 1)
    eng.rules.destroy(tok)
    eng.rules.check_state_based_actions()
    p1 = eng.state.player_by_id("p1")
    assert p1.graveyard == [] or tok not in p1.graveyard


def test_nontoken_still_goes_to_graveyard():
    # The SBA must only remove *tokens*; a real creature stays in the graveyard.
    eng = make_engine()
    bear = GameObject(Card(id="Bear", name="Bear", type_line="Creature — Bear",
                           is_creature=True, power=2, toughness=2), owner_id="p1",
                      zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    bear.damage_marked = 2
    eng.rules.check_state_based_actions()
    p1 = eng.state.player_by_id("p1")
    assert bear in p1.graveyard  # real cards persist in the graveyard


def test_is_token_survives_clone_for_rewind():
    import copy

    eng = make_engine()
    (tok,) = eng.rules.create_token("p1", soldier(), 1)
    restored = copy.deepcopy(tok)  # how GameState.clone snapshots the board
    assert restored.is_token is True


# -- End-to-end through the oracle parser -----------------------------------


def test_parsed_token_spell_creates_tokens_end_to_end():
    spell = Card(id="RTA", name="Raise the Alarm", type_line="Instant", is_instant=True,
                 oracle_text="Create two 1/1 white Soldier creature tokens.")
    eng = make_engine()
    p1 = eng.state.active_player
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    soldiers = [o for o in eng.state.battlefield if o.is_token and o.name == "Soldier"]
    assert len(soldiers) == 2
    assert all(o.power == 1 and o.toughness == 1 for o in soldiers)


def _anywhere(eng, obj):
    """Whether ``obj`` is still in any zone of the game."""
    if obj in eng.state.battlefield:
        return True
    for player in eng.state.players:
        for zone_cards in player.zones.values():
            if obj in zone_cards:
                return True
    return False


# -- Enumerating a deck's producible tokens (loading-screen art preload) ----


def test_producible_tokens_synthesized_from_oracle_and_deduped():
    # An inline creature token parsed off oracle text — synthesized (no art),
    # and de-duplicated across a deck's repeated copies.
    from mtg_analyzer.services.deck_tokens import producible_tokens

    spell = Card(id="RTA", name="Raise the Alarm", type_line="Instant", is_instant=True,
                 oracle_text="Create two 1/1 white Soldier creature tokens.")
    tokens = producible_tokens([spell, spell])
    assert [t.name for t in tokens] == ["Soldier"]
    assert tokens[0].power == 1 and tokens[0].toughness == 1
    assert not tokens[0].image_uri_small  # synthesized tokens carry no art


def test_producible_tokens_named_resolves_curated_art():
    # A bare *named* token resolves to the curated catalogue definition, which
    # carries real Scryfall art — so it's exactly what preloading needs.
    from mtg_analyzer.game import ability_catalogue
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec
    from mtg_analyzer.services.deck_tokens import producible_tokens

    ability_catalogue.register(
        "Test Treasure Maker",
        lambda: [AbilitySpec(
            ability_kind="spell_effect",
            effects=[EffectSpec("create_token", {"token_name": "Treasure"})],
        )],
    )
    try:
        card = Card(id="TTM", name="Test Treasure Maker", type_line="Sorcery",
                    is_sorcery=True, oracle_text="Create a Treasure token.")
        (token,) = producible_tokens([card])
        assert token.name == "Treasure"
        assert token.image_uri_small  # curated art present
    finally:
        ability_catalogue._REGISTRY.pop("test treasure maker", None)
