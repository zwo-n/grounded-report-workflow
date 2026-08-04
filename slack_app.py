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


def run_pipeline_in_background(
    user_request: str,
    channel_id: str,
    user_id: str,
    client,
):
    """
    백그라운드에서 파이프라인을 실행하고 결과를 Slack에 전송합니다.

    Args:
        user_request: 사용자 요청 문자열
        channel_id: 결과를 전송할 Slack 채널 ID
        user_id: 요청한 사용자 ID
        client: Slack WebClient 인스턴스
    """
    from test_real_doc import run_real_pipeline

    try:
        logger.info(f"파이프라인 시작: '{user_request}' (user={user_id})")

        output_path = run_real_pipeline(
            user_request=user_request,
            author=f"Slack User <@{user_id}>",
            verbose=True,
        )

        # 파일 존재 확인
        if not Path(output_path).exists():
            raise FileNotFoundError(f"생성된 파일을 찾을 수 없습니다: {output_path}")

        file_size = Path(output_path).stat().st_size
        logger.info(f"파이프라인 완료: {output_path} ({file_size:,} bytes)")

        # Slack에 파일 업로드 (files_upload_v2 사용)
        result = client.files_upload_v2(
            channel=channel_id,
            file=output_path,
            filename=Path(output_path).name,
            title=f"문서: {user_request[:50]}{'...' if len(user_request) > 50 else ''}",
            initial_comment=f"<@{user_id}> 요청하신 문서가 생성되었습니다.\n> {user_request}",
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

    # 백그라운드 스레드에서 파이프라인 실행
    thread = threading.Thread(
        target=run_pipeline_in_background,
        args=(text, channel_id, user_id, client),
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
