"""Standalone Coding uploads use the same versioned MinerU chain as E2E."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import fitz

from test_workflow_task import task,options
from metaagent.workflow_runner import run_workflow


def write_pdf(path,text):
    with fitz.open() as doc:
        page=doc.new_page();page.insert_text((72,72),text)
        doc.save(path)


def test_independent_pdf_and_supplement_parse_cache_and_resume(task,monkeypatch):
    import metaagent.coding.pipeline.extraction as coding
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(task.parent/'pool'))
    pdf=task.parent/'main.pdf';supp=task.parent/'supplement.pdf'
    write_pdf(pdf,'Disease X. Mean serial interval was 4 days, 95% CI 3 to 5.')
    write_pdf(supp,'Supplement: no additional interval estimates were reported.')
    inputs=task.parent/'documents.jsonl'
    inputs.write_text(json.dumps({'record_id':'r','path':'main.pdf','supplements':[{'path':'supplement.pdf','source_id':'S1'}]})+'\n')
    parses=[];seen=[]
    def mineru(path,**kwargs):
        with fitz.open(path) as doc:text='\n'.join(page.get_text() for page in doc)
        parses.append(Path(path).read_bytes())
        return SimpleNamespace(markdown=text)
    monkeypatch.setattr('tools.mineru.pdf_reader.extract_pdf_markdown_mineru',mineru)
    monkeypatch.setattr(coding,'init_llm',lambda *_:object())
    monkeypatch.setattr('metaagent.screening.engine.init_llm_model',lambda **_:(_ for _ in ()).throw(AssertionError('Standalone Coding must not force Screening')))
    def invoke(*,messages,stage_name,**_):
        source=messages[-1]['content'].split('Candidates (guidance only):',1)[0]
        payload=json.loads(source)
        text=' '.join(s['text'] for s in payload['source_segments'])
        assert '%PDF' not in text
        seen.append(stage_name)
        match=re.search(r'Mean serial interval was (\d+) days',text)
        rows=[]
        if match:
            value=float(match.group(1))
            row={'parameter_type':'serial_interval','estimate_measure':'mean','unit':'days',
                 'point_estimate':value,'uncertainty_type':'CI','uncertainty_level':'95%',
                 'uncertainty_low':value-1,'uncertainty_high':value+1}
            row['_field_evidence']={key:text.strip() for key in row}
            rows=[row]
        if stage_name=='stage_a':return json.dumps(rows)
        candidates=json.loads(messages[-1]['content'].split('Candidates (guidance only):',1)[1])
        if rows:rows[0]['candidate_id']=candidates[0]['candidate_id'] if candidates else None
        return json.dumps({'records':rows,'dispositions':[{'candidate_id':r['candidate_id'],'action':'keep','reason':'Source checked'} for r in candidates]})
    monkeypatch.setattr(coding,'_invoke_model_content',invoke)
    opts=options(task,start_at='coding',stop_after='coding',document_manifest=inputs)
    first=run_workflow(opts)
    assert first['status']=='complete' and len(parses)==2
    docs=[json.loads(line) for line in Path(first['artifacts']['coding_input_manifest']).read_text().splitlines()]
    assert len(docs[0]['source_documents'])==2
    for document in docs[0]['source_documents']:
        assert document['parser_route']=='mineru_parsed'
        assert Path(document['original_path']).read_bytes().startswith(b'%PDF')
        assert Path(document['path']).suffix=='.md'
        assert not Path(document['path']).read_bytes().startswith(b'%PDF')
        assert document['source_sha256'] and document['parser_fingerprint']
    assert 'stage_a' in seen and 'stage_b' in seen
    count=len(seen)
    reused=run_workflow(opts)
    assert reused['stage_results']['coding']['reused'] and len(seen)==count and len(parses)==2
    other=options(task,start_at='coding',stop_after='coding',document_manifest=inputs)
    other.output_dir=task.parent/'second-run'
    cached=run_workflow(other)
    cached_doc=json.loads(Path(cached['artifacts']['coding_input_manifest']).read_text().splitlines()[0])
    assert all(r['parser_route']=='mineru_content_cache' for r in cached_doc['source_documents'])
    assert len(parses)==2
    pdf.unlink();write_pdf(pdf,'Disease X. Mean serial interval was 6 days, 95% CI 5 to 7.')
    changed=run_workflow(opts)
    assert not changed['stage_results']['coding']['reused'] and len(parses)==3
    monkeypatch.setenv('MINERU_MODEL_VERSION','different-parser-version')
    reparsed=run_workflow(opts)
    assert not reparsed['stage_results']['coding']['reused'] and len(parses)==5
