# 이미지 도용 모니터링 시스템 (MVP 백엔드)

설계서 기준 MVP 1~2단계 (DB 스키마 + 판매 링크 등록 API + 범용 어댑터 수집)를 구현한 초기 스캐폴딩입니다.

## 실행 방법

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

서버가 뜨면 http://localhost:8000/docs 에서 Swagger UI로 바로 API 테스트가 가능합니다.

## 현재 동작하는 것

1. `POST /sellers` — 판매 링크 등록 (플랫폼명, URL, 메모)
2. `GET /sellers` — 등록된 링크 목록 조회
3. `POST /sellers/{id}/crawl` — 수집 실행 (MVP: 큐 없이 즉시 동기 실행)
4. `GET /sellers/{id}/images` — 수집된 이미지 목록 + 메타데이터(원본 URL, 해시, 크기) 조회
5. 수집된 이미지 파일은 `backend/storage/{seller_id}/` 폴더에 저장

## 다음 단계 (설계서 섹션 10 참고)

- [ ] Next.js 프론트엔드 (링크 등록 폼 + 결과 갤러리)
- [ ] 스마트스토어/쿠팡 전용 어댑터 추가 (`adapters/` 폴더에 `PlatformAdapter` 상속해서 구현 후 `registry.py`에 등록)
- [ ] JS 렌더링이 필요한 사이트 대응을 위한 Playwright 기반 어댑터
- [ ] 증거자료 zip/CSV 다운로드 엔드포인트
- [ ] 브라우저 자동화 도입 시 3.4절 리소스 관리(동시 실행 제한, 타임아웃) 적용

## 새 플랫폼 어댑터 추가하는 법

1. `adapters/` 폴더에 새 파일 생성 (예: `smartstore.py`)
2. `PlatformAdapter`를 상속해서 `match_url`, `extract_images`, `extract_meta` 구현
3. `adapters/registry.py`의 `ADAPTERS` 리스트 맨 앞에 새 어댑터 인스턴스 추가
   (구체적인 어댑터가 `GenericAdapter`보다 먼저 매칭되어야 하므로 순서 중요)
