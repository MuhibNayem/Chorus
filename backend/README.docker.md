# Backend Docker Stack

This backend stack runs:

- `backend-api` (FastAPI)
- `backend-worker` (Celery worker)
- `postgres` with `pgvector`
- `redis`
- `minio`

## Files

- `backend/Dockerfile`
- `backend/docker-compose.yml`
- `backend/.env.docker`

## Start

From the `backend/` directory:

```bash
docker compose --env-file .env.docker up --build
```

Run detached:

```bash
docker compose --env-file .env.docker up -d --build
```

## Stop

```bash
docker compose down
```

To remove volumes too:

```bash
docker compose down -v
```

## Required env

You must set:

- `MINIMAX_API_KEY`

Optional:

- `SERPER_API_KEY`
- `GOOGLE_API_KEY`
- `GOOGLE_CSE_ID`

## Ollama

The stack assumes Ollama is available outside Docker at:

```text
http://host.docker.internal:11434
```

If your Ollama host is elsewhere, update `OLLAMA_HOST` in `backend/.env.docker`.

## Exposed ports

- Backend API: `8000`
- Postgres: `5432`
- Redis: `6379`
- MinIO API: `9000`
- MinIO Console: `9001`
