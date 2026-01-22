#!/usr/bin/env python3
"""
오토마트 히스토리 크롤러
- 모든 기관의 과거 경매 데이터를 수집
- 관공서: 진행년도/공고번호별 recursive 크롤링
- 금융기관: 마감완료 공개매각 pagination 크롤링
- 멀티스레딩: 기관당 하나의 스레드
"""

import asyncio
import re
import csv
import time
from datetime import datetime
from urllib.parse import urljoin, parse_qs, urlparse, urlencode
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import threading

import aiohttp
from bs4 import BeautifulSoup
import pandas as pd

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s'
)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.automart.co.kr"
INTRO_URL = f"{BASE_URL}/views/pub_auction/pub_auction_intro.asp?num=1"

# 크롤링 설정
MAX_YEARS = 3  # 최대 몇 년치 데이터를 수집할지
DELAY_BETWEEN_REQUESTS = 0.3  # 요청 간 딜레이 (초)
MAX_CONCURRENT_PER_THREAD = 10  # 스레드당 동시 요청 수

# 하드코딩된 기관 목록 (JavaScript 렌더링 대신 사용)
# 포맷: (이름, URL경로타입, bidType, grCom, grOrd, grOrg, 카테고리)
INSTITUTIONS_DATA = [
    # 금융/개인/회원사 (Pub_CarHalbu)
    ("금융 공개매각", "Pub_CarHalbu", "1", "GMBG00", "2", "BGBA00", "financial"),
    ("개인 공개매각", "Pub_CarHalbu", "1", "GMGK01", "3", "BGGEGK", "financial"),
    ("회원사 공개매각", "Pub_CarHalbu", "1", "GMAM01", "3", "BGGEGE", "financial"),
    ("SK렌터카 공개매각", "Pub_CarHalbu", "1", "UPSK02", "3", "BGBASK", "financial"),

    # 관공서(세무) - 서울
    ("서울시청", "Pub_CarInfo", "3", "GMSW27", "4", "SMSMSW", "standard"),
    ("강남구청", "Pub_CarInfo", "3", "GMSW23", "4", "SMSMSW", "standard"),
    ("강동구청", "Pub_CarInfo", "3", "GMSW25", "4", "SMSMSW", "standard"),
    ("강북구청", "Pub_CarInfo", "3", "GMSW09", "4", "SMSMSW", "standard"),
    ("강서구청", "Pub_CarInfo", "3", "GMSW16", "4", "SMSMSW", "standard"),
    ("관악구청", "Pub_CarInfo", "3", "GMSW21", "4", "SMSMSW", "standard"),
    ("광진구청", "Pub_CarInfo", "3", "GMSW05", "4", "SMSMSW", "standard"),
    ("구로구청", "Pub_CarInfo", "3", "GMSW17", "4", "SMSMSW", "standard"),
    ("금천구청", "Pub_CarInfo", "3", "GMSW18", "4", "SMSMSW", "standard"),
    ("노원구청", "Pub_CarInfo", "3", "GMSW11", "4", "SMSMSW", "standard"),
    ("도봉구청", "Pub_CarInfo", "3", "GMSW10", "4", "SMSMSW", "standard"),
    ("동대문구청", "Pub_CarInfo", "3", "GMSW06", "4", "SMSMSW", "standard"),
    ("동작구청", "Pub_CarInfo", "3", "GMSW20", "4", "SMSMSW", "standard"),
    ("마포구청", "Pub_CarInfo", "3", "GMSW14", "4", "SMSMSW", "standard"),
    ("서대문구청", "Pub_CarInfo", "3", "GMSW13", "4", "SMSMSW", "standard"),
    ("서초구청", "Pub_CarInfo", "3", "GMSW22", "4", "SMSMSW", "standard"),
    ("성동구청", "Pub_CarInfo", "3", "GMSW04", "4", "SMSMSW", "standard"),
    ("성북구청", "Pub_CarInfo", "3", "GMSW08", "4", "SMSMSW", "standard"),
    ("송파구청", "Pub_CarInfo", "3", "GMSW24", "4", "SMSMSW", "standard"),
    ("양천구청", "Pub_CarInfo", "3", "GMSW15", "4", "SMSMSW", "standard"),
    ("영등포구청", "Pub_CarInfo", "3", "GMSW19", "4", "SMSMSW", "standard"),
    ("용산구청", "Pub_CarInfo", "3", "GMSW03", "4", "SMSMSW", "standard"),
    ("은평구청", "Pub_CarInfo", "3", "GMSW12", "4", "SMSMSW", "standard"),
    ("종로구청", "Pub_CarInfo", "3", "GMSW26", "4", "SMSMSW", "standard"),
    ("중구청", "Pub_CarInfo", "3", "GMSW01", "4", "SMSMSW", "standard"),
    ("중랑구청", "Pub_CarInfo", "3", "GMSW07", "4", "SMSMSW", "standard"),

    # 관공서(세무) - 인천
    ("인천시청", "Pub_CarInfo", "3", "GMIC00", "4", "SMSMIN", "standard"),
    ("계양구청", "Pub_CarInfo", "3", "GMIC07", "4", "SMSMIN", "standard"),
    ("남동구청", "Pub_CarInfo", "3", "GMIC05", "4", "SMSMIN", "standard"),
    ("부평구청", "Pub_CarInfo", "3", "GMIC06", "4", "SMSMIN", "standard"),
    ("서구청", "Pub_CarInfo", "3", "GMIC08", "4", "SMSMIN", "standard"),

    # 관공서(세무) - 경기
    ("수원시청", "Pub_CarInfo", "3", "GMKK00", "4", "SMSMKK", "standard"),
    ("고양시청", "Pub_CarInfo", "3", "GMKK33", "4", "SMSMKK", "standard"),
    ("성남시청", "Pub_CarInfo", "3", "GMKK46", "4", "SMSMKK", "standard"),
    ("용인시청", "Pub_CarInfo", "3", "GMKK10", "4", "SMSMKK", "standard"),
    ("부천시청", "Pub_CarInfo", "3", "GMKK01", "4", "SMSMKK", "standard"),
    ("안산시 상록구청", "Pub_CarInfo", "3", "GMKK25", "4", "SMSMKK", "standard"),
    ("화성시청", "Pub_CarInfo", "3", "GMKK18", "4", "SMSMKK", "standard"),
    ("평택시청", "Pub_CarInfo", "3", "GMKK07", "4", "SMSMKK", "standard"),
    ("남양주시청", "Pub_CarInfo", "3", "GMKK15", "4", "SMSMKK", "standard"),

    # 관공서(세무) - 부산
    ("부산시청", "Pub_CarInfo", "3", "GMBS00", "4", "SMSMBS", "standard"),
    ("사상구청", "Pub_CarInfo", "3", "GMBS01", "4", "SMSMBS", "standard"),
    ("사하구청", "Pub_CarInfo", "3", "GMBS04", "4", "SMSMBS", "standard"),

    # 관공서(세무) - 대전
    ("대전시청", "Pub_CarInfo", "3", "GMDJ05", "4", "SMSMDJ", "standard"),
    ("대덕구청", "Pub_CarInfo", "3", "GMDJ03", "4", "SMSMDJ", "standard"),

    # 관공서(세무) - 광주
    ("광주광역시청", "Pub_CarInfo", "3", "GMKJ04", "4", "SMSMKJ", "standard"),
    ("광주북구청", "Pub_CarInfo", "3", "GMKJ07", "4", "SMSMKJ", "standard"),

    # 공공기관 (Pub_CarHW)
    ("국민건강보험공단", "Pub_CarHW", "2", "NA0000", "3", "BOBONA", "standard"),
    ("근로복지공단", "Pub_CarHW", "2", "WE0000", "3", "BOBOWE", "standard"),
    ("한국도로공사", "Pub_CarHW", "2", "BOEX00", "2", "BOEX00", "standard"),

    # 검찰청/경찰청 (Pub_CarHW)
    ("압수(경찰청)", "Pub_CarHW", "6", "PLKAAK", "3", "PLKAAK", "standard"),
    ("검찰청", "Pub_CarHW", "6", "PLKAAG", "3", "PLKAAG", "standard"),
    ("서울특별시경찰청", "Pub_CarHW", "6", "PLKCSW", "3", "PLKCSW", "standard"),
    ("경기도남부경찰청", "Pub_CarHW", "6", "PLKCKK", "3", "PLKCKK", "standard"),
    ("경기도북부경찰청", "Pub_CarHW", "6", "PLKCKB", "3", "PLKCKB", "standard"),

    # 장기미반환 (Pub_CarMiBan)
    ("시설관리공단", "Pub_CarMiBan", "5", "SSISUL", "4", "MBMISW", "standard"),
    ("강남구 도시관리공단", "Pub_CarMiBan", "5", "GMSM21", "4", "MBMISW", "standard"),
]


