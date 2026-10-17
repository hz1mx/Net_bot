# Net Academy bot

Telegram bot that watches https://netacademy.sa/book?activity=tennis&type=trainer for free sessions with
coach Aldaaj (محمد الداعج), alerts the owner in Telegram, and books a session as a guest when the owner
presses its button. Everything is in `bot.py`; `README.md` (Arabic) is the user guide.

The owner writes in Saudi Arabic and is not a programmer: answer in Saudi Arabic, keep it short and
plain, and give exact steps when they have to do something on the PC.

## How it runs on this PC

- Windows, Python 3.13 (`py -3.13`). The bot runs hidden as the scheduled task `NetAcademyBot`
  (SYSTEM account) through `run_bot.bat`, started at boot by `install_boot_task.bat`.
- Its log is `bot.log` in this folder; read it first when something seems wrong.
- Only one copy can run (it holds a lock on 127.0.0.1:47653); a second one exits with code 3.
- Remote Control (`start_remote.bat`) is how the owner reaches this folder from their phone.

## Changing the bot

1. Edit `bot.py`, then check it: `py -3.13 -m py_compile bot.py`.
2. The running bot notices that `bot.py` changed within about 30 seconds and restarts itself into the
   new version (exit code 4), then sends "♻️ تحدّث البوت" in Telegram. No restart step is needed.
   If the new version crashes, `run_bot.bat` restores `bot.py.good` (the last version that started)
   and the bot reports it in Telegram; the cause is in `bot.log`.
3. Commit and push every change to GitHub right away (the owner wants changes uploaded
   automatically): `git add -A && git commit -m "..." && git push`. Pull first with `git pull` if the
   push is rejected; changes may also come from cloud sessions.

Editing a `.bat` file while the bot runs can break the running copy, because cmd reads batch files as
it goes. After changing `run_bot.bat`, ask the owner to run `restart_bot.bat` as administrator.

## Never

- Never commit the owner's private files: `.env` (bot token, name, phone, email), `state.json`,
  `action.json`, `booking_template.json`, `service_paths.bat`, `bot.log*`, `debug/`. They are in
  `.gitignore`; keep them there. The repository is public.
- Never print or paste the bot token or the owner's phone/email into chat, commits or logs.
- Never run `py -3.13 bot.py --test-book` or press booking buttons without the owner asking in that
  moment: it creates a real booking in their name.
- Do not run the long-running bot (`py -3.13 bot.py`) yourself; the background task already runs it.

## Useful checks (safe while the bot runs)

- `py -3.13 bot.py --probe`: replays the site's booking request for the coming days and lists the
  coaches per day. Use it when `/all` in Telegram warns that the site's data format changed.
- `py -3.13 bot.py --dump`: one check for the watched coach, raw data saved to `debug/`.
- `py -3.13 bot.py --find-api`: lists the site's data requests (needs Playwright's Chromium).
- If the booking button reports that the site's booking steps changed, the owner must record a new
  booking: `py -3.13 bot.py --record` opens a browser where they book as a guest up to the payment
  page without paying.

The site sits behind Vercel's bot protection: it blocks datacenter IPs, so it only works from this PC's
home connection, and it may rate-limit (HTTP 429) if checked too often.
