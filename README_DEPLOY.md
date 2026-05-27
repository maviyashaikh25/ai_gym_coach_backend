# Deployment guide

This document explains quick deployment options for the project: local Docker Compose, Render backend deployment, container images for cloud, and recommendations for managed services.

Prerequisites:
- A `GROQ_API_KEY` (set as env var).
- A PostgreSQL instance (or use the bundled `docker-compose` postgres).

Local (Docker Compose)

1. Create an `.env` file in the repo root with the following keys (replace values):

```
GROQ_API_KEY=your_groq_api_key_here
```

2. Build and start everything:

```powershell
docker compose up --build
```

- Backend will be reachable at `http://localhost:8000`
- Frontend will be reachable at `http://localhost:3000`

Notes for production
- Use a managed Postgres (Render, Railway, AWS RDS, Azure Database) and set `DATABASE_URL` to that value.
- Do NOT use `reload=True` in production; set `--reload` off in the prod uvicorn command.
- Keep `GROQ_API_KEY` and other secrets in environment variables or secret manager.
- If you need GPU/accelerated ML inference, choose hosts with GPU (GCP/AWS/OVH) and adapt containers accordingly.

Render backend
- Connect the repo to Render and either use `render.yaml` or create a new Web Service manually.
- Set these environment variables in Render:
	- `DATABASE_URL` = your Render Postgres connection string
	- `GROQ_API_KEY` = your Groq key
	- `ALLOW_ORIGINS` = your Vercel URL, for example `https://your-frontend.vercel.app`
- Render provides a `PORT` value automatically; the backend container now uses it.

Suggested cloud deployment paths
- Render / Railway / Fly / Heroku: push Docker image or connect repo and let service build. Provide `DATABASE_URL` and `GROQ_API_KEY` as secrets.
- Google Cloud Run / AWS App Runner: build container image, push to container registry, then deploy. Use Cloud SQL or managed Postgres for DB.

CI / CD
- Build and push Docker images to GitHub Container Registry or Docker Hub, then deploy.

Troubleshooting
- If `mediapipe` or `opencv` raises errors, ensure required OS libs are installed in the image (added in the provided `Dockerfile`).
