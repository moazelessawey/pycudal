# Making PyCuDAL Citable — Zenodo DOI Setup

This is the one part of "citability" that has to be done by you, once,
through your own login — Zenodo authenticates via your GitHub account, so
it can't be set up by anyone else on your behalf. Everything else (the
`CITATION.cff` file, the citation text below) is already prepared.

Once done, this gets you:
- A permanent DOI (e.g. `10.5281/zenodo.1234567`) that never changes, even
  across future versions
- A separate, version-specific DOI for every future release
- A "Cite this repository" button on GitHub (works immediately once
  `CITATION.cff` is committed, even before you do any of the Zenodo steps)
- A citation people can put in a reference list, an internal validation
  package, or a paper — instead of just a bare GitHub link

## Steps

1. **Commit `CITATION.cff`** to the root of the `pycudal` repository (same
   level as `README.md`). This alone activates GitHub's built-in "Cite this
   repository" button — no Zenodo account needed for this part.

2. **Log into [zenodo.org](https://zenodo.org)** using "Log in with GitHub"
   (top right). This links your GitHub account to Zenodo — no separate
   password to manage.

3. Go to **zenodo.org/account/settings/github/** (or Settings → GitHub from
   the menu). You'll see a list of your repositories with toggle switches.

4. **Toggle `pycudal` ON.** This tells Zenodo to watch that repository for
   new releases. Nothing is archived yet — this just arms it.

5. **Cut a new GitHub release** (or re-publish the current one as a new
   tag, e.g. `v1.0.9`) the normal way, via GitHub's Releases page. The
   moment you publish it, Zenodo automatically downloads a snapshot of the
   repo at that tag and archives it permanently.

6. Within a few minutes, go back to Zenodo → Upload → your repo will show
   up with a **DOI already assigned**. Click through to the record page to
   get the exact DOI (looks like `10.5281/zenodo.1234567`).

7. **Update `CITATION.cff`**: uncomment the `doi:` line and fill in the DOI
   you just got. Commit that change.

8. **Add a DOI badge to `README.md`** (Zenodo's record page gives you the
   exact Markdown snippet to copy — it looks like this):

   ```markdown
   [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.1234567.svg)](https://doi.org/10.5281/zenodo.1234567)
   ```

That's it — every release from here on gets its own DOI automatically, and
the top-level "concept DOI" (the one you commit to `CITATION.cff`) always
resolves to the latest version.

---

## Citation text (ready to use once the DOI exists)

Replace `10.5281/zenodo.XXXXXXX` below with your actual DOI from step 6,
and the version/date with whatever release you're citing.

### Plain text

> Elessawey, M. (2026). *PyCuDAL: A Python Implementation of Parametric
> Acceptance Limits for USP <905> Content Uniformity and USP <711>
> Dissolution* (Version 1.0.8) [Computer software].
> https://doi.org/10.5281/zenodo.XXXXXXX

### BibTeX

```bibtex
@software{elessawey_pycudal,
  author    = {Elessawey, Moaz},
  title     = {{PyCuDAL: A Python Implementation of Parametric Acceptance
               Limits for USP <905> Content Uniformity and USP <711>
               Dissolution}},
  year      = {2026},
  version   = {1.0.8},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.XXXXXXX},
  url       = {https://doi.org/10.5281/zenodo.XXXXXXX}
}
```

### Where to put this

- A `CITATION.cff` in the repo root (already prepared) covers GitHub's
  native "Cite this repository" button automatically.
- Consider also adding a short **"How to cite"** section near the bottom
  of `README.md` with the plain-text form above, since not everyone
  notices the GitHub sidebar button.
- This is also the reference to use in Appendix F (Program Description) or
  the References section of the Validation Protocol once a DOI exists —
  "GitHub repository" can be replaced with a permanent, versioned citation.
