## What does this PR do?
<!-- 1-3 sentences. Link the task: "Closes #12" -->

## Owner / module
<!-- e.g. Yusuf / socketlink/server -->

## Checklist (author)
- [ ] I branched from the latest `main` and merged/rebased `main` again before opening this PR
- [ ] I only changed files in my own folder (or the owner of the other folder approved)
- [ ] I did NOT change constants.py / events.py / exceptions.py / protocol.py / transport.py (or Sude approved)
- [ ] `ruff check .` passes
- [ ] `python -m pytest` passes locally
- [ ] I added/updated tests for my change
- [ ] Names follow README section 8 (snake_case, English, type hints, docstrings)
- [ ] No `print()`, no hard-coded host/port/timeouts, no bare `except:`
- [ ] GUI code: widgets are only touched from the Tk main thread

## How to test it manually
<!-- e.g. python run_server.py, then two python run_client.py, send "hi" -->

## Screenshots (GUI changes)

## Reviewer
<!-- Your code pair from README section 9.2 -->
