#include <stdint.h>
#include <stdbool.h>

typedef struct
{
    uint32_t RxTx;
    uint32_t TxFull;
    uint32_t RxEmpty;
    uint32_t EventStatus;
    uint32_t EventPending;
    uint32_t EventEnable;
} UART;

const uint32_t TxEvent = 1;
const uint32_t RxEvent = 2;
volatile UART *const uart = (UART *)0x60001800;

void init(int argc, const char*argv[]){

}
void led1(bool on){

}
bool button(){
    return false;
}
void com_tx(const void *const buf, unsigned int size){
    const uint8_t*const buf8 = (const uint8_t*const)buf;
    for(unsigned int i=0;i<size;i++){
        //wait tx buffer ready
        while (uart->TxFull);

        //send the byte
        uart->RxTx = buf8[i];
    }
}
void com_rx(void *const buf, unsigned int size){
    uint8_t*const buf8 = (uint8_t*const)buf;
    for(unsigned int i=0;i<size;i++){
        //wait rx buffer not empty
        while (uart->RxEmpty);

        //store the byte
        buf8[i] = uart->RxTx;
    }
}
void delay_ms(unsigned int ms){

}