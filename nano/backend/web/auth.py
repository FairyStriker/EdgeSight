"""Bearer 토큰 기반 단순 인증.

`EDGESIGHT_TOKEN` 환경변수가 설정된 경우에만 검증을 수행한다.
미설정 시(개발 모드)에는 모든 요청을 통과시키되 시작 시 경고를 남긴다.
"""

import os
from fastapi import Header, HTTPException, status


def get_expected_token() -> str | None:
    tok = os.environ.get("EDGESIGHT_TOKEN")
    return tok if tok else None


async def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_expected_token()
    if expected is None:
        return  # 개발 모드 — 인증 비활성

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer 토큰이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided = authorization.split(" ", 1)[1].strip()
    if provided != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="잘못된 토큰입니다.")
