"""PAR-283: the shared condition vocabulary reads the open leading/trailing "if" predicates.

Milestone 1: X thresholds, referent type phrases (conjunction, supertype, token, any subtype), "that spell" cast
facts, "your team", graveyard-source, "didn't attack", "no creatures are on the battlefield" and the hand-size
comparison with every opponent. Each phrase lands once in `static_condition` and is read by `condition_holds`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.static_conditions import condition_holds
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle


def _real(name):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _engine():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    return eng, eng.state.players[0]


def _battlefield(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _hand_spell(eng, p1, card, **cast):
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return obj


# -- parser: the phrases map to existing kinds ------------------------------------------------------------------------


@pytest.mark.parametrize("phrase,expected", [
    ("x is 6 or more", {"kind": "x_paid", "min": 6}),
    ("x was 7 or greater", {"kind": "x_paid", "min": 7}),
    ("x is 3 or less", {"kind": "x_paid", "max": 3}),
    ("x is 3", {"kind": "x_paid", "min": 3, "max": 3}),
    ("~ is in your graveyard", {"kind": "source_in_graveyard"}),
    ("this card is in your graveyard", {"kind": "source_in_graveyard"}),
    ("no creatures are on the battlefield", {"kind": "no_creatures_on_battlefield"}),
    ("you have more cards in hand than each opponent", {"kind": "you_have_most_cards_in_hand"}),
    ("~ didn't attack this turn", {"kind": "not", "condition": {"kind": "source_attacked_this_turn"}}),
    ("~ wasn't kicked", {"kind": "kicked", "max": 0}),
])
def test_phrase_maps_to_the_shared_kind(phrase, expected):
    assert static_condition(phrase) == expected


def test_your_team_is_the_controller_outside_a_team_game():
    assert static_condition("your team controls another warrior") == static_condition("you control another warrior")
    assert static_condition("your team gained life this turn") == static_condition("you gained life this turn")


@pytest.mark.parametrize("phrase,expected", [
    ("it was an artifact creature", {"kind": "all", "conditions": [
        {"kind": "is_card_type", "of": "previous_target", "card_type": "artifact"},
        {"kind": "is_card_type", "of": "previous_target", "card_type": "creature"}]}),
    # The contraction leaves the referent to the caller: the source in a standing clause, the pick after a target.
    ("it's an artifact creature", {"kind": "all", "conditions": [
        {"kind": "is_card_type", "card_type": "artifact"}, {"kind": "is_card_type", "card_type": "creature"}]}),
    ("that creature was a villain", {"kind": "is_subtype", "of": "previous_target", "subtype": "villain"}),
    ("it was a token", {"kind": "is_token", "of": "previous_target"}),
    ("that permanent was a legendary enchantment", {"kind": "all", "conditions": [
        {"kind": "is_legendary", "of": "previous_target"},
        {"kind": "is_card_type", "of": "previous_target", "card_type": "enchantment"}]}),
    ("it was a creature or planeswalker card", {"kind": "any", "conditions": [
        {"kind": "is_card_type", "of": "previous_target", "card_type": "creature"},
        {"kind": "is_card_type", "of": "previous_target", "card_type": "planeswalker"}]}),
])
def test_referent_type_phrases_read_every_characteristic_word(phrase, expected):
    assert static_condition(phrase) == expected


def test_permanent_card_means_neither_instant_nor_sorcery():
    cond = static_condition("it was a permanent card")
    assert cond["kind"] == "not" and {c["card_type"] for c in cond["condition"]["conditions"]} == {"instant", "sorcery"}


@pytest.mark.parametrize("phrase", [
    "it was a fnord", "that creature was a legendary fnord", "x is", "it's a creature card",
])
def test_unknown_words_fail_closed(phrase):
    assert static_condition(phrase) is None


# -- engine: the new kind and the real cards ---------------------------------------------------------------------------


def test_you_have_most_cards_in_hand_needs_strictly_more_than_every_opponent():
    eng, p1 = _engine()
    p2 = eng.state.players[1]
    filler = lambda i: GameObject(Card(id=f"c{i}", name=f"C{i}", type_line="Sorcery", oracle_text=""),
                                  owner_id="p1", zone=Zone.HAND)
    cond = {"kind": "you_have_most_cards_in_hand"}
    p1.hand.extend(filler(i) for i in range(2))
    p2.hand.extend(filler(i + 10) for i in range(2))
    assert condition_holds(cond, eng.state, None, "p1") is False  # equal is not "more than each opponent"
    p1.hand.append(filler(5))
    assert condition_holds(cond, eng.state, None, "p1") is True


def test_source_in_graveyard_follows_the_zone():
    eng, p1 = _engine()
    angel = _battlefield(eng, _real("Arden Angel"))
    assert condition_holds({"kind": "source_in_graveyard"}, eng.state, angel, "p1") is False
    angel.zone = Zone.GRAVEYARD
    assert condition_holds({"kind": "source_in_graveyard"}, eng.state, angel, "p1") is True


@pytest.mark.parametrize("name", [
    "Blot Out the Sky", "Built to Last", "Blacksmith's Skill", "Death's Caress", "Venom, Eddie Brock", "Pestilence",
    "Arden Angel", "Aurora Champion", "Akuta, Born of Ash", "Skizzik", "Air Nomad Student", "Bloodstone Goblin",
    "Reject Imperfection", "Subterranean Tremors", "Budding Insurgent", "Warren Pilferers", "The Destruction of Praxis",
])
def test_real_cards_gained_are_modeled(name):
    assert parse_oracle(_real(name)).coverage == MODELED


@pytest.mark.parametrize("x,destroyed", [(5, False), (6, True)])
def test_blot_out_the_sky_destroys_noncreature_nonland_permanents_only_from_x_six(x, destroyed):
    eng, p1 = _engine()
    enchantment = _battlefield(eng, Card(id="E", name="E", type_line="Enchantment", oracle_text=""))
    bear = _battlefield(eng, Card(id="B", name="B", type_line="Creature — Bear", is_creature=True, power=2, toughness=2))
    spell = _hand_spell(eng, p1, _real("Blot Out the Sky"))
    p1.mana_pool.add_many({"W": x, "B": x, "C": x + 2})
    eng.cast_spell(p1, spell, x=x)
    eng.resolve_until_stable()
    assert (enchantment.zone == Zone.GRAVEYARD) is destroyed
    assert bear.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("type_line,indestructible", [("Artifact Creature — Golem", True), ("Creature — Bear", False)])
def test_built_to_last_grants_indestructible_only_to_an_artifact_creature(type_line, indestructible):
    eng, p1 = _engine()
    target = _battlefield(eng, Card(id="T", name="T", type_line=type_line, is_creature=True, power=2, toughness=2))
    spell = _hand_spell(eng, p1, _real("Built to Last"))
    p1.mana_pool.add_many({"W": 3, "C": 3})
    eng.cast_spell(p1, spell, targets=[target])
    eng.resolve_until_stable()
    continuous.recompute(eng.state)
    assert target.power == 4  # the +2/+2 is unconditional
    assert combat.has(target, "indestructible") is indestructible


@pytest.mark.parametrize("kicked,pumped", [(0, False), (1, True)])
def test_bloodstone_goblin_reads_the_kicked_record_of_the_spell_that_was_cast(kicked, pumped):
    eng, p1 = _engine()
    goblin = _battlefield(eng, _real("Bloodstone Goblin"))
    spell = _hand_spell(eng, p1, Card(
        id="K", name="K", type_line="Sorcery", is_sorcery=True, mana_cost_string="{U}", converted_mana_cost=1,
        oracle_text="Kicker {1}\nYou gain 1 life.", keywords=["Kicker"]))
    p1.mana_pool.add_many({"U": 1, "C": 1})
    eng.cast_spell(p1, spell, kicked=kicked)
    eng.resolve_until_stable()
    continuous.recompute(eng.state)
    assert (goblin.power == 3) is pumped


def test_graveyard_trigger_still_fires_from_the_graveyard_with_the_source_zone_gate():
    # "while this card is in your graveyard" now also carries `source_in_graveyard` as the ability's gate.
    eng, p1 = _engine()
    forebear = GameObject(_real("Furious Forebear"), owner_id="p1", zone=Zone.GRAVEYARD)
    forebear.controller_id = "p1"
    bind_from_catalogue(forebear)
    p1.graveyard.append(forebear)
    bear = _battlefield(eng, Card(id="B", name="B", type_line="Creature — Bear", is_creature=True, power=2, toughness=2))
    p1.mana_pool.add_many({"W": 1, "C": 1})
    eng.rules.destroy(bear)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_pending_choice("pay")
    assert forebear.zone == Zone.HAND


def test_a_standing_it_s_a_wall_reads_the_source_not_a_pick():
    spec = next(s for s in parse_oracle(_real("Mistform Wall")).specs if s.ability_kind == "static")
    assert spec.effects[0].params["active_if"] == {"kind": "is_subtype", "subtype": "wall"}


@pytest.mark.parametrize("type_line,life", [("Creature — Human Peasant", 23), ("Creature — Bear", 20)])
def test_deaths_caress_gains_life_equal_to_toughness_only_for_a_human(type_line, life):
    eng, p1 = _engine()
    victim = _battlefield(eng, Card(id="V", name="V", type_line=type_line, is_creature=True, power=2, toughness=3),
                          controller="p2")
    spell = _hand_spell(eng, p1, _real("Death's Caress"))
    p1.mana_pool.add_many({"B": 3, "C": 3})
    eng.cast_spell(p1, spell, targets=[victim])
    eng.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD
    assert p1.life == life


@pytest.mark.parametrize("subtype,drawn", [("Villain", 1), ("Bear", 0)])
def test_venom_draws_only_when_the_creature_that_died_was_a_villain(subtype, drawn):
    eng, p1 = _engine()
    venom = _battlefield(eng, _real("Venom, Eddie Brock"))
    other = _battlefield(eng, Card(id="O", name="O", type_line=f"Creature — {subtype}", is_creature=True,
                                   power=1, toughness=1))
    deck = [Card(id=f"d{i}", name=f"D{i}", type_line="Land") for i in range(3)]
    for c in deck:
        p1.library.append(GameObject(c, owner_id="p1", zone=Zone.LIBRARY))
    hand_before = len(p1.hand)
    eng.rules.destroy(other)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert len(p1.hand) - hand_before == drawn
    assert venom.counters.get("+1/+1") == 1


# -- milestone 2: "if that player ..." on a per-player phase trigger --------------------------------------------------


def _phase_trigger_board(name):
    eng, p1 = _engine()
    eng.begin_turn()
    card = _battlefield(eng, _real(name))
    return eng, card, eng.state.players[1]


def _fire_step_as_p2(eng, step):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng.state.active_player_index = 1  # p2's own turn
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step, phase="beginning"))
    return eng.rules.put_triggers_on_stack()


def test_that_player_gates_read_the_player_whose_step_it_is():
    for name in ("Ebony Owl Netsuke", "Misers' Cage", "Razor Pendulum", "Rivalry", "Impatience", "Predatory Advantage"):
        result = parse_oracle(_real(name))
        assert result.coverage == MODELED, (name, result.unclaimed)


@pytest.mark.parametrize("cards,fires", [(4, False), (5, True)])
def test_misers_cage_checks_that_players_hand_not_the_controllers(cards, fires):
    eng, cage, p2 = _phase_trigger_board("Misers' Cage")
    for i in range(cards):
        p2.hand.append(GameObject(Card(id=f"h{i}", name=f"H{i}", type_line="Sorcery"), owner_id="p2", zone=Zone.HAND))
    # p1 (the controller) holds no cards: reading the controller's hand would never reach five.
    placed = _fire_step_as_p2(eng, "upkeep")
    assert placed == (1 if fires else 0)
    if fires:
        eng.rules.resolve_top_of_stack()
        assert p2.life == 18


def test_impatience_punishes_only_a_player_who_cast_nothing_this_turn():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng, impatience, p2 = _phase_trigger_board("Impatience")
    eng.state.active_player_index = 1
    # The controller casting a spell is no excuse for p2.
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", instance_id="x", object_types=["sorcery"]))
    assert _fire_step_as_p2(eng, "end") == 1
    eng.rules.resolve_top_of_stack()
    assert p2.life == 18

    eng2, impatience2, p2b = _phase_trigger_board("Impatience")
    eng2.state.active_player_index = 1
    eng2.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2", instance_id="y", object_types=["sorcery"]))
    assert _fire_step_as_p2(eng2, "end") == 0


def test_as_active_player_fails_closed_without_a_known_inner_kind():
    eng, p1 = _engine()
    assert condition_holds({"kind": "as_active_player", "condition": {"kind": "fnord"}}, eng.state, None, "p1") is False
    assert condition_holds({"kind": "as_active_player"}, eng.state, None, "p1") is False


# -- milestone 3: what a cost sacrificed / discarded, as it was ---------------------------------------------------------


@pytest.mark.parametrize("type_line,grows", [("Creature — Human Peasant", True), ("Creature — Bear", False)])
def test_falkenrath_aristocrat_grows_only_when_the_sacrificed_creature_was_a_human(type_line, grows):
    eng, p1 = _engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    aristocrat = _battlefield(eng, _real("Falkenrath Aristocrat"))
    victim = _battlefield(eng, Card(id="V", name="V", type_line=type_line, is_creature=True, power=1, toughness=1))
    eng.activate_ability(p1, aristocrat, sacrifice_choice=victim.instance_id)
    eng.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD
    assert (aristocrat.counters.get("+1/+1", 0) == 1) is grows


@pytest.mark.parametrize("type_line,drawn", [("Artifact — Vehicle", 1), ("Artifact Creature — Golem", 0)])
def test_hellish_sideswipe_draws_only_for_a_sacrificed_vehicle(type_line, drawn):
    eng, p1 = _engine()
    creature = "Creature" in type_line
    victim_card = Card(id="S", name="S", type_line=type_line, is_creature=creature,
                       power=2 if creature else None, toughness=2 if creature else None)
    sacrificed = _battlefield(eng, victim_card)
    target = _battlefield(eng, Card(id="T", name="T", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
                          controller="p2")
    for i in range(2):
        p1.library.append(GameObject(Card(id=f"d{i}", name=f"D{i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    spell = _hand_spell(eng, p1, _real("Hellish Sideswipe"))
    p1.mana_pool.add_many({"B": 4, "C": 4})
    hand = len(p1.hand)
    eng.cast_spell(p1, spell, targets=[target], sacrifice_choice=sacrificed.instance_id)
    eng.resolve_until_stable()
    assert target.zone == Zone.GRAVEYARD
    assert len(p1.hand) - (hand - 1) == drawn


@pytest.mark.parametrize("subtype,tokens", [("Zombie", 1), ("Human", 0)])
def test_necromancers_stockpile_makes_a_zombie_only_for_a_discarded_zombie_card(subtype, tokens):
    eng, p1 = _engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    stockpile = _battlefield(eng, _real("Necromancer's Stockpile"))
    discarded = GameObject(Card(id="D", name="D", type_line=f"Creature — {subtype}", is_creature=True, power=1, toughness=1),
                           owner_id="p1", zone=Zone.HAND)
    p1.hand.append(discarded)
    p1.library.append(GameObject(Card(id="L", name="L", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    p1.mana_pool.add_many({"B": 2})
    eng.activate_ability(p1, stockpile, discard_choices=[discarded.instance_id])
    eng.resolve_until_stable()
    made = [o for o in eng.state.battlefield if o.name == "Zombie"]
    assert len(made) == tokens


# -- milestone 4: "if you controlled that permanent" (RULE 608.2h last-known controller) --------------------------------


@pytest.mark.parametrize("owner_side,drawn", [("p1", 1), ("p2", 0)])
def test_boomerang_basics_draws_only_when_you_controlled_the_bounced_permanent(owner_side, drawn):
    eng, p1 = _engine()
    perm = _battlefield(eng, Card(id="P", name="P", type_line="Artifact"), controller=owner_side)
    for i in range(2):
        p1.library.append(GameObject(Card(id=f"d{i}", name=f"D{i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    spell = _hand_spell(eng, p1, _real("Boomerang Basics"))
    p1.mana_pool.add_many({"U": 3, "C": 3})
    eng.cast_spell(p1, spell, targets=[perm])
    eng.resolve_until_stable()
    assert perm.zone == Zone.HAND
    assert len([o for o in p1.hand if o.name.startswith("D")]) == drawn
