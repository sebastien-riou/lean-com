#ifndef LEANCOM_H
#define LEANCOM_H
#include <stdint.h>
#include <string.h>
#include <stdbool.h>

#define COM_TX_REQ  	0x40
#define COM_PRINT 	 	0x80
#define COM_TO_HOST   	0x00
#define COM_TO_DEVICE	0xC0
#define COM_PACKET_MAX_DATA_SIZE 0x3F

// Functions that must be provided by the environment
void _leancom_tx(const void *const buf, unsigned int size);
void _leancom_rx(void *const buf, unsigned int size);
void _leancom_error_handler(uint32_t err_code);

// Optional: define LEANCOM_RX_FLUSH and provide this function to discard the bytes already received,
// without blocking (for example by resetting the UART FIFO). It is called once, before the handshake.
#ifdef LEANCOM_RX_FLUSH
void _leancom_rx_flush(void);
#endif

// internal low level functions
static uint8_t _leancom_rx8(void){
	uint8_t out;
	_leancom_rx(&out,1);
	return out;
}
static void _leancom_tx8(uint8_t c){
	_leancom_tx(&c,1);
}
static void _leancom_raise_error(uint32_t err_code){
    _leancom_error_handler(err_code);
    while(1);//_leancom_error_handler shall not return
}
static void _leancom_tx_packet(uint8_t packet_type, const uint8_t*data, unsigned int size){
	uint8_t header = packet_type | size;
	_leancom_tx8(header);
	if(size > COM_PACKET_MAX_DATA_SIZE){
		_leancom_raise_error(__LINE__);
	}
	if(COM_TX_REQ != packet_type){
		for(unsigned int i=0;i<size;i++){
			_leancom_tx8(data[i]);
		}
	}
}

static void _leancom_rx_packet(uint8_t*dst, unsigned int size){
	_leancom_tx_packet(COM_TX_REQ,0,size);
	uint8_t header = _leancom_rx8();
	uint8_t packet_type = header & 0xC0;
	if(COM_TO_DEVICE != packet_type){
		_leancom_raise_error(__LINE__);
	}
	uint8_t packet_size = header & COM_PACKET_MAX_DATA_SIZE;
	if(size != packet_size){
		_leancom_raise_error(__LINE__);
	}
	for(unsigned int i=0;i<size;i++){
		dst[i] = _leancom_rx8();
	}
}

// User level functions
static void leancom_print(const char*s){
	unsigned int size = strlen(s);
	if(size == 0){
		return; // nothing to send, and no empty packet
	}
	while(size > COM_PACKET_MAX_DATA_SIZE){
		_leancom_tx_packet(COM_PRINT,(const uint8_t*)s,COM_PACKET_MAX_DATA_SIZE);
		s += COM_PACKET_MAX_DATA_SIZE;
		size -= COM_PACKET_MAX_DATA_SIZE;
	}
	_leancom_tx_packet(COM_PRINT,(const uint8_t*)s,size);
}

//function to override standard putchar if user wants to use printf
static int leancom_putchar(int c){
	const uint8_t byte = (uint8_t)c; // whatever the endianness
	_leancom_tx_packet(COM_PRINT,&byte,1);
	return c;
}

static void leancom_tx_data(const void*data, uint32_t size){
	uint8_t*data8=(uint8_t*)data;
	if(size == 0){
		return; // nothing to send, and no empty packet
	}
	while(size > COM_PACKET_MAX_DATA_SIZE){
		_leancom_tx_packet(COM_TO_HOST,data8,COM_PACKET_MAX_DATA_SIZE);
		data8 += COM_PACKET_MAX_DATA_SIZE;
		size -= COM_PACKET_MAX_DATA_SIZE;
	}
	_leancom_tx_packet(COM_TO_HOST,data8,size);
}

static void leancom_rx_data(void*data, uint32_t size){
	uint8_t*data8=(uint8_t*)data;
	if(size == 0){
		return; // nothing to receive, and no request for 0 bytes
	}
	while(size > COM_PACKET_MAX_DATA_SIZE){
		_leancom_rx_packet(data8,COM_PACKET_MAX_DATA_SIZE);
		data8 += COM_PACKET_MAX_DATA_SIZE;
		size -= COM_PACKET_MAX_DATA_SIZE;
	}
	_leancom_rx_packet(data8,size);
}

// Synchronization frames, 8 bytes each; MAGIC and ACK carry a 2-byte session id after their 6-byte pattern
static const uint8_t _leancom_hello[8] = {0xDA, 0x42, 0x65, 0x83, 0x2B, 0xA0, 0xE6, 0xAA}; // device -> host
static const uint8_t _leancom_magic[6] = {0xBC, 0x02, 0x9D, 0x8A, 0xA7, 0x3F};             // host -> device
static const uint8_t _leancom_ack[6]   = {0x2B, 0xD7, 0x94, 0x6C, 0xE1, 0x38};             // device -> host
static const uint8_t _leancom_go[8]    = {0x93, 0x4A, 0xE8, 0x27, 0x5C, 0xB1, 0xF6, 0x0E}; // host -> device

// Shift the next received byte into the window of the last 8 bytes
static void _leancom_sync_rx(uint8_t *const window){
	memmove(window, window + 1, 7);
	window[7] = _leancom_rx8();
}

// Rendez-vous with the host: announce, wait for MAGIC and its session id, acknowledge, wait for GO.
// Either side may start first; stale bytes, bytes lost while a side was not listening and a host
// restarted at any moment are tolerated. See the protocol documentation.
static void leancom_synchronize(void){
	(void) leancom_print;
	(void) leancom_putchar;
	(void) leancom_tx_data;
	(void) leancom_rx_data;
#ifdef LEANCOM_RX_FLUSH
	_leancom_rx_flush();
#endif
	_leancom_tx(_leancom_hello, 8); // a host already waiting sends its magic again
	uint8_t window[8] = {0};
	uint8_t ack[8];
	memcpy(ack, _leancom_ack, 6);
	do { // wait for MAGIC and the session id, skipping stale bytes
		_leancom_sync_rx(window);
	} while(0 != memcmp(window, _leancom_magic, 6));
	memcpy(ack + 6, window + 6, 2); // the session id
	_leancom_tx(ack, 8);
	memset(window, 0, sizeof(window));
	while(1){ // wait for GO; surplus copies of the magic slide out
		_leancom_sync_rx(window);
		if(0 == memcmp(window, _leancom_go, 8)){
			break;
		}
		if((0 == memcmp(window, _leancom_magic, 6)) && (0 != memcmp(window + 6, ack + 6, 2))){
			memcpy(ack + 6, window + 6, 2); // a restarted host: new id, acknowledge it
			_leancom_tx(ack, 8);
		}
	}
}

#endif // LEANCOM_H
