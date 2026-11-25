"""PAR-291 M2: non-sacrifice edicts -- "<player> exiles / returns a <pool> they control [to its owner's hand]".

The affected player (never the caster) picks which of their own permanents leaves (RULE 101.4 order for mass ones).
"""
import pytest

from test_par320_edict_counts_punishers import _three, _creature, _land, _put, _real, _card, _ids
from test_par320_residue import _spell
from mtg_analyzer.game.card_registry import is_card_covered
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

CLAIMED = ("Curfew", "Debt to the Kami", "Doomfall", "Early Winter", "Sunken Hope", "Blood Clock",
           "Blizzard Specter")


@pytest.mark.parametrize("name", CLAIMED)
def test_real_cards_are_covered(name):
    assert is_card_covered(_real(name))


@pytest.mark.parametrize("text", [
    "Each player returns a creature they control.",  # a bounce must name the hand
    "Each player exiles a creature they control to its owner's hand.",  # an exile never does
    "Each player returns a creature you control to its owner's hand.",  # the pool is the picker's own
    "Target opponent exiles a creature with flying they control.",  # a tail the edict pool refuses
])
def test_unsound_forms_stay_refused(text):
    assert not parse_oracle(_card("Neg", type_line="Sorcery", is_sorcery=True, oracle=text)).modeled


def test_curfew_each_player_chooses_their_own_creature_to_bounce():
    eng = _three()
    mine = [_creature(eng, f"A{i}", "p1") for i in range(2)]
    theirs = [_creature(eng, f"B{i}", "p2") for i in range(2)]
    solo = _creature(eng, "C0", "p3")
    _spell(eng, "Curfew")
    seen = []
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        seen.append(choice["player_id"])
        pool = mine if choice["player_id"] == "p1" else theirs
        assert _ids(choice) == {o.instance_id for o in pool}  # only that player's own creatures
        eng.resolve_pending_choice(str(pool[1].instance_id))
        eng.resolve_until_stable()
    assert seen == ["p1", "p2"]  # APNAP order; p3's lone creature is forced, never asked
    for o in (mine[1], theirs[1], solo):
        assert o.zone is Zone.HAND
    assert mine[0].zone is Zone.BATTLEFIELD and theirs[0].zone is Zone.BATTLEFIELD


def _run_mode(eng, name, index, source, targets):
    """Resolve one printed mode of the real modal card straight from its parsed spec (the mode pick is not under test)."""
    from mtg_analyzer.game.card_registry import specs_for
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext

    spec = next(s for s in specs_for(_real(name)) if s.modes)
    for e in spec.modes["options"][index]:
        effect = EffectRegistry.create(e.type, e.params)
        effect.source = source
        effect.apply(GameContext(eng.state, eng.rules), targets)
    eng.resolve_until_stable()


def test_debt_to_the_kami_exiles_the_targets_pick_not_the_casters():
    eng = _three()
    mine = _creature(eng, "Mine", "p1")
    a, b = _creature(eng, "T0", "p2"), _creature(eng, "T1", "p2")
    _run_mode(eng, "Debt to the Kami", 0, mine, [eng.state.player_by_id("p2")])
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2"
    assert _ids(choice) == {a.instance_id, b.instance_id}
    eng.resolve_pending_choice(str(b.instance_id))
    eng.resolve_until_stable()
    assert b.zone is Zone.EXILE and a.zone is Zone.BATTLEFIELD and mine.zone is Zone.BATTLEFIELD


def test_an_exile_edict_ignores_cant_be_sacrificed_and_a_player_without_the_pool_does_nothing():
    eng = _three()
    only = _creature(eng, "Only", "p2")
    only.cant_be_sacrificed_this_turn = True
    _land(eng, "Forest", "p2")
    src = _creature(eng, "Src", "p1")
    _run_mode(eng, "Debt to the Kami", 0, src, [eng.state.player_by_id("p2")])
    assert only.zone is Zone.EXILE  # RULE 701.17a: it was exiled, not sacrificed
    _run_mode(eng, "Debt to the Kami", 1, src, [eng.state.player_by_id("p3")])  # p3 controls no enchantment
    assert eng.state.pending_choice is None


def test_sunken_hope_bounces_the_active_players_creature_not_the_controllers():
    """"At the beginning of each player's upkeep, that player returns a creature they control": the upkeep player acts."""
    from mtg_analyzer.game.card_registry import specs_for
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext

    eng = _three(active="p2")
    mine = _creature(eng, "Mine", "p1")
    a, b = _creature(eng, "T0", "p2"), _creature(eng, "T1", "p2")
    spec = next(e for s in specs_for(_real("Sunken Hope")) for e in s.effects)
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = _creature(eng, "Hope", "p1")
    effect.apply(GameContext(eng.state, eng.rules))
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2"
    assert _ids(choice) == {a.instance_id, b.instance_id}
    eng.resolve_pending_choice(str(a.instance_id))
    eng.resolve_until_stable()
    assert a.zone is Zone.HAND and b.zone is Zone.BATTLEFIELD and mine.zone is Zone.BATTLEFIELD


def _blood_clock_upkeep(answer):
    """Blood Clock (controlled by p1) at p2's upkeep: p2 is asked, ``answer`` is "pay" or "decline"."""
    eng = _three()
    _put(eng, _real("Blood Clock"), "p1")
    mine = _creature(eng, "Mine", "p1")
    a, b = _creature(eng, "T0", "p2"), _creature(eng, "T1", "p2")
    eng.state.current_step = "cleanup"
    eng.begin_turn()
    while eng.state.current_step != "upkeep":
        eng.advance_step()
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "pay_cost_then" and choice["player_id"] == "p2"  # the upkeep's player, not the controller
    eng.resolve_pending_choice(answer)
    eng.resolve_until_stable()
    return eng, mine, a, b


def test_blood_clock_declined_payment_bounces_the_upkeep_players_pick():
    eng, mine, a, b = _blood_clock_upkeep("decline")
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2" and _ids(choice) == {a.instance_id, b.instance_id}
    eng.resolve_pending_choice(str(b.instance_id))
    eng.resolve_until_stable()
    assert b.zone is Zone.HAND and a.zone is Zone.BATTLEFIELD and mine.zone is Zone.BATTLEFIELD
    assert eng.state.player_by_id("p2").life == 20


def test_blood_clock_paid_life_keeps_the_permanents():
    eng, mine, a, b = _blood_clock_upkeep("pay")
    assert eng.state.pending_choice is None
    assert a.zone is Zone.BATTLEFIELD and b.zone is Zone.BATTLEFIELD
    assert eng.state.player_by_id("p2").life == 18
