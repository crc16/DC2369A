#!/usr/bin/python

#============================ adjust path =====================================

import sys
import os
if __name__ == "__main__":
    here = sys.path[0]
    sys.path.insert(0, os.path.join(here, '..', '..'))

#============================ verify installation =============================

from SmartMeshSDK import SmsdkInstallVerifier
(goodToGo,reason) = SmsdkInstallVerifier.verifyComponents(
    [
        SmsdkInstallVerifier.PYTHON,
        SmsdkInstallVerifier.PYSERIAL,
    ]
)
if not goodToGo:
    print "Your installation does not allow this application to run:\n"
    print reason
    raw_input("Press any button to exit")
    sys.exit(1)

#============================ imports =========================================

# add the SmartMeshSDK folder to the path
import time
import struct
from   operator import eq
import Tkinter
import threading
import tkMessageBox
import copy
import motedata

from   SmartMeshSDK                              import AppUtils,                        \
                                                        FormatUtils
from   SmartMeshSDK.ApiDefinition                import IpMgrDefinition
from   SmartMeshSDK.ApiException                 import APIError
from   SmartMeshSDK.protocols.DC2369AConverters  import DC2369AConverters
from   dustUI                                    import dustWindow,                      \
                                                        dustFrameConnection,             \
                                                        dustFrameText,                   \
                                                        dustFrameDC2369AConfiguration,   \
                                                        dustFrameDC2369AReport
from   SmartMeshSDK.IpMgrConnectorMux            import IpMgrConnectorMux,               \
                                                        IpMgrSubscribe

#============================ logging =========================================

# local

import logging
class NullHandler(logging.Handler):
    def emit(self, record):
        pass
log = logging.getLogger('App')
log.setLevel(logging.ERROR)
log.addHandler(NullHandler())

# global

AppUtils.configureLogging()

#============================ defines =========================================

#===== udp port
#apparently this is an ID specific to the board we are using
WKP_DC2369A             = 61624

#===== command IDs

CMDID_BASE              =  0x2484

# host->mote
CMDID_GET_CONFIG        = CMDID_BASE   # GET current configuration
CMDID_SET_CONFIG        = CMDID_BASE+1 # SET configuration

# mote->host
CMDID_CONFIGURATION     = CMDID_BASE   # current configuration
CMDID_REPORT            = CMDID_BASE+1 # report

#===== error codes

ERR_BASE                = 0x0BAD
ERR_NO_SERVICE          = ERR_BASE
ERR_NOT_ENOUGH_BW       = ERR_BASE+1

#===== Universal data constants
#memory of current, must be larger then 1
NUM_CURRENT_VALUES      = 10
SCALE_CURRENT           = 1.0

#============================ body ============================================

##
# \addtogroup DC2369A
# \{
# 

class dc2369aData(object):
    '''
    \brief A singleton that holds the data for this application. 
    It also holds a list of the currently displayed motes.
    '''
    
    #======================== singleton pattern ===============================
    
    _instance = None
    _init     = False
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(dc2369aData, cls).__new__(cls, *args, **kwargs)
        return cls._instance
    
    def __init__(self):
        
        # don't re-initialize an instance (needed because singleton)
        if self._init:
            return
        self._init = True
        
        # variables
        self.dataLock       = threading.RLock()
        self.data           = {}
        self.displayedMotes = []            #an array holding a list of motedata objects that are displayed

    
    #======================== public ==========================================
    #Helper functions for the self.data dictionary
    def set(self,k,v):
        with self.dataLock:
            self.data[k] = v
    
    def get(self,k):
        with self.dataLock:
            return copy.copy(self.data[k])

    #helper functions for the displayed Motes
    def addDisplayedMote(self, mote):
        with self.dataLock:
            self.displayedMotes.append(mote)

    def editDisplayedMote(self,mote,index):
        with self.dataLock:
            self.displayedMotes[index] = mote

    def getDisplayedMote(self,index):
        with self.dataLock:
            return self.displayedMotes[index]

    def clearDisplayedMotes(self):
        with self.dataLock:
            self.displayedMotes = []

    #determine if a mote is already being displayed with a mote address of addr
    def moteDisplayed(self, addr):
        with self.dataLock:
            numDisplayedMotes = int(self.get('numDisplayedMotes'))
            for i in range(numDisplayedMotes):
                displayedAddr = self.displayedMotes[i].getAddress()
                if displayedAddr == addr:
                    return True
            return False


