# MTG Deck Analyzer: Card Graphics & Lazy Loading Strategy

---

# PART 1: CARD GRAPHICS IN UI

## Card Display Components

### In Hand (Small Card)
```
┌──────────────┐
│   Island     │  ← Card image (thumbnail)
│ [/img]       │
│   Land       │
│ Tap: ⊗ U     │
│   [▼]        │
└──────────────┘
Width: 80-100px
Image height: 120px
Source: Scryfall image URL
```

### On Battlefield (Medium Card)
```
┌──────────────────┐
│    Grizzly       │  ← Card image (medium)
│    Bear          │
│  [/img]          │
│  (2/2)           │
│  Creature        │
│  [X] [⚔️] [TAP▼]  │
└──────────────────┘
Width: 120-150px
Image height: 200px
```

### In Expanded View (Large Card)
```
┌─────────────────────────────────┐
│        Lightning Bolt            │  ← Card image (large)
│                                 │
│        [/img]                   │
│                                 │
│        Instant                  │
│                                 │
│        Cost: 1R                 │
│                                 │
│        Deal 3 damage to target  │
│        creature or player       │
│                                 │
│        [CAST ▼] [Details]       │
└─────────────────────────────────┘
Width: 250-350px
Image height: 350-500px
```

## Image Sources

### Primary: Scryfall API

Scryfall provides card images via:
```
https://api.scryfall.com/cards/named?exact={card_name}

Returns:
{
  "id": "uuid",
  "name": "Lightning Bolt",
  "image_uris": {
    "small": "https://cards.scryfall.io/small/front/...",
    "normal": "https://cards.scryfall.io/normal/front/...",
    "large": "https://cards.scryfall.io/large/front/...",
    "png": "https://cards.scryfall.io/png/front/..."
  },
  ...
}
```

### Image URL Strategy
```
Small (Hand view):  image_uris.small       (65×90px)
Medium (Board):     image_uris.normal      (488×680px)
Large (Expanded):   image_uris.large       (672×936px)
Print/Export:       image_uris.png         (1200px height)
```

### Fallback: Text-Only If Image Unavailable
```
If image fails to load:
┌──────────────┐
│   Island     │
│              │  ← No image, use placeholder
│   [■]        │
│   Land       │
│ Tap: ⊗ U     │
└──────────────┘
```

---

# PART 2: IMAGE LOADING & CACHING STRATEGY

## Client-Side Image Caching

### React Image Component

```jsx
// CardImage.jsx
import { useState, useEffect } from 'react';

export const CardImage = ({ card, size = 'normal' }) => {
  const [imageUrl, setImageUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  
  // Get appropriate image URL based on size
  const getImageUrl = (card, size) => {
    if (!card.image_uris) return null;
    
    switch (size) {
      case 'small':
        return card.image_uris.small;
      case 'large':
        return card.image_uris.large;
      case 'png':
        return card.image_uris.png;
      case 'normal':
      default:
        return card.image_uris.normal;
    }
  };
  
  useEffect(() => {
    const url = getImageUrl(card, size);
    
    if (!url) {
      setError(true);
      setLoading(false);
      return;
    }
    
    // Check browser cache first
    const img = new Image();
    
    img.onload = () => {
      setImageUrl(url);
      setLoading(false);
    };
    
    img.onerror = () => {
      console.warn(`Failed to load image for ${card.name}`);
      setError(true);
      setLoading(false);
    };
    
    // Trigger image load
    img.src = url;
  }, [card, size]);
  
  if (loading) {
    return (
      <div className={`card-image card-image-${size} loading`}>
        <div className="spinner">⏳</div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className={`card-image card-image-${size} error`}>
        <div className="no-image">No Image</div>
      </div>
    );
  }
  
  return (
    <img
      src={imageUrl}
      alt={card.name}
      className={`card-image card-image-${size}`}
      loading="lazy"  // Lazy load images
    />
  );
};
```

### Browser Cache Strategy
```
Browser HTTP Cache:
  Cache-Control: max-age=31536000 (1 year)
  ETag: Version control
  
Scryfall images are stable:
  - Same image URL for same card (across sets, printings)
  - Can be cached indefinitely
  - Browser will use cached copy if available
```

### LocalStorage for Metadata
```javascript
// Remember which images we've loaded
const cardImageCache = {
  "lightning_bolt": {
    url: "https://cards.scryfall.io/normal/front/...",
    timestamp: Date.now(),
    loaded: true
  }
};

localStorage.setItem('cardImageCache', JSON.stringify(cardImageCache));
```

---

# PART 3: LAZY LOADING STRATEGY (Core Innovation)

## Problem: Don't Load All 20,000 Cards at Startup

**Bad Approach**:
```
Server starts → Download 20,000 cards from Scryfall
              → Store in database
              → Takes 30-60 seconds
              → Wastes storage if cards not used
```

