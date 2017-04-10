/**
Copyright (c) 2015, Dust Networks.  All rights reserved.
 
 LTP5901 interfaces with 2 other chips:
 LTC3335 via I2C and an interrupt on DP0 to measure charge used
 LTC1864L using SPI and SS_0 to measure system current

 Samples current every SAMPLE_INTERVAL and sends packet with sample and last charge measurement
 
 Future enhancements:

  * LTC2063 shutdown - need to know spinup time. Mote CPU cost for asserting/deasserting SHDNB_OUT with each
         measurement (currently 1/s) eats into saving from shutdown.
  * LTC3335 PGOOD checking - several options:
         ** Alarm when PGOOD drops, but still read LTC3335 output
         ** Poll PGOOD at start of while(1) in LTC3335 task and skip loop if not asserted
         ** Pend on PGOOD assert at start of while(1) in LTC3335 task. Since GPIO are level sensitive, this
            could result in interrupts being generated continuosly, which may be problematic.
  * Timestamping - this requires significant change to the code, as the current local task
         module consumes these notifications.
  * Could cut down on mote energy use by aggregating samples before sending
*/

// SDK includes
#include "dn_common.h"
#include "dn_system.h"
#include "dn_spi.h"
#include "dn_i2c.h"
#include "dn_gpio.h"
#include "dn_exe_hdr.h"
#include "cli_task.h"
#include "loc_task.h"
#include "well_known_ports.h"
#include "Ver.h"

// project includes
#include "app_task_cfg.h"

// C includes
#include "string.h"
#include "stdio.h"

//=========================== definitions =====================================
//===== pins
#define IRQN_IN                     DN_GPIO_PIN_0_DEV_ID  // DP0/M SS2n
#define PGOOD_IN                    DN_GPIO_PIN_16_DEV_ID // PWM0
//#define RIPPLE_CNTR                 DN_GPIO_PIN_21_DEV_ID //DP2
#define SHDNB_OUT                   DN_GPIO_PIN_22_DEV_ID // DP3
//#define OUTPUT_3V                   DN_GPIO_PIN_23_DEV_ID //DP4

#define PIN_LOW                     0x00
#define PIN_HIGH                    0x01
#define ENABLE                      1

//states for powering and disabling ICs
#define IC_DISABLED                 0
#define IC_POWERED                  1

//===== SPI ===============
#define SPI_BUFFER_LENGTH           4         // bytes 
#define SPI_TRANSFER                2         // bytes - one 16-bit sample per read

//===== timeout & durations
#define SAMPLE_PERIOD               1000      // ms
#define ONE_SECOND                  1000      // ms
#define LT2063_STARTUP              450       // ms, experimentally determined for how long it takes output
                                              // to become accurate after DC2063 is turned on
//===== LTC3335 registers==
#define REGISTER_A                  0x01
#define REGISTER_B                  0x02
#define REGISTER_C                  0x03
#define REGISTER_D                  0x04
#define REGISTER_E                  0x05

#define ALARM_TRIP_MASK             0x04
#define ALARM_CC_OVERFLOW_MASK      0x02
#define ALARM_ACON_OVERFLOW_MASK    0x01
#define TRIPPED                     1
#define CLEAR                       1
#define PENDING                     0
#define RIPPLE_OUTPUT               0x02 
#define PRESCALER                   0x09        // This needs to be adjusted to fit the battery and peak current

#define I2C_SLAVE_ADDR              0x64        // b1100100 - note that the LTC3335 datasheet shifts this left by one
                                                // bit for the read/write bit (what goes out the wire), so calls out 0xC8. 
#define I2C_PAYLOAD_LENGTH          2

//===== to enable debug functions =======
//#define DEBUG

//=========================== structs & enums =================================
//===== message formats

PACKED_START

typedef struct{
   INT16S   adcData;
   INT8U    charge;
}report_t;

typedef struct{
   INT32U samplePeriod;      // report period, in seconds
} app_cfg_t;

PACKED_STOP

//=========================== variables =======================================