@dataclass
class CarData:
    """차량 데이터 클래스"""
    institution: str = ""           # 기관명
    car_number: str = ""            # 차량번호
    car_model: str = ""             # 차량모델
    model_year: str = ""            # 모델연도
    mileage: str = ""               # 주행거리
    expected_price: str = ""        # 예정가
    winning_bid: str = ""           # 낙찰금액
    bid_count: str = ""             # 입찰건수
    description: str = ""           # 차량설명(특이사항)
    auction_date: str = ""          # 경매일시
    storage_location: str = ""      # 보관소
    detail_url: str = ""            # 상세페이지 URL
    notice_number: str = ""         # 공고번호

    def get_unique_key(self) -> str:
        """중복 체크용 고유 키 생성"""
        return f"{self.car_number}_{self.auction_date}_{self.notice_number}"


class InstitutionInfo:
    """기관 정보 클래스"""
    def __init__(self, name: str, url: str, category: str):
        self.name = name
        self.url = url
        self.category = category  # 'standard' or 'financial'

        # URL에서 파라미터 추출
        parsed = urlparse(url)
        self.params = parse_qs(parsed.query)
        self.bid_type = self.params.get('bidType', [''])[0]
        self.gr_com = self.params.get('grCom', [''])[0]
        self.gr_ord = self.params.get('grOrd', [''])[0]
        self.gr_org = self.params.get('grOrg', [''])[0]

        # URL 경로에서 path_type 추출 (Pub_CarInfo, Pub_CarHalbu, Pub_CarHW, Pub_CarMiBan)
        path_match = re.search(r'/pub_auction/(Pub_\w+)/', parsed.path)
        self.path_type = path_match.group(1) if path_match else 'Pub_CarInfo'


