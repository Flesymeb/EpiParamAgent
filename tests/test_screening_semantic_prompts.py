"""Offline, actual request-body coverage of task-first 5D semantics."""
import asyncio,json,re,socket
from pathlib import Path
import httpx,pytest
from langchain_openai import ChatOpenAI
from metaagent.screening import engine
from metaagent.screening import prompt_loader as prompts

DIMS=('disease_relevance','population_relevance','location_relevance','original_evidence','parameter_relevance')
@pytest.fixture(autouse=True)
def offline(monkeypatch):
 for k in ('LANGSMITH_TRACING','LANGCHAIN_TRACING_V2'):monkeypatch.setenv(k,'false')
 def no_connect(*a,**kw):raise AssertionError('External network forbidden')
 monkeypatch.setattr(socket.socket,'connect',no_connect)

def wire(config,question='Task question',mode='single',strategy='5d',stage='title_abstract'):
 requests=[]
 def reply(request):
  body=json.loads(request.content);requests.append(body)
  if config.get('review_protocol'):
   sent=json.loads(next(m['content'] for m in body['messages'] if m['role']=='user'))
   answer={'record_id':sent['records'][0]['record_id'],'assessments':[{'criterion_id':'a','status':'unknown','evidence_basis':'insufficient','reason':'Insufficient source'}],'proposed_route':'review'}
  elif strategy=='peco':answer={'population':{'present':True,'justification':'source'},'exposure':{'present':True,'justification':'source'},'comparison':{'present':False,'justification':'source'},'outcome':{'present':True,'justification':'source'},'include':True,'justification':'source','confidence':0.5}
  elif strategy.startswith('binary'):answer={'include':True,'justification':'source'}
  else:
   value={**{k:{'score':2,'justification':'Source details are uncertain'} for k in DIMS},'tier':'P','overall_justification':'Task-relevant path requires source verification'}
   source=next(m['content'] for m in body['messages'] if m['role']=='user');ids=re.findall(r'^Paper ID: (.+)$',source,re.M)
   answer={'papers':[{'paper_id':i,'decision':value} for i in ids]} if mode=='multi' else value
  return httpx.Response(200,json={'id':'mock','model':'offline','choices':[{'index':0,'message':{'role':'assistant','content':json.dumps(answer)},'finish_reason':'stop'}],'usage':{'prompt_tokens':3,'completion_tokens':4,'total_tokens':7}})
 async def go():
  async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
   llm=ChatOpenAI(model='offline',api_key='synthetic',base_url='http://offline.invalid/v1',max_retries=0,http_async_client=client)
   result=await engine.screen_papers_batch_async([{'record_id':'paper-1','PMID':'1','Title':'Imported cases in a small Letter','Abstract':'Original observations with an estimated outcome','fulltext':'Original full-text observations with an estimated outcome','reference_label':'DO_NOT_SEND_LABEL'}],question,llm,screening_config=config,batch_mode=mode,strategy=strategy,screening_stage=stage,content_key="fulltext" if "full_text" in stage else "Abstract",content_label="Full text" if "full_text" in stage else "Abstract")
   return result
 result=asyncio.run(go());assert len(requests)==1
 return requests[0],result
@pytest.mark.parametrize('disease',['mpox','covid19'])
@pytest.mark.parametrize('topic,guide',[('fatality','fatality'),('reproduction_number','reproduction_number'),('serial_interval','intervals')])
def test_task_guide_reaches_actual_5d_wire(disease,topic,guide):
 body,result=wire({'disease_focus':disease,'topic':topic,'parameter_focus':topic,'estimand_guard':{'enabled':False}},f'Assess {topic} in {disease}')
 text=json.dumps(body,ensure_ascii=False)
 assert f'[Parameter guide: {guide}]' in text and 'complete research question' in text
 assert 'Imported cases are not automatically irrelevant' in text
 assert 'This is not a quality ranking' in text and 'not automatically capped' in text
 assert 'DO_NOT_SEND_LABEL' not in text and result[0]['llm_tier']=='P'

@pytest.mark.parametrize('mode',['single','multi'])
def test_unknown_disease_defaults_never_inject_variant_scope(mode):
 body,_=wire({},'What outcomes are reported for pathogen Zeta?',mode=mode)
 text=json.dumps(body,ensure_ascii=False)
 assert 'SARS-CoV-2' not in text and 'wild-type only without variant comparison' not in text
 assert 'Score 2 if the paper estimates' not in text and 'not automatically weaker' in text

@pytest.mark.parametrize('strategy',['binary','binary_baseline'])
def test_control_wire_does_not_receive_new_parameter_guides(strategy):
 body,_=wire({'topic':'fatality'},'Assess fatality',strategy=strategy)
 assert '[Parameter guide:' not in json.dumps(body)

def test_typed_protocol_still_bypasses_new_domain_knowledge(monkeypatch):
 def forbidden(*a,**kw):raise AssertionError('Typed protocol cannot load 5D guides')
 monkeypatch.setattr(engine,'load_parameter_guides',forbidden)
 protocol={'version':'test','criteria':[{'id':'a','description':'Meets the declared task'}],'logic':'a'}
 body,result=wire({'review_protocol':protocol,'topic':'fatality'},'Task question')
 assert '[Parameter guide:' not in json.dumps(body) and result[0]['protocol_decision']['route']=='review'

