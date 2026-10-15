# Vision Workbench — Basler 실시간 검사 연동 가이드

Gradio 기반 비전 검사 UI 템플릿입니다. `assets/*.png`는 화면 시안용 정적 이미지입니다. 실제 운용에서는 Basler 카메라가 최신 프레임을 지속 수신하고, 사용자가 **측정 시작**을 누른 시점의 프레임을 모델로 전달해 검사합니다.

```text
Basler USB/GigE 카메라
  → CameraControl (pypylon 수신 스레드, 최신 프레임만 보관)
  ├─ Gradio 타이머 → 실시간 프리뷰
  └─ 측정 시작 → 최신 RGB 프레임 복사 + 임계값 → 모델 추론
      → P1/P2/P3 점수·주석 프레임 → PASS/CHECK·이력 갱신
```

| 기능 | 현재 UI | 실제 연동 후 |
| --- | --- | --- |
| 좌측 `CAPTURE` | `assets/preview.png` 표시 | Basler 최신 프레임 표시 |
| 중앙 검사 화면 | 정적 overview/ROI 이미지 | 마지막 검사 주석 프레임 및 ROI |
| `측정 시작` | 예시 점수 계산 | 최신 프레임으로 모델 추론 |
| `MATCH THRESHOLD` | 0~100 슬라이더/프리셋 | PASS/CHECK 판정 기준 |

## 1. Basler 환경 자동 구성

Windows PowerShell에서 프로젝트 루트로 이동한 뒤 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_basler.ps1
```

스크립트는 다음을 처리합니다.

1. Basler USB/GigE 드라이버가 있는지 확인합니다.
2. 드라이버가 하나라도 있으면 설치 단계를 건너뜁니다.
3. 드라이버가 없으면 공식 pylon Runtime 8.1.0을 다운로드하고 Basler 전자서명을 검증한 뒤 설치합니다. 최초 다운로드는 약 1.25GB이며 Windows 관리자 권한 승인이 필요합니다.
4. 전용 Python 3.12 가상환경을 생성하고 `requirements.txt`의 패키지(`pypylon` 포함)를 설치합니다.
5. pylon Transport Layer와 Python 패키지 연결을 검증합니다.

Basler 연결 방식이 정해져 있다면 필요한 드라이버만 설치할 수 있습니다.

```powershell
.\scripts\setup_basler.ps1 -Interface USB
.\scripts\setup_basler.ps1 -Interface GigE
.\scripts\setup_basler.ps1 -Interface Both
```

- `Auto`(기본값): USB 또는 GigE 드라이버 하나가 있으면 건너뜁니다.
- `USB`: USB 드라이버만 확인/설치합니다.
- `GigE`: GigE 드라이버만 확인/설치합니다.
- `Both`: USB와 GigE가 모두 있어야 설치를 건너뜁니다.

설치하지 않고 드라이버 유무만 검사하려면 다음을 실행합니다.

```powershell
.\scripts\setup_basler.ps1 -CheckOnly
```

인터넷이 없는 환경에서는 pylon Runtime 설치 파일을 준비하고 환경 변수로 경로를 지정합니다.

```powershell
$env:BASLER_INSTALLER = "D:\Installers\pylon Runtime 8.1.0.exe"
.\scripts\setup_basler.ps1
```

환경 구성 후 UI를 실행합니다.

```powershell
.\.venv\Scripts\python.exe .\template.py
```

## 2. Basler 카메라 컨트롤

[scripts/camera_control.py](scripts/camera_control.py)는 제공된 Basler 제어 프로젝트의 `pypylon` 수집 방식을 기반으로 작성되었습니다.

- 카메라 일련번호를 지정하거나 첫 번째 장치를 자동 선택합니다.
- `BayerGR12` 등 픽셀 포맷, 최대 해상도, 노출, 게인, FPS를 적용합니다.
- `GrabStrategy_LatestImageOnly`로 오래된 프레임을 버리고 최신 프레임을 수신합니다.
- UI와 모델에서 안전하게 쓰도록 RGB NumPy 배열의 복사본을 반환합니다.
- GigE 장치에는 버퍼/패킷 지연의 보수적인 기본값을 적용합니다.

연결된 장치를 확인하려면 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe .\scripts\camera_control.py
```

카메라 설정 및 인스턴스는 `template.py` 상단에 한 번만 생성합니다.

```python
from scripts.camera_control import BaslerCameraSettings, CameraControl

camera_settings = BaslerCameraSettings(
    pixel_format="BayerGR12",
    use_max_resolution=True,
    exposure_us=10_000,
    gain=0.0,
    limit_frame_rate=True,
    frame_rate_fps=10.0,
)

# 특정 카메라 사용 시 serial_number="12345678"으로 지정합니다.
camera_control = CameraControl(
    serial_number=None,
    settings=camera_settings,
)
```

`launchApp()`에서 Gradio 서버를 열기 전에 수신을 시작합니다.

```python
def launchApp() -> None:
    camera_control.start()
    demo.launch(
        inbrowser=True,
        allowed_paths=[str(ASSET_DIR)],
        theme=theme,
        css_paths=[CSS_PATH],
        head=renderFragment("head"),
    )
```

앱 종료 시에는 `camera_control.stop()`을 호출해 카메라를 해제해야 합니다. pylon Viewer 등 다른 프로그램이 카메라를 점유 중이면 먼저 종료하세요.

## 3. 실시간 프리뷰 연결

`template.py`의 고정 `gr.Image(value=str(PREVIEW_IMAGE), ...)`를 아래처럼 바꿉니다.

