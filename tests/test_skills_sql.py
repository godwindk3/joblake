import json
from importlib.resources import files
from test_search_v2 import FiltersV2Tests
from joblake.skills import catalogue, normalize


class SkillsSQLTests(FiltersV2Tests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.execute(cls, files('joblake').joinpath('sql/serving_skills.sql').read_text(encoding='utf8'))

    def seed_skills(self):
        self.seed()
        self.execute("UPDATE serving.jobs SET skills_required='{Python,Postgres,PostgreSQL}', skills_preferred='{SQL,Postgres}'")
        self.execute("UPDATE serving.jobs SET skills_required=NULL,skills_preferred='{SQL}' WHERE id=2")

    def search(self, **kwargs):
        args=','.join(k+'=>%s' for k in kwargs)
        return [r[0] for r in self.execute('select id from serving.search_jobs_v3('+args+')',list(kwargs.values()))]

    def stats(self, **kwargs):
        args=','.join(k+'=>%s' for k in kwargs)
        return self.execute('select serving.job_statistics_v1('+args+')',list(kwargs.values()))[0][0]

    def test_skill_filter_and_count(self):
        self.seed_skills()
        self.assertEqual(len(self.search(p_skills=['python'],p_limit=100)),43)
        self.assertEqual(self.search(p_skills=['python','sql'],p_skill_match='all'),[])
        self.assertEqual(len(self.search(p_skills=['python','sql'],p_skill_match='all',p_skill_scope='all',p_limit=100)),43)
        self.assertEqual(self.stats(p_skills=['sql'],p_skill_scope='all')['total'],44)
        s=self.stats()
        self.assertEqual(s['total'],45)
        self.assertEqual(s['coverage']['normalized'],43)
        self.assertEqual(next(r['count'] for r in s['rows'] if r['kind']=='skill' and r['key']=='postgresql'),43)
        a=self.search(p_skills=['python'],p_limit=20)
        b=self.search(p_skills=['python'],p_limit=20,p_offset=20)
        self.assertEqual(len(a+b),40); self.assertFalse(set(a)&set(b))

    def test_alias_parity_and_invalidation(self):
        for r in catalogue():
            for alias in [r['label'], *r['aliases']]:
                self.assertEqual(self.execute('select serving.skill_key(%s)',[alias])[0][0],r['key'])
        self.seed_skills()
        self.execute("UPDATE serving.jobs SET enrichment_status='pending' WHERE id=1")
        self.assertNotIn(1,self.search(p_skills=['python'],p_limit=100))
        self.assertEqual(self.execute('select required_skill_keys,preferred_skill_keys from serving.jobs where id=1')[0],([],[]))

    def test_invalid_skills_and_empty(self):
        for kwargs in [dict(p_skills=['no-such-key']),dict(p_skill_match='bad'),dict(p_skill_scope='bad'),dict(p_skills=[None]),dict(p_skills=['sql']*11)]:
            with self.assertRaises(Exception): self.search(**kwargs)
            with self.assertRaises(Exception): self.stats(**kwargs)
        s=self.stats()
        self.assertEqual(s['total'],0);self.assertEqual(s['rows'],[])

    def test_v2_v3_equivalence(self):
        self.seed_skills()
        for kwargs in [dict(p_query='C++'),dict(p_query='data eng'),dict(p_modes=['unknown']),dict(p_experience='zero'),dict(p_days=7),dict(p_cities=['Hà Nội'],p_seniority=['junior']),dict(p_query='!!!')]:
            self.assertEqual(self.v2_ids(**kwargs),self.search(**kwargs))
            total=len(self.search(**kwargs,p_limit=100))
            self.assertEqual(total,self.stats(**kwargs)['total'])
