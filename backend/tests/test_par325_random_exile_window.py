"""PAR-325 -- "exile a card at random from your graveyard, you may play/cast it this turn [exile it instead]".

Parsed from real oracle wording, then executed on a real GameEngine: the pick is made through the engine's seeded RNG
among only the cards that fit the filter, the permission exists for this turn only, and the RULE 614.1 "exile it
instead" rider fires for a spell cast through the window (and is dropped again when the window lapses uncast).
"""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature

PLAY = "exile a card at random from your graveyard. you may play that card this turn."
CAST_RIDER = ("exile an instant or sorcery card at random from your graveyard. you may cast it this turn. "
              "if a spell cast this way would be put into your graveyard, exile it instead.")
STORM = ("exile an instant or sorcery card with mana value 3 or less from your graveyard at random. you may cast it "
         "without paying its mana cost. if that spell would be put into a graveyard, exile it instead.")


def _spell(name, cost="{1}", mv=1, sorcery=False):
    return Card(id=name, name=name, type_line="Sorcery" if sorcery else "Instant", is_instant=not sorcery,
                is_sorcery=sorcery, mana_cost_string=cost, converted_mana_cost=mv, oracle_text="Draw a card.")


def _land(name="Plains"):
    return Card(id=name, name=name, type_line="Basic Land — Plains", is_land=True)


def _seeded(seed=0, counter=0):
    eng = _engine()
    eng.state.rng_seed, eng.state.rng_counter = seed, counter  # RULE 706: the engine's own reproducible RNG state
    return eng


def _grave(eng, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
    eng.state.player_by_id(owner).graveyard.append(obj)
    return obj


def _run(eng, text, source=None):
    source = source or _bf(eng, _creature("Grantor"))
    specs = parse_effect_body(text)
    assert specs, text
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context, [])
    return source


def _exiled(eng):
    return list(eng.state.player_by_id("p1").exile)


# --- parse -----------------------------------------------------------------------------------------------------

def test_parses_the_exile_and_its_window():
    types = [s.type for s in parse_effect_body(PLAY)]
    assert types == ["exile_random_graveyard_card", "cast_window_exiled_pool"]
    specs = parse_effect_body(CAST_RIDER)
    assert specs[0].params == {"card_filter": {"card_type_any": ["instant", "sorcery"]}}
    assert specs[1].params == {"only_spells": True, "same_turn_only": True, "exile_instead": True}
    specs = parse_effect_body(STORM)
    assert specs[0].params["card_filter"] == {"card_type_any": ["instant", "sorcery"], "max_mana_value": 3}
    assert specs[1].params == {"only_spells": True, "resolution_local": True, "free": True, "exile_instead": True}


