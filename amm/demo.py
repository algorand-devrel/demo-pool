import base64

from algosdk import *
from algosdk.algod import AlgodClient
from algosdk.v2client import algod
from algosdk.future.transaction import *
from sandbox import get_accounts
from pool import approval, clear
from pyteal import compileTeal, Mode

token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
url = "http://localhost:4001"

client = algod.AlgodClient(token, url)


def demo(app_id=None, asset_a=None, asset_b=None):
    # Get Account from sandbox
    addr, sk = get_accounts()[0]
    print("Using {}".format(addr))

    if asset_a == None:
        asset_a = create_asset(addr, sk, "A")
        print("Created asset a with id: {}".format(asset_a))

    if asset_b == None:
        asset_b = create_asset(addr, sk, "B")
        print("Created asset a with id: {}".format(asset_b))

    if app_id == None:
        # Create app
        app_id = create_app(addr, sk, asset_a, asset_b)
        print("Created App with id: {}".format(app_id))

    app_addr = logic.get_application_address(app_id)
    print("Application Address: {}".format(app_addr))

    # If this is a new contract, we should fund it with algos
    fund_if_needed(client, addr, sk, app_addr)

    # Bootstrap Pool
    sp = client.suggested_params()
    txn_group = assign_group_id(
        [
            get_app_call(
                addr, sp, app_id, app_args=["boot"], assets=[asset_a, asset_b]
            ),
        ]
    )
    result = send("boot", [txn.sign(sk) for txn in txn_group])
    pool_token = result["inner-txns"][0]["asset-index"]

    print("Created Pool Token: {}".format(pool_token))

    # Opt addr into newly created Pool Token
    sp = client.suggested_params()
    txn_group = assign_group_id(
        [
            get_asset_xfer(addr, sp, pool_token, addr, 0),
        ]
    )
    send("optin", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    # Fund Pool with initial liquidity
    sp = client.suggested_params()
    txn_group = assign_group_id(
        [
            get_app_call(
                addr,
                sp,
                app_id,
                app_args=["fund"],
                assets=[asset_a, asset_b, pool_token],
            ),
            AssetTransferTxn(addr, sp, app_addr, 1000, asset_a),
            AssetTransferTxn(addr, sp, app_addr, 3000, asset_b),
        ]
    )
    send("fund", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    # Mint liquidity tokens
    sp = client.suggested_params()
    txn_group = assign_group_id(
        [
            get_app_call(
                addr,
                sp,
                app_id,
                app_args=["mint"],
                assets=[asset_a, asset_b, pool_token],
            ),
            get_asset_xfer(addr, sp, asset_a, app_addr, 100000),
            get_asset_xfer(addr, sp, asset_b, app_addr, 10000),
        ]
    )

    send("mint", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    # Swap A for B
    sp = client.suggested_params()
    txn_group = assign_group_id(
        [
            get_app_call(addr, sp, app_id, ["swap"], [asset_a, asset_b]),
            get_asset_xfer(addr, sp, asset_a, app_addr, 5),
        ]
    )
    send("swap_a_b", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    # Swap B for A
    sp = client.suggested_params()
    txn_group = assign_group_id(
        [
            get_app_call(addr, sp, app_id, ["swap"], [asset_a, asset_b]),
            get_asset_xfer(addr, sp, asset_b, app_addr, 5),
        ]
    )
    send("swap_b_a", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    # Burn liq tokens
    sp = client.suggested_params()
    txn_group = assign_group_id(
        [
            get_app_call(addr, sp, app_id, ["burn"], [asset_a, asset_b, pool_token]),
            get_asset_xfer(addr, sp, pool_token, app_addr, 1000),
        ]
    )
    send("burn", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)


def get_asset_xfer(addr, sp, asset_id, app_addr, amt):
    return AssetTransferTxn(addr, sp, app_addr, amt, asset_id)


def get_app_call(addr, sp, app_id, app_args=[], assets=[], accounts=[]):
    return ApplicationCallTxn(
        addr,
        sp,
        app_id,
        OnComplete.NoOpOC,
        app_args=app_args,
        foreign_assets=assets,
        accounts=accounts,
    )


def create_asset(addr, pk, unitname):
    # Get suggested params from network
    sp = client.suggested_params()
    # Create the transaction
    create_txn = AssetCreateTxn(
        addr, sp, 1000000, 0, False, asset_name="asset", unit_name=unitname
    )
    # Ship it
    txid = client.send_transaction(create_txn.sign(pk))
    # Wait for the result so we can return the app id
    result = wait_for_confirmation(client, txid, 4)
    return result["asset-index"]


def create_app(addr, pk, a, b):
    # Read in approval teal source && compile
    approval_prog = compileTeal(approval(a, b), mode=Mode.Application, version=5)
    app_result = client.compile(approval_prog)
    app_bytes = base64.b64decode(app_result["result"])

    # Read in clear teal source && compile
    clear_prog = compileTeal(clear(), mode=Mode.Application, version=5)
    clear_result = client.compile(clear_prog)
    clear_bytes = base64.b64decode(clear_result["result"])

    gschema = StateSchema(32, 32)
    lschema = StateSchema(0, 0)

    # Get suggested params from network
    sp = client.suggested_params()
    # Create the transaction
    create_txn = ApplicationCreateTxn(
        addr, sp, 0, app_bytes, clear_bytes, gschema, lschema
    )

    # Sign it
    signed_txn = create_txn.sign(pk)

    # Ship it
    txid = client.send_transaction(signed_txn)

    # Wait for the result so we can return the app id
    result = wait_for_confirmation(client, txid, 4)

    return result["application-index"]


def fund_if_needed(client: AlgodClient, funder: str, pk: str, app: str):
    fund = False
    try:
        ai = client.account_info(app)
        fund = ai["amount"] < 1e7
    except:
        fund = True

    if fund:
        # Fund App address
        sp = client.suggested_params()
        txn_group = [PaymentTxn(funder, sp, app, 10000000)]
        return send("seed", [txn.sign(pk) for txn in txn_group])


def send(name, signed_group):
    print("Sending Transaction for {}".format(name))
    # write_dryrun(name, client, signed_group)
    txid = client.send_transactions(signed_group)
    return wait_for_confirmation(client, txid, 4)


def write_dryrun(name: str, client: AlgodClient, txns: List[SignedTransaction]):
    with open("dryruns/" + name + ".msgp", "wb") as f:
        drr = create_dryrun(client, txns)
        f.write(base64.b64decode(encoding.msgpack_encode(drr)))


def print_balances(app: str, addr: str, pool: int, a: int, b: int):
    appbal = client.account_info(app)
    print("App: ")
    for asset in appbal["assets"]:
        if asset["asset-id"] == pool:
            print("\tPool Balance {}".format(asset["amount"]))
        if asset["asset-id"] == a:
            print("\tAssetA Balance {}".format(asset["amount"]))
        if asset["asset-id"] == b:
            print("\tAssetB Balance {}".format(asset["amount"]))

    addrbal = client.account_info(addr)
    print("Participant: ")
    for asset in addrbal["assets"]:
        if asset["asset-id"] == pool:
            print("\tPool Balance {}".format(asset["amount"]))
        if asset["asset-id"] == a:
            print("\tAssetA Balance {}".format(asset["amount"]))
        if asset["asset-id"] == b:
            print("\tAssetB Balance {}".format(asset["amount"]))


if __name__ == "__main__":
    demo()