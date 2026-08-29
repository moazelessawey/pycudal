# Contributing

Thanks for considering a contribution!

## Setup
pip install -e .[all,dev]
pre-commit install

## Checks before opening a PR
pre-commit run --all-files     # ruff lint+format, hygiene hooks
pytest -q                      # validation/smoke tests
python cudal_gui.py --selftest

## PR checklist
- [ ] Tests pass and new behaviour is covered.
- [ ] `ruff check` and `ruff format --check` are clean.
- [ ] CHANGELOG.md updated under [Unreleased].
- [ ] Docs (README / USER_MANUAL) updated if UI or behaviour changed.
- [ ] Commits follow conventional style (feat:/fix:/docs:/chore:).

Report bugs via the issue template; for security issues see SECURITY.md.
