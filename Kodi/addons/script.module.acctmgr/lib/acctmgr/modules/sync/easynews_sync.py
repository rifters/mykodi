# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcgui
import xbmcvfs
import os

from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.db import chk_auth_db
from acctmgr.modules.db import easynews_db

# Variables
exists = xbmcvfs.exists

class Auth:
    def easynews_auth(self):

        # ========================= AM Lite Variables =========================
        acctmgr = xbmcaddon.Addon("script.module.acctmgr")
        your_username = acctmgr.getSetting("easynews.username")
        your_password = acctmgr.getSetting("easynews.password")
        master_user = your_username
        master_pass = your_password

        # ========================= Fen Light =========================
        try:
            if exists(var.chk_fenlt):
                if not exists(var.chkset_fenlt):
                    control.remake_fenlt_settings()
                    xbmc.sleep(500)
                    
                if exists(var.chkset_fenlt):
                    settings_db = var.fenlt_settings_db
                    chk_auth_user = chk_auth_db.chk_auth(settings_db, "easynews_user")
                    chk_auth_pass = chk_auth_db.chk_auth(settings_db, "easynews_password")
                    
                    if chk_auth_user != master_user or chk_auth_pass != master_pass:
                        easynews_db.auth(settings_db)
                        xbmc.sleep(300)
                        control.remake_fenlt_settings()
        except Exception as e:
            log_utils.error(f"Fen Light Easynews Failed: {e}")

        # ========================= Gears =========================
        try:
            if exists(var.chk_gears):
                if not exists(var.chkset_gears):
                    control.remake_gears_settings()
                    xbmc.sleep(500)
                    
                if exists(var.chkset_gears):
                    settings_db = var.gears_settings_db
                    chk_auth_user = chk_auth_db.chk_auth(settings_db, "easynews_user")
                    chk_auth_pass = chk_auth_db.chk_auth(settings_db, "easynews_password")
                    
                    if chk_auth_user != master_user or chk_auth_pass != master_pass:
                        easynews_db.auth(settings_db)
                        xbmc.sleep(300)
                        control.remake_gears_settings()
        except Exception as e:
            log_utils.error(f"Gears Easynews Failed: {e}")

        # ========================= Umbrella =========================
        try:
            if exists(var.chk_umb) and exists(var.chkset_umb):
                addon = xbmcaddon.Addon("plugin.video.umbrella")
                chk_auth_user = addon.getSetting("easynews.user")
                chk_auth_pass = addon.getSetting("easynews.password")
                if chk_auth_user != master_user or chk_auth_pass != master_pass:
                    for k, v in {
                        "easynews.user": your_username,
                        "easynews.password": your_password,
                        "easynews.enable": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Umbrella Easynews Failed: {e}")

        # ========================= Fen / POV =========================
        for addon_id, chk_addon, chk_settings, label, remake_settings in (
            #("plugin.video.fen", var.chk_fen, var.chkset_fen, "Fen", None),
            ("plugin.video.pov", var.chk_pov, var.chkset_pov, "POV", control.remake_pov_settings),
        ):
            try:
                if exists(chk_addon) and exists(chk_settings):
                    addon = xbmcaddon.Addon(addon_id)

                    chk_auth_user = addon.getSetting("easynews_user")
                    chk_auth_pass = addon.getSetting("easynews_password")

                    if chk_auth_user != master_user or chk_auth_pass != master_pass:
                        settings = {
                            "easynews_user":     your_username,
                            "easynews_password": your_password,
                            "provider.easynews": "true",
                        }

                        for k, v in settings.items():
                            addon.setSetting(k, v)

                        if remake_settings:
                            xbmc.sleep(200)
                            #remake_settings()

            except Exception as e:
                log_utils.error(f"{label} Easynews Failed: {e}")

        # ========================= Dradis / Genocide =========================
        addons = [
            ("Dradis",   "plugin.video.dradis",   var.chk_dradis,   var.chkset_dradis),
            ("Genocide", "plugin.video.genocide", var.chk_genocide, var.chkset_genocide),
        ]

        for name, plugin, chk_addon, chk_setting in addons:
            try:
                if exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth_user = addon.getSetting("easynews.username")
                    chk_auth_pass = addon.getSetting("easynews.password")
                    if chk_auth_user != master_user or chk_auth_pass != master_pass:
                        for k, v in {
                            "easynews_user": your_username,
                            "easynews_password": your_password,
                            "provider.easynews": "true",
                        }.items():
                            addon.setSetting(k, v)
            except Exception as e:
                log_utils.error(f"{name} Easynews Failed: {e}")
