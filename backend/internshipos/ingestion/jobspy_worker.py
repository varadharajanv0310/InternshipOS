"""Optional JobSpy subprocess, isolated from the API's logging and timeout."""
import contextlib
import io
import json
import sys


def main():
    request = json.load(sys.stdin)
    log = io.StringIO()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            from jobspy import scrape_jobs
        except ImportError:
            raise SystemExit("Optional dependency missing: install python-jobspy==1.1.82")
        frame = scrape_jobs(site_name=[request["site"]], search_term=request["search_term"],
            location=request["location"], country_indeed="India", results_wanted=request["results_wanted"],
            linkedin_fetch_description=True, description_format="html", verbose=1)
        records = json.loads(frame.to_json(orient="records", date_format="iso"))
    # Remove recruiter email columns: acquisition does not need personal contacts.
    for row in records:
        row.pop("emails", None)
    print(json.dumps({"records": records, "log": log.getvalue()[-3000:]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
