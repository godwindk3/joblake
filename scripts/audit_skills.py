"""Read-only local audit. No model calls, writes to DB or remote publication."""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from joblake.skills import VERSION, normalize
from joblake.supabase_sync import JOBS_QUERY, configure


def main():
    load_dotenv()
    configure()
    sources = defaultdict(Counter)
    unmapped = Counter()
    samples = defaultdict(list)
    with psycopg.connect(os.environ['LOCAL_DATABASE_URL'], connect_timeout=5) as c:
        c.execute('SET TRANSACTION READ ONLY')
        c.execute("SET LOCAL statement_timeout='30s'")
        rows = c.execute('''SELECT j.id,s.code,e.status,e.result
          FROM (''' + JOBS_QUERY + ''') j JOIN ref.sources s ON s.id=j.source_id
          LEFT JOIN core.job_parse_results r ON r.source_posting_id=j.id AND r.is_current
          LEFT JOIN core.current_job_enrichments e ON e.parse_result_id=r.id ORDER BY j.id''').fetchall()
        for id_, source, status, result in rows:
            counts = sources[source]
            counts['total'] += 1
            counts['enriched'] += status == 'succeeded'
            result = result if status == 'succeeded' and isinstance(result, dict) else {}
            req, pref, unknown = normalize(result.get('skills_required'), result.get('skills_preferred'), status)
            counts['extracted'] += bool(result.get('skills_required') or result.get('skills_preferred'))
            counts['normalized'] += bool(req or pref)
            counts['unmapped_postings'] += bool(unknown)
            unmapped.update(unknown)
            if status == 'succeeded' and len(samples[source]) < 10:
                samples[source].append({'posting_id': id_, 'required': result.get('skills_required'),
                    'preferred': result.get('skills_preferred'), 'keys_required': req, 'keys_preferred': pref,
                    'unmapped': unknown, 'evidence': (result.get('evidence') or {}).get('skills_required', [])})
    report = {'at': datetime.now(timezone.utc).isoformat(), 'version': VERSION,
              'sources': dict(sources), 'unmapped': unmapped.most_common(100), 'samples': dict(samples)}
    output = Path('output/skills-audit.json')
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'at': report['at'], 'sources': report['sources'], 'sample_counts': {s:len(v) for s,v in samples.items()},
                      'top_unmapped': report['unmapped'][:25], 'report': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
