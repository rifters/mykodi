# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file log_utils.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''


import os
import tempfile

from datetime import datetime
import xbmc
import traceback

from io import open

from resources.lib.modules import control
from resources.lib.modules.crewruntime import c

LOGDEBUG = xbmc.LOGDEBUG

name = c.name
pluginversion = c.pluginversion
moduleversion = c.moduleversion
kodiversion = c.kodiversion
sys_platform = c.platform

begincolor = begininfocolor = endcolor = ''

if control.setting('debug_in_color') == 'true':
    begincolor = '[COLOR red]'
    begininfocolor = '[COLOR lightblue]'
    endcolor = '[/color]'
DEBUGPREFIX = f'{begincolor}[ {name} {pluginversion} | {moduleversion} | {kodiversion} | {sys_platform} | DEBUG | old ]{endcolor}'
INFOPREFIX = f'{begininfocolor}[ {name} {pluginversion}/{moduleversion} | INFO ]{endcolor}'
LOGPATH = control.transPath('special://logpath/')
FILENAME = 'the_crew.log'
LOG_FILE = os.path.join(LOGPATH, FILENAME)
debug_enabled = control.setting('addon_debug')
debug_log = control.setting('debug.location')


def log(msg, trace=0):

    if not debug_enabled:
        return

    try:
        if isinstance(msg, str):
            if trace == 1:
                head = DEBUGPREFIX
                failure = str(traceback.format_exc())
                _msg = f'{msg}:\n    {failure}'
            else:
                head = INFOPREFIX
                _msg = f'\n    {msg}'

        else:
            raise TypeError('Logutils.log() msg not of type str!')

        if not debug_log == '0':
            if not os.path.exists(LOG_FILE):
                f = open(LOG_FILE, 'w', encoding='utf-8')
                f.write('\n\n\n\nstart\n')
                f.close()
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                line = ('[{} {}] {}: {}').format(datetime.now().date(), str(datetime.now().time())[:8], head, _msg)
                f.write(line.rstrip('\r\n') + '\n\n')
    except (TypeError, Exception) as e:
        try:
            xbmc.log(f'[ {name} ] Logging Failure: {e}', LOGDEBUG)
        except:
            pass


def error(msg=None, trace=True):
    """
    Log an error message with traceback.
    Compatible with log_utils.error() calls from CocoScrapers.
    """
    if not debug_enabled:
        return

    try:
        if msg is None:
            msg = 'Error occurred'

        failure = str(traceback.format_exc())
        _msg = f'{msg}:\n    {failure}' if msg else failure

        head = DEBUGPREFIX

        if not debug_log == '0':
            if not os.path.exists(LOG_FILE):
                f = open(LOG_FILE, 'w', encoding='utf-8')
                f.write('\n\n\n\nstart\n')
                f.close()
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                line = ('[{} {}] {}: {}').format(datetime.now().date(), str(datetime.now().time())[:8], head, _msg)
                f.write(line.rstrip('\r\n') + '\n\n')
    except (TypeError, Exception) as e:
        try:
            xbmc.log(f'[ {name} ] Error Logging Failure: {e}', LOGDEBUG)
        except:
            pass


