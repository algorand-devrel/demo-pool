Example Pool Contract
------------------------

## WARNING 

This code is meant for demonstration purposes only, it has _not_ been audited. Not to mention, I haven't even checked the math yet. 

DO NOT USE ON MAINNET 


## Motivation

This example is meant to illustrate how you may construct a contract that acts as a Token Pool.

Many DeFi applications are based on the concept of a Pool of liquidity.  

Users may provide tokens to the given pool and recieve some representation of their stake in the pool.  

The tokens held by the pool can be used for things like swaps or borrow/lending protocols.


## Implementation

This example is a very simple AMM composed of a single Smart Contract. 

An instance of this Contract specific to a hardcoded pair of assets, termed A and B. 

A number of Pool Tokens is minted to a Liqudity Provider when they deposit some amount of asset A and B. The Pool Token may be burned in exchange for a share of the pool comensurate with the number of tokens burned and balance of the assets.

A "Fixed" Swapping operation is allowed to convert some number of one token to the other token in the pool.


## Operations

The smart contract logic contains several operations:

*Bootstrap* - Create the Pool token, fund the app account with algos, opt into the assets

*Fund* - Intial funding for the pool of asset A and B. First issue of pool tokens returns a number of tokens according to:  
```
    sqrt(A_amt*B_amt) - scale 
```

*Mint* - A Liquidity Provider sends some number of the A and B in a given ratio, recieves some number of Pool Tokens according to: 
```
min(
    (A_amt/A_supply) * pool_issued,
    (B_amt/B_supply) * pool_issued
)
```

*Burn* - A Pool Token holder sends some number of Pool Tokens to recieve assets A and B according to:
```
    A_out = A_supply * (pool_amt / pool_issued)
    B_out = B_supply * (pool_amt / pool_issued)
```

*Swap* - A user sends some amount of asset A or B to swap for the other Asset in the pair and receives the other asset according to:
```
    out_amt = (in_amt * (scale-fee) * out_supply) / ((in_supply * scale) + (in_amt * (scale-fee)))
```


## To run the exampleo

Make sure [sandbox](https://github.com/algorand/sandbox) is installed and running with a private node configuration (`./sandbox up release`)

Create a virtual environment `python -m venv .venv`

Install python requirements `pip install -U -r requirements.txt`

Run the demo `python demo.py`

> Note: If it fails on the first time, you're probably on dev config and the asset balance lookups are weird for asset ids < 8, just try again