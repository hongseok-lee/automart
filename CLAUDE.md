# Automart Crawler - 개발 기록

## 프로젝트 개요
오토마트(automart.co.kr) 경매 사이트에서 낙찰 차량 정보를 수집하는 크롤러

## 성공한 접근법

### 1. AJAX 엔드포인트 발견 ✅
- **문제**: 메인 페이지(`pub_auction_intro.asp`)가 JavaScript로 동적 로딩되어 HTML에 기관 목록이 없음
- **해결**: 네트워크 분석으로 AJAX 엔드포인트 발견
  ```
  /inc/pub_auction/pub_auction_announceList_ajax.asp?ing=Y&num=4&...
  ```
- **결과**: 118개 기관 링크 성공적으로 수집

### 2. 비동기 병렬 처리 ✅
- `asyncio` + `aiohttp`로 동시 20개 연결
- `asyncio.Semaphore`로 rate limiting
- 전체 크롤링 시간 ~4분 (순차 처리 대비 대폭 단축)

### 3. 중복 제거 (CSV 기반) ✅
- **고유 키**: `차량번호 + 경매일시`
- `pandas.drop_duplicates()` 사용
- 매일 실행해도 기존 데이터와 병합 후 중복 자동 제거

### 4. 상세페이지에서 전체 차량번호 추출 ✅
- **문제**: 리스트 페이지에서 회원사 차량은 `XXX1234`로 마스킹
- **해결**: 상세페이지(`CarDetail_in.asp`)에서 전체 번호 추출
- **결과**: 공공기관(경찰청/검찰청) 차량은 전체 번호 표시, 회원사는 XXX 유지 (정상)

### 5. GitHub Actions 자동화 ✅
- 매일 오전 01:30 KST 자동 실행
- CSV 자동 커밋 & 푸시

---

## 해결된 이슈

### 6. 낙찰금액 파싱 오류 ✅ 해결 (2025-12-04)
- **문제**: 낙찰금액이 예정가로 잘못 수집됨
  - 예: 모하비 실제 낙찰가 `95,159,000원` → 수집된 값 `8,000,000` (예정가)
- **원인 분석**:
  - 기관 페이지 타입이 2가지 존재:
    1. `sisul_total_view.asp` - 예정가만 있음, 낙찰금액 없음
    2. `sisul_BidResult.asp` - **정확한 낙찰금액** + 입찰건수 있음
  - 기존 크롤러가 두 페이지를 구분하지 못하고 있었음

- **시도한 해결책**:
  1. 테이블 헤더에서 "낙찰금액" 컬럼 인덱스 찾기 → 부분 성공
  2. "원" 패턴으로 금액 찾기 → 예정가와 낙찰가 구분 불가
  3. 컬럼 인덱스 기반 파싱 → 테이블 구조가 페이지마다 다름
  4. **7셀 행 패턴 매칭** → 성공!

- **최종 해결책**:
  - `sisul_BidResult.asp` 페이지 전용 파싱 로직 추가
  - 7개 td 셀이 있고 첫 번째 셀이 숫자인 행 = 데이터 행
  - 테이블 구조: `순번 | 차량번호 | 차량명 | 모델연도 | 낙찰금액 | 입찰건수 | 낙찰자`
  - 폴백 로직으로 다른 페이지 타입도 처리

- **검증 결과**:
  - 모하비: `95,159,000원` 정확히 수집 ✅
  - 입찰건수도 함께 수집됨 ✅

### 7. GitHub Actions 푸시 권한 ✅ 해결
- **문제**: `Write access to repository not granted`
- **해결**: Repository Settings → Actions → Workflow permissions → "Read and write permissions" 활성화

---

## 페이지 구조 분석

### AJAX 엔드포인트 응답 (기관 목록)
```html
<tr>
  <td><a href="sisul_BidResult.asp?...">경기도 수원시청</a></td>
  <td>2025-12-02</td>
  <td>9</td>
</tr>
```

### sisul_BidResult.asp (결과조회 - 정확한 낙찰금액)
```html
<tr>
  <td>순번</td>
  <td>차량번호</td>
  <td>차량명</td>
  <td>모델연도</td>
  <td>낙찰금액</td>  <!-- 여기에 정확한 값 -->
  <td>입찰건수</td>
  <td>낙찰자</td>
</tr>
<tr>
  <td>1</td>
  <td><a href="CarDetail_in.asp?...">01거3181</a></td>
  <td>모하비</td>
  <td>2017</td>
  <td>95,159,000원</td>
  <td>35</td>
  <td>xxxxxx-xxxx218 xx진</td>
</tr>
```

### CarDetail_in.asp (상세페이지)
- 차량번호 (전체 또는 마스킹)
- 모델연도/기어
- 주행거리
- 예정가
- 보관소
- 차량설명(특이사항)

---

## TODO
- [x] `sisul_BidResult.asp` 페이지 전용 파싱 로직 구현 ✅
- [x] 입찰건수 필드 추가 완료 ✅
- [x] 낙찰금액 정확도 검증 ✅
- [ ] 낙찰금액 없는 차량 (1210건) 원인 분석 및 개선 (아직 발표 안 된 경매 등)

---

## 기술 스택
- Python 3.11
- aiohttp (비동기 HTTP)
- BeautifulSoup + lxml (HTML 파싱)
- pandas (CSV 처리)
- GitHub Actions (자동화)