class dc2369a(object):
    
    def __init__(
            self,
            connector,
            disconnectedCB, 
            updateMotesCB,
        ):
        
        # store params
        self.connector                 = connector
        self.disconnectedCB            = disconnectedCB
        self.updateMotesCB             = updateMotesCB
        
        # local variables
        self.converters = DC2369AConverters.DC2369AConverters(SCALE_CURRENT)
        
        # subscriber
        self.subscriber = IpMgrSubscribe.IpMgrSubscribe(self.connector)
        self.subscriber.start()
        self.subscriber.subscribe(
            notifTypes  =    [
                IpMgrSubscribe.IpMgrSubscribe.NOTIFDATA,
            ],

            fun =            self._notifDataCallback,
            isRlbl =         False,
        )
        self.subscriber.subscribe(
            notifTypes =     [
                IpMgrSubscribe.IpMgrSubscribe.ERROR,
                IpMgrSubscribe.IpMgrSubscribe.FINISH,
            ],
            fun =            self.disconnectedCB,
            isRlbl =         True,
        )
    
    #======================== public ==========================================
    
    def refreshMotes(self):
        '''
        \brief Get the MAC addresses of all operational motes in the network.
               Initialize an associated boolean list which represents if the mote is a dc2369a mote
        '''
        motes = []
        
        # start getMoteConfig() iteration with the 0 MAC address
        currentMac      = (0,0,0,0,0,0,0,0) 
        continueAsking  = True
        while continueAsking:
            try:
                res = self.connector.dn_getMoteConfig(currentMac,True)
            except APIError:
                continueAsking = False
            else:
                if ((not res.isAP) and (res.state in [4,])):
                    motes.append(tuple(res.macAddress))
                currentMac = res.macAddress
        
        # order by increasing MAC address
        motes.sort()
        
        # store in data singleton
        dc2369aData().set('motes',motes)
        # initialize a running list of the motes that are selectable.
        motesCorrectType = [False for i in range(len(motes))]
        dc2369aData().set('motesCorrectType', motesCorrectType)

    def disconnect(self):
        self.connector.disconnect()
    
    #======================== private =========================================
    
    #===== sending
    
    def _sendPayload(self,payload):
        
        if type(payload)==str:
            payload          = [ord(b) for b in payload]
        
        try:
            self.connector.dn_sendData(
                macAddress   = dc2369aData().get('selectedMote'),
                priority     = 2,
                srcPort      = WKP_DC2369A,
                dstPort      = WKP_DC2369A,
                options      = 0,
                data         = payload,
            )
        except Exception as err:
            log.error(err)
    
    #===== parsing

    def _notifDataCallback(self,notifName,notifParams):
        
        #get number of motes
        numMotes = dc2369aData().get('numDisplayedMotes')

        # verify board type
        if notifParams.dstPort != WKP_DC2369A:
            return

        #board is now of the correct type, add to list of accepted motes
        motes = dc2369aData().get('motes')
        motesCorrectType = dc2369aData().get('motesCorrectType')

        #check over all the motes, to see if the mote sending this data pack marked as viewable
        #if it is not marked as viewable, mark it as such
        for i in range(len(motes)):
            if tuple(notifParams.macAddress) == tuple(motes[i]):
                if not(motesCorrectType[i]):
                    motesCorrectType[i] = True
                    dc2369aData().set('motesCorrectType', motesCorrectType)
                    self.updateMotesCB();
                break           #if it is already marked as valid we can quit the for loop

        #only want to do anything if more then 1 mote
        if numMotes < 1:
            return

        #check to see that the address is associated with a displayed mote
        moteIndex = 0
        for i in range(numMotes):
            tempMote = dc2369aData().getDisplayedMote(i)
            if tuple(notifParams.macAddress) == tuple(tempMote.getAddress()):
                moteIndex = i
                break
            elif i == (numMotes - 1):
                return          #if it is not displayed, then we can quit

        #parse the data
        try:
            parsedData = self._parseData(notifParams.data)
        except ValueError as err:
            output  = "Could not parse received data {0}".format(
                FormatUtils.formatBuffer(notifParams.data)
            )
            print output
            log.error(output)
            return

        # log data
        output  = []
        output += ["Received data:"]
        for (k,v) in parsedData.items():
            output += ["- {0:<15}: 0x{1:x} ({1})".format(k,v)]
        output  = '\n'.join(output)
        log.debug(output)


        #grab mote
        tempMote = dc2369aData().getDisplayedMote(moteIndex)
        #if there is no mote yet we have nothing to do
        if tempMote == None: 
            return

        #record current
        current = self.converters.convertCurrent(parsedData['current']) 
        tempMote.setCurrent(current)  

        #record charge
        charge = self.converters.convertCharge(parsedData['charge'])
        tempMote.setCharge(charge)  

        dc2369aData().editDisplayedMote(tempMote, moteIndex)

    #parse data coming from dc2369.
    def _parseData(self,byteArray):
        returnVal = {}
        #log
        log.debug("_parseData with byteArray {0}".format(FormatUtils.formatBuffer(byteArray)))

        try:
            (
                returnVal['current'],
                returnVal['charge'],
            ) = struct.unpack('>HB', self._toString(byteArray[:]))
        except struct.error as err:
            raise ValueError(err)
        return returnVal

    #===== formatting
    
    def _toString(self, byteArray):
        return ''.join([chr(b) for b in byteArray])
    
