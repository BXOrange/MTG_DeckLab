# Empirical land estimate and ramp draw consistency

Analyze → Advice retains the Karsten commander-cost curve table and adds a
separate deterministic comparison. `frontend/src/js/manaAdvice.js` calculates
the comparison from already-resolved cards; `manaAdviceView.js` renders it.
There is no background worker, stochastic optimiser, casting policy, spell
resampling, simulation score, or additional backend request in this feature.
The pre-existing Dynamic Analysis game-engine simulations are separate.

## Empirical land reference

Source: [Frank Karsten, How Many Lands Do You Need in Your Deck? An Updated
Analysis (2022), reproduced article](https://www.peasant-magic.com/articles/magic-deckbuilding/how-many-lands-do-you-need-in-your-deck-an-updated-analysis).

The published 99-card formula is:

```
effective lands = 31.42 + 3.13 × average nonland mana value
                          − 0.28 × cheap draw/ramp count
```

The average is quantity-weighted, excludes the command zone and ordinary
lands, and includes spell/land MDFCs at their front-face mana value. Each
qualifying card is counted once: draw/selection takes precedence over ramp.
`cheapCardKind` implements the article's text criteria, not the narrower
static Ramp category or guaranteed executable effects:

- Draw/selection normally costs at most two. It includes the article's draw
  phrases and selection predicates, with its exclusions and creature-ETB
  requirement. One-mana cycling also qualifies, even on a more expensive spell.
- Remaining nonlands costing at most two qualify as ramp through the article's
  mana-addition, library land/basic search, land-Aura or creature-cheating
  predicates. This can include rituals, conditional sources and searches to
  hand. Those labels must not be mistaken for reliable early acceleration.

The published MDFC credit is 0.38 for non-mythic and 0.74 for mythic spell/land
cards. Subtract it from the effective target, then round to show the approximate
ordinary-land target. Missing MDFC rarity withholds that ordinary-land target
instead of guessing a credit. Both input lists are expandable for inspection.

The original fit used 60-card tournament decks. The Commander adaptation is
an approximate extrapolation, not an empirical Commander optimum or a
confidence interval. The formula reduces the curve to its average, and its
2022 rarity groups may suit newer MDFCs less well. Libraries other than 99
cards get an explicit notice: the reference stays the published 99-card
formula; probability calculations use the actual library size.

## Exact draw probabilities

`drawProbability` uses the hypergeometric distribution. `jointDrawProbability`
uses the multivariate version for disjoint ordinary-land, early-ramp and other
categories. For example:

```
P(L=l, R=r) = C(lands,l) × C(ramp,r) × C(other,n−l−r) / C(size,n)
```

Sum qualifying outcomes for requirements such as at least two ordinary lands
and at least one early ramp card. Do not multiply independent land/ramp odds.
The first table reports opening hand (7 cards), turn 2 (9 seen), and turn 3
(10 seen), capped at actual library size. All calculations assume no mulligans,
extra draw or selection, and include the multiplayer turn-one draw.

The probability-specific early-ramp category is narrower than the regression:
recognized repeatable permanent mana abilities, simple land-Aura acceleration,
and library searches putting lands onto the battlefield, at mana value two
or less. One-shot rituals, conditional triggers, variable X mana, and MDFCs
are excluded. Sacrifice-to-search creature ramp can qualify. This is a draw
category; colored costs, tapped entry, activation costs, legal search targets,
land-drop timing and successful casting are not evaluated.

The user selects a 70%, 80% or 90% preference for seeing at least one early
ramp card by turn 2. `requiredRampCount` finds the smallest count meeting it,
keeping current ordinary lands and library size fixed; hypothetical additions
replace other nonland slots. It does not invent cuts, resize the spell curve,
recalculate a hypothetical land target, or claim a universally optimal count.
Unreachable preferences are reported explicitly. A separate selector sets
opening-hand minimum ordinary lands (2–4) and minimum early ramp cards (0–2).

MDFCs contribute only their published fractional credit to the regression;
they are neither ordinary lands nor early ramp in the probability calculation.
Their face choices would require a different model. These limits are visible
under Inputs, assumptions and sources. UI selection state survives deck changes
and asynchronous combo-section refreshes through a delegated listener and
explicit restoration after render.

## Verification

Run `backend/venv/bin/python frontend/tests/test_mana_advice.py` for Chromium
checks using real ES modules and a local fixture server. Tests compare joint
probabilities against exhaustive enumeration of small hands, check the
published-formula example and ramp draw values, classification/deduplication,
MDFC weights and missing rarity, impossible targets, English/German rendering,
escaping, selectors, and Analyze deck/combination refreshes without workers.
