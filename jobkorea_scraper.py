
import asyncio
import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# 검색할 키워드
KEYWORDS = ['IT', '자율주행', '모빌리티']

async def scrape_jobkorea(page, keyword):
    """잡코리아에서 특정 키워드로 채용 공고를 스크레이핑합니다."""
    print(f"잡코리아에서 '{keyword}' 키워드로 검색을 시작합니다.")
    url = f"https://www.jobkorea.co.kr/Search/?stext={keyword}"
    await page.goto(url, wait_until="domcontentloaded")

    try:
        # 검색 결과가 로드될 때까지 대기 (30초로 증가)
                await page.wait_for_selector("div.post", timeout=30000)
    except PlaywrightTimeoutError:
        print(f"잡코리아에서 '{keyword}'에 대한 검색 결과가 없거나 로딩에 실패했습니다.")
        return []

    # 공고 링크 수집
        links = await page.eval_on_selector_all("div.post .title", """
        (elements => elements.map(el => el.href))
    """)

    jobs = []
    print(f"잡코리아에서 {len(links)}개의 공고를 찾았습니다. 내용을 수집합니다.")

    for link in links[:15]:  # 시간 관계상 일부만 수집 (필요시 조정)
        try:
            await page.goto(link, wait_until="domcontentloaded")
            await page.wait_for_selector("h1.title", timeout=10000)
            
            title = await page.locator("h1.title").inner_text()
            
            content = await page.locator(".detail-body").inner_text()
            
            jobs.append({
                "source": "잡코리아",
                "keyword": keyword,
                "title": title.strip(),
                "description": content.strip()
            })
        except PlaywrightTimeoutError:
            print(f"잡코리아 공고({link}) 내용을 가져오는 데 실패했습니다.")
        except Exception as e:
            print(f"처리 중 오류 발생: {link}, 오류: {e}")

    return jobs

async def main():
    """메인 실행 함수"""
    all_jobs = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False) # 브라우저 동작 확인을 위해 False로 설정
        page = await browser.new_page()

        for keyword in KEYWORDS:
            jobkorea_jobs = await scrape_jobkorea(page, keyword)
            all_jobs.extend(jobkorea_jobs)

        await browser.close()

    if all_jobs:
        # 데이터프레임으로 변환 후 CSV 파일로 저장
        df = pd.DataFrame(all_jobs)
        df.to_csv("jobkorea_postings.csv", index=False, encoding="utf-8-sig")
        print(f"\n스크레이핑 완료! 'jobkorea_postings.csv' 파일에 총 {len(all_jobs)}개의 공고가 저장되었습니다.")
    else:
        print("\n수집된 채용 공고가 없습니다.")

if __name__ == "__main__":
    asyncio.run(main())