typedef struct {
   // admin
   OS_EVENT*                    joinedSem;   // Posted when mote has joined the network.
   OS_EVENT*                    serviceSem;  // Posted when the mote has its requested services
   app_cfg_t                    app_cfg;
   // LTC3335 task
   OS_STK                       ltc3335TaskStack[TASK_APP_LTC3335_STK_SIZE];
   // LTC1864L task
   OS_STK                       ltc1864TaskStack[TASK_APP_LTC1864_STK_SIZE];
   // report task
   OS_STK                       reportTaskStack[TASK_APP_REPORT_STK_SIZE];
   OS_TMR*                      sampleTimer;        // Triggers transmissions of report.
   OS_EVENT*                    reportSem;          // Posted when time to send a new report.
   OS_EVENT*                    sampleSem;          // posted when time to boot up the 2063
   //data reporting
   report_t                     report;             // array of  ADC samples from LTC1864L + latest current from LTC3335
   //GPIO
   INT32U                       gpioNotifChannelBuf[1 + DN_CH_ASYNC_RXBUF_SIZE(sizeof(dn_gpio_notif_t))/sizeof(INT32U)];
   //I2C
   INT8U                        i2cBuffer[I2C_PAYLOAD_LENGTH];
   dn_ioctl_i2c_transfer_t      i2cTransfer;
   BOOLEAN                      fI2cOpened;
} app_v_t;

app_v_t app_v;

//=========================== prototypes ======================================
//i2c
INT8U   i2cRead(INT8U regAddr);
INT8U   i2cWrite(INT8U regAddr, INT8U value);

// GPIO
dn_error_t    gpioSetMode(INT8U pin, INT8U mode, INT8U pull, INT8U initLevel);
// for future use
void    gpioWrite(INT8U pin,INT8U value);

//=== Command Line Interface (CLI) handlers =======
dn_error_t cli_reset(INT8U* arg, INT32U len);
#ifdef DEBUG
dn_error_t cli_regSet(INT8U* arg, INT32U len);
dn_error_t cli_regGet(INT8U* arg, INT32U len);
#endif

//tasks
static void ltc3335Task(void* unused);
static void ltc1864Task(void* unused);
static void reportTask(void* unused);

//timer callback
void sampleTimer_cb(void* pTimer, void *pArgs);

//other functions
INT8U sendReport();

//=========================== const  ==============================================
// Note - help strings for user defined CLI commands don't work in stack 1.0.3.28
const dnm_ucli_cmdDef_t cliCmdDefs[] = {
  {&cli_reset,                      "reset",          "",       DN_CLI_ACCESS_LOGIN },
#ifdef DEBUG  
  {&cli_regSet,                     "regset",         "",       DN_CLI_ACCESS_LOGIN },
  {&cli_regGet,                     "regget",         "",       DN_CLI_ACCESS_LOGIN },
#endif
  {NULL,                            NULL,             NULL,                        0},
};

//=========================== initialization ==================================