@pytest.mark.parametrize("text", [
    # several cards at random feed a copy, not this window
    "exile three cards at random from your graveyard. you may cast them this turn.",
    # another zone / player
    "exile a card at random from your hand. you may play that card this turn.",
    "exile a card at random from an opponent's graveyard. you may play that card this turn.",
    # a played land is never "put into a graveyard"
    "exile a card at random from your graveyard. you may play that card this turn. "
    "if a spell cast this way would be put into your graveyard, exile it instead.",
    # the rider alone names no spell
    "exile a card at random from your graveyard. if a spell cast this way would be put into your graveyard, "
    "exile it instead.",
])
def test_neighbouring_shapes_stay_unclaimed(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize("name", ["Tersa Lightshatter", "Storm of Memories"])
def test_real_cards_are_modeled(name):
    from test_par157_back_selections import _cached
    assert parse_oracle(_cached(name)).modeled is True


# --- execution -------------------------------------------------------------------------------------------------

def test_pick_is_seeded_and_reproducible():
    picks = []
    for _ in range(2):
        eng = _seeded(7)
        cards = [_grave(eng, _spell(f"S{i}")) for i in range(8)]
        _run(eng, PLAY)
        (picked,) = _exiled(eng)
        picks.append(cards.index(picked))
    assert picks[0] == picks[1]


def test_every_card_can_be_the_pick_across_seeds_and_only_one_is_exiled():
    seen = set()
    for seed in range(40):
        eng = _seeded(counter=seed)
        cards = [_grave(eng, _spell(f"S{i}")) for i in range(3)]
        _run(eng, PLAY)
        assert len(_exiled(eng)) == 1
        assert len(eng.state.player_by_id("p1").graveyard) == 2
        seen.add(cards.index(_exiled(eng)[0]))
    assert seen == {0, 1, 2}


def test_filter_restricts_the_random_pool():
    for seed in range(15):
        eng = _seeded(counter=seed)
        _grave(eng, _land())
        _grave(eng, _creature("Bear"))
        wanted = _grave(eng, _spell("Wanted"))
        _run(eng, CAST_RIDER)
        assert _exiled(eng) == [wanted]


def test_empty_pool_exiles_nothing_and_grants_nothing():
    eng = _engine()
    land = _grave(eng, _land())
    _run(eng, CAST_RIDER)
    assert land.zone == Zone.GRAVEYARD and not _exiled(eng)
    assert eng.state.pending_choice is None and not eng.state.temp_play_permissions


def test_only_the_controllers_graveyard_is_read():
    eng = _engine()
    theirs = _grave(eng, _spell("Theirs"), owner="p2")
    _run(eng, PLAY)
    assert theirs.zone == Zone.GRAVEYARD


def test_play_window_is_this_turn_only_and_covers_lands():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    land = _grave(eng, _land())
    _run(eng, PLAY)
    assert land.zone == Zone.EXILE
    assert eng.can_play_land(p1, land)
    eng._step_cleanup()
    assert not eng.can_play_land(p1, land)
    assert land.zone == Zone.EXILE  # it simply stays exiled


def test_cast_window_with_rider_exiles_the_spell_afterwards():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _grave(eng, _spell("Insight", cost="{1}"))
    _run(eng, CAST_RIDER)
    p1.mana_pool.add("C", 1)
    assert spell.zone == Zone.EXILE and eng.can_cast(p1, spell)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE  # RULE 614.1: exiled instead of reaching the graveyard
    assert spell not in p1.graveyard


def test_cast_window_expires_and_the_rider_does_not_outlive_it():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _grave(eng, _spell("Insight"))
    _run(eng, CAST_RIDER)
    assert spell.exile_after_free_cast
    p1.mana_pool.add("C", 1)
    assert eng.can_cast(p1, spell)
    eng._step_cleanup()
    p1.mana_pool.add("C", 1)
    assert not eng.can_cast(p1, spell)
    assert not spell.exile_after_free_cast


def test_storm_of_memories_free_cast_respects_mana_value_and_exiles_instead():
    for seed in range(10):
        eng = _seeded(counter=seed)
        p1 = eng.state.player_by_id("p1")
        _grave(eng, _spell("Dear", "{4}", 4))
        cheap = _grave(eng, _spell("Cheap", "{2}", 2))
        _run(eng, STORM)
        assert eng.state.pending_choice["kind"] == "play_during_resolution"
        assert cheap.zone == Zone.EXILE and len(_exiled(eng)) == 1
        eng.play_resolution_card(p1, cheap)
        eng.resolve_until_stable()
        assert p1.mana_pool.total() == 0  # RULE 118.9: no mana cost paid
        assert cheap.zone == Zone.EXILE and cheap not in p1.graveyard


def test_storm_of_memories_declined_cast_leaves_a_plain_exiled_card():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    cheap = _grave(eng, _spell("Cheap", "{2}", 2))
    _run(eng, STORM)
    eng.resolve_pending_choice("decline")
    assert cheap.zone == Zone.EXILE and not eng.can_cast(p1, cheap)
    assert not cheap.exile_after_free_cast


# --- Radiant Scrollwielder (hand-authored static + the parser's PAR-325 trigger) -----------------------------------

def _wielder(eng):
    from test_par157_back_selections import _cached
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    wielder = GameObject(_cached("Radiant Scrollwielder"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(wielder)
    eng.state.add_to_battlefield(wielder)
    return wielder


def _hand_card(eng, card, owner):
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    eng.state.player_by_id(owner).hand.append(obj)
    bind_from_catalogue(obj)
    return obj


def test_scrollwielder_lifelink_goes_to_your_instants_and_sorceries_only():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    _wielder(eng)
    creature = _hand_card(eng, _creature("Bear"), "p1")
    p1.mana_pool.add("C", 5)
    eng.cast_spell(p1, creature)
    eng.recompute_continuous_effects()
    assert "lifelink" not in creature.granted_keywords  # a creature spell
    eng.resolve_until_stable()
    mine = _hand_card(eng, _spell("Mine"), "p1")
    theirs = _hand_card(eng, _spell("Theirs"), "p2")
    p1.mana_pool.add("C", 5)
    p2.mana_pool.add("C", 5)
    eng.cast_spell(p1, mine)
    eng.cast_spell(p2, theirs)
    eng.recompute_continuous_effects()
    assert "lifelink" in mine.granted_keywords
    assert "lifelink" not in theirs.granted_keywords  # not controlled by the Scrollwielder's controller


def test_scrollwielder_upkeep_trigger_exiles_at_random_and_opens_a_cast_window():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _wielder(eng)
    wanted = _grave(eng, _spell("Wanted"))
    _grave(eng, _creature("Bear"))
    eng.state.current_step = "upkeep"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    eng.resolve_until_stable()
    assert wanted.zone == Zone.EXILE and len(_exiled(eng)) == 1  # the creature card was never eligible
    p1.mana_pool.add("C", 1)
    assert eng.can_cast(p1, wanted)
    eng.cast_spell(p1, wanted)
    eng.resolve_until_stable()
    assert wanted.zone == Zone.EXILE  # "exile it instead" of the graveyard


def test_scrollwielder_lifelink_gains_life_from_a_spells_damage():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _wielder(eng)
    bolt = Card(id="Bolt", name="Bolt", type_line="Instant", is_instant=True, mana_cost_string="{R}",
                converted_mana_cost=1, oracle_text="Bolt deals 3 damage to target player.")
    obj = _hand_card(eng, bolt, "p1")
    p1.mana_pool.add("R", 1)
    life = p1.life
    eng.cast_spell(p1, obj, targets=[eng.state.player_by_id("p2")])
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 17
    assert p1.life == life + 3


def test_spell_damage_keyword_static_parses_and_stays_narrow():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
    got = static_effect_specs("instant and sorcery spells you control have deathtouch")
    assert got and got[0].params == {"keywords": ["deathtouch"],
                                     "spell_filter": {"card_type_any": ["instant", "sorcery"]}}
    assert static_effect_specs("instant and sorcery spells you control have flying") is None
    assert static_effect_specs("creature spells you control have lifelink") is None
    assert static_effect_specs("red instant and sorcery spells you control have lifelink") is None


# --- the rider also finishes the targeted sibling (Dire Fleet Daredevil, Nita, Forum Conciliator) ------------------

DAREDEVIL = ("exile target instant or sorcery card from an opponent's graveyard. you may cast it this turn, and mana "
             "of any type can be spent to cast that spell. if that spell would be put into a graveyard, exile it instead.")


def test_targeted_exile_cast_window_with_rider_executes():
    specs = parse_effect_body(DAREDEVIL)
    assert [s.type for s in specs] == ["exile", "cast_window_exiled_pool"]
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    theirs = _grave(eng, _spell("Theirs"), owner="p2")
    source = _bf(eng, _creature("Daredevil"))
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context, [theirs])
    assert theirs.zone == Zone.EXILE and theirs.exile_after_free_cast
    p1.mana_pool.add("R", 1)  # any type of mana pays the {1}
    assert eng.can_cast(p1, theirs)
    eng.cast_spell(p1, theirs)
    eng.resolve_until_stable()
    assert theirs.zone == Zone.EXILE
    assert theirs not in eng.state.player_by_id("p2").graveyard


def test_the_rider_is_refused_for_a_pool_it_cannot_name():
    # a plural pool or a played land has no single "spell" to carry the replacement
    assert parse_effect_body("exile the top two cards of your library. you may cast them this turn. "
                             "if that spell would be put into a graveyard, exile it instead.") is None


# --- exile at random, copy it, cast the copy (Wondrous Crucible, Capricious Hellraiser) ---------------------------

CRUCIBLE = ("mill 2 cards, then exile a nonland card at random from your graveyard. copy it. "
            "you may cast the copy without paying its mana cost.")
HELLRAISER = ("exile 3 cards at random from your graveyard. choose a noncreature, nonland card from among them and "
              "copy it. you may cast the copy without paying its mana cost.")


def _artifact(name="Trinket", mv=2):
    return Card(id=name, name=name, type_line="Artifact", mana_cost_string="{2}",
                converted_mana_cost=mv, oracle_text="")


def test_copy_shapes_parse():
    assert [s.type for s in parse_effect_body(CRUCIBLE)] == [
        "mill", "exile_random_graveyard_card", "copy_imprinted_card"]
    specs = parse_effect_body(HELLRAISER)
    assert specs[0].params == {"count": 3}
    assert specs[1].params == {"from_latest_exiled": True, "card_filter": {"without_card_type": ["creature", "land"]}}


@pytest.mark.parametrize("text", [
    # several exiled cards and a bare "it": which card?
    "exile 3 cards at random from your graveyard. copy it. you may cast the copy without paying its mana cost.",
    # an unreadable pick fails closed
    "exile 3 cards at random from your graveyard. choose a shiny card from among them and copy it. "
    "you may cast the copy without paying its mana cost.",
    "exile a card at random from your hand. copy it. you may cast the copy without paying its mana cost.",
])
def test_copy_neighbours_stay_unclaimed(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize("name", ["Wondrous Crucible", "Capricious Hellraiser"])
def test_copy_real_cards_are_modeled(name):
    from test_par157_back_selections import _cached
    assert parse_oracle(_cached(name)).modeled is True


def test_crucible_copies_the_random_nonland_card_and_the_original_stays_exiled():
    eng = _seeded(3)
    p1 = eng.state.player_by_id("p1")
    _grave(eng, _land())
    spell = _grave(eng, _spell("Insight", cost="{3}", mv=3))
    _run(eng, CRUCIBLE)
    # the two milled cards are the (land) fillers; the only nonland card is the instant
    assert spell.zone == Zone.EXILE
    choice = eng.state.pending_choice
    assert choice["kind"] == "play_during_resolution" and choice["free"]
    (copy_id,) = choice["instance_ids"]
    copy = eng.state.find_object(copy_id)
    assert copy.is_copy and copy.zone == Zone.EXILE and copy is not spell and copy.name == "Insight"
    eng.play_resolution_card(p1, copy)
    assert p1.mana_pool.total() == 0
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE  # the exiled card itself is never cast
    assert copy not in p1.exile and copy not in p1.graveyard  # RULE 707.10a: the copy ceased to exist


def test_crucible_permanent_copy_becomes_a_token():
    eng = _seeded(1)
    p1 = eng.state.player_by_id("p1")
    art = _grave(eng, _artifact())
    _run(eng, CRUCIBLE)
    (copy_id,) = eng.state.pending_choice["instance_ids"]
    copy = eng.state.find_object(copy_id)
    eng.play_resolution_card(p1, copy)
    eng.resolve_until_stable()
    assert art.zone == Zone.EXILE
    assert [o.name for o in eng.state.battlefield if o.name == "Trinket"] == ["Trinket"]


def test_crucible_declined_copy_ceases_to_exist():
    eng = _seeded(2)
    p1 = eng.state.player_by_id("p1")
    _grave(eng, _spell("Insight"))
    _run(eng, CRUCIBLE)
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert [o for o in p1.exile if getattr(o, "is_copy", False)] == []


def test_hellraiser_offers_copies_of_only_the_eligible_cards():
    for seed in range(12):
        eng = _seeded(seed)
        p1 = eng.state.player_by_id("p1")
        _grave(eng, _creature("Bear"))
        _grave(eng, _land())
        _grave(eng, _spell("Insight"))
        _grave(eng, _spell("Leftover"))  # a fourth card that stays: only three are exiled
        _run(eng, HELLRAISER)
        assert len([o for o in _exiled(eng) if not getattr(o, "is_copy", False)]) == 3
        choice = eng.state.pending_choice
        if choice is None:
            continue  # the three exiled cards held no noncreature, nonland card
        names = {eng.state.find_object(i).name for i in choice["instance_ids"]}
        assert names <= {"Insight", "Leftover"}
        copy = eng.state.find_object(sorted(choice["instance_ids"])[0])
        eng.play_resolution_card(p1, copy)
        eng.resolve_until_stable()
        assert [o for o in p1.exile if getattr(o, "is_copy", False)] == []  # one copy cast, the rest ceased to exist


BOMBARDMENT = ("exile an instant or sorcery card at random from your graveyard. then copy each card exiled with ~. "
               "you may cast any number of the copies without paying their mana costs.")


def test_bombardment_copies_every_card_exiled_with_it_across_activations():
    from test_par157_back_selections import _cached
    assert parse_oracle(_cached("Arcane Bombardment")).modeled is True
    eng = _seeded(5)
    p1 = eng.state.player_by_id("p1")
    source = _bf(eng, _creature("Bombardment"))
    first = _grave(eng, _spell("First"))
    _run(eng, BOMBARDMENT, source)
    (copy_id,) = eng.state.pending_choice["instance_ids"]
    assert eng.state.find_object(copy_id).name == "First"
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    second = _grave(eng, _spell("Second"))
    _run(eng, BOMBARDMENT, source)
    names = sorted(eng.state.find_object(i).name for i in eng.state.pending_choice["instance_ids"])
    assert names == ["First", "Second"]  # RULE 607.2a: the earlier card is still linked
    for iid in list(eng.state.pending_choice["instance_ids"]):
        eng.play_resolution_card(p1, eng.state.find_object(iid))
        eng.resolve_until_stable()
        if eng.state.pending_choice is None:
            break
    casts = [e for e in eng.state.event_log if e.type == EventType.SPELL_CAST]
    assert len(casts) == 2  # "any number of the copies": both were cast
    assert first.zone == Zone.EXILE and second.zone == Zone.EXILE  # the originals are never cast
    assert [o for o in p1.exile if getattr(o, "is_copy", False)] == []


def test_linked_copy_needs_the_free_cast_wording():
    assert parse_effect_body(BOMBARDMENT.replace(" without paying their mana costs", "")) is None
