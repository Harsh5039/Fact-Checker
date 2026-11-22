"""Offline tests: the pipeline is checked with fake Gemini / search responses (no keys needed)."""
import os
import sys
import types as _t
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _stub(name, **attrs):
    mod = _t.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


try:
    import ddgs, google.genai, pypdf  # noqa: F401
except ImportError:  # allow tests to run without the heavy dependencies installed
    _stub("ddgs", DDGS=object)
    _stub("pypdf", PdfReader=object)
    g = _stub("google")
    types_mod = _stub("google.genai.types", GenerateContentConfig=lambda **k: k)
    gen = _stub("google.genai", Client=lambda api_key=None: object(), types=types_mod)
    g.genai = gen

import factcheck  # noqa: E402


class JsonParsing(unittest.TestCase):
    def test_plain_and_fenced(self):
        self.assertEqual(factcheck._json('[{"a": 1}]'), [{"a": 1}])
        self.assertEqual(factcheck._json('```json\n[{"a": 1}]\n```'), [{"a": 1}])
        self.assertEqual(factcheck._json('Here you go: {"a": 2} thanks'), {"a": 2})


class FullRun(unittest.TestCase):
    def setUp(self):
        self.orig = (factcheck.read_pdf, factcheck._ask, factcheck.search)
        factcheck.read_pdf = lambda f: "Python was released in 1995. Amazon was founded in 1994. " * 3
        factcheck.search = lambda q: [{"title": "t", "url": "https://example.org", "content": "evidence"}]

    def tearDown(self):
        factcheck.read_pdf, factcheck._ask, factcheck.search = self.orig

    def test_two_gemini_calls_and_labels(self):
        calls = []

        def fake_ask(client, system, user):
            calls.append(1)
            if len(calls) == 1:
                return ('[{"claim":"Python was released in 1995","category":"date","search_query":"python first release"},'
                        '{"claim":"Amazon was founded in 1994","category":"date","search_query":"amazon founded"}]')
            return ('[{"id":0,"status":"Inaccurate","basis":"outdated","correct_fact":"1991","explanation":"x","source_urls":["https://example.org"]},'
                    '{"id":1,"status":"Verified","basis":"supported","correct_fact":"","explanation":"y","source_urls":[]}]')

        factcheck._ask = fake_ask
        res = factcheck.run(object(), "key")
        self.assertEqual(len(calls), 2)  # extract + judge-all
        self.assertEqual([r["status"] for r in res], ["Inaccurate", "Verified"])
        self.assertEqual(res[0]["correct_fact"], "1991")

    def test_judge_failure_is_unverified_not_false(self):
        n = []

        def fake_ask(client, system, user):
            n.append(1)
            if len(n) == 1:
                return '[{"claim":"c","category":"stat","search_query":"q"}]'
            raise RuntimeError("429 quota")

        factcheck._ask = fake_ask
        res = factcheck.run(object(), "key")
        self.assertEqual(res[0]["status"], "Unverified")

    def test_scanned_pdf_rejected(self):
        factcheck.read_pdf = lambda f: ""
        with self.assertRaises(ValueError):
            factcheck.run(object(), "key")


class ModelFallback(unittest.TestCase):
    def test_falls_back_when_daily_quota_gone(self):
        used = []

        class M:
            def generate_content(self, model, contents, config):
                used.append(model)
                if model == "a":
                    raise RuntimeError("429 GenerateRequestsPerDayPerProjectPerModel")
                return _t.SimpleNamespace(text="ok")

        client = _t.SimpleNamespace(models=M())
        factcheck.MODEL = "a,b"
        self.assertEqual(factcheck._ask(client, "s", "u"), "ok")
        self.assertEqual(used, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
