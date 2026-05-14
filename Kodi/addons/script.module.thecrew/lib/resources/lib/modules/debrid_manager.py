# -*- coding: utf-8 -*-

'''
    The Crew Add-on
    Debrid Account Manager

    Displays user account information for Real-Debrid, AllDebrid, and Premiumize
    Shows account status, expiration, points, and cloud storage access
'''

import xbmcgui
from resources.lib.modules import control
from resources.lib.modules.crewruntime import c

# Import new API classes
from resources.lib.apis.realdebrid_api import RealDebridAPI
from resources.lib.apis.alldebrid_api import AllDebridAPI
from resources.lib.apis.premiumize_api import PremiumizeAPI
from resources.lib.apis.orion_api import OrionAPI
from resources.lib.apis.trakt_api import TraktAPI

try:
    import resolveurl
    RESOLVEURL_AVAILABLE = True
except Exception:
    RESOLVEURL_AVAILABLE = False


class DebridAccountManager:
    def __init__(self):
        self.services = {
            'Real-Debrid': self.get_realdebrid_info,
            'AllDebrid': self.get_alldebrid_info,
            'Premiumize': self.get_premiumize_info,
            'Orion': self.get_orion_info,
            'Trakt': self.get_trakt_info
        }

    def show_account_info(self):
        """Main entry point - shows account info for all configured debrid services"""
        if not RESOLVEURL_AVAILABLE:
            xbmcgui.Dialog().ok(
                '[B]Debrid Account Manager[/B]',
                'ResolveURL is not installed or configured.\nPlease install ResolveURL to use debrid services.'
            )
            return

        # Get info for all services
        c.log('[Debrid Manager] Starting account info check...', 1)
        service_info = {}
        for service_name, get_info_func in self.services.items():
            try:
                c.log(f'[Debrid Manager] Checking {service_name}...', 1)
                info = get_info_func()
                if info:
                    c.log(f'[Debrid Manager] Got info for {service_name}', 1)
                    service_info[service_name] = info
                else:
                    c.log(f'[Debrid Manager] No info returned for {service_name}', 1)
            except Exception as e:
                c.log(f'[Debrid Manager] Error getting {service_name} info: {e}', 1)

                c.log(f'[Debrid Manager] Traceback: {traceback.format_exc()}', 1)

        c.log(f'[Debrid Manager] Found {len(service_info)} configured services', 1)
        if not service_info:
            xbmcgui.Dialog().ok(
                '[B]Debrid Account Manager[/B]',
                'No debrid accounts configured.\nConfigure your debrid services in ResolveURL settings.'
            )
            return

        # Show menu with available services
        self.show_service_menu(service_info)

    def show_service_menu(self, service_info):
        """Shows menu to select which debrid service to view details for"""
        service_names = list(service_info.keys())
        service_labels = []

        for name in service_names:
            info = service_info[name]
            status = '[COLOR green]Active[/COLOR]' if info.get('active') else '[COLOR red]Inactive[/COLOR]'
            service_labels.append(f'[COLOR skyblue]{name}[/COLOR]: {status}')

        service_labels.append('[COLOR skyblue]Browse Cloud Storage[/COLOR]')
        service_labels.append('Configure Debrid Services')

        choice = xbmcgui.Dialog().select(
            '[B]Debrid Account Manager[/B]',
            service_labels
        )

        if choice < 0:
            return
        elif choice < len(service_names):
            # Show detailed info for selected service
            self.show_service_details(service_names[choice], service_info[service_names[choice]], service_info)
        elif choice == len(service_names):
            # Browse cloud storage
            self.browse_cloud_menu(service_info)
        else:
            # Open ResolveURL settings
            control.execute('RunPlugin(plugin://plugin.video.thecrew/?action=ResolveUrlSettings)')

    def show_service_details(self, service_name, info, service_info):
        """Shows detailed account information for a specific service"""
        lines = []

        # Username / Name
        if info.get('username'):
            lines.append(f'Username: {info["username"]}')
        if info.get('name') and info['name'] != 'N/A':
            lines.append(f'Name: {info["name"]}')
        if info.get('email'):
            lines.append(f'Email: {info["email"]}')

        # Trakt-specific: VIP status
        if 'vip' in info:
            if info.get('vip_og'):
                lines.append('[COLOR gold]Status: VIP OG (Lifetime)[/COLOR]')
            elif info.get('vip_ep'):
                lines.append('[COLOR gold]Status: VIP Executive Producer[/COLOR]')
            elif info.get('vip'):
                lines.append('[COLOR gold]Status: VIP[/COLOR]')
            else:
                lines.append('Status: Free Account')

        # Format expiration date and calculate days left
        if info.get('expiration') and info['expiration'] != 'N/A':
            expiration_str, days_left = self._format_expiration(info['expiration'])
            lines.append(f'Expires: {expiration_str}')
            if days_left is not None and days_left >= 0:
                if days_left == 0:
                    lines.append('[COLOR red]Days Left: Expires Today![/COLOR]')
                elif days_left <= 7:
                    lines.append(f'[COLOR red]Days Left: {days_left} days[/COLOR]')
                elif days_left <= 30:
                    lines.append(f'[COLOR yellow]Days Left: {days_left} days[/COLOR]')
                else:
                    lines.append(f'[COLOR green]Days Left: {days_left} days[/COLOR]')
            elif days_left is not None and days_left < 0:
                lines.append(f'[COLOR red]Expired {abs(days_left)} days ago[/COLOR]')

        # Account type / Package
        if info.get('type'):
            lines.append(f'Account Type: {info["type"]}')
        if info.get('package'):
            lines.append(f'Package: {info["package"]}')

        # Points / Credits
        if info.get('points'):
            lines.append(f'Points/Credits: {info["points"]}')

        # Storage
        if info.get('storage'):
            lines.append(f'Storage Used: {info["storage"]}')

        # Limits
        if info.get('limits'):
            lines.append(f'Limits: {info["limits"]}')

        # Trakt-specific: Watch stats
        if info.get('movies_watched') is not None:
            lines.append('')
            lines.append('[B]Watch Statistics:[/B]')
            lines.append(f'Movies Watched: {info.get("movies_watched", 0):,}')
            lines.append(f'Movies Collected: {info.get("movies_collected", 0):,}')
            lines.append(f'Shows Watched: {info.get("shows_watched", 0):,}')
            lines.append(f'Episodes Watched: {info.get("episodes_watched", 0):,}')

            # Convert minutes to human-readable format
            total_minutes = info.get('total_minutes', 0)
            hours = total_minutes // 60
            days = hours // 24
            if days > 0:
                lines.append(f'Total Watch Time: {days:,} days ({hours:,} hours)')
            elif hours > 0:
                lines.append(f'Total Watch Time: {hours:,} hours')
            else:
                lines.append(f'Total Watch Time: {total_minutes:,} minutes')

        # Trakt-specific: Privacy & Location
        if info.get('private') is not None:
            lines.append(f'Privacy: {"Private" if info["private"] else "Public"}')
        if info.get('location') and info['location'] != 'N/A':
            lines.append(f'Location: {info["location"]}')
        if info.get('timezone') and info['timezone'] != 'N/A':
            lines.append(f'Timezone: {info["timezone"]}')

        # Inactive status
        if not info.get('active'):
            lines.append('[COLOR red]Account is not active or expired[/COLOR]')

        # Add options at the end
        lines.append('')
        lines.append('[COLOR skyblue]<< Back to Account Manager[/COLOR]')

        choice = xbmcgui.Dialog().select(
            f'[B]{service_name} Account[/B]',
            lines
        )

        # If user selects "Back" option (last item) or backs out, return to main menu
        if choice == len(lines) - 1 or choice < 0:
            # Show the service menu again
            self.show_service_menu(service_info)

    def browse_cloud_menu(self, service_info):
        """Shows menu to select cloud storage to browse"""
        service_names = [name for name in service_info.keys()]
        service_labels = [f'[COLOR skyblue]{name}[/COLOR] Cloud Storage' for name in service_names]
        service_labels.append('[COLOR skyblue]<< Back to Account Manager[/COLOR]')

        choice = xbmcgui.Dialog().select(
            '[B]Browse Cloud Storage[/B]',
            service_labels
        )

        if choice < 0:
            # User cancelled
            return
        elif choice < len(service_names):
            # Selected a service
            service_name = service_names[choice]
            self.browse_cloud_storage(service_name, service_info)
        else:
            # Back button - return to main menu
            self.show_service_menu(service_info)

    def browse_cloud_storage(self, service_name, service_info):
        """Opens cloud storage browser for the selected service"""
        c.log(f'[Debrid Manager] Opening {service_name} cloud browser...', 1)

        # Use control.execute to run the cloud browser action through the router
        if service_name == 'Real-Debrid':
            control.execute('Container.Update(plugin://plugin.video.thecrew/?action=rd_cloud)')
        elif service_name == 'AllDebrid':
            control.execute('Container.Update(plugin://plugin.video.thecrew/?action=ad_cloud)')
        elif service_name == 'Premiumize':
            control.execute('Container.Update(plugin://plugin.video.thecrew/?action=pm_cloud)')
        else:
            xbmcgui.Dialog().ok(
                'Unknown Service',
                f'Cloud browsing not available for {service_name}'
            )
            self.browse_cloud_menu(service_info)

    def get_realdebrid_info(self):
        """Get Real-Debrid account information using new API class"""
        try:
            # Check if service is configured via ResolveURL
            if not self._is_resolver_logged_in('Real-Debrid'):
                c.log('[Debrid Manager] Real-Debrid not configured', 1)
                return None

            # Use new API class to get user info
            c.log('[Debrid Manager] Using RealDebridAPI to get user info...', 1)
            rd = RealDebridAPI()
            data = rd.get_user()

            if data:
                c.log(f'[Debrid Manager] Real-Debrid data received: {data.get("username", "N/A")}', 1)
                return {
                    'active': True,
                    'username': data.get('username', 'N/A'),
                    'email': data.get('email', 'N/A'),
                    'expiration': data.get('expiration', 'N/A'),
                    'type': data.get('type', 'N/A'),
                    'points': str(data.get('points', 0)),
                    'limits': f"{data.get('limit', 'N/A')}"
                }
        except Exception as e:
            c.log(f'[Debrid Manager] Real-Debrid error: {e}', 1)
        return None

    def get_alldebrid_info(self):
        """Get AllDebrid account information using new API class"""
        try:
            # Check if service is configured via ResolveURL
            if not self._is_resolver_logged_in('AllDebrid'):
                c.log('[Debrid Manager] AllDebrid not configured', 1)
                return None

            # Use new API class to get user info
            c.log('[Debrid Manager] Using AllDebridAPI to get user info...', 1)
            ad = AllDebridAPI()
            response = ad.get_user()
            c.log(f'[Debrid Manager] AllDebrid raw response: {response}', 1)

            if response and 'user' in response:
                data = response.get('user', {})
                c.log(f'[Debrid Manager] AllDebrid data received: {data.get("username", "N/A")}', 1)
                return {
                    'active': True,
                    'username': data.get('username', 'N/A'),
                    'email': data.get('email', 'N/A'),
                    'expiration': data.get('premiumUntil', 'N/A'),
                    'type': 'Premium' if data.get('isPremium') else 'Free',
                    'points': str(data.get('fidelityPoints', 0))
                }
        except Exception as e:
            c.log(f'[Debrid Manager] AllDebrid error: {e}', 1)
        return None

    def get_premiumize_info(self):
        """Get Premiumize account information using new API class"""
        try:
            # Check if service is configured via ResolveURL
            if not self._is_resolver_logged_in('Premiumize.me'):
                c.log('[Debrid Manager] Premiumize not configured', 1)
                return None

            # Use new API class to get account info
            c.log('[Debrid Manager] Using PremiumizeAPI to get account info...', 1)
            pm = PremiumizeAPI()
            data = pm.account_info()
            c.log(f'[Debrid Manager] Premiumize raw response: {data}', 1)

            if data:
                c.log(f'[Debrid Manager] Premiumize data received: {data.get("customer_id", "N/A")}', 1)
                # Premiumize API doesn't return email, username, or total storage limit
                # Only: customer_id, premium_until, space_used, limit_used (bandwidth)
                storage_used = data.get('space_used', 0)
                storage_str = f'{storage_used / (1024**3):.2f} GB used'

                return {
                    'active': True,
                    'username': f'Customer ID: {data.get("customer_id", "N/A")}',
                    'expiration': data.get('premium_until', 'N/A'),
                    'type': 'Premium' if data.get('premium_until') else 'Free',
                    'storage': storage_str
                }
        except Exception as e:
            c.log(f'[Debrid Manager] Premiumize error: {e}', 1)
        return None

    def get_orion_info(self):
        """Get Orion account information"""
        try:
            c.log('[Debrid Manager] Starting Orion info check...', 1)

            # Check if Orion is installed
            if not c.is_orion_installed():
                c.log('[Debrid Manager] Orion is not installed', 1)
                return None

            c.log('[Debrid Manager] Orion is installed, creating API instance...', 1)

            # Create Orion API instance
            orion_api = OrionAPI()

            c.log(f'[Debrid Manager] OrionAPI instance created, available={orion_api.available}', 1)

            if not orion_api.available:
                c.log('[Debrid Manager] Orion API not available', 1)
                return None

            c.log('[Debrid Manager] Checking if Orion is enabled...', 1)

            if not orion_api.is_enabled():
                c.log('[Debrid Manager] Orion is not enabled or not authenticated', 1)
                return None

            c.log('[Debrid Manager] Orion is enabled, getting account info...', 1)

            # Get account info
            info = orion_api.account_info()
            if not info:
                c.log('[Debrid Manager] Orion account_info returned None', 1)
                return None

            c.log(f'[Debrid Manager] Orion account info: {info}', 1)
            return info

        except Exception as e:
            c.log(f'[Debrid Manager] Error getting Orion info: {e}', 1)
            import traceback
            c.log(f'[Debrid Manager] Traceback: {traceback.format_exc()}', 1)
            return None

    def get_trakt_info(self):
        """Get Trakt account information"""
        try:
            c.log('[Debrid Manager] Starting Trakt info check...', 1)

            # Create Trakt API instance
            trakt_api = TraktAPI()

            c.log(f'[Debrid Manager] TraktAPI instance created, authenticated={trakt_api.is_authenticated()}', 1)

            # Check if authenticated
            if not trakt_api.is_authenticated():
                c.log('[Debrid Manager] Trakt is not authenticated', 1)
                return None

            c.log('[Debrid Manager] Trakt is authenticated, getting account info...', 1)

            # Get account info
            info = trakt_api.account_info()
            if not info:
                c.log('[Debrid Manager] Trakt account_info returned None', 1)
                return None

            c.log(f'[Debrid Manager] Trakt account info for: {info.get("username", "N/A")}', 1)
            return info

        except Exception as e:
            c.log(f'[Debrid Manager] Error getting Trakt info: {e}', 1)
            import traceback
            c.log(f'[Debrid Manager] Traceback: {traceback.format_exc()}', 1)
            return None

    def _get_resolver(self, service_name):
        """Get resolver instance for a service"""
        try:
            if not RESOLVEURL_AVAILABLE:
                return None

            # Get resolver class and instantiate it
            resolver_classes = [r for r in resolveurl.relevant_resolvers(order_matters=True) if r.name == service_name]
            if resolver_classes:
                return resolver_classes[0]()  # Instantiate the resolver class
            return None
        except Exception as e:
            c.log(f'[Debrid Manager] Error getting {service_name} resolver: {e}', 1)
            return None

    def _is_resolver_logged_in(self, service_name):
        """Check if service is configured in ResolveURL addon settings"""
        try:
            if not RESOLVEURL_AVAILABLE:
                return False

            # Get ResolveURL addon instance
            resolver_addon = control.addon('script.module.resolveurl')

            # Map service names to ResolveURL setting prefixes
            service_map = {
                'Real-Debrid': 'RealDebridResolver',
                'AllDebrid': 'AllDebridResolver',
                'Premiumize.me': 'PremiumizeMeResolver'
            }

            prefix = service_map.get(service_name)
            if not prefix:
                c.log(f'[Debrid Manager] Unknown service: {service_name}', 1)
                return False

            # Check if enabled and has token
            enabled = resolver_addon.getSetting(f'{prefix}_enabled') == 'true'
            token = resolver_addon.getSetting(f'{prefix}_token')

            if enabled and token:
                c.log(f'[Debrid Manager] {service_name} is configured in ResolveURL', 1)
                return True
            else:
                c.log(f'[Debrid Manager] {service_name} not configured (enabled={enabled}, has_token={bool(token)})', 1)
                return False

        except Exception as e:
            c.log(f'[Debrid Manager] Login check error for {service_name}: {e}', 1)
            return False

    def _get_resolver_auth(self, resolver):
        """Get auth token/key from resolver"""
        try:
            # Try to get stored auth data
            if hasattr(resolver, 'get_setting'):
                # Try different setting names used by different services
                for setting_name in ['token', 'api_key', 'apikey', 'auth', 'client_id']:
                    try:
                        value = resolver.get_setting(setting_name)
                        if value:
                            c.log(f'[Debrid Manager] Retrieved {setting_name} for {resolver.name}', 1)
                            return value
                    except Exception:
                        continue

            c.log(f'[Debrid Manager] No auth token found for {resolver.name}', 1)
        except Exception as e:
            c.log(f'[Debrid Manager] Auth retrieval error for {resolver.name}: {e}', 1)
        return None

    def _format_expiration(self, expiration):
        """Convert Unix timestamp or ISO date to readable format and calculate days left"""
        try:
            from datetime import datetime, timezone

            # Try to parse as Unix timestamp first
            try:
                if isinstance(expiration, (int, float)):
                    exp_timestamp = int(expiration)
                elif isinstance(expiration, str) and expiration.isdigit():
                    exp_timestamp = int(expiration)
                else:
                    # Try parsing as ISO date string
                    exp_dt = datetime.fromisoformat(expiration.replace('Z', '+00:00'))
                    exp_timestamp = int(exp_dt.timestamp())

                exp_dt = datetime.fromtimestamp(exp_timestamp, timezone.utc)
                now = datetime.now(timezone.utc)

                # Calculate days left
                days_left = (exp_dt - now).days

                # Format as readable date
                date_str = exp_dt.strftime('%Y-%m-%d %H:%M UTC')

                return date_str, days_left
            except (ValueError, OSError):
                # If timestamp parsing fails, try as ISO string
                return str(expiration), None
        except Exception as e:
            c.log(f'[Debrid Manager] Expiration format error: {e}', 1)
            return str(expiration), None


def show_debrid_accounts():
    """Entry point for the debrid account manager"""
    manager = DebridAccountManager()
    manager.show_account_info()
