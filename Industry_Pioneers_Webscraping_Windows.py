import csv
import datetime
import os
from pathlib import Path
from time import sleep
from dotenv import load_dotenv
import ddddocr
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import re


def login(driver: webdriver.Chrome) -> None:
    """點擊首頁的「前往會員登入」按鈕，跳轉至登入頁面。

    Args:
        driver: Selenium WebDriver 實例。
    """
    wait = WebDriverWait(driver, 10)
    login_button = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "a[title='前往會員登入']"))
    )
    login_button.click()

def close_change_password_popup(driver: webdriver.Chrome) -> None:
    """若出現變更密碼提視窗，點擊取消"""
    wait = WebDriverWait(driver, 10)
    try:
        popup = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.jconfirm-box")))

        if popup:
            cancel_buttons = driver.find_elements(By.CSS_SELECTOR, "button.btn.btn-info")
        if len(cancel_buttons) >=2:
            cancel_buttons[1].click()
            print("已關閉密碼提示視窗")
        else:
            print("找到提示視窗，但找到取消按鈕")
    except TimeoutException:
        print("未出現變更密碼提示視窗，略過")


def get_captcha_image_bytes(driver: webdriver.Chrome) -> bytes:
    """切換至驗證碼 iframe（name='imgCapt1'），截取其中的圖片二進位資料。

    驗證碼並不是一個 <img> 元素，而是一個獨立的 <iframe>，
    iframe 內部才有真正的圖片。作法是切換至該 iframe，
    找到 <img> 元素後直接截圖，再切回主框架。

    Args:
        driver: Selenium WebDriver 實例。

    Returns:
        驗證碼圖片的 PNG 二進位資料。
    """
    wait = WebDriverWait(driver, 15)

    # 找到驗證碼 iframe（以 name 屬性定位）
    captcha_iframe = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[name='imgCapt1']"))
    )
    driver.switch_to.frame(captcha_iframe)
    print("[Info] 已切換至驗證碼 iframe")

    # 在 iframe 內，取得唯一的 <img> 元素並截圖
    captcha_img = wait.until(
        EC.presence_of_element_located((By.TAG_NAME, "img"))
    )
    image_bytes = captcha_img.screenshot_as_png
    print("[Info] 成功截取驗證碼圖片")

    # 切回主框架
    driver.switch_to.default_content()
    return image_bytes


def fill_login_info(
    driver: webdriver.Chrome, username: str, password: str
) -> None:
    """填入帳號、密碼、驗證碼並送出表單。

    所有表單元素（CPH1_*）均位於主框架中。
    驗證碼圖片位於 iframe[name='imgCapt1'] 內。

    Args:
        driver: Selenium WebDriver 實例。
        username: 登入用電子郵件帳號。
        password: 登入密碼。
    """
    wait = WebDriverWait(driver, 15)

    # 步驟一：等待表單輸入框出現（均在主框架）
    username_input = wait.until(
        EC.presence_of_element_located((By.ID, "CPH1_txt_EmailId"))
    )
    password_input = driver.find_element(By.ID, "CPH1_txt_dwsp")
    captcha_text_input = driver.find_element(By.ID, "CPH1_txt_VerifyCode")
    print("[Info] 成功定位表單輸入框")

    # 步驟二：取得驗證碼圖片資料並以 OCR 辨識
    image_bytes = get_captcha_image_bytes(driver)
    ocr = ddddocr.DdddOcr(ocr=True, show_ad=False)
    captcha_text = ocr.classification(image_bytes).strip()
    print(f"[Info] 驗證碼辨識結果: {captcha_text}")

    # 步驟三：填入帳號、密碼、驗證碼
    username_input.clear()
    username_input.send_keys(username)
    password_input.clear()
    password_input.send_keys(password)
    captcha_text_input.clear()
    captcha_text_input.send_keys(captcha_text)
    print("[Info] 表單填寫完成，準備送出")

    login_submit_button = wait.until(
        EC.element_to_be_clickable((By.ID, "CPH1_btnLogin"))
    )
    login_submit_button.click()
    print("[Info] 登入按鈕已點擊，等待跳轉...")
    close_change_password_popup(driver)


def attend_project(driver: webdriver.Chrome) -> None:
    """點擊「申請參加計畫」按鈕，跳轉至申請頁面。

    Args:
        driver: Selenium WebDriver 實例。
    """
    wait = WebDriverWait(driver, 15)
    attend_project_button = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "a[title='申請參加計畫']"))
    )
    attend_project_button.click()
    print("[Info] 申請參加計畫按鈕已點擊，等待跳轉...")