int p2_init(void){// This is the entry point in the application code.  Stack is expecting it to be called p2_init.
   INT8U           osErr;
  
   //===== initialize module variables
   memset(&app_v,0,sizeof(app_v_t));
  
    // create semaphores
   app_v.joinedSem   = OSSemCreate(0);   
   app_v.serviceSem  = OSSemCreate(0);
   app_v.reportSem   = OSSemCreate(1);   // "1" so mote sends report as soon as operational
   app_v.sampleSem   = OSSemCreate(1);
   
   //==== initialize helper tasks
   cli_task_init(
      "DC2369A",                            // appName
      cliCmdDefs                            // cliCmds
   );
   
   loc_task_init(
      JOIN_YES,                                 // fJoin
      NULL,                                     // netId
      WKP_USER_1,                               // udpPort
      app_v.joinedSem,                          // joinedSem
      SAMPLE_PERIOD,                            // bandwidth
      app_v.serviceSem                          // serviceSem
   );
	
   //===== create LTC3335 i2c task
   osErr = OSTaskCreateExt(
                           ltc3335Task,
                           (void *) 0,
                           (OS_STK*) (&app_v.ltc3335TaskStack[TASK_APP_LTC3335_STK_SIZE-1]),
                           TASK_APP_LTC3335_PRIORITY,
                           TASK_APP_LTC3335_PRIORITY,
                           (OS_STK*) app_v.ltc3335TaskStack,
                           TASK_APP_LTC3335_STK_SIZE,
                           (void *) 0,
                           OS_TASK_OPT_STK_CHK | OS_TASK_OPT_STK_CLR
   );
   ASSERT(osErr == OS_ERR_NONE);
	
   OSTaskNameSet(
                  TASK_APP_LTC3335_PRIORITY,
                  (INT8U*)TASK_APP_LTC3335_NAME,
                  &osErr
   );
   ASSERT(osErr == OS_ERR_NONE);
	
   //===== create LTC1864L spi adc task
   osErr = OSTaskCreateExt(
                           ltc1864Task,
                           (void *) 0,
                           (OS_STK*) (&app_v.ltc1864TaskStack[TASK_APP_LTC1864_STK_SIZE-1]),
                           TASK_APP_LTC1864_PRIORITY,
                           TASK_APP_LTC1864_PRIORITY,
                           (OS_STK*) app_v.ltc1864TaskStack,
                           TASK_APP_LTC1864_STK_SIZE,
                           (void *) 0,
                           OS_TASK_OPT_STK_CHK | OS_TASK_OPT_STK_CLR
   );
   ASSERT(osErr == OS_ERR_NONE);
	
   OSTaskNameSet(
                  TASK_APP_LTC1864_PRIORITY,
                  (INT8U*)TASK_APP_LTC1864_NAME,
                  &osErr
   );
   ASSERT(osErr == OS_ERR_NONE);

   //===== create report task
   osErr = OSTaskCreateExt(
                           reportTask,
                           (void *) 0,
                           (OS_STK*) (&app_v.reportTaskStack[TASK_APP_REPORT_STK_SIZE-1]),
                           TASK_APP_REPORT_PRIORITY,
                           TASK_APP_REPORT_PRIORITY,
                           (OS_STK*) app_v.reportTaskStack,
                           TASK_APP_REPORT_STK_SIZE,
                           (void *) 0,
                           OS_TASK_OPT_STK_CHK | OS_TASK_OPT_STK_CLR
   );
   ASSERT(osErr == OS_ERR_NONE);
   
   OSTaskNameSet(
                  TASK_APP_REPORT_PRIORITY, 
                  (INT8U*)TASK_APP_REPORT_NAME, 
                  &osErr
   );
   ASSERT(osErr == OS_ERR_NONE);
   
   return 0;
}
//========== CLI handler functions : These get called when a command is entered on the CLI =========
//===== CLI command to reset the mote
// @param arg = a string of arguments passed to the CLI command
// @param len = the length of the argument string
//
// @return  returns an error if dnm_loc_resetCmd fails
dn_error_t cli_reset(INT8U* arg, INT32U len){
   INT8U      rc;
   
   dnm_ucli_printf("Resetting...\r\n\n");
   
   // send reset to stack
   dnm_loc_resetCmd(&rc);	
   
   return(rc);
}

#ifdef DEBUG
//===== CLI command to set LTC3335 registers for testing
// @param arg = a string of arguments passed to the CLI command
// @param len = the length of the argument string
//
// @return  returns an error if incorrect arguments, otherwise DN_ERR_NONE
dn_error_t cli_regSet(INT8U* arg, INT32U len){
   dn_error_t dnErr;
   INT8U      rc;
   char       reg;
   int        value;
   INT8U      length;
   
   if (app_v.fI2cOpened == TRUE){
   
      // expects 2 parameters
      //--- param 0: register
      length = sscanf(arg, "%c", &reg);
      if (length < 1) {
         return DN_ERR_INVALID;
      }

      //--- param 1: value
      length = sscanf(arg+length, "%d", &value);
       if (length < 1) {
         return DN_ERR_INVALID;
      }

      switch (reg){  // can write A,B,C or E
         case 'A':
         case 'B':
         case 'C':
         case 'E': 
             dnErr = i2cWrite(reg - 0x40, value);
             break;
         default:
            dnm_ucli_printf("Error: invalid register\r\n");
            break;
      }   
   }
   else{
      dnm_ucli_printf("Error: i2c not open\r\n");
   }
   
   return DN_ERR_NONE;
}

