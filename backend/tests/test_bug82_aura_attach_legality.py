"""BUG-82: an Aura found "onto the battlefield attached to ~" that cannot enchant ~ stays in its zone (RULE 303.4g)."""
import pytest

from mtg_analyzer.models.game.game_state import EventType, Zone
from tests.support.deck_batch import card, game, put_on_battlefield
from tests.test_par292_pool_cast_and_pile_plays import _pick_found


def _illegal_aura(zone):
    """Wild Growth is "Enchant land": it can never enchant Boonweaver Giant (a creature)."""
    eng = game(library=3)
    aura = card(eng, "Wild Growth", zone=zone)
    giant = put_on_battlefield(eng, "Boonweaver Giant")
    eng.state.event_log.clear()  # setup events (the graveyard placement) are not under test
    return eng, aura, giant


@pytest.mark.parametrize("zone", [Zone.HAND, Zone.GRAVEYARD, Zone.LIBRARY])
def test_an_aura_that_cannot_enchant_the_host_stays_in_its_zone(zone):
    eng, aura, giant = _illegal_aura(zone)
    _pick_found(eng, aura)
    p1 = eng.state.player_by_id("p1")
    assert aura.zone == zone and aura.attached_to is None and aura in getattr(p1, zone.value)
    assert aura not in eng.state.permanents()
    types = [e.type for e in eng.state.event_log if e.get("instance_id") == aura.instance_id]
    assert EventType.ENTERS_BATTLEFIELD not in types and EventType.ATTACHED_TO_PERMANENT not in types
    assert not [e for e in eng.state.event_log if e.type == EventType.PUT_INTO_GRAVEYARD and e.get("instance_id") == aura.instance_id]


def test_a_legal_aura_still_attaches_and_hexproof_does_not_block_it():
    eng = game(library=3)
    aura = card(eng, "Pacifism", zone=Zone.LIBRARY)  # Enchant creature
    giant = put_on_battlefield(eng, "Boonweaver Giant")
    giant.intrinsic_keywords.add("hexproof")
    _pick_found(eng, aura)
    assert aura.zone == Zone.BATTLEFIELD and aura.attached_to == giant.instance_id  # RULE 303.4f: not targeting

