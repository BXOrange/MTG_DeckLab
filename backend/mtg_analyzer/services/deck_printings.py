"""Deck-scoped printing IDs for displaying alternate card images."""

from collections.abc import Callable
from copy import copy
from typing import TYPE_CHECKING

from mtg_analyzer.services.scryfall_client import card_from_scryfall_data

from mtg_analyzer.models.cards.card import Card

if TYPE_CHECKING:
    from mtg_analyzer.services.deck_database import DeckDatabase

PRINTING_ID_PREFIX = "deck-printing-"
IMAGE_SIZES = ("small", "normal", "large", "png")


PrintingImages = dict[str, dict[str, str]]
PrintingLookup = Callable[[str, str], PrintingImages]


def with_printing(card: Card, printing_id: str, images: PrintingImages) -> Card:
    """Use the deck's image identity while keeping the resolved rules card."""
    printed = copy(card)
    printed.id = printing_id
    for size in IMAGE_SIZES:
        setattr(printed, f"image_uri_{size}", images["front"].get(size, ""))
        setattr(printed, f"back_image_uri_{size}", images.get("back", {}).get(size, ""))
    return printed


def apply_deck_printings(
    cards: dict[str, Card], printings: dict[str, str], lookup: PrintingLookup,
) -> dict[str, Card]:
    if not printings:
        return cards
    result = cards.copy()
    for name, card in cards.items():
        if (printing_id := printings.get(name.lower())) and (images := lookup(printing_id, name)):
            result[name] = with_printing(card, printing_id, images)
    return result


def printing_images(card: Card) -> PrintingImages:
    return {
        "front": {size: getattr(card, f"image_uri_{size}") for size in IMAGE_SIZES},
        "back": {size: getattr(card, f"back_image_uri_{size}") for size in IMAGE_SIZES},
    }


def import_deck_printings(
    hints: dict[str, tuple[str, str]], data: list[dict], database: "DeckDatabase",
) -> tuple[dict[str, str], list[str]]:
    by_code = {(p["set"].lower(), p["collector_number"].lower()): p for p in data}
    printings = {}
    missing = []
    for name, code in hints.items():
        printing = by_code.get(code)
        if printing:
            printed = card_from_scryfall_data(printing)
            faces = printing.get("card_faces") or []
            names = {printed.name.lower(), printed.flavor_name.lower()}
            for face in faces:
                names.update(face[key].lower() for key in ("name", "flavor_name") if face.get(key))
            if name.lower() in names and printed.image_uri_normal:
                printing_id = PRINTING_ID_PREFIX + printed.id
                images = [(printing_id, printing_images(printed))]
                database.save_printing_options(name, images)
                if printed.name.lower() != name.lower():
                    database.save_printing_options(printed.name, images)
                printings[name.lower()] = printing_id
                continue
        missing.append(name)
    return printings, missing
