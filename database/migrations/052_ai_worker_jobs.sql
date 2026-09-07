-- ============================================================
-- 052: AI WORKER JOBS (Work Stream C - background runs)
-- ============================================================
-- A DB-backed claim/lease queue so an HTTP request can return EARLY and a
-- supervised worker process executes the AI run.
--
-- Why a DB queue (not FastAPI BackgroundTasks): background tasks die with
-- the request process and cannot be observed/resumed across requests or
-- processes. A claim row + lease gives at-most-once execution under
-- concurrency via FOR UPDATE SKIP LOCKED.
--
-- RLS is enabled with NO policies BY DESIGN (mirrors document_sequences):
-- only the backend service role and the worker (service key) touch this
-- table; clients read job status through the authenticated API endpoint,
-- which filters by user_id + organization_id.
-- ============================================================

CREATE TABLE IF NOT EXISTS ai.worker_jobs (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id   uuid        NOT NULL,
  user_id           uuid        NOT NULL,
  job_type          text        NOT NULL DEFAULT 'ai_execute',
  payload           jsonb       NOT NULL,
  status            text        NOT NULL DEFAULT 'QUEUED',
  claimed_by        text,
  claimed_at        timestamptz,
  lease_expires_at  timestamptz,
  result            jsonb,
  error             text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE ai.worker_jobs ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_worker_jobs_status_created
  ON ai.worker_jobs (status, created_at);

-- Claim the single oldest actionable job for this worker (SKIP LOCKED so
-- competing workers never block each other; expired leases are reclaimed).
CREATE OR REPLACE FUNCTION ai.claim_worker_job(
  p_worker       text,
  p_lease_seconds int DEFAULT 180
)
RETURNS ai.worker_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ai, public
AS $$
DECLARE
  v_job ai.worker_jobs;
BEGIN
  UPDATE ai.worker_jobs j
  SET status = 'RUNNING',
      claimed_by = p_worker,
      claimed_at = now(),
      lease_expires_at = now() + make_interval(secs => p_lease_seconds),
      updated_at = now()
  WHERE j.id = (
    SELECT id FROM ai.worker_jobs
    WHERE status = 'QUEUED'
       OR (status = 'RUNNING' AND lease_expires_at < now())
    ORDER BY created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  )
  RETURNING * INTO v_job;
  RETURN v_job;
END;
$$;

GRANT EXECUTE ON FUNCTION ai.claim_worker_job(text, int) TO service_role;
