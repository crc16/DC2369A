#!/usr/bin/python

#============================ adjust path =====================================

import sys
import os
if __name__ == "__main__":
    here = sys.path[0]
    sys.path.insert(0, os.path.join(here, '..'))

#============================ imports =========================================

import time
import threading
import Tkinter
from Tkinter import Canvas


import dustGuiLib
import dustFrame
import dustFrameText
from   dustStyle import dustStyle
import ttk


#graph set up
#http://matplotlib.org/examples/user_interfaces/embedding_in_tk2.html
import matplotlib
matplotlib.use('TkAgg')
from numpy import arange
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2TkAgg
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.pylab import *


#============================ defines =========================================

SYMBOL_DEGREE = u"\u2103"
PERCENT_SIGN  = u"\u0025"

#============================ body ============================================

class dustFrameDC2369AReport(dustFrame.dustFrame):

    '''
    \brief Displays the current level in a mote as well as its battery life.
           Has a running graph of the 

    '''

    GUI_UPDATE_PERIOD = 50

    def __init__(self,
                parentElem,
                guiLock,
                getCurrentCb,
                getChargeCb,
                frameName='Last Report',
                row=0,column=0,
                NUM_CURRENT_VALUES = 10,
                SCALE_CURRENT = 1):
        
        # record params
        self.getCurrentCb       = getCurrentCb
        self.getChargeCb        = getChargeCb
        self.maxcurrentvalues   = NUM_CURRENT_VALUES
        self.currentxData       = []  
        self.currentyData       = [] 
        self.numcurrentvalues   = 0
        self.line               = None  


        # initialize parent
        dustFrame.dustFrame.__init__(self,
            parentElem,
            guiLock,
            'DC2369A Mote Report',
            row,column, False, columnspan = 2
        )

        #configure the dustFrame
        self.columnconfigure(0, weight =1)
        self.columnconfigure(1, weight =1)
        self.columnconfigure(2, weight =1)


        #add the MAC address at the top of the frame
        temp    = dustGuiLib.Label(self.container,text = frameName)
        self._add(temp,0,0)
        temp.grid(columnspan = 3)
        temp.configure(
            font            = ("Helvetica",12,"bold"),  
            anchor          = Tkinter.CENTER
        )

        #Current label
        temp    = dustGuiLib.Label(self.container,text = 'Measured Current (A)')
        self._add(temp,1,0)
        temp.configure(
            font            = ("Helvetica",12,"bold"),  
            anchor          = Tkinter.CENTER
        )
        #Current Display
        self.current = dustGuiLib.Label(
            self.container,
            fg               = 'green',
            relief           = Tkinter.GROOVE, 
            borderwidth      = 2,
            width            = 6,
        )
        self._add(self.current,2,0)
        self.current.configure(
            font             = ('System', 40,'bold'),
            bg               = 'black',
        )
        
        # Charge label
        temp                 = dustGuiLib.Label(self.container, text= 'Used Battery Life')
        self._add(temp,3,0)
        temp.configure(
            font             = ("Helvetica",12,"bold"),
            anchor           = Tkinter.CENTER
        )
        #Charge Display
        self.charge     = dustGuiLib.Label(
            self.container,
            fg               = 'green',
            relief           = Tkinter.GROOVE, 
            borderwidth      = 2,
        )
        self._add(self.charge,4,0)
        self.charge.configure(
            font             = ('System', 40,'bold'),
            bg               = 'black',
        )

        #Graph
        #setup figure and subplots
        fig = plt.Figure(figsize = (4.5, 3))
        ax = fig.add_subplot(111)

        #adjust to be able to view axes titles
        fig.subplots_adjust(bottom = .2, left = .2, top = .85)
        #set axis and graph titles
        ax.set_title("Recent Current Values")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Current (A)")
        #set axis dimensions
        ax.axis([0, self.maxcurrentvalues -1, -SCALE_CURRENT - 0.2, SCALE_CURRENT + 0.2])
        #set graph visibility options - turn off x axis labels
        ax.get_xaxis().set_ticklabels([])
        ax.yaxis.grid()
        ax.xaxis.grid()

        #plot data
        self.line, = ax.plot(self.currentxData, self.currentyData, 'b-')
        plt.show()

        #set up animation 
        canvas = FigureCanvasTkAgg(fig, master=self.container)
        canvas.get_tk_widget().grid(column=2, row=1, rowspan = 4)
        canvas._tkcanvas.config(highlightthickness = 0)
        self.ani = animation.FuncAnimation(fig, self.animate, arange(1,200), init_func = self.clear_animation, 
                                            interval=30, blit=True)

        # schedule first GUI update, and call a update to set the valuies for Current and Charge
        self.updateGui()
        self.after(self.GUI_UPDATE_PERIOD,self.updateGui)
    
    #======================== public ==========================================
    
    #======================== privater ========================================
    #set values for the x and y axis in the new version of the script. 
    #we have to set the x every time due to the blit function of the FuncAnimation
    def animate(self,i):
        self.line.set_ydata(self.currentyData)
        self.line.set_xdata(self.currentxData)
        return self.line,

    #set up the animation to have no data
    def clear_animation(self):
        self.line.set_data([0.0], [0.0])
        return self.line,

    def updateGui(self):
        # current
        #this is a deque object, so get the most recent input
        newCurrentDeque = self.getCurrentCb()
        #set default current value
        newCurrent = 0.0
        if len(newCurrentDeque) != 0:
            #make the deque into a list, so we can get the length. 
            self.currentyData = list(newCurrentDeque)
            count = len(self.currentyData)
            #create the x axis.
            self.currentxData = [self.maxcurrentvalues - count + i for i in range(count)]
            #grab the most recent data point, if its valid set to newCurrent
            temp = float(self.currentyData[count-1])
            if temp != None:
                newCurrent = temp
        #regardless, set the new format to read newCurrent
        self.current.configure(
            text = '{0:.4f}'.format(newCurrent),
        )
        
        # charge
        newCharge = self.getChargeCb()
        if newCharge == None:
            newCharge = 0.0

        self.charge.configure(
            text = '{0:.1f}'.format(newCharge) + PERCENT_SIGN,
        )

        # schedule next GUI update
        self.after(self.GUI_UPDATE_PERIOD,self.updateGui)



