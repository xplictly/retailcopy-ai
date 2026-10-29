# RetailCopy AI

RetailCopy AI is an end-to-end retail product content platform that turns structured catalog data into source-grounded, reviewable, and exportable product copy.

The application combines a React dashboard, FastAPI services, SQLite persistence, configurable AI providers, category-aware generation, factual validation, quality-gated regeneration, multi-agent orchestration, and a compact retrieval-augmented workflow.

## Highlights

- Import product catalogs from CSV, JSON, DummyJSON, or Open Food Facts.
- Generate titles, short descriptions, long descriptions, feature bullets, SEO metadata, and keywords.
- Support professional, friendly, premium, technical, and playful brand voices.
- Generate multiple variants and recommend the highest-scoring draft.
- Retrieve approved category examples from SQLite for style and structure guidance.
- Validate generated claims against source product attributes.
- Regenerate only failed drafts within configurable retry limits.
- Run persistent batch jobs with progress, cancellation, retries, and failure reporting.
- Search and filter products by name, brand, and category.
- Review content collectively or by product number, with bulk approval, editing, rejection, and reviewer notes.
- Export approved or complete generated content as CSV or JSON.
- Reset the complete application database from the interface or API.

## Generation Pipeline

```text
Catalog import
    |
    v
Product normalization
    |
    v
Approved-example retrieval (SQLite lexical RAG)
    |
    v
Category-aware prompt construction
    |
    v
Content generation agent
    |
    v
Factual and quality verification agent
    |
    +--> Quality gate passed --> Variant recommendation
    |
    +--> Quality gate failed --> Improvement agent feedback --> Regeneration
    |
    v
Human review and approval
    |
    v
Persistent history and CSV/JSON export
```

### Agent Roles

1. **Product Research and Normalization Agent**
   - Inspects source attributes and identifies missing fields.
   - Treats missing specifications as unknown rather than inventing values.

2. **Content Generation Agent**
   - Creates the complete product-content structure using the configured provider, category guidance, brand voice, length, and SEO settings.

3. **Quality and Factual Verification Agent**
   - Checks unsupported claims, numeric contradictions, health claims, certifications, warranties, materials, and technical assertions.
   - Scores relevance, factual consistency, readability, creativity, SEO coverage, and brand adherence.

4. **Content Improvement Agent**
   - Converts verification failures into concrete prompt feedback.
   - Re-generates selectively and within a configured retry limit.

Each generation records an agent execution trace containing missing attributes, attempts, scores, warnings, regeneration feedback, and final gate status.

## Retrieval-Augmented Generation

RetailCopy AI implements retrieval over approved descriptions stored in SQLite. For a target product, the system retrieves approved descriptions with matching category context and lexical overlap. These records are used only as style and structure references.

The prompt enforces a strict boundary:

- Retrieved examples may guide tone, formatting, and category conventions.
- Retrieved facts must not be transferred to a different product.
- Generated claims must come from the target product's structured attributes.

This is a lightweight lexical RAG implementation. It does not currently use embeddings, a vector database, semantic reranking, or citation-grounded retrieval.

## Architecture

```text
React and TypeScript Dashboard
             |
             v
   FastAPI API under /api/v1
             |
             +--> Product and catalog services
             +--> Import and export services
             +--> Generation and agent orchestration
             +--> Quality and factual validation
             +--> Persistent batch worker
             |
             v
SQLite through SQLAlchemy
             |
             v
Gemini, Groq, OpenRouter, OpenAI-compatible,
Ollama, or deterministic Demo provider
```

## Technology Stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite |
| Backend | FastAPI, Pydantic, SQLAlchemy |
| Database | SQLite with WAL mode |
| AI Providers | Gemini, Groq, OpenRouter, OpenAI-compatible APIs, Ollama, Demo |
| Data Sources | DummyJSON, Open Food Facts, CSV, JSON |
| Testing | Pytest, pytest-asyncio, HTTPX, pytest-mock |

## Prerequisites

- macOS or another environment capable of running Python and Node.js
- Python 3.12 or compatible Python 3.10+
- Node.js 18 or later
- npm

## Installation and Setup

From the project directory:

```bash
./scripts/setup.sh
cp -n .env.example .env
```

The setup script creates a Python virtual environment, installs backend dependencies, installs frontend dependencies, and runs the backend test suite.

Alternatively, configure the components manually:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd ../frontend
npm install
```

## Running the Application

Start the backend:

```bash
./scripts/start-backend.sh
```

Start the frontend in a second terminal:

```bash
./scripts/start-frontend.sh
```

The application will be available at:

- Frontend: http://127.0.0.1:5173
- API documentation: http://127.0.0.1:8000/api/docs
- Alternative API documentation: http://127.0.0.1:8000/api/redoc
- Health check: http://127.0.0.1:8000/api/health

Demo mode is enabled by default. No API key is required and generation is deterministic.

## AI Provider Configuration

Copy `.env.example` to `.env`, then configure one provider.

Example Gemini configuration:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-1.5-flash
```

