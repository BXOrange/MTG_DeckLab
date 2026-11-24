"""BUG-87 / RULE 115.1 + 601.2c: a target frame offers only objects that meet every bound its spec carries.

`TargetFrame`s without the matching ``apply_*`` flag used to drop a parsed mana-value / colour / quality bound silently
(Annex Sentry's "mana value 3 or less" offered any artifact or creature). `targeting.unhonoured_qualifiers` names the
bounds a frame ignores; the full-cache sweep below proves no covered card binds a target the frame would not bound."""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import is_card_covered
from mtg_analyzer.game.targeting import TargetSpec, legal_targets, unhonoured_qualifiers
from mtg_analyzer.parser.oracle.gate import castable_back_half
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase

from test_mec171_reflexive_referents import make, new_board, on_battlefield


def offered(eng, spec):
    return {o["name"] for o in legal_targets(eng.state, "p1", spec)}


def test_artifact_or_creature_opponent_frame_applies_the_mana_value_bound():
    # Annex Sentry: "exile target artifact or creature an opponent controls with mana value 3 or less"
    eng, p1, p2 = new_board()
    on_battlefield(eng, make("Cheap Bear", cost="{1}{G}"), "p2")
    on_battlefield(eng, make("Edge Bear", cost="{2}{G}"), "p2")
    on_battlefield(eng, make("Big Bear", cost="{3}{G}"), "p2")
    on_battlefield(eng, make("Cheap Rock", "Artifact", "{2}", oracle=""), "p2")
    on_battlefield(eng, make("Big Rock", "Artifact", "{5}", oracle=""), "p2")
    on_battlefield(eng, make("Mine", cost="{1}"), "p1")
    spec = TargetSpec(kind="artifact_or_creature_you_dont_control", max_mana_value=3)
    assert unhonoured_qualifiers(spec) == ()
    assert offered(eng, spec) == {"Cheap Bear", "Edge Bear", "Cheap Rock"}


def test_creature_opponent_frame_applies_the_colour_bound():
    # Slithery Stalker: "exile target green or white creature an opponent controls"
    eng, p1, p2 = new_board()
    on_battlefield(eng, make("Green Bear", cost="{1}{G}"), "p2")
    on_battlefield(eng, make("White Bear", cost="{1}{W}"), "p2")
    on_battlefield(eng, make("Red Bear", cost="{1}{R}"), "p2")
    spec = TargetSpec(kind="creature_you_dont_control", colors=("G", "W"))
    assert unhonoured_qualifiers(spec) == ()
    assert offered(eng, spec) == {"Green Bear", "White Bear"}


@pytest.mark.parametrize("kind,mine", [("artifact_or_creature", True), ("artifact_you_control", True),
                                        ("artifact_you_dont_control", False)])
def test_artifact_frames_apply_the_nontoken_quality(kind, mine):
    # The Measure of a Man / The Blackstaff of Waterdeep / Hyperion Blacksmith: "nontoken artifact ..."
    eng, p1, p2 = new_board()
    owner = "p1" if mine else "p2"
    real = on_battlefield(eng, make("Real Rock", "Artifact", "{2}"), owner)
    fake = on_battlefield(eng, make("Fake Rock", "Artifact", "{2}"), owner)
    fake.is_token = True
    spec = TargetSpec(kind=kind, creature_filter={"nontoken": True, "card_type": "artifact"})
    assert unhonoured_qualifiers(spec) == ()
    assert offered(eng, spec) == {"Real Rock"}


def test_unhonoured_qualifiers_names_a_frame_that_ignores_a_bound():
    # A frame without the flag is reported, so the sweep below fails instead of an unbounded target slipping through.
    spec = TargetSpec(kind="artifact_enchantment_or_tapped_creature_you_dont_control", max_mana_value=3)
    assert unhonoured_qualifiers(spec) == ("max_mana_value",)
    assert unhonoured_qualifiers(TargetSpec(kind="graveyard_creature", max_mana_value=3)) == ()  # no frame: own branch


#: Binding every covered card that names a target takes minutes; the suite's 20s default would cut it off.
FULL_CACHE_SWEEP_TIMEOUT_SECONDS = 900


@pytest.mark.full_cache
@pytest.mark.timeout(FULL_CACHE_SWEEP_TIMEOUT_SECONDS)
def test_no_covered_card_binds_a_target_bound_its_frame_ignores():
    original = targeting.TargetSpec.__init__
    current: list[str] = []
    found: dict[str, set[str]] = {}

    def recording_init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if current and (dropped := unhonoured_qualifiers(self)):
            found.setdefault(f"{self.kind}:{','.join(dropped)}", set()).add(current[0])

    with CardDatabase(DB_PATH) as db:
        cards = db.list_cards()
    targeting.TargetSpec.__init__ = recording_init
    try:
        for card in cards:
            back = castable_back_half(card)
            halves = [half for half in (card, back) if half is not None and "target" in (half.oracle_text or "").lower()]
            if not halves or not is_card_covered(card):
                continue
            for half in halves:  # RULE 709.3 / 712: the other half binds as a card of its own
                current[:] = [card.name]
                bind_from_catalogue(GameObject(half, owner_id="p1", zone=Zone.BATTLEFIELD))
    finally:
        targeting.TargetSpec.__init__ = original
    assert not found, {k: sorted(v)[:5] for k, v in found.items()}
