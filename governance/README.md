Example Governance Pool Contract
------------------------

## WARNING 

This code is meant for demonstration purposes only, it has _not_ been audited. 

Also this does not use wide math operations, so it _will_ fail if you tried to use it without serious modifications.

DO NOT USE ON MAINNET 


## Motivation



## Implementation



## Operations


## To run the example

Make sure [sandbox](https://github.com/algorand/sandbox) is installed and running with a private node configuration (`./sandbox up release`)

Clone this repository and cd to this directory

Create a virtual environment `python -m venv .venv`

Install python requirements `pip install -U -r requirements.txt`

Run the demo `python demo.py`

> Note: If it fails on the first time, you're probably on dev config and the asset balance lookups are weird for asset ids < 8, just try again