from app.processing.pdf_visual_asset_enhancement import _enhancement_prompt
from app.structured_content_v2.model import AssetRoleV2


def test_visual_enhancement_prompt_requires_cleanup_without_content_rewrite() -> None:
    prompt = _enhancement_prompt(
        asset_role=AssetRoleV2.FIGURE,
        alt_text="stock chart",
    )

    for requirement in (
        "gray or pale yellow paper tint",
        "bleed-through and show-through",
        "scan speckles, dust, stains, smudges",
        "improved local contrast",
        "gentle sharpening",
        "Chinese and other text",
        "numbers, decimal points, table values",
        "Do not redraw, translate, replace, infer, invent, omit, crop, or rearrange",
    ):
        assert requirement in prompt
