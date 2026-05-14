import xbmc
import xbmcgui
import time
import os
from reminders import get_upcoming_reminders, remove_reminder

CHECK_INTERVAL = 30  # seconds

def main():
    xbmc.log("Reminder service started", level=xbmc.LOGINFO)
    while not xbmc.Monitor().abortRequested():
        try:
            reminders = get_upcoming_reminders(within_seconds=300)
            for r in reminders:
                # Show notification and remove reminder so it's not repeated
                xbmcgui.Dialog().notification(
                    'Program Reminder',
                    f"{r['program']} on {r['channel']} is starting soon!",
                    xbmcgui.NOTIFICATION_INFO,
                    5000
                )
                remove_reminder(r['channel'], r['program'], r['start_time'])
        except Exception as e:
            xbmc.log(f"Reminder service error: {str(e)}", level=xbmc.LOGERROR)
        xbmc.sleep(CHECK_INTERVAL * 1000)

if __name__ == "__main__":
    main()