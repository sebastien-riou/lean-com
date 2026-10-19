
include("${CMAKE_CURRENT_LIST_DIR}/../rv32ic.cmake")

set(linker_script_SRC ${CMAKE_CURRENT_SOURCE_DIR}/target/litex/litex_FLASH.ld)

set(target_SRCS 
	${CMAKE_CURRENT_SOURCE_DIR}/target/litex/startup.s
	${CMAKE_CURRENT_SOURCE_DIR}/target/litex/litex.c
)

set(target_include_c_DIRS 

)

set(linker_OPTS
    --specs=nosys.specs
    -ffreestanding -nostdlib
    -Wl,-Map=${CMAKE_PROJECT_NAME}.map
    -Wl,--start-group
    -Wl,--end-group
    -Wl,-z,max-page-size=8 # Allow good software remapping across address space (with proper GCC section making)
    -Wl,--print-memory-usage
)