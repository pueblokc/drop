# Using Drop with an AI assistant

Drop started as the answer to one question: *my AI assistant just made a chart, a video or a
report. How do I see it on my phone?* Pasting a file path into chat doesn't help when you're on
the couch. With Drop, the assistant runs one command and you get a link.

## 1. Install the client where the assistant runs

```bash
pip install "git+https://github.com/pueblokc/drop"
drop --init          # then edit the config it prints
drop --dry-run some-file.png
```

## 2. Tell the assistant about it

Add a short block to the assistant's standing instructions: `CLAUDE.md` for Claude Code,
`AGENTS.md` for Codex and other agents, or your tool's equivalent.

```markdown
## Showing me things
When you make something I'd want to look at (image, video, report page, PDF, export),
send it to my Drop gallery and give me the link:

    drop <file-or-folder> --title "<short title>" --tag <topic> --project "<project>" --json

Use the `link` field from the JSON output in your reply. Don't paste local paths alone.
Never drop secrets, credentials or other people's private data.
```

`--json` returns one object per file:

```json
{"results": [{"file": "out/chart.png", "title": "Disk usage", "id": "3f89eea84c",
  "link": "https://drop.example.com/#3f89eea84c", "mirror": null, "error": null}],
 "notified": ["telegram"]}
```

The exit code is `0` only when every file made it, so an agent can tell success from failure
without parsing text.

## 3. Optional: get pinged

Set one of the `[notify]` options and you get a message with the links each time something
lands: Telegram, [ntfy](https://ntfy.sh) or any webhook. Set `sender` to your assistant's name
and the message reads "Leo dropped 2 files".

## Tips

- **Tags and projects** turn the gallery into a searchable history of everything the assistant
  ever showed you. Pick a few tags and stick to them (`report`, `diagram`, `video`, `export`).
- **HTML reports** open inline, in a sandbox: their scripts run, but they can't touch the gallery.
- **Same file twice** is stored once. The id is a hash of the content.
- **Folders** work: `drop ./renders/` sends every file in it, skipping dotfiles.
