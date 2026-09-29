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

# Temp letöltési mappa
DOWNLOAD_DIR = Path.home() / "Downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Szigorú várakozási idők
LOGIN_TIMEOUT_MS = 15000
WAIT_COMPANY = 3
WAIT_NAV = 2

# Google Drive Megosztott Meghajtó Mappa ID-k
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
    """Google Drive API kliens inicializálása Secretből."""
    json_str = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON")
    if not json_str:
        print("FIGYELEM: GDRIVE_SERVICE_ACCOUNT_JSON nincs megadva!")
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
    """Fájl feltöltése vagy frissítése a Megosztott Meghajtó célmappájában."""
    if not drive_service or not folder_id:
        return

    try:
        # Lévő fájl keresése a Megosztott Meghajtón
        query = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
        results = drive_service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = results.get("files", [])

        media = MediaFileUpload(str(file_path), resumable=True)

        if files:
            # Létező fájl frissítése
            file_id = files[0]["id"]
            drive_service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True
            ).execute()
            print(f"  -> Google Drive: Fájl sikeresen frissítve: {file_name}")
        else:
            # Új fájl feltöltése
            file_metadata = {
                "name": file_name,
                "parents": [folder_id]
            }
            drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True
            ).execute()
            print(f"  -> Google Drive: Fájl sikeresen feltöltve: {file_name}")
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
        browser = p.chromium.launch(headless=False)

        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
            locale="hu-HU",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        page = context.new_page()
        page.set_default_timeout(30000)

        # =====================================================
        # LOGIN
        # =====================================================
        print("Login oldal megnyitása...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        time.sleep(1)

        print("Email mező kitöltése...")
        email_field = page.locator('input[type="email"]')
        email_field.click()
        email_field.fill(EMAIL)

        print("Jelszó mező kitöltése...")
        password_field = page.locator('input[type="password"]')
        password_field.click()
        password_field.fill(PASSWORD)

        time.sleep(0.5)

        print("Bejelentkezés indítása...")
        password_field.press("Enter")
        time.sleep(0.3)

        submit_btn = page.locator('button[type="submit"]').filter(has_text="Bejelentkezés")
        if submit_btn.is_visible():
            submit_btn.click(force=True)

        print("Várakozás a sikeres bejelentkezésre...")
        try:
            company_buttons = page.locator('aside button').filter(has=page.locator("span.truncate"))
            company_buttons.first.wait_for(state="visible", timeout=LOGIN_TIMEOUT_MS)
        except Exception as e:
            page.screenshot(path="login_error.png")
            print("\n[HIBA] Nem sikerült belépni!")
            raise e

        print("Sikeres belépés!")
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
                print(f"Cég kiválasztása: {company_name}")

                company_button = page.locator('aside button').filter(
                    has=page.locator("span.truncate", has_text=company_name)
                )

                company_button.click()
                time.sleep(WAIT_COMPANY)

                print("XLSX letöltése menü megnyitása...")
                xlsx_buttons = page.get_by_role(
                    "button",
                    name="XLSX letöltése",
                    exact=True
                )
                xlsx_buttons.first.click()
                time.sleep(WAIT_NAV)

                print("'Ez az év' kiválasztása...")
                page.get_by_role(
                    "button",
                    name="Ez az év",
                    exact=True
                ).click()
                time.sleep(WAIT_NAV)

                print("XLSX export indítása...")
                modal_xlsx_button = page.get_by_role(
                    "button",
                    name="XLSX letöltése",
                    exact=True
                ).last

                with page.expect_download(timeout=60000) as download_info:
                    modal_xlsx_button.click()

                download = download_info.value
                original_filename = download.suggested_filename
                extension = Path(original_filename).suffix or ".xlsx"

                filename = f"{safe_filename(company_name)}_ez_az_ev{extension}"
                destination = DOWNLOAD_DIR / filename

                download.save_as(str(destination))
                print(f"Letöltve helyileg: {destination}")

                # ---------------------------------------------
                # FELTÖLTÉS GOOGLE DRIVE MEGOSZTOTT MEGHAJTÓRA
                # ---------------------------------------------
                folder_id = DRIVE_FOLDERS.get(company_name)
                if not folder_id:
                    for key, f_id in DRIVE_FOLDERS.items():
                        if key.lower() in company_name.lower() or company_name.lower() in key.lower():
                            folder_id = f_id
                            break

                if folder_id:
                    print(f"Feltöltés a Google Drive Megosztott Meghajtóra (Folder ID: {folder_id})...")
                    upload_to_drive(drive_service, destination, folder_id, filename)
                else:
                    print(f"FIGYELEM: Nincs Drive mappa azonosító ehhez a céghez: {company_name}")

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

        print("\n" + "=" * 60)
        print("MINDEN CÉG FELDOLGOZÁSA BEFEJEZŐDÖTT")
        print("=" * 60)

        if sys.stdin.isatty():
            input("\nENTER = böngésző bezárása...")

        browser.close()


if __name__ == "__main__":
    main()
