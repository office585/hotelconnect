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

# A Google Drive-on létrehozott főmappa neve
PARENT_FOLDER_NAME = "HotelConnect"

# Temp letöltési mappa
DOWNLOAD_DIR = Path.home() / "Downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Szigorú várakozási idők
LOGIN_TIMEOUT_MS = 15000
WAIT_COMPANY = 3
WAIT_NAV = 2


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


def get_parent_folder_id(drive_service, parent_name=PARENT_FOLDER_NAME):
    """Megkeresi a 'HotelConnect' nevű főmappát a Google Drive-on."""
    if not drive_service:
        return None
    try:
        query = (
            f"name = '{parent_name}' and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        )
        results = drive_service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
            print(f"  -> Főmappa megtalálva: '{parent_name}' (ID: {folder_id})")
            return folder_id
        else:
            print(f"  -> HIBA: Nem található '{parent_name}' nevű mappa a Google Drive-on!")
            return None
    except Exception as e:
        print(f"  -> HIBA a(z) '{parent_name}' főmappa keresésekor: {e}")
        return None


def get_or_create_company_folder(drive_service, parent_id, company_name):
    """Megkeresi vagy létrehozza a cég almappáját a HotelConnect főmappában."""
    if not drive_service or not parent_id:
        return None
    try:
        query = (
            f"'{parent_id}' in parents and "
            f"name = '{company_name}' and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        )
        results = drive_service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = results.get("files", [])

        if files:
            return files[0]["id"]

        # Ha nem létezik az almappa, létrehozzuk a HotelConnect mappán belül
        folder_metadata = {
            "name": company_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        }
        folder = drive_service.files().create(
            body=folder_metadata,
            fields="id",
            supportsAllDrives=True
        ).execute()
        print(f"  -> Új almappa létrehozva: '{company_name}' (ID: {folder.get('id')})")
        return folder.get("id")
    except Exception as e:
        print(f"  -> HIBA a(z) '{company_name}' almappa kezelésekor: {e}")
        return None


def upload_and_cleanup(drive_service, file_path, folder_id, file_name):
    """Feltölti a fájlt, felülírja a régit (ha van), és törli a helyi temp fájlt."""
    if not drive_service or not folder_id:
        return

    try:
        # Keresés meglévő fájlra
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
            # Meglévő fájl frissítése (régi felülírása)
            file_id = files[0]["id"]
            drive_service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True
            ).execute()
            print(f"  -> Google Drive: Régi fájl felülírva és frissítve: {file_name}")

            # Ha esetleg korábbról több duplikátum maradt volna fent, a többit töröljük
            for extra_file in files[1:]:
                drive_service.files().delete(
                    fileId=extra_file["id"],
                    supportsAllDrives=True
                ).execute()
        else:
            # Új fájl létrehozása
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
            print(f"  -> Google Drive: Új fájl sikeresen feltöltve: {file_name}")

        # Helyi ideiglenes fájl törlése a sikeres feltöltés után
        if file_path.exists():
            file_path.unlink()
            print("  -> Helyi ideiglenes fájl törölve.")

    except Exception as e:
        print(f"  -> HIBA a Drive feltöltés/frissítés során ({file_name}): {e}")


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
    parent_folder_id = None

    if drive_service:
        parent_folder_id = get_parent_folder_id(drive_service, PARENT_FOLDER_NAME)

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
                # DRIVE ALMAPPA KERESÉSE / LÉTREHOZÁSA ÉS FELTÖLTÉS
                # ---------------------------------------------
                if parent_folder_id and drive_service:
                    company_folder_id = get_or_create_company_folder(
                        drive_service, parent_folder_id, company_name
                    )

                    if company_folder_id:
                        print(f"Feltöltés a Google Drive-ra ('{company_name}' almappába)...")
                        upload_and_cleanup(
                            drive_service, destination, company_folder_id, filename
                        )
                    else:
                        print(f"FIGYELEM: Nem sikerült felkészíteni a cég almappáját: {company_name}")
                else:
                    print("FIGYELEM: A fő 'HotelConnect' mappa nem található, feltöltés kihagyva.")

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
