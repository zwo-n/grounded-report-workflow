"""
slack_app.py - Slack 슬래시 명령어로 문서 생성 파이프라인 실행

Socket Mode를 사용하여 ngrok이나 별도 웹서버 노출 없이 Slack과 연결합니다.

사용법:
    python slack_app.py

Slack 앱 설정 (https://api.slack.com/apps):
    1. Socket Mode 활성화
    2. Slash Commands에 /report 추가
    3. Bot Token Scopes: chat:write, files:write, files:read, commands, channels:history

템플릿 모드 (provided_data):
    1. CSV/XLSX 파일을 채널에 업로드
    2. /report [요청] --template gambarlabs_report 실행
    3. 봇이 최근 10분 이내 업로드된 CSV를 찾아서 파이프라인에 전달
"""

import os
import re
import time
import tempfile
import threading
import logging
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# 환경 변수 로드
load_dotenv()

# 로깅 설정 (콘솔 + 파일)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("slack_app.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Slack 앱 초기화
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

# 상수
MAX_FILE_AGE_SECONDS = 600  # 10분
SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xls")


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


def parse_template_option(text: str) -> tuple[str, str | None]:
    """
    커맨드 텍스트에서 --template 옵션을 파싱합니다.

    Args:
        text: 원본 커맨드 텍스트

    Returns:
        (요청 텍스트, template_hint 또는 None)

    Examples:
        "7월 보고서 --template gambarlabs_report" -> ("7월 보고서", "gambarlabs_report")
        "AWS 비용 분석 보고서" -> ("AWS 비용 분석 보고서", None)
    """
    # --template <name> 패턴 찾기
    match = re.search(r"--template\s+(\S+)", text)
    if match:
        template_hint = match.group(1)
        # --template 부분 제거
        request_text = re.sub(r"\s*--template\s+\S+\s*", " ", text).strip()
        return request_text, template_hint
    return text, None


def find_recent_data_file(client, channel_id: str, user_id: str) -> dict | None:
    """
    채널에서 사용자가 최근 10분 이내 업로드한 CSV/XLSX 파일을 찾습니다.

    Args:
        client: Slack WebClient 인스턴스
        channel_id: 채널 ID
        user_id: 사용자 ID

    Returns:
        파일 정보 딕셔너리 또는 None
    """
    try:
        # 채널 최근 메시지 조회
        result = client.conversations_history(channel=channel_id, limit=20)
        if not result.get("ok"):
            logger.warning(f"채널 히스토리 조회 실패: {result.get('error')}")
            return None

        messages = result.get("messages", [])
        now_ts = time.time()

        for message in messages:
            # 해당 사용자의 메시지인지 확인
            if message.get("user") != user_id:
                continue

            # 파일이 있는지 확인
            files = message.get("files", [])
            for file_info in files:
                filename = file_info.get("name", "")
                file_ts = float(file_info.get("timestamp", 0))

                # 확장자 확인
                if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
                    continue

                # 시간 확인 (10분 이내)
                age_seconds = now_ts - file_ts
                if age_seconds > MAX_FILE_AGE_SECONDS:
                    logger.info(f"파일 '{filename}' 제외: {age_seconds:.0f}초 전 업로드 (제한: {MAX_FILE_AGE_SECONDS}초)")
                    continue

                logger.info(f"적합한 파일 발견: {filename} ({age_seconds:.0f}초 전 업로드)")
                # 디버그: file_info 전체 필드 출력
                logger.info(f"file_info 전체 필드: {list(file_info.keys())}")
                logger.info(f"url_private: {file_info.get('url_private', 'N/A')}")
                logger.info(f"url_private_download: {file_info.get('url_private_download', 'N/A')}")
                return file_info

        return None

    except Exception as e:
        logger.exception(f"파일 검색 실패: {e}")
        return None


