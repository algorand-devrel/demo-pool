import base64
import os
import json

from algosdk import *
from algosdk.algod import AlgodClient
from algosdk.encoding import msgpack_encode
from algosdk.v2client import algod
from algosdk.future.transaction import *
from sandbox import get_accounts
from pyteal import compileTeal, Mode

from pool import get_approval_src, get_clear_src, seed_amount

token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
url = "http://localhost:4001"

client = algod.AlgodClient(token, url)


def demo(app_id=None):
    # Get Account from sandbox
    addr, sk = get_accounts()[0]
    print("Using {}".format(addr))

    if app_id == None:
        # Create app
        app_id = create_app(addr, sk)
        print("Created App with id: {}".format(app_id))
    else:
        update_app(app_id, addr, sk)
        print("Updated App id: {}".format(app_id))

    app_addr = logic.get_application_address(app_id)
    print("Application Address: {}".format(app_addr))

    # Bootstrap Pool
    sp = client.suggested_params()
    sp.fee = sp.min_fee * 2  # pay for the txn on behalf of app
    txn_group = assign_group_id(
        [
            PaymentTxn(addr, sp, app_addr, seed_amount),
            get_app_call(addr, sp, app_id, app_args=["boot"]),
        ]
    )
    result = send("boot", [txn.sign(sk) for txn in txn_group])

    # Get the pool token from the result
    pool_token = result["inner-txns"][0]["asset-index"]
    print("Created Pool Token: {}".format(pool_token))
    print_balances(app_addr, addr, pool_token)

    # Opt addr into newly created Pool Token
    sp = client.suggested_params()
    txn_group = assign_group_id([get_asset_xfer(addr, sp, pool_token, addr, 0)])
    send("optin", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token)

    # Join Governance Pool
    sp = client.suggested_params()
    sp.fee = sp.min_fee * 2  # pay for the txn
    txn_group = assign_group_id(
        [
            get_app_call(
                addr,
                sp,
                app_id,
                app_args=["join"],
                assets=[pool_token],
            ),
            PaymentTxn(addr, sp, app_addr, 100000),
        ]
    )

    # with open("txns.txn", "wb") as f:
    #    for txn in txn_group:
    #        f.write(base64.b64decode(encoding.msgpack_encode(txn)))

    send("join", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token)

    # Vote in governance
    sp = client.suggested_params()
    sp.fee = sp.min_fee * 2  # pay for the txn
    txn_group = assign_group_id(
        # TODO: need to actually generate the vote payload and pass the governance address
        [
            get_app_call(
                addr,
                sp,
                app_id,
                app_args=["vote", json.dumps({"vote": "a"})],
                accounts=["57QZ4S7YHTWPRAM3DQ2MLNSVLAQB7DTK4D7SUNRIEFMRGOU7DMYFGF55BY"],
            )
        ]
    )
    send("vote", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token)

    # Exit governance
    sp = client.suggested_params()
    sp.fee = sp.min_fee * 2  # pay for the txn
    txn_group = assign_group_id(
        [
            get_app_call(addr, sp, app_id, ["exit"], [pool_token]),
            get_asset_xfer(addr, sp, pool_token, app_addr, 1000),
        ]
    )
    send("exit", [txn.sign(sk) for txn in txn_group])
    print_balances(app_addr, addr, pool_token)


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


def create_app(addr, pk):
    # Read in approval teal source && compile
    app_result = client.compile(get_approval_src(lock_start=100, lock_stop=110))
    app_bytes = base64.b64decode(app_result["result"])

    # Read in clear teal source && compile
    clear_result = client.compile(get_clear_src())
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


def update_app(id, addr, sk):
    # Read in approval teal source && compile
    app_result = client.compile(get_approval_src(lock_start=100, lock_stop=110))
    app_bytes = base64.b64decode(app_result["result"])

    # Read in clear teal source && compile
    clear_result = client.compile(get_clear_src())
    clear_bytes = base64.b64decode(clear_result["result"])

    # Get suggested params from network
    sp = client.suggested_params()
    # Create the transaction
    update_txn = ApplicationUpdateTxn(addr, sp, id, app_bytes, clear_bytes)
    # Sign it
    signed_txn = update_txn.sign(sk)
    # Ship it
    txid = client.send_transaction(signed_txn)

    # Wait for the result so we can return the app id
    return wait_for_confirmation(client, txid, 4)


def send(name, signed_group):
    print("Sending Transaction for {}".format(name))
    client.send_transactions(signed_group)
    # return the result for the last txid
    return wait_for_confirmation(client, signed_group[-1].get_txid(), 4)


def print_balances(app: str, addr: str, pool: int):
    appbal = client.account_info(app)
    print("App: ")
    print("\tAlgo Balance {}".format(appbal["amount"]))
    for asset in appbal["assets"]:
        if asset["asset-id"] == pool:
            print("\tPool Balance {}".format(asset["amount"]))

    addrbal = client.account_info(addr)
    print("Participant: ")
    print("\tAlgo Balance {}".format(addrbal["amount"]))
    for asset in addrbal["assets"]:
        if asset["asset-id"] == pool:
            print("\tPool Balance {}".format(asset["amount"]))


if __name__ == "__main__":
    demo()