//===== CLI command to read LTC3335 registers for testing
// @param arg = a string of arguments passed to the CLI command
// @param len = the length of the argument string
//
// @return  returns an error if incorrect arguments, otherwise DN_ERR_NONE
dn_error_t cli_regGet(INT8U* arg, INT32U len){
   dn_error_t dnErr;
   INT8U      rc;
   char       reg;
   INT8U      value;
   INT8U      length;
   
   if (app_v.fI2cOpened == TRUE){
   
      // expects 1 parameters
      //--- param 0: register
      length = sscanf(arg, "%c", &reg);
      if (length < 1) {
         return DN_ERR_INVALID;
      }

      switch (reg){  // can read C or D
         case 'C':
         case 'D':  
             value = i2cRead(reg - 0x40);
             break;
         default:
            dnm_ucli_printf("Error: invalid register\r\n");
            break;
      }   
   }
   else{
      dnm_ucli_printf("Error: i2c not open\r\n");
   }
   
   return DN_ERR_NONE;
}
#endif

//========================== LTC3335 task ====================
//
//   This task:
//   * sets up i2c communications with the the LTC3335
//   * reads the current charge when DPO asserts and stores the value to send to manager
//
//   Note that for the battery on the DC2369A, charge will not overflow 1B, but that this
//   is not generally true for larger batteries or different chip settings. Code needs to handle
//   overflow in the general case.
//
//   The math:
//   Qbat = 1000 mAh
//   Ipeak is ~10 mA during transmit.
//   With M=9, qLSB = 550 uAh
//   Typical current should be ~500 uA (LTC3335 @ ~1 uA , LTC1864 @ ~500 uA, and LTP5901 @ ~50 uA)
//   So we expect the charge count to increment approximately hourly.
//
static void ltc3335Task(void* unused){
   dn_error_t                   dnErr;
   INT8U                        osErr;
   dn_i2c_open_args_t           i2cOpenArgs;
   INT8U                        alarms;		// Alarm source
   CH_DESC                      notifChannel;
   OS_MEM*                      notifChMem;
   dn_gpio_notif_t              gpioNotif;
   dn_gpio_ioctl_notif_enable_t gpioNotifEnable;
   INT32U                       rxLen;
   INT32U                       msgType;
   INT8U                        rc;
	
   //Wait for stack to print version
   OSTimeDly(ONE_SECOND);
   dnm_ucli_printf("\r\n");
   
   // GPIO setup for IRQ pin from LTC3335
   dnErr = gpioSetMode(IRQN_IN, DN_IOCTL_GPIO_CFG_INPUT, DN_GPIO_PULL_UP, 0);
   ASSERT(dnErr == DN_ERR_NONE);
   
   //GPIO setup for IRQ input as divided  counter, just set up as input for now
   //dnErr = gpioSetMode(RIPPLE_CNTR, DN_IOCTL_GPIO_CFG_INPUT, DN_GPIO_PULL_UP, 0);
   //ASSERT(dnErr == DN_ERR_NONE);
   
   //GPIO setup for 3.3V output to power IRQ flip flops, initially it will be powered.
   //dnErr = gpioSetMode(OUTPUT_3V, DN_IOCTL_GPIO_CFG_OUTPUT, DN_GPIO_PULL_NONE, IC_POWERED);
   //ASSERT(dnErr == DN_ERR_NONE);

   
   // allocate memory for GPIO notification channel
   notifChMem = OSMemCreate(
                              app_v.gpioNotifChannelBuf,
                              1,
                              DN_CH_ASYNC_RXBUF_SIZE(sizeof(dn_gpio_notif_t)),
                              &osErr
   );
   ASSERT(osErr==OS_ERR_NONE);
   
   // create channel
   dnErr = dn_createAsyncChannel(notifChMem, &notifChannel);
   ASSERT(dnErr == DN_ERR_NONE);
   
   // i2c setup
   i2cOpenArgs.frequency = DN_I2C_FREQ_184_KHZ;
   dnErr = dn_open(
                   DN_I2C_DEV_ID,
                   &i2cOpenArgs,
                   sizeof(i2cOpenArgs)
                   );
   ASSERT(dnErr==DN_ERR_NONE);
   
   // tell CLI commands that i2c is available
   app_v.fI2cOpened = TRUE;
   
   // Write 0x09 to reg A = 0000 to  A[7:4] and 1001 to A[3:0]
   dnErr = i2cWrite(REGISTER_A, PRESCALER);
   ASSERT(dnErr == DN_ERR_NONE);
   
   // Write 00 to register C to clear
   dnErr = i2cWrite(REGISTER_C, PENDING);
   ASSERT(dnErr == DN_ERR_NONE);
 
   // Write register B - alarm level is 1
   dnErr = i2cWrite(REGISTER_B, TRIPPED);
   ASSERT(dnErr == DN_ERR_NONE);
   
   // Write register E(0) to clear any pending alarms
   dnErr = i2cWrite(REGISTER_E, CLEAR);
   ASSERT(dnErr == DN_ERR_NONE);
   
   // Write register E(0) to prepare for an alarm
   dnErr = i2cWrite(REGISTER_E, PENDING);
   ASSERT(dnErr == DN_ERR_NONE);
   
   //Write register E(1) to 1 to output the ripple counter to the IRQ pin
   dnErr = i2cWrite(REGISTER_E, RIPPLE_OUTPUT);
   ASSERT(dnErr == DN_ERR_NONE);
      
   // enable GPIO notifications
   gpioNotifEnable.fEnable             = ENABLE;
   gpioNotifEnable.activeLevel         = PIN_LOW;
   gpioNotifEnable.notifChannelId      = notifChannel;
   
   dnErr = dn_ioctl(
                    IRQN_IN,
                    DN_IOCTL_GPIO_ENABLE_NOTIF,
                    &gpioNotifEnable,
                    sizeof(gpioNotifEnable)
                    );
   ASSERT(dnErr == DN_ERR_NONE);
   
   while (1) {
		
      // wait for a GPIO notification on IRQN
//      dnErr = dn_readAsyncMsg(
//                              notifChannel,            // chDesc
//                              &gpioNotif,              // msg
//                              &rxLen,                  // rxLen
//                              &msgType,                // msgType
//                              sizeof(gpioNotif),       // maxLen
//                              0                        // timeout - 0 = no timeout
//      );
//      ASSERT(dnErr==DN_ERR_NONE);
//      		
//      // re-arm notification on opposite level
//      if (gpioNotifEnable.activeLevel==PIN_HIGH) {
//         gpioNotifEnable.activeLevel = PIN_LOW;
//      } 
//      else {
//         gpioNotifEnable.activeLevel = PIN_HIGH;
//      }
//      dnErr = dn_ioctl(
//                        IRQN_IN,
//                        DN_IOCTL_GPIO_ENABLE_NOTIF,
//                        &gpioNotifEnable,
//                        sizeof(gpioNotifEnable)
//      );
//      ASSERT(dnErr == DN_ERR_NONE);
//      
//      if (gpioNotifEnable.activeLevel == PIN_HIGH){  // IRQn was triggered     
//         
//         // Write 00 to register C to clear
//         dnErr = i2cWrite(REGISTER_C, PENDING);
//         ASSERT(dnErr == DN_ERR_NONE);
// 
//         // Write register B - alarm level is 1
//         dnErr = i2cWrite(REGISTER_B, TRIPPED);
//         ASSERT(dnErr == DN_ERR_NONE);
//		
//         // check to verify we alarmed due to charge incrementing
//         alarms = i2cRead(REGISTER_D);
//         ASSERT(dnErr == DN_ERR_NONE);
//           
//         if (alarms & ALARM_TRIP_MASK){
//            // store charge for sending to manager
//            app_v.report.charge += 1;
//#ifdef DEBUG            
//            dnm_ucli_printf("charge = %d\r\n", app_v.report.charge); 
//#endif         
//         }
//      
//         if (alarms & ALARM_CC_OVERFLOW_MASK){
//            dnm_ucli_printf("ERROR: CC overflow has occurred\r\n");
//         }
//      
//         if (alarms & ALARM_ACON_OVERFLOW_MASK){
//            dnm_ucli_printf("ERROR: ACON overflow has occurred\r\n");
//         }
//         
//         // Write to E[0] to clear the alarm
//         dnErr = i2cWrite(REGISTER_E, CLEAR);
//         ASSERT(dnErr == DN_ERR_NONE);
//         
//          // Write to E[0] to prepare for an alarm
//         dnErr = i2cWrite(REGISTER_E, PENDING);
//         ASSERT(dnErr == DN_ERR_NONE);
//      }
   }
}

