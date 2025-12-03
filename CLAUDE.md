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

### 6. sisul_BidResult.asp 낙찰금액 파싱 ✅ 해결 (2025-12-04)
- **문제**: 낙찰금액이 예정가로 잘못 수집됨
  - 예: 모하비 실제 낙찰가 `95,159,000원` → 수집된 값 `8,000,000` (예정가)
- **원인 분석**:
  - 기관 페이지 타입이 2가지 존재:
    1. `sisul_total_view.asp` - 금융기관 페이지, 다른 테이블 구조
    2. `sisul_BidResult.asp` - 관공서 페이지, **정확한 낙찰금액** + 입찰건수 있음
  - 기존 크롤러가 두 페이지를 구분하지 못하고 있었음

- **시도한 해결책 (시행착오)**:
  1. ❌ 테이블 헤더에서 "낙찰금액" 컬럼 인덱스 찾기
     - 결과: 부분 성공, 일부 페이지에서 헤더 탐지 실패
     - 이유: 테이블이 중첩되어 있어 헤더 행 식별이 어려움
  2. ❌ "원" 패턴으로 금액 찾기
     - 결과: 실패
     - 이유: 예정가와 낙찰가 모두 "원" 패턴이라 구분 불가
  3. ❌ 컬럼 인덱스 기반 파싱
     - 결과: 실패
     - 이유: 테이블 구조가 페이지마다 다름 (7셀, 13셀, 219셀 등)
  4. ✅ **7셀 행 패턴 매칭**
     - 결과: 성공!
     - 방법: `len(tds) == 7 and tds[0].isdigit()` 조건으로 데이터 행 식별

- **최종 해결책**:
  ```python
  # sisul_BidResult.asp 전용 파싱
  if len(tds) == 7:
      texts = [td.get_text(strip=True) for td in tds]
      if texts[0].isdigit():  # 첫 번째 셀이 순번(숫자)
          car_number = texts[1]  # 차량번호
          car_model = texts[2]   # 차량명
          model_year = texts[3]  # 모델연도
          winning_bid = texts[4] # 낙찰금액 ✅
          bid_count = texts[5]   # 입찰건수
  ```

- **검증 결과**:
  - 모하비 01거3181: `95,159,000원` ✅
  - 재규어 52서9524: `7,499,000원` ✅
  - 입찰건수도 함께 수집됨 ✅

---

### 7. sisul_total_view.asp 낙찰금액 파싱 ✅ 해결 (2025-12-04)
- **문제**: 금융기관(KB국민카드, 하나캐피탈 등) 차량의 낙찰금액이 수집되지 않음
  - 예: 토레스 실제 낙찰가 `27,190,000원` → 수집 안됨

- **원인 분석**:
  - `sisul_total_view.asp`는 `sisul_BidResult.asp`와 완전히 다른 테이블 구조
  - 테이블이 심하게 중첩되어 있음 (219개 td 셀이 한 행에!)
  - 기존 7셀 파싱 로직이 적용되지 않음

- **페이지 구조 분석 (시행착오)**:
  1. ❌ 전체 테이블 파싱 시도
     - 결과: 219개 셀이 나와서 어떤 것이 데이터인지 식별 불가
  2. ❌ CarDetail 링크가 있는 행 찾기
     - 결과: 부분 성공, 하지만 셀 개수가 불규칙
  3. ✅ **13셀 행 패턴 매칭 + 결과발표 텍스트 필터**
     - 결과: 성공!

- **발견한 테이블 구조**:
  ```
  13셀 행 구조:
  [2]: 차량번호+모델 (CarDetail 링크)
  [6]: 경매일시 (예: 2025.12.03(14:00))
  [10]: 낙찰금액 (예: 27,190,000)
  [12]: "결과발표" 텍스트
  ```

