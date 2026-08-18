"""S3-compatible durable object storage provider.

The provider keeps Atlas' opaque ``src_*`` references provider-independent while
mapping them to private object-store keys. It is intentionally synchronous to
match the StorageProvider v1 boundary; callers own thread offloading where large
reads are involved.

Hugging Face Storage Buckets expose an S3-compatible gateway with a few important
differences from AWS/R2. When the configured endpoint host is ``s3.hf.co`` this
provider automatically uses HF-compatible boto settings and does not rely on
arbitrary ``x-amz-meta-*`` user metadata, which the HF gateway does not persist.
"""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.storage.errors import (
    DeleteFailure,
    IntegrityMismatch,
    ObjectAlreadyExists,
    ObjectNotFound,
    ProviderUnavailable,
    ReadFailure,
    WriteFailure,
)
from app.storage.models import PutResult, StorageReference


class S3StorageProvider:
    """Private S3-compatible storage keyed by opaque Atlas references."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        prefix: str = "atlas",
        client: Any | None = None,
    ) -> None:
        if not endpoint_url or not bucket or not access_key_id or not secret_access_key:
            raise ProviderUnavailable("Object storage configuration is incomplete")
        self.endpoint_url = endpoint_url.rstrip("/")
        self.bucket = bucket
        self.prefix = prefix.strip("/") or "atlas"
        endpoint_host = (urlparse(self.endpoint_url).hostname or "").lower()
        self.is_huggingface_storage_bucket = endpoint_host == "s3.hf.co"
        self.user_metadata_supported = not self.is_huggingface_storage_bucket

        if client is not None:
            self.client = client
            return

        effective_region = (
            "us-east-1"
            if self.is_huggingface_storage_bucket
            else (region or "auto")
        )
        client_kwargs: dict[str, Any] = {
            "endpoint_url": self.endpoint_url,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "region_name": effective_region,
        }
        if self.is_huggingface_storage_bucket:
            client_kwargs["config"] = Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            )
        self.client = boto3.client("s3", **client_kwargs)

    @staticmethod
    def _ref(reference: StorageReference | str) -> StorageReference:
        if isinstance(reference, StorageReference):
            return StorageReference.parse(reference.value)
        return StorageReference.parse(str(reference))

    def object_key(self, reference: StorageReference | str) -> str:
        ref = self._ref(reference)
        return f"{self.prefix}/objects/{ref.value[4:6]}/{ref.value[6:8]}/{ref.value}"

    def ingress_key(self, upload_id: str) -> str:
        token = str(upload_id).strip()
        if not token or any(character not in "0123456789abcdef" for character in token.lower()):
            raise ValueError("Invalid upload id")
        return f"{self.prefix}/ingress/{token.lower()}"

    @staticmethod
    def _status(exc: ClientError) -> int | None:
        metadata = exc.response.get("ResponseMetadata") or {}
        try:
            return int(metadata.get("HTTPStatusCode"))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _is_not_found(cls, exc: ClientError) -> bool:
        code = str((exc.response.get("Error") or {}).get("Code") or "")
        return cls._status(exc) == 404 or code in {"404", "NoSuchKey", "NotFound"}

    def _head_key(self, key: str) -> dict[str, Any] | None:
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if self._is_not_found(exc):
                return None
            raise ProviderUnavailable("Object storage HEAD failed") from exc
        except Exception as exc:
            raise ProviderUnavailable("Object storage HEAD failed") from exc

    @staticmethod
    def _metadata_sha(head: dict[str, Any]) -> str:
        metadata = head.get("Metadata") or {}
        return str(metadata.get("sha256") or "").lower()

    def _assert_head_matches(
        self,
        head: dict[str, Any],
        *,
        expected_size: int,
        expected_sha256: str,
        expected_content_type: str | None = None,
    ) -> None:
        if int(head.get("ContentLength") or -1) != int(expected_size):
            raise IntegrityMismatch("Object storage byte size does not match expected source")
        if self.user_metadata_supported:
            if self._metadata_sha(head) != expected_sha256.lower():
                raise IntegrityMismatch("Object storage SHA-256 metadata does not match expected source")
        if expected_content_type:
            actual_type = str(head.get("ContentType") or "").split(";", 1)[0].strip().lower()
            if actual_type and actual_type != expected_content_type.lower():
                raise IntegrityMismatch("Object storage content type does not match expected source")

    def put(
        self,
        data: bytes,
        reference: StorageReference | str | None = None,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> PutResult:
        ref = self._ref(reference) if reference is not None else StorageReference.generate()
        actual_size = len(data)
        actual_sha = hashlib.sha256(data).hexdigest()
        if expected_size is not None and int(expected_size) != actual_size:
            raise IntegrityMismatch("Expected byte size does not match actual bytes")
        if expected_sha256 is not None and expected_sha256.lower() != actual_sha:
            raise IntegrityMismatch("Expected SHA-256 does not match actual bytes")
        key = self.object_key(ref)
        put_kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": data,
            "IfNoneMatch": "*",
        }
        if self.user_metadata_supported:
            put_kwargs["Metadata"] = {"sha256": actual_sha}
        try:
            self.client.put_object(**put_kwargs)
        except ClientError as exc:
            if self._status(exc) == 412:
                head = self._head_key(key)
                if head is not None:
                    try:
                        self._assert_head_matches(
                            head,
                            expected_size=actual_size,
                            expected_sha256=actual_sha,
                        )
                    except IntegrityMismatch as mismatch:
                        raise ObjectAlreadyExists(
                            "Object reference already exists with different bytes"
                        ) from mismatch
                    return PutResult(ref, actual_size, actual_sha)
            raise WriteFailure("Object storage write failed") from exc
        except Exception as exc:
            raise WriteFailure("Object storage write failed") from exc
        return PutResult(ref, actual_size, actual_sha)

    def get(self, reference: StorageReference | str) -> bytes:
        key = self.object_key(reference)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            data = response["Body"].read()
        except ClientError as exc:
            if self._is_not_found(exc):
                raise ObjectNotFound("Object not found") from exc
            raise ReadFailure("Object storage read failed") from exc
        except Exception as exc:
            raise ReadFailure("Object storage read failed") from exc
        if not isinstance(data, bytes):
            data = bytes(data)
        return data

    def exists(self, reference: StorageReference | str) -> bool:
        return self._head_key(self.object_key(reference)) is not None

    def delete(self, reference: StorageReference | str) -> None:
        key = self.object_key(reference)
        if self._head_key(key) is None:
            raise ObjectNotFound("Object not found")
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise DeleteFailure("Object storage delete failed") from exc

    def generate_ingress_put_url(
        self,
        *,
        upload_id: str,
        content_type: str,
        checksum_sha256: str,
        expires_seconds: int,
    ) -> tuple[str, dict[str, str]]:
        key = self.ingress_key(upload_id)
        params: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "ContentType": content_type,
        }
        headers = {"Content-Type": content_type}
        if self.user_metadata_supported:
            metadata = {
                "sha256": checksum_sha256.lower(),
                "upload-id": upload_id.lower(),
            }
            params["Metadata"] = metadata
            headers.update(
                {
                    "x-amz-meta-sha256": checksum_sha256.lower(),
                    "x-amz-meta-upload-id": upload_id.lower(),
                }
            )
        try:
            url = self.client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=int(expires_seconds),
                HttpMethod="PUT",
            )
        except Exception as exc:
            raise ProviderUnavailable("Could not create direct upload URL") from exc
        return url, headers

    def verify_ingress(
        self,
        *,
        upload_id: str,
        expected_size: int,
        expected_sha256: str,
        expected_content_type: str,
    ) -> None:
        head = self._head_key(self.ingress_key(upload_id))
        if head is None:
            raise ObjectNotFound("Direct upload object is not available")
        self._assert_head_matches(
            head,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            expected_content_type=expected_content_type,
        )
        if self.user_metadata_supported:
            metadata = head.get("Metadata") or {}
            if str(metadata.get("upload-id") or "").lower() != upload_id.lower():
                raise IntegrityMismatch("Direct upload id metadata does not match session")

    def publish_ingress(
        self,
        *,
        upload_id: str,
        reference: StorageReference | str,
        expected_size: int,
        expected_sha256: str,
        expected_content_type: str,
    ) -> PutResult:
        ref = self._ref(reference)
        self.verify_ingress(
            upload_id=upload_id,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            expected_content_type=expected_content_type,
        )
        destination_key = self.object_key(ref)
        existing = self._head_key(destination_key)
        if existing is not None:
            self._assert_head_matches(
                existing,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                expected_content_type=expected_content_type,
            )
            return PutResult(ref, int(expected_size), expected_sha256.lower())
        copy_kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": destination_key,
            "CopySource": {"Bucket": self.bucket, "Key": self.ingress_key(upload_id)},
        }
        if self.user_metadata_supported:
            copy_kwargs["MetadataDirective"] = "COPY"
        try:
            self.client.copy_object(**copy_kwargs)
        except Exception as exc:
            raise WriteFailure("Could not publish direct upload object") from exc
        published = self._head_key(destination_key)
        if published is None:
            raise WriteFailure("Published direct upload object is unavailable")
        self._assert_head_matches(
            published,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            expected_content_type=expected_content_type,
        )
        return PutResult(ref, int(expected_size), expected_sha256.lower())

    def delete_ingress(self, upload_id: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self.ingress_key(upload_id))
        except Exception as exc:
            raise DeleteFailure("Could not delete direct upload ingress object") from exc
