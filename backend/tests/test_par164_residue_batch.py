"""PAR-164 — damage-amount threshold on the DAMAGE trigger head.

"Whenever ~ / a source you control deals N or more damage [to ...]" and "an opponent is dealt N or
more damage by a single source" (RULE 120.3 / 603.2): one DAMAGE event is one source's damage to
one recipient, so its ``amount`` is compared against N via the trigger filter's ``event_minimums``.
The recipient-side "~ is dealt N or more damage" (no "single source") counts all simultaneous
damage and stays unclaimed (Innocent Bystander).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle

THRESHOLD = 3


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _card(name, text, type_line="Creature — Bear"):
    creature = "Creature" in type_line
    return Card(id=name[:8], name=name, type_line=type_line, is_creature=creature,
                power=2 if creature else None, toughness=2 if creature else None, oracle_text=text)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _fire_count(eng, source, amount, target="p2"):
    eng.rules.deal_damage(eng.state.player_by_id(target), amount, source=source, combat=True)
    return eng.rules.put_triggers_on_stack()


# --- parse -----------------------------------------------------------------


def test_heads_carry_amount_minimum():
    head = parse_object_trigger_head("~ deals 4 or more damage")
    assert head is not None and head.trigger["filter"]["event_minimums"] == {"amount": 4}
    head = parse_object_trigger_head("an opponent is dealt 3 or more damage by a single source")
    assert head is not None and head.condition["recipient_is_opponent"] is True
    assert head.trigger["filter"]["event_minimums"] == {"amount": 3}


def test_recipient_side_without_single_source_stays_unclaimed():
    assert parse_object_trigger_head("~ is dealt 3 or more damage") is None


def test_real_cards_modeled():
    for name, text in [
        ("Deus of Calamity", "Whenever ~ deals 6 or more damage to an opponent, destroy target land that player controls."),
        ("Dragonborn Champion", "Whenever a source you control deals 5 or more damage to a player, draw a card."),
        ("Pain Magnification", "Whenever an opponent is dealt 3 or more damage by a single source, that player discards a card."),
    ]:
        assert parse_oracle(_card(name, text)).coverage == MODELED, name
    bystander = _card("Innocent Bystander", "Whenever ~ is dealt 3 or more damage, investigate.")
    assert parse_oracle(bystander).coverage != MODELED


# --- execute -----------------------------------------------------------------


def test_self_threshold_fires_at_and_above_but_not_below():
    eng = _engine()
    src = _bf(eng.state, _card("Spinneret", "Whenever ~ deals 4 or more damage, you gain 1 life."))
    assert _fire_count(eng, src, 3) == 0
    assert _fire_count(eng, src, 4) == 1
    eng.rules.resolve_top_of_stack()
    assert _fire_count(eng, src, 7) == 1


def test_split_damage_does_not_add_up():
    eng = _engine()
    src = _bf(eng.state, _card("Spinneret", "Whenever ~ deals 4 or more damage, you gain 1 life."))
    assert _fire_count(eng, src, 2) == 0
    assert _fire_count(eng, src, 2) == 0


def test_source_you_control_threshold_draws():
    eng = _engine()
    state = eng.state
    _bf(state, _card("Champion", "Whenever a source you control deals 5 or more damage to a player, draw a card."))
    mine = _bf(state, _card("Mine", ""))
    theirs = _bf(state, _card("Theirs", ""), controller="p2")
    for _ in range(2):
        state.player_by_id("p1").library.append(
            GameObject(Card(id="L", name="L", type_line="Plains", is_land=True), owner_id="p1", zone=Zone.LIBRARY))
    assert _fire_count(eng, mine, 4) == 0
    assert _fire_count(eng, theirs, 6, target="p1") == 0
    assert _fire_count(eng, mine, 5) == 1
    eng.rules.resolve_top_of_stack()
    assert len(state.player_by_id("p1").hand) == 1


def test_pain_magnification_makes_the_damaged_opponent_discard():
    eng = _engine()
    state = eng.state
    _bf(state, _card("Pain Magnification",
                     "Whenever an opponent is dealt 3 or more damage by a single source, that player discards a card.",
                     type_line="Enchantment"))
    src = _bf(state, _card("Hitter", ""))
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    for pl in (p1, p2):
        pl.hand.append(GameObject(Card(id="H" + pl.id, name="H", type_line="Plains", is_land=True),
                                  owner_id=pl.id, zone=Zone.HAND))
    assert _fire_count(eng, src, THRESHOLD - 1) == 0
    assert _fire_count(eng, src, THRESHOLD, target="p1") == 0  # not an opponent of the enchantment's controller
    assert _fire_count(eng, src, THRESHOLD) == 1
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()
    assert len(p2.hand) == 0 and len(p1.hand) == 1


# --- "you may exile it. When you do, <targeted payoff>" (reflexive, RULE 603.12) ----------------------------

PARAMECIA_TEXT = ("When ~ dies, you may exile it. When you do, "
                  "put target creature card from your graveyard on top of your library.")
BALROG_TEXT = ("When ~ dies, you may exile it. When you do, "
               "for each opponent, exile up to 1 target creature that player controls.")


def _kill(eng, obj):
    eng.rules.destroy(obj)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()


def test_may_exile_source_then_cards_modeled_and_gated_to_self_dies():
    for name, text in [("Paramecia Coloniex", PARAMECIA_TEXT), ("The Balrog of Moria", BALROG_TEXT)]:
        assert parse_oracle(_card(name, text)).coverage == MODELED, name
    attacks = _card("Odd", "Whenever ~ attacks, you may exile it. When you do, draw a card.")
    assert parse_oracle(attacks).coverage != MODELED  # "it" is not a card in the graveyard there
    sandbender = _card("Sandbender Scavengers", "When ~ dies, you may exile it. When you do, return target creature "
                       "card with mana value less than or equal to ~'s power from your graveyard to the battlefield.")
    assert parse_oracle(sandbender).coverage != MODELED


def test_paramecia_exiles_itself_then_puts_a_creature_card_on_top():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    coloniex = _bf(state, _card("Paramecia Coloniex", PARAMECIA_TEXT))
    dead = GameObject(_card("Dead Bear", ""), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(dead)
    _kill(eng, coloniex)
    assert state.pending_choice is not None and state.pending_choice["kind"] == "exile_source_then"
    eng.rules.resolve_choice("exile")
    assert coloniex.zone == Zone.EXILE
    eng.rules.put_triggers_on_stack()
    assert state.pending_choice["kind"] == "trigger_target"  # the reflexive trigger gathers its own target
    eng.rules.resolve_choice(str(dead.instance_id))
    eng.resolve_until_stable()
    assert dead.zone == Zone.LIBRARY and p1.library[0] is dead


def test_declining_the_exile_gives_no_payoff():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    coloniex = _bf(state, _card("Paramecia Coloniex", PARAMECIA_TEXT))
    dead = GameObject(_card("Dead Bear", ""), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(dead)
    _kill(eng, coloniex)
    eng.rules.resolve_choice("decline")
    assert coloniex.zone == Zone.GRAVEYARD and dead.zone == Zone.GRAVEYARD
    assert eng.rules.put_triggers_on_stack() == 0


def test_balrog_exiles_an_opponents_creature_after_exiling_itself():
    eng = _engine()
    state = eng.state
    balrog = _bf(state, _card("The Balrog of Moria", BALROG_TEXT))
    victim = _bf(state, _card("Victim", ""), controller="p2")
    _kill(eng, balrog)
    eng.rules.resolve_choice("exile")
    eng.rules.put_triggers_on_stack()
    if state.pending_choice is not None:
        eng.rules.resolve_choice(str(victim.instance_id))
    eng.resolve_until_stable()
    assert balrog.zone == Zone.EXILE
    assert victim.zone == Zone.EXILE


def test_if_you_do_spelling_fails_closed():
    # Nothing would gate an inline payoff on the exile having happened (RULE 608.2c): stays unclaimed.
    text = ("When ~ dies, you may exile it. If you do, search your library for a planeswalker card, "
            "put it onto the battlefield, then shuffle.")
    assert parse_oracle(_card("Arena Rector", text)).coverage != MODELED
    targeted = "When ~ dies, you may exile it. If you do, return target creature card from your graveyard to your hand."
    assert parse_oracle(_card("Odd Dies", targeted)).coverage != MODELED


def test_no_payoff_when_the_dying_card_left_the_graveyard_before_the_exile():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    coloniex = _bf(state, _card("Paramecia Coloniex", PARAMECIA_TEXT))
    dead = GameObject(_card("Dead Bear", ""), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(dead)
    _kill(eng, coloniex)
    coloniex.zone = Zone.HAND  # left the graveyard in response: the exile cannot happen
    eng.rules.resolve_choice("exile")
    assert coloniex.zone == Zone.HAND
    assert eng.rules.put_triggers_on_stack() == 0 and state.pending_choice is None


def test_that_player_under_a_group_damage_head_is_the_damaged_player():
    # Previously read as the damage source's controller (Larceny made its own controller discard).
    text = "Whenever a creature you control deals combat damage to a player, that player discards a card."
    eng = _engine()
    state = eng.state
    _bf(state, _card("Larceny", text, type_line="Enchantment"))
    hitter = _bf(state, _card("Hitter", ""))
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    for pl in (p1, p2):
        pl.hand.append(GameObject(Card(id="H" + pl.id, name="H", type_line="Plains", is_land=True),
                                  owner_id=pl.id, zone=Zone.HAND))
    assert _fire_count(eng, hitter, 1) == 1
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()
    assert len(p1.hand) == 1 and len(p2.hand) == 0
