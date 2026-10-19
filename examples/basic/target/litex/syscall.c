// Minimal system calls for newlib on the LiteX target: printf goes to __io_putchar, which the
// application provides (examples/basic/source/main.c routes it to leancom_putchar). There is no
// file system and no input. Every function runs in bounded time.
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/stat.h>

extern int __io_putchar(int ch) __attribute__((weak));

int _write(int file, char *ptr, int len){
  if(0 == __io_putchar){
    errno = ENOSYS;
    return -1;
  }
  for(int i = 0; i < len; i++){
    __io_putchar(ptr[i]);
  }
  return len;
}

int _read(int file, char *ptr, int len){
  errno = ENOSYS;
  return -1;
}

int _close(int file){
  return -1;
}

// A character device that is a terminal: newlib then line-buffers stdout, so that each line of
// printf is sent when it ends instead of when the buffer is full
int _fstat(int file, struct stat *st){
  st->st_mode = S_IFCHR;
  return 0;
}

int _isatty(int file){
  return 1;
}

int _lseek(int file, int ptr, int dir){
  return 0;
}

// The heap starts at _end and stops _Min_Stack_Size bytes below _estack, see litex_FLASH.ld
void *_sbrk(ptrdiff_t incr){
  extern uint8_t _end;
  extern uint8_t _estack;
  extern uint8_t _Min_Stack_Size; // its address is the size reserved for the stack
  static uintptr_t heap_end = 0;
  if(0 == heap_end){
    heap_end = (uintptr_t)&_end;
  }
  const uintptr_t limit = (uintptr_t)&_estack - (uintptr_t)&_Min_Stack_Size;
  if(heap_end + (uintptr_t)incr > limit){
    errno = ENOMEM;
    return (void *)-1;
  }
  const uintptr_t prev = heap_end;
  heap_end += (uintptr_t)incr;
  return (void *)prev;
}