def download_slack_file(file_info: dict, bot_token: str, client=None) -> str:
    """
    Slack 파일을 다운로드하여 임시 경로에 저장합니다.

    slack_sdk에는 전용 다운로드 메서드가 없으므로 (Issue #1434 참조)
    urllib을 사용하여 직접 다운로드합니다.

    Args:
        file_info: Slack 파일 정보 딕셔너리
        bot_token: Slack Bot Token
        client: Slack WebClient (files_info 재조회용)

    Returns:
        다운로드된 파일의 임시 경로

    Raises:
        Exception: 다운로드 실패 시
    """
    import urllib.request
    import urllib.error

    filename = file_info.get("name", "data.csv")
    file_id = file_info.get("id")

    # 디버그: file_info 전체 URL 필드 출력
    logger.info(f"file_info URL 필드들:")
    for key in sorted(file_info.keys()):
        if "url" in key.lower():
            logger.info(f"  {key}: {file_info.get(key)}")

    # url_private_download 우선, 없으면 url_private 사용
    download_url = file_info.get("url_private_download") or file_info.get("url_private")

    # 만약 둘 다 없고 client가 있으면 files_info로 재조회
    if not download_url and client and file_id:
        logger.info(f"URL 없음, files_info로 재조회: file_id={file_id}")
        try:
            result = client.files_info(file=file_id)
            if result.get("ok"):
                file_detail = result.get("file", {})
                logger.info(f"files_info 응답 URL 필드들:")
                for key in sorted(file_detail.keys()):
                    if "url" in key.lower():
                        logger.info(f"  {key}: {file_detail.get(key)}")
                download_url = file_detail.get("url_private_download") or file_detail.get("url_private")
        except Exception as e:
            logger.warning(f"files_info 재조회 실패: {e}")

    if not download_url:
        raise ValueError(f"파일 '{filename}'의 다운로드 URL이 없습니다")

    logger.info(f"파일 다운로드 시작: {filename}")
    logger.info(f"다운로드 URL: {download_url}")

    # 헤더 준비 (디버그용 로그)
    masked_token = f"{bot_token[:10]}...{bot_token[-4:]}" if len(bot_token) > 14 else "***"
    logger.info(f"요청 헤더: Authorization=Bearer {masked_token}")

    # urllib 사용 (리다이렉트 시에도 Authorization 헤더 유지)
    # requests는 다른 도메인으로 리다이렉트 시 Authorization 헤더를 제거함
    headers = {"Authorization": f"Bearer {bot_token}"}

    # urllib은 기본적으로 리다이렉트를 따라가며 헤더를 유지
    req = urllib.request.Request(download_url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            content_type = response.headers.get("Content-Type", "unknown")
            final_url = response.url
            status_code = response.status

            logger.info(f"응답 Status: {status_code}")
            logger.info(f"응답 Content-Type: {content_type}")
            logger.info(f"최종 URL: {final_url}")

            # 데이터 읽기
            data = response.read()

            # 응답 앞부분 로그 (디버그)
            logger.info(f"응답 앞부분 (200 bytes): {data[:200]}")

            # text/html이면 인증 실패 가능성
            if "text/html" in content_type:
                logger.error("응답이 HTML입니다. 인증 실패 또는 로그인 페이지일 수 있습니다.")
                logger.error(f"HTML 내용: {data[:500].decode('utf-8', errors='replace')}")
                raise Exception(
                    "파일 다운로드 실패: HTML 응답 (files:read scope 누락 가능성). "
                    "Slack 앱 설정에서 Bot Token Scopes에 'files:read'를 추가하고 앱을 재설치하세요."
                )

    except urllib.error.HTTPError as e:
        logger.error(f"HTTP 에러: {e.code} {e.reason}")
        if e.code == 403:
            raise Exception(
                "파일 다운로드 실패: 403 Forbidden. "
                "Slack 앱 설정에서 Bot Token Scopes에 'files:read'를 추가하고 앱을 재설치하세요."
            )
        raise Exception(f"파일 다운로드 실패: HTTP {e.code} {e.reason}")

    # 임시 파일로 저장
    suffix = Path(filename).suffix
    temp_file = tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=suffix,
        prefix="slack_upload_",
        delete=False,
    )
    temp_file.write(data)
    temp_file.close()

    file_size = len(data)
    logger.info(f"파일 다운로드 완료: {temp_file.name} ({file_size:,} bytes)")

    return temp_file.name