- **최종 해결책**:
  ```python
  # sisul_total_view.asp 전용 파싱 (금융기관)
  if len(tds) >= 13:
      # CarDetail 링크가 있는 행만 처리
      link = td.find('a', href=lambda x: 'CarDetail_in.asp' in x)
      if link and '결과발표' in row_text:
          # 금액 패턴으로 낙찰금액 추출
          for td in tds:
              text = td.get_text(strip=True)
              if re.match(r'^[\d,]+$', text) and len(text) >= 7:
                  winning_bid = text  # 예: 27,190,000
  ```

- **검증 결과**:
  - KB국민카드 토레스 XXXX7695: `27,190,000원` ✅
  - 하나캐피탈 카이엔: `155,790,000원` ✅

---

### 8. GitHub Actions 푸시 권한 ✅ 해결
- **문제**: `Write access to repository not granted`
- **해결**: Repository Settings → Actions → Workflow permissions → "Read and write permissions" 활성화

---

## 페이지 타입별 파싱 전략

### 1. sisul_BidResult.asp (관공서 - 7셀 구조)
```html
<tr>
  <td>1</td>                           <!-- 순번 -->
  <td><a href="...">01거3181</a></td>  <!-- 차량번호 -->
  <td>모하비</td>                       <!-- 차량명 -->
  <td>2017</td>                        <!-- 모델연도 -->
  <td>95,159,000원</td>                <!-- 낙찰금액 ✅ -->
  <td>35</td>                          <!-- 입찰건수 -->
  <td>xxxxxx-xxxx218</td>              <!-- 낙찰자 -->
</tr>
```

**파싱 로직**:
- `len(tds) == 7` 체크
- `tds[0].isdigit()` = 데이터 행
- `tds[4]` = 낙찰금액

### 2. sisul_total_view.asp (금융기관 - 13셀 구조)
```html
<!-- 중첩 테이블로 한 행에 13개 셀 -->
<tr>
  <td>...</td>                         <!-- [0-1] 기타 -->
  <td><a href="...">XXXX7695토레스</a></td>  <!-- [2] 차량번호+모델 -->
  <td>...</td>                         <!-- [3-5] 기타 -->
  <td>2025.12.03(14:00)</td>           <!-- [6] 경매일시 -->
  <td>...</td>                         <!-- [7-9] 기타 -->
  <td>27,190,000</td>                  <!-- [10] 낙찰금액 ✅ -->
  <td>...</td>                         <!-- [11] 기타 -->
  <td>결과발표</td>                    <!-- [12] 결과발표 -->
</tr>
```

**파싱 로직**:
- `len(tds) >= 13` 체크
- CarDetail 링크 있고 + "결과발표" 텍스트 있는 행
- 금액 패턴(`^\d+,\d+,\d+$`)으로 낙찰금액 추출

### 3. CarDetail_in.asp (상세페이지)
- 차량번호 (전체 또는 마스킹)
- 모델연도/기어
- 주행거리
- 예정가
- 보관소
- 차량설명(특이사항)

---

## 테스트 케이스 검증

| 차량 | 페이지 타입 | 기대값 | 실제값 | 결과 |
|------|-------------|--------|--------|------|
| 모하비 01거3181 | sisul_BidResult.asp | 95,159,000원 | 95,159,000원 | ✅ |
| 재규어 52서9524 | sisul_BidResult.asp | 7,499,000원 | 7,499,000원 | ✅ |
| 토레스 XXXX7695 | sisul_total_view.asp | 27,190,000원 | 27,190,000원 | ✅ |

---

## TODO
- [x] `sisul_BidResult.asp` 페이지 전용 파싱 로직 구현 ✅
- [x] `sisul_total_view.asp` 페이지 전용 파싱 로직 구현 ✅
- [x] 입찰건수 필드 추가 완료 ✅
- [x] 낙찰금액 정확도 검증 ✅
- [ ] 금융기관 페이지 중복 데이터 제거 개선

---

## 기술 스택
- Python 3.11
- aiohttp (비동기 HTTP)
- BeautifulSoup + lxml (HTML 파싱)
- pandas (CSV 처리)
- GitHub Actions (자동화)
