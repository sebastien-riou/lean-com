// Native stand-in for a lean-com device, for the test suite.
//
// It uses the real header-only library (include/leancom.h) and talks to the host on stdin and stdout,
// which the tests connect to pipes or to a pseudo-terminal. Diagnostics go to stderr.
//
// Usage: device SCENARIO [garbage=N] [flush=1] [size=N]
//   garbage=N   send N bytes 0x55 before synchronizing (stale bytes on the host side)
//   flush=1     receive one byte, then discard the bytes already received, then synchronize
//               (needs LEANCOM_RX_FLUSH; the trigger byte lets a test put stale bytes in place first)
//   size=N      transfer size of the 'echo' scenario (default 200, max 4096)
//
// Exit codes: 0 scenario done, 2 usage error, 101 I/O error on stdin or stdout, 102 lean-com error.
//
// Manual build, from the top-level directory:
//   cc -std=c11 -Wall -Wextra -g -O0 -DLEANCOM_RX_FLUSH -I include -o build/device test/native/device.c

#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "leancom.h"

enum { EXIT_USAGE = 2, EXIT_IO = 101, EXIT_LEANCOM = 102 };

// Functions required by leancom.h: the data path uses read(2)/write(2) only, never stdio

void _leancom_tx(const void *const buf, unsigned int size){
  const uint8_t *p = buf;
  while(size > 0){
    ssize_t n = write(STDOUT_FILENO, p, size);
    if(n < 0){
      if(errno == EINTR) continue;
      fprintf(stderr, "device: write failed: %s\n", strerror(errno));
      exit(EXIT_IO);
    }
    p += n;
    size -= (unsigned int)n;
  }
}

void _leancom_rx(void *const buf, unsigned int size){
  uint8_t *p = buf;
  while(size > 0){
    ssize_t n = read(STDIN_FILENO, p, size);
    if(n < 0){
      if(errno == EINTR) continue;
      fprintf(stderr, "device: read failed: %s\n", strerror(errno));
      exit(EXIT_IO);
    }
    if(n == 0){
      fprintf(stderr, "device: end of input while waiting for %u byte(s)\n", size);
      exit(EXIT_IO);
    }
    p += n;
    size -= (unsigned int)n;
  }
}

void _leancom_error_handler(uint32_t err_code){
  fprintf(stderr, "device: leancom error at leancom.h:%u\n", (unsigned int)err_code);
  exit(EXIT_LEANCOM);
}

#ifdef LEANCOM_RX_FLUSH
// Discard the bytes already received, what a UART FIFO reset does on a device
void _leancom_rx_flush(void){
  struct pollfd pfd = {.fd = STDIN_FILENO, .events = POLLIN};
  uint8_t sink[64];
  while(poll(&pfd, 1, 0) > 0 && (pfd.revents & POLLIN)){
    if(read(STDIN_FILENO, sink, sizeof(sink)) <= 0) break;
  }
}
#endif

// Scenarios

static uint8_t buf[4096];

// The examples/basic application: greet, receive 4 bytes, send them back inverted
static void scenario_basic(bool with_printf){
  leancom_print("hello world!\n");
  if(with_printf){
    // what printf does when __io_putchar is leancom_putchar: one packet per character
    for(const char *s = "hello world from printf over lean-com!\n"; *s; s++){
      leancom_putchar(*s);
    }
  }
  uint8_t data[4] = {0};
  leancom_rx_data(data, sizeof(data));
  for(unsigned int i = 0; i < sizeof(data); i++){
    data[i] = ~data[i];
  }
  leancom_tx_data(data, sizeof(data));
  leancom_print("basic_test done.\n");
}

static void scenario_echo(unsigned int size){
  leancom_rx_data(buf, size);
  leancom_tx_data(buf, size);
}

// A print longer than a packet, then two lines of data
static void scenario_lines(void){
  leancom_print("0123456789012345678901234567890123456789012345678901234567890123456789\n");
  leancom_tx_data("line one\nline two\n", 18);
}

