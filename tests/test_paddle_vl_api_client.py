import json, hashlib
from pathlib import Path
import httpx, pytest
from app.processing.errors import ProviderClientError, ProviderErrorCategory
from app.processing.models import ArtifactMetadata, ProviderLifecycleStatus
from app.processing.paddle_vl import PaddleVLClient, PaddleVLClientConfig, PaddleVLDocument, PaddleVLJobRequest, PaddleVLOptions
FIX=Path('tests/fixtures/providers/paddle_vl_api')
def load(n): return json.loads((FIX/n).read_text())
def req(): return PaddleVLJobRequest('job_fixture_001','request_fixture_001',[PaddleVLDocument('document_fixture_001','https://example.com/doc.pdf',pdf_source_sha256='a'*64)],options=PaddleVLOptions(batch_size=2,max_concurrent_workers=1,fail_fast=False,ttl_seconds=3600,pdf_download_timeout_seconds=10,max_pdf_bytes=1000))
def client(handler): return PaddleVLClient(PaddleVLClientConfig('https://provider.test','secret-token'), transport=httpx.MockTransport(handler))

def test_config_validation_and_redaction():
    with pytest.raises(ProviderClientError): PaddleVLClientConfig('', 'token')
    with pytest.raises(ProviderClientError): PaddleVLClientConfig('http://x', 'token')
    with pytest.raises(ProviderClientError): PaddleVLClientConfig('https://x', '')
    with pytest.raises(ProviderClientError): PaddleVLClientConfig('https://x', 'token', timeout_seconds=0)
    with pytest.raises(ProviderClientError): PaddleVLClientConfig('https://x', 'token', default_result_profile='raw')
    assert 'secret-token' not in repr(PaddleVLClientConfig('https://x','secret-token'))


