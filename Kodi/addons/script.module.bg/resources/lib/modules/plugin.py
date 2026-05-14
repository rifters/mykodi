import xbmc
import xbmcplugin
import xbmcaddon
import sys
import os
from .params import Params
from .bg_enabler import bg_enable
from .bg_disabler import bg_disable

handle = int(sys.argv[1])

def router(paramstring):

    p = Params(paramstring)
    xbmc.log(str(p.get_params()),xbmc.LOGDEBUG)

    mode = p.get_mode()
    
    xbmcplugin.setContent(handle, 'files')

    if mode == 1:
        bg_enable()

    elif mode == 2:
        bg_disable()


    xbmcplugin.endOfDirectory(handle)
