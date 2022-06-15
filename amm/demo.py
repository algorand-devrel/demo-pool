import base64

from algosdk import *
from algosdk.atomic_transaction_composer import *
from algosdk.algod import AlgodClient
from algosdk.v2client import algod
from algosdk.future.transaction import *
from contract import build_program
from sandbox import get_accounts


token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
url = "http://localhost:4001"

client = algod.AlgodClient(token, url)

contract: abi.Contract


def demo():
    ###
    # Get Account from sandbox
    ###
    addr, sk = get_accounts()[0]
    signer = AccountTransactionSigner(sk)
    print("Using {}".format(addr))

    ###
    # Create assets as needed
    ###
    asset_a = create_asset(addr, sk, "A")
    print("Created asset a with id: {}".format(asset_a))

    asset_b = create_asset(addr, sk, "B")
    print("Created asset a with id: {}".format(asset_b))

    approval, clear, contract = build_program(asset_a, asset_b)

    # Create app
    app_id, app_addr = create_app(addr, sk, approval, clear)
    print("Created App with id: {} and address: {}".format(app_id, app_addr))

    ###
    # Bootstrap Pool
    ###
    sp = client.suggested_params()
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id,
        contract.get_method_by_name("bootstrap"),
        addr,
        sp,
        signer,
        [asset_a, asset_b],
    )
    result = atc.execute(client, 2)
    pool_token = result.abi_results[0].return_value
    print("Created Pool Token: {}".format(pool_token))

    ###
    # Opt addr into newly created Pool Token
    ###
    sp = client.suggested_params()
    atc = AtomicTransactionComposer()
    atc.add_transaction(
        TransactionWithSigner(
            txn=AssetTransferTxn(addr, sp, addr, 0, pool_token),
            signer=signer,
        )
    )
    atc.execute(client, 2)
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    ###
    # Fund Pool with initial liquidity
    ###
    sp = client.suggested_params()
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id,
        contract.get_method_by_name("fund"),
        addr,
        sp,
        signer,
        [
            TransactionWithSigner(
                txn=AssetTransferTxn(addr, sp, app_addr, 1000, asset_a), signer=signer
            ),
            TransactionWithSigner(
                txn=AssetTransferTxn(addr, sp, app_addr, 3000, asset_b), signer=signer
            ),
            pool_token,
            asset_a,
            asset_b,
        ],
    )

    atc.execute(client, 2)
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    ###
    # Mint pool tokens
    ###
    sp = client.suggested_params()
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id,
        contract.get_method_by_name("mint"),
        addr,
        sp,
        signer,
        [
            TransactionWithSigner(
                txn=AssetTransferTxn(addr, sp, app_addr, 100000, asset_a), signer=signer
            ),
            TransactionWithSigner(
                txn=AssetTransferTxn(addr, sp, app_addr, 1000, asset_b), signer=signer
            ),
            pool_token,
            asset_a,
            asset_b,
        ],
    )
    atc.execute(client, 2)
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    ###
    # Swap A for B
    ###
    sp = client.suggested_params()
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id,
        contract.get_method_by_name("swap"),
        addr,
        sp,
        signer,
        [
            TransactionWithSigner(
                txn=AssetTransferTxn(addr, sp, app_addr, 5, asset_a), signer=signer
            ),
            asset_a,
            asset_b,
        ],
    )
    atc.execute(client, 2)
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    ###
    # Swap B for A
    ###
    sp = client.suggested_params()
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id,
        contract.get_method_by_name("swap"),
        addr,
        sp,
        signer,
        [
            TransactionWithSigner(
                txn=AssetTransferTxn(addr, sp, app_addr, 5, asset_b), signer=signer
            ),
            asset_a,
            asset_b,
        ],
    )
    atc.execute(client, 2)
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)

    ###
    # Burn pool tokens
    ###
    sp = client.suggested_params()
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id,
        contract.get_method_by_name("burn"),
        addr,
        sp,
        signer,
        [
            TransactionWithSigner(
                txn=AssetTransferTxn(addr, sp, app_addr, 100, pool_token), signer=signer
            ),
            pool_token,
            asset_a,
            asset_b,
        ],
    )
    atc.execute(client, 2)
    print_balances(app_addr, addr, pool_token, asset_a, asset_b)


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


def create_app(addr, pk, approval_prog, clear_prog):
    # Read in approval teal source && compile
    app_result = client.compile(approval_prog)
    app_bytes = base64.b64decode(app_result["result"])

    # Read in clear teal source && compile
    clear_result = client.compile(clear_prog)
    clear_bytes = base64.b64decode(clear_result["result"])

    gschema = StateSchema(32, 32)
    lschema = StateSchema(0, 0)

    # Get suggested params from network
    sp = client.suggested_params()
    # Create app call
    atc = AtomicTransactionComposer()
    atc.add_transaction(
        TransactionWithSigner(
            txn=ApplicationCreateTxn(
                addr, sp, OnComplete.NoOpOC, app_bytes, clear_bytes, gschema, lschema
            ),
            signer=AccountTransactionSigner(pk),
        )
    )
    abi_result = atc.execute(client, 2)
    result = client.pending_transaction_info(abi_result.tx_ids[0])
    app_id = result["application-index"]
    app_addr = logic.get_application_address(app_id)

    # Fund App address
    sp = client.suggested_params()
    txid = client.send_transaction(PaymentTxn(addr, sp, app_addr, int(1e7)).sign(pk))
    wait_for_confirmation(client, txid, 4)

    return app_id, app_addr


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