def run_pipeline_in_background(
    user_request: str,
    channel_id: str,
    user_id: str,
    user_display_name: str,
    client,
    template_hint: str | None = None,
    provided_chunks: list | None = None,
    temp_file_path: str | None = None,
):
    """
    백그라운드에서 파이프라인을 실행하고 결과를 Slack에 전송합니다.

    Args:
        user_request: 사용자 요청 문자열
        channel_id: 결과를 전송할 Slack 채널 ID
        user_id: 요청한 사용자 ID
        user_display_name: 사용자 표시 이름 (Slack API에서 조회한 값)
        client: Slack WebClient 인스턴스
        template_hint: 템플릿 힌트 (예: "gambarlabs_report")
        provided_chunks: 제공 데이터 chunk 리스트
        temp_file_path: 삭제할 임시 파일 경로
    """
    try:
        if provided_chunks:
            # 템플릿 모드: main.py의 run_pipeline 사용
            from pipeline.main import run_pipeline
            import hashlib

            logger.info(f"템플릿 모드 파이프라인 시작: '{user_request}' (template={template_hint}, chunks={len(provided_chunks)})")

            # 출력 경로 생성
            timestamp = int(time.time())
            hash_suffix = hashlib.md5(user_request.encode()).hexdigest()[:6]
            output_path = f"output/report_{timestamp}_{hash_suffix}.docx"

            # 출력 디렉토리 생성
            Path("output").mkdir(exist_ok=True)

            # 실행 시간 측정
            start_time = time.time()

            run_pipeline(
                user_request=user_request,
                output_path=output_path,
                template_hint=template_hint,
                provided_chunks=provided_chunks,
                force_fixed_template=True,
                slack_user_name=user_display_name,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            summary = {
                "total_duration_ms": elapsed_ms,
                "total_steps": 3,  # 개요, 주요내용, 결론
                "successful_steps": 3,
                "failed_steps": 0,
                "steps": [
                    {"step_name": "템플릿 파이프라인", "status": "success", "duration_ms": elapsed_ms},
                ],
            }

        else:
            # 일반 모드: test_real_doc의 run_real_pipeline 사용
            from test_real_doc import run_real_pipeline

            logger.info(f"일반 모드 파이프라인 시작: '{user_request}' (user={user_display_name})")

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

        # 템플릿 모드 추가 정보
        mode_text = ""
        if template_hint:
            mode_text = f"\n*모드:* 템플릿 (`{template_hint}`)"
            if provided_chunks:
                mode_text += f" / 데이터 {len(provided_chunks)}건"

        # Slack에 파일 업로드 (files_upload_v2 사용)
        result = client.files_upload_v2(
            channel=channel_id,
            file=output_path,
            filename=Path(output_path).name,
            title=f"문서: {user_request[:50]}{'...' if len(user_request) > 50 else ''}",
            initial_comment=(
                f"<@{user_id}> 요청하신 문서가 생성되었습니다.\n"
                f"> {user_request}{mode_text}\n\n"
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

    finally:
        # 임시 파일 정리
        if temp_file_path and Path(temp_file_path).exists():
            try:
                Path(temp_file_path).unlink()
                logger.info(f"임시 파일 삭제: {temp_file_path}")
            except Exception as e:
                logger.warning(f"임시 파일 삭제 실패: {e}")


@app.command("/report")
def handle_report_command(ack, command, client, respond):
    """
    /report 슬래시 명령어 핸들러

    사용법:
        /report [문서 요청 내용]
        /report [문서 요청 내용] --template gambarlabs_report

    템플릿 모드 사용 시:
        1. 먼저 CSV/XLSX 파일을 채널에 업로드
        2. /report [요청] --template [템플릿명] 실행
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
                "*사용법:*\n"
                "• 일반 모드: `/report [문서 요청 내용]`\n"
                "• 템플릿 모드: `/report [요청] --template gambarlabs_report`\n\n"
                "*템플릿 모드 사용법:*\n"
                "1. CSV/XLSX 파일을 이 채널에 업로드\n"
                "2. `/report 7월 활동 보고서 --template gambarlabs_report` 실행\n\n"
                "*예시:*\n"
                "`/report AWS 클라우드 비용 최적화 방안에 대한 기술 보고서를 작성해줘`"
            ),
            response_type="ephemeral",  # 본인에게만 보임
        )
        return

    # --template 옵션 파싱
    user_request, template_hint = parse_template_option(text)
    logger.info(f"/report 명령 수신: user={user_id}, request='{user_request[:50]}...', template={template_hint}")

    # Slack API로 사용자 표시 이름 조회
    user_display_name = get_user_display_name(client, user_id)
    logger.info(f"사용자 이름 조회: {user_id} -> {user_display_name}")

    # 템플릿 모드인 경우: 최근 업로드 파일 찾기
    provided_chunks = None
    temp_file_path = None

    if template_hint:
        logger.info(f"템플릿 모드 활성화: {template_hint}")

        # 최근 업로드 파일 검색
        file_info = find_recent_data_file(client, channel_id, user_id)

        if not file_info:
            respond(
                text=(
                    f"⚠️ 최근 10분 이내에 업로드된 CSV/XLSX 파일을 찾을 수 없습니다.\n\n"
                    f"*템플릿 모드 사용법:*\n"
                    f"1. 먼저 CSV 또는 XLSX 파일을 이 채널에 업로드하세요\n"
                    f"2. 그 다음 `/report {user_request} --template {template_hint}` 명령을 다시 실행하세요\n\n"
                    f"_지원 형식: .csv, .xlsx, .xls_"
                ),
                response_type="ephemeral",
            )
            return

        filename = file_info.get("name", "unknown")
        logger.info(f"데이터 파일 발견: {filename}")

        # 파일 다운로드
        try:
            bot_token = os.environ.get("SLACK_BOT_TOKEN")
            temp_file_path = download_slack_file(file_info, bot_token, client=client)
        except Exception as e:
            logger.exception(f"파일 다운로드 실패: {e}")
            respond(
                text=(
                    f"⚠️ 파일 다운로드에 실패했습니다.\n"
                    f"*파일:* `{filename}`\n"
                    f"*오류:* `{str(e)}`"
                ),
                response_type="ephemeral",
            )
            return

        # 데이터 인제스트
        try:
            from pipeline.data_ingest import ingest_tabular
            provided_chunks = ingest_tabular(temp_file_path)
            logger.info(f"데이터 인제스트 완료: {len(provided_chunks)}개 chunk")
        except Exception as e:
            logger.exception(f"데이터 인제스트 실패: {e}")
            # 임시 파일 정리
            if temp_file_path and Path(temp_file_path).exists():
                Path(temp_file_path).unlink()
            respond(
                text=(
                    f"⚠️ 파일 파싱에 실패했습니다.\n"
                    f"*파일:* `{filename}`\n"
                    f"*오류:* `{str(e)}`\n\n"
                    f"_CSV 파일이 올바른 형식인지 확인해주세요._"
                ),
                response_type="ephemeral",
            )
            return

        # 접수 메시지 (템플릿 모드)
        respond(
            text=(
                f"📋 템플릿 모드로 문서 생성을 시작합니다.\n"
                f"> {user_request}\n\n"
                f"*템플릿:* `{template_hint}`\n"
                f"*데이터 파일:* `{filename}` ({len(provided_chunks)}건)\n\n"
                f"_(생성에 1~2분 정도 소요됩니다)_"
            ),
            response_type="in_channel",
        )

    else:
        # 접수 메시지 (일반 모드)
        respond(
            text=(
                f"문서 생성 요청을 받았습니다. 잠시만 기다려주세요...\n"
                f"> {user_request}\n\n"
                f"_(생성에 3~5분 정도 소요될 수 있습니다)_"
            ),
            response_type="in_channel",
        )

    # 백그라운드 스레드에서 파이프라인 실행
    thread = threading.Thread(
        target=run_pipeline_in_background,
        args=(user_request, channel_id, user_id, user_display_name, client),
        kwargs={
            "template_hint": template_hint,
            "provided_chunks": provided_chunks,
            "temp_file_path": temp_file_path,
        },
        daemon=True,
    )
    thread.start()


@app.event("app_mention")
def handle_app_mention(event, say):
    """앱 멘션 핸들러 (선택적)"""
    user = event.get("user")
    say(
        f"안녕하세요 <@{user}>!\n"
        f"• 일반 문서: `/report [요청 내용]`\n"
        f"• 템플릿 문서: CSV 업로드 후 `/report [요청] --template gambarlabs_report`"
    )


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
