#!/usr/bin/python

#============================ adjust path =====================================

import sys
import os
if __name__ == "__main__":
    here = sys.path[0]
    sys.path.insert(0, os.path.join(here, '..'))

#============================ imports =========================================

import Tkinter

from   SmartMeshSDK     import  FormatUtils
import dustGuiLib
import dustFrame
from   dustStyle        import dustStyle

#============================ body ============================================

class dustFrameDC2369AConfiguration(dustFrame.dustFrame):
    
    def __init__(self,
            parentElem,
            guiLock,
            selectedMoteChangedCB,
            displayMoteButtonCB,
            refreshButtonCB,
            clearMotesButtonCB,
            frameName="Configuration",row=0,column=1):
        
        # record params
        self.selectedMoteChangedCB     = selectedMoteChangedCB
        self.displayMoteButtonCB       = displayMoteButtonCB
        self.refreshButtonCB           = refreshButtonCB
        self.clearMotesButtonCB        = clearMotesButtonCB
        
        # local variables
        self.selectedMote         = Tkinter.StringVar()
        self.selectedMote.trace("w",self._selectedMoteChangedCB_internal)
        
        # initialize parent
        dustFrame.dustFrame.__init__(self,
            parentElem,
            guiLock,
            frameName,
            row,column
        )
            
        # motes
        temp                      = dustGuiLib.Label(self.container,
            anchor                = Tkinter.NW,
            justify               = Tkinter.LEFT,
            text                  = 'Select mote:')
        self._add(temp,0,0)
        self.motes                = dustGuiLib.OptionMenu(
            self.container,
            self.selectedMote,
            *['']
        )
        self._add(self.motes,0,1)

        # display mote button
        self.displayMoteButton = dustGuiLib.Button(self.container,
            text                  = 'Display Mote',
            command               = self.displayMoteButtonCB,
        )
        self._add(self.displayMoteButton,0,2)      

        # refresh button
        self.refreshButton        = dustGuiLib.Button(self.container,
            text                  = 'Update Mote List',
            command               = self.refreshButtonCB
        )
        self._add(self.refreshButton,1,2)

        #clear mote buttons
        self.clearMotesButton     = dustGuiLib.Button(self.container,
            text                  = 'Clear Motes',
            command               = self.clearMotesButtonCB,
        )
        self._add(self.clearMotesButton,2,2)

        # action label
        self.actionLabel          = dustGuiLib.Label(self.container,
            anchor                = Tkinter.CENTER,
            justify               = Tkinter.LEFT,
            text                  = '',
        )
        self._add(self.actionLabel,1,1)
        
        
    
    #============================ public ======================================
    
    def displayConfiguration(self,reportPeriod,bridgeSettlingTime,ldoOnTime):
        
        with self.guiLock:
            # delete previous content
            self.reportPeriod.delete(1.0,Tkinter.END)
            self.bridgeSettlingTime.delete(1.0,Tkinter.END)
            self.ldoOnTime.delete(1.0,Tkinter.END)
            
            # clear color
            self.reportPeriod.configure(bg=dustStyle.COLOR_BG)
            self.bridgeSettlingTime.configure(bg=dustStyle.COLOR_BG)
            self.ldoOnTime.configure(bg=dustStyle.COLOR_BG)
            
            # insert new content
            self.reportPeriod.insert(1.0,str(reportPeriod))
            self.bridgeSettlingTime.insert(1.0,str(bridgeSettlingTime))
            self.ldoOnTime.insert(1.0,str(ldoOnTime))
    
    def disableButtons(self):
        
        with self.guiLock:
            self.refreshButton.configure(state=Tkinter.DISABLED)
            self.displayMoteButton.configure(state=Tkinter.DISABLED)
            self.motes.configure(state=Tkinter.DISABLED)
            self.clearMotesButton.configure(state=Tkinter.DISABLED)

    
    def enableButtons(self):
        
        with self.guiLock:
            self.refreshButton.configure(state=Tkinter.NORMAL)
            self.displayMoteButton.configure(state=Tkinter.NORMAL)
            self.motes.configure(state=Tkinter.NORMAL)
            self.clearMotesButton.configure(state=Tkinter.NORMAL)

    def refresh(self, macs):
        with self.guiLock:
            self.motes['menu'].delete(0, 'end')
            
            # format the MAC addresses into strings
            formattedMacs = [FormatUtils.formatMacString(mac) for mac in macs]
            
            # update the optionmenu
            for mac in formattedMacs:
                self.motes['menu'].add_command(
                    label   = mac,
                    command = Tkinter._setit(self.selectedMote,mac)
                )
            
            # update the selected mote, if pre
            previousSelectedMote = self.selectedMote.get()
            if (formattedMacs) and (previousSelectedMote not in formattedMacs):
                self.selectedMote.set(formattedMacs[0])
    
    def writeActionMsg(self,text):
        
        with self.guiLock:
            self.actionLabel.configure(text=text)
    
    #============================ private =====================================
    
    def _selectedMoteChangedCB_internal(self,*args):
        
        # get selected mote
        bytes = self.selectedMote.get().split('-')
        
        if len(bytes)==8:
            # convert
            selectedMote = [int(b,16) for b in self.selectedMote.get().split('-')]
            
            # indicate
            self.selectedMoteChangedCB(selectedMote)
        
#============================ sample app =============================
# The following gets called only if you run this module as a 
# standalone app, by double-clicking on this source file. This code is 
# NOT executed when importing this module is a larger application
#
class exampleApp(object):
    
    ACTION_DELAY = 1.0 # in seconds
    
    def __init__(self):
        self.window  = dustWindow.dustWindow("dustFrameDC2369AConfiguration",
                                  self._closeCb)
        self.guiLock              = threading.Lock()
        self.frame = dustFrameDC2369AConfiguration(self.window,self.guiLock,
            selectedMoteChangedCB = self._selectedMoteChangedCB,
            refreshButtonCB       = self._refreshButtonCB,
            displayMoteButtonCB   = self._displayMoteButtonCB,
            row=0,column=0
        )
        self.frame.show()
        self.window.mainloop()
    
    #===== GUI action callbacks
    
    def _selectedMoteChangedCB(self,mote):
        print "selected mote changed to {0}".format(mote)
    
    def _refreshButtonCB(self):
        print "refresh button pressed, scheduling action in {0}s".format(self.ACTION_DELAY)
        t = threading.Timer(self.ACTION_DELAY,self._refresh)
        t.start()

    def _displayMoteButtonCB(self):
        print "display mote button pressed..."
    
    
    def _closeCb(self):
        print " _closeCb called"
    
    #===== private
    
    def _refresh(self):
        print "Refreshing"
        self.frame.refresh(
            macs = [
                [0x11]*8,
                [0x22]*8,
                [0x33]*8,
            ]
        )
        
if __name__ == '__main__':
    import threading
    import dustWindow
    exampleApp()
