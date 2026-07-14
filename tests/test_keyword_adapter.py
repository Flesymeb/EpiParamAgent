import sys
import json
from pathlib import Path
from unittest.mock import MagicMock

# Ensure src is on path for test run via `python tests/test_keyword_adapter.py`
# sys.path removed - using package imports))

import tools.epidemiology.keyword_generator as kg
from tools.epidemiology.keyword_generator import KeywordGeneratorAgent


def test_http_fallback_success():
    # Prepare agent with dummy config
    agent = KeywordGeneratorAgent(llm_provider="siliconflow")
    agent.llm = object()
    agent.raw_openai_client = None
    agent.api_base = "https://example.test/v1"
    agent.api_key = "test-key"
    agent.model = "test-model"

    # Mock requests.Session.post to return a fake response
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "primary_keywords": ["test"],
                            "synonyms": [],
                            "related_terms": [],
                            "domain_terms": [],
                        }
                    )
                }
            }
        ]
    }

    class DummySession:
        def __init__(self, *a, **k):
            pass

        def post(self, url, json, headers, timeout):
            return fake_resp

        def mount(self, *a, **k):
            pass

    # Patch the module's requests.Session
    kg.requests.Session = lambda: DummySession()

    # Call the adapter by invoking _call_llm with messages; should not raise
    resp = agent._call_llm([{"role": "user", "content": "Hello"}])
    assert hasattr(resp, "content")


if __name__ == "__main__":
    test_http_fallback_success()
    print("test passed")