Supported providers:

- `demo`: deterministic local demonstration provider
- `gemini`: Google Gemini
- `groq`: Groq-hosted models
- `openrouter`: OpenRouter-compatible models
- `openai_compatible`: OpenAI or OpenAI-compatible endpoints
- `ollama`: locally hosted Ollama models

Never commit a `.env` file or API key to the repository.

## Catalog Imports

### CSV and JSON Uploads

Template endpoints:

```text
GET /api/v1/import/templates/csv
GET /api/v1/import/templates/json
```

Upload endpoints:

```text
POST /api/v1/import/csv
POST /api/v1/import/json
```

Imported records are normalized and stored in SQLite. Duplicate records are identified by source name and external product ID.

### Public Catalogs

```text
POST /api/v1/import/dummyjson?max_records=100&page_size=30
POST /api/v1/import/open-food-facts?query=coffee&max_records=30
POST /api/v1/import/synthetic?count=55
```

Synthetic generation is available for demonstration purposes only. Production or mentor demonstrations should use publicly sourced, uploaded, or explicitly approved catalog data.

## Main API Areas

| Area | Endpoints |
| --- | --- |
| Products | `/api/v1/products`, `/api/v1/products/{id}`, `/api/v1/products/{id}/generate` |
| Descriptions and review | `/api/v1/products/{id}/descriptions`, `/api/v1/products/descriptions/{id}/review` |
| Batch jobs | `/api/v1/batch-jobs` and nested status, cancellation, retry, and result routes |
| Imports | `/api/v1/import/*` |
| Analytics | `/api/v1/analytics`, `/api/v1/categories`, `/api/v1/provider/status` |
| Export | `/api/v1/export` |
| Database reset | `/api/v1/reset?confirm=true` |

The complete interactive contract is available from the Swagger UI.

## Review and Export

The review workspace separates:

- Pending descriptions
- Approved descriptions
- Descriptions requiring editing
- Rejected descriptions
- Batch generation failures
- Product quantities and factual warnings
- Agent execution and regeneration traces
- Generated variants and quality comparisons

Reviewer actions can apply to the complete pending set or to selected product numbers. Export requests support name, brand, and category search, category filtering, product ID filtering, and approved-only output.

## Testing

Run the complete backend suite:

```bash
cd backend
.venv/bin/python -m pytest -q
```

Run the frontend production build:

```bash
cd frontend
npm run build
```

The automated suite covers validation, product APIs, imports, exports, reviews, batch processing, retries, provider behavior, and quality-related workflows.

## Project Structure

```text
backend/
  app/
    ai/               AI provider adapters and prompt construction
    api/v1/           REST routes
    db/               Database engine and initialization
    integrations/     External catalog and file import adapters
    models/           SQLAlchemy persistence models
    services/         Generation, agents, RAG, validation, quality, and exports
    workers/          Durable batch-job processing
  tests/              Unit and integration tests
frontend/
  src/
    App.tsx           Dashboard and review workspace
    api.ts            Typed API client
scripts/
  setup.sh            macOS/Linux dependency setup
  start-backend.sh    Backend launcher
  start-frontend.sh   Frontend launcher
```

## Data and Security Considerations

- SQLite is suitable for a local or demonstration deployment, not a horizontally scaled production database.
- API keys belong in environment variables and must not be placed in source code.
- Human approval is required before content is considered published.
- Quality scores and factual-rule warnings support review but do not prove factual truth.
- Public or imported source fields should be treated as evidence to validate, not as an automatically verified authority.
- No authentication layer is included in the current local demonstration application. It should not be exposed to an untrusted public network.

## Known Limitations

- Retrieval uses lexical matching rather than embeddings.
- Factual validation uses deterministic rules and quality heuristics, not a comprehensive fact database.
- Quality scoring is not an independent proof of correctness.
- Batch jobs are stored locally and are not distributed across separate worker processes.
- Live-provider quality and availability depend on the configured API provider and network.
- The database reset action permanently deletes local catalog, review, description, and batch data.

## Contributors

- [mrkeerthics24-dot](https://github.com/mrkeerthics24-dot)
- [poojamagaji](https://github.com/poojamagaji)
- [KumarSambhavSingh](https://github.com/KumarSambhavSingh)

These accounts are repository contributors under development of the project. GitHub also credits accounts as contributors in commit statistics only when their authenticated GitHub account appears in commit authorship.

## Repository

GitHub: https://github.com/xplictly/retailcopy-ai
