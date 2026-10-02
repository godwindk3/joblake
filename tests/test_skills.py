import unittest
from joblake.skills import catalogue, normalize, token


class SkillTests(unittest.TestCase):
    def test_aliases_and_separation(self):
        req, pref, unknown = normalize(['Postgres', ' PostgreSQL ', 'C++', 'C#', 'C', 'Java'], ['JS', 'Postgres', 'React Native', 'ReactJS', 'vague skill'])
        self.assertEqual(req, ['c', 'cplusplus', 'csharp', 'java', 'postgresql'])
        self.assertEqual(pref, ['javascript', 'react', 'react-native'])
        self.assertEqual(unknown, ['vague skill'])

    def test_null_and_stale(self):
        self.assertEqual(normalize(None, None), ([], [], []))
        self.assertEqual(normalize(['SQL'], ['Python'], 'failed'), ([], [], []))
        self.assertEqual(normalize(['Tiếng Anh'], ['English']), (['english'], [], []))

    def test_unique_keys_and_aliases(self):
        rows = catalogue()
        self.assertEqual(len(rows), len({r['key'] for r in rows}))
        aliases = {}
        for row in rows:
            for value in [row['label'], *row['aliases']]:
                self.assertIn(aliases.get(token(value)), (None, row['key']))
                aliases[token(value)] = row['key']
