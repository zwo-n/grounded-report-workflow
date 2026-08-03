"""
pipeline_logger.py - 파이프라인 실행 로그/디버깅 유틸리티

가벼운 데코레이터 기반으로 파이프라인 각 단계의 실행 로그를 캡처하고
실시간 스트리밍(JSON Lines, SSE)을 지원합니다.

사용법:
    from pipeline.pipeline_logger import log_step, PipelineContext, print_summary

    ctx = PipelineContext("my_pipeline")

    @log_step(ctx, "데이터 로드")
    def load_data(path):
        ...

    # 실행 후 요약 출력
    print_summary(ctx)
"""

import functools
import json
import logging
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from queue import Queue
from typing import Any, Callable, Optional
from enum import Enum


# =============================================================================
# 로그 포맷터 설정
# =============================================================================
class JsonFormatter(logging.Formatter):
    """JSON Lines 포맷 로거"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # 추가 데이터가 있으면 병합
        if hasattr(record, "step_event"):
            log_data["event"] = record.step_event
        return json.dumps(log_data, ensure_ascii=False, default=str)


def setup_json_logger(name: str = "pipeline", stream=None) -> logging.Logger:
    """JSON 포맷 로거 생성"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    return logger


# =============================================================================
# 단계 상태 및 이벤트 데이터 클래스
# =============================================================================
class StepStatus(str, Enum):
    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class StepEvent:
    """단계 실행 이벤트"""
    step_name: str
    status: StepStatus
    started_at: str
    ended_at: Optional[str] = None
    duration_ms: Optional[float] = None
    input_summary: Optional[dict] = None
    output_summary: Optional[Any] = None
    error: Optional[str] = None
    traceback: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


@dataclass
class PipelineContext:
    """파이프라인 실행 컨텍스트 - 전체 실행 상태 추적"""
    pipeline_name: str
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    ended_at: Optional[str] = None
    total_duration_ms: Optional[float] = None
    steps: list[StepEvent] = field(default_factory=list)
    event_queue: Optional[Queue] = None  # SSE 스트리밍용
    json_logger: Optional[logging.Logger] = None
    stream_to_console: bool = True
    _start_time: float = field(default_factory=time.perf_counter)

    def __post_init__(self):
        if self.json_logger is None and self.stream_to_console:
            self.json_logger = setup_json_logger(self.pipeline_name)

    def add_step(self, event: StepEvent) -> None:
        """단계 이벤트 추가 및 스트리밍"""
        self.steps.append(event)

        # JSON Lines 로그 출력
        if self.json_logger:
            record = logging.LogRecord(
                name=self.pipeline_name,
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=f"[{event.status.value}] {event.step_name}",
                args=(),
                exc_info=None,
            )
            record.step_event = event.to_dict()
            self.json_logger.handle(record)

        # SSE 큐에 푸시
        if self.event_queue:
            self.event_queue.put(event)

    def finish(self) -> None:
        """파이프라인 종료 마킹"""
        self.ended_at = datetime.now().isoformat()
        self.total_duration_ms = (time.perf_counter() - self._start_time) * 1000

    def get_summary(self) -> dict:
        """실행 요약 반환"""
        # started 이벤트 제외하고 완료된 단계만 카운트
        completed = [s for s in self.steps if s.status != StepStatus.STARTED]
        return {
            "pipeline_name": self.pipeline_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "total_duration_ms": self.total_duration_ms,
            "total_steps": len(completed),
            "successful_steps": sum(1 for s in completed if s.status == StepStatus.SUCCESS),
            "failed_steps": sum(1 for s in completed if s.status == StepStatus.FAILED),
            "steps": [s.to_dict() for s in completed],
        }


# =============================================================================
# 값 요약 유틸리티
# =============================================================================
def summarize_value(value: Any, max_length: int = 200) -> Any:
    """값을 요약하여 반환 (너무 크면 잘라냄)"""
    if value is None:
        return None

    if isinstance(value, str):
        if len(value) > max_length:
            return value[:max_length] + f"... ({len(value)} chars)"
        return value

    if isinstance(value, (list, tuple)):
        if len(value) > 5:
            return {
                "type": type(value).__name__,
                "length": len(value),
                "preview": [summarize_value(v, 50) for v in value[:3]],
            }
        return [summarize_value(v, 50) for v in value]

    if isinstance(value, dict):
        if len(value) > 10:
            keys = list(value.keys())[:5]
            return {
                "type": "dict",
                "keys_count": len(value),
                "preview_keys": keys,
            }
        return {k: summarize_value(v, 50) for k, v in list(value.items())[:10]}

    if hasattr(value, "__dict__"):
        return {"type": type(value).__name__, "repr": str(value)[:max_length]}

    return value


def summarize_args(args: tuple, kwargs: dict) -> dict:
    """함수 인자 요약"""
    result = {}

    if args:
        result["args"] = [summarize_value(a) for a in args]

    if kwargs:
        result["kwargs"] = {k: summarize_value(v) for k, v in kwargs.items()}

    return result if result else None


