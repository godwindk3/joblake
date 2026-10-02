"""Content validity is independent of a worker's date/source selection policy."""

CURRENT_CONTENT = """
SELECT r.id AS parse_result_id, p.id AS source_posting_id,
       core.enrichment_hash(r) AS input_hash, core.enrichment_input(r) AS input_payload,
       r.title, s.code AS source, p.first_seen_at, r.posted_at, r.fetched_at
FROM core.job_parse_results r
JOIN core.source_job_postings p ON p.id=r.source_posting_id
JOIN ref.sources s ON s.id=p.source_id
JOIN crawl_state.jobs j ON j.id=p.crawler_job_id
WHERE r.is_current AND r.quality_status IN ('accepted','partial')
  AND j.listing_status='active'
"""