//=========================== LTC1864L task =====================================
//
//   This task:
//   * sets up SPI communications with the the LTC1864L
//   * reads the currrent every SAMPLE_PERIOD 
//   * Data comes out big endian, so we need to swap to display but not to send.
//
static void ltc1864Task(void* unused){
   INT8U                        osErr;
   dn_error_t                   dnErr;
   dn_spi_open_args_t           spiOpenArgs;
   INT8U                        spiTxBuffer[SPI_BUFFER_LENGTH];
   INT8U                        spiRxBuffer[SPI_BUFFER_LENGTH];
   dn_ioctl_spi_transfer_t      spiTransfer;
	
   //Wait for stack to print version
   OSTimeDly(ONE_SECOND);
   dnm_ucli_printf("\r\n");
   
   //===== initialize SPI
   // open the SPI device
   spiOpenArgs.maxTransactionLenForCPHA_1 = 0;
   dnErr = dn_open(
      DN_SPI_DEV_ID,
      &spiOpenArgs,
      sizeof(spiOpenArgs)
   );
   ASSERT(dnErr == DN_ERR_NONE);
   
   // initialize spi communication parameters
   spiTransfer.txData             = spiTxBuffer;
   spiTransfer.rxData             = spiRxBuffer;
   spiTransfer.transactionLen     = SPI_TRANSFER;       // bytes
   spiTransfer.numSamples         = 1;
   spiTransfer.startDelay         = 1;                  // delay 8 clock cycles = ~1 us (max Ten = 120 ns)
   spiTransfer.clockPolarity      = DN_SPI_CPOL_0;      // clock starts low
   spiTransfer.clockPhase         = DN_SPI_CPHA_0;      // capture on rising edge
   spiTransfer.bitOrder           = DN_SPI_MSB_FIRST;
   spiTransfer.slaveSelect        = DN_SPIM_SS_0n;
   spiTransfer.clockDivider       = DN_SPI_CLKDIV_2;    // ~ 3.5 MHz
  
   //configure SHDN pin on the lt2063
   dnErr = gpioSetMode(SHDNB_OUT, DN_IOCTL_GPIO_CFG_OUTPUT, DN_GPIO_PULL_NONE, IC_POWERED);
   ASSERT(dnErr == DN_ERR_NONE);

   //set the sample rate
   app_v.app_cfg.samplePeriod = SAMPLE_PERIOD;
   
   // create sample timer
   app_v.sampleTimer = OSTmrCreate(
                                      app_v.app_cfg.samplePeriod,       // dly
                                      app_v.app_cfg.samplePeriod,       // period
                                      OS_TMR_OPT_PERIODIC,              // opt
                                      (OS_TMR_CALLBACK)&sampleTimer_cb, // callback
                                      NULL,                             // callback_arg
                                      NULL,                             // pname
                                      &osErr                            // perr
                                      );
   ASSERT(osErr==OS_ERR_NONE);

   // start sample timer
   OSTmrStart(app_v.sampleTimer, &osErr);
   ASSERT (osErr == OS_ERR_NONE);
   
   while (1) {
	   
      // sample adc once per second 
      // achieve this by waiting for the sampleSem (1/s)
      OSSemPend(app_v.sampleSem, 0, &osErr);
      
      //activate lt2063 
      gpioWrite(SHDNB_OUT, IC_POWERED); 
      
      //and wait startup time
      OSTimeDly(LT2063_STARTUP);
      
      // read out sample
      spiTxBuffer[0] = 0x00; // LTC1864L doesn't require any configuration
      spiTxBuffer[1] = 0x00;
      
      dnErr = dn_ioctl(
                     DN_SPI_DEV_ID,
                     DN_IOCTL_SPI_TRANSFER,
                     &spiTransfer,
                     sizeof(spiTransfer)
      );
      if (dnErr != DN_ERR_NONE) {
            dnm_ucli_printf("Unable to communicate over SPI, err=%d\r\n",dnErr);
      }
      
      // if doing multiple samples per report, we'd store directly in the 
      memcpy(&app_v.report.adcData, spiRxBuffer, SPI_TRANSFER);
 
      //once we have copied successfully, post the report sem to start report task
      OSSemPost(app_v.reportSem);

#ifdef DEBUG     
      dnm_ucli_printf("sample=%d\r\n", ntohs(app_v.report.adcData));
#endif
   }     
}

