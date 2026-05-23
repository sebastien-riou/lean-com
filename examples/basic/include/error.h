#pragma once

#define CONST_OK 0
#define CONST_NOT_SET 0xFFFFFFFF

#define ERROR_PACKET_TOO_SHORT              0x00000001
#define ERROR_PACKET_TOO_LONG               0x00000002
#define INTERNAL_ERROR_RESPONSE_TOO_LONG    0x00000003
#define ERROR_UNSUPPORTED_CMD               0x00000004
#define INTERNAL_ERROR_CORRUPT              0x00000005
#define ERROR_CMD_TOO_SHORT                 0x00000006
#define ERROR_CMD_TOO_LONG                  0x00000007
#define ERROR_BUTTON_PRESSED                0x00000008
#define INTERNAL_ERROR_NVM_WRITE            0x00000009
#define ERROR_VERIFICATION_FAIL             0x0000000A
#define ERROR_NOT_IMPLEMENTED               0x0000000B

void throw_exception(uint32_t err_code);