def _sanitize_log(text):
    """
    Anonymize log content by removing/replacing sensitive information.
    Returns sanitized text safe for public sharing.
    """
    import re
    import platform

    # Get actual username to replace
    try:
        import getpass
        actual_username = getpass.getuser()
    except:
        actual_username = None

    # Get system username from platform-specific paths
    try:
        system_username = os.path.expanduser('~').split(os.sep)[-1]
    except:
        system_username = None

    sanitized = text

    # Replace Windows paths: C:\Users\username -> C:\Users\[USER]
    sanitized = re.sub(r'C:\\Users\\[^\\]+', r'C:\\Users\\[USER]', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'C:/Users/[^/]+', r'C:/Users/[USER]', sanitized, flags=re.IGNORECASE)

    # Replace Linux/Mac paths: /home/username-> /home/[USER]
    sanitized = re.sub(r'/home/[^/]+', r'/home/[USER]', sanitized)
    sanitized = re.sub(r'/Users/[^/]+', r'/Users/[USER]', sanitized)

    # Replace actual usernames if detected
    if actual_username:
        sanitized = sanitized.replace(actual_username, '[USER]')
    if system_username and system_username !=actual_username:
        sanitized = sanitized.replace(system_username, '[USER]')

    # Replace IP addresses (local and public)
    # IPv4 private ranges
    sanitized = re.sub(r'\b192\.168\.\d{1,3}\.\d{1,3}\b', '[IP-LOCAL]', sanitized)
    sanitized = re.sub(r'\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP-LOCAL]', sanitized)
    sanitized = re.sub(r'\b172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}\b', '[IP-LOCAL]', sanitized)
    # Generic IPv4 (potential public IPs)
    sanitized = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]', sanitized)

    # Replace MAC addresses
    sanitized = re.sub(r'\b[0-9A-Fa-f]{2}([-:])[0-9A-Fa-f]{2}(\1[0-9A-Fa-f]{2}){4}\b', '[MAC]', sanitized)

    # Replace auth tokens (40-64 character hex strings, common in APIs)
    sanitized = re.sub(r'\b[0-9a-f]{40,64}\b', '[TOKEN]', sanitized, flags=re.IGNORECASE)

    # Replace Bearer tokens
    sanitized = re.sub(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', 'Bearer [TOKEN]', sanitized, flags=re.IGNORECASE)

    # Replace authorization headers
    sanitized = re.sub(r'Authorization:\s*[^\r\n]+', 'Authorization: [REDACTED]', sanitized, flags=re.IGNORECASE)

    # Replace API keys in URLs
    sanitized = re.sub(r'[?&](api_key|apikey|key|token)=[^&\s]+', r'\1=[KEY]', sanitized, flags=re.IGNORECASE)

    # Replace device/computer names (if present in logs)
    try:
        hostname = platform.node()
        if hostname:
            sanitized = sanitized.replace(hostname, '[DEVICE]')
    except:
        pass

    return sanitized


def upload_log(log_type='kodi'):
    """
    Upload anonymized log file to paste.kodi.tv

    Args:
        log_type: 'kodi' for kodi.log or 'crew' for the_crew.log

    Returns:
        URL string if successful, None if failed
    """
    import xbmcgui

    try:
        if log_type == 'kodi':
            log_file = control.transPath('special://logpath/kodi.log')
            log_name = 'Kodi Log'
        else:  # crew
            log_file = LOG_FILE
            log_name = 'The Crew Log'

        # Check if log exists
        if not os.path.exists(log_file):
            control.okDialog(f'{log_name} not found', heading='Upload Failed')
            return None

        # Confirm upload
        if not control.yesnoDialog(f'Upload {log_name} to paste.kodi.tv?', '', 'Log will be anonymized before upload', 'URL expires in 1 month'):
            return None

        # Show progress
        progress = control.progressDialog
        progress.create('The Crew Log Upload', f'Reading {log_name}...')

        # Read log file
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read()
        except Exception as e:
            control.okDialog(f'Error reading log: {str(e)}', heading='Upload Failed')
            progress.close()
            return None

        # Check size and truncate if necessary (paste.kodi.tv has size limits)
        MAX_CHARS = 500000  # ~500KB limit to be safe
        truncated = False
        if len(log_content) > MAX_CHARS:
            c.log(f'[Log Upload] Log too large ({len(log_content)} chars), truncating to last 2500 lines', 1)
            lines = log_content.splitlines()
            log_content = '\n'.join(lines[-2500:])  # Last 2500 lines only
            truncated = True

        progress.update(25, f'Anonymizing {log_name}...')

        # Sanitize log content
        sanitized_content = _sanitize_log(log_content)

        # Add header with timestamp and version info
        truncate_note = '\n# TRUNCATED: Only last 2500 lines included (original log too large)' if truncated else ''
        header = f'''# The Crew Log Upload
# Upload Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Plugin Version: {pluginversion}
# Module Version: {moduleversion}
# Kodi Version: {kodiversion}
# Platform: {sys_platform}
# Log Type: {log_name}
# NOTE: This log has been anonymized - usernames, IPs, and tokens replaced{truncate_note}
#
================================================================================

'''
        sanitized_content = header + sanitized_content

        progress.update(50, 'Uploading to paste.kodi.tv...')

        # Upload to paste.kodi.tv
        try:
            c.log(f'[Log Upload] Attempting upload, content size: {len(sanitized_content)} chars', 1)

            # Try using requests library first (like gears addon does)
            try:
                import requests
                url = 'https://paste.kodi.tv/'
                user_agent = f'The Crew Log Uploader {pluginversion}'

                c.log(f'[Log Upload] Using requests library to POST to {url}documents', 1)
                c.log(f'[Log Upload] Content size: {len(sanitized_content)} chars', 1)

                response = requests.post(
                    url + 'documents',
                    data=sanitized_content.encode('utf-8', errors='ignore'),
                    headers={'User-Agent': user_agent},
                    timeout=30
                )

                c.log(f'[Log Upload] Response status: {response.status_code}', 1)

                # Check for HTTP errors
                if response.status_code == 413:
                    c.log('[Log Upload] Error 413: Log still too large even after truncation', 1)
                    progress.close()
                    control.okDialog('Log file too large for paste.kodi.tv.\nPlease use "Clear Log" in Tools and try again.', heading='Upload Failed')
                    return None
                elif response.status_code != 200:
                    c.log(f'[Log Upload] HTTP error {response.status_code}: {response.text[:500]}', 1)
                    progress.close()
                    control.okDialog(f'Upload failed: HTTP {response.status_code}', heading='Upload Failed')
                    return None

                # Try to parse JSON response
                c.log(f'[Log Upload] Response text (first 500): {response.text[:500]}', 1)

                try:
                    json_data = response.json()
                except:
                    c.log(f'[Log Upload] Failed to parse JSON, full response: {response.text}', 1)
                    progress.close()
                    control.okDialog('Invalid response from paste.kodi.tv', heading='Upload Failed')
                    return None

                if 'key' in json_data:
                    paste_url = url + json_data['key']
                    c.log(f'[Log Upload] Upload successful: {paste_url}', 1)

                    progress.update(100, 'Upload successful!')
                    control.sleep(500)
                    progress.close()

                    # Copy to clipboard
                    try:
                        import subprocess
                        if sys_platform == 'windows':
                            subprocess.run(['clip'], input=paste_url.encode('utf-16'), check=True)
                        elif sys_platform == 'linux':
                            subprocess.run(['xclip', '-selection', 'clipboard'], input=paste_url.encode(), check=True)
                        elif sys_platform in ['osx', 'darwin']:
                            subprocess.run(['pbcopy'], input=paste_url.encode(), check=True)
                        c.log(f'[Log Upload] URL copied to clipboard', 1)
                    except Exception as e:
                        c.log(f'[Log Upload] Clipboard copy failed: {e}', 1)
                        pass  # Clipboard copy is optional

                    # Generate and show QR code for easy mobile access
                    try:
                        from .segno import make as make_qr
                        import xbmc

                        # Create temp directory if it doesn't exist
                        temp_dir = os.path.join(tempfile.gettempdir(), 'thecrew_qr')
                        os.makedirs(temp_dir, exist_ok=True)

                        # Create QR code
                        c.log(f'[Log Upload] Generating QR code for: {paste_url}', 1)
                        qr = make_qr(paste_url, error='H')  # High error correction

                        # Save to temp file
                        qr_path = os.path.join(temp_dir, 'log_upload_qr.png')
                        qr.save(qr_path, scale=10, border=2, dark='#000000', light='#FFFFFF')

                        c.log(f'[Log Upload] QR code saved to {qr_path}', 1)

                        # Ask if user wants to see QR code
                        qr_message = f'Log uploaded successfully!\n\n{paste_url}\n\n(URL copied to clipboard)\n\nShow QR code to scan with phone?'
                        if control.yesnoDialog(qr_message, heading='Upload Successful', yeslabel='Show QR', nolabel='Close'):
                            # Display QR code
                            c.log(f'[Log Upload] Displaying QR code', 1)
                            xbmc.executebuiltin(f'ShowPicture({qr_path})')
                    except Exception as e:
                        c.log(f'[Log Upload] QR code generation failed: {e}', 1)
                        import traceback
                        c.log(f'[Log Upload] QR Traceback: {traceback.format_exc()}', 1)
                        # Show simple success dialog as fallback
                        msg = f'Log uploaded successfully!\n\nURL (copied to clipboard):\n{paste_url}\n\nExpires: 1 month'
                        control.okDialog(msg, heading='Upload Successful')

                    return paste_url
                elif 'message' in json_data:
                    error_msg = json_data['message']
                    c.log(f'[Log Upload] paste.kodi.tv returned error: {error_msg}', 1)
                    progress.close()
                    control.okDialog(f'Upload failed: {error_msg}', heading='Upload Failed')
                    return None
                else:
                    c.log(f'[Log Upload] Unexpected response: {response.text}', 1)
                    progress.close()
                    control.okDialog('paste.kodi.tv returned unexpected response', heading='Upload Failed')
                    return None

            except ImportError:
                # Fallback: requests not available, shouldn't happen in Kodi but handle it
                c.log('[Log Upload] requests library not available', 1)
                progress.close()
                control.okDialog('requests library not available', heading='Upload Failed')
                return None

        except Exception as e:
            progress.close()
            c.log(f'[Log Upload] Network/upload error: {str(e)}', 1)
            c.log(f'[Log Upload] Traceback: {traceback.format_exc()}', 1)
            control.okDialog(f'Network error: {str(e)}', heading='Upload Failed')
            return None

    except Exception as e:
        try:
            progress.close()
        except:
            pass
        control.okDialog(f'Unexpected error: {str(e)}', heading='Upload Failed')
        c.log(f'[Log Upload] Error: {e}', 1)
        c.log(f'[Log Upload] Traceback: {traceback.format_exc()}', 1)
        return None
