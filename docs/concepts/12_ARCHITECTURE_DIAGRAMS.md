# Architecture Diagrams (PlantUML)

Visual companions to the prose design docs in this folder. These render with
any PlantUML tool (the [PlantUML VS Code extension](https://marketplace.visualstudio.com/items?itemName=jebbs.plantuml),
`plantuml.jar`, or the public plantuml.com server) — paste a fenced block's
contents between `@startuml`/`@enduml` into a renderer, or point a
PlantUML-aware Markdown previewer at this file directly.

Kept intentionally small and coarse-grained: these are orientation diagrams
for someone new to the codebase, not a generated/exhaustive UML dump. When
the shape of a module changes enough that a diagram actively misleads,
update the relevant one here — don't let it silently rot.

---

## 1. Component overview

The layered flow from the CLAUDE.md "Architecture & data flow" section, as a
component diagram. Solid arrows are direct calls/imports; the oracle-text
pipeline (dashed) is the alternate path for cards with no hand-authored
catalogue entry.

```plantuml
@startuml
skinparam componentStyle rectangle
skinparam backgroundColor transparent

package "Data model (models/)" {
  [Card] as Card
  [GameObject] as GameObject
  [GameState] as GameState
  Card --> GameObject : printed\ncharacteristics
  GameObject --> GameState : lives in a zone of
}

package "Oracle pipeline (parser/oracle/)" {
  [normalize] as Normalize
  [segmenter] as Segmenter
  [catalogue/handlers] as Handlers
  [gate.parse_oracle] as Gate
  Normalize --> Segmenter
  Segmenter --> Handlers
  Handlers --> Gate
}

package "Ability sourcing (game/)" {
  [card_catalogue\n(via card_registry.specs_for)] as Catalogue
  [effect_binder] as Binder
  [EffectRegistry] as Registry
  Catalogue --> Binder : hand-authored\nAbilitySpec
  Gate ..> Binder : MODELED\nAbilitySpec
  Binder --> Registry : builds live\nGameEffect
}

package "Rules engine (game/)" {
  [RulesEngine] as Rules
  [GameEngine] as Engine
  [combat.py] as Combat
  [continuous.py] as Continuous
  Registry --> Rules : effects act\nthrough
  Rules --> Engine : turn/stack/SBA\nprimitives
  Engine --> Combat : keyword rules,\nblocking
  Engine --> Continuous : layer recompute\n(RULE 613)
}

package "Session + API" {
  [GameSession] as Session
  [FastAPI /api/game] as API
  Engine --> Session : snapshots,\nundo, wire view
  Session --> API : JSON
}

package "Frontend (frontend/src/js/)" {
  [goldfishView.js] as Goldfish
  [replayView.js] as Replay
}
API --> Goldfish : GameState.to_dict()
API --> Replay

GameState --> Rules
Card --> Catalogue
Card --> Normalize : oracle_text
@enduml
```

---

## 2. Core data-model classes

Not every field — just the ownership/containment shape that trips people up
first: a `Card` is immutable print data, shared/cloned cheaply across
copies; a `GameObject` is one mutable in-play instance of a `Card`;
`GameState` owns every zone across both players plus the stack and event bus.

```plantuml
@startuml
skinparam classAttributeIconSize 0
skinparam backgroundColor transparent

class Card {
  name
  mana_cost / mana_cost_string
  type_line, oracle_text
  power / toughness / loyalty
  color_identity
  keywords[]
  ..immutable printed data..
}

class GameObject {
  instance_id
  zone: Zone
  owner, controller
  tapped, summoning_sick
  counters{}
  damage_marked
  attached_to
  intrinsic_keywords
  parametric_keywords
  ..derived (continuous.recompute)..
  power / toughness (effective)
  granted_keywords
  static_trace
}
Card "1" <-- "1" GameObject : .card

class Player {
  life, poison
  hand[], library[], graveyard[]
  exile[], battlefield[], command[]
  mana_pool: ManaPool
  commander_casts{}
}
GameObject "*" --o "1" Player : zone lists

class ManaPool {
  W/U/B/R/G/C tallies
  can_pay(cost)
  pay(cost)
}
Player "1" *-- "1" ManaPool

class GameState {
  players[]
  stack: StackItem[]
  turn, phase, step
  active_player
  pending_choice
  fire_event() / subscribe()
}
GameState "1" o-- "2" Player
GameState "1" o-- "*" StackItem

class StackItem {
  source: GameObject
  effects[]
  targets[]
  x (announced value)
}

class GameEffect {
  <<abstract>>
  apply(context)
}
class TriggeredAbility
class ActivatedAbility
class StaticAbility
class ReplacementEffect
GameEffect <|-- TriggeredAbility
GameEffect <|-- ActivatedAbility
GameEffect <|-- StaticAbility
GameEffect <|-- ReplacementEffect
GameObject "1" o-- "*" GameEffect : bound abilities
@enduml
```

---

## 3. Sequence: casting a spell (interactive stack, RULE 608)

Shows the "leaves the spell on the stack" model (docs/07) rather than
auto-resolve: an instant can be cast in response before the original
resolves.

```plantuml
@startuml
skinparam backgroundColor transparent
actor Player
participant "GameSession" as Session
participant "GameEngine" as Engine
participant "RulesEngine" as Rules
participant "GameState" as State
participant "EffectRegistry" as Registry

Player -> Session : action: cast_spell(card, targets, x?)
Session -> Engine : cast_spell(player, card, ...)
Engine -> Rules : effective_cast_cost(card)
Rules --> Engine : cost (incl. commander tax,\ncost reductions)
Engine -> Rules : mana_pool.pay(cost)
Engine -> State : push StackItem(card, effects, targets)
State --> Engine : ok
Engine --> Session : legal_actions() refreshed
Session --> Player : GameState.to_dict()\n(spell now visible on stack)

... opponent/you may respond with an instant, same flow ...

Player -> Session : action: pass_priority
Session -> Engine : pass_priority(player)
Engine -> Engine : all players passed\nin succession?
Engine -> State : pop top StackItem
Engine -> Registry : resolve each bound GameEffect
Registry -> Rules : effect primitives\n(deal_damage, draw_cards, ...)
Rules -> State : mutate zones/life/counters,\nfire_event(...)
State -> Rules : triggered abilities\ncollected off the event bus
Rules -> State : put_triggers_on_stack()\n(APNAP, may open a\ntrigger_target pending_choice)
Engine -> Rules : check_state_based_actions()
Rules --> Engine : SBA results (deaths, etc.)
Engine --> Session : updated GameState
Session --> Player : GameState.to_dict()
@enduml
```

---

## 4. Sequence: oracle-text → effect (bind-on-load)

The compiler pipeline behind "card text becomes behaviour without a
hand-authored entry" (docs/09). Runs once per object at game setup;
`card_registry.specs_for` is the fork between the two sources.

```plantuml
@startuml
skinparam backgroundColor transparent
participant "build_goldfish_engine" as Build
participant "card_registry\n.specs_for(card)" as Specs
participant "card_catalogue\n(hand-authored)" as Catalogue
participant "parser.oracle.gate\n.parse_oracle(card)" as Gate
participant "normalize + segmenter" as Front
participant "catalogue/handlers\n(effect families)" as Handlers
participant "effect_binder\n.bind_from_catalogue(obj)" as Binder
participant "EffectRegistry" as Registry

Build -> Specs : specs_for(card)
Specs -> Catalogue : registered by name?
alt card is hand-authored
  Catalogue --> Specs : AbilitySpec[]
else not registered
  Specs -> Gate : parse_oracle(card)
  Gate -> Front : normalize(oracle_text)\n+ segment clauses
  Front -> Handlers : each clause vs.\nthe handler table
  Handlers --> Gate : matched AbilitySpec\nor "unclaimed"
  Gate --> Specs : (AbilitySpec[], MODELED | UNMODELED)
  note right of Gate
    Fail-closed: specs are only
    added when the whole card's
    text is fully MODELED —
    never a half-resolved card.
  end note
end
Specs --> Build : AbilitySpec[]
Build -> Binder : bind_from_catalogue(obj)
Binder -> Registry : build live GameEffect\nper spec (whitelisted "type")
Registry --> Binder : GameEffect instances
Binder -> Binder : attach to obj\n(triggered/activated/static/\nreplacement/intrinsic_keywords)
@enduml
```

---

## 5. State: a turn (RULE 500)

`game/phases.py`'s `TurnSequence` walked by the engine; skip effects (docs/07
PART 8) can bypass a step entirely (e.g. an extra-combat effect, or "skip
your draw step").

```plantuml
@startuml
skinparam backgroundColor transparent
[*] --> Untap
Untap --> Upkeep
Upkeep --> Draw
Draw --> Main1
Main1 --> CombatBegin
CombatBegin --> DeclareAttackers
DeclareAttackers --> DeclareBlockers
DeclareBlockers --> CombatDamage
CombatDamage --> CombatEnd
CombatEnd --> Main2
Main2 --> EndStep
EndStep --> Cleanup
Cleanup --> Untap : next turn

note left of Draw
  Skipped on the very first
  turn of the game (RULE 103.8a)
  via a StaticEffect step-skip.
end note

note right of CombatDamage
  First/double strike:
  two damage sub-steps.
end note

note right of Cleanup
  Discard to 7, empty mana pools,
  "until end of turn" effects end
  (pump, RULE 514.2).
end note
@enduml
```

Every step opens a priority window (RULE 500.4, solo goldfish auto-resolves
it; `pass_priority(player)` is the interactive primitive, docs/07 PART 1 and
`docs/implementation-state/Done_Backend.md` "Game Engine (Phase 3)").