**Good Approach (Lazy Loading)**:
```
Server starts → Database empty (or minimal)
User loads Deck → Check: Are these cards in DB?
                → NO: Fetch from Scryfall NOW
                → Store in DB for future
                → Display to user
Next user loads same Deck → Cards already in DB (instant)
```

## Implementation Pattern

### Step 1: User Loads Deckliste

```
POST /api/decks
{
  "deck_name": "My Burn Deck",
  "cards": [
    {"name": "Lightning Bolt", "qty": 4},
    {"name": "Counterspell", "qty": 2},
    {"name": "Island", "qty": 18}
  ]
}
```

### Step 2: Server Checks DB

```python
@app.post("/api/decks")
def create_deck(deck_data):
    card_ids_needed = []
    
    for card_name in deck_data.cards:
        # Check: Is this card in database?
        card = db.query(Card).filter_by(name=card_name).first()
        
        if card is None:
            # NO: Need to fetch from Scryfall
            card_ids_needed.append(card_name)
        else:
            # YES: Already in DB, use it
            pass
    
    if card_ids_needed:
        # Fetch missing cards from Scryfall
        fetched_cards = fetch_from_scryfall(card_ids_needed)
        
        # Store in database
        for card_data in fetched_cards:
            card = Card(
                name=card_data['name'],
                mana_cost=card_data['mana_cost'],
                image_uri_small=card_data['image_uris']['small'],
                image_uri_normal=card_data['image_uris']['normal'],
                image_uri_large=card_data['image_uris']['large'],
                type_line=card_data['type_line'],
                oracle_text=card_data['oracle_text'],
                # ... other fields
                last_updated=datetime.now()
            )
            db.add(card)
        
        db.commit()
    
    # Now all cards are in DB, create deck
    deck = create_deck_in_db(deck_data)
    
    return {"deck_id": deck.id, "status": "created"}
```

### Step 3: Return to Client with Images

```json
{
  "status": "success",
  "deck_id": "deck_123",
  "cards": [
    {
      "name": "Lightning Bolt",
      "qty": 4,
      "mana_cost": "{R}",
      "type_line": "Instant",
      "image_uri": "https://cards.scryfall.io/normal/front/...",
      "oracle_text": "Deal 3 damage..."
    },
    ...
  ]
}
```

### Step 4: Display to User

Client renders cards with images loaded.

### Step 5: Next User (Fast)

User 2 loads same deck:
```
Server checks DB:
  ✓ Lightning Bolt already loaded
  ✓ Counterspell already loaded
  ✓ Island already loaded
  
Returns immediately (no Scryfall API call)
```

## Database Schema for Lazy Loading

### Cards Table (Progressive Loading)

```sql
CREATE TABLE cards (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    scryfall_id VARCHAR(255) UNIQUE,
    
    -- When was this loaded?
    loaded_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    
    -- Card Data (Lazy loaded from Scryfall)
    mana_cost VARCHAR(50),
    color_identity VARCHAR(10),
    type_line VARCHAR(255),
    oracle_text TEXT,
    power INT,
    toughness INT,
    
    -- Image URLs (Primary: Scryfall)
    image_uri_small VARCHAR(500),
    image_uri_normal VARCHAR(500),
    image_uri_large VARCHAR(500),
    image_uri_png VARCHAR(500),
    
    -- Cached Metadata (from Scryfall)
    set_code VARCHAR(10),
    rarity VARCHAR(20),
    is_legendary BOOLEAN,
    is_land BOOLEAN,
    is_creature BOOLEAN,
    
    -- Indexing for fast lookup
    INDEX idx_name (name),
    INDEX idx_scryfall_id (scryfall_id),
    INDEX idx_loaded (loaded_at)
);
```

### Decks Table (References Lazy-Loaded Cards)

```sql
CREATE TABLE decks (
    id UUID PRIMARY KEY,
    user_id UUID,
    deck_name VARCHAR(255),
    commander_id UUID REFERENCES cards(id),
    created_at TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_user (user_id)
);

CREATE TABLE deck_cards (
    id UUID PRIMARY KEY,
    deck_id UUID REFERENCES decks(id),
    card_id UUID REFERENCES cards(id),
    quantity INT,
    
    INDEX idx_deck (deck_id),
    INDEX idx_card (card_id)
);
```

## Performance Implications

### Initial Load (First User with New Deck)
```
Time: ~3-5 seconds
  - Parse deckliste: 100ms
  - Check DB: 50ms
  - Fetch from Scryfall: 2-4 seconds (depends on network)
  - Store in DB: 200ms
  - Return to client: 100ms

Once stored: Subsequent users see instant response
```

