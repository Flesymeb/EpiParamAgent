"""Default 5D consumes actual assessments/tags; legacy is explicit."""
import asyncio, copy, json, re, socket
import httpx
import pytest
from langchain_openai import ChatOpenAI
from metaagent.screening import engine
from metaagent.screening.guards import apply_screening_guards
from metaagent.screening.models import ScreeningDecision, classify_screening_decision
DIMS=('disease_relevance','population_relevance','location_relevance','original_evidence','parameter_relevance')
def payload(tier='S',score=0):
 return {**{k:{'score':score,'justification':'Source assessment.'} for k in DIMS},'tier':tier,'overall_justification':'Holistic judgment under the supplied review criteria.'}
@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
 for k in ('LANGCHAIN_TRACING_V2','LANGSMITH_TRACING'):monkeypatch.setenv(k,'false')
 def forbidden(*a,**kw):raise AssertionError('External network forbidden')
 monkeypatch.setattr(socket.socket,'connect',forbidden)
def test_no_derived_total_or_rating_based_tag():
 value=ScreeningDecision(**payload('S',0));assert value.overall_score is None
 assert classify_screening_decision(value)=='strong_candidate'
 data=payload('U',4);data['overall_score']=1;value=ScreeningDecision(**data)
 assert value.overall_score==1 and classify_screening_decision(value)=='unlikely_candidate'
@pytest.mark.parametrize('stage',['strict','confirm_parameter','filter_possible'])
def test_default_has_no_numeric_veto(stage):
 assert classify_screening_decision(ScreeningDecision(**payload('S',0)),stage_mode=stage)=='strong_candidate'
 assert classify_screening_decision(ScreeningDecision(**payload('U',4)),stage_mode=stage)=='unlikely_candidate'
def test_missing_tier_no_threshold_fallback():
 data=payload(score=4);data.pop('tier');value=ScreeningDecision(**data)
 with pytest.raises(ValueError,match='explicit valid'):classify_screening_decision(value)
 assert classify_screening_decision(value,prefer_llm_tier=False)=='strong_candidate'
@pytest.mark.parametrize('bad',[True,False,2.8,5,-1,'high','2'])
def test_default_rejects_guessed_scores(bad):
 data=payload();data[DIMS[0]]['score']=bad
 with pytest.raises(ValueError):engine._parse_json_result(json.dumps(data),ScreeningDecision)
@pytest.mark.parametrize('issue',['dimension','justification','tier','invalid_tier'])
def test_default_requires_actual_complete_payload(issue):
 data=payload()
 if issue=='dimension':data.pop(DIMS[1])
 elif issue=='justification':data[DIMS[1]].pop('justification')
 elif issue=='tier':data.pop('tier')
 else:data['tier']='include'
 with pytest.raises(ValueError):engine._parse_json_result(json.dumps(data),ScreeningDecision)
def test_legacy_normalization_explicit_only():
 data={'disease':4,'parameter':4,'overall_score':3.6}
 with pytest.raises(ValueError):engine._parse_json_result(json.dumps(data),ScreeningDecision)
 value=engine._parse_json_result(json.dumps(data),ScreeningDecision,strict_5d=False)
 assert value.population_relevance.score==2 and value.overall_score is None
 assert classify_screening_decision(value,prefer_llm_tier=False)=='possible_candidate'
def run_wire(mode,issue,repair=True):
 received=[];count=2 if mode=='multi' else 1
 records=[{'PMID':str(i+1),'Title':f'SOURCE_{i}','Abstract':f'Original observations SOURCE_ABSTRACT_{i}'} for i in range(count)]
 def respond(request):
  body=json.loads(request.content);received.append(body)
  source=next(m['content'] for m in body['messages'] if m['role']=='user')
  ids=re.findall(r'^Paper ID: (.+)$',source,re.M)
  decision=payload('S',0);bad=len(received)==1 or not repair
  if bad and issue=='tier':decision.pop('tier')
  if bad and issue=='dimension':decision.pop(DIMS[2])
  if bad and issue=='score':decision[DIMS[0]]['score']=True
  answer={'papers':[{'paper_id':i,'decision':copy.deepcopy(decision)} for i in ids]} if mode=='multi' else decision
  if bad and mode=='multi':
   if issue=='missing_id':answer['papers'].pop()
   if issue=='extra_id':answer['papers'].append({'paper_id':'extra','decision':payload()})
   if issue=='duplicate_id':answer['papers'].append(copy.deepcopy(answer['papers'][0]))
  return httpx.Response(200,json={'id':'mock','model':'offline','choices':[{'index':0,'message':{'role':'assistant','content':json.dumps(answer)},'finish_reason':'stop'}],'usage':{'prompt_tokens':7,'completion_tokens':11,'total_tokens':18}})
 async def execute():
  async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
   llm=ChatOpenAI(model='offline',api_key='synthetic',base_url='https://offline.invalid/v1',max_retries=0,http_async_client=client)
   return await engine.screen_papers_batch_async(records,'Use the supplied review criteria.',llm,batch_mode=mode,batch_size=count,batch_concurrency=1,screening_config={'estimand_guard':{'enabled':False}})
 return asyncio.run(execute()),received

