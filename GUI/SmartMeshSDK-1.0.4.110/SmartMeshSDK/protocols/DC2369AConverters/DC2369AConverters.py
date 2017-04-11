#!/usr/bin/python

import logging
class NullHandler(logging.Handler):
	def emit(self, record):
		pass
log = logging.getLogger('DC2369AConverters')
log.setLevel(logging.ERROR)
log.addHandler(NullHandler())

NUM_COUNTS 			= 65535.0
FULL_SCALE     		= 2.1
HALF_SCALE    		= FULL_SCALE / 2
VOLTS_PER_COUNT 	= FULL_SCALE / NUM_COUNTS #~32 uA per count, this is the exact value.



class DC2369AConverters(object):
	
	
	#======================== singleton pattern ===============================
	
	_instance           = None
	_init               = False
	
	def __new__(cls, *args, **kwargs):
		if not cls._instance:
			cls._instance = super(DC2369AConverters,cls).__new__(cls, *args, **kwargs)
		return cls._instance
	
	def __init__(self, SCALE):
		
		# don't re-initialize an instance (needed because singleton)
		if self._init:
			return
		self._init = True
		
		# store params
		# 1 if sensing over a 10 mOhm sense resistor, can be altered depending on application
		self.scale = float(SCALE)

		# log
		log.info("creating instance")		
	
	#======================== public ==========================================
	
	def convertCurrent(self,value):   
		'''
		\brief Convert raw current value to mA.
		'''
		# convert to a floating point value between +/- 1.05 * self.scale
		# Note that the full scale of the ADC is 1.05A, not 1A.
		returnVal = (float(value * VOLTS_PER_COUNT) - HALF_SCALE) * self.scale

		return returnVal


	def convertCharge(self,value):
		'''
		\brief Convert raw current value to mA.
		'''		
		#convert to proper format for the charge value
		temp = float(value)
		#each count of charge is ~1/180 used of the battery
		returnVal = temp / 180. * 100.
		return returnVal	

	
#======================== private =========================================

#============================ main ============================================

def main():
	DC2369converter = DC2369AConverters()
	print DC2369converter.convertCurrent(32850)
	print DC2369converter.convertCharge(0x00000A)

if __name__ == '__main__':
	main()