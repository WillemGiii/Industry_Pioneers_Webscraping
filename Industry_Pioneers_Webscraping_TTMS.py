import argparse
import csv
import datetime
import re
from pathlib import Path
from time import sleep
from typing import Sequence

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


TARGET_URL = "https://ttms.etraining.gov.tw/eYVTR/YipClassApply"
ROW_SELECTOR = "tbody#rows > tr"
NEXT_PAGE_SELECTOR = "button#nextPage"
DATE_PATTERN = re.compile(r"\d{2,3}/\d{2}/\d{2}")
PAGE_DELAY_SECONDS = 1
FIELDNAMES = [
    "Serial_Number",
    "CourseCategory",
    "CourseName",
    "TrainingUnit",
    "ClassLocation",
    "StartDate",
    "EndDate",
    "SignUps",
]


def get_search_end_date(reference_date: datetime.date | None = None) -> str:
    """依參考日期回傳查詢用的民國年半年底日期。"""
    target_date = reference_date or datetime.date.today()
    roc_year = target_date.year - 1911
    cutoff_date = datetime.date(target_date.year, 6, 30)

    if target_date <= cutoff_date:
        return f"{roc_year}/06/30"
    return f"{roc_year}/12/31"


def modified_time_sent_search(
    driver: webdriver.Chrome,
    reference_date: datetime.date | None = None,
) -> None:
    """填入截止日期並送出查詢表單。

    以今日日期為基準，計算對應的民國年截止日期：
    若今日在 6 月 30 日（含）以前，截止日為當年 6/30；
    否則截止日為當年 12/31。
    """
    wait = WebDriverWait(driver, 15)
    modified_time_column = wait.until(
        EC.element_to_be_clickable((By.ID, "Form_FTDATE_TW"))
    )
    previous_rows = driver.find_elements(By.CSS_SELECTOR, ROW_SELECTOR)
    end_date = get_search_end_date(reference_date)

    modified_time_column.clear()
    modified_time_column.send_keys(end_date)

    send_button = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "div.yipq__actions > button[type='submit']")
        )
    )
    send_button.click()
    print(f"[Info] 已以截止日 {end_date} 送出查詢，等待頁面載入...")

    if previous_rows:
        wait.until(EC.staleness_of(previous_rows[0]))


def fetch_table_rows(driver: webdriver.Chrome) -> list[WebElement] | None:
    """等待並取得表格中所有列的 WebElement 清單。"""
    wait = WebDriverWait(driver, 15)

    try:
        rows_elements = wait.until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ROW_SELECTOR))
        )
        print(f"[Info] 成功載入表格，本頁共 {len(rows_elements)} 筆資料。")
        return rows_elements
    except TimeoutException:
        print("[Warn] 等待超時：頁面中未出現指定的表格結構。")
        return None


def access_project_detail(
    driver: webdriver.Chrome,
    rows_elements: Sequence[WebElement],
) -> list[dict[str, str]]:
    """走訪表格每一列，擷取各欄位資料並彙整成字典清單。"""
    current_page_data: list[dict[str, str]] = []

    for index, element in enumerate(rows_elements):
        for attempt in range(3):
            try:
                if attempt > 0:
                    all_rows = driver.find_elements(By.CSS_SELECTOR, ROW_SELECTOR)
                    if index >= len(all_rows):
                        break
                    element = all_rows[index]

                tds = element.find_elements(By.TAG_NAME, "td")

                # 會取用 tds[6]，因此至少需要 7 個欄位。
                if len(tds) < 7:
                    print(
                        f"[Warn] 第 {index + 1} 列只有 {len(tds)} 個欄位，"
                        "已略過該列。"
                    )
                    break

                matched_dates = DATE_PATTERN.findall(tds[5].text)
                if len(matched_dates) >= 2:
                    start_date, end_date = matched_dates[:2]
                else:
                    start_date = ""
                    end_date = ""
                    print(
                        f"[Warn] 第 {index + 1} 列日期格式不正確: "
                        f"{tds[5].text}"
                    )

                current_page_data.append(
                    {
                        "Serial_Number": tds[0].text.strip(),
                        "CourseCategory": tds[1].text.strip(),
                        "CourseName": tds[2].text.strip(),
                        "TrainingUnit": tds[3].text.strip(),
                        "ClassLocation": tds[4].text.strip(),
                        "StartDate": start_date,
                        "EndDate": end_date,
                        "SignUps": tds[6].text.strip(),
                    }
                )
                break
            except StaleElementReferenceException:
                print(
                    f"[Warn] 第 {index + 1} 列 WebElement 已過期，"
                    f"第 {attempt + 1} 次重試..."
                )
                sleep(1)
            except NoSuchElementException as error:
                print(f"[Warn] 解析第 {index + 1} 列時發生元素遺失: {error}")
                break
            except Exception as error:
                print(f"[Error] 解析第 {index + 1} 列時發生未預期的錯誤: {error}")
                break

    return current_page_data


