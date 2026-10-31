"""PAR-215 axis E: a mana-value ceiling measured per candidate -- Drown in the Loch's "mana value less than or equal
to the number of cards in its controller's graveyard" (RULE 601.2c / RULE 202.3): each target answers to its own
controller's graveyard, so the offer is evaluated candidate by candidate."""
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game
from tests.test_par215_damage_recipients import _parse

BOUND = {"candidate_controller_count": {"zone": "graveyard", "of": "you"}}


def test_drown_in_the_loch_is_modeled_per_candidate():
    result = _parse(
        "Choose one —\n• Counter target spell with mana value less than or equal to the number of cards in its "
        "controller's graveyard.\n• Destroy target creature with mana value less than or equal to the number of "
        "cards in its controller's graveyard."
    )
    assert result.modeled
    assert "candidate_controller_count" in str(result.specs[0].to_dict())


def test_creature_offer_compares_against_each_controllers_own_graveyard():
    eng = game(library=0)
    mine = filler(eng, "Mine", mv=3, power=3, toughness=3)
    theirs = filler(eng, "Theirs", mv=3, power=3, toughness=3, player="p2")
    for i in range(3):
        filler(eng, f"Dead{i}", zone=Zone.GRAVEYARD, player="p2")  # only the opponent has a 3-card graveyard
    offered = {o["instance_id"] for o in legal_targets(
        eng.state, "p1", TargetSpec(kind="creature", max_mana_value=BOUND), None)}
    assert theirs.instance_id in offered and mine.instance_id not in offered


def test_drown_in_the_loch_destroy_mode_kills_only_a_creature_within_its_controllers_graveyard():
    eng = game(library=0)
    theirs = filler(eng, "Theirs", mv=2, power=2, toughness=2, player="p2")
    for i in range(2):
        filler(eng, f"Dead{i}", zone=Zone.GRAVEYARD, player="p2")
    spell = card(eng, "Drown in the Loch", zone=Zone.HAND)
    cast(eng, spell, targets=[theirs], mode=1)
    assert theirs.zone == Zone.GRAVEYARD


def test_spell_offer_compares_against_the_spells_own_controllers_graveyard():
    eng = game(library=0)
    big = filler(eng, "Big", mv=3, power=3, toughness=3, player="p2", zone=Zone.HAND)
    eng.state.stack.clear()
    from mtg_analyzer.models.game.game_state import StackItem
    eng.state.stack.append(StackItem(kind="spell", controller_id="p2", obj=big, description="Big"))
    spec = TargetSpec(kind="spell", spell_filter={"max_mana_value": BOUND})
    assert legal_targets(eng.state, "p1", spec, None) == []  # p2's graveyard is empty: mana value 3 > 0
    for i in range(3):
        filler(eng, f"Dead{i}", zone=Zone.GRAVEYARD, player="p2")
    assert [o["instance_id"] for o in legal_targets(eng.state, "p1", spec, None)] == [big.instance_id]
