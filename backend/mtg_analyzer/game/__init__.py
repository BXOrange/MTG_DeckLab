"""Rules & game engine (Phase 2/3).

Reference: docs/07_GAME_LOOP_EFFECT_SYSTEM.md,
docs/02_MVP_USECASES_REVISED.md R2.*/R4.*.

The model layer (mtg_analyzer/models/) holds game *state*; this package
holds the *rules* that read and change it:

- ``effects``     — the effect type hierarchy + registry (docs/07 PART 2/4/6)
- ``phases``      — phases/steps as executable sequences (docs/07 PART 1)
- ``rules_engine``— casting, mana payment, stack resolution, priority,
                    replacement effects, state-based actions (docs/02 R2.*)
- ``game_engine`` — the turn/phase/step loop, action validation, goldfish
                    (docs/02 R4.*)
"""

from .effects import (
    ActivatedAbility,
    DealDamageEffect,
    DestroyEffect,
    DiscardEffect,
    DrawCardEffect,
    EffectRegistry,
    GameContext,
    GameEffect,
    ReplacementEffect,
    StaticEffect,
    TriggeredAbility,
    WinConditionEffect,
)
from .game_engine import GameEngine
from .phases import DEFAULT_TURN_SEQUENCE, GamePhase, GameStep, TurnSequence
from .rules_engine import RulesEngine

__all__ = [
    "ActivatedAbility",
    "DEFAULT_TURN_SEQUENCE",
    "DealDamageEffect",
    "DestroyEffect",
    "DiscardEffect",
    "DrawCardEffect",
    "EffectRegistry",
    "GameContext",
    "GameEffect",
    "GameEngine",
    "GamePhase",
    "GameStep",
    "ReplacementEffect",
    "RulesEngine",
    "StaticEffect",
    "TriggeredAbility",
    "TurnSequence",
    "WinConditionEffect",
]
