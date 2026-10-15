from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import gradio as gr
from led_control import (
    BAUD_RATE,
    COM_PORT,
    OUTPUT_MAX,
    LightCommunicationError,
    set_channel_brightness,
    set_four_brightness,
)


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
MAX_HISTORY = 5
DEFAULT_P1 = 97.31
DEFAULT_P2 = 97.54
DEFAULT_P3 = 96.88
DEFAULT_BRIGHTNESS = 54.0
DEFAULT_THRESHOLD = 72.0
LIGHT_COUNT = 4
DEFAULT_LIGHTING_LABEL = f"4-CH CONTROL  ·  AVG {DEFAULT_BRIGHTNESS:.0f}"
THRESHOLD_PRESETS: tuple[int, ...] = (30, 50, 70)


@dataclass(frozen=True, slots=True)
class InspectionRecord:
    p1: float
    p2: float
    p3: float


INITIAL_HISTORY: tuple[InspectionRecord, ...] = (
    InspectionRecord(p1=DEFAULT_P1, p2=DEFAULT_P2, p3=DEFAULT_P3),
)


def renderTemplate(path: Path, **values: object) -> str:
    return path.read_text(encoding="utf-8").format(**values)


def renderFragment(name: str, **values: object) -> str:
    root = ElementTree.parse(FRAGMENTS_TEMPLATE_PATH).getroot()
    fragment = root.find(f"template[@id='{name}']")
    if fragment is None:
        raise ValueError(f"Unknown template fragment: {name}")
    content = "".join(
        ElementTree.tostring(child, encoding="unicode", method="html")
        for child in fragment
    )
    return content.format(**values)


def renderOverview() -> str:
    return renderTemplate(
        OVERVIEW_TEMPLATE_PATH,
        overview_src=f"/gradio_api/file={OVERVIEW_IMAGE.as_posix()}",
        p1_src=f"/gradio_api/file={P1_IMAGE.as_posix()}",
        p2_src=f"/gradio_api/file={P2_IMAGE.as_posix()}",
        p3_src=f"/gradio_api/file={P3_IMAGE.as_posix()}",
    )


def renderHistory(records: Sequence[InspectionRecord]) -> str:
    rows: list[str] = []
    for index in range(MAX_HISTORY):
        position = index + 1
        if index >= len(records):
            rows.append(renderFragment("history_empty_row", position=position))
            continue

        record = records[index]
        rows.append(
            renderFragment(
                "history_row",
                position=position,
                p1=record.p1,
                p2=record.p2,
                p3=record.p3,
            )
        )
    return renderFragment("history_list", rows="".join(rows))


def calculateLighting(
    light_1: float,
    light_2: float,
    light_3: float,
    light_4: float,
) -> tuple[float, str]:
    average = sum((light_1, light_2, light_3, light_4)) / LIGHT_COUNT
    label = f"4-CH CONTROL  ·  AVG {average:.0f}"
    return average, label


def applyLighting(
    light_1: float,
    light_2: float,
    light_3: float,
    light_4: float,
) -> tuple[float, str, object, str]:
    """Send all four channel settings to the lighting controller."""
    values = (light_1, light_2, light_3, light_4)
    average, label = calculateLighting(*values)
    try:
        transmissions = set_four_brightness(*values)
    except (LightCommunicationError, ValueError) as error:
        message = f"⚠ 전송 실패: {error}"
        return average, label, gr.update(visible=True), message

    frames = " · ".join(sent.packet.hex(" ").upper() for sent in transmissions)
    message = f"✓ 전송 완료 ({COM_PORT}, {BAUD_RATE} bps): {frames}"
    return average, label, gr.update(visible=False), message


def applyLightChannel(
    channel: int,
    light_1: float,
    light_2: float,
    light_3: float,
    light_4: float,
) -> tuple[float, str, str]:
    """Send only the slider channel after the user releases it."""
    values = (light_1, light_2, light_3, light_4)
    average, label = calculateLighting(*values)
    try:
        sent = set_channel_brightness(channel, values[channel - 1])
    except (LightCommunicationError, ValueError) as error:
        return average, label, f"⚠ CH{channel:02d} 전송 실패: {error}"

    message = (
        f"✓ CH{channel:02d} 적용 완료 ({COM_PORT}, {BAUD_RATE} bps): "
        f"{sent.packet.hex(' ').upper()}"
    )
    return average, label, message


def showLighting() -> object:
    return gr.update(visible=True)


def hideLighting() -> object:
    return gr.update(visible=False)


def applyThreshold(preset: int | float | None) -> float:
    if preset not in THRESHOLD_PRESETS:
        raise ValueError(f"Unsupported threshold preset: {preset}")
    return float(preset)


def syncThreshold(threshold: float) -> int | None:
    if threshold not in THRESHOLD_PRESETS:
        return None
    return int(threshold)


