# Romania Intel Agent

Monorepo containing the Python/FastAPI backend (`romania-intel-engine/`) and the
Next.js frontend (`romania-intel-frontend/`, a separate git submodule).

## Backend setup (`romania-intel-engine/`)

```bash
python3 -m venv venv
source venv/bin/activate
cd romania-intel-engine
pip install -r requirements.txt
```

## Frontend setup (`romania-intel-frontend/`)

```bash
cd romania-intel-frontend
npm install
```

See [CLAUDE.md](CLAUDE.md) for architecture details and how to run each service.
