# 10. Sources & Licenses

DeckLab obtains some card data, combo data, and decklists from third
parties. These providers are not affiliated with DeckLab; their data and
services remain subject to their respective terms and rights.

## Sources used

- **Scryfall** — Card data comes from the [Scryfall API](https://scryfall.com/docs/api)
  and the Oracle card pool. Card data is cached locally; card images are
  fetched on demand, cached locally, and served by the backend. See Scryfall's
  [API guidelines for data and images](https://scryfall.com/docs/api) and
  [Terms of Service](https://scryfall.com/docs/terms).
- **Commander Spellbook** — Static deck analysis lazily downloads the
  published [combo dataset](https://json.commanderspellbook.com/variants.json.gz)
  and stores it locally for deck matching. More information:
  [Commander Spellbook](https://commanderspellbook.com/) and its
  [API schema](https://backend.commanderspellbook.com/schema/).
- **Archidekt** — When a user explicitly enters a deck to import, DeckLab
  can retrieve its decklist through Archidekt's interface. See
  [Archidekt's Terms of Use](https://archidekt.com/terms).

This list provides attribution; it does not transfer or assert a license
for content from these providers. Their respective requirements and
rights holders govern that content. DeckLab's own software is licensed
under [GPL-2.0](https://github.com/BXOrange/MTG_Deck_Analyzer/blob/main/LICENSE);
that license does not cover third-party content.

## Wizards of the Coast notice

DeckLab is unofficial Fan Content permitted under the [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.
