# MTG Deck Analyzer

A Magic: The Gathering deck analyzer and rules-driven game engine.

## Project Structure

```
backend/    Python backend (data layer, rules engine, effects, services)
frontend/   Browser client (no build step: static HTML/CSS/JS)
docs/       Architecture, requirements, and implementation specs
```

See [docs/03_ARCHITECTURE_AND_BUILDPLAN.md](docs/03_ARCHITECTURE_AND_BUILDPLAN.md) for the overall architecture and [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md) for the phased build plan.

## Backend Setup

```bash
./backend/install.sh
source backend/venv/bin/activate
pytest backend/tests/
```

## Frontend Setup

No Node/npm required yet — it's plain ES modules served as static files.

```bash
cd frontend
python3 -m http.server 8765
# open http://localhost:8765
```

See [frontend/README.md](frontend/README.md) for details.

## License

GPL-2.0, see [LICENSE](LICENSE).
