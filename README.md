# MEMORA

**Personal AI Knowledge & Productivity Agent**

MEMORA is an individual MCA 3rd-semester project planned as a web application for personal knowledge and productivity. Its future goals include working with a user's documents, answering questions grounded in their content, and supporting user-controlled memory and productivity. Those features are roadmap items, not implemented functionality.

## Technology stack

- **Frontend:** React, Vite, JavaScript, HTML5, and CSS3
- **Backend:** Python 3.12, FastAPI, and Uvicorn
- **Database:** PostgreSQL, SQLAlchemy 2.x, Alembic, and the psycopg 3 binary driver
- **Semantic search:** pgvector and local Sentence Transformers (`all-MiniLM-L6-v2`)
- **Authentication:** Argon2 password hashing via `pwdlib`, signed access tokens via PyJWT
- **Settings:** `pydantic-settings`, loaded from the backend-local `.env`
- **Testing:** Pytest, FastAPI TestClient, and an isolated in-memory SQLite test database
- **Later phases:** Gemini API (optional Ollama), grounded answer generation, memory, and productivity workflows

The project runs natively on Windows. Docker and container-based tooling are not used.

## Project structure

```text
MEMORA/
├── frontend/
│   └── src/
│       ├── api/          # Centralized API client
│       ├── auth/         # In-memory auth state and protected route
│       ├── components/   # Shared authentication layout
│       └── pages/        # Login, registration, dashboard, and documents
├── backend/
│   ├── app/
│   │   ├── api/          # Authentication, document, and semantic search routes
│   │   ├── core/         # Settings and password/JWT security
│   │   ├── db/           # SQLAlchemy base, engine, and session dependency
│   │   ├── models/       # User, document, and vector chunk models
│   │   ├── schemas/      # Request and safe response schemas
│   │   └── services/     # Extraction, chunking, embeddings, and search
│   ├── alembic/          # Reviewed database migrations
│   ├── storage/          # Private, ignored uploaded files
│   ├── tests/            # Isolated authentication, document, indexing, and search tests
│   ├── .env.example
│   └── requirements-dev.txt
├── docs/
├── .gitignore
└── README.md
```

The root `.gitignore` excludes local environment files, Python virtual environments, and frontend build/dependency output. Keep real credentials in `backend/.env`; never commit or share that file.

## Local environment configuration

The application loads `backend/.env` from its absolute location, regardless of the terminal's working directory. Do not overwrite an existing `.env`. If creating one for a fresh checkout, copy `backend/.env.example` and edit it locally.

Required/optional settings:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL SQLAlchemy URL, using the `postgresql+psycopg` driver |
| `APP_ENV` | Application environment label (defaults to `development`) |
| `JWT_SECRET_KEY` | Local, randomly generated signing key; at least 32 bytes |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime in minutes (default `30`, maximum `1440`) |
| `FRONTEND_ORIGIN` | Single permitted browser origin for CORS (default `http://localhost:5173`) |
| `DOCUMENT_STORAGE_DIR` | Private upload storage directory (default `backend/storage/documents`) |
| `DOCUMENT_MAX_UPLOAD_SIZE_MB` | Maximum uploaded file size in MiB (default `10`) |
| `DOCUMENT_MAX_EXTRACTED_TEXT_CHARS` | Maximum extracted text per file (default `1000000`) |
| `DOCUMENT_CHUNK_SIZE_CHARS` | Character-based target for deterministic text chunks (default `2000`) |
| `DOCUMENT_CHUNK_OVERLAP_CHARS` | Character-based chunk overlap (default `400`) |
| `EMBEDDING_MODEL_NAME` | Local Sentence Transformers model (default `sentence-transformers/all-MiniLM-L6-v2`) |
| `EMBEDDING_BATCH_SIZE` | CPU embedding batch size (default `32`) |
| `SEARCH_MINIMUM_SIMILARITY` | Inclusive cosine-similarity floor for results (default `0.0`, valid range `-1.0` to `1.0`) |

If `JWT_SECRET_KEY` is absent, login/token verification return a safe configuration error; no signing key is hardcoded. Generate a key locally and append it to the existing `.env` without printing it or replacing another setting:

```powershell
cd "E:\memora project\backend"
$envPath = (Resolve-Path .\.env).Path
if (Select-String -Path $envPath -Pattern '^JWT_SECRET_KEY=' -Quiet) {
    throw 'JWT_SECRET_KEY is already set. Do not replace it.'
}
$jwtSecret = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))" | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($jwtSecret)) {
    throw 'Could not generate the local JWT key.'
}
[System.IO.File]::AppendAllText($envPath, "`r`nJWT_SECRET_KEY=$jwtSecret`r`n", [System.Text.UTF8Encoding]::new($false))
$jwtSecret = $null
```

