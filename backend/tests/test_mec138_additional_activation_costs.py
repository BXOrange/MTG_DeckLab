"""MEC-138: "[activated | mana] abilities of <group> cost an additional <non-mana cost> to activate" (Brutal Suppression's
"sacrifice a land", Thran Portal's "1 life"), through the real engine and real cached cards. RULE 601.2f / 602.2b (the
additional cost is part of the total cost the activator pays), 119.4 (life can be paid only if the total allows it),
605.1a (a mana ability is an activated ability), 305.6 (intrinsic basic-land mana abilities)."""
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession
from tests.support.deck_batch import card, game, main_phase

#: Ramosian Sergeant's "{3}, {T}: search ..." costs {3}.
SERGEANT_MANA = 3
#: Thran Portal's added life cost.
PORTAL_LIFE = 1
STARTING_LIFE = 20
#: A one-mana spell's cost for the auto-tap checks.
ONE_GREEN = "{G}"


def _sergeant_actions(eng, player="p1", source=None):
    return [a for a in eng.legal_actions(eng.state.player_by_id(player))
            if a["type"] == "activate_ability" and (source is None or a["instance_id"] == source.instance_id)]


def _portal(eng, player="p1", land_type="Forest"):
    portal = card(eng, "Thran Portal", player=player)
    portal.chosen_type = land_type  # the "as it enters" choice (RULE 305.6 then gives the intrinsic mana ability)
    eng.recompute_continuous_effects()
    return portal


def _tap_offers(eng, source, player="p1"):
    return [a for a in eng.legal_actions(eng.state.player_by_id(player))
            if a["type"] == "tap_for_mana" and a["instance_id"] == source.instance_id]


# --- parse ------------------------------------------------------------------------------------------------------

def test_both_cards_are_modeled_and_carry_the_additional_cost():
    db = CardDatabase(DB_PATH)
    found = {}
    for name in ("Brutal Suppression", "Thran Portal"):
        result = parse_oracle(db.get_card(name))
        assert result.modeled, (name, result.unclaimed)
        found[name] = [e.params for s in result.specs for e in s.effects if e.params.get("additional_cost")]
    assert found["Brutal Suppression"][0]["additional_cost"] == {"sacrifice": "land"}
    assert found["Brutal Suppression"][0]["source_group"] == {"controller": "any", "nontoken": True, "subtype": "rebel"}
    assert found["Thran Portal"][0]["additional_cost"] == {"pay_life": PORTAL_LIFE}
    assert found["Thran Portal"][0]["mana_abilities_only"] is True


def test_a_scaled_sacrifice_clause_stays_unclaimed():
    # Drought's "for each black mana symbol" scaling is a different primitive: never claim a clause the engine ignores.
    assert not parse_oracle(CardDatabase(DB_PATH).get_card("Drought")).modeled


# --- Brutal Suppression -----------------------------------------------------------------------------------------

def test_a_rebel_activation_offers_and_performs_the_land_sacrifice_of_the_activators_choice():
    eng = game()
    sergeant = card(eng, "Ramosian Sergeant")
    card(eng, "Brutal Suppression")
    first, second = card(eng, "Forest"), card(eng, "Forest")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("C", SERGEANT_MANA)
    offered = _sergeant_actions(eng, source=sergeant)
    assert offered and "Sacrifice a land" in offered[0]["cost_label"]
    assert {o["instance_id"] for o in offered[0]["sacrifice_cost"]["options"]} == {first.instance_id, second.instance_id}
    eng.activate_ability(p1, sergeant, 0, sacrifice_choice=second.instance_id)  # RULE 602.2b: the activator picks
    assert second in p1.graveyard and first in eng.state.battlefield
    assert sergeant.tapped and p1.mana_pool.total() == 0


