"""Packaged parameter semantics and curated synthetic source/output examples."""
from __future__ import annotations
import json
from pathlib import Path

PROMPTS=Path(__file__).resolve().parents[1]/'prompts/coding'
CODING_PROMPT_VERSION='coding_v2'


def normalize_review_context(value):
    """Copy caller-owned question/criteria without narrowing or inventing scope."""
    if value is None:return None
    if not isinstance(value,dict) or set(value)-{'research_question','review_protocol'}:
        raise ValueError('Coding review_context accepts research_question and review_protocol only')
    question=value.get('research_question')
    if question is not None and (not isinstance(question,str) or not question.strip()):
        raise ValueError('Coding research_question must be nonempty text')
    protocol=value.get('review_protocol')
    if protocol is not None and not isinstance(protocol,dict):raise ValueError('Coding review_protocol must be an object')
    if protocol is not None:
        from metaagent.screening.protocol import validate_protocol
        validate_protocol(protocol)
    try:
        encoded=json.dumps(value,ensure_ascii=False,allow_nan=False)
    except (ValueError,TypeError):raise ValueError('Coding review_context must contain finite JSON values') from None
    if len(encoded.encode('utf-8'))>65536:raise ValueError('Coding review_context exceeds 64 KiB')
    return json.loads(encoded)


def load_review_context(path=None, research_question=None):
    import yaml
    value=yaml.safe_load(Path(path).read_text(encoding='utf-8-sig')) if path else {}
    if not isinstance(value,dict):raise ValueError('Coding task context must be an object')
    if research_question is not None:value={**value,'research_question':research_question}
    return normalize_review_context(value) if value else None

def coding_task_context(config):
    """Make the caller's binding scope visible in both A serialization backends."""
    scope=config.parameters.get('extraction_scope')
    scope=scope.strip() if isinstance(scope,str) and scope.strip() else None
    context={'prompt_version':CODING_PROMPT_VERSION,'extraction_scope':scope,
             'scope_is_explicit':scope is not None}
    review=normalize_review_context(config.parameters.get('review_context'))
    if review is not None:context['review_context']=review
    return context


def parameter_key(config):
    topic=(config.effect_type+' '+config.name).lower()
    for key,terms in {
        'reproduction_number':('reproduction','r0/rt'),
        'incubation_period':('incubation',),
        'serial_interval':('serial','generation interval'),
        'fatality':('fatality','mortality'),
        'positivity':('positivity',),
    }.items():
        if any(term in topic for term in terms):return key
    return 'generic'


def _example_quote(name,value,source):
    """Find a minimal source phrase for the curated synthetic schema labels."""
    aliases={
        'parameter_type':{'R0':'R0','Rt':'Rt','CFR':'confirmed cases','IFR':'infection fatality proportion',
                          'incubation_period':'incubation period','serial_interval':'serial interval','positivity_rate':'positive'},
        'uncertainty_type':{'CI':'confidence interval','CrI':'credible interval','IQR':'IQR'},
        'record_kind':{'count_only':'No rate or interval was reported.','rate_estimate':'proportion'},
        'estimate_measure':{'count_only':'did not report a percentage.'},
    }
    phrase=aliases.get(name,{}).get(value,str(value))
    if value==0 and name=='deaths':phrase='no deaths occurred'
    if phrase not in source:
        if name in {'denominator_count','confirmed_cases'}:phrase=str(value)+' confirmed cases'
        elif name=='tested_count':phrase=str(value)+' people tested'
        elif name=='positive_count':phrase=str(value)+' positive people'
        elif value=='count_only':phrase='No rate or interval was reported.'
    if phrase not in source:
        # This is an explicit example authoring error, not permission to invent a span.
        raise ValueError(f'Synthetic example field lacks a source-aligned quote: {name}')
    return phrase


def source_aligned_examples(config):
    """Restrict synthetic labels to codebook fields; every value has source evidence."""
    examples=json.loads((PROMPTS/'examples.json').read_text())
    key=parameter_key(config)
    source_examples=examples.get(key,examples['generic'])
    fields={f.name:f for f in config.fields}
    result=[]
    for item in source_examples:
        rows=[]
        for row in item['records']:
            values={name:row.get(name,'NR' if f.required and f.type=='str' else None) for name,f in fields.items() if name!='pmid'}
            evidence={}
            for name,value in values.items():
                if value is None or value=='NR':continue
                evidence[name]=row.get('_field_evidence',{}).get(name) or [_example_quote(name,value,item['source'])]
            anchor=row.get('_record_quote') or (evidence.get('parameter_type') or evidence.get('point_estimate') or [item['source']])[0]
            if anchor not in item['source'] or any(quote not in item['source'] for quotes in evidence.values() for quote in quotes):
                raise ValueError('Synthetic example has ungrounded record or field evidence')
            rows.append({**values,'_field_evidence':evidence,'_record_quote':anchor})
        if rows and not any(any(v is not None and v!='NR' for k,v in row.items() if k not in {'_field_evidence','_record_quote'}) for row in rows):continue
        result.append({'synthetic':True,'source':item['source'],'records':rows})
    return result


def parameter_context(config):
    key=parameter_key(config)
    common=(PROMPTS/'parameter_uncertainty.md').read_text()
    pack=PROMPTS/f'parameter_{key}.md'
    return common+(pack.read_text() if pack.exists() else ''),source_aligned_examples(config)
