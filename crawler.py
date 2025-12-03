#!/usr/bin/env python3
"""
오토마트 경매 차량 크롤러
- 발표완료된 경매 기관에서 낙찰된 차량 정보를 수집
- 멀티스레드 병렬 처리로 빠른 크롤링
"""

import asyncio
import re
import csv
from datetime import datetime
from urllib.parse import urljoin, parse_qs, urlparse
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
import logging

import aiohttp
from bs4 import BeautifulSoup
from tqdm.asyncio import tqdm_asyncio
import pandas as pd

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.automart.co.kr"
INTRO_URL = f"{BASE_URL}/views/pub_auction/pub_auction_intro.asp?num=4"
# AJAX 엔드포인트 - 발표완료 기관 목록
AJAX_URL = f"{BASE_URL}/inc/pub_auction/pub_auction_announceList_ajax.asp?ing=Y&num=4&type=&detail_1=1&detail_2=1&detail_3=1&detail_4=1&detail_5=1&detail_6=1&son2=1"

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
    description: str = ""           # 차량설명(특이사항)
    auction_date: str = ""          # 경매일시
    storage_location: str = ""      # 보관소
    detail_url: str = ""            # 상세페이지 URL

    def get_unique_key(self) -> str:
        """중복 체크용 고유 키 생성 (차량번호 + 경매일시)"""
        return f"{self.car_number}_{self.auction_date}"