def test_config_strips_surrounding_environment_whitespace_before_httpx():
    config = PaddleVLClientConfig('\r\n  https://provider.test/prefix/  \n', 'secret-token')
    assert config.base_url == 'https://provider.test/prefix/'
    scoped = PaddleVLClient(config, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert str(scoped._client.base_url) == 'https://provider.test/prefix/'


@pytest.mark.parametrize('bad_url', ['https://provider.test\u200b', 'https://provider.test:bad'])
def test_config_maps_httpx_invalid_url_syntax_to_configuration_error(bad_url):
    with pytest.raises(ProviderClientError) as exc_info:
        PaddleVLClientConfig(bad_url, 'secret-token')
    assert exc_info.value.detail.category is ProviderErrorCategory.CONFIGURATION
    assert 'base URL is invalid' in exc_info.value.detail.safe_message


def test_request_validation_and_exact_json():
    assert req().to_provider_json()['documents'][0]['pdf_source_url']=='https://example.com/doc.pdf'
    with pytest.raises(ProviderClientError): PaddleVLDocument('', 'https://x').to_provider_json()
    with pytest.raises(ProviderClientError): PaddleVLDocument('d', 'http://x').to_provider_json()
    with pytest.raises(ProviderClientError): PaddleVLDocument('d', 'https://x', pdf_source_sha256='bad').to_provider_json()
    with pytest.raises(ProviderClientError): PaddleVLJobRequest('j','r',[PaddleVLDocument('d','https://x'),PaddleVLDocument('e','https://x')]).to_provider_json()

@pytest.mark.asyncio
async def test_submit_auth_header_json_and_accepted():
    seen={}
    scoped = PaddleVLClient(PaddleVLClientConfig('https://provider.test/prefix/', 'secret-token'), transport=httpx.MockTransport(lambda r: (seen.update(auth=r.headers.get('authorization'), body=json.loads(r.content), path=r.url.path) or httpx.Response(202,json=load('job_submit_response_accepted.json')))))
    async with scoped as c:
        sub=await c.submit_job(req())
    assert seen['auth']=='Bearer secret-token' and seen['path']=='/prefix/ocr/jobs'
    assert seen['body']==req().to_provider_json()
    assert sub.status is ProviderLifecycleStatus.QUEUED

@pytest.mark.asyncio
@pytest.mark.parametrize('fixture,status,category',[('error_authentication.json',401,ProviderErrorCategory.AUTHENTICATION),('error_validation.json',422,ProviderErrorCategory.VALIDATION),('error_job_missing.json',404,ProviderErrorCategory.JOB_NOT_FOUND),('error_provider_failure.json',500,ProviderErrorCategory.EXECUTION_FAILED),('error_result_expired.json',410,ProviderErrorCategory.RESULT_EXPIRED),('error_artifact_missing_or_expired.json',404,ProviderErrorCategory.ARTIFACT_MISSING)])
async def test_error_mapping(fixture,status,category):
    async with client(lambda r: httpx.Response(status,json=load(fixture))) as c:
        with pytest.raises(ProviderClientError) as e: await c.get_job_status('job_fixture_001')
    assert e.value.detail.category is category and e.value.detail.provider_code
    assert 'secret-token' not in str(e.value)

@pytest.mark.asyncio
async def test_timeout_and_unavailable():
    async def h(r): raise httpx.ReadTimeout('x')
    async with client(h) as c:
        with pytest.raises(ProviderClientError) as e: await c.get_job_status('j')
    assert e.value.detail.category is ProviderErrorCategory.TIMEOUT
    async def h2(r): raise httpx.ConnectError('x')
    async with client(h2) as c:
        with pytest.raises(ProviderClientError) as e: await c.get_job_status('j')
    assert e.value.detail.category is ProviderErrorCategory.UNAVAILABLE

@pytest.mark.asyncio
@pytest.mark.parametrize('fixture,expected',[('job_status_queued.json',ProviderLifecycleStatus.QUEUED),('job_status_running.json',ProviderLifecycleStatus.RUNNING),('job_status_completed.json',ProviderLifecycleStatus.PROVIDER_COMPLETED),('job_status_partial_failed.json',ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED),('job_status_failed.json',ProviderLifecycleStatus.FAILED),('job_status_expired.json',ProviderLifecycleStatus.EXPIRED)])
async def test_status_parsing(fixture,expected):
    async with client(lambda r: httpx.Response(200,json=load(fixture))) as c:
        s=await c.get_job_status('job_fixture_001')
    assert s.status is expected and s.raw_provider_payload

@pytest.mark.asyncio
@pytest.mark.parametrize('fixture',['result_summary_completed.json','result_standard_completed.json','result_full_inline_completed.json','result_full_artifact_metadata.json','result_partial_failed.json'])
async def test_result_profiles(fixture):
    seen={}
    async with client(lambda r: (seen.update(query=r.url.query.decode()) or httpx.Response(200,json=load(fixture)))) as c:
        res=await c.get_job_result('job_fixture_001',profile='full')
    assert 'profile=full' in seen['query'] and res.raw_provider_payload

@pytest.mark.asyncio
async def test_result_not_ready_and_malformed_result_and_profile_validation():
    async with client(lambda r: httpx.Response(200,json=load('error_result_not_ready.json'))) as c:
        with pytest.raises(ProviderClientError) as e: await c.get_job_result('job_fixture_001')
    assert e.value.detail.category is ProviderErrorCategory.RESULT_NOT_READY
    async with client(lambda r: httpx.Response(200,json={'job_id':'j','status':'weird'})) as c:
        with pytest.raises(ProviderClientError): await c.get_job_result('j')
    async with client(lambda r: httpx.Response(200,json=load('result_summary_completed.json'))) as c:
        with pytest.raises(ProviderClientError): await c.get_job_result('job_fixture_001', profile='raw')

@pytest.mark.asyncio
async def test_artifact_download_checksum_auth_and_origin_safety():
    content=b'{"ok":true}\n'; sha=hashlib.sha256(content).hexdigest(); seen={}
    metadata=ArtifactMetadata(download_endpoint='https://evil.test/artifact', sha256=sha, size_bytes=len(content))
    async with client(lambda r: (seen.update(path=r.url.path,auth=r.headers.get('authorization')) or httpx.Response(200,content=content,headers={'X-Artifact-SHA256':sha,'Content-Length':str(len(content))}))) as c:
        art=await c.get_job_artifact('job_fixture_001', metadata)
    assert art.content==content and art.metadata.sha256==sha and seen['path'].endswith('/artifact') and seen['auth']=='Bearer secret-token'
    async with client(lambda r: httpx.Response(200,content=content)) as c:
        with pytest.raises(ProviderClientError): await c.get_job_artifact('j', ArtifactMetadata(sha256='0'*64))

@pytest.mark.asyncio
async def test_job_id_path_escaping_blocks_path_traversal():
    seen={}
    async with client(lambda r: (seen.update(path=r.url.path, query=r.url.query.decode()) or httpx.Response(200,json=load('job_status_completed.json')))) as c:
        await c.get_job_status('job/../fixture?x=1')
    assert seen['path'] == '/ocr/jobs/job%2F..%2Ffixture%3Fx%3D1'
    assert seen['query'] == ''

@pytest.mark.asyncio
async def test_malformed_success_missing_required_field_maps_safely():
    async with client(lambda r: httpx.Response(200,json={'status':'completed'})) as c:
        with pytest.raises(ProviderClientError) as e: await c.get_job_status('job_fixture_001')
    assert e.value.detail.category is ProviderErrorCategory.MALFORMED_RESPONSE
