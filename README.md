# MTG Deck Analyzer

A Magic: The Gathering deck analyzer and rules-driven game engine.

## Project Structure

```
backend/    Python backend (data layer, rules engine, effects, services)
frontend/   React frontend
docs/       Architecture, requirements, and implementation specs
```

See [docs/03_ARCHITECTURE_AND_BUILDPLAN.md](docs/03_ARCHITECTURE_AND_BUILDPLAN.md) for the overall architecture and [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md) for the phased build plan.

## Backend Setup

```bash
./backend/install.sh
source backend/venv/bin/activate
pytest backend/tests/
```

## License

GPL-2.0, see [LICENSE](LICENSE).
