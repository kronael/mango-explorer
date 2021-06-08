# # ⚠ Warning
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
# LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
# NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# [🥭 Mango Markets](https://mango.markets/) support is available at:
#   [Docs](https://docs.mango.markets/)
#   [Discord](https://discord.gg/67jySBhxrg)
#   [Twitter](https://twitter.com/mangomarkets)
#   [Github](https://github.com/blockworks-foundation)
#   [Email](mailto:hello@blockworks.foundation)

import argparse
import logging
import os
import random
import time
import typing

from decimal import Decimal
from solana.publickey import PublicKey
from solana.rpc.api import Client
from solana.rpc.types import MemcmpOpts, RPCError, RPCResponse
from solana.rpc.commitment import Commitment, Single

from .constants import MangoConstants, SOL_DECIMAL_DIVISOR
from .token import TokenLookup


# # 🥭 Context
#
# ## Environment Variables
#
# It's possible to override the values in the `Context` variables provided. This can be easier than creating
# the `Context` in code or introducing dependencies and configuration.
#
# The following environment variables are read:
# * CLUSTER (defaults to: mainnet-beta)
# * CLUSTER_URL (defaults to URL for RPC server for CLUSTER defined in `ids.json`)
# * GROUP_NAME (defaults to: BTC_ETH_USDT)
#

default_cluster = os.environ.get("CLUSTER") or "mainnet-beta"
default_cluster_url = os.environ.get("CLUSTER_URL") or MangoConstants["cluster_urls"][default_cluster]

default_program_id = PublicKey(MangoConstants[default_cluster]["mango_program_id"])
default_dex_program_id = PublicKey(MangoConstants[default_cluster]["dex_program_id"])

default_group_name = os.environ.get("GROUP_NAME") or "BTC_ETH_USDT"
default_group_id = PublicKey(MangoConstants[default_cluster]["mango_groups"][default_group_name]["mango_group_pk"])


# The old program ID is used for the 3-token Group, but since the program ID is stored
# in ids.json per cluster, it's not currently possible to put it in that (shared) file.
#
# We keep it here and do some special processing with it.
#
_OLD_3_TOKEN_GROUP_ID = PublicKey("7pVYhpKUHw88neQHxgExSH6cerMZ1Axx1ALQP9sxtvQV")
_OLD_3_TOKEN_PROGRAM_ID = PublicKey("JD3bq9hGdy38PuWQ4h2YJpELmHVGPPfFSuFkpzAd9zfu")


# # 🥭 Context class
#
# A `Context` object to manage Solana connection and Mango configuration.
#