def inspectSurface(
    brightness: float,
    threshold: float,
    history_records: list[InspectionRecord],
) -> tuple[str, str, list[InspectionRecord]]:
    drift = (
        (brightness - DEFAULT_BRIGHTNESS) * 0.009
        + (threshold - DEFAULT_THRESHOLD) * 0.006
    )
    scores = [DEFAULT_P1 + drift, DEFAULT_P2 + drift, DEFAULT_P3 + drift]
    state = "PASS" if min(scores) >= threshold else "CHECK"
    record = InspectionRecord(p1=scores[0], p2=scores[1], p3=scores[2])
    updated_records = [*history_records, record][-MAX_HISTORY:]
    return (
        renderFragment(
            "result",
            state=state,
            state_class=state.lower(),
            average=sum(scores) / 3,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            p1=scores[0],
            p2=scores[1],
            p3=scores[2],
        ),
        renderHistory(updated_records),
        updated_records,
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
    history_records = gr.State(value=list(INITIAL_HISTORY))
    average_brightness = gr.State(value=DEFAULT_BRIGHTNESS)
    with gr.Row(equal_height=False, elem_classes="main-grid"):
        with gr.Column(scale=2, elem_classes="side"):
            with gr.Column(scale=0, elem_classes="ui-block"):
                gr.HTML(renderFragment("capture_label"))
                gr.Image(value=str(PREVIEW_IMAGE), show_label=False, interactive=False, elem_classes="asset-frame")
            with gr.Column(
                scale=0,
                elem_classes=["ui-block", "control-group"],
            ):
                gr.HTML(renderFragment("lighting_label"))
                lighting_button = gr.Button(
                    DEFAULT_LIGHTING_LABEL,
                    elem_classes="lighting-open-button",
                )
                gr.HTML(renderFragment("lighting_hint"))
            with gr.Column(
                scale=0,
                elem_classes=["ui-block", "control-group"],
            ):
                gr.HTML(renderFragment("detection_label"))
                threshold = gr.Slider(
                    0,
                    100,
                    value=DEFAULT_THRESHOLD,
                    step=1,
                    label="MATCH THRESHOLD",
                )
                gr.HTML(renderFragment("threshold_preset_label"))
                threshold_preset = gr.Radio(
                    choices=[(f"{value}%", value) for value in THRESHOLD_PRESETS],
                    value=None,
                    container=False,
                    show_label=False,
                    elem_classes="threshold-presets",
                )
                gr.HTML(renderFragment("detection_hint"))

        with gr.Column(scale=6, elem_classes="workbench"):
            with gr.Column(elem_classes="ui-block"):
                gr.HTML(renderOverview())
                inspect_button = gr.Button("측정 시작", variant="primary", elem_classes="overview-inspect-button")

        with gr.Column(scale=2, elem_classes="results"):
            with gr.Column(elem_classes="ui-block"):
                gr.HTML(renderFragment("result_label"))
                result = gr.HTML(renderFragment("result_initial"))
            with gr.Column(elem_classes="ui-block"):
                gr.HTML(renderFragment("history_label"))
                history = gr.HTML(renderHistory(INITIAL_HISTORY))
            with gr.Column(elem_classes="ui-block"):
                gr.HTML(renderFragment("system_status"))

    with gr.Column(visible=False, elem_classes="lighting-modal") as lighting_modal:
        with gr.Column(elem_classes="lighting-dialog"):
            gr.HTML(renderFragment("lighting_modal_header"))
            light_1 = gr.Slider(
                0,
                100,
                value=DEFAULT_BRIGHTNESS,
                step=1,
                label="LIGHT 01 BRIGHTNESS",
            )
            light_2 = gr.Slider(
                0,
                100,
                value=DEFAULT_BRIGHTNESS,
                step=1,
                label="LIGHT 02 BRIGHTNESS",
            )
            light_3 = gr.Slider(
                0,
                100,
                value=DEFAULT_BRIGHTNESS,
                step=1,
                label="LIGHT 03 BRIGHTNESS",
            )
            light_4 = gr.Slider(
                0,
                100,
                value=DEFAULT_BRIGHTNESS,
                step=1,
                label="LIGHT 04 BRIGHTNESS",
            )
            lighting_close = gr.Button(
                "설정 적용 후 닫기",
                variant="primary",
                elem_classes="lighting-close-button",
            )
            serial_status = gr.Markdown(
                f"통신 설정: `{COM_PORT}` · `{BAUD_RATE}` bps · 8N1 · 출력 0–`{OUTPUT_MAX}`",
                elem_classes="serial-status",
            )

    light_controls = (light_1, light_2, light_3, light_4)

    lighting_button.click(
        showLighting,
        outputs=lighting_modal,
        show_progress="hidden",
    )
    lighting_close.click(
        applyLighting,
        inputs=light_controls,
        outputs=[average_brightness, lighting_button, lighting_modal, serial_status],
        show_progress="hidden",
    )

    for light_control in light_controls:
        light_control.change(
            calculateLighting,
            inputs=light_controls,
            outputs=[average_brightness, lighting_button],
            show_progress="hidden",
        )

    for channel, light_control in enumerate(light_controls, start=1):
        light_control.release(
            lambda light_1, light_2, light_3, light_4, selected_channel=channel: applyLightChannel(
                selected_channel,
                light_1,
                light_2,
                light_3,
                light_4,
            ),
            inputs=light_controls,
            outputs=[average_brightness, lighting_button, serial_status],
            show_progress="hidden",
        )

    threshold_preset.input(
        applyThreshold,
        inputs=threshold_preset,
        outputs=threshold,
        show_progress="hidden",
    )
    threshold.input(
        syncThreshold,
        inputs=threshold,
        outputs=threshold_preset,
        show_progress="hidden",
    )

    inspect_button.click(
        inspectSurface,
        inputs=[average_brightness, threshold, history_records],
        outputs=[result, history, history_records],
    )


def launchApp() -> None:
    demo.launch(
        inbrowser=True,
        allowed_paths=[str(ASSET_DIR)],
        theme=theme,
        css_paths=[CSS_PATH],
        head=renderFragment("head"),
    )


if __name__ == "__main__":
    launchApp()
