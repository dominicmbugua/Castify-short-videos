# Castify Shorts Pipeline — Automated Landscape Video Shorts

An aautomated pipeline for converting landscape videos into vertical shorts (9:16) with intelligent clip selection, formatting, and delivery to Google Drive.

**Status**: Proof-of-Concept (v3 Design Review)  
**Design Document**: `docs/DESIGN_v3.pdf`  
**Team**: Dominic (Backend/Pipeline) + Zawadi (Frontend/Delivery)  
**Timeline**: 8 Working Days

---

## Overview

This pipeline accepts landscape videos (URL, file upload, or ZIP) via a web dashboard, automatically extracts random non-overlapping clips, formats them for vertical viewing (1080×1920), and delivers them to Google Drive with email notification.

**Key Features:**
- Random clip selection (deterministic & reproducible)
- Two vertical-formatting options: center crop or pad-to-canvas
- Idempotent processing with fencing-token based recovery
- Duplicate-safe Google Drive uploads using content hashes
- Tracked email delivery with crash-safe retry
- Partial-failure support for multi-video ZIPs

---

## Project Structure

```
castify-shorts-pipeline/
├── backend/                    # Python FastAPI + Celery
│   ├── api/                   # API endpoints
│   ├── workers/               # Celery task workers
│   ├── schemas/               # SQLAlchemy ORM models
│   ├── utils/                 # Helper functions
│   ├── main.py                # FastAPI app
│   └── requirements.txt        # Python dependencies
├── frontend/                   # React dashboard
│   ├── src/
│   ├── public/
│   └── package.json (Day 1)
├── database/
│   ├── migrations/            # Alembic migrations
│   └── schema.sql             # Postgres schema
├── config/
│   ├── development.env        # Local dev environment
│   └── production.env         # Production config
├── docs/
│   ├── DESIGN_v3.pdf          # System design
│   └── DAY1_PLAN.md           # Day 1 tasks
└── docker-compose.yml         # Local services
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose

### Backend
```bash
cd backend
pip install -r requirements.txt
```

### Frontend
```bash
cd frontend
npm install
npm start
```

### Local Services
```bash
docker-compose up -d
```

This starts Redis, PostgreSQL, and MinIO.

---

## Day 1 Deliverables

**Dominic (Backend):**
- Postgres schema + Alembic migrations
- POST /submissions endpoint
- Celery worker skeleton + fencing token logic

**Zawadi (Frontend):**
- Submission form UI
- Form → API integration
- Status page display

See `docs/DAY1_PLAN.md` for details.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn |
| Queue | Celery + Redis |
| Database | PostgreSQL + SQLAlchemy |
| Video | FFmpeg |
| Storage | S3 / MinIO |
| Drive | Google Drive API |
| Email | SendGrid / SES |
| Frontend | React |

---

## Contributing

Work in feature branches following the 8-day PoC plan:

```bash
git checkout -b day1/backend
# ... work on tasks
git commit -m "Day 1: [Task description]"
git push origin day1/backend
# Create PR for review
```

---

## License

Internal — Castify.ai
