#include <stdint.h>
#include <stdbool.h>
#include <setjmp.h>
#include <string.h>
#include "error.h"
#include "util.h"
#include "leancom.h"

//Application level HAL
void init(int argc, const char*argv[]);
void led1(bool on);
bool button();
void com_tx(const void *const buf, unsigned int size);
void com_rx(void *const buf, unsigned int size);
void delay_ms(unsigned int ms);
//Application


static jmp_buf exception_ctx;
void throw_exception(uint32_t err_code){
  longjmp(exception_ctx,err_code);
}


void _leancom_tx(const void *const buf, unsigned int size){
  com_tx(buf, size);
}
void _leancom_rx(void *const buf, unsigned int size){
  com_rx(buf, size);
}
void _leancom_error_handler(uint32_t err_code){
  throw_exception(err_code);
}

#if HAS_PRINTF
#include <stdio.h>
int __io_putchar(int ch){
	leancom_putchar(ch);
	return ch;
}
#endif

#include "ui.h"
const char*version = xstr(GIT_VERSION);


void exception_handler(uint32_t err_code){
  ui_wait_button();
}

volatile uint8_t mask = 0;
void basic_test(){
  leancom_synchronize();
  leancom_print("hello world!\n");
  #if HAS_PRINTF
  printf("hello world from printf over lean-com!\n");
  #endif
  uint8_t buf[4] = {0};
  leancom_rx_data(buf,sizeof(buf));
  for(unsigned int i=0;i<sizeof(buf);i++){
    buf[i] = ~buf[i];
  }
  leancom_tx_data(buf,sizeof(buf));
  leancom_print("basic_test done.\n");
}

int main(int argc, const char*argv[]){
  init(argc,argv);
  led1(1);
  uint32_t err_code=-1;
  if(0 == (err_code = setjmp(exception_ctx))){
    basic_test();
    err_code = 0;
    led1(0);
  } else {
    exception_handler(err_code);
  }
  if(0==err_code){
    while(1){ui_led1_blink_ms(5000,DUTY_CYCLE_50);}
  }else{
    ui_wait_button();
    led1(0);
    while(1);
  }
  return err_code;
}


