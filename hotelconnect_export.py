import os
import csv
import json
import time
import tempfile
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright
from openpyxl import load_workbook

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# ============================================================
# BEÁLLÍTÁSOK
# ============================================================

LOGIN_URL = "https://p.hotelconnect.hu/login"

EMAIL = os.environ["HOTELCONNECT_EMAIL"]
PASSWORD = os.environ["HOTELCONNECT_PASSWORD"]

GDRIVE_SERVICE_ACCOUNT_JSON = os.environ["GDRIVE_SERVICE_ACCOUNT_JSON"]

WAIT_COMPANY = 3
WAIT_NAV = 2

CURRENT_YEAR = datetime.now().year


# ============================================================
# HOTELCONNECT EGYSÉG -> DRIVE MAPPA
# ============================================================

COMPANIES = {
    "Maverick Athenaeum": {
        "code": "ATH",
        "folder_id": "19bo5GiU6lrPEgfrSbJrO74e7pWD9Ng7U",
    },

    "Maverick Downtown": {
        "code": "DT",
        "folder_id": "1HjE1CMPEIYHqG6HA7aPc5OqG0GAfHdXU",
    },

    "Maverick City Lodge": {
        "code": "SOHO",
        "folder_id": "1fz1PwvGgmam-vZpg9SF3chn7s4ujTUYf",
    },

    "Giselle Vintage Doubles": {
        "code": "GVD",
        "folder_id": "1WWJ3dhu1yw2Lfw3ZxqTqaRtLsjLmg1ac",
    },

    "Maverick Urban Lodge": {
        "code": "CENTRAL",
        "folder_id": "1OlJCdki0z-TC1lrewUrL4f0nPzGAbpwO",
    },

    "Giselle Buda Castle": {
        "code": "GBC",
        "folder_id": "1xk3SOqhKWNPbRMkgZM1JleGwgYHN8p2K",
    },

    "The Amberlyn Suite Hotel": {
        "code": "AMBERLYN",
        "folder_id": "102qpagWkmb8j9NO7IU93D6qTVVYdBGKt",
    },
}


# ============================================================
# GOOGLE DRIVE
# ============================================================

