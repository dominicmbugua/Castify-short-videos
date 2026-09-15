# Day 1 Plan — Repo Setup & Foundations

**Duration**: 1 Day  
**Parallel Work**: Dominic (Backend) | Zawadi (Frontend)  
**Goal**: Complete repo scaffold, core database schema, API skeleton, and form UI

---

## Dominic — Backend / Pipeline

### Task 1.1: Database Schema & Migrations

**Files to Create**:
- Database schema tables: Job, VideoTask, Clip, EmailDelivery
- Alembic migration setup
- SQLAlchemy ORM models

**Deliverables**:
- [ ] Postgres schema applied
- [ ] SQLAlchemy models in `backend/schemas/models.py`
- [ ] Alembic migrations working

**Estimated Time**: 1.5–2 hours

---

### Task 1.2: FastAPI App & Validation

**Files to Create**:
- `backend/api/submissions.py` — POST /submissions endpoint
- `backend/api/status.py` — GET /status/{job_id} endpoint
- `backend/utils/validation.py` — Input validation logic

**Validation Rules**:
- Email format check
- URL reachability via HEAD request
- File magic bytes validation
- ZIP safety checks

**Deliverables**:
- [ ] FastAPI app runs on localhost:8000
- [ ] POST /submissions accepts all three input types
- [ ] Valid submissions create a Job record
- [ ] GET /status/{job_id} returns current state

**Estimated Time**: 2–2.5 hours

---

### Task 1.3: Celery Worker Skeleton

**Files to Create**:
- `backend/workers/celery_app.py` — Celery configuration
- `backend/workers/claim.py` — Fencing-token task claim logic
- `backend/utils/db.py` — Database utilities

**Deliverables**:
- [ ] Celery configured to use Redis
- [ ] Worker can start without errors
- [ ] Task claim logic with fencing token

**Estimated Time**: 1.5–2 hours

---

## Zawadi — Frontend / Delivery

### Task 2.1: Submission Form UI

**Files to Create**:
- `frontend/src/components/SubmissionForm.jsx`
- `frontend/src/hooks/useForm.js`
- `frontend/src/components/FileUpload.jsx`

**Form Fields**:
1. Email address (required)
2. Video source: URL | File | ZIP
3. Clip configuration: duration min/max, max clips, vertical format

**Deliverables**:
- [ ] Form renders with all fields
- [ ] Inline validation with error messages
- [ ] File drag-and-drop support

**Estimated Time**: 2–2.5 hours

---

### Task 2.2: Form → API Integration

**Files to Modify**:
- Wire form to POST /submissions
- Handle success/error responses
- Show confirmation screen

**Deliverables**:
- [ ] Form POSTs to backend
- [ ] Success shows job_id and status URL
- [ ] Error messages display properly

**Estimated Time**: 1–1.5 hours

---

### Task 2.3: Status Page (Basic)

**Files to Create**:
- `frontend/src/pages/StatusPage.jsx`
- `frontend/src/hooks/useJobStatus.js`

**Deliverables**:
- [ ] Status page displays job state
- [ ] Polls /status endpoint every 2–3 seconds
- [ ] Shows per-video task status

**Estimated Time**: 1.5–2 hours

---

## Success Criteria

By end of Day 1:

✅ Can submit form from frontend  
✅ Backend creates Job and VideoTask in Postgres  
✅ Status page reflects queued state  
✅ Celery worker can be started  
✅ Schema is clean and indexed  
✅ Code is committed to git  

---

## Next Steps

- **Day 2**: Object storage staging, job enqueuing
- **Day 3**: Background inspection, random clip selection
- **Day 4**: Clip extraction, encoding, vertical formatting
- **Day 5**: Drive upload with deduplication
- **Day 6–8**: Recovery, email delivery, cleanup, testing
