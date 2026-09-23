"""Actual Presidio built-in EmailRecognizer and Anonymizer; no NLP model required.

This profile deliberately excludes PERSON, phone and all other entities. It
uses no custom regex, alternate test engine or dynamic runtime downloads.
"""
from importlib.metadata import version
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

import tldextract
# Pin the packaged public-suffix snapshot; no runtime fetches or user-cache writes.
tldextract.extract = tldextract.TLDExtract(cache_dir=None, suffix_list_urls=())
from presidio_analyzer.predefined_recognizers import EmailRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from app.profile import PROFILE

assert version('tldextract') == '5.3.0'
assert version('presidio-analyzer') == '2.2.360'
assert version('presidio-anonymizer') == '2.2.360'
recognizer = EmailRecognizer()
anonymizer = AnonymizerEngine()
app = FastAPI()


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(max_length=3000)
    profile_revision: Literal['presidio-email-2_2_360-psl5_3_0-v1']


@app.get('/ready')
async def ready():
    return {'profile_revision': PROFILE}


@app.post('/redact')
def redact(body: Input):
    results = recognizer.analyze(body.text, ['EMAIL_ADDRESS'], nlp_artifacts=None)
    results = [r for r in results if r.score >= 0.5]
    output = anonymizer.anonymize(body.text, results, operators={'EMAIL_ADDRESS': OperatorConfig('replace', {'new_value': '[EMAIL]'})})
    return {'text': output.text, 'profile_revision': PROFILE, 'completed': True}
