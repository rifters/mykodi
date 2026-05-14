# -*- coding: utf-8 -*-
import xbmcgui
import json
import urllib.request
import urllib.error

from acctmgr.modules import control
from acctmgr.modules import log_utils

# ---------------------------------------------------------------------
# TorBox API
# ---------------------------------------------------------------------
API_BASE = "https://api.torbox.app"
USER_PATH = "/v1/api/user/me"

torbox_icon = control.joinPath(control.artPath(), "torbox.png")


class Torbox:
	def auth(self):
		api = xbmcgui.Dialog().input("Enter TorBox API Key:")
		if not api:
			control.notification(message="TorBox authorization cancelled!",icon=torbox_icon)
			return False

		api = api.strip().replace("\n", "").replace("\r", "")
		if not api:
			control.notification(message="TorBox authorization failed!",icon=torbox_icon)
			return False

		url = f"{API_BASE}{USER_PATH}"
		req = urllib.request.Request(url)

		# Bearer token auth (as per TorBox docs + POV)
		req.add_header("Authorization", f"Bearer {api}")
		req.add_header("User-Agent", "Kodi/21 acctmgr")
		req.add_header("Accept", "application/json")

		try:
			response = urllib.request.urlopen(req, timeout=10)
			payload = json.loads(response.read().decode("utf-8"))

			# Defensive parsing
			data = payload.get("data") or {}

			acct_id = data.get("id") or ""
			is_subscribed = data.get("is_subscribed")
			plan = data.get("plan")
			expires = data.get("premium_expires_at")

			# Determine account status
			if is_subscribed is True or expires:
				auth_status = "Premium"
			elif plan == 1:
				auth_status = "Basic"
			else:
				auth_status = "Authorized"

			# Persist settings
			control.setSetting("torbox.token", api)
			control.setSetting("torbox.acct_id", str(acct_id))
			control.setSetting("torbox.auth_status", auth_status)

			control.notification(title="AM Lite",message="Successfully Authorized!",icon=torbox_icon)

			return True

		except urllib.error.HTTPError as e:
			if e.code == 401:
				control.notification(message="TorBox Authorization Failed (Invalid API Key)",icon=torbox_icon)
			elif e.code == 403:
				control.notification(message="TorBox Authorization Failed (Forbidden)",icon=torbox_icon)
			else:
				control.notification(message=f"TorBox Authorization Failed (HTTP {e.code})",icon=torbox_icon)

			try:
				body = e.read().decode("utf-8", errors="ignore")
				log_utils.error(f"TorBox auth HTTP {e.code}: {body}")
			except Exception:
				log_utils.error(f"TorBox auth HTTP {e.code}")

			return False

		except Exception as e:
			log_utils.error(f"TorBox authorization failed: {e}")
			control.notification(message="TorBox Authorization Failed",icon=torbox_icon)
			return False

	def revoke(self):
		if not control.okDialog("TorBox", "Revoke TorBox Authorization?"):
			return

		control.setSetting("torbox.token", "")
		control.setSetting("torbox.acct_id", "")
		control.setSetting("torbox.auth_status", "")

		control.notification("TorBox Authorization Revoked",icon=torbox_icon)
