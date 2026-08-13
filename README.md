# AI and Data Science in Python Course Library

This repository is the public, static edition of the Course Library Command Center. GitHub Pages serves the portal UI and its curated catalog; the course files remain in Google Drive.

- Deployed Pages URL: https://dhar174.github.io/AI-and-Data-Science-in-Python-class/
- Date-neutral class plan: https://dhar174.github.io/AI-and-Data-Science-in-Python-class/class-plan.html
- Student Day Guides: https://dhar174.github.io/AI-and-Data-Science-in-Python-class/student-guides.html
- Day 1 guide: https://dhar174.github.io/AI-and-Data-Science-in-Python-class/student-day-01.html
- Day 2 guide: https://dhar174.github.io/AI-and-Data-Science-in-Python-class/student-day-02.html
- Repository: https://github.com/dhar174/AI-and-Data-Science-in-Python-class
- Public catalog: `data/course-catalog.json`

The site is not considered deployed until the anonymous Drive audit, repository verification, GitHub Pages deployment, and production smoke test all pass.

## Public delivery model

- GitHub Pages hosts only HTML, CSS, JavaScript, and the public catalog.
- Google Drive hosts course documents and media.
- External course web apps continue to launch on their existing hosts.
- Embedded text excerpts are included for eligible text records.
- Binary files are previewed through their verified Google Drive pages; no course binary is copied into this repository.
- Viewing a public Drive item is anonymous. Google sign-in may still be required to save, copy, or edit it.

## Student class plan

`class-plan.html` is the date-neutral student guide to all 33 sessions. Its authoritative schedule and syllabus remain in the private Course Library's promoted `docs/three_module_curriculum_package`; the public repository contains only the generated student-safe page. The private renderer must produce byte-identical local and public copies, and the public verifier rejects source drift, malformed navigation, private paths, internal IDs, and embedded `file:` URLs.

## Student Day Guides

`student-guides.html` is the 33-day hub. `student-day-01.html` and `student-day-02.html` are detailed class-night guides; the remaining pages retain their generated public resource views. The shared `student-guides.css` and `student-guides.js` support every guide page. All Student Day Guide outputs are generated from validated private curriculum sources and must not be hand-edited in this checkout.

Run the private generator from the private Course Library Portal directory, targeting this public checkout:

```powershell
py -3 -B .\build_student_guides.py --output-dir "<public-checkout>"
py -3 -B .\build_student_guides.py --output-dir "<public-checkout>" --check
```

Only public-safe generated student-guide output crosses into this repository. Private source documents, local paths, internal IDs, and instructor-only material remain outside the public checkout.

## Manual regeneration and release

Run this workflow after the private source catalog changes:

1. Regenerate the public allowlisted catalog with `scripts/export_public_catalog.py`, always passing `--denylist data/public-denylist.json`.
2. Regenerate and check all Student Day Guide outputs with the private `build_student_guides.py` workflow above.
3. If the promoted private schedule or syllabus changed, regenerate both class-plan copies with the private `build_class_plan.py` and confirm they are byte-identical.
4. Run `scripts/verify_public_catalog.py` and `scripts/verify_public_site.py`.
5. Run the anonymous Drive-link audit in a fresh browser context with no Google cookies.
6. Stop before committing if any exported Drive URL requires access or has a reproducible link error. Treat HTTP 429 as a throttled audit: retry at a lower rate and record the affected scope; do not misclassify it as an access-permission failure.
7. Serve the repository from its parent folder and test it at `/AI-and-Data-Science-in-Python-class/` so asset paths match the GitHub project-site subpath.
8. Run `py -3 -B -m unittest discover -s tests -p "test_*.py"` and `node --check app.js`; `-B` prevents disposable bytecode caches from polluting the release diff.
9. Confirm the private source portal hashes are unchanged.
10. Commit on a feature branch, push only that branch, and open a pull request to `main`. Never push release changes directly to `main`.
11. Merge only after review and all release checks pass. GitHub Pages publishes from `main` and `/(root)` after the PR merge.
12. Wait for the Pages deployment for the merge commit, then verify the production URL, class-plan URL, Student Day Guides URLs, console, public catalog, representative Drive links, and external web apps.

Drive permissions are never changed by this repository workflow.

## Online-only denylist

To hide a record from the public site without changing the offline catalog:

1. Add its stable `id` to `data/public-denylist.json`.
2. Run `py -3 scripts/apply_public_denylist.py` from this checkout.
3. Run `py -3 scripts/verify_public_catalog.py --denylist data/public-denylist.json`.
4. Commit on a feature branch and deliver the change through a reviewed pull request; do not push directly to `main`.

The public-only command reads the existing public catalog and rewrites both
`data/course-catalog.json` and `data/catalog-data.js`. It never writes to the
offline course-library folder. Full source-based exports should also pass
`--denylist data/public-denylist.json` so hidden records do not return later.
