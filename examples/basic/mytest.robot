*** Comments ***
The firmware runs in Renode with its UART on a pseudo-terminal. The test plays the host by running the
leancom command line tool on that pseudo-terminal, and checks its output: the session described in the
README, on the STM32U5 once with the device started first and once with the host started first, then on
LiteX.

Run it from examples/basic: pipenv install (once), then pipenv run ./testit <preset>.
HOST_TIMEOUT limits the host session (default 60 s); pipenv run ./testit debug --variable
HOST_TIMEOUT:none removes the limit, for single-step debugging.


*** Settings ***
Suite Setup         Setup
Suite Teardown      Teardown
Test Teardown       Stop Host And Emulation
Resource            ${RENODEKEYWORDS}
Library             OperatingSystem
Library             Process


*** Variables ***
${PYTHON}           python3
${HOST_TIMEOUT}     60s
${PTY}              ${TEMPDIR}${/}leancom-test-uart
${EXPECTED}         hello world!\nhello world from printf over lean-com!\nFF EE DD CC


*** Keywords ***
Create Machine
    [Arguments]    ${platform}    ${build}    ${uart}
    Reset Emulation
    Execute Command    mach create
    Execute Command    machine LoadPlatformDescription @${PWD_PATH}/target/${platform}
    Execute Command    sysbus LoadELF @${PWD_PATH}/build/${build}/leancom-basic.elf
    Execute Command    emulation CreateUartPtyTerminal "term" "${PTY}" forceCreate=true
    Execute Command    connector Connect sysbus.${uart} term

Start Host
    Set Test Variable    ${HOST_LOG}    ${OUTPUT_DIR}${/}${TEST_NAME}.host.log
    ${host}=    Start Process    ${PYTHON}    -m    leancom    --log-level    DEBUG    ${PTY}    tx00112233    rx4
    ...    stderr=${HOST_LOG}
    RETURN    ${host}

Wait Until Host Sent Its Magic
    [Arguments]    ${host}
    WHILE    True    limit=NONE
        ${log}=    Get File    ${HOST_LOG}
        IF    'sync: tx MAGIC' in $log    BREAK
        ${running}=    Is Process Running    ${host}
        IF    not $running    Fail    leancom exited before sending its magic:\n${log}
        Sleep    0.1s
    END

Host Output Should Be The README Session
    [Arguments]    ${host}
    ${result}=    Wait For Process    ${host}    timeout=${HOST_TIMEOUT}    on_timeout=kill
    Should Be Equal As Integers    ${result.rc}    0    leancom failed:\n${result.stderr}    values=False
    Should Be Equal    ${result.stdout}    ${EXPECTED}

Stop Host And Emulation
    Terminate All Processes    kill=True
    Test Teardown


*** Test Cases ***
Device starts first on stm32u5a5
    Create Machine    stm32/stm32u5a5.repl    build-nucleo-u5a5zj-q.cmake    usart1
    Start Emulation
    ${host}=    Start Host
    Host Output Should Be The README Session    ${host}

Host starts first on stm32u5a5
    Create Machine    stm32/stm32u5a5.repl    build-nucleo-u5a5zj-q.cmake    usart1
    ${host}=    Start Host
    Wait Until Host Sent Its Magic    ${host}
    Start Emulation
    Host Output Should Be The README Session    ${host}

Device starts first on litex
    Create Machine    litex/litex.repl    build-litex.cmake    uart
    Start Emulation
    ${host}=    Start Host
    Host Output Should Be The README Session    ${host}
