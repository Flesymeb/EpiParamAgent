"""Endpoint outages/response identity are retained without exposing credentials."""
import json

from metaagent.config import LLMConfig
from metaagent.service_health import probe_runtime


def configure(monkeypatch, *, status=200, payload=None, body='', lines=()):
    class Response:
        status_code=status
        ok=status<400
        text=body
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def json(self): return payload
        def iter_lines(self): return iter(lines)
    class Session:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def post(self,url,**kwargs):
            assert url=='http://node.example/v1/chat/completions'
            assert kwargs['json']['model']=='node-model'
            return Response()
    monkeypatch.setattr('metaagent.service_health.requests.Session',Session)
    return LLMConfig(provider='selfhosted',model='node-model',api_base='http://node.example/v1',api_key='secret-test-value')


def test_no_healthy_upstream_is_outage_and_never_secret_body(monkeypatch):
    cfg=configure(monkeypatch,status=503,body='no healthy upstream secret-test-value')
    result=probe_runtime(cfg)
    assert result['status']=='service_unavailable'
    assert result['classification']=='deployment_unavailable'
    assert result['diagnostic']=='no healthy upstream'
    assert 'secret-test-value' not in json.dumps(result)


def test_identity_is_observed_not_assumed(monkeypatch):
    cfg=configure(monkeypatch,payload={'model':'actually-reported-model','choices':[{'message':{'content':'{}'}}]})
    result=probe_runtime(cfg)
    assert result['status']=='ready'
    assert result['configured_model']=='node-model'
    assert result['observed_model']=='actually-reported-model'
    assert result['time_to_first_content_s'] is None


def test_empty_reasoning_output_does_not_claim_answer(monkeypatch):
    cfg=configure(monkeypatch,payload={'model':'node-model','choices':[{'message':{'content':''},'finish_reason':'length'}]})
    result=probe_runtime(cfg)
    assert result['status']=='ready' and not result['visible_content_received']


def test_streaming_probe_preserves_usage_and_first_content_time(monkeypatch):
    cfg=configure(monkeypatch,lines=[b'data: {"model":"node-model","choices":[{"delta":{"content":"OK"}}]}',
                                    b'data: {"choices":[],"usage":{"output_tokens":1}}',b'data: [DONE]'])
    cfg.force_streaming=True
    result=probe_runtime(cfg)
    assert result['status']=='ready'
    assert result['time_to_first_content_s'] is not None
    assert result['usage']['output_tokens']==1


def test_invalid_http200_response_not_marked_ready(monkeypatch):
    cfg=configure(monkeypatch,payload={'models':[]})
    result=probe_runtime(cfg)
    assert result['status']=='service_unavailable'
    assert result['classification']=='invalid_completion_envelope'


def test_uppercase_no_proxy_not_shadowed_by_lowercase(monkeypatch):
    observed=[]
    class Response:
        ok=False
        status_code=503
        text='no healthy upstream'
        def __enter__(self): return self
        def __exit__(self,*a): pass
    class Session:
        trust_env=True
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def post(self,*a,**kw):
            observed.append(self.trust_env)
            return Response()
    monkeypatch.setattr('metaagent.service_health.requests.Session',Session)
    monkeypatch.setenv('NO_PROXY','node.example')
    monkeypatch.setenv('no_proxy','localhost')
    result=probe_runtime(LLMConfig(model='node-model',api_base='http://node.example/v1'))
    assert observed==[False]
    assert result['classification']=='deployment_unavailable'
