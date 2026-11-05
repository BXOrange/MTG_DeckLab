"""PAR-231 -- "<n> or more cards are put into exile" batch heads (Rakshasa Vizier, Stonebinder's Familiar).

RULE 603.2c: the `EXILE` events of one exiling action or instruction are one `EVENT_BATCH`, so a trigger
fires once per action however many cards moved; RULE 111.1: a token is not a card.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

from tests.test_par119_object_trigger_head import _named
from tests.test_par120_count_phrase import _creature, _put
from tests.test_par23_cost_help_keywords import _card, _engine, _gy, _hand, _main

VIZIER = "Whenever one or more cards are put into exile from your graveyard, put that many +1/+1 counters on ~."
FAMILIAR = ("Whenever one or more cards are put into exile during your turn, put a +1/+1 counter on ~. "
            "This ability triggers only once each turn.")


@pytest.mark.parametrize(
    "cond, trigger_keys",
    [
        ("1 or more cards are put into exile from your graveyard",
         {"exile_cards_only": True, "exile_owner": "you", "filter": {"from_zone": "graveyard"}}),
        ("1 or more cards are put into exile during your turn",
         {"exile_cards_only": True, "phase_relation": "you"}),
        ("1 or more cards an opponent owns are put into exile",
         {"exile_cards_only": True, "exile_owner": "opponent"}),
    ],
)
def test_exile_batch_grammar(cond, trigger_keys):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == "EVENT_BATCH"
    assert head.trigger["batch"] == {"of": "EXILE", "min": 1}
    for key, value in trigger_keys.items():
        assert head.trigger[key] == value


@pytest.mark.parametrize(
    "cond",
    [
        "1 or more cards an opponent owns are put into exile from your graveyard",  # contradictory owner
        "1 or more other cards are put into exile",
        "1 or more cards are put into exile from a sideboard",
        "1 or more cards are put into exile with a flavour tail",
    ],
)
def test_exile_batch_fails_closed(cond):
    assert parse_object_trigger_head(cond) is None


@pytest.mark.parametrize("name", ["Rakshasa Vizier", "Stonebinder's Familiar"])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


@pytest.mark.parametrize("name", ["The Heron Moon", "Ketramose, the New Dawn"])
def test_cards_with_an_unmodelled_second_clause_stay_unclaimed(name):
    assert parse_oracle(_named(name)).modeled is False


def _grave(state, count, owner="p1"):
    return [_gy(state, _card(f"Junk {owner}{i}", cost="{1}", type_line="Instant", is_creature=False,
                             is_instant=True), owner) for i in range(count)]


def _counters(obj):
    return obj.counters.get("+1/+1", 0)


def test_one_exile_action_of_three_graveyard_cards_is_one_trigger_with_that_many_counters():
    eng = _engine()
    state = eng.state
    vizier = _put(state, VIZIER, name="Vizier")
    cards = _grave(state, 3)
    with state.simultaneous():
        for card in cards:
            eng.rules.exile(card)
    eng.resolve_until_stable()
    assert _counters(vizier) == 3


def test_separate_exile_actions_trigger_separately():
    eng = _engine()
    state = eng.state
    vizier = _put(state, VIZIER, name="Vizier")
    for card in _grave(state, 2):
        eng.rules.exile(card)
    eng.resolve_until_stable()
    assert _counters(vizier) == 2


def test_only_your_graveyard_counts_and_only_cards_from_it():
    eng = _engine()
    state = eng.state
    vizier = _put(state, VIZIER, name="Vizier")
    eng.rules.exile(_grave(state, 1, owner="p2")[0])  # an opponent's graveyard
    eng.rules.exile(_creature(state, "Bear"))  # a battlefield card, not a graveyard one
    eng.resolve_until_stable()
    assert _counters(vizier) == 0


def test_a_delve_payment_is_a_single_action():
    # The ruling: delving several cards is one action, so Vizier triggers once for all of them.
    eng = _engine()
    state = eng.state
    vizier = _put(state, VIZIER, name="Vizier")
    _grave(state, 5)
    spell = _hand(state, _card("Treasure Cruise", cost="{7}{U}", type_line="Sorcery", is_creature=False,
                               is_sorcery=True, keywords=["Delve"], oracle_text="Delve"))
    _main(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"U": 1, "C": 3})
    eng.cast_spell(p1, spell, help_pay=True)
    eng.resolve_until_stable()
    assert len(p1.exile) == 4
    assert _counters(vizier) == 4
    assert [e for e in state.event_log if e.type == "EVENT_BATCH" and e.get("batch_of") == "EXILE"
            and len(e.get("members")) == 4]


def test_a_token_is_not_a_card_and_an_opponents_turn_does_not_count():
    eng = _engine()
    state = eng.state
    familiar = _put(state, FAMILIAR, name="Familiar", types="Creature — Spirit Dog")
    token = _creature(state, "Spirit")
    token.is_token = True
    eng.rules.exile(token)
    eng.resolve_until_stable()
    assert _counters(familiar) == 0  # RULE 111.1
    state.active_player_index = 1
    eng.rules.exile(_grave(state, 1)[0])
    eng.resolve_until_stable()
    assert _counters(familiar) == 0  # "during your turn"
    state.active_player_index = 0
    eng.rules.exile(_creature(state, "Bear"))
    eng.resolve_until_stable()
    assert _counters(familiar) == 1


def test_familiar_triggers_once_per_event_and_once_each_turn():
    eng = _engine()
    state = eng.state
    familiar = _put(state, FAMILIAR, name="Familiar", types="Creature — Spirit Dog")
    with state.simultaneous():
        for card in _grave(state, 3):
            eng.rules.exile(card)
    eng.resolve_until_stable()
    assert _counters(familiar) == 1  # the ruling: several cards in one event, one trigger
    eng.rules.exile(_creature(state, "Bear"))
    eng.resolve_until_stable()
    assert _counters(familiar) == 1  # "only once each turn"


def test_an_exile_all_spell_is_one_batch():
    eng = _engine()
    state = eng.state
    familiar = _put(state, "Whenever one or more cards are put into exile, put a +1/+1 counter on ~.", name="Familiar", types="Creature — Spirit Dog")
    # RULE 603.2c: three artifacts leave in one instruction; no once-per-turn cap hides a per-card firing.
    for i in range(3):
        _put(state, "", name=f"Relic{i}", types="Artifact", owner="p2")
    spell = _hand(state, _card("Shatter All", cost="{0}", type_line="Sorcery", is_creature=False,
                               is_sorcery=True, oracle_text="Exile all artifacts."))
    _main(eng)
    p1 = state.player_by_id("p1")
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert not [o for o in state.battlefield if "Artifact" in (o.card.type_line or "")]
    assert _counters(familiar) == 1