class Context:
    def __init__(self, cluster: str, cluster_url: str, program_id: PublicKey, dex_program_id: PublicKey,
                 group_name: str, group_id: PublicKey):
        configured_program_id = program_id
        if group_id == _OLD_3_TOKEN_GROUP_ID:
            configured_program_id = _OLD_3_TOKEN_PROGRAM_ID

        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.cluster: str = cluster
        self.cluster_url: str = cluster_url
        self.client: Client = Client(cluster_url)
        self.program_id: PublicKey = configured_program_id
        self.dex_program_id: PublicKey = dex_program_id
        self.group_name: str = group_name
        self.group_id: PublicKey = group_id
        self.commitment: Commitment = Single
        self.encoding: str = "base64"
        self.token_lookup: TokenLookup = TokenLookup.default_lookups()

        # kangda said in Discord: https://discord.com/channels/791995070613159966/836239696467591186/847816026245693451
        # "I think you are better off doing 4,8,16,20,30"
        self.retry_pauses: typing.List[Decimal] = [Decimal(4), Decimal(
            8), Decimal(16), Decimal(20), Decimal(30)]

    def fetch_sol_balance(self, account_public_key: PublicKey) -> Decimal:
        result = self.client.get_balance(account_public_key, commitment=self.commitment)
        value = Decimal(result["result"]["value"])
        return value / SOL_DECIMAL_DIVISOR

    def fetch_program_accounts_for_owner(self, program_id: PublicKey, owner: PublicKey):
        memcmp_opts = [
            MemcmpOpts(offset=40, bytes=str(owner)),
        ]

        return self.client.get_program_accounts(program_id, memcmp_opts=memcmp_opts, commitment=self.commitment, encoding=self.encoding)

    def unwrap_or_raise_exception(self, response: RPCResponse) -> typing.Any:
        if "error" in response:
            if response["error"] is str:
                message: str = typing.cast(str, response["error"])
                code: int = -1
            else:
                error: RPCError = typing.cast(RPCError, response["error"])
                message = error["message"]
                code = error["code"]
            raise Exception(
                f"Error response from server: '{message}', code: {code}")

        return response["result"]

    def unwrap_transaction_id_or_raise_exception(self, response: RPCResponse) -> str:
        return typing.cast(str, self.unwrap_or_raise_exception(response))

    def random_client_id(self) -> int:
        # 9223372036854775807 is sys.maxsize for 64-bit systems, with a bit_length of 63.
        # We explicitly want to use a max of 64-bits though, so we use the number instead of
        # sys.maxsize, which could be lower on 32-bit systems or higher on 128-bit systems.
        return random.randrange(9223372036854775807)

    @staticmethod
    def _lookup_name_by_address(address: PublicKey, collection: typing.Dict[str, str]) -> typing.Optional[str]:
        address_string = str(address)
        for stored_name, stored_address in collection.items():
            if stored_address == address_string:
                return stored_name
        return None

    @staticmethod
    def _lookup_address_by_name(name: str, collection: typing.Dict[str, str]) -> typing.Optional[PublicKey]:
        for stored_name, stored_address in collection.items():
            if stored_name == name:
                return PublicKey(stored_address)
        return None

    def lookup_group_name(self, group_address: PublicKey) -> str:
        for name, values in MangoConstants[self.cluster]["mango_groups"].items():
            if values["mango_group_pk"] == str(group_address):
                return name
        return "« Unknown Group »"

    def lookup_oracle_name(self, token_address: PublicKey) -> str:
        return Context._lookup_name_by_address(token_address, MangoConstants[self.cluster]["oracles"]) or "« Unknown Oracle »"

    def wait_for_confirmation(self, transaction_id: str, max_wait_in_seconds: int = 60) -> typing.Optional[typing.Dict]:
        self.logger.info(
            f"Waiting up to {max_wait_in_seconds} seconds for {transaction_id}.")
        for wait in range(0, max_wait_in_seconds):
            time.sleep(1)
            confirmed = default_context.client.get_confirmed_transaction(transaction_id)
            if confirmed["result"] is not None:
                self.logger.info(f"Confirmed after {wait} seconds.")
                return confirmed["result"]
        self.logger.info(f"Timed out after {wait} seconds waiting on transaction {transaction_id}.")
        return None

    def new_from_cluster(self, cluster: str) -> "Context":
        cluster_url = MangoConstants["cluster_urls"][cluster]
        program_id = PublicKey(MangoConstants[cluster]["mango_program_id"])
        dex_program_id = PublicKey(MangoConstants[cluster]["dex_program_id"])
        group_id = PublicKey(MangoConstants[cluster]["mango_groups"][self.group_name]["mango_group_pk"])

        return Context(cluster, cluster_url, program_id, dex_program_id, self.group_name, group_id)

    def new_from_cluster_url(self, cluster_url: str) -> "Context":
        return Context(self.cluster, cluster_url, self.program_id, self.dex_program_id, self.group_name, self.group_id)

    def new_from_group_name(self, group_name: str) -> "Context":
        group_id = PublicKey(MangoConstants[self.cluster]["mango_groups"][group_name]["mango_group_pk"])

        # If this Context had the old 3-token Group, we need to override it's program ID.
        program_id = self.program_id
        if self.group_id == _OLD_3_TOKEN_GROUP_ID:
            program_id = PublicKey(MangoConstants[self.cluster]["mango_program_id"])

        return Context(self.cluster, self.cluster_url, program_id, self.dex_program_id, group_name, group_id)

    def new_from_group_id(self, group_id: PublicKey) -> "Context":
        actual_group_name = "« Unknown Group »"
        group_id_str = str(group_id)
        for group_name in MangoConstants[self.cluster]["mango_groups"]:
            if MangoConstants[self.cluster]["mango_groups"][group_name]["mango_group_pk"] == group_id_str:
                actual_group_name = group_name
                break

        # If this Context had the old 3-token Group, we need to override it's program ID.
        program_id = self.program_id
        if self.group_id == _OLD_3_TOKEN_GROUP_ID:
            program_id = PublicKey(MangoConstants[self.cluster]["mango_program_id"])

        return Context(self.cluster, self.cluster_url, program_id, self.dex_program_id, actual_group_name, group_id)

    @staticmethod
    def from_command_line(cluster: str, cluster_url: str, program_id: PublicKey,
                          dex_program_id: PublicKey, group_name: str,
                          group_id: PublicKey) -> "Context":
        # Here we should have values for all our parameters (because they'll either be specified
        # on the command-line or will be the default_* value) but we may be in the situation where
        # a group name is specified but not a group ID, and in that case we want to look up the
        # group ID.
        #
        # In that situation, the group_name will not be default_group_name but the group_id will
        # still be default_group_id. In that situation we want to override what we were passed
        # as the group_id.
        if (group_name != default_group_name) and (group_id == default_group_id):
            group_id = PublicKey(MangoConstants[cluster]["mango_groups"][group_name]["mango_group_pk"])

        return Context(cluster, cluster_url, program_id, dex_program_id, group_name, group_id)

    @staticmethod
    def from_cluster_and_group_name(cluster: str, group_name: str) -> "Context":
        cluster_url = MangoConstants["cluster_urls"][cluster]
        program_id = PublicKey(MangoConstants[cluster]["mango_program_id"])
        dex_program_id = PublicKey(MangoConstants[cluster]["dex_program_id"])
        group_id = PublicKey(MangoConstants[cluster]["mango_groups"][group_name]["mango_group_pk"])

        return Context(cluster, cluster_url, program_id, dex_program_id, group_name, group_id)

    # Configuring a `Context` is a common operation for command-line programs and can involve a
    # lot of duplicate code.
    #
    # This function centralises some of it to ensure consistency and readability.
    #
    @staticmethod
    def add_context_command_line_parameters(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--cluster", type=str, default=default_cluster,
                            help="Solana RPC cluster name")
        parser.add_argument("--cluster-url", type=str, default=default_cluster_url,
                            help="Solana RPC cluster URL")
        parser.add_argument("--program-id", type=str, default=default_program_id,
                            help="Mango program ID/address")
        parser.add_argument("--dex-program-id", type=str, default=default_dex_program_id,
                            help="DEX program ID/address")
        parser.add_argument("--group-name", type=str, default=default_group_name,
                            help="Mango group name")
        parser.add_argument("--group-id", type=str, default=default_group_id,
                            help="Mango group ID/address")

    # This function is the converse of `add_context_command_line_parameters()` - it takes
    # an argument of parsed command-line parameters and expects to see the ones it added
    # to that collection in the `add_context_command_line_parameters()` call.
    #
    # It then uses those parameters to create a properly-configured `Context` object.
    #
    @staticmethod
    def from_context_command_line_parameters(args: argparse.Namespace) -> "Context":
        # Here we should have values for all our parameters (because they'll either be specified
        # on the command-line or will be the default_* value) but we may be in the situation where
        # a group name is specified but not a group ID, and in that case we want to look up the
        # group ID.
        #
        # In that situation, the group_name will not be default_group_name but the group_id will
        # still be default_group_id. In that situation we want to override what we were passed
        # as the group_id.
        group_id = args.group_id
        if (args.group_name != default_group_name) and (group_id == default_group_id):
            group_id = PublicKey(MangoConstants[args.cluster]["mango_groups"][args.group_name]["mango_group_pk"])

        program_id = args.program_id
        if group_id == PublicKey("7pVYhpKUHw88neQHxgExSH6cerMZ1Axx1ALQP9sxtvQV"):
            program_id = PublicKey("JD3bq9hGdy38PuWQ4h2YJpELmHVGPPfFSuFkpzAd9zfu")

        return Context(args.cluster, args.cluster_url, program_id, args.dex_program_id, args.group_name, group_id)

    def __str__(self) -> str:
        return f"""« Context:
    Cluster: {self.cluster}
    Cluster URL: {self.cluster_url}
    Program ID: {self.program_id}
    DEX Program ID: {self.dex_program_id}
    Group Name: {self.group_name}
    Group ID: {self.group_id}
»"""

    def __repr__(self) -> str:
        return f"{self}"


