Example Pool Contract
------------------------

**WARNING** DO NOT USE THIS YET IM POSITIVE THE MATH IS WRONG

This example is meant to illustrate how you may construct a contract that acts as a Token Pool.

## Motivation

Many DeFi applications are based on the concept of a Pool of liquidity.  

Users may provide tokens to the given pool and recieve some representation of their stake in the pool.  

The tokens held by the pool can be used for things like swaps or borrow/lending operations.


## Implementation

This example is a very simple AMM pool with no fees for swapping besides protocol fees. 

A single instance of this example is relevant for one pair of assets, termed A and B.  Asset A is defined as the Asset with the lower asset index.

A Pool Token is created to represent the liquidity providers share of the pool.


## Operations

The smart contract logic contains several operations:

*Mint*   - A Liquidity Provider sends some number of the A and B in a given ratio, recieves some number of Pool Tokens

*Burn*  - A Liquidity Provider sends some number of tokens in a given ratio to 

*Swap*      - A user sends some amount of asset A or B to swap for the other Asset in the pair and receives the other asset according to the current Ratio

scale = 1000
fee = 3

bootstrap:
    create token
    opt in
    initial liq token out = sqrt(amtA*amtB) - scale

Mint:
    liq token out = min(
        (assetA amt /assetA supply ) * issued_tokens
        (assetB amt /assetB supply) * issued_tokens
    )

Burn:
    assetA_out = assetA_supply * (burn_amount / issued_liquidity_tokens)
    assetB_out = assetB_supply * (burn_amount / issued_liquidity_tokens)

Swap (Fixed only):
    amount_out = (asset_in_amount * (scale-fee) * output_supply) / ((input_supply * scale) + (asset_in_amount * (scale-fee)))

