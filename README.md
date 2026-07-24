# AI and Data Science in Python Course Library

This repository is the public, static edition of the Course Library Command Center. GitHub Pages serves the portal UI and its curated catalog; the course files remain in Google Drive.

- Planned Pages URL: https://dhar174.github.io/AI-and-Data-Science-in-Python-class/
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

## Manual regeneration and release

Run this workflow after the private source catalog changes:

1. Regenerate the public allowlisted catalog with `scripts/export_public_catalog.py`.
2. Run `scripts/verify_public_catalog.py` and `scripts/verify_public_site.py`.
3. Run the anonymous Drive-link audit in a fresh browser context with no Google cookies.
4. Stop before committing or pushing if any exported Drive URL requires access or errors.
5. Serve the repository from its parent folder and test it at `/AI-and-Data-Science-in-Python-class/` so asset paths match the GitHub project-site subpath.
6. Run the Python test suite and `node --check app.js`.
7. Confirm the private source portal hashes are unchanged.
8. Commit and push `main`, then publish GitHub Pages from `main` and `/(root)`.
9. Verify the production URL, console, public catalog, representative Drive links, and external web apps.

Drive permissions are never changed by this repository workflow.
