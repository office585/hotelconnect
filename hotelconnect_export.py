import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://p.hotelconnect.hu/login"

EMAIL = os.environ.get("HOTELCONNECT_EMAIL", "buki.bertold@mavericklodges.com")
PASSWORD = os.environ.get("HOTELCONNECT_PASSWORD", "Lebonote10@@@@")

# Windows / Local Letöltések mappa
DOWNLOAD_DIR = Path.home() / "Downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Kért várakozások
WAIT_COMPANY = 3
WAIT_NAV = 2


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
        # LOGIN
        # =====================================================
        print("Login oldal megnyitása...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        page.locator('input[type="email"]').fill(EMAIL)
        page.locator('input[type="password"]').fill(PASSWORD)

        print("Bejelentkezés...")
        page.locator('button[type="submit"]').click()

        # Login oldal elhagyása (JS ellenőrzés SPA / pushState esetére)
        page.wait_for_function(
            "() => !window.location.href.includes('/login')",
            timeout=60000
        )

        print("Sikeres belépés.")
        print("Aktuális URL:", page.url)

        print(f"Várakozás login után: {WAIT_COMPANY} mp")
        time.sleep(WAIT_COMPANY)

        # =====================================================
        # CÉGEK KIOLVASÁSA
        # =====================================================

        # Csak az Egységek oldalsáv gombjai
        company_buttons = page.locator(
            'aside button[title*="NTAK jelentés"]'
        )

        company_count = company_buttons.count()

        print(f"\nTalált cégek száma: {company_count}")

        companies = []

        for i in range(company_count):
            button = company_buttons.nth(i)

            # A belső span tartalmazza a cég nevét
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

                company_button = page.locator(
                    'aside button'
                ).filter(
                    has=page.locator(
                        "span.truncate",
                        has_text=company_name
                    )
                )

                company_button.click()

                print(f"Várakozás cégváltás után: {WAIT_COMPANY} mp")
                time.sleep(WAIT_COMPANY)

                # ---------------------------------------------
                # XLSX LETÖLTÉSE - FŐ GOMB
                # ---------------------------------------------
                print("XLSX letöltése menü megnyitása...")

                # Az első látható XLSX letöltése gomb
                xlsx_buttons = page.get_by_role(
                    "button",
                    name="XLSX letöltése",
                    exact=True
                )

                # Ekkor még elvileg csak a főoldali gomb látható
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

                # A modal megnyitása után két "XLSX letöltése"
                # gomb is lehet a DOM-ban.
                # A látható, modális gombot választjuk.
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

                filename = (
                    f"{safe_filename(company_name)}"
                    f"_ez_az_ev{extension}"
                )

                destination = DOWNLOAD_DIR / filename

                download.save_as(str(destination))

                print("LETÖLTVE:")
                print(destination)

                # Következő művelet előtt kis várakozás
                time.sleep(WAIT_NAV)

            except Exception as e:
                print(f"HIBA ennél a cégnél: {company_name}")
                print(str(e))

                # Ha valamilyen modal nyitva maradt, megpróbáljuk bezárni
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

                # Nem állítjuk le az egész robotot, hanem megyünk a következő cégre
                continue

        # =====================================================
        # KÉSZ
        # =====================================================

        print("\n" + "=" * 60)
        print("MINDEN CÉG FELDOLGOZÁSA BEFEJEZŐDÖTT")
        print("=" * 60)

        print("Letöltési mappa:")
        print(DOWNLOAD_DIR)

        if sys.stdin.isatty():
            input("\nENTER = böngésző bezárása...")

        browser.close()


if __name__ == "__main__":
    main()
