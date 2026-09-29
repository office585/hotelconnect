import json
import os
import sys
import time
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://p.hotelconnect.hu/login"

EMAIL = os.environ.get("HOTELCONNECT_EMAIL", "buki.bertold@mavericklodges.com")
PASSWORD = os.environ.get("HOTELCONNECT_PASSWORD", "Lebonote10@@@@")

# Temp / Munkamenet mappa
DOWNLOAD_DIR = Path.home() / "Downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Várakozások (másodperc)
WAIT_COMPANY = 3
WAIT_NAV = 2

# Cégek és Google Drive mappa azonosítók
DRIVE_FOLDERS = {
    "Maverick Athenaeum": "19bo5GiU6lrPEgfrSbJrO74e7pWD9Ng7U",
    "Maverick Downtown": "1HjE1CMPEIYHqG6HA7aPc5OqG0GAfHdXU",
    "Maverick City Lodge": "1fz1PwvGgmam-vZpg9SF3chn7s4ujTUYf",
    "Giselle Vintage Doubles": "1WWJ3dhu1yw2Lfw3ZxqTqaRtLsjLmg1ac",
    "Maverick Urban Lodge": "1OlJCdki0z-TC1lrewUrL4f0nPzGAbpwO",
    "Giselle Buda Castle": "1xk3SOqhKWNPbRMkgZM1JleGwgYHN8p2K",
    "The Amberlyn Suite Hotel": "102qpagWkmb8j9NO7IU93D6qTVVYdBGKt",
}


def get_drive_service():
    """Google Drive kliens inicializálása Secretből."""
    json_str = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON")
    if not json_str:
        print("FIGYELEM: GDRIVE_SERVICE_ACCOUNT_JSON nincs megadva, Drive feltöltés kihagyva.")
        return None
    try:
        info = json.loads(json_str)
        creds = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        print(f"Hiba a Google Drive kapcsolódás során: {e}")
        return None


def upload_to_drive(drive_service, file_path, folder_id, file_name):
    """Fájl feltöltése vagy frissítése a cél Drive mappában."""
    if not drive_service or not folder_id:
        return

    try:
        # Ellenőrizzük, létezik-e már ilyen nevű fájl a mappában
        query = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])

        media = MediaFileUpload(str(file_path), resumable=True)

        if files:
            file_id = files[0]["id"]
            drive_service.files().update(
                fileId=file_id,
                media_body=media
            ).execute()
            print(f"  -> Drive fájl frissítve: {file_name}")
        else:
            file_metadata = {
                "name": file_name,
                "parents": [folder_id]
            }
            drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id"
            ).execute()
            print(f"  -> Drive fájl feltöltve: {file_name}")
    except Exception as e:
        print(f"  -> HIBA a Drive feltöltéskor ({file_name}): {e}")


def safe_filename(name):
    """Fájlnévhez biztonságos cégnév."""
    return (
        name.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("*", "_")
        .replace("?", "_")
        .replace('"', "_")
        .replace("<", "_")
        .replace(">", "_")
        .replace("|", "_")
    )


