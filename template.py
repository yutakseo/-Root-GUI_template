from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import gradio as gr


APP_DIR = Path(__file__).parent
ASSET_DIR = APP_DIR / "assets"
TEMPLATE_DIR = APP_DIR / "templates"
CSS_PATH = TEMPLATE_DIR / "style.css"
OVERVIEW_TEMPLATE_PATH = TEMPLATE_DIR / "overview.html"
FRAGMENTS_TEMPLATE_PATH = TEMPLATE_DIR / "fragments.html"
PREVIEW_IMAGE = ASSET_DIR / "preview.png"
OVERVIEW_IMAGE = ASSET_DIR / "overview.png"
P1_IMAGE = ASSET_DIR / "P1.png"
P2_IMAGE = ASSET_DIR / "P2.png"
P3_IMAGE = ASSET_DIR / "P3.png"


def render_template(path: Path, **values: object) -> str:
    return path.read_text(encoding="utf-8").format(**values)


def render_fragment(name: str, **values: object) -> str:
    root = ElementTree.parse(FRAGMENTS_TEMPLATE_PATH).getroot()
    fragment = root.find(f"template[@id='{name}']")
    if fragment is None:
        raise ValueError(f"Unknown template fragment: {name}")
    content = "".join(
        ElementTree.tostring(child, encoding="unicode", method="html")
        for child in fragment
    )
    return content.format(**values)


def render_overview() -> str:
    return render_template(
        OVERVIEW_TEMPLATE_PATH,
        overview_src=f"/gradio_api/file={OVERVIEW_IMAGE.as_posix()}",
        p1_src=f"/gradio_api/file={P1_IMAGE.as_posix()}",
        p2_src=f"/gradio_api/file={P2_IMAGE.as_posix()}",
        p3_src=f"/gradio_api/file={P3_IMAGE.as_posix()}",
    )


def inspect_surface(brightness: int, threshold: int):
    drift = (brightness - 54) * 0.009 + (threshold - 72) * 0.006
    scores = [97.31 + drift, 97.54 + drift, 96.88 + drift]
    state = "PASS" if min(scores) >= threshold else "CHECK"
    return (
        render_fragment("metrics", p1=scores[0], p2=scores[1], p3=scores[2]),
        render_fragment(
            "summary",
            state=state,
            state_class=state.lower(),
            average=sum(scores) / 3,
            timestamp=datetime.now().strftime("%H:%M:%S"),
        ),
    )


theme = gr.themes.Base(
    font=[gr.themes.GoogleFont("IBM Plex Sans KR"), "Segoe UI", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "Consolas", "monospace"],
).set(
    body_background_fill="#1e1e1e",
    body_text_color="#cccccc",
    block_background_fill="#252526",
    block_border_width="0px",
    block_radius="0px",
    input_background_fill="#3c3c3c",
    input_border_color="#3c3c3c",
    input_border_color_focus="#007fd4",
    button_primary_background_fill="#0e639c",
    button_primary_background_fill_hover="#1177bb",
    button_primary_text_color="#ffffff",
)


with gr.Blocks(title="Vision Workbench") as demo:
    with gr.Row(equal_height=False, elem_classes="main-grid"):
        with gr.Column(scale=2, elem_classes="side"):
            with gr.Column(elem_classes="ui-block"):
                gr.HTML(render_fragment("capture_label"))
                gr.Image(value=str(PREVIEW_IMAGE), show_label=False, interactive=False, elem_classes="asset-frame")
            with gr.Column(elem_classes=["ui-block", "control-group"]):
                gr.HTML(render_fragment("lighting_label"))
                brightness = gr.Slider(0, 100, value=54, step=1, label="LED BRIGHTNESS")
                gr.HTML(render_fragment("lighting_hint"))
            with gr.Column(elem_classes=["ui-block", "control-group"]):
                gr.HTML(render_fragment("detection_label"))
                threshold = gr.Slider(0, 100, value=72, step=1, label="MATCH THRESHOLD")
                gr.HTML(render_fragment("detection_hint"))

        with gr.Column(scale=6, elem_classes="workbench"):
            with gr.Column(elem_classes="ui-block"):
                gr.HTML(render_overview())
                inspect_button = gr.Button("측정 시작", variant="primary", elem_classes="overview-inspect-button")

        with gr.Column(scale=2, elem_classes="results"):
            with gr.Column(elem_classes="ui-block"):
                gr.HTML(render_fragment("result_label"))
                summary = gr.HTML(render_fragment("summary_initial"))
            with gr.Column(elem_classes="ui-block"):
                gr.HTML(render_fragment("points_label"))
                metrics = gr.HTML(render_fragment("metrics_initial"))
            with gr.Column(elem_classes="ui-block"):
                gr.HTML(render_fragment("system_status"))

    inspect_button.click(inspect_surface, inputs=[brightness, threshold], outputs=[metrics, summary])


demo.launch(
    inbrowser=True,
    allowed_paths=[str(ASSET_DIR)],
    theme=theme,
    css_paths=[CSS_PATH],
    head=render_fragment("head"),
)
