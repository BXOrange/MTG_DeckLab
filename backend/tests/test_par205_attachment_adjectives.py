"""Leading attachment adjectives use the same live filters as trailing qualifiers."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, text="", type_line="Creature — Bear"):
    creature = "Creature" in type_line
    return Card(id=name, name=name, oracle_text=text, type_line=type_line,
                is_creature=creature, power=2 if creature else None,
                toughness=2 if creature else None)


def _place(engine, card, player="p1"):
    obj = GameObject(card, owner_id=player, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


@pytest.mark.parametrize("word", ["enchanted", "equipped"])
@pytest.mark.parametrize("tail", ["get +2/+2", "have shroud"])
def test_leading_and_trailing_attachment_words_emit_the_same_specs(word, tail):
    leading = static_effect_specs(f"{word} creatures you control {tail}.")
    trailing = static_effect_specs(f"creatures you control that are {word} {tail}.")
    assert leading and [spec.to_dict() for spec in leading] == [spec.to_dict() for spec in trailing]
    assert leading[0].params["object_filter"] == {word: True}
    assert "subtype" not in leading[0].params


@pytest.mark.parametrize("name,text", [
    ("A Tale for the Ages", "Enchanted creatures you control get +2/+2."),
    ("Greater Auramancy", "Other enchantments you control have shroud.\nEnchanted creatures you control have shroud."),
    ("Kemba, Kha Enduring", "Whenever Kemba or another Cat you control enters, attach up to one target Equipment you control to that creature.\nEquipped creatures you control get +1/+1.\n{3}{W}{W}: Create a 2/2 white Cat creature token."),
    ("Dalakos, Crafter of Wonders", "{T}: Add {C}{C}. Spend this mana only to cast artifact spells or activate abilities of artifacts.\nEquipped creatures you control have flying and haste."),
])
def test_real_card_text_is_fully_modeled(name, text):
    type_line = "Enchantment" if name in ("A Tale for the Ages", "Greater Auramancy") else "Creature — Human"
    assert parse_oracle(_card(name, text, type_line)).modeled


@pytest.mark.parametrize("word,subtype", [("enchanted", "Aura"), ("equipped", "Equipment")])
def test_anthem_tracks_attachment_type_controller_and_live_movement(word, subtype):
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    _place(engine, _card("Anthem", f"{word.capitalize()} creatures you control get +2/+2.", "Enchantment"))
    first = _place(engine, _card("First"))
    second = _place(engine, _card("Second"))
    opponent = _place(engine, _card("Opponent"), "p2")
    wrong_host = _place(engine, _card("Wrong attachment"))
    kind = "Enchantment" if subtype == "Aura" else "Artifact"
    attachment = _place(engine, _card("Attachment", type_line=f"{kind} — {subtype}"), "p2")
    attachment.attached_to = first.instance_id
    other = "Equipment" if subtype == "Aura" else "Aura"
    wrong = _place(engine, _card("Other kind", type_line=f"{'Artifact' if other == 'Equipment' else 'Enchantment'} — {other}"))
    wrong.attached_to = wrong_host.instance_id

    def pt(obj):
        engine.recompute_continuous_effects()
        return obj.power, obj.toughness

    # RULE 303.4b / 301.5: the attachment's controller is irrelevant.
    assert pt(first) == (4, 4)
    assert pt(second) == pt(opponent) == pt(wrong_host) == (2, 2)
    attachment.attached_to = second.instance_id
    assert pt(first) == (2, 2)
    assert pt(second) == (4, 4)
    attachment.attached_to = opponent.instance_id
    assert pt(second) == pt(opponent) == (2, 2)
    attachment.attached_to = None
    assert pt(first) == pt(second) == (2, 2)


def test_subtyped_keyword_grant_only_reaches_equipped_warriors():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    _place(engine, _card("Kor Blademaster", "Equipped Warriors you control have double strike."))
    warrior = _place(engine, _card("Warrior", type_line="Creature — Warrior"))
    bear = _place(engine, _card("Bear"))
    equipment = _place(engine, _card("Equipment", type_line="Artifact — Equipment"))
    for host, expected in [(warrior, True), (bear, False)]:
        equipment.attached_to = host.instance_id
        engine.recompute_continuous_effects()
        assert ("double_strike" in warrior.granted_keywords) is expected
        assert "double_strike" not in bear.granted_keywords


@pytest.mark.parametrize("detach_before_resolution", [False, True])
def test_enchanted_target_is_narrowed_and_rechecked(detach_before_resolution):
    from mtg_analyzer.game.targeting import legal_targets

    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    engine.begin_turn()
    source = _place(engine, _card("Ramses Overdark", "{T}: Destroy target enchanted creature."))
    source.summoning_sick = False
    victim = _place(engine, _card("Victim"), "p2")
    bare = _place(engine, _card("Bare"), "p2")
    aura = _place(engine, _card("Aura", "Enchant creature", type_line="Enchantment — Aura"))
    aura.attached_to = victim.instance_id
    engine.recompute_continuous_effects()
    [spec] = source.activated_abilities[0].effects[0].target_specs
    offered = {t.get("instance_id") for t in legal_targets(engine.state, "p1", spec, source)}
    assert victim.instance_id in offered and bare.instance_id not in offered
    engine.activate_ability(engine.state.player_by_id("p1"), source, 0, targets=[victim])
    if detach_before_resolution:
        aura.attached_to = None
    engine.resolve_until_stable()
    assert (victim in engine.state.battlefield) is detach_before_resolution


@pytest.mark.parametrize("text", [
    "enchanted creatures you control get +2/+2 and draw a card.",
    "equipped creatures you control have flying and an unsupported ability.",
    "enchanted creatures you control get +2/+2 unless you control a potato.",
])
def test_unsupported_tails_are_not_silently_dropped(text):
    assert static_effect_specs(text) is None