@pytest.mark.parametrize('mode',['single','multi'])
@pytest.mark.parametrize('issue',['tier','dimension','score'])
def test_actual_wire_one_contract_correction(mode,issue):
 result,requests=run_wire(mode,issue)
 assert len(requests)==2
 assert all(r['llm_suggest']=='strong_candidate' and r['llm_tier']=='S' and r['overall_score'] is None for r in result)
 assert 'output contract' in requests[1]['messages'][-1]['content']
 assert 'S/P/U' in requests[1]['messages'][-1]['content']
 assert all('SOURCE_ABSTRACT_0' in json.dumps(r['messages']) for r in requests)

@pytest.mark.parametrize('mode',['single','multi'])
def test_persistent_bad_tier_is_error_without_fabricated_scores(mode):
 result,requests=run_wire(mode,'tier',False)
 assert len(requests)==2
 assert all(r['llm_suggest']=='error' and r['llm_tier']=='' for r in result)
 for row in result:
  assert row['overall_score'] is None
  assert all(row[f'{k}_score'] is None for k in ('disease','population','location','evidence','parameter'))
@pytest.mark.parametrize('issue',['missing_id','extra_id','duplicate_id'])
@pytest.mark.parametrize('repair',[True,False])
def test_batch_id_contract_repaired_once_or_explicit_errors(issue,repair):
 result,requests=run_wire('multi',issue,repair)
 assert len(requests)==2 and len(result)==2
 assert all(r['llm_suggest']==('strong_candidate' if repair else 'error') for r in result)
 assert all('SOURCE_ABSTRACT_0' in json.dumps(r['messages']) for r in requests)

def test_guard_preserves_tags_and_review_scope():
 row={'llm_suggest':'strong_candidate','llm_tier':'S','Title':'Effective reproduction number','Abstract':'Rt estimate'}
 apply_screening_guards([row],{'estimand_guard':{'target':'R0'}},preserve_model_tier=True)
 assert row['llm_tier']=='S' and row['llm_suggest']=='strong_candidate' and row['screening_requires_review']
 editorial={'llm_suggest':'strong_candidate','llm_tier':'S','pub_types':['Editorial'],'Title':'Brief commentary','Abstract':'Comment on an issue'}
 apply_screening_guards([editorial],preserve_model_tier=True)
 assert editorial['screening_requires_review'] and editorial['llm_tier']=='S' and editorial['llm_suggest']=='strong_candidate'
 original={'llm_suggest':'strong_candidate','llm_tier':'S','pub_types':['Review'],'Title':'Cohort study','Abstract':'We enrolled patients'}
 apply_screening_guards([original],preserve_model_tier=True)
 assert original['publication_type_conflict']=='original_data_cues_present' and not original.get('screening_requires_review')

def test_default_disables_numeric_rescue_but_legacy_remains():
 base={'llm_suggest':'unlikely_candidate','llm_tier':'U','pub_types':['Editorial'],'Title':'Comment','Abstract':'Comment',**{k+'_score':4 for k in ('disease','population','location','parameter')},'evidence_score':0}
 current=copy.deepcopy(base);legacy=copy.deepcopy(base)
 apply_screening_guards([current],preserve_model_tier=True);apply_screening_guards([legacy])
 assert current['llm_suggest']=='unlikely_candidate' and current['llm_tier']=='U' and not current.get('screening_requires_review')
 assert current['screening_review_flags'] and legacy['llm_suggest']=='possible_candidate'