def get_drive_service():
    service_account_info = json.loads(
        GDRIVE_SERVICE_ACCOUNT_JSON
    )

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=[
            "https://www.googleapis.com/auth/drive"
        ],
    )

    return build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def upload_or_replace_file(
    drive_service,
    local_file,
    folder_id,
    drive_filename,
):
    """
    Ha a fájl már létezik a mappában, frissíti.
    Ha nincs, létrehozza.
    """

    safe_name = drive_filename.replace("'", "\\'")

    query = (
        f"name = '{safe_name}' "
        f"and '{folder_id}' in parents "
        f"and trashed = false"
    )

    result = (
        drive_service.files()
        .list(
            q=query,
            fields="files(id,name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )

    existing_files = result.get("files", [])

    media = MediaFileUpload(
        str(local_file),
        mimetype="text/csv",
        resumable=True,
    )

    if existing_files:
        file_id = existing_files[0]["id"]

        print(
            f"Drive fájl frissítése: "
            f"{drive_filename}"
        )

        drive_service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True,
        ).execute()

    else:
        print(
            f"Új Drive fájl létrehozása: "
            f"{drive_filename}"
        )

        metadata = {
            "name": drive_filename,
            "parents": [folder_id],
        }

        drive_service.files().create(
            body=metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute()


# ============================================================
# XLSX -> NYERS CSV
# ============================================================

def xlsx_to_csv(xlsx_path, csv_path):
    """
    Csak a cellák tényleges értékét menti.
    Nincs formázás, nincs stílus, nincs Excel sallang.
    """

    workbook = load_workbook(
        filename=xlsx_path,
        read_only=True,
        data_only=True,
    )

    worksheet = workbook.active

    with open(
        csv_path,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as csv_file:

        writer = csv.writer(
            csv_file,
            delimiter=",",
            quoting=csv.QUOTE_MINIMAL,
        )

        for row in worksheet.iter_rows(
            values_only=True
        ):
            writer.writerow(
                [
                    "" if value is None else value
                    for value in row
                ]
            )

    workbook.close()


# ============================================================
# HOTELCONNECT
# ============================================================

def run():
    drive_service = get_drive_service()

    # Ideiglenes könyvtár:
    # GitHub Actions futás végén úgyis eltűnik.
    temp_dir = Path(tempfile.mkdtemp())

    print(f"Ideiglenes könyvtár: {temp_dir}")

    success = []
    failed = []

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 900
            },
            accept_downloads=True,
        )

        page = context.new_page()

        page.set_default_timeout(60000)

        # ====================================================
        # LOGIN
        # ====================================================

        print("\nHotelConnect megnyitása...")

        page.goto(
            LOGIN_URL,
            wait_until="domcontentloaded"
        )

        page.locator(
            'input[type="email"]'
        ).fill(EMAIL)

        page.locator(
            'input[type="password"]'
        ).fill(PASSWORD)

        page.locator(
            'button[type="submit"]'
        ).click()

        page.wait_for_url(
            lambda url: "/login" not in url,
            timeout=60000
        )

        print("Sikeres belépés.")

        time.sleep(WAIT_COMPANY)

        # ====================================================
        # ELÉRHETŐ EGYSÉGEK KIOLVASÁSA
        # ====================================================

        buttons = page.locator(
            'aside button[title*="NTAK jelentés"]'
        )

        found_companies = []

        for i in range(buttons.count()):

            button = buttons.nth(i)

            name = (
                button
                .locator("span.truncate")
                .inner_text()
                .strip()
            )

            found_companies.append(name)

        print("\nHotelConnect egységek:")

        for name in found_companies:
            print(f" - {name}")

        # ====================================================
        # CSAK A KÉRT 7 EGYSÉG
        # ====================================================

        for company_name, config in COMPANIES.items():

            print("\n")
            print("=" * 65)
            print(company_name)
            print("=" * 65)

            if company_name not in found_companies:

                print(
                    "HIBA: az egység nem található "
                    "a HotelConnect listában."
                )

                failed.append(company_name)
                continue

            try:

                # ============================================
                # CÉG KIVÁLASZTÁSA
                # ============================================

                company_button = (
                    page
                    .locator(
                        'aside button[title*="NTAK jelentés"]'
                    )
                    .filter(
                        has=page.locator(
                            "span.truncate",
                            has_text=company_name,
                        )
                    )
                )

                print(
                    f"Egység kiválasztása: "
                    f"{company_name}"
                )

                company_button.click()

                time.sleep(WAIT_COMPANY)

                # ============================================
                # XLSX MENÜ
                # ============================================

                print(
                    "XLSX letöltés menü megnyitása..."
                )

                page.get_by_role(
                    "button",
                    name="XLSX letöltése",
                    exact=True,
                ).first.click()

                time.sleep(WAIT_NAV)

                # ============================================
                # EZ AZ ÉV
                # ============================================

                print("'Ez az év' kiválasztása...")

                page.get_by_role(
                    "button",
                    name="Ez az év",
                    exact=True,
                ).click()

                time.sleep(WAIT_NAV)

                # ============================================
                # LETÖLTÉS
                # ============================================

                print("Export letöltése...")

                with page.expect_download(
                    timeout=180000
                ) as download_info:

                    page.get_by_role(
                        "button",
                        name="XLSX letöltése",
                        exact=True,
                    ).last.click()

                download = download_info.value

                xlsx_path = (
                    temp_dir
                    / f"{config['code']}_{CURRENT_YEAR}.xlsx"
                )

                download.save_as(
                    str(xlsx_path)
                )

                print(
                    f"XLSX letöltve: "
                    f"{xlsx_path.stat().st_size / 1024 / 1024:.2f} MB"
                )

                # ============================================
                # CSV KÉSZÍTÉS
                # ============================================

                csv_filename = (
                    f"hotelconnect_"
                    f"{config['code']}_"
                    f"{CURRENT_YEAR}.csv"
                )

                csv_path = (
                    temp_dir
                    / csv_filename
                )

                print(
                    "Átalakítás nyers CSV-vé..."
                )

                xlsx_to_csv(
                    xlsx_path,
                    csv_path
                )

                print(
                    f"CSV méret: "
                    f"{csv_path.stat().st_size / 1024 / 1024:.2f} MB"
                )

                # XLSX törlése
                try:
                    xlsx_path.unlink()
                except Exception:
                    pass

                # ============================================
                # DRIVE FELTÖLTÉS
                # ============================================

                upload_or_replace_file(
                    drive_service=drive_service,
                    local_file=csv_path,
                    folder_id=config["folder_id"],
                    drive_filename=csv_filename,
                )

                print(
                    f"KÉSZ: {company_name}"
                )

                success.append(company_name)

                # helyi CSV sem kell tovább
                try:
                    csv_path.unlink()
                except Exception:
                    pass

                time.sleep(WAIT_NAV)

            except Exception as error:

                print(
                    f"HIBA: {company_name}"
                )

                print(error)

                failed.append(company_name)

                # Ha modal nyitva maradt
                try:
                    cancel = page.get_by_role(
                        "button",
                        name="Mégse",
                        exact=True,
                    )

                    if cancel.is_visible():
                        cancel.click()
                        time.sleep(WAIT_NAV)

                except Exception:
                    pass

                continue

        browser.close()

    # ========================================================
    # ÖSSZEGZÉS
    # ========================================================

    print("\n")
    print("=" * 65)
    print("FUTÁS VÉGE")
    print("=" * 65)

    print("\nSikeres:")

    for name in success:
        print(f" OK  {name}")

    if failed:
        print("\nHibás:")

        for name in failed:
            print(f" ERR {name}")

        raise RuntimeError(
            f"{len(failed)} egység feldolgozása sikertelen."
        )

    print("\nMinden egység sikeresen elkészült.")


if __name__ == "__main__":
    run()
