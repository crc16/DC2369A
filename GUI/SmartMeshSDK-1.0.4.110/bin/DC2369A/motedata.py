#============================ imports =========================================
from collections                                 import deque
import threading

#============================ defines =========================================


#============================ body ============================================

class moteData(object):
    '''
    \brief A data type to encapsulate the data displayed in the dc2369 report
    '''

    # def __new__(cls, *args, **kwargs):
    #     if not cls._instance:
    #         cls._instance = super(dc2369aData, cls).__new__(cls, *args, **kwargs)
    #     return cls._instance


    def __init__(self, macAddress, moteNumber, numCurrentValues):        
        # variables
        self.macAddress         = macAddress
        self.charge             = 0.0
        self.current            = deque(maxlen = numCurrentValues)
        self.dataLock           = threading.RLock()
        self.moteNumber         = moteNumber


    #======================== public ==========================================
    def getAddress(self):
        with self.dataLock:
            return self.macAddress

    def getAddressString(self):
        with self.dataLock:
            str = "("
            for i in range(len(self.macAddress)):
                #temp = hex(self.macAddress[i])
                temp = format(self.macAddress[i], 'x')
                if len(temp)==1:
                    temp = '0'+temp
                if i != 0 & i != len(self.macAddress)-1:
                    str += "-"
                str += temp
            str += ")"
            return str

    def setCharge(self, charge):
        with self.dataLock:
            self.charge     = float(charge)

    def getCharge(self):
        with self.dataLock:
            return self.charge

    def setCurrent(self,current):
        with self.dataLock:
            self.current.append(float(current))

    def getCurrent(self):
        with self.dataLock:
            return self.current

    def getMoteNumber(self):
        with self.dataLock:
            return self.moteNumber
            
    def toString(self):
        if len(self.current) == 0:
            return str(self.macAddress) + ' has no data associated yet.'
        else:
            lastCurrent = list(self.current)[0]
            return str(self.macAddress) + ' has (charge,current) of (' + str(lastCurrent)+ ', ' + str(self.charge) + ').\n'


#============================ main ============================================

def main():
    motedata = moteData((0,1,0,0,0,3,3,2))
    print str(list(motedata.getCurrent()))
    for x in range (0, 15):
        motedata.setCurrent(x / 15.0 )
    print motedata.toString()

if __name__ == '__main__':
    main()