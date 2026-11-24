"""RULE 702.167: printed Craft costs and material descriptions."""
import re

_CRAFT = re.compile(r"craft with (?P<materials>.+?)\s+(?P<cost>(?:\{[^}]+\})+)\.?$", re.I)
_SIMPLE = {
    "artifact": (1, "artifact"),
    "creature": (1, "creature"),
    "cave": (1, "cave"),
    "island": (1, "island"),
    "two creatures": (2, "creature"),
    "six artifacts": (6, "artifact"),
}
_VARIABLE = {
    "one or more": (1, "any"),
    "one or more creatures": (1, "creature"),
    "one or more dinosaurs": (1, "dinosaur"),
    "four or more nonlands with activated abilities": (4, "nonland_activated"),
    "four or more red instant and/or sorcery cards": (4, "red_instant_sorcery_card"),
}


def parse_craft(line):
    match = _CRAFT.fullmatch(line.strip())
    if match is None:
        return None
    materials = match["materials"].lower()
    if materials in _SIMPLE:
        minimum, word = _SIMPLE[materials]
        return match["cost"], {"minimum": minimum, "word": word}
    if materials in _VARIABLE:
        minimum, word = _VARIABLE[materials]
        return match["cost"], {"minimum": minimum, "word": word, "variable": True}
    if materials == "two that share a card type":
        return match["cost"], {"minimum": 2, "word": "shared_type"}
    if materials == "a dinosaur, a merfolk, a pirate, and a vampire":
        return match["cost"], {"minimum": 4, "word": "four_tribes"}
    return None