//=========================== report task =====================================
//
//   This task:
//      Sends packets containing ADC and charge measurements to the manager. 
//      We are currently sending for each sample instead of aggregating.
//      Sets up the LT2063 and brings it in and out of shut down mode
//
static void reportTask(void* unused){
   dn_error_t                dnErr;
   INT8U                     osErr;
   
   //Wait for stack to print version
   OSTimeDly(ONE_SECOND);
   
   // wait for the loc_task to finish getting services
   dnm_ucli_printf("Waiting to join and get services...\r\n");
   OSSemPend(app_v.serviceSem, 0, &osErr);
   ASSERT(osErr==OS_ERR_NONE);
   dnm_ucli_printf("Services granted\r\n");

   while (1) {
      
      // wait for new event
      OSSemPend(app_v.reportSem, 0, &osErr);
      
      //removes power from the LT2063
      //comment out to never put the lt2063 into sleep mode
      gpioWrite(SHDNB_OUT, IC_DISABLED); 
      
      // send report
      dnErr = sendReport();
      if (dnErr != DN_ERR_NONE){
         dnm_ucli_printf("Error sending report!\r\n");
      }
   }
}

void sampleTimer_cb(void* pTimer, void *pArgs){
   OSSemPost(app_v.sampleSem);
}

//=========================== helpers =========================================
//===== send packet to manager containing measurements
// @return return error code from dnm_loc_sendtoCmd
INT8U sendReport(){
   dn_error_t      dnErr;
   INT8U           osErr;
   loc_sendtoNW_t* pkToSend;
   INT8U           rc;
   INT8U           pkBuf[sizeof(loc_sendtoNW_t)+sizeof(report_t)];
   report_t        payload;
   INT16U          cmdId;
   INT8U           count;
      
   // prepare packet to send
   pkToSend = (loc_sendtoNW_t*)pkBuf;
   pkToSend->locSendTo.socketId          = loc_getSocketId();
   pkToSend->locSendTo.destAddr          = DN_MGR_IPV6_MULTICAST_ADDR;
   pkToSend->locSendTo.destPort          = WKP_USER_1;
   pkToSend->locSendTo.serviceType       = DN_API_SERVICE_TYPE_BW;
   pkToSend->locSendTo.priority          = DN_API_PRIORITY_MED;
   pkToSend->locSendTo.packetId          = 0xFFFF; // 0xFFFF = no notification
   
   // insert payload into packet
   memcpy(pkToSend->locSendTo.payload, &app_v.report, sizeof(report_t));
	
   // send packet
   dnErr = dnm_loc_sendtoCmd(
                              pkToSend,
                              sizeof(report_t),
                              &rc
   );
   ASSERT(dnErr==DN_ERR_NONE);
	
   if (rc == DN_API_RC_OK) {
#ifdef DEBUG         
      dnm_ucli_printf("Report sent: adc = %d, charge = %d\r\n", ntohs(app_v.report.adcData), app_v.report.charge);  
#endif
      return(rc);
   } 
   else {
      return(dnErr);
   }
}

