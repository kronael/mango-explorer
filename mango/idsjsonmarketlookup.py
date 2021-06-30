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

import enum
import typing

from decimal import Decimal
from solana.publickey import PublicKey

from .constants import MangoConstants
from .market import Market
from .marketlookup import MarketLookup
from .perpsmarket import PerpsMarket
from .spotmarket import SpotMarket
from .token import Token


class IdsJsonMarketType(enum.Enum):
    PERP = enum.auto()
    SPOT = enum.auto()

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self}"


# # 🥭 IdsJsonMarketLookup class
#
# This class allows us to look up market data from our ids.json configuration file.
#


class IdsJsonMarketLookup(MarketLookup):
    def __init__(self, cluster: str) -> None:
        super().__init__()
        self.cluster: str = cluster

    @staticmethod
    def _from_dict(market_type: IdsJsonMarketType, group_address: PublicKey, data: typing.Dict, tokens: typing.Sequence[Token], quote_symbol: str) -> Market:
        base_symbol = data["baseSymbol"]
        if tokens[0].symbol == quote_symbol and tokens[1].symbol == base_symbol:
            quote = tokens[0]
            base = tokens[1]
        elif tokens[0].symbol == base_symbol and tokens[1].symbol == quote_symbol:
            base = tokens[0]
            quote = tokens[1]
        else:
            raise Exception(f"Could not find base ('{base_symbol}') or quote symbol ('{quote_symbol}') in tokens.")

        address = PublicKey(data["publicKey"])
        if market_type == IdsJsonMarketType.PERP:
            return PerpsMarket(base, quote, address)
        else:
            return SpotMarket(base, quote, address, group_address)

    @staticmethod
    def _load_tokens(data: typing.Dict) -> typing.Sequence[Token]:
        tokens: typing.List[Token] = []
        for token_data in data:
            token = Token(token_data["symbol"], token_data["symbol"], PublicKey(
                token_data["mintKey"]), Decimal(token_data["decimals"]))
            tokens += [token]
        return tokens

    def find_by_symbol(self, symbol: str) -> typing.Optional[Market]:
        for group in MangoConstants["groups"]:
            if group["cluster"] == self.cluster:
                group_address: PublicKey = PublicKey(group["publicKey"])
                for market_data in group["perpMarkets"]:
                    if market_data["name"].upper() == symbol.upper():
                        tokens = IdsJsonMarketLookup._load_tokens(group["tokens"])
                        return IdsJsonMarketLookup._from_dict(IdsJsonMarketType.PERP, group_address, market_data, tokens, group["quoteSymbol"])
                for market_data in group["spotMarkets"]:
                    if market_data["name"].upper() == symbol.upper():
                        tokens = IdsJsonMarketLookup._load_tokens(group["tokens"])
                        return IdsJsonMarketLookup._from_dict(IdsJsonMarketType.SPOT, group_address, market_data, tokens, group["quoteSymbol"])
        return None

    def find_by_address(self, address: PublicKey) -> typing.Optional[Market]:
        for group in MangoConstants["groups"]:
            if group["cluster"] == self.cluster:
                group_address: PublicKey = PublicKey(group["publicKey"])
                for market_data in group["perpMarkets"]:
                    if market_data["key"] == str(address):
                        tokens = IdsJsonMarketLookup._load_tokens(group["tokens"])
                        return IdsJsonMarketLookup._from_dict(IdsJsonMarketType.PERP, group_address, market_data, tokens, group["quoteSymbol"])
                for market_data in group["spotMarkets"]:
                    if market_data["key"] == str(address):
                        tokens = IdsJsonMarketLookup._load_tokens(group["tokens"])
                        return IdsJsonMarketLookup._from_dict(IdsJsonMarketType.SPOT, group_address, market_data, tokens, group["quoteSymbol"])
        return None

    def all_markets(self) -> typing.Sequence[Market]:
        markets = []
        for group in MangoConstants["groups"]:
            if group["cluster"] == self.cluster:
                group_address: PublicKey = PublicKey(group["publicKey"])
                for market_data in group["perpMarkets"]:
                    tokens = IdsJsonMarketLookup._load_tokens(group["tokens"])
                    market = IdsJsonMarketLookup._from_dict(
                        IdsJsonMarketType.PERP, group_address, market_data, tokens, group["quoteSymbol"])
                    markets = [market]
                for market_data in group["spotMarkets"]:
                    tokens = IdsJsonMarketLookup._load_tokens(group["tokens"])
                    market = IdsJsonMarketLookup._from_dict(
                        IdsJsonMarketType.SPOT, group_address, market_data, tokens, group["quoteSymbol"])
                    markets = [market]

        return markets