def modified_time_sent_search(driver: webdriver.Chrome) -> None:
    """填入截止日期並送出查詢表單。

    以今日日期為基準，計算對應的民國年截止日期：
    若今日在 6 月 30 日（含）以前，截止日為當年 6/30；
    否則截止日為當年 12/31。

    Args:
        driver: Selenium WebDriver 實例。
    """
    wait = WebDriverWait(driver, 15)
    modified_time_column = wait.until(
        EC.element_to_be_clickable((By.ID, "Form_FTDATE_TW"))
    )

    target_date = datetime.date.today()
    # 計算民國年 (西元年 - 1911)
    roc_year = target_date.year - 1911

    # 定義當年的 6月 30日 作為分界點
    cutoff_date = datetime.date(target_date.year, 6, 30)

    # 判斷目標日期是否在 6月30日 (含)以前
    if target_date <= cutoff_date:
        end_date = f"{roc_year}/06/30"
    else:
        end_date = f"{roc_year}/12/31"

    modified_time_column.clear()
    modified_time_column.send_keys(end_date)

    send_button = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "button[title='送出']"))
    )
    send_button.click()
    print("[Info] 查詢按鈕已點擊，等待跳轉...")

def fetch_table_rows(
    driver: webdriver.Chrome,
) -> list | None:
    """等待並取得表格中所有列的 WebElement 清單。

    使用 ``presence_of_all_elements_located`` 條件，只要 DOM 中出現
    至少一個符合 ``tbody#rows > tr`` 的元素，就立即回傳整個清單。

    Args:
        driver: Selenium WebDriver 實例。

    Returns:
        包含所有 ``<tr>`` WebElement 的串列；若等待超時則回傳 ``None``。

    Raises:
        TimeoutException: 當頁面在等待時限內未出現指定的表格結構時捕捉並印出，
            不向上傳遞。
    """
    wait = WebDriverWait(driver, 15)

    try:
        # 使用 presence_of_all_elements_located 條件
        # 只要 DOM 中出現一個符合 CSS_Selector 的 <tr> (列)，就會回傳一個包含所有已定位 WebElements 的串列
        locator = (By.CSS_SELECTOR, "tbody#rows > tr")
        rows_elements = wait.until(EC.presence_of_all_elements_located(locator))

        # 取得實際載入的列數
        print(f"成功載入表格，共獲得 {len(rows_elements)} 筆資料")

        return rows_elements

    except TimeoutException:
        print("等待超時：頁面中未出現指定的表格結構。")
        return None
    

def access_project_detail(
    driver: webdriver.Chrome,
    rows_elements: list,
) -> list:
    """走訪表格每一列，擷取各欄位資料並彙整成字典清單。

    針對翻頁後的 DOM 重繪情境，本函式在每列的處理中捕捉
    ``StaleElementReferenceException``，並重新透過 ``driver`` 定位
    該列元素，以避免持有失效的 WebElement 參照。

    Args:
        driver: Selenium WebDriver 實例。
        rows_elements: 由 ``fetch_table_rows`` 回傳的 ``<tr>`` WebElement 清單。

    Returns:
        包含每列資料字典的清單，每個字典的鍵對應欄位名稱。
    """
    current_page_data: list[dict] = []

    for index, element in enumerate(rows_elements):
        # 最多重試 3 次，以應對頁面局部刷新造成的 Stale 問題
        for attempt in range(3):
            try:
                # 若 element 已失效，重新從 DOM 定位同位置的 <tr>
                if attempt > 0:
                    all_rows = driver.find_elements(
                        By.CSS_SELECTOR, "tbody#rows > tr"
                    )
                    if index >= len(all_rows):
                        break
                    element = all_rows[index]

                # 取得該列 (Row) 內所有的行 (Column)
                tds = element.find_elements(By.TAG_NAME, "td")

                # 確保該列的行數足夠，避免 IndexError
                if len(tds) < 6:
                    break

                # 注意 nth-child 是 1-based (第 6 個 td)
                duration_element = element.find_element(
                    By.CSS_SELECTOR, "td:nth-child(6).text-center"
                )
                data_pattern = r"\d{2,3}/\d{2}/\d{2}"
                matched_dates = re.findall(data_pattern, duration_element.text)
                if len(matched_dates) >=2:
                    start_date = matched_dates[0]
                    end_date = matched_dates[1]
                else:
                    start_date = ""
                    end_date = ""
                    print(f"[Warn] 第 {index + 1} 列日期格式不正確: {duration_element.text}")

                # 建立資料字典
                row_dict = {
                    "Serial_Number": tds[0].text.strip(),
                    "CourseCategory": tds[1].text.strip(),
                    "CourseName": tds[2].text.strip(),
                    "TrainingUnit": tds[3].text.strip(),
                    "ClassLocation": tds[4].text.strip(),
                    "StartDate": start_date,
                    "EndDate": end_date,
                    "SignUps": tds[-1].text.strip(),
                }

                current_page_data.append(row_dict)
                break  # 成功則跳出重試迴圈

            except StaleElementReferenceException:
                print(f"[Warn] 第 {index + 1} 列 WebElement 已過期，第 {attempt + 1} 次重試...")
                sleep(1)
            except NoSuchElementException as e:
                print(f"[Warn] 解析第 {index + 1} 列時發生元素遺失: {e}")
                break
            except Exception as e:
                print(f"[Error] 解析第 {index + 1} 列時發生未預期的錯誤: {e}")
                break

    return current_page_data

