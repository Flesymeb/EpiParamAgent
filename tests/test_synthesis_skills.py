"""Skill manuals reach the Pi agent through a staged, hash-bound read_skill action."""
import json

import pytest

from metaagent.synthesis.pi_agent import _prepare_workspace, pi_synthesis_fingerprint
from metaagent.synthesis.pi_tools import TOOL_SCHEMA, dispatch

ROWS = [{'estimate_id': 'a', 'point_estimate': 4.0, 'unit': 'days',
         'uncertainty_type': 'SE', 'se': 0.5, 'cohort_id': 'cohort-a'}]


def workspace(tmp_path):
    method = tmp_path / 'methods.md'
    method.write_text('normal inverse-variance fixed-effect mean')
    return _prepare_workspace(records=ROWS, research_question='What is the mean?',
                              method_sources=[method], output_dir=tmp_path / 'out')


def test_skills_are_staged_with_an_index(tmp_path):
    w = workspace(tmp_path)
    meta = json.loads((w / 'workspace.json').read_text())
    names = [skill['name'] for skill in meta['skills']]
    assert {'estimands', 'epidemiology_parameters', 'python_meta_analysis',
            'r_meta_analysis', 'sandbox_environment'} <= set(names)
    for skill in meta['skills']:
        assert (w / skill['path']).is_file()
        assert skill['description']


def test_profile_lists_the_manuals_and_the_contract(tmp_path):
    w = workspace(tmp_path)
    profile = dispatch(w, 'profile', {})
    assert [skill['name'] for skill in profile['skills']]
    assert TOOL_SCHEMA['read_skill']['name']


def test_read_skill_returns_the_manual_text(tmp_path):
    w = workspace(tmp_path)
    result = dispatch(w, 'read_skill', {'name': 'python_meta_analysis'})
    assert 'combine_effects' in result['text']
    assert result['sha256'] and result['characters'] == len(result['text'])


def test_read_skill_rejects_unknown_and_unsafe_names(tmp_path):
    w = workspace(tmp_path)
    for name in ('', 'nope', '../pi_agent', 'python_meta_analysis/../../etc/passwd', 5):
        with pytest.raises(ValueError):
            dispatch(w, 'read_skill', {'name': name})


def test_a_changed_staged_manual_is_refused(tmp_path):
    w = workspace(tmp_path)
    meta = json.loads((w / 'workspace.json').read_text())
    target = w / next(skill['path'] for skill in meta['skills'] if skill['name'] == 'estimands')
    target.write_text(target.read_text() + '\nchanged\n')
    with pytest.raises(ValueError):
        dispatch(w, 'read_skill', {'name': 'estimands'})


def test_fingerprint_covers_the_skill_manuals(tmp_path):
    fingerprint = pi_synthesis_fingerprint(records=ROWS, research_question='What is the mean?')
    manuals = [name for name in fingerprint['implementation'] if name.endswith('.md')]
    assert 'estimands.md' in manuals and 'python_meta_analysis.md' in manuals
