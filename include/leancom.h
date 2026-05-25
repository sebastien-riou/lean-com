
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

// internal low level functions
uint8_t _leancom_rx8(){
	uint8_t out;
	_leancom_rx(&out,1);
	return out;
}
void _leancom_tx8(uint8_t c){
	_leancom_tx(&c,1);
}
void _leancom_raise_error(uint32_t err_code){
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
	while(size > COM_PACKET_MAX_DATA_SIZE){
		_leancom_tx_packet(COM_PRINT,(const uint8_t*)s,COM_PACKET_MAX_DATA_SIZE);
		s += COM_PACKET_MAX_DATA_SIZE;
		size -= COM_PACKET_MAX_DATA_SIZE;
	}
	_leancom_tx_packet(COM_PRINT,(const uint8_t*)s,size);
}

//function to override standard putchar if user wants to use printf
static int leancom_putchar(int c){
	_leancom_tx_packet(COM_PRINT,(const uint8_t*)&c,1);
	return c;
}

static void leancom_tx_data(const void*data, uint32_t size){
	uint8_t*data8=(uint8_t*)data;
	while(size > COM_PACKET_MAX_DATA_SIZE){
		_leancom_tx_packet(COM_TO_HOST,data8,COM_PACKET_MAX_DATA_SIZE);
		data8 += COM_PACKET_MAX_DATA_SIZE;
		size -= COM_PACKET_MAX_DATA_SIZE;
	}
	_leancom_tx_packet(COM_TO_HOST,data8,size);
}

static void leancom_rx_data(void*data, uint32_t size){
	uint8_t*data8=(uint8_t*)data;
	while(size > COM_PACKET_MAX_DATA_SIZE){
		_leancom_rx_packet(data8,COM_PACKET_MAX_DATA_SIZE);
		data8 += COM_PACKET_MAX_DATA_SIZE;
		size -= COM_PACKET_MAX_DATA_SIZE;
	}
	_leancom_rx_packet(data8,size);
}

static void leancom_synchronize(){
    (void) leancom_print;
    (void) leancom_tx_data;
    (void) leancom_rx_data;
    
	const uint64_t magic = 0xF2443FA78A9D02BC;
	const uint8_t*magic_bytes = (uint8_t*)&magic;
	unsigned int cnt = 0;
	while(cnt<8){
		_leancom_tx8(magic_bytes[cnt]);
		uint8_t r = _leancom_rx8();
		bool hit = r == magic_bytes[cnt];
		if((!hit) && (cnt<7)) {
			bool next_hit =  r == magic_bytes[cnt+1];
			if(next_hit){
				hit = 1;
				if(cnt + 1 == sizeof(magic) - 1){
					_leancom_tx8(magic_bytes[cnt+1]);
					break;
				}
			}
		}
		if(hit) {
			cnt++;
		} else {
			cnt = 0;
		}
	}
	while(1){
		_leancom_tx8(1);
		uint8_t r = _leancom_rx8();
		if(1 == r) {
			break;
		}
	}
}