def main():
    drive_service = get_drive_service()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False
        )

        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=True
        )

        page = context.new_page()
        page.set_default_timeout(60000)

        # =====================================================
        # LOGIN (KÉZI GÉPELÉS SZIMULÁCIÓ)
        # =====================================================
        print("Login oldal megnyitása...")
        page.goto(LOGIN_URL, wait_until="networkidle")
        time.sleep(2)

        print("Email mező kijelölése és gépelés...")
        email_field = page.locator('input[type="email"]')
        email_field.click()
        time.sleep(0.5)
        email_field.press_sequentially(EMAIL, delay=80)

        time.sleep(0.5)

        print("Jelszó mező kijelölése és gépelés...")
        password_field = page.locator('input[type="password"]')
        password_field.click()
        time.sleep(0.5)
        password_field.press_sequentially(PASSWORD, delay=80)

        time.sleep(1)

        print("Bejelentkezés (Enter lenyomása)...")
        password_field.press("Enter")

        # Megvárjuk az oldalsáv cég gombjainak megjelenését (sikeres belépés garanciája)
        print("Várakozás a sikeres bejelentkezésre...")
        company_buttons = page.locator('aside button[title*="NTAK jelentés"]')
        company_buttons.first.wait_for(state="visible", timeout=60000)

        print("Sikeres belépés!")
        print("Aktuális URL:", page.url)

        time.sleep(WAIT_COMPANY)

        # =====================================================
        # CÉGEK KIOLVASÁSA
        # =====================================================
        company_count = company_buttons.count()
        print(f"\nTalált cégek száma: {company_count}")

        companies = []
        for i in range(company_count):
            button = company_buttons.nth(i)
            company_name = button.locator("span.truncate").inner_text().strip()
            companies.append(company_name)
            print(f"  {i + 1}. {company_name}")

        # =====================================================
        # CÉGEKEN VÉGIGMEGYÜNK
        # =====================================================
        for index, company_name in enumerate(companies, start=1):

            print("\n" + "=" * 60)
            print(f"[{index}/{len(companies)}] {company_name}")
            print("=" * 60)

            try:
                # ---------------------------------------------
                # CÉGVÁLTÁS
                # ---------------------------------------------
                print(f"Cég kiválasztása: {company_name}")

                company_button = page.locator('aside button').filter(
                    has=page.locator("span.truncate", has_text=company_name)
                )

                company_button.click()
                time.sleep(WAIT_COMPANY)

                # ---------------------------------------------
                # XLSX LETÖLTÉSE - FŐ GOMB
                # ---------------------------------------------
                print("XLSX letöltése menü megnyitása...")

                xlsx_buttons = page.get_by_role(
                    "button",
                    name="XLSX letöltése",
                    exact=True
                )

                xlsx_buttons.first.click()
                time.sleep(WAIT_NAV)

                # ---------------------------------------------
                # EZ AZ ÉV
                # ---------------------------------------------
                print("'Ez az év' kiválasztása...")

                page.get_by_role(
                    "button",
                    name="Ez az év",
                    exact=True
                ).click()

                time.sleep(WAIT_NAV)

                # ---------------------------------------------
                # MODÁLIS XLSX LETÖLTÉS
                # ---------------------------------------------
                print("XLSX export indítása...")

                modal_xlsx_button = page.get_by_role(
                    "button",
                    name="XLSX letöltése",
                    exact=True
                ).last

                with page.expect_download(timeout=120000) as download_info:
                    modal_xlsx_button.click()

                download = download_info.value
                original_filename = download.suggested_filename
                extension = Path(original_filename).suffix or ".xlsx"

                filename = f"{safe_filename(company_name)}_ez_az_ev{extension}"
                destination = DOWNLOAD_DIR / filename

                download.save_as(str(destination))
                print(f"Letöltve helyileg: {destination}")

                # ---------------------------------------------
                # GOOGLE DRIVE FELTÖLTÉS
                # ---------------------------------------------
                folder_id = DRIVE_FOLDERS.get(company_name)
                if not folder_id:
                    # Részleges egyezés keresése, ha a név nem 100%-ig pontos
                    for key, f_id in DRIVE_FOLDERS.items():
                        if key.lower() in company_name.lower() or company_name.lower() in key.lower():
                            folder_id = f_id
                            break

                if folder_id:
                    print(f"Feltöltés Google Drive-ra (Folder ID: {folder_id})...")
                    upload_to_drive(drive_service, destination, folder_id, filename)
                else:
                    print(f"FIGYELEM: Nincs Drive mappa társítva ehhez a céghez: {company_name}")

                time.sleep(WAIT_NAV)

            except Exception as e:
                print(f"HIBA ennél a cégnél: {company_name}")
                print(str(e))

                try:
                    cancel_button = page.get_by_role(
                        "button",
                        name="Mégse",
                        exact=True
                    )

                    if cancel_button.is_visible():
                        cancel_button.click()
                        time.sleep(WAIT_NAV)

                except Exception:
                    pass

                continue

        # =====================================================
        # KÉSZ
        # =====================================================
        print("\n" + "=" * 60)
        print("MINDEN CÉG FELDOLGOZÁSA BEFEJEZŐDÖTT")
        print("=" * 60)

        if sys.stdin.isatty():
            input("\nENTER = böngésző bezárása...")

        browser.close()


if __name__ == "__main__":
    main()
