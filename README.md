# Vision Workbench — 실시간 카메라 추론 연동 가이드

이 Gradio 템플릿의 `assets/*.png`는 화면 시안용 정적 이미지입니다. 실제 운영에서는 카메라가 최신 프레임을 계속 수신하고, 사용자가 **측정 시작**을 누른 시점의 프레임(또는 최근 N개 프레임)을 모델로 추론합니다.

```text
카메라 SDK / RTSP / USB 카메라
  → CameraService (수신 스레드, 최신 프레임만 보관)
  ├─ UI 타이머 → 실시간 프리뷰
  └─ 측정 시작 → 최신 프레임 복사 + threshold → 모델 추론
      → P1/P2/P3 점수·주석 프레임 → PASS/CHECK·이력 표시
```

| 기능 | 현재 | 연동 후 |
| --- | --- | --- |
| 좌측 `CAPTURE` | `assets/preview.png` 고정 표시 | 최신 카메라 프레임 |
| 중앙 화면 | 정적 overview/ROI 이미지 | 마지막 검사 주석 프레임·ROI |
| `측정 시작` | 예시 점수 계산 | 최신 프레임으로 실제 모델 추론 |
| `MATCH THRESHOLD` | 0~100 슬라이더/프리셋 | PASS/CHECK 판정 기준 |

`template.py`의 `inspectSurface()`는 현재 모델을 호출하지 않습니다. 아래의 카메라 수신 및 추론 함수로 교체해야 합니다.

## 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install opencv-python  # OpenCV로 USB/RTSP 수신 시
python template.py
```

LED 포트가 다른 경우에만 다음 값을 설정합니다.

```powershell
$env:LIGHT_SERIAL_PORT = "COM5"
$env:LIGHT_SERIAL_BAUDRATE = "9600"
```

## 1. 카메라 수신 서비스

프로젝트 루트에 `camera_service.py`를 만듭니다. `source=0`은 첫 USB 카메라입니다. RTSP는 URL을 넣고, 산업용 카메라는 `cv2.VideoCapture` 부분만 제조사 SDK의 프레임 콜백으로 교체하면 됩니다.

```python
# camera_service.py
from threading import Event, Lock, Thread
import time
import cv2
import numpy as np


class CameraService:
    def __init__(self, source: int | str = 0) -> None:
        self.source = source
        self._frame: np.ndarray | None = None
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self.error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self) -> None:
        camera = cv2.VideoCapture(self.source)
        if not camera.isOpened():
            self.error = f"카메라를 열 수 없습니다: {self.source}"
            return
        try:
            while not self._stop.is_set():
                ok, frame = camera.read()
                if not ok:
                    self.error = "카메라 프레임 수신에 실패했습니다."
                    time.sleep(0.05)
                    continue
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                with self._lock:
                    self._frame = frame_rgb
                self.error = None
        finally:
            camera.release()

    def get_latest_frame(self) -> np.ndarray | None:
        # 카메라 스레드가 덮어쓰지 못하도록 복사본을 반환한다.
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
```

프레임을 락 없이 공유하거나 모델에 원본 버퍼를 넘기지 마세요. 수신 도중 덮어써진 프레임을 추론하는 문제가 생길 수 있습니다.

## 2. 프레임 추론 어댑터

`inference.py`는 UI와 카메라 종류에서 독립적으로 둡니다. UI 임계값은 퍼센트(0~100)이며, 0~1 confidence를 쓰는 모델은 여기에서 한 번만 변환합니다.

```python
# inference.py
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

    # 모델은 앱 시작 시 한 번만 로드하여 재사용합니다.
    # prediction = model.predict(frame_rgb, conf=confidence_threshold)
    # return FrameInferenceResult(
    #     p1=prediction.pass_scores["P1"] * 100,
    #     p2=prediction.pass_scores["P2"] * 100,
    #     p3=prediction.pass_scores["P3"] * 100,
    #     annotated_frame=prediction.annotated_rgb,
    # )
    raise NotImplementedError("사용 중인 모델 SDK에 맞게 구현하세요.")
```

P1/P2/P3은 모두 “높을수록 정상”인 점수로 통일하는 것을 권장합니다.

```python
state = "PASS" if min(p1, p2, p3) >= threshold else "CHECK"
```

모델이 “높을수록 결함”인 defect confidence를 반환한다면 `pass_score = (1 - defect_confidence) * 100`으로 바꾸거나, 판정식과 UI 라벨을 함께 반대로 바꾸세요. 둘을 혼합하면 임계값 방향이 반대가 됩니다.

## 3. 실시간 프리뷰 연결

`template.py` 상단에 추가합니다.

```python
from camera_service import CameraService
from inference import run_frame_inference

