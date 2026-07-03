// Local, client-only stand-in for the future server-side game engine
// (see docs/07_GAME_LOOP_EFFECT_SYSTEM.md). It only implements enough
// to preview a Commander opening hand on the play area: shuffle,
// draw, mulligan. No rules enforcement, no turns, no stack — that all
// belongs on the server once the real game engine exists.

let nextId = 1;
function makeCardInstance(name) {
  return { id: `c${nextId++}`, name };
}

function shuffle(cards) {
  const copy = cards.slice();
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function expandToInstances(cardCounts) {
  const instances = [];
  for (const card of cardCounts) {
    for (let i = 0; i < card.qty; i++) {
      instances.push(makeCardInstance(card.name));
    }
  }
  return instances;
}

const STARTING_LIFE = 40; // Commander default (RULE 903.7)
const OPENING_HAND_SIZE = 7;

export function newBoardFromDeck(deck) {
  const library = shuffle(expandToInstances(deck.mainDeck));
  const hand = library.splice(0, Math.min(OPENING_HAND_SIZE, library.length));

  return {
    life: STARTING_LIFE,
    commandZone: expandToInstances(deck.commanders),
    library,
    hand,
    battlefield: [],
    graveyard: [],
    exile: [],
    mulligans: 0,
  };
}

export function mulligan(board, deck) {
  const fresh = newBoardFromDeck(deck);
  return { ...fresh, mulligans: board.mulligans + 1 };
}

export function drawCard(board) {
  if (board.library.length === 0) return board;
  const [drawn, ...rest] = board.library;
  return { ...board, library: rest, hand: [...board.hand, drawn] };
}

// Moves any hand card to the battlefield. Deliberately not restricted to
// lands: without a card database the frontend only knows card names, not
// types, so real casting/timing rules can't be enforced yet. This is a
// placeholder for the future "cast_spell"/"play_land" actions the server
// will validate (see docs/05_GAME_UI_AND_CARD_INTERACTION.md PART 3).
export function moveToBattlefield(board, cardId) {
  const card = board.hand.find((c) => c.id === cardId);
  if (!card) return board;
  return {
    ...board,
    hand: board.hand.filter((c) => c.id !== cardId),
    battlefield: [...board.battlefield, card],
  };
}