This command keeps the generated key in a PowerShell variable and writes it directly to the ignored `.env`; it does not echo the key. Do not run `Get-Content .env`, paste the key into chat, or add it to source control. If the local PostgreSQL password contains reserved URL characters, percent-encode those characters in `DATABASE_URL`.

## Database migrations

Alembic uses the URL from `backend/.env` and the application's SQLAlchemy metadata. A **migration** is a version-controlled script that describes a schema change; the **database schema** is the set of objects currently present in PostgreSQL. The document-indexing migration adds indexing status only. The vector migration creates the chunk/vector table and indexes, and verifies that pgvector is already installed before changing the schema. These migrations do not drop or recreate existing application data.

From a PowerShell terminal:

```powershell
cd "E:\memora project\backend"
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current
```

For future model changes, generate and review a migration before applying it:

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe schema change"
```

Do not apply autogenerated operations until you have confirmed they affect only the intended schema.

The additive indexing-status migration can be applied while pgvector is being set up:

```powershell
.\.venv\Scripts\alembic.exe upgrade 9a2d1140b6e3
```

The vector migration does not install PostgreSQL extensions. On Windows, install a pgvector build compatible with the local PostgreSQL major version using the [official pgvector Windows instructions](https://github.com/pgvector/pgvector#windows). The extension files must be installed into that PostgreSQL server's own `lib` and `share/extension` directories. Then, using a database role with permission to create extensions, connect to the existing `memora` database and run:

```sql
CREATE EXTENSION vector;
```

Check availability without modifying the database:

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name = 'vector';
```

Only after pgvector is installed and enabled in `memora`, run `.\.venv\Scripts\alembic.exe upgrade head`. The vector migration stops before schema changes if it cannot find the extension. Do not drop or recreate the database to install pgvector.

## Authentication API

The backend stores normalized, case-insensitive email addresses and Argon2 password hashes. Registration requires a password of 8–128 characters. User endpoints return safe profile schemas that omit password data. Login issues an HS256 JWT with a UUID `sub`, `iat`, and `exp`; protected endpoints validate those claims, load the user from the database, and reject inactive accounts.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/auth/register` | Create an account; returns a safe profile |
| `POST` | `/api/auth/login` | Verify credentials and return a bearer access token |
| `GET` | `/api/auth/me` | Return the active user profile; requires `Authorization: Bearer <token>` |
| `GET` | `/api/health` | Check API availability without depending on PostgreSQL |
| `GET` | `/api/health/db` | Run a lightweight database health check |

Duplicate email registration returns HTTP 409. Login uses the same HTTP 401 message for unknown emails and incorrect passwords. Missing or invalid bearer tokens return HTTP 401 with a `WWW-Authenticate: Bearer` header; inactive accounts are rejected.

The React client keeps access tokens in memory only. Refreshing the browser clears the session and requires signing in again; protected routes verify `/api/auth/me` before showing the dashboard. Sign out clears the browser's in-memory token. As access tokens are stateless, a signed-out token is not revoked server-side and remains valid until it expires. HttpOnly-cookie sessions, token revocation, refresh tokens, email verification, password reset, and MFA are deferred.

The backend allows CORS only for the configured `FRONTEND_ORIGIN` (one origin). The frontend calls the API through Vite's local `/api` proxy.

## Private document management

Signed-in users can upload PDF, DOCX, and UTF-8 TXT files up to **10 MiB** per file. The backend validates the extension, media type, and file contents, then stores a UUID-named file under the authenticated user's private directory. By default, files are stored at `backend/storage/documents/<user-id>/`, outside Vite's public directory and excluded from Git. The stored filename and filesystem path are not returned by the API.

PyMuPDF extracts PDF text; `python-docx` extracts DOCX paragraphs and tables; TXT uses strict UTF-8 decoding with BOM support. Extracted text is normalized and capped at one million characters per file. Scanned/image-only PDFs do not receive OCR. Uploaded documents and text remain local; neither document content nor search queries are sent to a hosted embedding API.

All document routes require an active-user bearer token. Queries are scoped to the current user; another user's document IDs return 404.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/documents/upload` | Upload and extract one PDF, DOCX, or TXT document (`multipart/form-data`, field `file`) |
| `GET` | `/api/documents` | List the current user's safe document metadata; supports `limit` and `offset` |
| `GET` | `/api/documents/{document_id}` | Read owned document metadata and processing status |
| `GET` | `/api/documents/{document_id}/content` | Read extracted text for an owned document |
| `POST` | `/api/documents/{document_id}/reindex` | Rebuild owned document chunks and embeddings |
| `DELETE` | `/api/documents/{document_id}` | Delete an owned document and its stored file |
| `POST` | `/api/search` | Search current user's indexed passages by semantic similarity |