def get_next_page(driver: webdriver.Chrome) -> None:
    """等待頁面 Loading 遮罩消失後，點擊翻頁器的「下一頁」按鈕，
    並再次等待遮罩出現後消失，確認新頁面完全載入才返回。

    網站在翻頁時會顯示 ``blockUI blockOverlay`` 全畫面遮罩阻擋互動。
    若在遮罩存在時點擊按鈕，將引發 ``ElementClickInterceptedException``。

    Args:
        driver: Selenium WebDriver 實例。
    """
    overlay_locator = (By.CSS_SELECTOR, "div.blockUI.blockOverlay")
    wait = WebDriverWait(driver, 30)

    # 步驟一：確保點擊前遮罩已消失（前一次翻頁的 Loading 已結束）
    wait.until(EC.invisibility_of_element_located(overlay_locator))
    print("[Info] Loading 遮罩已消失，準備點擊下一頁...")

    # 步驟二：等待「下一頁」按鈕可點擊後執行點擊
    next_page_button = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "div.news-pager-main > a#nextPage")
        )
    )
    next_page_button.click()
    print("[Info] 下一頁已點擊，等待頁面載入...")

    # 步驟三：等待新頁面的 Loading 遮罩出現後再消失，確認載入完成
    try:
        # 先等遮罩出現（翻頁觸發 Loading）
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(overlay_locator)
        )
        # 再等遮罩消失（Loading 結束）
        wait.until(EC.invisibility_of_element_located(overlay_locator))
    except TimeoutException:
        # 若遮罩未出現（頁面太快載完），直接繼續即可
        pass
    print("[Info] 新頁面載入完成。")

def save_information_detail() -> Path:
    """產生今日的 CSV 輸出路徑（與本腳本位於同一目錄）。

    Returns:
        以今日日期命名的 CSV ``Path`` 物件。
    """
    today = datetime.date.today()
    file_name = f"{today}_Industry_Pioneers_Number_of_applicants.csv"
    return Path(__file__).parent / file_name



def main() -> None:
    """主程式入口：載入憑證、啟動 WebDriver 並完成登入流程。"""
    # 步驟一：載入 .env 檔案中的環境變數
    load_dotenv()

    # 步驟二：使用 os.getenv() 提取變數
    username = os.getenv("INDUSTRY_PIONEERS_USERNAME")
    password = os.getenv("INDUSTRY_PIONEERS_PASSWORD")

    if not username or not password:
        raise EnvironmentError(
            "無法取得登入憑證，請確認 .env 檔案是否存在且設定正確"
        )

    # 步驟三：建立 ChromeOptions 並啟動 WebDriver
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = webdriver.Chrome(options=options)

    try:
        driver.get("https://elite.taiwanjobs.gov.tw/ClassSearch")
        print("Page Title:", driver.title)

        login(driver)
        print("Page Title:", driver.title)

        fill_login_info(driver, username, password)
        sleep(5)
        print("Page Title:", driver.title)

        attend_project(driver)
        sleep(5)
        print("Page Title:", driver.title)

        modified_time_sent_search(driver)
        sleep(5)
        print("Page Title:", driver.title)
        sleep(5)
        
        daily_record_list: list[dict] = []
        page_num = 1
        wait = WebDriverWait(driver, 10)
        while True:
            
            rows_elements = fetch_table_rows(driver)

            # 防衛：若表格未出現（fetch 回傳 None），直接結束迴圈
            if rows_elements is None:
                print("[Warn] 無法取得表格資料，停止翻頁。")
                break

            daily_record_list.extend(access_project_detail(driver, rows_elements))

            try:
                next_page_button = wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div.news-pager-main > a#nextPage")
                    )
                )
                # class 屬性可能為複合字串，如 "btn-pager disabled"，需用 in 判斷
                btn_class = next_page_button.get_attribute("class") or ""
                if "disabled" in btn_class:
                    print("[Info] 已到達最後一頁，停止翻頁。")
                    break
            except TimeoutException:
                print("[Info] 找不到下一頁按鈕，停止翻頁。")
                break

            print(f"[Info] 正在擷取第 {page_num} 頁資料...")
            # 判斷「下一頁」按鈕是否存在且未被 disabled
            

            sleep(3)
            get_next_page(driver)
            sleep(3)  # 等待新頁面 DOM 穩定後再繼續
            page_num += 1

        file_name = save_information_detail()

        fieldnames = [
            "Serial_Number",
            "CourseCategory",
            "CourseName",
            "TrainingUnit",
            "ClassLocation",
            "StartDate",
            "EndDate",
            "SignUps",
        ]
        # 副總!!! daily_record_list 是 list of dicts，是每一筆課程的資料

        with file_name.open("w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(daily_record_list)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()