# =============================================================================
# 데코레이터
# =============================================================================
def log_step(
    ctx: PipelineContext,
    step_name: Optional[str] = None,
    capture_input: bool = True,
    capture_output: bool = True,
):
    """
    파이프라인 단계 로깅 데코레이터

    Args:
        ctx: PipelineContext 인스턴스
        step_name: 단계 이름 (None이면 함수명 사용)
        capture_input: 입력 인자 캡처 여부
        capture_output: 출력 결과 캡처 여부

    Example:
        @log_step(ctx, "섹션 계획 생성")
        def plan_sections(request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = step_name or func.__name__
            start_time = time.perf_counter()
            started_at = datetime.now().isoformat()

            # 시작 이벤트
            start_event = StepEvent(
                step_name=name,
                status=StepStatus.STARTED,
                started_at=started_at,
                input_summary=summarize_args(args, kwargs) if capture_input else None,
            )
            ctx.add_step(start_event)

            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000

                # 성공 이벤트
                success_event = StepEvent(
                    step_name=name,
                    status=StepStatus.SUCCESS,
                    started_at=started_at,
                    ended_at=datetime.now().isoformat(),
                    duration_ms=round(duration_ms, 2),
                    input_summary=summarize_args(args, kwargs) if capture_input else None,
                    output_summary=summarize_value(result) if capture_output else None,
                )
                ctx.add_step(success_event)

                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000

                # 실패 이벤트
                fail_event = StepEvent(
                    step_name=name,
                    status=StepStatus.FAILED,
                    started_at=started_at,
                    ended_at=datetime.now().isoformat(),
                    duration_ms=round(duration_ms, 2),
                    input_summary=summarize_args(args, kwargs) if capture_input else None,
                    error=str(e),
                    traceback=traceback.format_exc(),
                )
                ctx.add_step(fail_event)
                raise

        return wrapper
    return decorator


# =============================================================================
# 콘솔 출력 (타임라인 뷰)
# =============================================================================
def print_summary(ctx: PipelineContext, detailed: bool = False) -> None:
    """파이프라인 실행 요약을 콘솔에 출력"""
    ctx.finish()
    summary = ctx.get_summary()

    print("\n" + "=" * 70)
    print(f"  Pipeline: {summary['pipeline_name']}")
    print("=" * 70)
    print(f"  시작: {summary['started_at']}")
    print(f"  종료: {summary['ended_at']}")
    print(f"  총 소요시간: {summary['total_duration_ms']:.2f}ms")
    print(f"  단계: {summary['successful_steps']}/{summary['total_steps']} 성공", end="")
    if summary['failed_steps'] > 0:
        print(f" ({summary['failed_steps']} 실패)")
    else:
        print()
    print("-" * 70)

    # 타임라인
    print("\n  Timeline:")
    print("  " + "-" * 66)

    # 성공/실패 이벤트만 표시 (started 제외)
    completed_steps = [s for s in ctx.steps if s.status != StepStatus.STARTED]

    for i, step in enumerate(completed_steps):
        status_icon = "✓" if step.status == StepStatus.SUCCESS else "✗"
        status_color = "" if step.status == StepStatus.SUCCESS else "[FAILED] "

        print(f"  {status_icon} {status_color}{step.step_name}")
        print(f"      소요시간: {step.duration_ms:.2f}ms")

        if detailed:
            if step.input_summary:
                input_str = json.dumps(step.input_summary, ensure_ascii=False, default=str)
                if len(input_str) > 100:
                    input_str = input_str[:100] + "..."
                print(f"      입력: {input_str}")

            if step.output_summary:
                output_str = json.dumps(step.output_summary, ensure_ascii=False, default=str)
                if len(output_str) > 100:
                    output_str = output_str[:100] + "..."
                print(f"      출력: {output_str}")

        if step.error:
            print(f"      에러: {step.error}")
            if detailed and step.traceback:
                for line in step.traceback.strip().split("\n")[-3:]:
                    print(f"        {line}")

        if i < len(completed_steps) - 1:
            print("      │")

    print("  " + "-" * 66)
    print()


# =============================================================================
# SSE 스트리밍 유틸리티 (FastAPI/Flask 등에서 사용)
# =============================================================================
def create_sse_generator(ctx: PipelineContext):
    """
    SSE 이벤트 제너레이터 생성

    Example (FastAPI):
        @app.get("/pipeline/stream")
        async def stream_pipeline():
            ctx = PipelineContext("my_pipeline", event_queue=Queue())
            # 백그라운드에서 파이프라인 실행
            return StreamingResponse(
                create_sse_generator(ctx),
                media_type="text/event-stream"
            )
    """
    def generator():
        while True:
            if ctx.event_queue is None:
                break

            try:
                event = ctx.event_queue.get(timeout=30)
                yield f"data: {event.to_json()}\n\n"

                # 파이프라인 종료 시 마지막 이벤트
                if ctx.ended_at:
                    yield f"data: {json.dumps({'type': 'complete', 'summary': ctx.get_summary()})}\n\n"
                    break

            except Exception:
                # 타임아웃 시 heartbeat
                yield f": heartbeat\n\n"

    return generator()


# =============================================================================
# 컨텍스트 매니저 버전
# =============================================================================
class PipelineRun:
    """
    컨텍스트 매니저로 파이프라인 실행 추적

    Example:
        with PipelineRun("my_pipeline") as ctx:
            result = my_decorated_function()
        # 자동으로 요약 출력
    """
    def __init__(
        self,
        name: str,
        stream_to_console: bool = True,
        auto_summary: bool = True,
        detailed: bool = False,
    ):
        self.name = name
        self.stream_to_console = stream_to_console
        self.auto_summary = auto_summary
        self.detailed = detailed
        self.ctx: Optional[PipelineContext] = None

    def __enter__(self) -> PipelineContext:
        self.ctx = PipelineContext(
            pipeline_name=self.name,
            stream_to_console=self.stream_to_console,
        )
        return self.ctx

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.auto_summary and self.ctx:
            print_summary(self.ctx, detailed=self.detailed)
        return False  # 예외 전파
