import unittest
from pathlib import Path
from test_supabase_serving import ServingTests

class FiltersV2Tests(ServingTests):
 @classmethod
 def setUpClass(cls):
  super().setUpClass()
  root=Path(__file__).resolve().parents[1]
  cls.execute(cls, (root/'src/joblake/sql/serving_enrichment.sql').read_text(encoding='utf-8'))
  cls.execute(cls, (root/'src/joblake/sql/serving_search_v2.sql').read_text(encoding='utf-8'))
 def seed(self):
  self.execute("""INSERT INTO serving.sources VALUES (1,'example','Example');
   INSERT INTO serving.jobs(id,source_id,canonical_url,title,categories_raw,skills_raw,location_cities,last_seen_at,first_seen_at,
    enrichment_status,experience_min_years,experience_max_years,seniority_levels,work_mode)
   SELECT n,1,'https://example.test/'||n,'Data Engineer C++','{}','{SQL}',CASE WHEN n%2=0 THEN ARRAY['Hà Nội','Đà Nẵng'] ELSE ARRAY['Hồ Chí Minh'] END,
    now(),now()-interval '2 hours','succeeded',2,4,ARRAY['junior','middle'],'remote' FROM generate_series(1,45) n;
   UPDATE serving.jobs SET experience_min_years=0 WHERE id=1;
   UPDATE serving.jobs SET experience_min_years=NULL WHERE id=2;
   UPDATE serving.jobs SET enrichment_status='not_enriched' WHERE id=3;
   UPDATE serving.jobs SET first_seen_at=NULL WHERE id=4;
   UPDATE serving.jobs SET posted_at=now()-interval '40 days' WHERE id=5;""")
 def v2_ids(self, **kwargs):
  allowed={'p_query','p_sources','p_cities','p_experience','p_seniority','p_modes','p_days','p_sort','p_limit','p_offset'}
  assert set(kwargs)<=allowed
  args=','.join(k+'=>%s' for k in kwargs)
  return [r[0] for r in self.execute('SELECT id FROM serving.search_jobs_v2('+args+')',list(kwargs.values()))]
 def test_v2_filters(self):
  self.seed()
  self.assertEqual(self.v2_ids(p_experience='zero'),[1])
  self.assertEqual(set(self.v2_ids(p_experience='unknown')),{2,3})
  self.assertEqual(len(self.v2_ids(p_seniority=['junior','middle'],p_limit=100)),44)
  self.assertEqual(self.v2_ids(p_modes=['unknown']),[3])
  self.assertEqual(len(self.v2_ids(p_modes=['remote','unknown'],p_limit=100)),45)
  selected=self.v2_ids(p_query='data eng',p_cities=['Hà Nội'],p_experience='1to3',p_modes=['remote'],p_limit=100)
  self.assertTrue(selected and all(n%2==0 and n!=2 for n in selected))
  self.assertEqual(len(selected),len(set(selected)))
 def test_v2_dates_and_pages(self):
  self.seed()
  ids=self.v2_ids(p_days=1,p_sort='newest',p_limit=100)
  self.assertEqual(len(ids),43)
  self.assertNotIn(4,ids); self.assertNotIn(5,ids)
  self.assertEqual(len(self.v2_ids(p_limit=100)),45)
  a=self.v2_ids(p_limit=20); b=self.v2_ids(p_limit=20,p_offset=20)
  self.assertFalse(set(a)&set(b));self.assertEqual(len(a+b),40)
  for q in ['data eng','C++','data engineer']:
   self.assertEqual(len(self.v2_ids(p_query=q,p_limit=100)),45)
 def test_v2_validation(self):
  for kwargs in [{'p_days':5},{'p_experience':'bad'},{'p_limit':101},{'p_seniority':['bad']},{'p_modes':['remote',None]}]:
   with self.assertRaises(Exception): self.v2_ids(**kwargs)
 def test_v2_first_seen_survives_repeat_sync(self):
  from joblake.supabase_sync import sync
  self.assertEqual(sync(),0)
  before=self.execute('SELECT id,first_seen_at FROM serving.jobs ORDER BY id')
  self.assertTrue(all(row[1] is not None for row in before))
  self.execute("UPDATE crawl_state.jobs SET last_seen_at=now()")
  self.assertEqual(sync(),0)
  self.assertEqual(self.execute('SELECT id,first_seen_at FROM serving.jobs ORDER BY id'),before)
  self.assertEqual(sync(verify_only=True),0)

if __name__=='__main__': unittest.main()

