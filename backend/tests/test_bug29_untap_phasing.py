"""BUG-29: intrinsic phasing executes in the untap step (RULE 502.1, 702.26a).

Real engine, real turn transitions (`begin_turn`): a phased-in permanent with
phasing phases out on its controller's untap, phases in on the controller's
next untap (not the opponent's), attachments follow indirectly (702.26g/h),
and the phase-in/phase-out sets are taken simultaneously.
"""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine


def _card(name, text="", type_line="Creature — Bear", creature=True):
    return Card(id=name, name=name, type_line=type_line, oracle_text=text,
                is_creature=creature, power=2 if creature else None,
                toughness=2 if creature else None,
                keywords=["Phasing"] if "Phasing" in text else [])


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", [_card("A")] * 40), ("p2", "Bob", [_card("B")] * 40)],
        starting_life=20, starting_hand=0,
    )


def _put(eng, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _turn(eng, expected_player):
    """Run one whole real turn (untap step included) and check whose it was."""
    eng.run_turn()
    assert eng.state.active_player.id == expected_player


def test_phasing_creature_cycles_on_controllers_untaps_only():
    eng = _engine()
    ghost = _put(eng, _card("Ghost", "Phasing"), "p1")
    plain = _put(eng, _card("Plain"), "p1")
    for _ in range(3):
        _turn(eng, "p1")  # p1's untap: phases out
        assert ghost.phased_out is True
        _turn(eng, "p2")  # p2's untap: stays out
        assert ghost.phased_out is True
        _turn(eng, "p1")  # p1's untap: phases in, not out again
        assert ghost.phased_out is False
        _turn(eng, "p2")  # p2's untap: stays in
        assert ghost.phased_out is False
        assert plain.phased_out is False


def test_attachments_phase_indirectly_with_host_and_return_together():
    eng = _engine()
    ghost = _put(eng, _card("Ghost", "Phasing"), "p1")
    aura = _put(eng, _card("Aura", type_line="Enchantment — Aura", creature=False), "p2")
    equip = _put(eng, _card("Equip", type_line="Artifact — Equipment", creature=False), "p1")
    aura.parametric_keywords = {"enchant": {"quality": "creature"}}
    aura.attached_to = ghost.instance_id
    equip.parametric_keywords = {"equip": {}}
    equip.attached_to = ghost.instance_id
    _turn(eng, "p1")  # all out together
    assert ghost.phased_out and aura.phased_out and equip.phased_out
    assert aura.attached_to == ghost.instance_id
    _turn(eng, "p2")  # the aura's controller untaps; it must not phase in alone
    assert aura.phased_out and ghost.phased_out
    _turn(eng, "p1")  # all back in, still attached
    assert not (ghost.phased_out or aura.phased_out or equip.phased_out)
    assert aura.attached_to == ghost.instance_id and equip.attached_to == ghost.instance_id
    _turn(eng, "p2")
    _turn(eng, "p1")  # repeats
    assert ghost.phased_out and aura.phased_out and equip.phased_out


def test_phasing_in_permanent_does_not_phase_out_same_step():
    eng = _engine()
    ghost = _put(eng, _card("Ghost", "Phasing"), "p1")
    ghost.phased_out = True  # phased out under p1's control earlier
    _turn(eng, "p1")  # p1's untap: phases in, and stays in
    assert ghost.phased_out is False


def test_granted_phasing_phases_and_plain_permanent_unaffected():
    eng = _engine()
    plain = _put(eng, _card("Plain"), "p1")
    other = _put(eng, _card("Other"), "p1")
    plain.intrinsic_keywords = {"phasing"}  # a bound/granted keyword, not printed
    _turn(eng, "p1")
    assert plain.phased_out is True
    assert other.phased_out is False
