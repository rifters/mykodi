# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file log_uploader.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
Log Uploader Module

Uploads Kodi and The Crew logs anonymously to paste services for troubleshooting.

'''
import os
import re
import platform
from datetime import datetime
import xbmc
import xbmcvfs
from . import control
from .crewruntime import c


class LogUploader:
    """Handles anonymous log uploads for troubleshooting"""

    @staticmethod
    def _sanitize_log(text):
        """
        Anonymize log content by removing/replacing sensitive information.
        Returns sanitized text safe for public sharing.
        """
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

        # Replace Linux/Mac paths: /home/username -> /home/[USER]
        sanitized = re.sub(r'/home/[^/]+', r'/home/[USER]', sanitized)
        sanitized = re.sub(r'/Users/[^/]+', r'/Users/[USER]', sanitized)

        # Replace actual usernames if detected
        if actual_username:
            sanitized = sanitized.replace(actual_username, '[USER]')
        if system_username and system_username != actual_username:
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

    @staticmethod
    def upload_kodi_log():
        """Upload Kodi's kodi.log file anonymously"""
        try:
            c.log('[LogUploader] Starting Kodi log upload')

            # Get Kodi log path
            log_path = xbmcvfs.translatePath('special://logpath/kodi.log')

            if not os.path.exists(log_path):
                c.log(f'[LogUploader] Kodi log not found at: {log_path}')
                control.infoDialog('Kodi log file not found', icon='ERROR')
                return False

            # Read log file
            c.log(f'[LogUploader] Reading Kodi log from: {log_path}')
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read()

            original_size = len(log_content)
            c.log(f'[LogUploader] Original log size: {original_size} bytes')

            # Sanitize log content (make it anonymous)
            c.log('[LogUploader] Sanitizing log content (anonymizing)...')
            sanitized_content = LogUploader._sanitize_log(log_content)

            # Add header with upload info
            header = f'''# The Crew - Kodi Log Upload
# Upload Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Plugin Version: {c.pluginversion}
# Module Version: {c.moduleversion}
# Kodi Version: {c.kodiversion}
# Platform: {c.platform}
# NOTE: This log has been ANONYMIZED - usernames, IPs, and tokens replaced
# Original Size: {original_size:,} bytes
#
================================================================================

'''
            sanitized_content = header + sanitized_content
            log_size = len(sanitized_content)
            c.log(f'[LogUploader] Sanitized log size: {log_size} bytes')

            # Upload to paste service
            paste_url = LogUploader._upload_to_paste(sanitized_content, 'Kodi Log')

            if paste_url:
                c.log(f'[LogUploader] Kodi log uploaded successfully: {paste_url}')
                # Show QR code dialog
                LogUploader._show_qr_code(
                    paste_url,
                    'Kodi Log Uploaded Successfully',
                    f'Your Kodi log has been uploaded ANONYMOUSLY.\n\n'
                    f'All usernames, IPs, MAC addresses, and tokens have been removed.\n\n'
                    f'Share this link with support:\n{paste_url}\n\n'
                    f'Scan QR code with your phone or copy the link above.\n\n'
                    f'Expires in 7 days | Size: {log_size:,} bytes'
                )
                return True
            else:
                c.log('[LogUploader] Failed to upload Kodi log')
                control.infoDialog('Failed to upload log', icon='ERROR')
                return False

        except Exception as e:
            c.log(f'[LogUploader] Error uploading Kodi log: {e}')
            import traceback
            c.log(f'[LogUploader] Traceback: {traceback.format_exc()}')
            control.infoDialog('Error uploading log', icon='ERROR')
            return False

    @staticmethod
    def upload_crew_log():
        """Upload The Crew's the_crew.log file anonymously"""
        try:
            c.log('[LogUploader] Starting The Crew log upload')

            # Get The Crew log path - same location where it's written (special://logpath)
            log_dir = xbmcvfs.translatePath('special://logpath')
            log_path = os.path.join(log_dir, 'the_crew.log')

            if not os.path.exists(log_path):
                c.log(f'[LogUploader] The Crew log not found at: {log_path}')
                control.infoDialog('The Crew log file not found', icon='ERROR')
                return False

            # Read log file
            c.log(f'[LogUploader] Reading The Crew log from: {log_path}')
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read()

            original_size = len(log_content)
            c.log(f'[LogUploader] Original log size: {original_size} bytes')

            # Sanitize log content (make it anonymous)
            c.log('[LogUploader] Sanitizing log content (anonymizing)...')
            sanitized_content = LogUploader._sanitize_log(log_content)

            # Add header with upload info
            header = f'''# The Crew - The Crew Log Upload
