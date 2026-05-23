*** Settings *** 
Suite Setup     Setup 
Suite Teardown  Teardown 
Test Teardown   Test Teardown 
Resource        ${RENODEKEYWORDS} 

*** Keywords ***

Three Arguments
    [Arguments]    ${arg1}    ${arg2}    ${arg3}
    Log    1st argument: ${arg1}
    Log    2nd argument: ${arg2}
    Log    3rd argument: ${arg3}
            
Common Init
            ResetEmulation
            # Create the Machine
            Execute Command             mach create

Start Test  
            [Arguments]                 ${uart}
            # Connect the UART
            Create Terminal Tester      sysbus.${uart}
            Start Emulation
            Wait For Line On Uart       END        timeout=10

*** Test Cases *** 

leancom on stm32u5a5
            Common Init
            Execute Command             machine LoadPlatformDescription @${PWD_PATH}/target/stm32/stm32u5a5.repl
            Execute Command             sysbus LoadELF @${PWD_PATH}/build/build-nucleo-u5a5zj-q.cmake/leancom-basic.elf
            Start Test                  usart1

leancom on litex
            Skip
            Common Init 
            Execute Command             machine LoadPlatformDescription @${PWD_PATH}/target/litex/litex.repl
            Execute Command             sysbus LoadELF @${PWD_PATH}/build/build-litex.cmake/leancom-basic.elf
            Start Test                  uart