```python
camera_preview = gr.Image(
    label="CAM-01 실시간 영상",
    type="numpy",
    interactive=False,
    elem_classes="asset-frame",
)

def getCameraPreview():
    return camera_control.get_latest_frame()

# UI 갱신은 10 FPS. 실제 카메라 수신 FPS와는 독립적입니다.
preview_timer = gr.Timer(value=0.1)
preview_timer.tick(
    getCameraPreview,
    outputs=camera_preview,
    show_progress="hidden",
)
```

`get_latest_frame()`은 내부 프레임 버퍼의 RGB 복사본을 반환합니다. 따라서 수신 스레드가 화면 표시 또는 추론 중인 프레임을 덮어쓰지 않습니다.

## 4. 추론 어댑터와 임계값 전달

`inference.py`를 추가하고 모델 종류와 무관한 인터페이스를 만듭니다.

```python
from dataclasses import dataclass
import numpy as np


@dataclass
class FrameInferenceResult:
    p1: float  # 0~100, 높을수록 정상인 합격 점수
    p2: float
    p3: float
    annotated_frame: np.ndarray | None = None


def run_frame_inference(frame_rgb: np.ndarray, threshold: float) -> FrameInferenceResult:
    if frame_rgb is None:
        raise ValueError("수신된 카메라 프레임이 없습니다.")
    if not 0 <= threshold <= 100:
        raise ValueError("임계값은 0~100 사이여야 합니다.")

    confidence_threshold = threshold / 100.0  # 예: 72 → 0.72
    # prediction = model.predict(frame_rgb, conf=confidence_threshold)
    # return FrameInferenceResult(...)
    raise NotImplementedError("사용 중인 모델 SDK에 맞게 구현하세요.")
```

P1/P2/P3을 모두 “높을수록 정상”인 0~100 점수로 통일하면 판정식은 다음과 같습니다.

```python
state = "PASS" if min(p1, p2, p3) >= threshold else "CHECK"
```

결함 confidence처럼 “높을수록 불량”인 모델 출력은 `pass_score = (1 - defect_confidence) * 100`으로 바꾸거나, 판정식과 UI 라벨을 함께 반대로 바꿔야 합니다.

## 5. `측정 시작`에 최신 프레임 연결

검사 결과 프레임 출력 영역을 추가합니다.

```python
inspection_output = gr.Image(
    label="마지막 검사 결과", type="numpy", interactive=False
)
```

기존 `inspectSurface()`를 다음과 같은 함수로 교체합니다.

```python
def inspectCamera(
    threshold: float,
    history_records: list[InspectionRecord],
) -> tuple[str, str, list[InspectionRecord], object]:
    frame = camera_control.get_latest_frame()
    try:
        inference = run_frame_inference(frame, threshold)
    except Exception as error:
        error_html = (
            '<div class="summary"><div class="result-state check">ERROR</div>'
            f'<div class="result-caption">{error}</div></div>'
        )
        return error_html, renderHistory(history_records), history_records, frame

    scores = (inference.p1, inference.p2, inference.p3)
    state = "PASS" if min(scores) >= threshold else "CHECK"
    record = InspectionRecord(*scores)
    updated_records = [*history_records, record][-MAX_HISTORY:]
    result_html = renderFragment(
        "result", state=state, state_class=state.lower(),
        average=sum(scores) / len(scores),
        timestamp=datetime.now().strftime("%H:%M:%S"),
        p1=inference.p1, p2=inference.p2, p3=inference.p3,
    )
    output_frame = (
        inference.annotated_frame
        if inference.annotated_frame is not None
        else frame
    )
    return result_html, renderHistory(updated_records), updated_records, output_frame
```

버튼은 프리뷰 컴포넌트를 입력으로 넘기지 않고, 클릭 시점에 카메라 컨트롤의 최신 프레임을 직접 읽습니다.

```python
inspect_button.click(
    inspectCamera,
    inputs=[threshold, history_records],
    outputs=[result, history, history_records, inspection_output],
)
```

### 임계값 전달 예시

```text
측정 시작 클릭 → 최신 RGB 프레임 복사
UI threshold   → 72.0
모델 confidence_threshold → 0.72
모델 반환      → P1=93.4, P2=77.8, P3=71.6
판정           → 71.6 < 72.0 → CHECK
```

프리셋 라디오 버튼(30/50/70)은 이미 `applyThreshold()`를 통해 `threshold` 슬라이더를 바꿉니다. 따라서 버튼에 `threshold`만 전달하면 프리셋과 직접 입력이 모두 같은 값으로 모델에 전달됩니다.

## 운영 체크리스트

- pylon Viewer에서 카메라가 먼저 검색되는지 확인합니다.
- 모델은 앱 시작 시 한 번만 로드하고 매 프레임/버튼마다 재로딩하지 않습니다.
- 카메라 끊김이나 빈 프레임은 `camera_control.get_status()`로 UI/로그에 표시합니다.
- UI 프리뷰 FPS, 카메라 FPS, 모델 FPS를 분리합니다.
- 검사 이력에는 임계값, 카메라 일련번호, 조명값, 모델 버전, 검사 시각을 함께 저장합니다.
- 연속 추론은 Gradio 타이머에서 직접 모델을 호출하지 말고 별도 워커에서 최신 프레임만 처리합니다.

## 파일 역할

- `template.py`: Gradio UI, 프리뷰/버튼 이벤트, 임계값, 결과/이력
- `scripts/camera_control.py`: Basler 카메라 제어와 최신 프레임 수신
- `scripts/setup_basler.ps1`: 드라이버/pylon Runtime/Python 패키지 자동 구성
- `inference.py` (추가 필요): 최신 프레임을 실제 모델에 전달하는 어댑터
- `scripts/led_control.py`: 4채널 LED 밝기 제어
