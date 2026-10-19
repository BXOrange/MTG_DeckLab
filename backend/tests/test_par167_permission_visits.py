"""Free standing casting windows belong to the original zone visit."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from test_mec106_gift import _engine
from test_par167_casting_windows import _apply, _in_graveyard, _instant


GRANT = ("until end of turn, you may cast target instant or sorcery card "
         "from your graveyard without paying its mana cost.")


def _move(eng, obj, zone):
    player = eng.state.player_by_id(obj.owner_id)
    getattr(player, obj.zone.value).remove(obj)
    obj.zone = zone
    getattr(player, zone.value).append(obj)


@pytest.mark.parametrize("restore", [False, True])
def test_free_graveyard_window_survives_clone_and_casts_without_mana(restore):
    eng = _engine()
    spell = _in_graveyard(eng, _instant())
    _apply(eng, GRANT, spell)
    if restore:
        eng = GameEngine(eng.state.clone())
        spell = eng.state.find_object(spell.instance_id)
    player = eng.state.player_by_id("p1")
    assert eng.can_cast(player, spell)
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.GRAVEYARD
    assert player.mana_pool.total() == 0


@pytest.mark.parametrize("restore", [False, True])
def test_graveyard_free_marker_does_not_waive_later_hand_cast_cost(restore):
    eng = _engine()
    spell = _in_graveyard(eng, _instant())
    _apply(eng, GRANT, spell)
    _move(eng, spell, Zone.HAND)
    if restore:
        eng = GameEngine(eng.state.clone())
        spell = eng.state.find_object(spell.instance_id)
    player = eng.state.player_by_id("p1")
    assert not eng.can_cast(player, spell)
    assert not eng.can_cast(player, spell, free=True)
    with pytest.raises(ValueError):
        eng.cast_spell(player, spell)
    player.mana_pool.add("C", 1)
    eng.cast_spell(player, spell)
    assert player.mana_pool.total() == 0


def test_new_paid_graveyard_permission_does_not_rearm_previous_free_window():
    eng = _engine()
    spell = _in_graveyard(eng, _instant())
    _apply(eng, GRANT, spell)
    _move(eng, spell, Zone.HAND)
    _move(eng, spell, Zone.GRAVEYARD)
    _apply(eng, GRANT.replace(" without paying its mana cost", ""), spell)
    player = eng.state.player_by_id("p1")
    assert not eng.can_cast(player, spell)
    player.mana_pool.add("C", 1)
    eng.cast_spell(player, spell)
    assert player.mana_pool.total() == 0


@pytest.mark.parametrize("restore", [False, True])
def test_exile_free_window_does_not_follow_a_card_to_hand(restore):
    eng = _engine()
    spell = _in_graveyard(eng, _instant())
    _move(eng, spell, Zone.EXILE)
    player = eng.state.player_by_id("p1")
    eng.rules._grant_temp_play_permission(spell, player, "Grantor", True, None)
    eng.state.grant_free_cast_permission(spell)
    assert eng.can_cast(player, spell)
    _move(eng, spell, Zone.HAND)
    if restore:
        eng = GameEngine(eng.state.clone())
        spell = eng.state.find_object(spell.instance_id)
        player = eng.state.player_by_id("p1")
    assert not eng.can_cast(player, spell)
    player.mana_pool.add("C", 1)
    eng.cast_spell(player, spell)
    assert player.mana_pool.total() == 0


def test_dynamic_pool_offers_opponent_graveyard_casts_only_to_holder_until_cleanup():
    from test_mec106_gift import _bf, _creature
    from test_par167_casting_windows import _run, URABRASK

    eng = _engine()
    holder = eng.state.player_by_id("p1")
    other = eng.state.player_by_id("p2")
    own = _in_graveyard(eng, _instant("Own"))
    theirs = _in_graveyard(eng, _instant("Theirs"), owner="p2")
    bear = _in_graveyard(eng, _creature("Wrong type"), owner="p2")
    _run(eng, URABRASK, source=_bf(eng, _creature("Grantor")))
    holder.mana_pool.add("C", 2)
    other.mana_pool.add("C", 2)

    def offered(player):
        return {action["instance_id"] for action in eng.legal_actions(player)
                if action.get("type") == "cast_spell"}

    assert {own.instance_id, theirs.instance_id} <= offered(holder)
    assert bear.instance_id not in offered(holder)
    assert own.instance_id not in offered(other)
    eng._step_cleanup()
    assert not {own.instance_id, theirs.instance_id} & offered(holder)