def test_loader_multi_scope_latent_and_unknown():
 value=prompts.load_parameter_guides({'topic':'serial_interval'},'Study R0, fatality and incubation period')
 assert all(f'[Parameter guide: {k}]' in value for k in ('fatality','reproduction_number','intervals'))
 assert '[Parameter guide: intervals]' in prompts.load_parameter_guides({'topic':'latent_period'})
 assert '[Parameter guide: intervals]' not in prompts.load_parameter_guides({'topic':'fatality'},'Confidence intervals')
 assert prompts.load_parameter_guides({},'Unspecified outcome in pathogen Zeta')==''

@pytest.mark.parametrize('stage',[k for k,v in prompts.PROMPT_FILES.items() if v[0].parent.name=='5d'])
def test_all_system_resources_format_and_share_task_semantics(stage):
 system,_=prompts.load_prompt_templates(stage)
 rendered=system.format(**{k:'Declared task information' for k in ('research_question','disease_focus','disease_exclude','parameter_focus','parameter_exclude','parameter_scoring_note','screening_stage')})
 assert len(rendered.split())<900  # Includes explicit insufficient-source/exception boundary checks.
 assert 'Imported cases are not automatically irrelevant' in rendered
 assert 'not a quality ranking' in rendered and 'not automatically capped' in rendered
 assert '0 = clear nonmatch' in rendered and '2 = insufficient' in rendered
 assert 'exactly one tier S/P/U' in rendered and 'weighted total' in rendered
 assert "pilot's GT" not in rendered

def test_peco_context_does_not_load_5d_guides(monkeypatch):
 from metaagent.screening.models import PECODecision
 captured=[]
 def forbidden(*a,**kw):raise AssertionError('PECO must not load 5D parameter guides')
 monkeypatch.setattr(engine,'load_parameter_guides',forbidden)
 class Model:
  def bind(self,**kw):return self
  async def ainvoke(self,messages,**kw):
   captured.append(messages)
   return PECODecision(population={'present':True,'justification':'source'},exposure={'present':True,'justification':'source'},comparison={'present':False,'justification':'source'},outcome={'present':True,'justification':'source'},include=True,justification='source',confidence=0.5)
 result=asyncio.run(engine.screen_papers_batch_async([{'PMID':'1','Title':'Source','Abstract':'Source abstract'}],'Assess reproduction number',Model(),strategy='peco',screening_config={'topic':'reproduction_number'}))
 assert len(captured)==1 and '[Parameter guide:' not in str(captured)
 assert result[0]['llm_suggest']!='error'


def test_shared_user_format_respects_matched_fulltext_stage():
 body,_=wire({'topic':'serial_interval'},'Assess serial interval',stage='matched_full_text')
 system=body['messages'][0]['content'];user=body['messages'][-1]['content']
 assert 'Stage: full-text assessment' in system
 assert 'Stage: title/abstract triage' not in user
 assert 'screening stage and complete eligibility scope declared in the system' in user
 assert 'Full text: Original full-text observations' in user

@pytest.mark.parametrize('case,question,title,abstract,tag',[
 ('identity_only','Assess original target-parameter estimates.','Alvarez 2020','','P'),
 ('linked_exception','Include Region A infections and explicitly linked exported cases; exclude unlinked foreign-origin cases.','Cases sampled overseas','The exported cases were linked to exposure in Region A.','S'),
 ('borrowed_only','Include original estimates of the reproduction number.','Illustrative model scenarios','The reproduction number is only a borrowed fixed assumption; no original estimate is reported.','U'),
 ('inputs_unresolved','Require original reproduction-number estimates using both genomic and incidence data.','Original reproduction-number estimation','We estimated the reproduction number using genomic observations.','P'),
 ('only_excluded_inputs','Require original reproduction-number estimates using both genomic and incidence data.','Original estimation with one source','Only genomic observations were used; no incidence data were used.','U'),
 ('confirmed_design_exclusion','Include prospective designs and exclude retrospective designs.','A retrospective study','This retrospective cohort estimates the target outcome from historical records.','U'),
])
def test_candidate2_boundary_cases_reach_real_wire_without_inferred_facts(case,question,title,abstract,tag):
 """Mock answers test transport/state preservation, not LLM scientific accuracy."""
 received=[]
 def reply(request):
  body=json.loads(request.content);received.append(body)
  answer={**{key:{'score':2,'justification':'Only the supplied source is available; unresolved facts are not inferred.'} for key in DIMS},'tier':tag,'overall_justification':'Source facts and the declared inclusion/exclusion conditions must be checked; unknown metadata is unresolved.'}
  return httpx.Response(200,json={'id':'offline-boundary','model':'offline','choices':[{'index':0,'message':{'role':'assistant','content':json.dumps(answer)},'finish_reason':'stop'}]})
 source={'record_id':case,'Title':title,'Abstract':abstract,'Authors':'Alvarez','DOI':'10.0000/synthetic-record','historical_label':'DO_NOT_SEND_GOLD'}
 async def go():
  async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
   llm=ChatOpenAI(model='offline',api_key='synthetic',base_url='http://offline.invalid/v1',http_async_client=client,max_retries=0)
   return await engine.screen_papers_batch_async([source],question,llm,screening_config={'estimand_guard':{'enabled':False}})
 result=asyncio.run(go())
 assert len(received)==1
 text=json.dumps(received[0]['messages'],ensure_ascii=False)
 assert question in text and title in text and 'DO_NOT_SEND_GOLD' not in text
 assert source['Title']==title and source['Abstract']==abstract
 assert result[0]['llm_tier']==tag and result[0]['overall_score'] is None
 assert result[0]['llm_suggest']=={'S':'strong_candidate','P':'possible_candidate','U':'unlikely_candidate'}[tag]
 assert not any(key in result[0] for key in ('sample_size','study_design','population_size'))
