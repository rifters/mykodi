import json
import os
import time
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

class RemindersManager:
    def __init__(self):
        if not xbmcvfs.exists(PROFILE_PATH):
            xbmcvfs.mkdirs(PROFILE_PATH)
        self.reminders_path = os.path.join(PROFILE_PATH, "reminders.json")
        if not xbmcvfs.exists(self.reminders_path):
            self.save_reminders([])
        self.reminders = self.load_reminders()

    def load_reminders(self):
        if not xbmcvfs.exists(self.reminders_path):
            return []
        with xbmcvfs.File(self.reminders_path, "r") as f:
            return json.loads(f.read())

    def save_reminders(self, reminders):
        dir_path = os.path.dirname(self.reminders_path)
        if not xbmcvfs.exists(dir_path):
            xbmcvfs.mkdirs(dir_path)
        with xbmcvfs.File(self.reminders_path, "w") as f:
            f.write(json.dumps(reminders, indent=2, ensure_ascii=False))

    def add_reminder(self, channel, program, start_time):
        reminders = self.load_reminders()
        reminders.append({
            "channel": channel,
            "program": program,
            "start_time": start_time
        })
        self.save_reminders(reminders)

    def remove_reminder(self, channel, program, start_time):
        reminders = self.load_reminders()
        reminders = [r for r in reminders if not (
            r["channel"] == channel and r["program"] == program and r["start_time"] == start_time
        )]
        self.save_reminders(reminders)

    def get_upcoming_reminders(self, within_seconds=300):
        now = int(time.time())
        reminders = self.load_reminders()
        return [r for r in reminders if 0 <= r["start_time"] - now <= within_seconds]

    def list_reminders(self):
        reminders = self.load_reminders()
        if not reminders:
            return "No reminders set."
        lines = []
        for r in reminders:
            t = time.strftime('%Y-%m-%d %H:%M', time.localtime(r["start_time"]))
            lines.append(f"{r['program']} on {r['channel']} at {t}")
        return "\n".join(lines)

    def clear_reminders(self):
        """Remove all reminders."""
        self.save_reminders([])

reminders_manager = RemindersManager()
add_reminder = reminders_manager.add_reminder
remove_reminder = reminders_manager.remove_reminder
get_upcoming_reminders = reminders_manager.get_upcoming_reminders
list_reminders = reminders_manager.list_reminders