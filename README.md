# lean-com
Library for communication between embedded system and host computer

Host side is a python package, target side is a C, header only, library.

It offers the following features:

- Rendez-vous: Synchronisation of host and target
- Data transfert: Bi-directional transfer of binary data
- Debug prints: Uni-directional transfer of strings (Target to Host) 


## Installation of Python package
- Choose a working directory
- If it does not have a pipenv yet: `touch Pipfile`
- `pipenv install git+https://github.com/sebastien-riou/lean-com.git`

It can be added to an existing Pipfile like that:
````
leancom = {git = "git+https://github.com/sebastien-riou/lean-com.git"}
````

Alternatively you can use this repo as a submodule.

## Development / test

### Build embedded code
````
cd examples/basic
./buildit nucleo-u5a5zj-q.cmake debug
````

### Run it
Launch renode using the VSCode launch 'Dbg Renode U5A5'.

### Connect to it
From top level directory: 
````
pipenv run python -m leancom.cli /tmp/leancom-uart tx00112233 rx4
````

Alternatively you can use the VSCode launch 'Python basic' to debug the python side.

You should get the following:
````
hello world!
hello world from printf over lean-com!
FF EE DD CC
````