Uploads are saved and extracted even when embedding or pgvector setup is unavailable; their separate indexing status is marked failed with a safe setup message. The Documents page shows indexing state and offers a retry action. Existing documents are not indexed automatically. Use the authenticated reindex endpoint after vector storage is configured. Deleting a document also removes its chunks.

## Local chunking and semantic search

Text is split deterministically by paragraph with a configurable character-based target (`DOCUMENT_CHUNK_SIZE_CHARS`, default 2,000) and overlap (`DOCUMENT_CHUNK_OVERLAP_CHARS`, default 400). This is an approximation rather than model-token counting; word boundaries are preserved. Extractors do not currently provide page ranges, so search responses return `null` page metadata rather than guessing.

The local model defaults to `sentence-transformers/all-MiniLM-L6-v2`, producing 384-dimensional vectors. Vectors are normalized and ranked using cosine similarity (`1 - pgvector cosine distance`). `SEARCH_MINIMUM_SIMILARITY` filters results inclusively before the top-k limit; its default of `0.0` is an uncalibrated starting value, not an empirically optimal relevance threshold. Calibrate it against a labeled set of relevant and unrelated queries before treating it as a production relevance setting. Model loading is cached per process and uses CPU inference. The first use may download model weights from Hugging Face and therefore requires an internet connection; subsequent use can load from the local model cache. No GPU is required. Changing to a model with a different vector dimension requires a reviewed database migration and reindexing plan.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/search` | Authenticated semantic search; request `{"query":"project deadlines","limit":5}` (`limit` 1–10) |
| `POST` | `/api/documents/{document_id}/reindex` | Authenticated, owner-only reindex; replaces the owned document's chunk set transactionally |

Search responses include each document filename, chunk identifier/index, passage, optional page range, and cosine similarity in the range used by the vector metric. They also include `indexed_chunk_count` (the number of the current user's completed-document chunks considered) and the active `minimum_similarity`. The UI distinguishes an empty indexed corpus from indexed passages that did not meet the threshold. The UI labels each returned score explicitly. All vector queries are filtered by authenticated user ID. Semantic retrieval is implemented; LLM answer generation, RAG prompting, OCR, memory, and autonomous actions are not.

## Install dependencies

Use the existing Python virtual environment:

```powershell
cd "E:\memora project\backend"
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

This installs FastAPI, SQLAlchemy, Alembic, `psycopg[binary]`, `pydantic-settings`, `email-validator`, `pwdlib[argon2]`, PyJWT, PyMuPDF, `python-docx`, `python-multipart`, pgvector's SQLAlchemy integration, Sentence Transformers with its CPU PyTorch runtime, and test tools. The initial local model download occurs on first indexing/search use and may require an internet connection. The frontend dependencies, including React Router, are installed with `npm.cmd install`.

## Run locally on Windows

Open two VS Code PowerShell terminals. PostgreSQL must already be installed, running, and configured in `backend/.env`. Existing upload/extraction remains available with indexing marked failed until pgvector and its migration are ready. Semantic indexing and search require the vector migration and local model.

Backend:

```powershell
cd "E:\memora project\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Frontend:

```powershell
cd "E:\memora project\frontend"
npm.cmd install
npm.cmd run dev
```

Open the local Vite URL (usually `http://localhost:5173`). The app redirects unauthenticated visitors to sign-in; account creation is available from the registration link. API documentation is at `http://127.0.0.1:8000/docs`.

## Tests and checks

Backend API tests create an isolated in-memory SQLite database per test. They do not connect to, reset, or modify the PostgreSQL development database:

```powershell
cd "E:\memora project\backend"
.\.venv\Scripts\python.exe -m pytest .\tests -q
.\.venv\Scripts\python.exe -m pip check
```

Build the frontend:

```powershell
cd "E:\memora project\frontend"
npm.cmd run build
```

The tests cover authentication, document upload/extraction and ownership, deterministic chunking, mocked embedding validation, indexing/reindexing behavior, and user-scoped semantic search. Tests use temporary storage and an in-memory SQLite database; they do not alter the local PostgreSQL database. They do not require pgvector or download the real model.

## High-level roadmap

1. Workspace preparation and documentation.
2. React/Vite and FastAPI foundation.
3. PostgreSQL, migrations, user authentication, and private document upload/text extraction.
4. Local chunking, embeddings, and semantic retrieval.
5. Grounded answer generation and user-controlled memory.
6. Validated productivity actions and project documentation.

Only the features described as implemented above are currently available.