# ## Provided Configured Objects
#
# This file provides 3 `Context` objects, already configured and ready to use.
# * default_context (uses the environment variables specified above and `ids.json` file for configuration)
# * solana_context (uses the environment variables specified above and `ids.json` file for configuration but
#   explicitly sets the RPC server to be [Solana's mainnet RPC server](https://api.mainnet-beta.solana.com))
# * serum_context (uses the environment variables specified above and `ids.json` file for configuration but
#   explicitly sets the RPC server to be [Project Serum's mainnet RPC server](https://solana-api.projectserum.com))
# * rpcpool_context (uses the environment variables specified above and `ids.json` file for configuration but
#   explicitly sets the RPC server to be [RPCPool's free mainnet RPC server](https://api.rpcpool.com))
#
# Where notebooks depend on `default_context`, you can change this behaviour by adding an import line like:
# ```
# from Context import solana_context as default_context
# ```
# This can be useful if one of the RPC servers starts behaving oddly.

# ### default_context object
#
# A default `Context` object that connects to mainnet, to save having to create one all over the place. This
# `Context` uses the default values in the `ids.json` file, overridden by environment variables if they're set.


default_context = Context(default_cluster, default_cluster_url, default_program_id,
                          default_dex_program_id, default_group_name, default_group_id)


# ### solana_context object
#
# A `Context` object that connects to mainnet using Solana's own https://api.mainnet-beta.solana.com server.
# Apart from the RPC server URL, this `Context` uses the default values in the `ids.json` file, overridden by
# environment variables if they're set.

solana_context = default_context.new_from_cluster_url("https://api.mainnet-beta.solana.com")


# ### serum_context object
#
# A `Context` object that connects to mainnet using Serum's own https://solana-api.projectserum.com server.
# Apart from the RPC server URL, this `Context` uses the default values in the `ids.json` file, overridden by
# environment variables if they're set.

serum_context = default_context.new_from_cluster_url("https://solana-api.projectserum.com")


# ### rpcpool_context object
#
# A `Context` object that connects to mainnet using RPCPool's free https://api.rpcpool.com server.
# Apart from the RPC server URL, this `Context` uses the default values in the `ids.json` file, overridden by
# environment variables if they're set.

rpcpool_context = default_context.new_from_cluster_url("https://api.rpcpool.com")