def test_no_land_means_the_rebel_ability_is_not_offered_or_activatable():
    eng = game()
    sergeant = card(eng, "Ramosian Sergeant")
    card(eng, "Brutal Suppression")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("C", SERGEANT_MANA)
    assert not _sergeant_actions(eng, source=sergeant)  # RULE 601.2h: a cost that can't be paid can't be activated
    try:
        eng.activate_ability(p1, sergeant, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("activated without a land to sacrifice")
    assert not sergeant.tapped and p1.mana_pool.total() == SERGEANT_MANA


def test_without_the_enchantment_there_is_no_sacrifice():
    eng = game()
    sergeant = card(eng, "Ramosian Sergeant")
    land = card(eng, "Forest")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("C", SERGEANT_MANA)
    offered = _sergeant_actions(eng, source=sergeant)
    assert offered and "sacrifice_cost" not in offered[0]
    eng.activate_ability(p1, sergeant, 0)
    assert land in eng.state.battlefield


def test_a_token_rebel_is_unaffected():
    eng = game()
    sergeant = card(eng, "Ramosian Sergeant")
    sergeant.is_token = True  # "nontoken Rebels": a token is outside the group (RULE 111.1)
    card(eng, "Brutal Suppression")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("C", SERGEANT_MANA)
    offered = _sergeant_actions(eng, source=sergeant)
    assert offered and "sacrifice_cost" not in offered[0]  # no land needed (none exists)


def test_a_non_rebel_is_unaffected():
    eng = game()
    other = card(eng, "Llanowar Elves")
    card(eng, "Brutal Suppression")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    assert not [a for a in _sergeant_actions(eng, source=other) if "sacrifice_cost" in a]
    assert _tap_offers(eng, other)  # its mana ability is not taxed either


def test_an_opponents_rebels_pay_with_their_own_lands():
    eng = game()
    sergeant = card(eng, "Ramosian Sergeant", player="p2")
    card(eng, "Brutal Suppression", player="p1")  # global: "activated abilities of nontoken Rebels"
    mine = card(eng, "Forest", player="p1")
    p2 = eng.state.player_by_id("p2")
    main_phase(eng)
    p2.mana_pool.add("C", SERGEANT_MANA)
    assert not _sergeant_actions(eng, "p2", sergeant)  # p2 has no land of its own to sacrifice
    theirs = card(eng, "Forest", player="p2")
    offered = _sergeant_actions(eng, "p2", sergeant)
    assert offered
    assert [o["instance_id"] for o in offered[0]["sacrifice_cost"]["options"]] == [theirs.instance_id]
    eng.activate_ability(p2, sergeant, 0, sacrifice_choice=theirs.instance_id)
    assert theirs in p2.graveyard and mine in eng.state.battlefield


def test_a_session_flow_collects_the_sacrifice_and_undo_restores_it():
    eng = game()
    sergeant = card(eng, "Ramosian Sergeant")
    card(eng, "Brutal Suppression")
    land = card(eng, "Forest")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("C", SERGEANT_MANA)
    session = GameSession(eng, require_setup=False)
    offered = [a for a in session.legal_actions("p1") if a["type"] == "activate_ability"
               and a.get("instance_id") == sergeant.instance_id]
    assert offered, "the taxed ability is offered to the player (and so to bots)"
    action = dict(offered[0])
    action["sacrifice_choice"] = land.instance_id
    session.apply_action(action, actor_id="p1")
    live = session.engine.state.player_by_id("p1")
    assert land.instance_id in [o.instance_id for o in live.graveyard]
    session.rewind(1)
    restored = session.engine.state.player_by_id("p1")
    assert land.instance_id in [o.instance_id for o in session.engine.state.battlefield]
    assert restored.mana_pool.total() == SERGEANT_MANA
    assert [a for a in session.legal_actions("p1") if a["type"] == "activate_ability"
            and a.get("instance_id") == sergeant.instance_id]


# --- Thran Portal -----------------------------------------------------------------------------------------------

def test_thran_portal_taps_for_mana_at_the_price_of_one_life():
    eng = game()
    portal = _portal(eng)
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    offers = _tap_offers(eng, portal)
    assert offers and "Pay 1 life" in offers[0]["cost_label"]
    eng.tap_for_mana(p1, portal)
    assert p1.life == STARTING_LIFE - PORTAL_LIFE and p1.mana_pool.total() == 1 and portal.tapped


def test_thran_portal_cannot_be_tapped_without_the_life():
    eng = game()
    portal = _portal(eng)
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.life = 0  # RULE 119.4: a player can pay life only if their total is at least that much
    assert not _tap_offers(eng, portal)
    try:
        eng.tap_for_mana(p1, portal)
    except ValueError:
        pass
    else:
        raise AssertionError("tapped for mana with no life to pay")
    assert not portal.tapped and p1.life == 0


def test_each_portal_taxes_only_itself_and_other_lands_stay_free():
    eng = game()
    first, second = _portal(eng), _portal(eng)
    forest = card(eng, "Forest")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    eng.tap_for_mana(p1, first)
    assert p1.life == STARTING_LIFE - PORTAL_LIFE  # not 2: the second Portal's clause is its own
    eng.tap_for_mana(p1, forest)
    assert p1.life == STARTING_LIFE - PORTAL_LIFE
    assert second  # untouched


def test_auto_tap_uses_the_free_land_first_and_charges_life_only_when_forced():
    eng = game()
    portal = _portal(eng)
    forest = card(eng, "Forest")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    eng.auto_tap_for(p1, cost=ManaCost.parse(ONE_GREEN))
    assert forest.tapped and not portal.tapped and p1.life == STARTING_LIFE
    p1.mana_pool.empty()  # spend the first mana, so only the Portal is left to tap
    eng.auto_tap_for(p1, cost=ManaCost.parse(ONE_GREEN))
    assert portal.tapped and p1.life == STARTING_LIFE - PORTAL_LIFE


def test_auto_tap_does_not_treat_the_portal_as_free_at_zero_life():
    eng = game()
    _portal(eng)
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.life = 0
    try:
        eng.auto_tap_for(p1, cost=ManaCost.parse(ONE_GREEN))
    except ValueError:
        pass
    else:
        raise AssertionError("auto-tap planned a life payment the player cannot make")
    assert p1.life == 0


def test_a_session_tap_for_mana_charges_life_and_undo_restores_it():
    eng = game()
    portal = _portal(eng)
    main_phase(eng)
    session = GameSession(eng, require_setup=False)
    offer = next(a for a in session.legal_actions("p1")
                 if a["type"] == "tap_for_mana" and a["instance_id"] == portal.instance_id)
    session.apply_action(dict(offer), actor_id="p1")
    assert session.engine.state.player_by_id("p1").life == STARTING_LIFE - PORTAL_LIFE
    session.rewind(1)
    restored = session.engine.state.player_by_id("p1")
    assert restored.life == STARTING_LIFE and restored.mana_pool.total() == 0
    assert [a for a in session.legal_actions("p1") if a["type"] == "tap_for_mana"
            and a["instance_id"] == portal.instance_id]


# --- Brutal Suppression on abilities that already sacrifice (RULE 601.2f: the added cost joins the total) -----------

def _actions(eng, source, player="p1"):
    return [a for a in eng.legal_actions(eng.state.player_by_id(player))
            if a["type"] == "activate_ability" and a["instance_id"] == source.instance_id]


def test_lawbringer_sacrifices_itself_and_a_land_under_suppression():
    eng = game()
    lawbringer = card(eng, "Lawbringer")
    card(eng, "Brutal Suppression")
    target = card(eng, "Goblin Piker", player="p2")  # a red creature for the exile
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    assert not _actions(eng, lawbringer)  # no land: the combined cost can't be paid
    land, spare = card(eng, "Forest"), card(eng, "Forest")
    offered = _actions(eng, lawbringer)
    assert offered and {o["instance_id"] for o in offered[0]["sacrifice_cost"]["options"]} == {
        land.instance_id, spare.instance_id}
    eng.activate_ability(p1, lawbringer, 0, targets=[target], sacrifice_choice=spare.instance_id)
    assert lawbringer in p1.graveyard and spare in p1.graveyard and land in eng.state.battlefield


def test_trenching_steed_needs_two_different_lands_under_suppression():
    eng = game()
    steed = card(eng, "Trenching Steed")
    card(eng, "Brutal Suppression")
    first = card(eng, "Forest")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    assert not _actions(eng, steed)  # one land cannot be sacrificed twice (RULE 701.17a)
    second = card(eng, "Forest")
    assert _actions(eng, steed)
    eng.activate_ability(p1, steed, 0, sacrifice_choice=second.instance_id)
    assert first in p1.graveyard and second in p1.graveyard


def test_censer_bearer_pays_mana_itself_and_a_land_through_a_session_and_undo():
    eng = game()
    # Children of Korlis (also a Rebel) is still UNMODELED for its own effect, so Censer-Bearer stands for the shape.
    children = card(eng, "Samite Censer-Bearer")
    card(eng, "Brutal Suppression")
    land = card(eng, "Forest")
    main_phase(eng)
    eng.state.player_by_id("p1").mana_pool.add("W", 1)
    session = GameSession(eng, require_setup=False)
    offered = [a for a in session.legal_actions("p1") if a["type"] == "activate_ability"
               and a.get("instance_id") == children.instance_id]
    assert offered and "Sacrifice ~ and a land" in offered[0]["cost_label"]
    action = dict(offered[0])
    action["sacrifice_choice"] = land.instance_id
    session.apply_action(action, actor_id="p1")
    ids = [o.instance_id for o in session.engine.state.player_by_id("p1").graveyard]
    assert children.instance_id in ids and land.instance_id in ids
    session.rewind(1)
    battlefield = [o.instance_id for o in session.engine.state.battlefield]
    assert children.instance_id in battlefield and land.instance_id in battlefield


def test_no_real_card_pairs_a_payment_time_life_cost_with_thran_portals_clause():
    # The life addition is `self_only`, so it only ever meets Thran Portal's own intrinsic land-type mana ability, which
    # has no printed life payment; a sentinel (half your life, X) on that same ability cannot occur.
    eng = game()
    portal = _portal(eng)
    assert all(not a.cost.additional_cost_unpayable and a.cost.pay_life == PORTAL_LIFE
               for a in __import__("mtg_analyzer.game.mana_abilities", fromlist=["x"]).mana_abilities_for(
                   portal, state=eng.state))