class InstitutionCrawler:
    """개별 기관 크롤러 (스레드 내에서 실행)"""

    def __init__(self, institution: InstitutionInfo, delay: float = DELAY_BETWEEN_REQUESTS):
        self.institution = institution
        self.delay = delay
        self.results: List[CarData] = []
        self.visited_urls: Set[str] = set()
        self.session: Optional[aiohttp.ClientSession] = None
        self.semaphore: Optional[asyncio.Semaphore] = None

    async def _get_html(self, url: str, retries: int = 3) -> Optional[str]:
        """HTML 페이지 가져오기"""
        if url in self.visited_urls:
            return None
        self.visited_urls.add(url)

        async with self.semaphore:
            for attempt in range(retries):
                try:
                    await asyncio.sleep(self.delay)
                    async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        if response.status == 200:
                            content = await response.read()
                            try:
                                return content.decode('utf-8')
                            except UnicodeDecodeError:
                                try:
                                    return content.decode('euc-kr')
                                except UnicodeDecodeError:
                                    return content.decode('cp949', errors='ignore')
                        else:
                            logger.warning(f"HTTP {response.status}: {url}")
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout (attempt {attempt+1}/{retries}): {url}")
                except Exception as e:
                    logger.warning(f"Error (attempt {attempt+1}/{retries}): {url} - {e}")

                if attempt < retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
            return None

    async def crawl_standard_institution(self) -> List[CarData]:
        """관공서 타입 기관 크롤링 (년도/공고번호 기반)

        핵심: 각 년도를 선택하면 해당 년도의 공고 목록이 새로 로드됨
        따라서 각 년도별로 페이지를 다시 요청하여 공고 목록을 가져와야 함
        """
        all_vehicles = []

        # 1단계: sisul_total_view.asp로 접근하여 최신 NotNo 획득
        total_view_url = (
            f"{BASE_URL}/views/pub_auction/{self.institution.path_type}/sisul_total_view.asp?"
            f"bidType={self.institution.bid_type}&"
            f"grCom={self.institution.gr_com}&"
            f"grOrd={self.institution.gr_ord}&"
            f"grOrg={self.institution.gr_org}"
        )

        initial_not_no = None
        try:
            async with self.session.get(total_view_url, timeout=aiohttp.ClientTimeout(total=30), allow_redirects=True) as response:
                final_url = str(response.url)
                html = await response.text()

                not_no_match = re.search(r'NotNo=([A-Z0-9]+)', final_url)
                if not_no_match:
                    initial_not_no = not_no_match.group(1)
                else:
                    not_no_match = re.search(r'NotNo=([A-Z0-9]+)', html)
                    if not_no_match:
                        initial_not_no = not_no_match.group(1)
        except Exception as e:
            logger.warning(f"[{self.institution.name}] total_view 접근 실패: {e}")

        if not initial_not_no:
            logger.warning(f"[{self.institution.name}] NotNo를 찾을 수 없음 (데이터 없음)")
            return []

        logger.debug(f"[{self.institution.name}] 초기 NotNo: {initial_not_no}")

        # 2단계: 결과조회 페이지에서 년도 드롭다운 파싱
        bid_result_url = (
            f"{BASE_URL}/views/pub_auction/{self.institution.path_type}/sisul_BidResult.asp?"
            f"bidType={self.institution.bid_type}&"
            f"grOrd={self.institution.gr_ord}&"
            f"grOrg={self.institution.gr_org}&"
            f"grCom={self.institution.gr_com}&"
            f"NotNo={initial_not_no}&menuNo=6"
        )

        html = await self._get_html(bid_result_url)
        if not html or '해당되는 공고가 존재하지 않습니다' in html:
            logger.warning(f"[{self.institution.name}] 결과조회 페이지 접근 실패")
            return []

        soup = BeautifulSoup(html, 'lxml')

        # 년도 추출 (select 옵션에서)
        discovered_years = set()
        for select in soup.find_all('select'):
            for opt in select.find_all('option'):
                value = opt.get('value', '') or opt.get_text(strip=True)
                if re.match(r'^20\d{2}$', value):
                    discovered_years.add(value)

        # NotNo에서 현재 년도도 추가
        current_notice_match = re.search(r'(\d{4})A(\d+)', initial_not_no)
        if current_notice_match:
            discovered_years.add(current_notice_match.group(1))

        if not discovered_years:
            current_year = datetime.now().year
            discovered_years = {str(y) for y in range(current_year, current_year - MAX_YEARS, -1)}

        logger.info(f"[{self.institution.name}] 수집 대상 년도: {sorted(discovered_years, reverse=True)}")

        # 3단계: 각 년도별로 페이지를 다시 요청하여 해당 년도의 공고 목록 가져오기
        crawled_notices = set()

        for year in sorted(discovered_years, reverse=True):
            # 해당 년도의 공고 목록을 가져오기 위해 notyear 파라미터로 페이지 요청
            year_url = (
                f"{BASE_URL}/views/pub_auction/{self.institution.path_type}/sisul_BidResult.asp?"
                f"bidType={self.institution.bid_type}&"
                f"NotNo={initial_not_no}&menuNo=6&"
                f"ViewNotNo={initial_not_no}&notyear={year}"
            )

            year_html = await self._get_html(year_url)
            if not year_html:
                continue

            year_soup = BeautifulSoup(year_html, 'lxml')

            # 해당 년도의 공고번호들 파싱
            notices_for_year = set()
            for select in year_soup.find_all('select'):
                for opt in select.find_all('option'):
                    text = opt.get_text(strip=True)
                    # 공고번호 형식: "2024-3591 [입찰]" 또는 "2024-1754 [입찰]"
                    notice_match = re.search(r'(\d{4})-(\d+)', text)
                    if notice_match:
                        n_year = notice_match.group(1)
                        n_num = notice_match.group(2)
                        if n_year == year:
                            notices_for_year.add(n_num)

            if notices_for_year:
                logger.debug(f"[{self.institution.name}] {year}년 공고: {len(notices_for_year)}개")

            # 해당 년도의 각 공고 크롤링
            for notice_num in notices_for_year:
                notice_key = f"{year}-{notice_num}"
                if notice_key in crawled_notices:
                    continue

                not_no = f"{self.institution.gr_com}{year}A{notice_num}"
                vehicles = await self._crawl_single_notice(not_no, notice_key, year)
                all_vehicles.extend(vehicles)
                crawled_notices.add(notice_key)

        if all_vehicles:
            logger.info(f"[{self.institution.name}] 총 {len(all_vehicles)}대 수집")

        return all_vehicles

    async def _crawl_single_notice(self, not_no: str, notice_str: str, year: str) -> List[CarData]:
        """단일 공고 크롤링"""
        url = (
            f"{BASE_URL}/views/pub_auction/{self.institution.path_type}/sisul_BidResult.asp?"
            f"bidType={self.institution.bid_type}&"
            f"grOrd={self.institution.gr_ord}&"
            f"grOrg={self.institution.gr_org}&"
            f"grCom={self.institution.gr_com}&"
            f"NotNo={not_no}&menuNo=6"
        )

        html = await self._get_html(url)
        if not html or '해당되는 공고가 존재하지 않습니다' in html:
            return []

        vehicles = await self._parse_bid_result_page(html, notice_str, year)
        if vehicles:
            logger.debug(f"[{self.institution.name}] {notice_str}: {len(vehicles)}대")

        return vehicles

    async def _parse_bid_result_page(self, html: str, notice: str, year: str) -> List[CarData]:
        """결과조회 페이지에서 차량 정보 파싱"""
        soup = BeautifulSoup(html, 'lxml')
        vehicles = []

        # 경매일시 추출 시도
        auction_date = ""
        date_match = re.search(r'(\d{4}[.-]\d{2}[.-]\d{2})', html)
        if date_match:
            auction_date = date_match.group(1).replace('.', '-')

        # 테이블에서 차량 정보 추출 (7-8컬럼 구조)
        for tr in soup.find_all('tr'):
            tds = tr.find_all('td')

            # 7컬럼 구조: 순번 | 차량번호 | 차량명 | 모델연도 | 낙찰금액 | 입찰건수 | 낙찰자
            if len(tds) >= 6:
                texts = [td.get_text(strip=True) for td in tds]

                # 첫 번째 셀이 숫자인지 확인 (순번)
                if texts[0].isdigit():
                    car_number = texts[1] if len(texts) > 1 else ""
                    car_model = texts[2] if len(texts) > 2 else ""
                    model_year = texts[3] if len(texts) > 3 else ""

                    # 낙찰금액 추출
                    winning_bid = ""
                    bid_text = texts[4] if len(texts) > 4 else ""
                    bid_match = re.search(r'([\d,]+)', bid_text)
                    if bid_match:
                        winning_bid = bid_match.group(1)

                    # 입찰건수
                    bid_count = texts[5] if len(texts) > 5 else ""
                    if not bid_count.isdigit():
                        bid_count = ""

                    # 상세 URL 추출
                    detail_url = ""
                    link = tds[1].find('a', href=True) if len(tds) > 1 else None
                    if link:
                        href = link.get('href', '')
                        if href.startswith('/'):
                            detail_url = urljoin(BASE_URL, href)
                        elif not href.startswith('http'):
                            detail_url = urljoin(BASE_URL + "/views/pub_auction/Common/", href)
                        else:
                            detail_url = href

                    if car_number and car_number != '차량번호':
                        car = CarData(
                            institution=self.institution.name,
                            car_number=car_number,
                            car_model=car_model,
                            model_year=model_year,
                            winning_bid=winning_bid,
                            bid_count=bid_count,
                            auction_date=auction_date,
                            detail_url=detail_url,
                            notice_number=notice or f"{year}"
                        )
                        vehicles.append(car)

        return vehicles

    async def crawl_financial_institution(self) -> List[CarData]:
        """금융기관 타입 크롤링 (마감완료 공개매각 + pagination)"""
        all_vehicles = []

        # 마감완료 공개매각 URL (son2=1)
        base_params = {
            'bidType': self.institution.bid_type,
            'grCom': self.institution.gr_com,
            'grOrd': self.institution.gr_ord,
            'grOrg': self.institution.gr_org,
            'son2': '1',  # 마감완료
            'sMonth': '1',  # 검색기간 1달
        }

        page = 1
        max_pages = 50  # 최대 페이지 수 제한

        while page <= max_pages:
            base_params['PageNo'] = str(page)

            url = f"{BASE_URL}/views/pub_auction/Pub_CarHalbu/sisul_total_view.asp?{urlencode(base_params)}"
            html = await self._get_html(url)

            if not html:
                break

            soup = BeautifulSoup(html, 'lxml')
            vehicles = self._parse_financial_page(soup)

            if not vehicles:
                break

            all_vehicles.extend(vehicles)

            # 다음 페이지 존재 여부 확인
            next_page_link = soup.find('a', href=re.compile(rf'gfnpagemove.*{page + 1}'))
            if not next_page_link:
                break

            page += 1
            logger.info(f"[{self.institution.name}] 페이지 {page} 크롤링 중...")

        return all_vehicles

    def _parse_financial_page(self, soup: BeautifulSoup) -> List[CarData]:
        """금융기관 페이지에서 차량 정보 파싱"""
        vehicles = []

        # CarDetail_in.asp 링크 찾기
        for link in soup.find_all('a', href=re.compile(r'CarDetail_in\.asp')):
            href = link.get('href', '')

            # 링크 내부의 텍스트 노드들을 분리해서 추출
            # 구조: 차량번호 <br> 모델명
            car_number = ""
            car_model = ""

            # 링크 내의 모든 텍스트 노드 추출
            texts = []
            for child in link.children:
                if hasattr(child, 'name'):
                    if child.name == 'br':
                        continue  # br 태그 건너뛰기
                    texts.append(child.get_text(strip=True))
                else:
                    text = str(child).strip()
                    if text:
                        texts.append(text)

            if len(texts) >= 2:
                car_number = texts[0]
                car_model = texts[1]
            elif len(texts) == 1:
                # 하나만 있으면 차량번호로 간주
                car_number = texts[0]

            # 부모 행에서 추가 정보 추출
            parent_row = link.find_parent('tr')
            if not parent_row:
                parent_td = link.find_parent('td')
                if parent_td:
                    parent_row = parent_td.find_parent('tr')

            auction_date = ""
            model_year = ""
            expected_price = ""
            storage_location = ""

            if parent_row:
                row_text = parent_row.get_text()

                # 날짜 패턴 (2025.12.04)
                date_match = re.search(r'(\d{4}\.\d{2}\.\d{2})', row_text)
                if date_match:
                    auction_date = date_match.group(1).replace('.', '-')

                # 가격 (마지막 큰 숫자) - 낙찰금액 또는 예정가
                price_matches = re.findall(r'([\d,]{7,})', row_text)
                if price_matches:
                    expected_price = price_matches[-1]  # 마지막 큰 숫자가 보통 낙찰금액

                # 보관소 링크
                storage_links = parent_row.find_all('a', href=re.compile(r'Pub_CarPlace\.asp'))
                if storage_links:
                    storage_location = storage_links[0].get_text(strip=True)

            detail_url = urljoin(BASE_URL + "/views/pub_auction/Common/", href) if href else ""

            if car_number and len(car_number) >= 4:
                car = CarData(
                    institution=self.institution.name,
                    car_number=car_number,
                    car_model=car_model,
                    expected_price=expected_price,
                    auction_date=auction_date,
                    storage_location=storage_location,
                    detail_url=detail_url
                )
                vehicles.append(car)

        return vehicles

    async def get_vehicle_details(self, vehicles: List[CarData]) -> List[CarData]:
        """차량 상세 정보 수집 (평가액 등)"""
        tasks = [self._get_single_detail(car) for car in vehicles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        detailed_vehicles = []
        for result in results:
            if isinstance(result, CarData):
                detailed_vehicles.append(result)
            elif isinstance(result, Exception):
                logger.warning(f"상세 정보 수집 실패: {result}")

        return detailed_vehicles

    async def _get_single_detail(self, car: CarData) -> CarData:
        """단일 차량 상세 정보 수집"""
        if not car.detail_url:
            return car

        html = await self._get_html(car.detail_url)
        if not html:
            return car

        soup = BeautifulSoup(html, 'lxml')

        # 페이지 전체 텍스트에서 정규식으로 추출
        page_text = soup.get_text()

        # 주행거리 추출
        if not car.mileage:
            mileage_match = re.search(r'주행거리\s*([\d,]+)', page_text)
            if mileage_match:
                car.mileage = mileage_match.group(1)

        # 예정가 추출
        if not car.expected_price:
            price_match = re.search(r'예\s*정\s*가\s*([\d,]+)', page_text)
            if price_match:
                car.expected_price = price_match.group(1)

        # 차량명 추출 (기존 값이 없거나 너무 짧을 때만)
        if not car.car_model or len(car.car_model) < 3:
            model_match = re.search(r'차량명\s*([^\n]{3,50}?)(?:\s*모델연도|$)', page_text)
            if model_match:
                car.car_model = model_match.group(1).strip()

        # 보관소 추출
        if not car.storage_location:
            storage_match = re.search(r'보관소\s*(오토마트[^\n]+보관소)', page_text)
            if storage_match:
                car.storage_location = storage_match.group(1).strip()

        # 특이사항 추출 (200자 제한)
        if not car.description:
            desc_match = re.search(r'특이사항[)\s]*(.*?)(?:이전 절차|할부가능|선택 차량|$)', page_text, re.DOTALL)
            if desc_match:
                desc = desc_match.group(1).strip()
                desc = re.sub(r'\s+', ' ', desc)
                car.description = desc[:200] if len(desc) > 200 else desc

        return car

    async def run(self) -> List[CarData]:
        """크롤링 실행"""
        connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT_PER_THREAD)

        async with aiohttp.ClientSession(
            connector=connector,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
            }
        ) as session:
            self.session = session
            self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_PER_THREAD)

            logger.info(f"[{self.institution.name}] 크롤링 시작 (타입: {self.institution.category})")

            if self.institution.category == 'financial':
                vehicles = await self.crawl_financial_institution()
            else:
                vehicles = await self.crawl_standard_institution()

            if vehicles:
                logger.info(f"[{self.institution.name}] {len(vehicles)}대 차량 발견, 상세 정보 수집 중...")
                vehicles = await self.get_vehicle_details(vehicles)

            logger.info(f"[{self.institution.name}] 크롤링 완료: {len(vehicles)}대")
            return vehicles