// Read an  LTC3335 register
// @param regAddr = address of register to read
//
// @return returns contents of register (1B)
INT8U i2cRead(INT8U regAddr){
   dn_error_t                   dnErr;
   INT8U                        i;
   INT8U                        writeBuffer[I2C_PAYLOAD_LENGTH];
   
   // prepare buffer
   memset(app_v.i2cBuffer,0,sizeof(app_v.i2cBuffer));
   memset(writeBuffer,0,sizeof(writeBuffer));
   
   writeBuffer[0] = regAddr;
   
   // initialize I2C communication parameters
   app_v.i2cTransfer.slaveAddress    = I2C_SLAVE_ADDR;
   app_v.i2cTransfer.writeBuf        = writeBuffer;
   app_v.i2cTransfer.readBuf         = app_v.i2cBuffer;
   app_v.i2cTransfer.writeLen        = 1;
   app_v.i2cTransfer.readLen         = 1; //sizeof(app_v.i2cBuffer);
   app_v.i2cTransfer.timeout         = 0xff;
   
   // initiate transaction
   dnErr = dn_ioctl(
                    DN_I2C_DEV_ID,
                    DN_IOCTL_I2C_TRANSFER,
                    &app_v.i2cTransfer,
                    sizeof(app_v.i2cTransfer)
                    );
   ASSERT(dnErr == DN_ERR_NONE);
   
   // print result of regiter read
//   dnm_ucli_printf("Read %02x from register %c\r\n",app_v.i2cBuffer[0], 0x40+regAddr);
   
   return(app_v.i2cBuffer[0]);
}

