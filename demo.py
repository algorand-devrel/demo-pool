from algosdk import *
from algosdk.v2client import algod
from algosdk.v2client.models import DryrunSource, DryrunRequest
from algosdk.future.transaction import *
from sandbox import get_accounts
import base64
import os

token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
url = "http://localhost:4001"

client = algod.AlgodClient(token, url)

asset_a = 100
asset_b = 101

def demo():
    # Create acct
    addr, pk = get_accounts()[0]
    print("Using {}".format(addr))

    # Create app
    app_id = create_app(addr, pk)
    print("Created App with id: {}".format(app_id))

    app_addr = logic.get_application_address(app_id)
    print("Application Address: {}".format(app_addr))


    # Initialize Pool
    sp = client.suggested_params()
    txn_group = [
        get_app_call(addr, sp, app_id, ["init"]),
    ]
    signed_group = [txn.sign(pk) for txn in txn_group]
    txid = client.send_transactions(signed_group)
    print("Sending transaction for init: {}".format(txid))

    result = wait_for_confirmation(client, txid, 4)
    print(result)

    pool_token = result['created-asset']

    # Deposit to pool
    sp = client.suggested_params()
    txn_group = [
        get_app_call(addr, sp, app_id, ["deposit"]),
        get_asset_xfer(addr, sp, asset_a, app_addr, 1000),
        get_asset_xfer(addr, sp, asset_b, app_addr, 100),
    ]

    signed_group = [txn.sign(pk) for txn in assign_group_id(txn_group)]

    txid = client.send_transactions(signed_group)
    print("Sending grouped transaction for deposit: {}".format(txid))

    result = wait_for_confirmation(client, txid, 4)
    print(result)

    # withdraw from pool
    sp = client.suggested_params()
    txn_group = [
        get_app_call(addr, sp, app_id, ["withdraw"], [asset_a, asset_b]),
        get_asset_xfer(addr, sp, asset_a, pool_token, 1000),
    ]

    signed_group = [txn.sign(pk) for txn in assign_group_id(txn_group)]

    txid = client.send_transactions(signed_group)
    print("Sending grouped transaction for deposit: {}".format(txid))

    result = wait_for_confirmation(client, txid, 4)
    print(result)





def get_asset_xfer(addr, sp, asset_id, app_addr, amt):
    return AssetTransferTxn(addr, sp, app_addr, amt, asset_id)

def get_app_call(addr, sp, app_id):
    return ApplicationCallTxn(addr, sp, app_id, OnComplete.NoOpOC)


def create_app(addr, pk):
    # Get suggested params from network
    sp = client.suggested_params()

    path = os.path.dirname(os.path.abspath(__file__))

    # Read in approval teal source && compile
    approval = open(os.path.join(path, "approval.teal")).read()
    app_result = client.compile(approval)
    app_bytes = base64.b64decode(app_result["result"])

    # Read in clear teal source && compile
    clear = open(os.path.join(path, "clear.teal")).read()
    clear_result = client.compile(clear)
    clear_bytes = base64.b64decode(clear_result["result"])

    # We dont need no stinkin storage
    schema = StateSchema(0, 0)

    # Create the transaction
    create_txn = ApplicationCreateTxn(
        addr, sp, 0, app_bytes, clear_bytes, schema, schema
    )

    # Sign it
    signed_txn = create_txn.sign(pk)

    # Ship it
    txid = client.send_transaction(signed_txn)

    # Wait for the result so we can return the app id
    result = wait_for_confirmation(client, txid, 4)

    return result["application-index"]


if __name__ == "__main__":
    demo()