class HistoryCrawler:
    """히스토리 크롤러 메인 클래스"""

    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers
        self.all_results: List[CarData] = []
        self.lock = threading.Lock()

    def get_all_institutions(self) -> List[InstitutionInfo]:
        """하드코딩된 기관 목록 반환 (JavaScript 렌더링 페이지 대신)"""
        logger.info("기관 목록 로드 중...")

        institutions = []

        for name, path_type, bid_type, gr_com, gr_ord, gr_org, category in INSTITUTIONS_DATA:
            url = (
                f"{BASE_URL}/views/pub_auction/{path_type}/sisul_total_view.asp?"
                f"bidType={bid_type}&grCom={gr_com}&grOrd={gr_ord}&grOrg={gr_org}&hk=0"
            )
            institutions.append(InstitutionInfo(name, url, category))

        logger.info(f"총 {len(institutions)}개 기관 로드")

        # 카테고리별 통계
        standard_count = sum(1 for i in institutions if i.category == 'standard')
        financial_count = sum(1 for i in institutions if i.category == 'financial')
        logger.info(f"  - 관공서: {standard_count}개, 금융기관: {financial_count}개")

        return institutions

    def _crawl_single_institution(self, institution: InstitutionInfo) -> List[CarData]:
        """단일 기관 크롤링 (스레드에서 실행)"""
        crawler = InstitutionCrawler(institution)

        # 새 이벤트 루프 생성 및 실행
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            results = loop.run_until_complete(crawler.run())
            return results
        except Exception as e:
            logger.error(f"[{institution.name}] 크롤링 실패: {e}")
            return []
        finally:
            loop.close()

    def run(self) -> List[CarData]:
        """전체 크롤링 실행 (멀티스레드)"""
        institutions = self.get_all_institutions()

        if not institutions:
            logger.error("크롤링할 기관이 없습니다.")
            return []

        logger.info(f"멀티스레드 크롤링 시작 (workers: {self.max_workers})")

        all_results = []

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix='Crawler') as executor:
            future_to_inst = {
                executor.submit(self._crawl_single_institution, inst): inst
                for inst in institutions
            }

            completed = 0
            total = len(institutions)

            for future in as_completed(future_to_inst):
                institution = future_to_inst[future]
                completed += 1

                try:
                    results = future.result()
                    all_results.extend(results)
                    logger.info(f"진행률: {completed}/{total} - [{institution.name}] {len(results)}대 수집")
                except Exception as e:
                    logger.error(f"[{institution.name}] 처리 중 오류: {e}")

        logger.info(f"전체 크롤링 완료: {len(all_results)}대")
        return all_results

    def save_to_csv(self, results: List[CarData], filename: str = "automart_history.csv"):
        """결과를 CSV로 저장"""
        if not results:
            logger.warning("저장할 데이터가 없습니다.")
            return

        column_mapping = {
            'institution': '기관명',
            'car_number': '차량번호',
            'car_model': '차량모델',
            'model_year': '모델연도',
            'mileage': '주행거리',
            'expected_price': '예정가',
            'winning_bid': '낙찰금액',
            'bid_count': '입찰건수',
            'description': '차량설명(특이사항)',
            'auction_date': '경매일시',
            'storage_location': '보관소',
            'detail_url': '상세URL',
            'notice_number': '공고번호'
        }

        df = pd.DataFrame([asdict(car) for car in results])
        df = df.rename(columns=column_mapping)

        # 중복 제거
        before_dedup = len(df)
        df = df.drop_duplicates(subset=['차량번호', '경매일시', '공고번호'], keep='first')
        after_dedup = len(df)

        # 정렬
        df = df.sort_values('경매일시', ascending=False)

        df.to_csv(filename, index=False, encoding='utf-8-sig')

        logger.info(f"저장 완료: {filename}")
        logger.info(f"  - 수집: {len(results)}건")
        logger.info(f"  - 중복제거: {before_dedup - after_dedup}건")
        logger.info(f"  - 최종: {after_dedup}건")


def main():
    """메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(description='오토마트 히스토리 크롤러')
    parser.add_argument('--workers', type=int, default=10, help='동시 크롤링 스레드 수')
    parser.add_argument('--output', type=str, default='automart_history.csv', help='출력 파일명')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("오토마트 히스토리 크롤러 시작")
    logger.info(f"스레드 수: {args.workers}, 출력 파일: {args.output}")
    logger.info("=" * 60)

    start_time = time.time()

    crawler = HistoryCrawler(max_workers=args.workers)
    results = crawler.run()
    crawler.save_to_csv(results, args.output)

    elapsed = time.time() - start_time
    logger.info(f"총 소요 시간: {elapsed:.1f}초")


if __name__ == "__main__":
    main()
