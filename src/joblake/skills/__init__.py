"""Versioned, conservative skill normalization. Never infer requirements."""
import json
import unicodedata
from importlib.resources import files

VERSION = '2026-10-02.1'


def token(value):
    return ' '.join(unicodedata.normalize('NFC', value).lower().split())


def catalogue():
    return json.loads(files(__package__).joinpath('catalogue.json').read_text(encoding='utf-8'))


def normalize(required, preferred, status='succeeded'):
    if status != 'succeeded':
        return [], [], []
    aliases = {token(alias): row['key'] for row in catalogue()
               for alias in [row['label'], *row['aliases']]}
    def keys(values):
        return {aliases[token(v)] for v in values or [] if token(v) in aliases}
    req, pref = keys(required), keys(preferred)
    unknown = sorted({v for v in (required or []) + (preferred or []) if token(v) not in aliases})
    return sorted(req), sorted(pref - req), unknown
