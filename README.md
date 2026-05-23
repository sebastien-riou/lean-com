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