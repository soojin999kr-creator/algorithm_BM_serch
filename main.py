"""Google Cloud Run 배포용 FastAPI 서버 (main.py)

Stitch 'Boyer-Moore Visualizer Web App' (projects/13665966594260626734) 프로젝트와 연동되어
보이어-무어(Boyer-Moore) 문자열 검색 알고리즘의 나쁜 문자표(Bad Character)와 착한 접미부(Good Suffix)
동시 비교 시각화 스냅샷, 히스토그램 데이터 및 텔레메트리 벤치마크를 제공합니다.
"""

import asyncio
import json
import logging
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

try:
    from .algorithms import run_boyer_moore_search
except ImportError:
    from algorithms import run_boyer_moore_search

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Boyer-Moore Algorithm Telemetry Engine API",
    description="보이어-무어 알고리즘의 나쁜 문자표와 착한 접미부 동시 비교 시각화 및 히스토그램 스냅샷 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BMSearchRequest(BaseModel):
    text: str = Field(
        ...,
        description="검색 대상 텍스트 (길이 1 ~ 500자)",
        example="ABAA BABACB AA",
    )
    pattern: str = Field(
        ...,
        description="찾을 패턴 문자열 (길이 1 ~ 50자)",
        example="BABACB",
    )

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("검색 대상 텍스트가 비어 있습니다.")
        if len(v) > 500:
            raise ValueError(f"시각화 애니메이션의 원활한 렌더링을 위해 텍스트는 최대 500자까지 지원합니다. (현재: {len(v)}자)")
        return v

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("패턴 문자열이 비어 있습니다.")
        if len(v) > 50:
            raise ValueError(f"패턴 문자열은 최대 50자까지 지원합니다. (현재: {len(v)}자)")
        return v


@app.get("/health", tags=["Health"])
def health_check():
    """서버 상태 확인용 헬스체크 엔드포인트"""
    return {
        "status": "healthy",
        "service": "boyer-moore-telemetry-engine",
        "version": "1.0.0",
        "linkedStitchProject": "projects/13665966594260626734",
    }


@app.post("/api/search", tags=["Boyer-Moore"])
def search_endpoint(request: BMSearchRequest):
    """텍스트와 패턴을 받아 보이어-무어 단계별 시각화 스냅샷과 히스토그램 데이터를 반환합니다."""
    if len(request.pattern) > len(request.text):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"패턴 길이({len(request.pattern)})가 대상 텍스트 길이({len(request.text)})보다 깁니다.",
        )

    try:
        result = run_boyer_moore_search(request.text, request.pattern)
        return {
            "success": True,
            "data": result,
        }
    except Exception as e:
        logger.error(f"보이어-무어 스냅샷 생성 중 에러 발생: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"알고리즘 시각화 데이터 생성 실패: {str(e)}",
        )


@app.websocket("/ws/search")
async def websocket_search_stream(websocket: WebSocket):
    """실시간 스트리밍 시각화용 웹소켓 엔드포인트"""
    await websocket.accept()
    logger.info("웹소켓 클라이언트 연결됨.")
    try:
        while True:
            text_data = await websocket.receive_text()
            data = json.loads(text_data)
            text = data.get("text", "ABAA BABACB AA")
            pattern = data.get("pattern", "BABACB")
            delay_ms = data.get("delayMs", 100) / 1000.0

            result = run_boyer_moore_search(text, pattern)
            snapshots = result.get("snapshots", [])

            # 메타데이터 선송신
            await websocket.send_json({
                "type": "metadata",
                "bad_char_table": result.get("bad_char_table"),
                "good_suffix_table": result.get("good_suffix_table"),
                "total_snapshots": len(snapshots),
            })

            # 단계별 스냅샷 지연 송신
            for snap in snapshots:
                await websocket.send_json({
                    "type": "snapshot",
                    "snapshot": snap,
                })
                await asyncio.sleep(delay_ms)

            await websocket.send_json({
                "type": "complete",
                "summary": {
                    "total_comparisons": result.get("total_comparisons"),
                    "total_shifts": result.get("total_shifts"),
                    "matches": result.get("matches"),
                    "elapsed_time_ms": result.get("elapsed_time_ms"),
                },
            })
    except WebSocketDisconnect:
        logger.info("웹소켓 클라이언트 연결 종료.")
    except Exception as e:
        logger.error(f"웹소켓 스트리밍 중 오류 발생: {e}", exc_info=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

