import json
from pathlib import Path
import pytest
from app.processing.errors import ProviderClientError
from app.processing.models import ProviderLifecycleStatus
from app.processing.paddle_vl.mapping import map_status, map_progress, map_pages
FIX=Path('tests/fixtures/providers/paddle_vl_api')

def load(n): return json.loads((FIX/n).read_text())

def test_status_mapping_provider_completed_not_atlas_succeeded():
    assert map_status('completed') is ProviderLifecycleStatus.PROVIDER_COMPLETED
    assert map_status('partial_failed') is ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED
    with pytest.raises(ProviderClientError): map_status('cancelled')

def test_progress_100_is_provider_only_completion():
    p=map_progress(load('job_status_completed.json'))
    assert p.percent_complete==100.0 and p.provider_execution_complete is True

def test_valid_multi_range_fixture_sorted():
    doc=load('result_page_mapping_multi_range.json')['documents'][0]
    pages=map_pages(doc['document_id'], doc['raw_result'])
    assert [p.page_number for p in pages] == sorted([p.page_number for p in pages])
    assert pages[0].page_index == 0

def test_duplicate_page_rejected():
    pages=[{'page_number':1,'page_index':0,'local_page_index':0,'source_page_range':[1,1]}]*2
    with pytest.raises(ProviderClientError): map_pages('d',pages)

def test_missing_page_rejected():
    pages=[{'page_number':1,'page_index':0,'local_page_index':0,'source_page_range':[1,3]},{'page_number':3,'page_index':2,'local_page_index':2,'source_page_range':[1,3]}]
    with pytest.raises(ProviderClientError): map_pages('d',pages)

def test_inconsistent_indices_rejected():
    with pytest.raises(ProviderClientError): map_pages('d',[{'page_number':2,'page_index':0,'local_page_index':0,'source_page_range':[2,2]}])
    with pytest.raises(ProviderClientError): map_pages('d',[{'page_number':2,'page_index':1,'local_page_index':2,'source_page_range':[2,2]}])

def test_requested_subset_is_not_marked_missing_when_range_is_complete():
    pages=[{'page_number':5,'page_index':4,'local_page_index':0,'source_page_range':[5,6]},{'page_number':6,'page_index':5,'local_page_index':1,'source_page_range':[5,6]}]
    assert [p.page_number for p in map_pages('d', pages)] == [5, 6]

def test_expected_page_total_detects_missing_full_document_page():
    pages=[{'page_number':1,'page_index':0,'local_page_index':0,'source_page_range':[1,1]},{'page_number':3,'page_index':2,'local_page_index':0,'source_page_range':[3,3]}]
    with pytest.raises(ProviderClientError): map_pages('d', pages, expected_pages_total=3)

def test_negative_progress_counter_rejected():
    with pytest.raises(ProviderClientError): map_progress({'status':'running','pages_total':-1})