CAMERA_SOURCE = 0
# RTSP 예: CAMERA_SOURCE = "rtsp://user:password@192.168.0.10:554/stream"
camera_service = CameraService(CAMERA_SOURCE)
```

좌측 `CAPTURE` 블록의 기존 정적 `gr.Image(value=str(PREVIEW_IMAGE), ...)`를 교체합니다.

```python
camera_preview = gr.Image(
    label="CAM-01 실시간 영상",
    type="numpy",
    interactive=False,
    elem_classes="asset-frame",
)

def getCameraPreview():
    return camera_service.get_latest_frame()

preview_timer = gr.Timer(value=0.1)  # 브라우저 프리뷰 10 FPS
preview_timer.tick(getCameraPreview, outputs=camera_preview, show_progress="hidden")
```

`launchApp()`에서 웹 서버보다 먼저 카메라를 시작합니다.

```python
def launchApp() -> None:
    camera_service.start()
    demo.launch(
        inbrowser=True,
        allowed_paths=[str(ASSET_DIR)],
        theme=theme,
        css_paths=[CSS_PATH],
        head=renderFragment("head"),
    )
```

UI 갱신 주기(보통 5~15 FPS)는 카메라 원본 FPS와 별개입니다. 고속 카메라 영상 전체를 브라우저로 전송할 필요는 없습니다.

## 4. 측정 버튼에 최신 프레임과 임계값 전달

검사 출력 영역을 추가합니다.

```python
inspection_output = gr.Image(
    label="마지막 검사 결과", type="numpy", interactive=False
)
```

기존 `inspectSurface()`를 아래로 교체합니다.

```python
def inspectCamera(
    threshold: float,
    history_records: list[InspectionRecord],
) -> tuple[str, str, list[InspectionRecord], object]:
    frame = camera_service.get_latest_frame()
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
    return result_html, renderHistory(updated_records), updated_records, (
        inference.annotated_frame if inference.annotated_frame is not None else frame
    )
```

버튼은 프리뷰를 입력으로 넘기지 않습니다. 클릭 시점에 서비스의 최신 프레임을 직접 읽습니다.

```python
inspect_button.click(
    inspectCamera,
    inputs=[threshold, history_records],
    outputs=[result, history, history_records, inspection_output],
)
```

### 임계값 전달 예시

```text
측정 시작 클릭 → 최신 frame_rgb 복사
UI threshold   → 72.0
모델 confidence_threshold → 0.72
모델 반환      → P1=93.4, P2=77.8, P3=71.6
판정           → 71.6 < 72.0 → CHECK
```

프리셋 라디오 버튼(30/50/70)은 이미 `applyThreshold()`를 통해 `threshold` 슬라이더를 바꿉니다. 따라서 버튼에 `threshold`만 전달하면 프리셋과 직접 입력이 모두 동일하게 모델에 전달됩니다.

## 연속 추론이 필요한 경우

위 구조는 “라이브 화면을 보다가 버튼으로 검사”하는 방식입니다. 모든 프레임을 계속 검사해야 한다면 UI 타이머에서 모델을 호출하지 마세요. 타이머 이벤트가 중첩되어 작업이 밀릴 수 있습니다.

별도 워커 스레드/프로세스가 최신 프레임만 추론하고 최신 결과 하나만 공유 메모리에 저장하게 하세요. UI 타이머는 결과를 표시하고, 버튼은 결과 확정 및 이력 저장만 합니다. 이렇게 하면 카메라 수신, 모델 연산, 브라우저 렌더링이 서로 막지 않습니다.

## 운영 체크리스트

- 모델은 앱 시작 시 한 번만 로드합니다.
- 카메라 끊김/빈 프레임/재연결 상태를 로그와 화면에 표시합니다.
- 수신·추론 사이에는 프레임 복사본을 사용합니다.
- UI FPS, 카메라 FPS, 모델 FPS를 분리합니다.
- 이력에 임계값, 카메라 ID, 조명값, 모델 버전, 검사 시각을 함께 저장합니다.
- `assets/`는 시안용으로 보존하고 실시간 프레임은 메모리에서 처리합니다.

## 파일 역할

- `template.py`: Gradio UI, 프리뷰/버튼 이벤트, 임계값, 결과/이력
- `camera_service.py` (추가): 카메라 또는 RTSP 수신과 최신 프레임 보관
- `inference.py` (추가): 최신 프레임을 모델에 전달하는 어댑터
- `led_control.py`: 4채널 LED 밝기 제어