// Sends data before asking for any
static void scenario_sends_first(void){
  const uint8_t data[2] = {0x00, 0x11};
  leancom_tx_data(data, sizeof(data));
  leancom_rx_data(buf, 1);
}

// Zero-size transfers and an empty print, which put nothing on the wire, then one byte of data
static void scenario_zero_sizes(void){
  leancom_rx_data(buf, 0);
  leancom_tx_data(buf, 0);
  leancom_print("");
  const uint8_t data = 0x42;
  leancom_tx_data(&data, 1);
}

// ISSUES.md #4: a two-byte UTF-8 character split between two print packets, then one byte of data
static void scenario_print_utf8(void){
  char s[66];
  memset(s, 'a', 62);
  s[62] = (char)0xC3; // 'e acute' is C3 A9: C3 ends the first packet of 63 bytes
  s[63] = (char)0xA9;
  s[64] = '\n';
  s[65] = '\0';
  leancom_print(s);
  const uint8_t data = 0x42;
  leancom_tx_data(&data, 1);
}

// A device reset in the middle of the session: a new HELLO reaches the host, then the basic application
static void scenario_restart(void){
  leancom_print("hello world!\n");
  leancom_synchronize();
  scenario_basic(false);
}

// Same order as the switch in main()
static const char *const scenarios[] = {
  "basic", "basic_printf", "echo", "lines", "sends_first", "zero_sizes", "print_utf8", "restart",
};
static const unsigned int n_scenarios = sizeof(scenarios) / sizeof(scenarios[0]);

static void usage(void){
  fprintf(stderr, "usage: device SCENARIO [garbage=N] [flush=1] [size=N]\nscenarios:");
  for(unsigned int i = 0; i < n_scenarios; i++){
    fprintf(stderr, " %s", scenarios[i]);
  }
  fprintf(stderr, "\n");
}

int main(int argc, char *argv[]){
  if(argc < 2){
    usage();
    return EXIT_USAGE;
  }
  int scenario = -1;
  for(unsigned int i = 0; i < n_scenarios; i++){
    if(0 == strcmp(argv[1], scenarios[i])) scenario = (int)i;
  }
  if(scenario < 0){
    fprintf(stderr, "device: unknown scenario '%s'\n", argv[1]);
    usage();
    return EXIT_USAGE;
  }
  unsigned int garbage = 0, flush = 0, size = 200;
  for(int i = 2; i < argc; i++){
    if(1 == sscanf(argv[i], "garbage=%u", &garbage)) continue;
    if(1 == sscanf(argv[i], "flush=%u", &flush)) continue;
    if(1 == sscanf(argv[i], "size=%u", &size)) continue;
    fprintf(stderr, "device: invalid option '%s'\n", argv[i]);
    usage();
    return EXIT_USAGE;
  }
  if(size > sizeof(buf)){
    fprintf(stderr, "device: size=%u exceeds the %u-byte buffer\n", size, (unsigned int)sizeof(buf));
    return EXIT_USAGE;
  }
  if(flush){
#ifdef LEANCOM_RX_FLUSH
    (void)_leancom_rx8(); // the trigger byte: the stale bytes written with it are in place
    _leancom_rx_flush();
#else
    fprintf(stderr, "device: flush=1 needs a build with -DLEANCOM_RX_FLUSH\n");
    return EXIT_USAGE;
#endif
  }

  for(unsigned int i = 0; i < garbage; i++) _leancom_tx8(0x55);
  leancom_synchronize();

  switch(scenario){
    case 0: scenario_basic(false); break;
    case 1: scenario_basic(true); break;
    case 2: scenario_echo(size); break;
    case 3: scenario_lines(); break;
    case 4: scenario_sends_first(); break;
    case 5: scenario_zero_sizes(); break;
    case 6: scenario_print_utf8(); break;
    case 7: scenario_restart(); break;
  }
  return 0;
}
