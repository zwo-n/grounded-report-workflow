"""
slack_app.py - Slack 슬래시 명령어로 문서 생성 파이프라인 실행

Socket Mode를 사용하여 ngrok이나 별도 웹서버 노출 없이 Slack과 연결합니다.

사용법:
    python slack_app.py

Slack 앱 설정 (https://api.slack.com/apps):
    1. Socket Mode 활성화
    2. Slash Commands에 /report 추가
    3. Bot Token Scopes: chat:write, files:write, commands
"""

import os
import threading
import logging
from pathlib import Path

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# 환경 변수 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Slack 앱 초기화
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


def format_summary_for_slack(summary: dict) -> str:
    """
    파이프라인 실행 요약을 Slack 메시지 형식으로 변환합니다.

    Args:
        summary: PipelineContext.get_summary() 결과

    Returns:
        Slack 메시지용 포맷된 문자열
    """
    total_ms = summary.get("total_duration_ms", 0)
    total_sec = total_ms / 1000
    total_steps = summary.get("total_steps", 0)
    successful = summary.get("successful_steps", 0)
    failed = summary.get("failed_steps", 0)

    lines = [
        f"*실행 요약*",
        f"• 총 소요시간: `{total_sec:.1f}초`",
        f"• 단계: {successful}/{total_steps} 성공" + (f" ({failed} 실패)" if failed > 0 else ""),
        "",
        "*단계별 소요시간*",
    ]

    # 주요 단계별 시간 (성공한 것만)
    steps = summary.get("steps", [])
    step_times = {}

    for step in steps:
        if step.get("status") == "success":
            name = step.get("step_name", "")
            duration = step.get("duration_ms", 0)

            # 같은 이름의 단계는 합산 (예: 여러 섹션의 LLM 호출)
            if name in step_times:
                step_times[name]["count"] += 1
                step_times[name]["total_ms"] += duration
            else:
                step_times[name] = {"count": 1, "total_ms": duration}

    # 단계별 출력 (소요시간 내림차순)
    sorted_steps = sorted(step_times.items(), key=lambda x: x[1]["total_ms"], reverse=True)

    for name, data in sorted_steps[:6]:  # 상위 6개만
        count = data["count"]
        total = data["total_ms"] / 1000
        if count > 1:
            lines.append(f"• {name}: `{total:.1f}초` ({count}회)")
        else:
            lines.append(f"• {name}: `{total:.1f}초`")

    return "\n".join(lines)


def get_user_display_name(client, user_id: str) -> str:
    """
    Slack API를 호출하여 사용자의 표시 이름을 가져옵니다.

    Args:
        client: Slack WebClient 인스턴스
        user_id: Slack 사용자 ID

    Returns:
        사용자 표시 이름 (display_name > real_name > user_id 순으로 폴백)
    """
    try:
        result = client.users_info(user=user_id)
        if result.get("ok"):
            profile = result.get("user", {}).get("profile", {})
            # display_name이 있으면 사용, 없으면 real_name
            display_name = profile.get("display_name") or ""
            real_name = profile.get("real_name") or ""
            return display_name.strip() or real_name.strip() or f"User-{user_id}"
    except Exception as e:
        logger.warning(f"사용자 정보 조회 실패: {e}")
    return f"User-{user_id}"