### Subsequent Loads (Same Deck)
```
Time: ~200-500ms
  - Parse deckliste: 100ms
  - Query DB: 50ms (indexed lookups, very fast)
  - Return to client: 100ms
  - Fetch images (client-side, parallel): 1-2 seconds

But API call is fast!
Images load in background while UI ready
```

### Scaling
```
After 1 month with 100 users:
  - Maybe 1000-2000 unique cards loaded
  - Database: ~500MB (manageable)
  - Queries: Instant (indexed)
  - Scryfall API calls: Minimal (only new cards)

vs. Pre-loading all 20K:
  - Database: 2-3GB
  - Slower queries
  - Wasted storage
```

---

# PART 4: IMAGE RENDERING IN HAND UI

## Updated CardInHand Component

```jsx
// CardInHand.jsx
import { CardImage } from './CardImage';

export const CardInHand = ({ card, legalActions, onCardClick }) => {
  const [showMenu, setShowMenu] = useState(false);
  
  const cardActions = legalActions.filter(
    action => action.card_id === card.id
  );
  
  const handleCardClick = () => {
    if (cardActions.length === 0) {
      alert(`${card.name}: No legal actions`);
      return;
    }
    setShowMenu(!showMenu);
  };
  
  return (
    <div className="card-in-hand">
      {/* Card Image (Lazy Loaded) */}
      <div
        className={`card-display ${cardActions.length > 0 ? 'clickable' : 'disabled'}`}
        onClick={handleCardClick}
      >
        <CardImage
          card={card}
          size="small"  // Use small (65×90px) for hand view
        />
      </div>
      
      {/* Card Details (Text Fallback) */}
      <div className="card-details">
        <div className="card-name">{card.name}</div>
        <div className="card-cost">
          {card.is_land ? `Tap: ${card.mana_produces}` : `${card.mana_cost}`}
        </div>
      </div>
      
      {/* Action Menu */}
      {showMenu && (
        <div className="action-menu">
          {cardActions.map(action => (
            <div
              key={action.id}
              className="action-option"
              onClick={() => onActionSelected(action)}
            >
              {getActionLabel(action)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
```

## Hand Layout with Images

```
┌─────────────────────────────────────────────────────────┐
│ YOUR HAND (7 cards)                                     │
│                                                          │
│  [Image] [Image] [Image] [Image] [Image] [Image] [I...] │
│  Island  Mountain Lightning Counterspell Counterspell │
│   Tap:U  Tap:R   Cost:1R    Cost:2U      Cost:2U     │
│   [▼]    [▼]     [CAST▼]    [CAST▼]      [CAST▼]    │
│                                                          │
│ Click card to see options                              │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Expanded Card View with Full Image

```
┌───────────────────────────────────────────────────────┐
│ CARD DETAILS: Lightning Bolt                          │
│                                                        │
│ ┌─────────────────────────────────────────────────┐  │
│ │                                                 │  │
│ │    [Full Card Image - 250-350px wide]          │  │
│ │                                                 │  │
│ │    Lightning Bolt (Instant)                    │  │
│ │    Cost: 1R                                    │  │
│ │                                                 │  │
│ │    Deal 3 damage to target creature or player │  │
│ │                                                 │  │
│ │    [CAST ▼] [Details] [Examine]               │  │
│ │                                                 │  │
│ └─────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────┘
```

---

# PART 5: ON-BATTLEFIELD CARD DISPLAY

## Creature on Battlefield

```
┌────────────────────┐
│  [Card Image]      │  ← From card.image_uri_normal
│                    │
│  Grizzly Bear      │
│  (2/2, untapped)   │
│                    │
│  [TAP] [⚔️] [MENU▼] │
└────────────────────┘
```

## Land on Battlefield

```
┌────────────────────┐
│  [Card Image]      │  ← From card.image_uri_normal
│                    │
│  Island            │
│  (tapped)          │
│                    │
│  [UNTAP] [MENU▼]   │
└────────────────────┘
```

---

# PART 6: IMAGE PERFORMANCE OPTIMIZATION

## Lazy Loading Images in React

```jsx
// Use native HTML lazy loading
<img
  src={imageUrl}
  alt={card.name}
  loading="lazy"  // ← Browser handles lazy loading
/>
```

## Serve Images via CDN (Optional, Later)

```
Future enhancement (Phase 8+):
  Cache Scryfall images on own CDN
  Serve from edge location
  Faster downloads for users worldwide
  
