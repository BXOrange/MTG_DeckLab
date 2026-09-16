"""Helpers shared by 2+ card factories in `card_catalogue` (a real card
*family* whose members need more than `card_registry.families.
register_family`'s single-`EffectSpec` template fits — see `licid.py`).
Not itself a card entry, and not imported by `card_catalogue/__init__.py`'s
alphabetic sweep; each member card that needs one imports it directly.
"""