class dc2369aGui(object):
    
    def __init__(self):
        
        # local variables
        self.guiLock                = threading.Lock()
        self.apiDef                 = IpMgrDefinition.IpMgrDefinition()
        self.dc2369aHandler         = None
        self.connector              = None
        
        # initialize data singleton
        dc2369aData().set('selectedMote',   None)
        dc2369aData().set('numDisplayedMotes', 0)
        
        # create window
        self.window               = dustWindow.dustWindow(
            'DC2369A',
            self._windowCb_close,
        )
        
        # add connection Frame
        self.connectionFrame      = dustFrameConnection.dustFrameConnection(
            self.window,
            self.guiLock,
            self._connectionFrameCb_connected,
            frameName="Serial connection",
            row=0,column=0,
        )
        self.connectionFrame.apiLoaded(self.apiDef)
        self.connectionFrame.serialPortText.delete("1.0",Tkinter.END)
        self.connectionFrame.show()
        
        # add configuration frame
        self.configurationFrame   = dustFrameDC2369AConfiguration.dustFrameDC2369AConfiguration(
            self.window,
            self.guiLock,
            selectedMoteChangedCB   = self._selectedMoteChangedCB,
            displayMoteButtonCB     = self._displayMoteButtonCB,
            refreshButtonCB         = self._refreshButtonCB,
            clearMotesButtonCB      = self._clearMotesButtonCB,
            row=0,column=1,
        )
        self.configurationFrame.disableButtons()
        self.configurationFrame.show()
        
        # establish a list of report Frames, so we can keep track of them as they are added
        self.reportFrames = []
        
        # local variables
        self.userMsg         = ''      # error message printed to user
    
    #======================== public ==========================================
    
    def start(self):
        # start Tkinter's main thread
        try:
            self.window.bind('<<Err>>', self._sigHandlerErr)
            self.window.mainloop()
        except SystemExit:
            sys.exit()
    
    #======================== private =========================================
    
    #===== window callback to close and shut down all operations

    # we do not want to destroy the window until we have disconnected, 
    # or else it will have nothing to disconnect from.
    def _windowCb_close(self):
        if self.dc2369aHandler:
            self.dc2369aHandler.disconnect()
        #wait until we have disconnected to quit/destroy
        if self.connector:
            while(self.connector != None):
                pass
            # below is needed to get rid of the matplotlib scripts
            self.window.quit()
            self.window.destroy()

    
    #===== connectionFrame
    
    def _connectionFrameCb_connected(self,connector):
        '''
        \brief Called when the connectionFrame has connected.
        '''
        # store the connector
        self.connector = connector
        
        # start a notification client
        self.dc2369aHandler = dc2369a(
            connector                  = self.connector,
            disconnectedCB             = self._connectionFrameCb_disconnected,
            updateMotesCB              = self._updateMoteList,
        )
        
        # enable cfg buttons
        self.configurationFrame.enableButtons()
        
        # load operational motes
        self._refreshButtonCB()

    def _connectionFrameCb_disconnected(self,notifName,notifParams):
        '''
        \brief Called when the connectionFrame has disconnected.
        '''  
        if self.connector:
            # disable cfg buttons
            self.configurationFrame.disableButtons()

            # update the GUI
            self.connectionFrame.updateGuiDisconnected()

            # delete the connector
            self.connector.disconnect()
        self.connector = None
        
    
    #===== configurationFrame
    
    def _selectedMoteChangedCB(self,mote):
        dc2369aData().set('selectedMote',mote)
    
    def _refreshButtonCB(self): 
        self.dc2369aHandler.refreshMotes()
        # refresh list - no motes have identified themselves as dc2369a boards, so none are availible yet
        self.configurationFrame.refresh([])

    # get the list of all motes, and remove ones that are not dc2369a boards
    # set the new list as the list of availible address's
    def _updateMoteList(self):
        motes = dc2369aData().get('motes')
        motesCorrectType = dc2369aData().get('motesCorrectType')
        for i in reversed(range(len(motes))):
            if not(motesCorrectType[i]):
                motes.pop(i)
        self.configurationFrame.writeActionMsg('Updating Motes...')
        self.configurationFrame.refresh(motes)
       

    #add a report frame if the selected mote does not already have one
    def _displayMoteButtonCB(self):
        addr = dc2369aData().get('selectedMote')
        if addr == None:
            return
        elif dc2369aData().moteDisplayed(addr):
            self.configurationFrame.writeActionMsg('Mote Already Displayed')
        else:
            self.configurationFrame.writeActionMsg('Displaying Mote...')
            self._displayReportFrame()

    #clear all mote displays    
    def _clearMotesButtonCB(self):
        numdisplayedmotes = dc2369aData().get('numDisplayedMotes')
        for i in reversed(range(numdisplayedmotes)):
            frm = self.reportFrames[i]
            frm.grid_forget()
            frm.destroy()
        dc2369aData().set('numDisplayedMotes', 0)
        dc2369aData().clearDisplayedMotes()
        self.configurationFrame.writeActionMsg('Clearing Motes...')
        self.reportFrames = []
    
    
    #===== reportFrame
    def _displayReportFrame(self):
        macAddr  = dc2369aData().get('selectedMote')
        numdisplayedmotes = dc2369aData().get('numDisplayedMotes')
        mote     = motedata.moteData(macAddr, numdisplayedmotes, NUM_CURRENT_VALUES)
        dc2369aData().set('numDisplayedMotes', numdisplayedmotes + 1)
        dc2369aData().addDisplayedMote(mote)

        #determine row and column for new report frame (only 3 per column, and each column takes up 2 rows)
        row = numdisplayedmotes % 3 + 1
        column = (numdisplayedmotes / 3) * 2

        temp = dustFrameDC2369AReport.dustFrameDC2369AReport(
            self.window,
            self.guiLock,
            getCurrentCb            = lambda: self._getCurrent(numdisplayedmotes),
            getChargeCb             = lambda: self._getCharge(numdisplayedmotes),
            frameName               = mote.getAddressString(),
            row = row,     column = column,
            NUM_CURRENT_VALUES      = NUM_CURRENT_VALUES,
            SCALE_CURRENT           = SCALE_CURRENT
        )
        temp.show()
        self.reportFrames.append(temp)

    #callback function to get list of current values
    def _getCurrent(self, i):
        tempMote = dc2369aData().getDisplayedMote(i)
        return tempMote.getCurrent()

    #callback function to get the charge value
    def _getCharge(self, i):
        tempMote = dc2369aData().getDisplayedMote(i)
        return tempMote.getCharge()
    
    #===== internal signal handlers
    
    def _sigHandlerErr(self,args):
        tkMessageBox.showerror(title="Error",message=self.userMsg)

#============================ main ============================================

def main():

    dc2369aGuiHandler = dc2369aGui()
    dc2369aGuiHandler.start()

if __name__ == '__main__':
    main()

##
# end of DC2369A
# \}
# 