For now: Direct Scryfall URLs work fine
```

## Image Prefetching (Advanced)

```jsx
// Prefetch images for cards likely to be played
useEffect(() => {
  // When game loads, prefetch images for hand cards
  hand.forEach(card => {
    const link = document.createElement('link');
    link.rel = 'prefetch';
    link.href = card.image_uri_normal;
    document.head.appendChild(link);
  });
}, [hand]);
```

---

# PART 7: DEALING WITH IMAGE FAILURES

## Fallback Strategy

```jsx
export const CardImage = ({ card, size = 'normal' }) => {
  const [imageUrl, setImageUrl] = useState(null);
  const [error, setError] = useState(false);
  
  const handleImageError = () => {
    console.error(`Image failed for ${card.name}`);
    setError(true);
  };
  
  if (error) {
    // Show text-based card representation
    return (
      <div className="card-image-fallback">
        <div className="card-name">{card.name}</div>
        <div className="card-type">{card.type_line}</div>
        <div className="card-cost">{card.mana_cost}</div>
      </div>
    );
  }
  
  return (
    <img
      src={imageUrl}
      alt={card.name}
      onError={handleImageError}
    />
  );
};
```

## No Internet / Offline Mode

```
If Scryfall is unreachable:
  - Load cached images from localStorage (if available)
  - Fall back to text display
  - Show warning: "Images not available (offline)"
  - Game still playable with text-only cards
```

---

# PART 8: DATABASE UPDATES & MAINTENANCE

## Update Card Data (When Scryfall Changes)

```python
# Periodic task to refresh card data
def refresh_card_data(card_id):
    """Update card info from Scryfall (if changed)"""
    
    card = db.query(Card).filter_by(id=card_id).first()
    
    # Fetch latest from Scryfall
    scryfall_data = fetch_scryfall(card.name)
    
    # Check if anything changed
    if card.last_updated < datetime.now() - timedelta(days=30):
        # Update every 30 days (in case of image changes)
        card.image_uri_normal = scryfall_data['image_uris']['normal']
        card.last_updated = datetime.now()
        db.commit()

# Run periodically (e.g., once per week)
@scheduler.scheduled_job('cron', day_of_week='sun', hour=2)
def refresh_all_cards():
    cards = db.query(Card).all()
    for card in cards:
        refresh_card_data(card.id)
```

---

# PART 9: REVISED PHASE 1 (with Graphics & Lazy Loading)

## Phase 1: Data Layer + API + Graphics (Weeks 1-2)

### Server-Side Changes
```
✓ Card Database schema (with image URLs, loaded_at timestamp)
✓ Lazy loading logic (fetch from Scryfall on first use)
✓ Store image URLs in database
✓ Scryfall API integration (fetch on demand)
✓ Deckliste parser (extract card names)
✓ Card validator (check: does card exist in Scryfall?)
✓ Error handling (card not found, Scryfall unreachable, etc.)
```

### Client-Side Changes
```
✓ CardImage component (lazy load images, handle errors)
✓ Card display with images (in hand view)
✓ Fallback to text if image unavailable
✓ Browser caching strategy
✓ Image performance optimization
```

### Deliverables
```
✓ Server fetches/stores card images on first deck load
✓ Client displays card images in UI
✓ Lazy loading works (not all cards pre-loaded)
✓ Performance: First deck ~3-5 sec, subsequent decks ~200ms
✓ Images cached (browser + server)
```

---

# PART 10: COMPLETE FLOW: Load Deck with Images

```
STEP 1: User clicks "Create Deck"
        Input: "4x Lightning Bolt, 2x Counterspell, ..."

STEP 2: Client sends to server
        POST /api/decks {cards: [...]]}

STEP 3: Server processes deckliste
        - Parse card names
        - Check: Are these in database?

STEP 4: Server fetches missing cards
        For each card not in DB:
          - Query Scryfall API
          - Get: mana_cost, type, image_uri, oracle_text, etc.
          - Store in database

STEP 5: Server returns deck with card data
        {
          "deck_id": "deck_123",
          "cards": [
            {
              "name": "Lightning Bolt",
              "image_uri": "https://cards.scryfall.io/...",
              "type": "Instant",
              "mana_cost": "1R",
              ...
            },
            ...
          ]
        }

STEP 6: Client renders deck
        For each card:
          - <CardImage src={image_uri} />
          - Images load lazily (browser handles)
          - Fallback to text if image fails

STEP 7: Display to user
        Hand shows cards with images
        User can click card to see actions
        Images load in background (non-blocking)

STEP 8: Later sessions (same cards)
        Database has cards already
        No Scryfall API calls
        Instant response
```

---

# CONCLUSION

**Key Points**:
1. ✅ Card images displayed from Scryfall URLs
2. ✅ Lazy loading: Cards loaded on-demand (not pre-loaded)
3. ✅ Storage efficient: Only store cards actually used
4. ✅ Performance: First load ~3-5 sec, subsequent <1 sec
5. ✅ Scalable: Database grows slowly (only used cards)
6. ✅ Resilient: Fallback to text if images unavailable

**This replaces**: "2000 card cache pre-loaded at startup"
**With**: "On-demand card loading, images from Scryfall, lazy rendering"