class AutomartCrawler:
    """오토마트 경매 크롤러"""

    def __init__(self, max_concurrent: int = 20, delay: float = 0.1):
        self.max_concurrent = max_concurrent
        self.delay = delay
        self.semaphore: Optional[asyncio.Semaphore] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.results: List[CarData] = []
        self.failed_urls: List[str] = []

    async def _get_html(self, url: str, retries: int = 3) -> Optional[str]:
        """HTML 페이지 가져오기 (재시도 로직 포함)"""
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(self.max_concurrent)

        async with self.semaphore:
            for attempt in range(retries):
                try:
                    await asyncio.sleep(self.delay)
                    async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        if response.status == 200:
                            # 인코딩 처리 (EUC-KR 또는 UTF-8)
                            content = await response.read()
                            try:
                                return content.decode('utf-8')
                            except UnicodeDecodeError:
                                try:
                                    return content.decode('euc-kr')
                                except UnicodeDecodeError:
                                    return content.decode('cp949', errors='ignore')
                        else:
                            logger.warning(f"HTTP {response.status} for {url}")
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout (attempt {attempt+1}/{retries}): {url}")
                except Exception as e:
                    logger.warning(f"Error (attempt {attempt+1}/{retries}): {url} - {e}")

                if attempt < retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))

            self.failed_urls.append(url)
            return None

    async def get_institution_links(self) -> List[Tuple[str, str, str]]:
        """AJAX 엔드포인트에서 기관 링크 수집
        Returns: [(기관명, URL, 발표일시), ...]
        """
        logger.info("AJAX 엔드포인트에서 기관 목록 수집 중...")
        html = await self._get_html(AJAX_URL)
        if not html:
            logger.error("AJAX 페이지 로드 실패")
            return []

        soup = BeautifulSoup(html, 'lxml')
        institutions = []

        # 테이블에서 링크 추출
        for row in soup.find_all('tr'):
            link = row.find('a', href=True)
            if not link:
                continue

            href = link.get('href', '')
            # sisul_total_view.asp 또는 sisul_BidResult.asp 링크 찾기
            if 'sisul_total_view.asp' in href or 'sisul_BidResult.asp' in href:
                full_url = urljoin(BASE_URL, href)
                institution_name = link.get_text(strip=True)

                # 발표일시 찾기 (같은 행에서)
                cells = row.find_all('td')
                auction_date = ""
                for cell in cells:
                    text = cell.get_text(strip=True)
                    if re.match(r'\d{4}-\d{2}-\d{2}', text):
                        auction_date = text
                        break

                if institution_name:
                    # 중복 제거 (같은 URL이더라도 다른 날짜면 추가)
                    institutions.append((institution_name, full_url, auction_date))

        logger.info(f"총 {len(institutions)}개 기관 링크 수집 완료")
        return institutions

    async def get_vehicles_from_list_page(self, url: str, institution: str, auction_date: str) -> List[CarData]:
        """단일 목록 페이지에서 차량 정보 추출"""
        html = await self._get_html(url)
        if not html:
            return []

        soup = BeautifulSoup(html, 'lxml')
        vehicles = []

        # 차량 목록 테이블 찾기
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if 'CarDetail_in.asp' in href:
                full_url = urljoin(BASE_URL + "/views/pub_auction/Common/", href) if not href.startswith('http') else href
                if href.startswith('/'):
                    full_url = urljoin(BASE_URL, href)

                # 링크 텍스트에서 차량번호와 모델 추출
                link_text = link.get_text(strip=True)
                parts = link_text.split(None, 1)
                car_number = parts[0] if parts else ""
                car_model = parts[1] if len(parts) > 1 else ""

                # 같은 행에서 낙찰금액 찾기
                parent_row = link.find_parent('tr')
                winning_bid = ""
                storage_location = ""

                if parent_row:
                    cells = parent_row.find_all('td')
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        # 금액 패턴 (숫자,숫자,숫자 형식)
                        if re.match(r'^[\d,]+$', text) and len(text) > 3:
                            winning_bid = text
                        # 보관소 패턴
                        if '보관소' in text:
                            storage_location = text

                if car_number:
                    car = CarData(
                        institution=institution,
                        car_number=car_number,
                        car_model=car_model,
                        winning_bid=winning_bid,
                        auction_date=auction_date,
                        storage_location=storage_location,
                        detail_url=full_url
                    )
                    vehicles.append(car)

        return vehicles

    async def get_all_vehicles_from_institution(self, url: str, institution: str, auction_date: str) -> List[CarData]:
        """기관 페이지에서 모든 페이지의 차량 정보 수집 (페이지네이션 처리)"""
        all_vehicles = []

        # 첫 페이지
        vehicles = await self.get_vehicles_from_list_page(url, institution, auction_date)
        all_vehicles.extend(vehicles)

        # 페이지네이션 확인 및 추가 페이지 수집
        html = await self._get_html(url)
        if html:
            soup = BeautifulSoup(html, 'lxml')
            # 페이지 번호 링크 찾기
            page_links = soup.find_all('a', href=re.compile(r'gfnpagemove'))
            max_page = 1

            for link in page_links:
                match = re.search(r'gfnpagemove\(["\']?(\d+)["\']?\)', link.get('href', ''))
                if match:
                    page_num = int(match.group(1))
                    max_page = max(max_page, page_num)

            # 추가 페이지 수집
            if max_page > 1:
                # URL에 PageNo 파라미터 추가
                parsed = urlparse(url)
                base_params = parse_qs(parsed.query)

                for page in range(2, max_page + 1):
                    # 페이지 URL 생성 (PageNo 파라미터 사용)
                    page_url = url
                    if 'PageNo=' in url:
                        page_url = re.sub(r'PageNo=\d+', f'PageNo={page}', url)
                    else:
                        separator = '&' if '?' in url else '?'
                        page_url = f"{url}{separator}PageNo={page}"

                    page_vehicles = await self.get_vehicles_from_list_page(page_url, institution, auction_date)
                    all_vehicles.extend(page_vehicles)

        return all_vehicles

    async def get_car_details(self, car: CarData) -> CarData:
        """차량 상세 페이지에서 추가 정보 수집"""
        if not car.detail_url:
            return car

        html = await self._get_html(car.detail_url)
        if not html:
            return car

        soup = BeautifulSoup(html, 'lxml')

        # 테이블에서 정보 추출
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            for i, cell in enumerate(cells):
                text = cell.get_text(strip=True)

                # 모델연도/기어
                if '모델연도' in text and i + 1 < len(cells):
                    value = cells[i + 1].get_text(strip=True)
                    # "2014 / 자동" 에서 연도만 추출
                    year_match = re.search(r'(\d{4})', value)
                    if year_match:
                        car.model_year = year_match.group(1)

                # 주행거리
                if '주행거리' in text and i + 1 < len(cells):
                    car.mileage = cells[i + 1].get_text(strip=True)

                # 예정가
                if '예' in text and '정' in text and '가' in text and i + 1 < len(cells):
                    car.expected_price = cells[i + 1].get_text(strip=True)

                # 차량명 (상세)
                if '차량명' in text and i + 1 < len(cells):
                    detailed_model = cells[i + 1].get_text(strip=True)
                    if detailed_model:
                        car.car_model = detailed_model

                # 보관소
                if '보관소' in text and i + 1 < len(cells):
                    car.storage_location = cells[i + 1].get_text(strip=True)

                # 차량설명(특이사항)
                if '특이사항' in text and i + 1 < len(cells):
                    car.description = cells[i + 1].get_text(strip=True)
                    # 이미지 태그 다음의 텍스트 정리
                    car.description = re.sub(r'\s+', ' ', car.description).strip()

        return car

    async def crawl_institution(self, institution_data: Tuple[str, str, str]) -> List[CarData]:
        """단일 기관의 모든 차량 크롤링"""
        institution_name, url, auction_date = institution_data

        try:
            # 기관에서 차량 목록 수집
            vehicles = await self.get_all_vehicles_from_institution(url, institution_name, auction_date)

            if not vehicles:
                return []

            # 각 차량의 상세 정보 수집 (병렬)
            detailed_vehicles = await asyncio.gather(
                *[self.get_car_details(car) for car in vehicles],
                return_exceptions=True
            )

            # 에러 필터링
            result = []
            for v in detailed_vehicles:
                if isinstance(v, CarData):
                    result.append(v)
                elif isinstance(v, Exception):
                    logger.warning(f"상세 정보 수집 실패: {v}")

            return result

        except Exception as e:
            logger.error(f"기관 크롤링 실패 ({institution_name}): {e}")
            return []

    async def run(self) -> List[CarData]:
        """전체 크롤링 실행"""
        connector = aiohttp.TCPConnector(limit=self.max_concurrent, limit_per_host=10)

        async with aiohttp.ClientSession(
            connector=connector,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            }
        ) as session:
            self.session = session
            self.semaphore = asyncio.Semaphore(self.max_concurrent)

            # 1단계: 기관 목록 수집
            institutions = await self.get_institution_links()

            if not institutions:
                logger.error("기관 목록을 가져올 수 없습니다.")
                return []

            # 2단계: 각 기관에서 차량 정보 수집 (병렬)
            logger.info(f"총 {len(institutions)}개 기관에서 차량 정보 수집 중...")

            tasks = [self.crawl_institution(inst) for inst in institutions]
            results = await tqdm_asyncio.gather(*tasks, desc="크롤링 진행")

            # 결과 합치기
            for result in results:
                if result:
                    self.results.extend(result)

            logger.info(f"총 {len(self.results)}대 차량 정보 수집 완료")

            if self.failed_urls:
                logger.warning(f"실패한 URL: {len(self.failed_urls)}개")

            return self.results

    def save_to_csv(self, filename: str = "automart_master.csv"):
        """결과를 CSV 파일로 저장 (기존 데이터와 병합, 중복 제거)"""
        import os

        if not self.results:
            logger.warning("저장할 데이터가 없습니다.")
            return

        # 컬럼 순서 및 한글 이름 매핑
        column_mapping = {
            'institution': '기관명',
            'car_number': '차량번호',
            'car_model': '차량모델',
            'model_year': '모델연도',
            'mileage': '주행거리',
            'expected_price': '예정가',
            'winning_bid': '낙찰금액',
            'description': '차량설명(특이사항)',
            'auction_date': '경매일시',
            'storage_location': '보관소',
            'detail_url': '상세URL'
        }

        # 새 데이터 DataFrame 생성
        new_df = pd.DataFrame([asdict(car) for car in self.results])
        new_df = new_df.rename(columns=column_mapping)

        # 기존 파일이 있으면 로드하여 병합
        existing_count = 0
        if os.path.exists(filename):
            try:
                existing_df = pd.read_csv(filename, encoding='utf-8-sig')
                existing_count = len(existing_df)
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            except Exception as e:
                logger.warning(f"기존 파일 로드 실패, 새로 생성합니다: {e}")
                combined_df = new_df
        else:
            combined_df = new_df

        # 중복 제거 (차량번호 + 경매일시 기준, 첫 번째 유지)
        before_dedup = len(combined_df)
        combined_df = combined_df.drop_duplicates(
            subset=['차량번호', '경매일시'],
            keep='first'
        )
        after_dedup = len(combined_df)
        duplicates_removed = before_dedup - after_dedup

        # 경매일시 기준 정렬 (최신순)
        combined_df = combined_df.sort_values('경매일시', ascending=False)

        # 저장
        combined_df.to_csv(filename, index=False, encoding='utf-8-sig')

        # 통계 출력
        new_records = after_dedup - existing_count
        logger.info(f"수집: {len(self.results)}건 | 신규: {new_records}건 | 중복제거: {duplicates_removed}건 | 총: {after_dedup}건")
        logger.info(f"마스터 파일 저장: {filename}")


async def main():
    """메인 함수"""
    crawler = AutomartCrawler(max_concurrent=20, delay=0.1)

    try:
        await crawler.run()

        # 마스터 CSV로 저장 (자동 병합 및 중복 제거)
        crawler.save_to_csv("automart_master.csv")

    except Exception as e:
        logger.error(f"크롤링 중 오류 발생: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