def run_pipeline_in_background(
    user_request: str,
    channel_id: str,
    user_id: str,
    user_display_name: str,
    client,
):
    """
    백그라운드에서 파이프라인을 실행하고 결과를 Slack에 전송합니다.

    Args:
        user_request: 사용자 요청 문자열
        channel_id: 결과를 전송할 Slack 채널 ID
        user_id: 요청한 사용자 ID
        user_display_name: 사용자 표시 이름 (Slack API에서 조회한 값)
        client: Slack WebClient 인스턴스
    """
    from test_real_doc import run_real_pipeline

    try:
        logger.info(f"파이프라인 시작: '{user_request}' (user={user_display_name})")

        output_path, summary = run_real_pipeline(
            user_request=user_request,
            author=user_display_name,
            verbose=True,
            return_summary=True,
        )

        # 파일 존재 확인
        if not Path(output_path).exists():
            raise FileNotFoundError(f"생성된 파일을 찾을 수 없습니다: {output_path}")

        file_size = Path(output_path).stat().st_size
        logger.info(f"파이프라인 완료: {output_path} ({file_size:,} bytes)")

        # 실행 요약 포맷
        summary_text = format_summary_for_slack(summary)

        # Slack에 파일 업로드 (files_upload_v2 사용)
        result = client.files_upload_v2(
            channel=channel_id,
            file=output_path,
            filename=Path(output_path).name,
            title=f"문서: {user_request[:50]}{'...' if len(user_request) > 50 else ''}",
            initial_comment=(
                f"<@{user_id}> 요청하신 문서가 생성되었습니다.\n"
                f"> {user_request}\n\n"
                f"{summary_text}"
            ),
        )

        logger.info(f"파일 업로드 완료: {result.get('file', {}).get('id', 'unknown')}")

    except Exception as e:
        logger.exception(f"파이프라인 실패: {e}")

        # 실패 메시지 전송
        try:
            client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> 문서 생성에 실패했습니다.\n```{str(e)}```",
            )
        except Exception as slack_err:
            logger.exception(f"Slack 메시지 전송 실패: {slack_err}")


@app.command("/report")
def handle_report_command(ack, command, client, respond):
    """
    /report 슬래시 명령어 핸들러

    사용법: /report [문서 요청 내용]
    예시: /report 클라우드 비용 최적화 방안에 대한 기술 보고서를 작성해줘
    """
    # 즉시 응답 (3초 타임아웃 방지)
    ack()

    user_id = command.get("user_id")
    channel_id = command.get("channel_id")
    text = command.get("text", "").strip()

    # 요청 내용이 없으면 안내 메시지
    if not text:
        respond(
            text=(
                "사용법: `/report [문서 요청 내용]`\n"
                "예시: `/report AWS 클라우드 비용 최적화 방안에 대한 기술 보고서를 작성해줘`"
            ),
            response_type="ephemeral",  # 본인에게만 보임
        )
        return

    # 접수 메시지 전송
    respond(
        text=(
            f"문서 생성 요청을 받았습니다. 잠시만 기다려주세요...\n"
            f"> {text}\n\n"
            f"_(생성에 3~5분 정도 소요될 수 있습니다)_"
        ),
        response_type="in_channel",  # 채널 전체에 표시
    )

    logger.info(f"/report 명령 수신: user={user_id}, text='{text[:50]}...'")

    # Slack API로 사용자 표시 이름 조회
    user_display_name = get_user_display_name(client, user_id)
    logger.info(f"사용자 이름 조회: {user_id} -> {user_display_name}")

    # 백그라운드 스레드에서 파이프라인 실행
    thread = threading.Thread(
        target=run_pipeline_in_background,
        args=(text, channel_id, user_id, user_display_name, client),
        daemon=True,
    )
    thread.start()


@app.event("app_mention")
def handle_app_mention(event, say):
    """앱 멘션 핸들러 (선택적)"""
    user = event.get("user")
    say(f"안녕하세요 <@{user}>! `/report [요청 내용]` 명령어로 문서를 생성할 수 있습니다.")


@app.event("message")
def handle_message(event, logger):
    """메시지 이벤트 핸들러 (로깅용)"""
    # DM이나 봇 메시지는 무시
    if event.get("channel_type") == "im" and not event.get("bot_id"):
        logger.debug(f"DM 수신: {event.get('text', '')[:50]}")


def main():
    """메인 실행 함수"""
    # 환경 변수 확인
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")

    if not bot_token:
        raise ValueError("SLACK_BOT_TOKEN 환경 변수가 설정되지 않았습니다.")
    if not app_token:
        raise ValueError("SLACK_APP_TOKEN 환경 변수가 설정되지 않았습니다.")

    logger.info("Slack 앱 시작 중...")
    logger.info(f"Bot Token: {bot_token[:10]}...{bot_token[-4:]}")
    logger.info(f"App Token: {app_token[:10]}...{app_token[-4:]}")

    # Socket Mode 핸들러로 앱 실행
    handler = SocketModeHandler(app, app_token)

    logger.info("Socket Mode 연결 시도 중...")
    handler.start()


if __name__ == "__main__":
    main()
