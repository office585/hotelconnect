            print("Figyelem: a korábbi kód szerint csak az aktív munkalapot exportáljuk.", flush=True)
        with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            for row in worksheet.iter_rows(values_only=True):
                # A teljesen ures, akar csak formazott sorok nem foglalnak helyet.
                if not any(value is not None and value != "" for value in row):
                    continue
                writer.writerow(["" if value is None else value for value in row])
                rows_written += 1
    finally:
        workbook.close()
    if not rows_written:
        raise RuntimeError("Üres export: nem írom felül a korábbi Drive-fájlt.")
    return rows_written


def close_export_dialog(page: Page) -> None:
    cancel = page.get_by_role("button", name="Mégse", exact=True)
    if cancel.count() == 1 and cancel.is_visible():
        cancel.click()
        pause(page, WAIT_NAV)


def run() -> None:
    email = secret("HOTELCONNECT_EMAIL")
    password = secret("HOTELCONNECT_PASSWORD")
    secret("GDRIVE_SERVICE_ACCOUNT_JSON")
    year = datetime.now(ZoneInfo("Europe/Budapest")).year
    successful = []
    failed = []

    with tempfile.TemporaryDirectory(prefix="hotelconnect-") as temporary:
        directory = Path(temporary)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    accept_downloads=True,
                    locale="hu-HU",
                    timezone_id="Europe/Budapest",
                )
                page = context.new_page()
                page.set_default_timeout(60000)
                login(page, email, password)

                # A Drive kapcsolat csak a sikeres login utan kovetkezik.
                drive_service = get_drive_service()
                try:
                    for index, (company_name, config) in enumerate(COMPANIES.items(), 1):
                        stage = "Cég kiválasztása"
                        print(f"\n[{index}/{len(COMPANIES)}] {company_name}", flush=True)
                        try:
                            company = unit_buttons(page).filter(
                                has=page.locator(
                                    "span.truncate",
                                    has_text=re.compile(r"^" + re.escape(company_name) + r"$"),
                                )
                            )
                            company.click()
                            pause(page, WAIT_COMPANY)

                            stage = "XLSX menü megnyitása"
                            page.get_by_role("button", name="XLSX letöltése", exact=True).first.click()
                            pause(page, WAIT_NAV)

                            stage = "Ez az év kiválasztása"
                            page.get_by_role("button", name="Ez az év", exact=True).click()
                            pause(page, WAIT_NAV)

                            stage = "XLSX letöltése"
                            with page.expect_download(timeout=180000) as download_info:
                                page.get_by_role("button", name="XLSX letöltése", exact=True).last.click()
                            download = download_info.value
                            xlsx_path = directory / f"{config['code']}_{year}.xlsx"
                            download.save_as(str(xlsx_path))
                            print(f"XLSX: {xlsx_path.stat().st_size / 1048576:.2f} MB", flush=True)
                            pause(page, WAIT_NAV)
                            close_export_dialog(page)

                            stage = "CSV készítése"
                            csv_path = directory / f"hotelconnect_{config['code']}_{year}.csv"
                            count = xlsx_to_csv(xlsx_path, csv_path)
                            print(f"CSV: {csv_path.stat().st_size / 1048576:.2f} MB, {count} sor", flush=True)

                            stage = "Google Drive feltöltés"
                            upload_or_replace_file(drive_service, csv_path, config["folder_id"])
                            successful.append(company_name)
                            print(f"KÉSZ: {company_name}", flush=True)
                            xlsx_path.unlink(missing_ok=True)
                            csv_path.unlink(missing_ok=True)
                            pause(page, WAIT_NAV)
                        except Exception as error:
                            failed.append(company_name)
                            print(f"HIBA [{stage}] {company_name}: {redact(error)}", flush=True)
                            with suppress(Exception):
                                close_export_dialog(page)
                finally:
                    drive_service.close()
                context.close()
            finally:
                browser.close()

    print(f"\nSikeres: {len(successful)}/7. Hibás: {len(failed)}.", flush=True)
    if failed:
        raise RuntimeError("Sikertelen egységek: " + ", ".join(failed))


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        # Nincs titkokat is tartalmazhato, szuretlen traceback.
        print(f"\nHIBA: {redact(error)}", file=sys.stderr, flush=True)
        sys.exit(1)