// Write an LTC3335 register
// @param regAddr = address of register to write
// @param value   = value to write in register
//
// @return returns RC from dn_ioctl (i2c transfer) command
INT8U i2cWrite(INT8U regAddr, INT8U value){
   dn_error_t                   dnErr;
   
   app_v.i2cBuffer[0] = regAddr;
   app_v.i2cBuffer[1] = value;
 
   // initialize I2C communication parameters
   app_v.i2cTransfer.slaveAddress    = I2C_SLAVE_ADDR;
   app_v.i2cTransfer.writeBuf        = app_v.i2cBuffer;
   app_v.i2cTransfer.readBuf         = NULL;
   app_v.i2cTransfer.writeLen        = sizeof(app_v.i2cBuffer);
   app_v.i2cTransfer.readLen         = 0;
   app_v.i2cTransfer.timeout         = 0x00;
   
   // initiate transaction
   dnErr = dn_ioctl(
                    DN_I2C_DEV_ID,
                    DN_IOCTL_I2C_TRANSFER,
                    &app_v.i2cTransfer,
                    sizeof(app_v.i2cTransfer)
                    );
   
   // print result of register write
   if (dnErr==DN_ERR_NONE) {
//      dnm_ucli_printf("Wrote %02x to register %c\r\n",value, 0x40+regAddr);
   } 
   else {
      dnm_ucli_printf("Unable to write over I2C, err=%d\r\n",dnErr);
   }
   
   return(dnErr);
}

// ===== GPIO commands ============

// Setup GPIO pin
// @param pin       = which pin to set
// @param mode      = input or output
// @param pull      = direction of pullup for inputs
// @param initLevel = initial level for outputs
//
// @return returns RC from dn_ioctl (pin set) command
dn_error_t gpioSetMode(INT8U pin, INT8U mode, INT8U pull, INT8U initLevel) {
   dn_error_t                   dnErr;
   dn_gpio_ioctl_cfg_in_t       gpioInCfg;
   dn_gpio_ioctl_cfg_out_t      gpioOutCfg; 
   
   dnErr = dn_open(
      pin,
      NULL,
      0
   );
   ASSERT(dnErr==DN_ERR_NONE);
   
   if (mode == DN_IOCTL_GPIO_CFG_OUTPUT){
     gpioOutCfg.initialLevel = initLevel;
     dnErr = dn_ioctl(
        pin,
        mode,
        &gpioOutCfg,
        sizeof(gpioOutCfg)
     );
     ASSERT(dnErr==DN_ERR_NONE);
   }
   
   if (mode == DN_IOCTL_GPIO_CFG_INPUT){
     gpioInCfg.pullMode = pull;
     dnErr = dn_ioctl(
        pin,
        mode,
        &gpioInCfg,
        sizeof(gpioInCfg)
     );
     ASSERT(dnErr==DN_ERR_NONE);
   }
  
   if ((mode != DN_IOCTL_GPIO_CFG_INPUT) && (mode != DN_IOCTL_GPIO_CFG_OUTPUT)){
      
      return(DN_ERR_INVALID);
   }
   else {
      
      return(DN_ERR_NONE);
   } 
}


// Write to GPIO output
// @param pin       = which pin to set
// @param value     = PIN_HIGH or PIN_LOW
//
void gpioWrite(INT8U pin, INT8U value) {
   dn_error_t  dnErr;
   
   dnErr = dn_write(
      pin,                      // device
      &value,                   // buf
      sizeof(value)             // len
   );
   
   ASSERT(dnErr==DN_ERR_NONE);
}

//=============================================================================
//=========================== install a kernel header =========================
//=============================================================================

/**
 A kernel header is a set of bytes prepended to the actual binary image of this
 application. Thus header is needed for your application to start running.
 */

DN_CREATE_EXE_HDR(DN_VENDOR_ID_NOT_SET,
                  DN_APP_ID_NOT_SET,
                  VER_MAJOR,
                  VER_MINOR,
                  VER_PATCH,
                  VER_BUILD);
