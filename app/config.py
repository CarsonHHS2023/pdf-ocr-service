"""Application settings."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_host: str = "0.0.0.0"
    api_port: int = 7860
    upload_dir: Path = Path("uploads")
    output_dir: Path = Path("output")
    storage_root: Path = Path("storage/objects")
    cors_origins: list[str] = ["*"]
    layout_engine: str = "auto"
    layout_debug_enabled: bool = False
    layout_debug_dir: Path = Path("output/layout_debug")
    layout_min_text_block_size: int = 8
    layout_min_visual_block_size: int = 12
    layout_min_confidence: float = 0.0
    # Header/footer filtering: exclude text/title blocks within these
    # fractional bands of the page height (configurable via env vars
    # HEADER_RATIO and FOOTER_RATIO).
    header_ratio: float = 0.08
    footer_ratio: float = 0.08
    # When True the first page (index 0) is treated as a cover image;
    # OCR text extraction is skipped for it.  Set COVER_PAGE_AS_IMAGE=true
    # in the environment to enable.
    cover_page_as_image: bool = False
    paddle_vl_api_base_url: str | None = None
    paddle_vl_api_bearer_token: str | None = None
    paddle_vl_api_timeout_seconds: float = 30.0
    paddle_vl_api_default_result_profile: str = "standard"
    public_source_transport_origin: str | None = Field(default=None, validation_alias="ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN")
    processing_operator_enabled: bool = Field(default=False, validation_alias="ATLAS_PROCESSING_OPERATOR_ENABLED")
    processing_operator_token: str | None = Field(default=None, validation_alias="ATLAS_PROCESSING_OPERATOR_TOKEN", repr=False)

    # Browser -> S3-compatible object storage direct upload. This is opt-in so
    # Production and existing Staging deployments retain current behavior until
    # a private bucket, credentials, CORS, and a signing secret are configured.
    direct_upload_enabled: bool = Field(default=False, validation_alias="ATLAS_DIRECT_UPLOAD_ENABLED")
    direct_upload_signing_secret: str | None = Field(
        default=None,
        validation_alias="ATLAS_DIRECT_UPLOAD_SIGNING_SECRET",
        repr=False,
    )
    direct_upload_url_ttl_seconds: int = Field(
        default=900,
        validation_alias="ATLAS_DIRECT_UPLOAD_URL_TTL_SECONDS",
    )
    direct_upload_single_put_max_bytes: int = Field(
        default=100 * 1024 * 1024,
        validation_alias="ATLAS_DIRECT_UPLOAD_SINGLE_PUT_MAX_BYTES",
    )
    object_storage_endpoint_url: str | None = Field(
        default=None,
        validation_alias="ATLAS_OBJECT_STORAGE_ENDPOINT_URL",
    )
    object_storage_bucket: str | None = Field(
        default=None,
        validation_alias="ATLAS_OBJECT_STORAGE_BUCKET",
    )
    object_storage_access_key_id: str | None = Field(
        default=None,
        validation_alias="ATLAS_OBJECT_STORAGE_ACCESS_KEY_ID",
        repr=False,
    )
    object_storage_secret_access_key: str | None = Field(
        default=None,
        validation_alias="ATLAS_OBJECT_STORAGE_SECRET_ACCESS_KEY",
        repr=False,
    )
    object_storage_region: str = Field(
        default="auto",
        validation_alias="ATLAS_OBJECT_STORAGE_REGION",
    )
    object_storage_prefix: str = Field(
        default="atlas",
        validation_alias="ATLAS_OBJECT_STORAGE_PREFIX",
    )

    # Production TXT structure analysis targets OpenAI GPT-5.6 Luna by default.
    # Endpoint/model remain overrideable for controlled evaluation or rollback;
    # credentials never have a repository default and must come from a secret/env.
    txt_structure_api_base_url: str | None = Field(
        default="https://api.openai.com/v1",
        validation_alias="ATLAS_TXT_STRUCTURE_API_BASE_URL",
    )
    txt_structure_api_key: str | None = Field(default=None, validation_alias="ATLAS_TXT_STRUCTURE_API_KEY", repr=False)
    # Existing deployments may already carry the same OpenAI account secret for
    # PDF structure refinement. TXT may safely reuse that credential when its own
    # dedicated secret is absent; the TXT-specific secret always takes precedence.
    pdf_structure_refinement_openai_api_key: str | None = Field(
        default=None,
        validation_alias="PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY",
        repr=False,
    )
    txt_structure_model: str | None = Field(
        default="gpt-5.6-luna",
        validation_alias="ATLAS_TXT_STRUCTURE_MODEL",
    )
    txt_structure_timeout_seconds: float = Field(default=30.0, validation_alias="ATLAS_TXT_STRUCTURE_TIMEOUT_SECONDS")
    txt_structure_temperature: float = Field(default=0.0, validation_alias="ATLAS_TXT_STRUCTURE_TEMPERATURE")
    txt_structure_max_attempts: int = Field(default=3, validation_alias="ATLAS_TXT_STRUCTURE_MAX_ATTEMPTS")
    txt_structure_retry_backoff_seconds: float = Field(
        default=0.5,
        validation_alias="ATLAS_TXT_STRUCTURE_RETRY_BACKOFF_SECONDS",
    )

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