#============================ sample app =============================
# The following gets called only if you run this module as a 
# standalone app, by double-clicking on this source file. This code is 
# NOT executed when importing this module is a larger application
#
class exampleApp(object):
    
    UPDATE_PERIOD_CHARGE     = .5 # seconds
    UPDATE_PERIOD_CURRENT    = .5 # seconds
    
    def __init__(self):
        now = time.time()
        self.lastUpdateCurrent     = now
        self.lastUpdateCharge    = now
        
        self.window  = dustWindow('dustFrameDC2369AReport',
            self._closeCb)
        self.guiLock    = threading.Lock()
        self.frame      = dustFrameDC2369AReport(
            self.window,
            self.guiLock,
            getCurrentCb      = self._getCurrentCb,
            getChargeCb     = self._getChargeCb
            #row=0,column=1
        )
        self.frame.show()
        self.window.mainloop()
    
    def _getCurrentCb(self):
        
        returnVal = None
        
        now = time.time()
        
        if now-self.lastUpdateCurrent>self.UPDATE_PERIOD_CURRENT:
            returnVal = random.uniform(-40,85)
            self.lastUpdateCurrent = now
        
        print "_getCurrentCb() returns  {0}".format(returnVal)
        
        return returnVal

    def _getChargeCb(self):
        
        returnVal = None
        
        now = time.time()
        
        if now-self.lastUpdateCharge>self.UPDATE_PERIOD_CHARGE:
            returnVal = random.uniform(-40,85)
            self.lastUpdateCharge = now
        
        print "_getChargeCb() returns  {0}".format(returnVal)
        
        return returnVal

        
    def _closeCb(self):
        print ' _closeCb called'
        #self.window.close()
        self.window.quit()
        self.window.destroy()
        sys.exit()

if __name__ == '__main__':
    import random

    from dustWindow import dustWindow
    exampleApp()