# Upload Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Plugin Version: {c.pluginversion}
# Module Version: {c.moduleversion}
# Kodi Version: {c.kodiversion}
# Platform: {c.platform}
# NOTE: This log has been ANONYMIZED - usernames, IPs, and tokens replaced
# Original Size: {original_size:,} bytes
#
================================================================================

'''
            sanitized_content = header + sanitized_content
            log_size = len(sanitized_content)
            c.log(f'[LogUploader] Sanitized log size: {log_size} bytes')

            # Upload to paste service
            paste_url = LogUploader._upload_to_paste(sanitized_content, 'The Crew Log')

            if paste_url:
                c.log(f'[LogUploader] The Crew log uploaded successfully: {paste_url}')
                # Show QR code dialog
                LogUploader._show_qr_code(
                    paste_url,
                    'The Crew Log Uploaded Successfully',
                    f'Your The Crew log has been uploaded ANONYMOUSLY.\n\n'
                    f'All usernames, IPs, MAC addresses, and tokens have been removed.\n\n'
                    f'Share this link with support:\n{paste_url}\n\n'
                    f'Scan QR code with your phone or copy the link above.\n\n'
                    f'Expires in 7 days | Size: {log_size:,} bytes'
                )
                return True
            else:
                c.log('[LogUploader] Failed to upload The Crew log')
                control.infoDialog('Failed to upload log', icon='ERROR')
                return False

        except Exception as e:
            c.log(f'[LogUploader] Error uploading The Crew log: {e}')
            import traceback
            c.log(f'[LogUploader] Traceback: {traceback.format_exc()}')
            control.infoDialog('Error uploading log', icon='ERROR')
            return False

    @staticmethod
    def _upload_to_paste(content, title='Log'):
        """
        Upload content to a paste service anonymously

        Args:
            content (str): The content to upload
            title (str): Title for the paste

        Returns:
            str: URL of the uploaded paste, or None if failed
        """
        try:
            from ..modules.http_client import HTTPClient

            c.log(f'[LogUploader] Uploading to paste service ({len(content)} bytes)')

            # Use dpaste.com - free, anonymous, no account needed
            paste_url = 'https://dpaste.com/api/v2/'

            # Prepare data
            data = {
                'content': content,
                'title': title,
                'syntax': 'text',
                'expiry_days': 7  # Expire after 7 days
            }

            # Get session and upload
            session = HTTPClient.get_session('default')
            response = session.post(paste_url, data=data, timeout=30)
            response.raise_for_status()

            # dpaste returns the URL in the response text
            result_url = response.text.strip()

            if result_url and result_url.startswith('http'):
                c.log(f'[LogUploader] Upload successful: {result_url}')
                return result_url
            else:
                c.log(f'[LogUploader] Unexpected response: {result_url}')

                # Fallback: Try paste.ubuntu.com
                c.log('[LogUploader] Trying fallback paste service')
                return LogUploader._upload_to_ubuntu_paste(content, title)

        except Exception as e:
            c.log(f'[LogUploader] Error uploading to dpaste: {e}')
            import traceback
            c.log(f'[LogUploader] Traceback: {traceback.format_exc()}')

            # Fallback to ubuntu paste
            try:
                return LogUploader._upload_to_ubuntu_paste(content, title)
            except:
                return None

    @staticmethod
    def _upload_to_ubuntu_paste(content, title='Log'):
        """Fallback paste service using paste.ubuntu.com"""
        try:
            from ..modules.http_client import HTTPClient

            c.log('[LogUploader] Using Ubuntu paste as fallback')

            paste_url = 'https://paste.ubuntu.com/'

            data = {
                'content': content,
                'poster': 'The Crew Addon',
                'syntax': 'text',
                'expiration': '604800'  # 7 days in seconds
            }

            session = HTTPClient.get_session('default')
            response = session.post(paste_url, data=data, timeout=30)
            response.raise_for_status()

            # Ubuntu paste returns HTML, extract URL from response
            result_url = response.url  # The final URL after redirect

            if result_url and result_url != paste_url:
                c.log(f'[LogUploader] Fallback upload successful: {result_url}')
                return result_url
            else:
                c.log('[LogUploader] Fallback upload failed')
                return None

        except Exception as e:
            c.log(f'[LogUploader] Fallback upload error: {e}')
            return None

    @staticmethod
    def _show_qr_code(url, header, message):
        """Show QR code dialog for URL"""
        try:
            import xbmcgui
            import tempfile
            import hashlib

            # Generate QR code with unique filename based on URL hash
            try:
                from ..modules.segno import make as make_qr

                # Create temp directory if it doesn't exist
                temp_dir = os.path.join(tempfile.gettempdir(), 'thecrew_qr')
                os.makedirs(temp_dir, exist_ok=True)

                # Generate unique filename using hash of URL (prevents caching issues)
                url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                qr_filename = os.path.join(temp_dir, f'log_upload_qr_{url_hash}.png')

                # Generate QR code
                c.log(f'[LogUploader] Generating QR code: {qr_filename}')
                qr = make_qr(url, error='H')  # High error correction
                qr.save(qr_filename, scale=10, border=2, dark='#000000', light='#FFFFFF')

                qr_path = qr_filename
            except Exception as e:
                c.log(f'[LogUploader] QR code generation failed: {e}')
                qr_path = None

            if not qr_path or not os.path.exists(qr_path):
                c.log('[LogUploader] QR code generation failed, falling back to textviewer')
                control.dialog.textviewer(header, message)
                return

            # Simple QR viewer class
            class LogQRViewer(xbmcgui.WindowXMLDialog):
                def __init__(self, *args, **kwargs):
                    self.header = kwargs.get('header', 'Log Uploaded')
                    self.message = kwargs.get('message', '')
                    self.qr_path = kwargs.get('qr_path', '')

                def onInit(self):
                    try:
                        # Control IDs from LogViewer_QR.xml
                        HEADERLABEL = 101
                        TEXT = 502
                        QR_IMAGE = 501
                        CLOSEBUTTON = 503

                        self.getControl(HEADERLABEL).setLabel(self.header)
                        self.getControl(TEXT).setText(self.message)
                        self.getControl(QR_IMAGE).setImage(self.qr_path)
                        self.setFocusId(CLOSEBUTTON)
                    except Exception as e:
                        c.log(f'[LogUploader] QR dialog init error: {e}')

                def onAction(self, action):
                    # Close on back/esc
                    if action.getId() in [10, 92]:  # ACTION_NAV_BACK, ACTION_PREVIOUS_MENU
                        self.close()

                def onClick(self, controlId):
                    if controlId == 503:  # Close button
                        self.close()

            # Show dialog
            xml_file = 'LogViewer_QR.xml'
            addon_path = c.get_artwork_path()
            skin = c.appearance() or 'thecrew'

            dialog = LogQRViewer(
                xml_file,
                addon_path,
                skin,
                header=header,
                message=message,
                qr_path=qr_path
            )
            dialog.doModal()
            del dialog

        except Exception as e:
            c.log(f'[LogUploader] QR dialog error: {e}')
            import traceback
            c.log(f'[LogUploader] Traceback: {traceback.format_exc()}')
            # Fallback to textviewer
            control.dialog.textviewer(header, message)
