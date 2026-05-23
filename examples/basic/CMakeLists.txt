cmake_minimum_required(VERSION 3.22)

project(leancom-basic)

# Sources
set(sources_SRCS
	${CMAKE_CURRENT_SOURCE_DIR}/source/main.c
)

# Include directories
set(include_c_DIRS
	${CMAKE_CURRENT_SOURCE_DIR}/include
)

# libs
set(link_DIRS

)

set(link_LIBS

)

include("cmake/generic_binary.cmake")

include(CTest)
add_test(NAME leancom-basic
					COMMAND leancom-basic)

