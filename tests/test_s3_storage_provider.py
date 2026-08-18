"""S3-compatible provider mechanics without network access."""
from __future__ import annotations

from io import BytesIO
from urllib.parse import parse_qs, urlparse

from botocore.exceptions import ClientError

from app.storage.models import StorageReference
from app.storage.s3 import S3StorageProvider


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.presign_calls: list[dict] = []
        self.copy_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    def generate_presigned_url(self, operation, *, Params, ExpiresIn, HttpMethod):
        self.presign_calls.append(
            {
                "operation": operation,
                "Params": Params,
                "ExpiresIn": ExpiresIn,
                "HttpMethod": HttpMethod,
            }
        )
        return "https://objects.example.test/presigned"

    def head_object(self, *, Bucket, Key):
        try:
            value = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise ClientError(
                {
                    "Error": {"Code": "404", "Message": "Not Found"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "HeadObject",
            ) from exc
        return {
            "ContentLength": len(value["Body"]),
            "ContentType": value.get("ContentType"),
            "Metadata": dict(value.get("Metadata") or {}),
        }

    def get_object(self, *, Bucket, Key):
        value = self.objects[(Bucket, Key)]
        return {"Body": BytesIO(value["Body"])}

    def put_object(
        self,
        *,
        Bucket,
        Key,
        Body,
        Metadata=None,
        IfNoneMatch=None,
        ContentType=None,
    ):
        self.objects[(Bucket, Key)] = {
            "Body": bytes(Body),
            "Metadata": dict(Metadata or {}),
            "ContentType": ContentType,
        }
        return {"ETag": "fake"}

    def copy_object(self, **kwargs):
        self.copy_calls.append(kwargs)
        source = kwargs["CopySource"]
        original = self.objects[(source["Bucket"], source["Key"])]
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "Body": original["Body"],
            "Metadata": dict(original.get("Metadata") or {}),
            "ContentType": original.get("ContentType"),
        }
        return {"CopyObjectResult": {"ETag": "fake-copy"}}

    def delete_object(self, *, Bucket, Key):
        self.delete_calls.append({"Bucket": Bucket, "Key": Key})
        self.objects.pop((Bucket, Key), None)
        return {}


def _provider(client: FakeS3Client) -> S3StorageProvider:
    return S3StorageProvider(
        endpoint_url="https://account.r2.cloudflarestorage.com",
        bucket="atlas-staging",
        access_key_id="access",
        secret_access_key="secret",
        region="auto",
        prefix="atlas",
        client=client,
    )


def _hf_provider(client: FakeS3Client) -> S3StorageProvider:
    return S3StorageProvider(
        endpoint_url="https://s3.hf.co/carsonhhs",
        bucket="atlas-staging",
        access_key_id="HFAK-test",
        secret_access_key="secret",
        region="auto",
        prefix="atlas",
        client=client,
    )


def test_hf_client_uses_required_path_style_region_checksum_and_sigv4_settings(monkeypatch):
    captured = {}
    fake_client = FakeS3Client()

    def fake_boto_client(service_name, **kwargs):
        captured["service_name"] = service_name
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr("app.storage.s3.boto3.client", fake_boto_client)

    provider = S3StorageProvider(
        endpoint_url="https://s3.hf.co/carsonhhs",
        bucket="atlas-staging",
        access_key_id="HFAK-test",
        secret_access_key="secret",
        region="auto",
        prefix="atlas",
    )

    assert provider.is_huggingface_storage_bucket is True
    assert captured["service_name"] == "s3"
    assert captured["endpoint_url"] == "https://s3.hf.co/carsonhhs"
    assert captured["region_name"] == "us-east-1"
    assert captured["config"].signature_version == "s3v4"
    assert captured["config"].s3 == {"addressing_style": "path"}
    assert captured["config"].request_checksum_calculation == "when_required"
    assert captured["config"].response_checksum_validation == "when_required"


def test_hf_real_presigner_emits_sigv4_query_parameters_without_network_access():
    provider = S3StorageProvider(
        endpoint_url="https://s3.hf.co/carsonhhs",
        bucket="atlas-staging",
        access_key_id="HFAK-test",
        secret_access_key="secret-test",
        region="auto",
        prefix="atlas",
    )

    url, headers = provider.generate_ingress_put_url(
        upload_id="6" * 32,
        content_type="application/pdf",
        checksum_sha256="f" * 64,
        expires_seconds=900,
    )

    query = parse_qs(urlparse(url).query)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert "X-Amz-Credential" in query
    assert "X-Amz-Signature" in query
    assert "AWSAccessKeyId" not in query
    assert "Signature" not in query
    assert headers == {"Content-Type": "application/pdf"}


def test_presigned_ingress_put_signs_only_expected_object_metadata():
    client = FakeS3Client()
    provider = _provider(client)
    checksum = "a" * 64
    upload_id = "1" * 32

    url, headers = provider.generate_ingress_put_url(
        upload_id=upload_id,
        content_type="application/pdf",
        checksum_sha256=checksum,
        expires_seconds=900,
    )

    assert url == "https://objects.example.test/presigned"
    assert headers == {
        "Content-Type": "application/pdf",
        "x-amz-meta-sha256": checksum,
        "x-amz-meta-upload-id": upload_id,
    }
    assert client.presign_calls == [
        {
            "operation": "put_object",
            "Params": {
                "Bucket": "atlas-staging",
                "Key": f"atlas/ingress/{upload_id}",
                "ContentType": "application/pdf",
                "Metadata": {"sha256": checksum, "upload-id": upload_id},
            },
            "ExpiresIn": 900,
            "HttpMethod": "PUT",
        }
    ]


def test_hf_presigned_ingress_put_does_not_depend_on_user_metadata():
    client = FakeS3Client()
    provider = _hf_provider(client)
    checksum = "d" * 64
    upload_id = "4" * 32

    url, headers = provider.generate_ingress_put_url(
        upload_id=upload_id,
        content_type="application/pdf",
        checksum_sha256=checksum,
        expires_seconds=900,
    )

    assert provider.is_huggingface_storage_bucket is True
    assert provider.user_metadata_supported is False
    assert url == "https://objects.example.test/presigned"
    assert headers == {"Content-Type": "application/pdf"}
    assert client.presign_calls == [
        {
            "operation": "put_object",
            "Params": {
                "Bucket": "atlas-staging",
                "Key": f"atlas/ingress/{upload_id}",
                "ContentType": "application/pdf",
            },
            "ExpiresIn": 900,
            "HttpMethod": "PUT",
        }
    ]


def test_publish_ingress_uses_server_side_copy_and_preserves_integrity_metadata():
    client = FakeS3Client()
    provider = _provider(client)
    checksum = "b" * 64
    upload_id = "2" * 32
    reference = StorageReference.parse("src_0123456789abcdef0123456789abcdef")
    ingress_key = provider.ingress_key(upload_id)
    client.objects[("atlas-staging", ingress_key)] = {
        "Body": b"%PDF-direct",
        "ContentType": "application/pdf",
        "Metadata": {"sha256": checksum, "upload-id": upload_id},
    }

    result = provider.publish_ingress(
        upload_id=upload_id,
        reference=reference,
        expected_size=len(b"%PDF-direct"),
        expected_sha256=checksum,
        expected_content_type="application/pdf",
    )

    assert result.reference == reference
    assert result.byte_size == len(b"%PDF-direct")
    assert result.checksum_sha256 == checksum
    assert client.copy_calls == [
        {
            "Bucket": "atlas-staging",
            "Key": "atlas/objects/01/23/src_0123456789abcdef0123456789abcdef",
            "CopySource": {"Bucket": "atlas-staging", "Key": ingress_key},
            "MetadataDirective": "COPY",
        }
    ]
    assert provider.get(reference) == b"%PDF-direct"


def test_hf_publish_ingress_accepts_missing_user_metadata_and_copies_server_side():
    client = FakeS3Client()
    provider = _hf_provider(client)
    checksum = "e" * 64
    upload_id = "5" * 32
    reference = StorageReference.parse("src_1123456789abcdef0123456789abcdef")
    ingress_key = provider.ingress_key(upload_id)
    client.objects[("atlas-staging", ingress_key)] = {
        "Body": b"%PDF-hf-direct",
        "ContentType": "application/pdf",
        "Metadata": {},
    }

    result = provider.publish_ingress(
        upload_id=upload_id,
        reference=reference,
        expected_size=len(b"%PDF-hf-direct"),
        expected_sha256=checksum,
        expected_content_type="application/pdf",
    )

    assert result.reference == reference
    assert result.byte_size == len(b"%PDF-hf-direct")
    assert result.checksum_sha256 == checksum
    assert client.copy_calls == [
        {
            "Bucket": "atlas-staging",
            "Key": "atlas/objects/11/23/src_1123456789abcdef0123456789abcdef",
            "CopySource": {"Bucket": "atlas-staging", "Key": ingress_key},
        }
    ]
    assert provider.get(reference) == b"%PDF-hf-direct"


def test_ingress_delete_does_not_delete_published_source():
    client = FakeS3Client()
    provider = _provider(client)
    checksum = "c" * 64
    upload_id = "3" * 32
    reference = StorageReference.parse("src_abcdef0123456789abcdef0123456789")
    ingress_key = provider.ingress_key(upload_id)
    client.objects[("atlas-staging", ingress_key)] = {
        "Body": b"%PDF-direct",
        "ContentType": "application/pdf",
        "Metadata": {"sha256": checksum, "upload-id": upload_id},
    }
    provider.publish_ingress(
        upload_id=upload_id,
        reference=reference,
        expected_size=len(b"%PDF-direct"),
        expected_sha256=checksum,
        expected_content_type="application/pdf",
    )

    provider.delete_ingress(upload_id)

    assert ("atlas-staging", ingress_key) not in client.objects
    assert provider.get(reference) == b"%PDF-direct"
