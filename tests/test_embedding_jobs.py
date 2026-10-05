from sqlalchemy import text

import app.services.embedding_jobs as embedding_jobs
from app.db.session import engine


def test_embedding_job_uses_configured_chroma_and_fails_cleanly(monkeypatch):
    """The job connects to the Chroma host/port from settings (it used to
    hardcode localhost:8001), and an unreachable Chroma marks the job
    failed instead of leaving it at status='running'."""
    connected_to = []

    def unreachable_chroma(host, port):
        connected_to.append((host, port))
        raise ConnectionError("Chroma is unreachable")

    monkeypatch.setattr(embedding_jobs.settings, "chroma_host", "chroma.internal")
    monkeypatch.setattr(embedding_jobs.settings, "chroma_port", 9100)
    monkeypatch.setattr(embedding_jobs, "SentenceTransformer", lambda name: object())
    monkeypatch.setattr(embedding_jobs.chromadb, "HttpClient", unreachable_chroma)

    job_id = embedding_jobs.create_pending_embedding_job(engine, total=1)
    try:
        embedding_jobs.run_embedding_batch(engine, job_id, representations=[])

        with engine.connect() as db:
            status, error = db.execute(
                text("SELECT status, error FROM embedding_jobs WHERE id = :id"), {"id": job_id}
            ).one()
        assert connected_to == [("chroma.internal", 9100)]
        assert status == "failed"
        assert error == "Chroma is unreachable"
    finally:
        with engine.begin() as db:
            db.execute(text("DELETE FROM embedding_jobs WHERE id = :id"), {"id": job_id})
