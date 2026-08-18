"""Paddle-VL package exports without eagerly importing the HTTP client."""
from app.processing.paddle_vl.models import PaddleVLDocument, PaddleVLJobRequest, PaddleVLOptions
__all__ = ["PaddleVLClient", "PaddleVLClientConfig", "PaddleVLDocument", "PaddleVLJobRequest", "PaddleVLOptions"]
def __getattr__(name):
    if name in {"PaddleVLClient", "PaddleVLClientConfig"}:
        from app.processing.paddle_vl.client import PaddleVLClient, PaddleVLClientConfig
        return {"PaddleVLClient": PaddleVLClient, "PaddleVLClientConfig": PaddleVLClientConfig}[name]
    raise AttributeError(name)
