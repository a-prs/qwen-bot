# Schedule Skill

Create, list, edit, and delete scheduled tasks.

## When to use

When the user asks to:
- Set a reminder
- Create a recurring task
- Send something at a specific time
- Check or manage their schedules

## How it works

Read and write `schedules.json` in the workspace root.
See QWEN.md for the full format specification.

## Examples

User: "Напомни завтра в 14:00 позвонить стоматологу"
→ Create entry with cron for tomorrow 14:00, once=true

User: "Каждое утро в 9 присылай новости по AI"
→ Create entry with cron "0 9 * * *"

User: "Покажи мои напоминания"
→ Read schedules.json, format as list

User: "Удали напоминание про стоматолога"
→ Remove matching entry from schedules.json
