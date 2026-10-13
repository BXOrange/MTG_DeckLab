"""PAR-126 — parser rows for "a spell or ability an opponent controls causes you to
discard `<X>`" (RULE 603.1/614.1) onto MEC-101's `DISCARD_CARD.cause_controller_id`
provenance. Cards are built from their real Oracle text under a non-catalogue name so the
parser fallback (not a hand-authored entry) supplies the behaviour."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance

_PROV = ParserProvenance(version="test", source="test")

GUERRILLA = ("When a spell or ability an opponent controls causes you to discard this card, "
             "it deals 4 damage to any target.")
PURGE = ("When a spell or ability an opponent controls causes you to discard this card, "
         "that player loses 5 life.")
QUAGNOTH = ("When a spell or ability an opponent controls causes you to discard this card, "
            "return it to your hand.")
SAND_GOLEM = ("When a spell or ability an opponent controls causes you to discard this card, "
              "return this card from your graveyard to the battlefield with a +1/+1 counter "
              "on it at the beginning of the next end step.")
MANGARA = ("When a spell or ability an opponent controls causes you to discard this card, "
           "you gain 2 life, and you return this card from your graveyard to your hand at "
           "the beginning of the next end step.")
FOCUS = ("Whenever a spell or ability an opponent controls causes you to discard a card, "
         "you gain 2 life and you may draw a card.")
LIEGE = ("If a spell or ability an opponent controls causes you to discard this card, put it "
         "onto the battlefield instead of putting it into your graveyard.")


def _seg(text):
    return segment_line(text.lower().replace("this card", "this card"), allow_spell_effect=False,
                        provenance=_PROV)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20,
                              starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _cause(controller="p2"):
    obj = GameObject(Card(id="Src", name="Src", type_line="Sorcery"), owner_id=controller,
                     zone=Zone.STACK)
    obj.controller_id = controller
    return obj


def _in_hand(eng, text, type_line="Creature", name="Test Discarder"):
    p1 = eng.state.player_by_id("p1")
    card = Card(id=name, name=name, type_line=type_line, oracle_text=text,
                is_creature="Creature" in type_line,
                power=2 if "Creature" in type_line else None,
                toughness=2 if "Creature" in type_line else None)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    return obj


# --- parser shapes ---------------------------------------------------------------------


def test_self_form_emits_opponent_caused_discard_trigger():
    seg = _seg(GUERRILLA)
    assert seg.claimed
    assert seg.spec.trigger == {
        "event": "DISCARD_CARD", "condition": {"subject": "self"},
        "requires_opponent_caused_discard": True,
    }


def test_a_card_form_is_player_subject():
    seg = _seg(FOCUS)
    assert seg.claimed
    assert seg.spec.trigger["condition"] == {"subject": "you"}


def test_wilt_leaf_clause_is_a_replacement_not_a_trigger():
    seg = _seg(LIEGE)
    assert seg.claimed
    assert seg.spec.ability_kind == "replacement"
    assert [e.type for e in seg.spec.effects] == ["discard_to_battlefield"]


def test_broader_effect_causes_wording_stays_unclaimed():
    seg = _seg("If an effect causes you to discard a card, discard it, but you may put it on "
               "top of your library instead of into your graveyard.")
    assert not seg.claimed


# --- engine, end to end -----------------------------------------------------------------


def test_psychic_purge_drains_the_causing_opponent():
    eng = _engine()
    obj = _in_hand(eng, PURGE, type_line="Sorcery")
    eng.rules.discard_specific(obj, cause=_cause())
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 15
    assert eng.state.player_by_id("p1").life == 20


def test_quagnoth_returns_to_hand_on_opponent_discard():
    eng = _engine()
    obj = _in_hand(eng, QUAGNOTH)
    eng.rules.discard_specific(obj, cause=_cause())
    eng.resolve_until_stable()
    assert obj in eng.state.player_by_id("p1").hand


def test_own_discard_does_not_fire():
    eng = _engine()
    obj = _in_hand(eng, PURGE, type_line="Sorcery")
    eng.rules.discard_specific(obj)  # cleanup / own cost: no cause
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 20
    assert obj in eng.state.player_by_id("p1").graveyard


def test_own_ability_cause_does_not_fire():
    eng = _engine()
    obj = _in_hand(eng, QUAGNOTH)
    eng.rules.discard_specific(obj, cause=_cause("p1"))
    eng.resolve_until_stable()
    assert obj in eng.state.player_by_id("p1").graveyard


def test_mangara_gains_life_now_and_returns_at_end_step():
    eng = _engine()
    obj = _in_hand(eng, MANGARA, type_line="Instant")
    eng.rules.discard_specific(obj, cause=_cause())
    eng.resolve_until_stable()
    p1 = eng.state.player_by_id("p1")
    assert p1.life == 22 and obj in p1.graveyard
    eng.state.current_step = "end"
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert obj in p1.hand


def test_sand_golem_returns_with_counter_at_end_step():
    eng = _engine()
    obj = _in_hand(eng, SAND_GOLEM, type_line="Artifact Creature — Golem")
    eng.rules.discard_specific(obj, cause=_cause())
    eng.resolve_until_stable()
    p1 = eng.state.player_by_id("p1")
    assert obj in p1.graveyard
    eng.state.current_step = "end"
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD
    assert obj.counters.get("+1/+1") == 1


def test_guerrilla_tactics_trigger_goes_on_the_stack_from_the_graveyard():
    eng = _engine()
    obj = _in_hand(eng, GUERRILLA, type_line="Instant")
    assert len(obj.triggered_abilities) == 1
    eng.rules.discard_specific(obj, cause=_cause())
    assert obj in eng.state.player_by_id("p1").graveyard
    assert len(eng.rules.pending_triggers) == 1, "trigger queued off the discarded card"


def test_guerrilla_tactics_own_discard_queues_nothing():
    eng = _engine()
    obj = _in_hand(eng, GUERRILLA, type_line="Instant")
    eng.rules.discard_specific(obj)
    assert len(eng.rules.pending_triggers) == 0


def test_wilt_leaf_liege_enters_battlefield_instead_of_graveyard():
    eng = _engine()
    obj = _in_hand(eng, LIEGE)
    eng.rules.discard_specific(obj, cause=_cause())
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD
    assert obj not in eng.state.player_by_id("p1").graveyard


def test_wilt_leaf_liege_own_discard_goes_to_graveyard():
    eng = _engine()
    obj = _in_hand(eng, LIEGE)
    eng.rules.discard_specific(obj)
    eng.resolve_until_stable()
    assert obj in eng.state.player_by_id("p1").graveyard


def test_metrognome_makes_tokens_for_the_discarded_cards_owner():
    eng = _engine()
    obj = _in_hand(eng, "When a spell or ability an opponent controls causes you to discard "
                        "this card, create 4 1/1 colorless Gnome artifact creature tokens.",
                   type_line="Artifact")
    eng.rules.discard_specific(obj, cause=_cause())
    eng.resolve_until_stable()
    gnomes = [o for o in eng.state.battlefield if "Gnome" in o.card.type_line]
    assert len(gnomes) == 4 and all(g.controller_id == "p1" for g in gnomes)


def test_spiritual_focus_fires_from_the_battlefield_for_any_caused_discard():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    focus = _in_hand(eng, FOCUS, type_line="Enchantment", name="Test Focus")
    p1.hand.remove(focus)
    focus.zone = Zone.BATTLEFIELD
    eng.state.battlefield.append(focus)
    victim = _in_hand(eng, "", type_line="Instant", name="Plain Victim")
    eng.rules.discard_specific(victim, cause=_cause())
    eng.resolve_until_stable()
    assert p1.life == 22
    own = _in_hand(eng, "", type_line="Instant", name="Own Victim")
    eng.rules.discard_specific(own)
    eng.resolve_until_stable()
    assert p1.life == 22
