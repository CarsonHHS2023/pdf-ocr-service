"""Application entrypoint for Hugging Face Spaces."""

import os

import uvicorn

from app.logging_config import configure_application_logging


if __name__ == "__main__":
    # Keep the OCRmyPDF comparison isolated from all post-crop image processing.
    # This deliberately overrides any inherited deployment setting for the
    # experiment branch so screenshots, figures, and tables are never sent to an
    # LLM/image-edit provider.
    os.environ["VISUAL_ASSET_ENHANCEMENT_ENABLED"] = "0"
    os.environ["PDF_VISUAL_ASSET_ENHANCEMENT_ENABLED"] = "0"

    configure_application_logging()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=7860,
        reload=False,
        access_log=False,
        log_config=None,
    )