def get_next_page(
    driver: webdriver.Chrome,
    current_rows: Sequence[WebElement],
) -> bool:
    """若尚有下一頁，點擊翻頁並等待新的列載入。"""
    wait = WebDriverWait(driver, 30)

    try:
        next_page_button = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, NEXT_PAGE_SELECTOR))
        )
    except TimeoutException as error:
        raise RuntimeError("找不到下一頁按鈕，無法確認資料是否完整。") from error

    if (
        not next_page_button.is_enabled()
        or next_page_button.get_attribute("disabled") is not None
    ):
        print("[Info] 已到達最後一頁，停止翻頁。")
        return False

    previous_first_row = current_rows[0] if current_rows else None
    next_page_button = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, NEXT_PAGE_SELECTOR))
    )
    next_page_button.click()
    print("[Info] 下一頁已點擊，等待頁面載入...")

    if previous_first_row is not None:
        wait.until(EC.staleness_of(previous_first_row))
    wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, ROW_SELECTOR)))
    sleep(PAGE_DELAY_SECONDS)
    return True


def save_information_detail(output_path: Path | None = None) -> Path:
    """產生 CSV 輸出路徑，預設與本腳本位於同一目錄。"""
    if output_path is not None:
        return output_path

    today = datetime.date.today()
    file_name = f"{today}_Industry_Pioneers_Number_of_applicants_TTMS.csv"
    return Path(__file__).parent / file_name


def write_csv(file_name: Path, daily_record_list: Sequence[dict[str, str]]) -> None:
    """將課程資料寫入 UTF-8 BOM CSV。"""
    file_name.parent.mkdir(parents=True, exist_ok=True)
    with file_name.open("w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(daily_record_list)


def create_driver(headless: bool = False) -> webdriver.Chrome:
    """建立 Chrome WebDriver。"""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(options=options)


def validate_records(records: Sequence[dict[str, str]]) -> None:
    """確認擷取結果的序號連續，避免寫出不完整的 CSV。"""
    if not records:
        return

    try:
        serial_numbers = [int(record["Serial_Number"]) for record in records]
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("資料序號缺失或格式不正確。") from error

    expected_serial_numbers = list(range(1, len(records) + 1))
    if serial_numbers != expected_serial_numbers:
        raise RuntimeError(
            "資料序號不連續，可能有重複或遺漏的翻頁資料。"
        )


def scrape_all_pages(driver: webdriver.Chrome) -> list[dict[str, str]]:
    """查詢並擷取所有頁面的課程資料。"""
    modified_time_sent_search(driver)
    daily_record_list: list[dict[str, str]] = []
    page_num = 1

    while True:
        print(f"[Info] 正在擷取第 {page_num} 頁資料...")
        rows_elements = fetch_table_rows(driver)
        if rows_elements is None:
            raise RuntimeError("無法取得表格資料，未寫入 CSV。")

        current_page_data = access_project_detail(driver, rows_elements)
        if len(current_page_data) != len(rows_elements):
            raise RuntimeError(
                f"第 {page_num} 頁顯示 {len(rows_elements)} 列，"
                f"但只成功解析 {len(current_page_data)} 列，未寫入 CSV。"
            )
        daily_record_list.extend(current_page_data)

        if not get_next_page(driver, rows_elements):
            break
        page_num += 1

    validate_records(daily_record_list)
    return daily_record_list


def main(
    *,
    headless: bool = False,
    output_path: Path | None = None,
) -> Path:
    """啟動 WebDriver，擷取 TTMS 公開課程報名人數並輸出 CSV。"""
    driver = create_driver(headless=headless)
    try:
        driver.get(TARGET_URL)
        print(f"[Info] 頁面標題: {driver.title}")
        daily_record_list = scrape_all_pages(driver)
    finally:
        driver.quit()

    file_name = save_information_detail(output_path)
    write_csv(file_name, daily_record_list)
    print(f"[Info] 已寫入 {len(daily_record_list)} 筆資料: {file_name}")
    return file_name


def parse_args() -> argparse.Namespace:
    """解析命令列參數。"""
    parser = argparse.ArgumentParser(
        description="擷取產業新尖兵 TTMS 公開課程報名人數。"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="使用無頭模式執行 Chrome。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="指定 CSV 輸出路徑。",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    main(headless=arguments.headless, output_path=arguments.output)
