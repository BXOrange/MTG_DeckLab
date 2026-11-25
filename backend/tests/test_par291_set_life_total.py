"""PAR-291: "<player>'s life total becomes <amount>" -- one parsed shape for every printed subject and amount."""
import pytest

from test_par320_edict_counts_punishers import _three, _creature, _real, _card
from test_par320_residue import _spell
from mtg_analyzer.game.card_registry import is_card_covered
from mtg_analyzer.parser.oracle.gate import parse_oracle

CLAIMED = ("Mindslicer", "Sire of Insanity", "Myojin of Night's Reach", "Jace's Archivist", "Whispering Madness",
           "Arbiter of Knollridge", "Biorhythm", "Blessed Wind", "Magister Sphinx", "Repay in Kind",
           "Shaman of Forgotten Ways", "The Darkhold", "The Endstone", "Vraska, Relic Seeker")


@pytest.mark.parametrize("name", CLAIMED)
def test_real_cards_are_covered(name):
    assert is_card_covered(_real(name))


@pytest.mark.parametrize("text", [
    "Your life total becomes the number of creatures they control.",  # two players named
    "Each player's life total becomes the number of creatures you control.",  # per-player count from the controller
    "Target player's life total becomes the highest life total among all creatures.",
    "That player's life total becomes 1.",  # needs a trigger event; not claimed by this row
])
def test_mismatched_or_unmodelled_forms_stay_refused(text):
    assert not parse_oracle(_card('Negative', type_line='Sorcery', is_sorcery=True, oracle=text)).modeled


def test_biorhythm_counts_each_players_own_creatures():
    eng = _three()
    ps = list(eng.state.players)
    for i, p in enumerate(ps):
        p.life = (20, 5, 33)[i]
        for j in range((3, 0, 2)[i]):
            _creature(eng, f"C{i}{j}", p.id)
    _spell(eng, "Biorhythm")
    assert [p.life for p in ps] == [3, 0, 2]


def _run_card_effect(eng, name, source, effect_type="set_life"):
    """Resolve the first ``effect_type`` effect the parser reads off the real card (its ETB / activated / spell body)."""
    from mtg_analyzer.game.card_registry import specs_for
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext

    spec = next(e for s in specs_for(_real(name)) for e in s.effects if e.type == effect_type)
    effect = EffectRegistry.create(effect_type, spec.params)
    effect.source = source
    effect.apply(GameContext(eng.state, eng.rules))


def test_repay_in_kind_and_arbiter_use_the_extreme_measured_once():
    eng = _three()
    ps = list(eng.state.players)
    for p, life in zip(ps, (12, 7, 30)):
        p.life = life
    _spell(eng, "Repay in Kind")
    assert [p.life for p in ps] == [7, 7, 7]
    for p, life in zip(ps, (12, 7, 30)):
        p.life = life
    _run_card_effect(eng, "Arbiter of Knollridge", _creature(eng, "Src", "p1"))
    assert [p.life for p in ps] == [30, 30, 30]


def test_blessed_wind_sets_the_target_only():
    eng = _three()
    target = eng.state.player_by_id("p2")
    target.life = 3
    _spell(eng, "Blessed Wind", [target])
    assert [p.life for p in eng.state.players] == [20, 20, 20]
    target.life = 41
    _spell(eng, "Blessed Wind", [target])
    assert target.life == 20


def test_starting_life_fractions_round_as_printed():
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
    eng = _three()
    me = eng.state.player_by_id("p1")
    me.starting_life = 41
    src = _creature(eng, "Src", "p1")
    for params, expected in (({"fraction_of_starting": 2, "round_up": True, "target_kind": None}, 21),
                             ({"fraction_of_starting": 2, "target_kind": None}, 20),
                             ({"fraction_of_starting": 1, "target_kind": None}, 41)):
        me.life = 3
        effect = EffectRegistry.create("set_life", params)
        effect.source = src
        effect.apply(GameContext(eng.state, eng.rules))
        assert me.life == expected


def _fill_hands(eng, sizes):
    from test_par320_residue import _hand
    for p, n in zip(eng.state.players, sizes):
        _hand(eng, p.id, n)


def test_each_player_discards_their_hand():
    eng = _three()
    _fill_hands(eng, (3, 0, 5))
    _run_card_effect(eng, "Sire of Insanity", _creature(eng, "Src", "p1"), "discard")
    assert [len(p.hand) for p in eng.state.players] == [0, 0, 0]


def test_each_opponent_discards_only_the_opponents_hands():
    eng = _three()
    _fill_hands(eng, (3, 2, 5))
    _run_card_effect(eng, "Myojin of Night's Reach", _creature(eng, "Src", "p1"), "discard")
    assert [len(p.hand) for p in eng.state.players] == [3, 0, 0]


def test_jaces_archivist_draws_the_greatest_discard_for_everyone():
    eng = _three()
    _fill_hands(eng, (3, 1, 5))
    for p in eng.state.players:
        from test_par320_residue import _library
        _library(eng, p.id, 10)
    _run_card_effect(eng, "Jace's Archivist", _creature(eng, "Src", "p1"), "bind")
    assert [len(p.hand) for p in eng.state.players] == [5, 5, 5]


def test_third_person_that_many_tokens_after_a_discard_are_not_a_trigger_amount():
    """Awaken the Erstwhile counts each player's own discard; "creates that many" must not read a trigger amount."""
    assert not is_card_covered(_real("Awaken the Erstwhile"))
